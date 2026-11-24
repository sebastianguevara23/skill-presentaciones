"""Ajustes probados para corregir slides con código (solo necesitan python-pptx y Pillow).

Uso desde un script de arreglos:

    import sys; sys.path.insert(0, "<carpeta de la skill>/scripts")
    from neo_skill.ajustes import *
    prs = abrir("Deck - NEO/v1.pptx")
    s = slide(prs, 3)
    rejilla(s, columnas=2)
    centrar_bloque(s)
    prs.save("Deck - NEO/v2.pptx")

Las medidas son pt del archivo final (lienzo de 1440 × 810 pt).
"""
from __future__ import annotations

from pathlib import Path

from pptx import Presentation

PT = 12700
ZONA_X, ZONA_W = 90, 1260          # zona de contenido en x (pt)
PIE = 692                          # borde inferior de la zona de contenido (pt)
AIRE_TITULO = 28                   # aire bajo el título (pt)
GAP = 12                           # separación entre cards (pt)

__all__ = ["PT", "abrir", "slide", "es_card", "unidades", "mover", "rejilla", "centrar_bloque",
           "llenar_ancho", "traer_al_frente", "reemplazar_marcador", "quitar_fondo_blanco", "borrar_slide",
           "caja_pt"]


def abrir(ruta: str | Path):
    return Presentation(str(ruta))


def slide(prs, numero: int):
    """Slide por número (1-based), como la nombra la persona."""
    return prs.slides[numero - 1]


def caja_pt(forma) -> tuple[float, float, float, float]:
    return forma.left / PT, forma.top / PT, forma.width / PT, forma.height / PT


def _marca(forma) -> bool:
    return forma.name.startswith("NEO_BRAND")


BASES = ("card", "item", "metric_card", "circle", "member_card")


def es_card(forma) -> bool:
    """La base de una unidad del motor: `card_3`, `item_6`, `metric_card_5`… (no sus piezas,
    como `card_text_4`, `card_header_4` o `item_number_7`)."""
    prefijo, _, numero = forma.name.rpartition("_")
    return numero.isdigit() and prefijo in BASES


def _dentro(forma, base) -> bool:
    cx, cy = forma.left + forma.width / 2, forma.top + forma.height / 2
    return base.left <= cx <= base.left + base.width and base.top <= cy <= base.top + base.height


def unidades(s) -> list[tuple]:
    """(base, piezas) de cada card de la slide, en orden de lectura. Las piezas son todo lo que
    cae dentro de la base: cabecera, texto, número, ícono."""
    bases = sorted((f for f in s.shapes if es_card(f)), key=lambda f: (round(f.top / PT / 20), f.left))
    return [(b, [f for f in s.shapes if f is not b and not es_card(f) and not _marca(f) and _dentro(f, b)])
            for b in bases]


def mover(forma, dx_pt: float = 0, dy_pt: float = 0) -> None:
    forma.left += int(dx_pt * PT)
    forma.top += int(dy_pt * PT)


def _caja(c) -> tuple[float, float, float, float]:
    """Caja (x, y, w, h) en pt de una forma o de una tupla ya en pt."""
    return caja_pt(c) if hasattr(c, "left") else tuple(float(v) for v in c)


