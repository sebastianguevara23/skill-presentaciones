"""Las imágenes de la plantilla: lo que los layouts y masters dibujan detrás de las slides.

`leer` solo veía las formas de cada slide. En un deck de cliente el logo estaba
solo en `slideLayout1`, nadie lo vio y hubo que meterlo a mano en un `preparado.pptx`. Este
módulo extrae las imágenes de `slideLayouts` y `slideMasters` que se ven en al menos una slide
visible (con su recorte `a:srcRect` aplicado) y marca las que pueden ser el logo del cliente,
para pasarlas a `redisenar --logo-cliente RUTA`.
"""
from __future__ import annotations

import hashlib
import io
from pathlib import Path

from lxml import etree
from PIL import Image
from pptx import Presentation
from pptx.oxml.ns import qn

from neo_refactor.knowledge import ROOT, Knowledge
from neo_refactor.optimize import KNOWN_NEO_LOGO_MD5_PREFIXES

EMU_PT = 12700
# Una imagen que cubre el 15 % de la slide o más es un fondo, no un logo.
AREA_FONDO = 0.15
# «Cerca de un borde»: la imagen empieza o termina a menos de esta fracción del ancho (o del alto)
# de la slide. Y un logo no cruza más de la mitad de la slide: una banda de borde a borde es adorno.
BORDE = 0.2
LADO_MAX = 0.5


def _nombre(part) -> str:
    """`/ppt/slideLayouts/slideLayout1.xml` → `slideLayout1`."""
    return Path(str(part.partname)).stem


def _huellas_neo() -> tuple[str, ...]:
    """Prefijos md5 de los logos NEO conocidos: los de `tokens.yaml` (vigentes y antiguos), los del
    optimizador y los archivos de `assets/brand/`."""
    logos = Knowledge(ROOT).tokens["brand"]["known_logos"]
    archivos = sorted((ROOT / "assets" / "brand").glob("neo-logo*.png"))
    return (*logos["current"], *logos["old"], *KNOWN_NEO_LOGO_MD5_PREFIXES,
            *(hashlib.md5(p.read_bytes()).hexdigest() for p in archivos))


def _hijo(xfrm, ox: float, oy: float, sx: float, sy: float) -> tuple[float, float, float, float]:
    """Transformación de los hijos de un grupo (`a:xfrm` con `chOff`/`chExt`) al espacio de la slide."""
    off, ext = xfrm.find(qn("a:off")), xfrm.find(qn("a:ext"))
    ch_off, ch_ext = xfrm.find(qn("a:chOff")), xfrm.find(qn("a:chExt"))
    if None in (off, ext, ch_off, ch_ext):
        return ox, oy, sx, sy
    gx, gy, gw, gh = (int(off.get("x", 0)), int(off.get("y", 0)), int(ext.get("cx", 0)), int(ext.get("cy", 0)))
    cx, cy = int(ch_off.get("x", 0)), int(ch_off.get("y", 0))
    kx, ky = gw / (int(ch_ext.get("cx", 0)) or 1), gh / (int(ch_ext.get("cy", 0)) or 1)
    return ox + (gx - cx * kx) * sx, oy + (gy - cy * ky) * sy, sx * kx, sy * ky


def _imagenes_de(tree, t=(0.0, 0.0, 1.0, 1.0)):
    """(r:embed, srcRect, caja en pt) de cada `p:pic` del árbol, también dentro de grupos.

    Los placeholders de imagen del layout no se dibujan en la slide: se saltan."""
    ox, oy, sx, sy = t
    for el in tree:
        if not isinstance(el.tag, str):
            continue
        tag = etree.QName(el).localname
        if tag == "grpSp":
            xfrm = el.find(f"{qn('p:grpSpPr')}/{qn('a:xfrm')}")
            yield from _imagenes_de(el, _hijo(xfrm, *t) if xfrm is not None else t)
        elif tag == "pic":
            if el.find(f"{qn('p:nvPicPr')}/{qn('p:nvPr')}/{qn('p:ph')}") is not None:
                continue
            blip = el.find(f"{qn('p:blipFill')}/{qn('a:blip')}")
            xfrm = el.find(f"{qn('p:spPr')}/{qn('a:xfrm')}")
            if blip is None or not blip.get(qn("r:embed")) or xfrm is None:
                continue
            off, ext = xfrm.find(qn("a:off")), xfrm.find(qn("a:ext"))
            if off is None or ext is None:
                continue
            x, y = ox + int(off.get("x", 0)) * sx, oy + int(off.get("y", 0)) * sy
            w, h = int(ext.get("cx", 0)) * sx, int(ext.get("cy", 0)) * sy
            src = el.find(f"{qn('p:blipFill')}/{qn('a:srcRect')}")
            recorte = tuple(int(src.get(k, 0)) for k in "ltrb") if src is not None else (0, 0, 0, 0)
            yield blip.get(qn("r:embed")), recorte, [round(v / EMU_PT, 1) for v in (x, y, w, h)]


