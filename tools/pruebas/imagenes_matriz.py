"""Pruebas de la 0.2.0: imagen protagonista, capturas sin fondo, matriz centrada y columna destacada.

Arma un deck sintético (una captura con margen blanco, una foto y una matriz), lo rediseña con
el motor (`neo.py leer` + `redisenar`) y mide el PPTX que sale:

- con captura, la imagen ocupa más del 50 % del ancho de la zona y el bloque imagen + texto
  queda centrado (en horizontal y en vertical), con imagen y texto alineados arriba;
- con foto, el comportamiento de siempre: 40 % del ancho, pegada al margen, texto hasta el margen;
- la captura sale con transparencia en la slide clara y sin tocar en la oscura y con
  `image_background: "keep"`; el blanco encerrado por el contenido no se toca; un diagrama casi
  todo blanco conserva su fondo y deja el aviso `image_background_kept`;
- la matriz queda centrada en vertical y sus filas crecen hasta `row_target`;
- la columna destacada tiene la cabecera blue y las celdas blue_pale con alfa, y la auditoría
  de paleta (`_fill` de `audit/brand.py`, como `off_palette_shape`) las acepta.

Uso: uv run --with python-pptx==1.0.2 --with pillow==12.3.0 python tools/pruebas/imagenes_matriz.py
     [--salida CARPETA]   (deja ahí el deck, el plan y el rediseño para mirarlos)
Necesita uv, como la skill. Sale con 1 si algo falla.
"""
from __future__ import annotations

import io
import json
import random
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt

RAIZ = Path(__file__).resolve().parents[2]
SKILL = RAIZ / "skills" / "neo-presentaciones"
NEO = SKILL / "scripts" / "neo.py"
# Medidas lógicas del motor (lienzo de 720 × 405; el archivo final va al doble).
ZONA_X, ZONA_W, PIE = 45.0, 630.0, 350.0
GAP_IMAGEN = 14.0      # image_text.yaml → body_gap
GAP_MATRIZ = 10.0      # matrix.yaml → body_gap
TOL = 1.5
fallas: list[str] = []


def comprobar(condicion: bool, mensaje: str) -> None:
    print(("ok   " if condicion else "FALLA") + " " + mensaje)
    if not condicion:
        fallas.append(mensaje)


def neo(*args: str, cwd: Path) -> dict:
    proc = subprocess.run(["uv", "run", "--quiet", str(NEO), *args], capture_output=True, text=True, cwd=cwd)
    if proc.returncode != 0:
        print(proc.stdout[-1500:], proc.stderr[-1500:])
        raise SystemExit(f"neo.py {args[0]} falló con código {proc.returncode}")
    return json.loads(proc.stdout)


# ---------------------------------------------------------------- imágenes sintéticas

def captura(ruta: Path) -> None:
    """Un tablero con margen blanco: panel gris con borde, barras, renglones y una celda blanca
    encerrada por un borde (ese blanco no está conectado con el borde de la imagen)."""
    im = Image.new("RGB", (1600, 900), "white")
    d = ImageDraw.Draw(im)
    d.rectangle([80, 60, 1520, 840], fill=(236, 240, 248), outline=(40, 40, 70), width=4)
    for k, alto in enumerate((420, 300, 520, 380, 610, 450)):
        x = 160 + k * 130
        d.rectangle([x, 780 - alto, x + 80, 780], fill=(45, 91, 255))
    for k in range(7):
        d.rectangle([1000, 140 + k * 50, 1000 + 380 - k * 30, 160 + k * 50], fill=(0, 0, 51))
    d.rectangle([1000, 560, 1440, 780], fill="white", outline=(0, 0, 51), width=6)   # celda encerrada
    im.save(ruta)


