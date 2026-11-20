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
           "llenar_ancho", "traer_al_frente", "reemplazar_marcador", "borrar_slide", "caja_pt"]


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

    Regla de marca: se centra el contenido de cards bajo el encabezado, pero NO las cifras,
    las imágenes, las tablas ni las hojas de trabajo, que van arriba, pegadas al título.
    Por eso la función no hace nada si la slide tiene cifras o imágenes de contenido."""
    if any(f.name.startswith(("metric_", "photo_", "image_")) or getattr(f, "has_table", False) for f in s.shapes):
        return 0.0
    titulo = next((f for f in s.shapes if f.name.startswith("title")), None)
    bloque = [f for f in s.shapes if not _marca(f) and not f.name.startswith(("title", "subtitle", "kicker"))]
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


def borrar_slide(prs, numero: int) -> None:
    sld = prs.slides._sldIdLst[numero - 1]
    prs.part.drop_rel(sld.rId)
    prs.slides._sldIdLst.remove(sld)