def flecha_escuadra(s, desde, hasta, color: str = "2D5BFF", grosor_pt: float = 3, separacion_pt: float = 6):
    """Flecha en escuadra (forma libre ortogonal con punta) del borde derecho de `desde` a `hasta`.

    Receta de embudo: del borde derecho de cada paso al siguiente, cerca de lo que señala.
    `desde` y `hasta` son formas o cajas `(x, y, w, h)` en pt del archivo final. Sale del centro
    del borde derecho de `desde` y la punta (`a:tailEnd` triangular) queda a `separacion_pt` del
    destino. El trazado depende de dónde está `hasta`:

    - a la derecha y a la misma altura: recta horizontal hasta su borde izquierdo;
    - a la derecha y más arriba o más abajo: en Z hasta su borde izquierdo;
    - debajo o encima, con el centro a la derecha de la salida: en L hasta su borde de arriba
      (o de abajo);
    - debajo o encima y más a la izquierda (el paso siguiente de un embudo): sale a la derecha,
      baja (o sube) y vuelve hasta su borde derecho.

    Devuelve la forma.
    """
    from pptx.dml.color import RGBColor
    from pptx.oxml.ns import qn

    dx, dy, dw, dh = _caja(desde)
    hx, hy, hw, hh = _caja(hasta)
    sx, sy = dx + dw, dy + dh / 2
    hcx, hcy = hx + hw / 2, hy + hh / 2
    sep = separacion_pt
    if hx >= sx + 2 * sep and hy <= sy <= hy + hh:
        puntos = [(hx - sep, sy)]
    elif hx >= sx + 2 * sep:
        medio = (sx + hx) / 2
        puntos = [(medio, sy), (medio, hcy), (hx - sep, hcy)]
    elif hcx > sx + sep:
        puntos = [(hcx, sy), (hcx, hy - sep if hcy > sy else hy + hh + sep)]
    else:
        codo = max(sx, hx + hw) + max(3 * sep, 6 * grosor_pt)
        puntos = [(codo, sy), (codo, hcy), (hx + hw + sep, hcy)]
    b = s.shapes.build_freeform(int(sx * PT), int(sy * PT), scale=1.0)
    b.add_line_segments([(int(x * PT), int(y * PT)) for x, y in puntos], close=False)
    sh = b.convert_to_shape()
    sh.fill.background()
    sh.line.color.rgb = RGBColor.from_string(color.upper())
    sh.line.width = int(grosor_pt * PT)
    sh.shadow.inherit = False
    ln = sh.line._get_or_add_ln()
    # Orden del esquema en `a:ln`: relleno, guion, unión (miter), headEnd, tailEnd.
    ln.append(ln.makeelement(qn("a:miter"), {"lim": "800000"}))
    ln.append(ln.makeelement(qn("a:tailEnd"), {"type": "triangle", "w": "med", "len": "med"}))
    # Sin el estilo del tema (python-pptx deja effectRef 1: Google y LibreOffice lo dibujan).
    style = sh._element.find(qn("p:style"))
    if style is not None:
        sh._element.remove(style)
    sh.name = f"flecha_escuadra_{sh.shape_id}"
    return sh


__all__.append("flecha_escuadra")


def _colocar(base, piezas, x_pt: float, y_pt: float, ancho_pt: float | None = None) -> None:
    escala = (ancho_pt * PT / base.width) if ancho_pt else 1.0
    x0, y0 = base.left, base.top
    for f in [base, *piezas]:
        f.left = int(x_pt * PT + (f.left - x0) * escala)
        f.top = int(y_pt * PT + (f.top - y0))
        f.width = int(f.width * escala)


