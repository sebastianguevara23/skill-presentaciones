"""Arma `ejemplos/deck-de-prueba.pptx`: un deck sin la marca NEO para probar el rediseño.

Contenido inventado y neutro (no es material de cliente). Letra Calibri, colores sueltos y
cajas desalineadas: lo típico que llega para rediseñar.

Uso: uv run --with python-pptx==1.0.2 --with pillow==12.3.0 python tools/crear-deck-de-prueba.py
"""
from pathlib import Path

from PIL import Image, ImageDraw
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.util import Emu, Pt

RAIZ = Path(__file__).resolve().parents[1]
SALIDA = RAIZ / "ejemplos" / "deck-de-prueba.pptx"
GRIS, ROJO, VERDE = RGBColor(0x40, 0x40, 0x40), RGBColor(0xC0, 0x39, 0x2B), RGBColor(0x27, 0xAE, 0x60)


def caja(slide, x, y, w, h, texto, tam=18, negrita=False, color=GRIS, relleno=None):
    forma = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Emu(x), Emu(y), Emu(w), Emu(h)) if relleno \
        else slide.shapes.add_textbox(Emu(x), Emu(y), Emu(w), Emu(h))
    if relleno:
        forma.fill.solid()
        forma.fill.fore_color.rgb = relleno
        forma.line.fill.background()
    tf = forma.text_frame
    tf.word_wrap = True
    for i, linea in enumerate(texto.split("\n")):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        r = p.add_run()
        r.text = linea
        r.font.size, r.font.bold, r.font.name = Pt(tam), negrita, "Calibri"
        r.font.color.rgb = RGBColor(255, 255, 255) if relleno else color
    return forma


def imagen(ruta: Path) -> Path:
    img = Image.new("RGB", (800, 600), (210, 225, 240))
    d = ImageDraw.Draw(img)
    for i in range(0, 800, 40):
        d.line([(i, 600), (i + 300, 0)], fill=(180, 200, 225), width=12)
    d.ellipse([280, 180, 520, 420], fill=(90, 130, 190))
    img.save(ruta)
    return ruta


def main() -> None:
    prs = Presentation()
    prs.slide_width, prs.slide_height = Emu(12192000), Emu(6858000)
    vacio = prs.slide_layouts[6]
    E = 12192000 / 13.333  # EMU por pulgada aproximada para ubicar

    s = prs.slides.add_slide(vacio)
    caja(s, int(E), int(2.2 * E), int(11 * E), int(1.2 * E), "Plan de transformación digital 2027", 40, True, ROJO)
    caja(s, int(E), int(3.5 * E), int(11 * E), int(0.6 * E), "Propuesta para el comité de dirección", 20)

    s = prs.slides.add_slide(vacio)
    caja(s, int(0.7 * E), int(0.5 * E), int(11 * E), int(0.9 * E), "Agenda", 32, True, ROJO)
    caja(s, int(0.9 * E), int(1.6 * E), int(9 * E), int(4 * E),
         "1. Contexto del mercado\n2. Diagnóstico interno\n3. Iniciativas propuestas\n4. Inversión y retorno\n5. Próximos pasos", 22)

    s = prs.slides.add_slide(vacio)
    caja(s, int(0.6 * E), int(0.4 * E), int(11 * E), int(0.9 * E), "Tres frentes de trabajo", 30, True, ROJO)
    for i, (t, b) in enumerate([("Clientes", "Unificar los canales de atención y medir la satisfacción cada mes."),
                                ("Procesos", "Automatizar la aprobación de créditos y reducir el papel."),
                                ("Personas", "Formar a los equipos en datos y en herramientas de IA.")]):
        caja(s, int((0.7 + i * 4.1) * E), int((1.8 + (i % 2) * 0.25) * E), int(3.7 * E), int(2.8 * E),
             f"{t}\n{b}", 18, False, relleno=[ROJO, VERDE, GRIS][i])

    s = prs.slides.add_slide(vacio)
    caja(s, int(0.6 * E), int(0.4 * E), int(11 * E), int(0.9 * E), "Resultados del piloto", 30, True, ROJO)
    for i, (v, l) in enumerate([("38 %", "menos tiempo de respuesta"), ("2,4 M", "soles ahorrados al año"),
                                ("+12", "puntos de satisfacción")]):
        caja(s, int((0.8 + i * 4) * E), int(2.2 * E), int(3.5 * E), int(1.2 * E), v, 48, True, VERDE)
        caja(s, int((0.8 + i * 4) * E), int(3.4 * E), int(3.5 * E), int(0.8 * E), l, 18)

    s = prs.slides.add_slide(vacio)
    caja(s, int(0.6 * E), int(0.4 * E), int(11 * E), int(0.9 * E), "Lo que aprendimos", 30, True, ROJO)
    caja(s, int(0.7 * E), int(1.7 * E), int(6 * E), int(3.5 * E),
         "Los equipos adoptan más rápido cuando ven resultados en las primeras semanas. "
         "El acompañamiento semanal fue más útil que las capacitaciones largas.", 20)
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    ruta = imagen(RAIZ / "ejemplos" / "_foto.png")
    s.shapes.add_picture(str(ruta), Emu(int(7.3 * E)), Emu(int(1.7 * E)), Emu(int(5 * E)), Emu(int(3.75 * E)))

    s = prs.slides.add_slide(vacio)
    caja(s, int(E), int(2.6 * E), int(11 * E), int(1.2 * E), "¡Gracias!", 44, True, ROJO)

    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(SALIDA))
    ruta.unlink()
    print(SALIDA)


if __name__ == "__main__":
    main()