def diagrama_vacio(ruta: Path) -> None:
    """Un diagrama casi todo blanco: quitarle el fondo se llevaría más del 70 % de la imagen."""
    im = Image.new("RGB", (1200, 800), "white")
    d = ImageDraw.Draw(im)
    d.ellipse([500, 300, 700, 500], outline=(0, 0, 51), width=8)
    d.line([300, 400, 500, 400], fill=(45, 91, 255), width=8)
    im.save(ruta)


def foto(ruta: Path) -> None:
    """Una «foto»: degradado con ruido (muchos colores, sin fondo blanco)."""
    rnd = random.Random(7)
    im = Image.new("RGB", (1200, 800))
    px = im.load()
    for y in range(800):
        for x in range(1200):
            px[x, y] = (min(255, x // 6 + rnd.randint(0, 40)), min(255, y // 5 + rnd.randint(0, 40)),
                        120 + rnd.randint(0, 60))
    im.save(ruta)


# ---------------------------------------------------------------- deck de entrada

def caja(s, x, y, w, h, *parrafos, size=18):
    tf = s.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h)).text_frame
    tf.word_wrap = True
    for k, texto in enumerate(parrafos):
        p = tf.paragraphs[0] if k == 0 else tf.add_paragraph()
        p.text = texto
        p.runs[0].font.size = Pt(size)


ANALISIS = ("Las ventas por búsqueda crecieron 18 % frente a septiembre y explican la mitad del alza.",
            "Redes sociales se mantuvo estable; el costo por clic bajó por tercera semana seguida.",
            "El correo sigue rezagado: conviene revisar la segmentación antes del cierre del trimestre.")
MATRIZ = [("Canal", "Clics", "Conversión", "Costo por clic"),
          ("Búsqueda", "12.400", "3,1 %", "USD 0,42"),
          ("Redes sociales", "8.950", "2,4 %", "USD 0,35"),
          ("Correo", "3.120", "1,2 %", "USD 0,18")]


def deck(ruta: Path, img_captura: Path, img_foto: Path, img_vacio: Path) -> None:
    prs = Presentation()
    prs.slide_width, prs.slide_height = Emu(12192000), Emu(6858000)
    blank = prs.slide_layouts[6]

    s = prs.slides.add_slide(blank)                                      # 1 portada
    caja(s, 0.8, 2.6, 11, 1.2, "Reporte mensual de prueba", size=40)
    caja(s, 0.8, 3.9, 11, 0.6, "Imágenes y matrices")

    for titulo, imagen in (("Ventas por canal en octubre", img_captura),   # 2 captura
                           ("Equipo en terreno", img_foto),                # 3 foto
                           ("Flujo de aprobación", img_vacio),             # 5 diagrama casi vacío
                           ("Detalle del tablero de ventas", img_captura)):  # 6 captura con su fondo
        if titulo.startswith("Flujo"):
            _matriz(prs.slides.add_slide(blank))                         # 4 matriz
        s = prs.slides.add_slide(blank)
        caja(s, 0.6, 0.4, 12, 0.8, titulo, size=28)
        s.shapes.add_picture(str(imagen), Inches(0.6), Inches(1.5), width=Inches(6.4))
        caja(s, 7.3, 1.5, 5.4, 4.5, *ANALISIS, size=16)
    prs.save(str(ruta))


def _matriz(s) -> None:
    caja(s, 0.6, 0.4, 12, 0.8, "Comparación de canales", size=28)
    xs, ws = (0.6, 3.6, 6.6, 9.6), (2.8, 2.8, 2.8, 2.8)
    for fila, celdas in enumerate(MATRIZ):
        for col, texto in enumerate(celdas):
            caja(s, xs[col], 1.6 + fila * 0.9, ws[col], 0.6, texto, size=16)


# ---------------------------------------------------------------- plan