def _gap_actual(grupos) -> float:
    """La separación que ya dio el motor entre cards vecinas de una fila (o GAP si no hay)."""
    huecos = []
    orden = sorted(grupos, key=lambda g: (round(g[0].top / PT / 20), g[0].left))
    for (a, _), (b, _) in zip(orden, orden[1:]):
        if round(a.top / PT / 20) == round(b.top / PT / 20):
            huecos.append((b.left - a.left - a.width) / PT)
    huecos = sorted(h for h in huecos if h > 0)
    return huecos[len(huecos) // 2] if huecos else GAP


def rejilla(s, columnas: int, gap: float | None = None, x: float = ZONA_X, ancho_total: float = ZONA_W) -> None:
    """Reacomoda las cards en `columnas` columnas que llenan la zona (3+1 → 2×2, por ejemplo),
    con la misma separación que dio el motor. Las cards de una fila quedan del alto de la más alta."""
    grupos = unidades(s)
    if not grupos:
        return
    gap = _gap_actual(grupos) if gap is None else gap
    ancho = (ancho_total - gap * (columnas - 1)) / columnas
    alto = max(b.height for b, _ in grupos) / PT
    y0 = min(b.top for b, _ in grupos) / PT
    for k, (base, piezas) in enumerate(grupos):
        fila, col = divmod(k, columnas)
        _colocar(base, piezas, x + col * (ancho + gap), y0 + fila * (alto + gap), ancho)
        base.height = int(alto * PT)


def llenar_ancho(s, gap: float | None = None) -> None:
    """Agranda las cards de cada fila para que la fila cubra todo el ancho de la zona, con la
    separación que ya tenían. Sirve cuando quedaron angostas con aire a los lados."""
    grupos = unidades(s)
    gap = _gap_actual(grupos) if gap is None else gap
    filas: dict[int, list] = {}
    for base, piezas in grupos:
        filas.setdefault(round(base.top / PT / 20), []).append((base, piezas))
    for fila in filas.values():
        fila.sort(key=lambda g: g[0].left)
        ancho = (ZONA_W - gap * (len(fila) - 1)) / len(fila)
        for k, (base, piezas) in enumerate(fila):
            _colocar(base, piezas, ZONA_X + k * (ancho + gap), base.top / PT, ancho)


def centrar_bloque(s, aire_titulo: float = AIRE_TITULO, pie: float = PIE) -> float:
    """Centra el contenido entre el título (+aire) y el pie. Devuelve el desplazamiento en pt.

    Regla de marca (D4, 0.2.0): se centran en vertical las cards, las tablas, las matrices y
    el bloque imagen + texto. NO las cifras (`metric_`) ni las hojas de trabajo (renglones
    `writing_line`), que van arriba, pegadas al título: con ellas la función no hace nada.
    El encabezado, las notas del pie y la marca no se mueven."""
    if any(f.name.startswith(("metric_", "writing_line")) for f in s.shapes):
        return 0.0
    titulo = next((f for f in s.shapes if f.name.startswith("title")), None)
    bloque = [f for f in s.shapes
              if not _marca(f) and not f.name.startswith(("title", "subtitle", "kicker", "note"))]
    if not titulo or not bloque:
        return 0.0
    arriba = min(f.top for f in bloque) / PT
    abajo = max(f.top + f.height for f in bloque) / PT
    tope = (titulo.top + titulo.height) / PT + aire_titulo
    dy = (tope + pie) / 2 - (arriba + abajo) / 2
    if arriba + dy < tope:
        dy = tope - arriba
    for f in bloque:
        mover(f, dy_pt=dy)
    return dy


def traer_al_frente(s, forma) -> None:
    el = forma._element
    el.getparent().remove(el)
    s.shapes._spTree.append(el)


def reemplazar_marcador(s, foto: str | Path, texto: str = "Colocar imagen"):
    """Cambia un recuadro «Colocar imagen» por la foto, recortada para llenar sin deformar."""
    from PIL import Image

    marco = next((f for f in s.shapes if getattr(f, "has_text_frame", False) and texto in f.text_frame.text), None)
    if marco is None:
        raise ValueError(f"no hay un recuadro «{texto}» en esta slide")
    w, h = Image.open(foto).size
    pic = s.shapes.add_picture(str(foto), marco.left, marco.top, marco.width, marco.height)
    r_marco, r_foto = marco.width / marco.height, w / h
    if r_foto > r_marco:
        sobra = 1 - r_marco / r_foto
        pic.crop_left = pic.crop_right = sobra / 2
    else:
        sobra = 1 - r_foto / r_marco
        pic.crop_top = pic.crop_bottom = sobra / 2
    marco._element.getparent().remove(marco._element)
    return pic


def quitar_fondo_blanco(s, forma, umbral: int = 245) -> bool:
    """Quita el fondo blanco de una captura, un gráfico o un diagrama (solo en slides claras).

    Usa el mismo relleno que el motor (`neo_refactor.bg_clear`): lo casi blanco conectado con
    el borde queda transparente. Reemplaza la imagen de la forma por el PNG limpio y conserva
    su posición, tamaño y recorte. Devuelve False si no correspondía (la imagen ya tenía
    transparencia, no había fondo que quitar o se iría más del 70 % de la imagen)."""
    import io
    import sys

    from pptx.oxml.ns import qn

    motor = Path(__file__).resolve().parents[2] / "motor"
    if str(motor) not in sys.path:
        sys.path.insert(0, str(motor))
    from neo_refactor.bg_clear import clear_white_background
    from PIL import Image

    blip = forma._element.find(".//" + qn("a:blip"))
    if blip is None or blip.get(qn("r:embed")) is None:
        raise ValueError(f"«{forma.name}» no es una imagen")
    viejo = blip.get(qn("r:embed"))
    with Image.open(io.BytesIO(s.part.related_part(viejo).blob)) as im:
        im.load()
        limpia = clear_white_background(im, umbral)
    if limpia is None:
        return False
    png = io.BytesIO()
    limpia.save(png, "PNG", optimize=True)
    png.seek(0)
    _parte, nuevo = s.part.get_or_add_image_part(png)
    blip.set(qn("r:embed"), nuevo)
    s.part.drop_rel(viejo)   # solo si ninguna otra forma de la slide la usa
    return True


def borrar_slide(prs, numero: int) -> None:
    sld = prs.slides._sldIdLst[numero - 1]
    prs.part.drop_rel(sld.rId)
    prs.slides._sldIdLst.remove(sld)
