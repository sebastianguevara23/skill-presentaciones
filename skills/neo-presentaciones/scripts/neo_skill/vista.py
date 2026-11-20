"""Imágenes para mirar: una PNG por slide, cuadrículas y antes/después.

Todo pasa por LibreOffice (el mismo render en cualquier equipo). Google Slides corta las
líneas un poco distinto: lo que queda justo aquí, revísalo también en Google.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import entorno

FONDO = (238, 241, 248)
NAVY = (0, 0, 51)


def _fuente(tamano: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    ruta = entorno.FONTS / "Montserrat-SemiBold.ttf"
    try:
        return ImageFont.truetype(str(ruta), tamano)
    except OSError:
        return ImageFont.load_default()


def render(pptx: Path, carpeta: Path, slides: list[int] | None = None, ancho: int = 1280,
           prefijo: str = "slide") -> list[Path]:
    """PNG de cada slide visible del PPTX (las ocultas también se dibujan: LibreOffice las exporta)."""
    with tempfile.TemporaryDirectory(prefix="neo-pdf-") as tmp:
        pdf = entorno.a_pdf(_visibles(pptx, Path(tmp)), Path(tmp))
        return entorno.pdf_a_png(pdf, carpeta, ancho=ancho, paginas=slides, prefijo=prefijo)


def _visibles(pptx: Path, tmp: Path) -> Path:
    """Copia con todas las slides visibles: LibreOffice salta las ocultas al exportar."""
    from pptx import Presentation

    prs = Presentation(str(pptx))
    ocultas = [s for s in prs.slides if s._element.get("show") == "0"]
    if not ocultas:
        return pptx
    for s in ocultas:
        s._element.set("show", "1")
    copia = tmp / pptx.name
    prs.save(str(copia))
    return copia


def cuadriculas(imagenes: list[Path], destino: Path, por_hoja: int = 6, columnas: int = 3,
                ancho_celda: int = 560, titulo: str = "") -> list[Path]:
    """Hojas de contacto: varias slides por imagen, con su número, para mirar de un vistazo."""
    hojas = []
    for n, inicio in enumerate(range(0, len(imagenes), por_hoja), 1):
        grupo = imagenes[inicio:inicio + por_hoja]
        celdas = [Image.open(p).convert("RGB") for p in grupo]
        alto_celda = int(ancho_celda * celdas[0].height / celdas[0].width)
        filas = (len(celdas) + columnas - 1) // columnas
        margen, cabeza = 16, 30
        hoja = Image.new("RGB", (columnas * (ancho_celda + margen) + margen,
                                 filas * (alto_celda + cabeza + margen) + margen), FONDO)
        draw, fuente = ImageDraw.Draw(hoja), _fuente(16)
        for k, (ruta, img) in enumerate(zip(grupo, celdas)):
            x = margen + (k % columnas) * (ancho_celda + margen)
            y = margen + (k // columnas) * (alto_celda + cabeza + margen)
            numero = ruta.stem.split("-")[-1].lstrip("0") or "0"
            draw.text((x, y + 4), f"{titulo} {numero}".strip(), fill=NAVY, font=fuente)
            hoja.paste(img.resize((ancho_celda, alto_celda), Image.LANCZOS), (x, y + cabeza))
        salida = destino / f"cuadricula-{n}.png"
        destino.mkdir(parents=True, exist_ok=True)
        hoja.save(salida)
        hojas.append(salida)
    return hojas


def antes_despues(antes: Path, despues: Path, destino: Path, etiqueta: str) -> Path:
    a, b = Image.open(antes).convert("RGB"), Image.open(despues).convert("RGB")
    ancho = 900
    a = a.resize((ancho, int(ancho * a.height / a.width)), Image.LANCZOS)
    b = b.resize((ancho, int(ancho * b.height / b.width)), Image.LANCZOS)
    margen, cabeza = 16, 34
    hoja = Image.new("RGB", (2 * ancho + 3 * margen, max(a.height, b.height) + cabeza + 2 * margen), FONDO)
    draw, fuente = ImageDraw.Draw(hoja), _fuente(18)
    draw.text((margen, margen), f"ANTES · {etiqueta}", fill=NAVY, font=fuente)
    draw.text((2 * margen + ancho, margen), "DESPUÉS", fill=NAVY, font=fuente)
    hoja.paste(a, (margen, margen + cabeza))
    hoja.paste(b, (2 * margen + ancho, margen + cabeza))
    destino.parent.mkdir(parents=True, exist_ok=True)
    hoja.save(destino)
    return destino