def _recortar(im: Image.Image, recorte: tuple[int, int, int, int]) -> Image.Image:
    """Aplica `a:srcRect` (l, t, r, b en milésimas de %: 100000 = 100 %). Un valor negativo agrega
    aire alrededor en PowerPoint: aquí se ignora y la imagen queda entera de ese lado."""
    if not any(recorte):
        return im
    l, t, r, b = (max(0, v) / 100000 for v in recorte)
    w, h = im.size
    caja = (round(w * l), round(h * t), round(w * (1 - r)), round(h * (1 - b)))
    if caja[2] - caja[0] < 1 or caja[3] - caja[1] < 1:
        return im
    return im.crop(caja)


def _candidata(caja: list[float], ancho: float, alto: float) -> bool:
    """¿Puede ser el logo del cliente? Chica (no es un fondo) y cerca de una esquina o un borde."""
    x, y, w, h = caja
    if w <= 0 or h <= 0 or w * h >= AREA_FONDO * ancho * alto:
        return False
    if w > LADO_MAX * ancho or h > LADO_MAX * alto:
        return False
    cerca_x = min(x, ancho - (x + w)) <= BORDE * ancho
    cerca_y = min(y, alto - (y + h)) <= BORDE * alto
    return cerca_x or cerca_y


def imagenes(deck: Path, out: Path) -> list[dict]:
    """Imágenes de layouts y masters que se ven en alguna slide visible, extraídas a
    `<out>/plantilla/<sha>.png`.

    Cada una: `sha` (md5[:10] de la imagen embebida, como en `parse_deck`), `archivo`, `origen`
    («slideLayout1», «slideMaster1»), `caja_pt` ([x, y, ancho, alto] en el lienzo del deck),
    `slides` (las slides visibles donde se ve), `es_neo` y `candidata_client_logo`.
    """
    prs = Presentation(str(deck))
    ancho, alto = prs.slide_width / EMU_PT, prs.slide_height / EMU_PT
    # Qué slides visibles muestran cada layout y cada master. `showMasterSp="0"` en la slide
    # esconde lo de su layout y su master; en el layout, esconde lo del master.
    usos: dict[str, tuple[object, list[int]]] = {}
    for n, slide in enumerate(prs.slides, 1):
        if slide._element.get("show") == "0" or slide._element.get("showMasterSp") == "0":
            continue
        layout = slide.slide_layout
        usos.setdefault(_nombre(layout.part), (layout.part, []))[1].append(n)
        if layout._element.get("showMasterSp") != "0":
            master = layout.slide_master
            usos.setdefault(_nombre(master.part), (master.part, []))[1].append(n)
    neo = _huellas_neo()
    carpeta = out / "plantilla"
    archivos: dict[tuple[str, tuple], Path] = {}
    encontradas = []
    # Layouts primero y en orden de número: el logo del cliente suele estar en el de portada.
    orden = sorted(usos, key=lambda k: (not k.startswith("slideLayout"), len(k), k))
    for origen in orden:
        part, slides = usos[origen]
        arbol = part._element.find(f"{qn('p:cSld')}/{qn('p:spTree')}")
        if arbol is None:
            continue
        for rid, recorte, caja in _imagenes_de(arbol):
            if rid not in part.rels:
                continue
            blob = part.related_part(rid).blob
            md5 = hashlib.md5(blob).hexdigest()
            sha = md5[:10]
            clave = (sha, recorte)
            if clave not in archivos:
                carpeta.mkdir(parents=True, exist_ok=True)
                iguales = sum(1 for s, _ in archivos if s == sha)
                stem = sha if not iguales else f"{sha}-{iguales + 1}"
                try:
                    with Image.open(io.BytesIO(blob)) as im:
                        im.load()
                        ruta = carpeta / f"{stem}.png"
                        _recortar(im, recorte).save(ruta)
                except (OSError, ValueError):
                    # EMF, WMF u otro formato que Pillow no abre: se deja tal cual.
                    ruta = carpeta / f"{stem}.{part.related_part(rid).partname.ext}"
                    ruta.write_bytes(blob)
                archivos[clave] = ruta
            es_neo = any(md5.startswith(p) for p in neo)
            encontradas.append({
                "sha": sha, "archivo": str(archivos[clave]), "origen": origen, "caja_pt": caja,
                "slides": sorted(slides), "es_neo": es_neo,
                "candidata_client_logo": not es_neo and _candidata(caja, ancho, alto),
            })
    return encontradas