def plan(lectura: dict) -> list[dict]:
    slides = {s["slide"]: s for s in lectura["slides"]}

    def ids(n):
        textos = {(e.get("parrafos") or [e.get("texto", "")])[0]: e["id"] for e in slides[n]["elementos"]
                  if e["tipo"] == "text"}
        imagenes = [e["id"] for e in slides[n]["elementos"] if e["tipo"] == "image"]
        return textos, imagenes

    def imagen_texto(n, clase, **extra):
        textos, imagenes = ids(n)
        titulo = next(t for t in textos if t not in ANALISIS)
        return {"slide": n, "family": "image_text_clients",
                "roles": {textos[titulo]: "title", textos[ANALISIS[0]]: "body", imagenes[0]: "image:1"},
                "asset_classes": {imagenes[0]: clase}, **extra}

    textos, _ = ids(1)
    portada = {"slide": 1, "family": "title_slide",
               "roles": {textos["Reporte mensual de prueba"]: "title", textos["Imágenes y matrices"]: "subtitle"}}
    textos, _ = ids(4)
    roles = {textos["Comparación de canales"]: "title"}
    for col, texto in enumerate(MATRIZ[0]):
        roles[textos[texto]] = "header"
    for fila, celdas in enumerate(MATRIZ[1:], 1):
        for texto in celdas:
            roles[textos[texto]] = f"row:{fila}"
    return [portada,
            imagen_texto(2, "screenshot"),
            imagen_texto(3, "photo"),
            {"slide": 4, "family": "comparison_matrix", "roles": roles, "highlight_column": 3},
            imagen_texto(5, "diagram"),
            imagen_texto(6, "screenshot", image_background="keep")]


# ---------------------------------------------------------------- medidas del resultado

class Medida:
    def __init__(self, prs):
        self.k = prs.slide_width / 12700 / 720      # pt finales por pt lógico

    def caja(self, forma) -> tuple[float, float, float, float]:
        return tuple(v / 12700 / self.k for v in (forma.left, forma.top, forma.width, forma.height))


def formas(slide_o_formas, *prefijos):
    """Formas del motor cuyo nombre empieza con un prefijo (sin la marca)."""
    todas = getattr(slide_o_formas, "shapes", slide_o_formas)
    return [f for f in todas if f.name.startswith(prefijos) and not f.name.startswith("NEO_BRAND")]


def imagen_de(forma) -> Image.Image:
    return Image.open(io.BytesIO(forma.image.blob))


def transparente(im: Image.Image) -> bool:
    if im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info):
        return im.convert("RGBA").getchannel("A").getextrema()[0] < 255
    return False


def relleno(forma) -> tuple[str | None, int | None]:
    """(color del relleno, alfa en milésimas de %) tal como queda en el XML."""
    solido = forma._element.spPr.find(qn("a:solidFill"))
    if solido is None or not len(solido):
        return None, None
    color = solido[0]
    alfa = color.find(qn("a:alpha"))
    return color.get("val"), (int(alfa.get("val")) if alfa is not None else None)


def bloque(m: Medida, piezas) -> tuple[float, float, float, float]:
    cajas = [m.caja(f) for f in piezas]
    izq, arr = min(c[0] for c in cajas), min(c[1] for c in cajas)
    der, aba = max(c[0] + c[2] for c in cajas), max(c[1] + c[3] for c in cajas)
    return izq, arr, der, aba


def probar_captura(prs, m: Medida, n: int) -> None:
    s = prs.slides[n - 1]
    pic = formas(s, "image_")[0]
    x, y, w, h = m.caja(pic)
    comprobar(w > 0.5 * ZONA_W, f"captura: la imagen ocupa {w:.0f} lógicos ({w / ZONA_W:.0%} de la zona de "
                                f"{ZONA_W:.0f}, {w / 720:.0%} de la slide); más del 50 % de la zona")
    textos, barra = formas(s, "body_"), formas(s, "accent_bar_")
    comprobar(bool(textos) and bool(barra), "captura: mensaje con su barra de acento")
    if not textos or not barra:
        return
    bx, by, bw, bh = m.caja(barra[0])
    comprobar(abs(by - y) <= 0.5 and abs(m.caja(textos[0])[1] - y) <= 0.5,
              "captura: imagen, barra y texto alineados arriba")
    alto_texto = max(m.caja(t)[1] + m.caja(t)[3] for t in textos) - min(m.caja(t)[1] for t in textos)
    comprobar(abs(bh - alto_texto) <= 1.0, f"captura: la barra mide lo que el texto ({bh:.1f} / {alto_texto:.1f})")
    ancho_texto = max(m.caja(t)[0] + m.caja(t)[2] for t in textos) - m.caja(textos[0])[0]
    comprobar(ancho_texto <= 250 + 0.5, f"captura: texto en una columna de 250 lógicos o menos ({ancho_texto:.0f})")
    izq, arr, der, aba = bloque(m, [pic, *textos, *barra])
    comprobar(abs((izq - ZONA_X) - (ZONA_X + ZONA_W - der)) <= TOL,
              f"captura: bloque centrado en horizontal (márgenes {izq - ZONA_X:.1f} y {ZONA_X + ZONA_W - der:.1f})")
    titulo = formas(s, "title_")[0]
    tope = m.caja(titulo)[1] + m.caja(titulo)[3] + GAP_IMAGEN
    esperado = tope + max(0.0, (PIE - tope - (aba - arr)) / 2)
    comprobar(abs(arr - esperado) <= TOL, f"captura: bloque centrado en vertical (arriba {arr:.1f}, esperado {esperado:.1f})")
    im = imagen_de(pic)
    comprobar(transparente(im), "captura: sale sin fondo blanco (con transparencia) en la slide clara")
    if transparente(im):
        rgba = im.convert("RGBA")
        W, H = rgba.size
        comprobar(rgba.getpixel((2, 2))[3] == 0 and rgba.getpixel((W // 2, H - 3))[3] == 0,
                  "captura: el margen blanco quedó transparente")
        celda = rgba.getpixel((round(W * 1220 / 1600), round(H * 670 / 900)))
        comprobar(celda[3] == 255 and min(celda[:3]) >= 245, "captura: el blanco encerrado por el contenido no se tocó")


def probar_foto(prs, m: Medida, n: int) -> None:
    s = prs.slides[n - 1]
    pic = formas(s, "image_")[0]
    x, y, w, h = m.caja(pic)
    comprobar(abs(x - ZONA_X) <= 0.5 and w <= 0.4 * ZONA_W + 0.5,
              f"foto: como siempre, pegada al margen y con el 40 % del ancho como máximo (x {x:.1f}, ancho {w:.0f})")
    textos = formas(s, "body_")
    if textos:
        tx, _ty, tw, _th = m.caja(textos[0])
        derecha = max(m.caja(t)[0] + m.caja(t)[2] for t in textos)
        comprobar(tx >= x + w + 22 - 0.5 and derecha <= ZONA_X + ZONA_W + 0.5 and tw > 300,
                  f"foto: el mensaje arranca junto a la imagen y llega hasta el margen (ancho {tw:.0f})")
    comprobar(not transparente(imagen_de(pic)), "foto: la imagen no se toca (sin transparencia)")


def probar_sin_tocar(prs, n: int, mensaje: str) -> None:
    pics = formas(prs.slides[n - 1], "image_")
    comprobar(bool(pics) and not transparente(imagen_de(pics[0])), mensaje)


def probar_matriz(prs, m: Medida, n: int) -> None:
    s = prs.slides[n - 1]
    rects = [f for f in s.shapes if f.shape_type == MSO_SHAPE_TYPE.AUTO_SHAPE]
    cabeceras, celdas = formas(rects, "matrix_head_"), formas(rects, "matrix_cell_")
    comprobar(len(cabeceras) == 4 and len(celdas) == 12, f"matriz: 4 cabeceras y 12 celdas ({len(cabeceras)}, {len(celdas)})")
    if not cabeceras or not celdas:
        return
    izq, arr, der, aba = bloque(m, [*cabeceras, *celdas])
    titulo = formas(s, "title_")[0]
    tope = m.caja(titulo)[1] + m.caja(titulo)[3] + GAP_MATRIZ
    esperado = tope + max(0.0, (PIE - tope - (aba - arr)) / 2)
    comprobar(abs(arr - esperado) <= TOL and arr > tope + 5,
              f"matriz: centrada en vertical (arriba {arr:.1f}, esperado {esperado:.1f}, tope {tope:.1f})")
    altos = sorted({round(m.caja(c)[3], 1) for c in celdas})
    comprobar(all(abs(a - 35) <= 0.5 for a in altos), f"matriz: las filas crecen hasta 35 lógicos ({altos})")
    destacada = sorted(cabeceras, key=lambda f: f.left)[2]
    color, alfa = relleno(destacada)
    otras = {relleno(f)[0] for f in cabeceras if f is not destacada}
    comprobar(color == "2D5BFF" and alfa is None and otras == {"000033"},
              f"matriz: cabecera destacada en blue y el resto en navy ({color}, {otras})")
    columna = [c for c in celdas if abs(c.left - destacada.left) < 12700]
    resto = [c for c in celdas if c not in columna]
    rellenos = {relleno(c) for c in columna}
    comprobar(len(columna) == 3 and rellenos == {("C5D5F7", 45000)},
              f"matriz: celdas destacadas en blue_pale con 45 % de alfa ({rellenos})")
    comprobar(all(relleno(c)[1] is None for c in resto), "matriz: las demás celdas sin alfa")


def motor(codigo: str, *args: str) -> subprocess.CompletedProcess:
    """Corre código con el motor importable (las mismas dependencias que `neo.py`)."""
    deps = ["pydantic==2.13.5", "pyyaml==6.0.3", "python-pptx==1.0.2", "pillow==12.3.0", "lxml==6.1.3",
            "pymupdf==1.28.2"]
    cmd = ["uv", "run", "--quiet", "--no-project", *(a for d in deps for a in ("--with", d)),
           "python", "-c", codigo, str(SKILL / "motor"), *args]
    return subprocess.run(cmd, capture_output=True, text=True)


PALETA = """
import sys
from pptx import Presentation
sys.path.insert(0, sys.argv[1])
from neo_refactor.audit.brand import _Colors, _Shape, _fill, _line
from neo_refactor.knowledge import Knowledge
permitidos = {v.upper() for v in Knowledge().tokens["colors"].values()}
slide = Presentation(sys.argv[2]).slides[int(sys.argv[3]) - 1]
colores = _Colors(slide)
malos = []
for f in slide.shapes:
    if f.shape_type != 1:
        continue
    envuelta = _Shape(f._element, f.name, 0, 0, 0, 0, "")
    for color in (_fill(envuelta, colores), _line(envuelta, colores)[0]):
        if color and color != "gradient" and color not in permitidos:
            malos.append((f.name, color))
print(malos)
"""


def probar_paleta(salida: Path, n: int) -> None:
    """La misma lectura de color que `off_palette_shape` (`audit/policies.py`): `_fill` y `_line`
    de `audit/brand.py` contra los tokens de la paleta."""
    proc = motor(PALETA, str(salida), str(n))
    comprobar(proc.returncode == 0 and proc.stdout.strip() == "[]",
              f"matriz: la auditoría de paleta acepta los colores con alfa ({proc.stdout.strip() or proc.stderr[-300:]})")


# Hoy el motor no compone slides oscuras con imágenes de contenido (la composición libre en
# oscuro todavía no se dibuja; solo el separador es oscuro): la guarda se prueba llamando al
# paso del composer que quita el fondo, con una slide oscura, una clara con «keep» y una clara.
OSCURA = """
import sys, types
sys.path.insert(0, sys.argv[1])
from neo_refactor.composer import Composer
from neo_refactor.knowledge import Knowledge
from neo_refactor.schemas import Box, RenderedSlide, RPicture

def limpia(modo, fondo="clear"):
    pic = RPicture(role="image", box=Box(x=45, y=100, w=300, h=170), path=sys.argv[2], group="image1",
                   sources=["i1"])
    rs = RenderedSlide(source_index=5, layout="image_text", mode=modo, background="", elements=[pic])
    Composer(Knowledge(), {5: {"i1": "screenshot"}})._clear_backgrounds(
        types.SimpleNamespace(index=5), types.SimpleNamespace(image_background=fondo), rs)
    return rs.elements[0].path != sys.argv[2]

print(limpia("dark"), limpia("light", "keep"), limpia("light"))
"""


def probar_oscura(imagen: Path) -> None:
    proc = motor(OSCURA, str(imagen))
    salida = proc.stdout.strip()
    comprobar(proc.returncode == 0 and salida == "False False True",
              f"oscura: el composer no quita el fondo en una slide oscura ni con «keep», sí en la clara "
              f"({salida or proc.stderr[-300:]})")


def probar_tope(reporte: dict, prs, n: int) -> None:
    """Un diagrama casi todo blanco conserva su fondo y deja el aviso `image_background_kept`."""
    fila = next((s for s in reporte.get("slides", []) if s.get("slide") == n), {})
    avisos = [i.get("detail", "") for i in fila.get("issues", [])]
    comprobar(any(a.startswith("image_background_kept:") for a in avisos),
              f"tope: aviso image_background_kept al conservar el fondo ({avisos})")
    probar_sin_tocar(prs, n, "tope: si se iría más del 70 % de la imagen, el fondo se conserva")


def probar_ajustes(original: Path, rediseno: Path, carpeta: Path) -> None:
    """`ajustes.quitar_fondo_blanco` y la regla nueva de `ajustes.centrar_bloque` (D4)."""
    sys.path.insert(0, str(SKILL / "scripts"))
    from neo_skill import ajustes

    prs = ajustes.abrir(original)
    s = ajustes.slide(prs, 2)
    pic = next(f for f in s.shapes if f.shape_type == MSO_SHAPE_TYPE.PICTURE)
    pic.crop_left, pic.crop_bottom = 0.05, 0.03
    antes = (pic.left, pic.top, pic.width, pic.height, pic.crop_left, pic.crop_bottom)
    hecho = ajustes.quitar_fondo_blanco(s, pic)
    despues = (pic.left, pic.top, pic.width, pic.height, pic.crop_left, pic.crop_bottom)
    comprobar(hecho and transparente(imagen_de(pic)) and antes == despues,
              "ajustes.quitar_fondo_blanco: imagen sin fondo, misma posición, tamaño y recorte")
    foto_s = ajustes.slide(prs, 3)
    foto_pic = next(f for f in foto_s.shapes if f.shape_type == MSO_SHAPE_TYPE.PICTURE)
    comprobar(ajustes.quitar_fondo_blanco(foto_s, foto_pic) is False,
              "ajustes.quitar_fondo_blanco: una foto sin fondo blanco queda igual (False)")
    prs.save(str(carpeta / "ajustado.pptx"))
    otra = Presentation(str(carpeta / "ajustado.pptx")).slides[1]
    rels = [r for r in otra.part.rels.values() if r.reltype.endswith("/image")]
    comprobar(len(rels) == 1 and transparente(imagen_de(next(f for f in otra.shapes if f.shape_type == 13))),
              f"ajustes.quitar_fondo_blanco: el archivo guarda solo la imagen nueva ({len(rels)} relación)")

    prs = ajustes.abrir(rediseno)
    s = ajustes.slide(prs, 4)
    tabla = [f for f in s.shapes if f.name.startswith(("matrix_", "cell", "head"))]
    for f in tabla:
        ajustes.mover(f, dy_pt=-40)
    dy = ajustes.centrar_bloque(s)
    titulo = next(f for f in s.shapes if f.name.startswith("title"))
    tope = (titulo.top + titulo.height) / ajustes.PT + ajustes.AIRE_TITULO
    arriba = min(f.top for f in tabla) / ajustes.PT
    abajo = max(f.top + f.height for f in tabla) / ajustes.PT
    comprobar(dy > 0 and abs((arriba - tope) - (ajustes.PIE - abajo)) <= 1.0,
              f"ajustes.centrar_bloque: centra la matriz entre el título y el pie (movió {dy:.1f} pt)")
    tabla[0].name = "metric_card_99"
    comprobar(ajustes.centrar_bloque(s) == 0.0, "ajustes.centrar_bloque: con cifras no mueve nada")


def main() -> None:
    guardar = Path(sys.argv[sys.argv.index("--salida") + 1]) if "--salida" in sys.argv else None
    with tempfile.TemporaryDirectory(prefix="neo-imagenes-matriz-") as tmp:
        t = Path(tmp)
        captura(t / "captura.png")
        foto(t / "foto.png")
        diagrama_vacio(t / "vacio.png")
        deck(t / "deck.pptx", t / "captura.png", t / "foto.png", t / "vacio.png")
        lectura = neo("leer", "deck.pptx", "--out", "lectura", "--sin-imagenes", cwd=t)
        datos = json.loads((t / lectura["lectura"]).read_text(encoding="utf-8"))
        (t / "plan.json").write_text(json.dumps(plan(datos), ensure_ascii=False, indent=1), encoding="utf-8")
        red = neo("redisenar", "deck.pptx", "--plan", "plan.json", "--out", "v1.pptx", cwd=t)
        modos = {s["slide"]: s["modo"] for s in red.get("slides", [])}
        comprobar(red.get("ok") is True and all(modos.get(k) == "redesign" for k in range(1, 7)),
                  f"redisenar: las 6 slides rediseñadas ({modos})")
        prs = Presentation(str(t / "v1.pptx"))
        m = Medida(prs)
        probar_captura(prs, m, 2)
        probar_foto(prs, m, 3)
        probar_matriz(prs, m, 4)
        probar_tope(json.loads((t / "v1_report.json").read_text(encoding="utf-8")), prs, 5)
        probar_sin_tocar(prs, 6, "keep: con image_background «keep» la captura conserva su fondo")
        probar_paleta(t / "v1.pptx", 4)
        # Integración con la verificación: la captura sin fondo es la misma imagen del original.
        ver = neo("verificar", "deck.pptx", "v1.pptx", "--reporte", "v1_report.json", cwd=t)
        tratadas = ver.get("imagenes_tratadas") or []
        comprobar(ver.get("ok") is True and len(tratadas) >= 1,
                  f"verificar: la captura sin fondo pasa como imagen tratada ({len(tratadas)})")
        ent = neo("entregar", "deck.pptx", "v1.pptx", "--reporte", "v1_report.json", "--out", "final.pptx", cwd=t)
        comprobar(ent.get("ok") is True and (t / "final.pptx").exists(),
                  "entregar: entrega el deck con capturas sin fondo")
        shutil.copy2(t / "captura.png", t / "captura-oscura.png")
        probar_oscura(t / "captura-oscura.png")
        probar_ajustes(t / "deck.pptx", t / "v1.pptx", t)
        if guardar:
            guardar.mkdir(parents=True, exist_ok=True)
            for nombre in ("deck.pptx", "plan.json", "v1.pptx", "v1_report.json", "captura.png", "foto.png",
                           "vacio.png"):
                if (t / nombre).exists():
                    shutil.copy2(t / nombre, guardar / nombre)
    print()
    if fallas:
        print(f"{len(fallas)} falla(s).")
        raise SystemExit(1)
    print("Todo bien.")


if __name__ == "__main__":
    main()
