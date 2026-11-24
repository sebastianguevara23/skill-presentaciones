"""Pruebas del logo del cliente (plan 0.2.0, tareas 2.3 y 2.4).

- 2.3: un logo con bloque o fondo propio (texto amarillo sobre un bloque negro) va igual en
  fondo oscuro; el texto negro suelto sigue pasando a blanco; un JPG con fondo blanco pierde
  ese fondo en la variante oscura.
- 2.4: `leer` lista el logo que está solo en `slideLayout1` (con `srcRect`) como candidato a
  `client_logo`, y `redisenar --logo-cliente` pone el bloque NEO | cliente en todas las slides
  sin que el logo cuente como contenido faltante ni sobrante.

Uso: uv run --with python-pptx==1.0.2 --with pillow==12.3.0 python tools/pruebas/logos.py
(necesita uv, como la skill). Sale con 1 si algo falla.
"""
from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.oxml.shapes.picture import CT_Picture
from pptx.util import Emu, Pt

RAIZ = Path(__file__).resolve().parents[2]
SKILL = RAIZ / "skills" / "neo-presentaciones"
NEO = SKILL / "scripts" / "neo.py"
# Lo que necesita `cobrand.py` para importarse fuera de neo.py.
MOTOR = ["--with", "pydantic==2.13.5", "--with", "pillow==12.3.0"]
AMARILLO, NEGRO = (255, 205, 17, 255), (20, 20, 20, 255)
fallas: list[str] = []


def comprobar(condicion: bool, mensaje: str) -> None:
    print(("ok   " if condicion else "FALLA") + " " + mensaje)
    if not condicion:
        fallas.append(mensaje)


def neo(*args: str, cwd: Path, esperado: int = 0) -> dict:
    proc = subprocess.run(["uv", "run", "--quiet", str(NEO), *args], capture_output=True, text=True, cwd=cwd)
    if proc.returncode != esperado:
        fallas.append(f"{args[0]}: código {proc.returncode} (esperado {esperado})\n{proc.stdout[-1500:]}{proc.stderr[-1500:]}")
        print(fallas[-1])
        return {}
    return json.loads(proc.stdout) if proc.stdout.strip() else {}


# ---------------------------------------------------------------- fixtures

def _letras_logo(d: ImageDraw.ImageDraw, x0: int, y0: int, alto: int, color) -> None:
    """Tres letras a trazos gruesos (sin depender de una fuente instalada)."""
    t, w = alto // 6, alto * 2 // 3
    d.rectangle([x0, y0, x0 + t, y0 + alto], fill=color)                       # C
    d.rectangle([x0, y0, x0 + w, y0 + t], fill=color)
    d.rectangle([x0, y0 + alto - t, x0 + w, y0 + alto], fill=color)
    x = x0 + w + t
    d.polygon([(x, y0 + alto), (x + w // 2, y0), (x + w, y0 + alto), (x + w - t, y0 + alto),
               (x + w // 2, y0 + 2 * t), (x + t, y0 + alto)], fill=color)      # A
    x += w + t
    d.rectangle([x, y0, x + w, y0 + t], fill=color)                             # T
    d.rectangle([x + w // 2 - t // 2, y0, x + w // 2 + t // 2, y0 + alto], fill=color)


def logo_bloque(ruta: Path) -> Path:
    """Texto amarillo sobre un bloque negro, con aire transparente alrededor (logo con bloque propio)."""
    im = Image.new("RGBA", (640, 260), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rectangle([20, 20, 620, 240], fill=NEGRO)
    _letras_logo(d, 90, 60, 140, AMARILLO)
    im.save(ruta)
    return ruta


def logo_bloque_y_texto(ruta: Path) -> Path:
    """Bloque negro a la izquierda (con texto amarillo) y texto amarillo suelto a la derecha: el
    borde no es todo opaco, pero la mayor región oscura es un área llena."""
    im = Image.new("RGBA", (900, 260), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, 420, 259], fill=NEGRO)
    _letras_logo(d, 40, 60, 140, AMARILLO)
    _letras_logo(d, 470, 90, 80, AMARILLO)
    im.save(ruta)
    return ruta


def _texto_negro(d: ImageDraw.ImageDraw, x0: int, y0: int, alto: int, color) -> None:
    """«ELTOL» a trazos: letras sueltas, ninguna es un área llena."""
    t, w = alto // 7, alto // 2
    x = x0
    for letra in "ELTOL":
        if letra == "E":
            d.rectangle([x, y0, x + t, y0 + alto], fill=color)
            for y in (y0, y0 + alto // 2 - t // 2, y0 + alto - t):
                d.rectangle([x, y, x + w, y + t], fill=color)
        elif letra == "L":
            d.rectangle([x, y0, x + t, y0 + alto], fill=color)
            d.rectangle([x, y0 + alto - t, x + w, y0 + alto], fill=color)
        elif letra == "T":
            d.rectangle([x, y0, x + w, y0 + t], fill=color)
            d.rectangle([x + w // 2 - t // 2, y0, x + w // 2 + t // 2, y0 + alto], fill=color)
        else:
            d.ellipse([x, y0, x + w, y0 + alto], outline=color, width=t)
        x += w + t * 2


def logo_texto_negro(ruta: Path) -> Path:
    im = Image.new("RGBA", (700, 200), (0, 0, 0, 0))
    _texto_negro(ImageDraw.Draw(im), 30, 30, 140, NEGRO)
    im.save(ruta)
    return ruta


def logo_fondo_blanco(ruta: Path) -> Path:
    """Un JPG: texto negro sobre fondo blanco opaco y, a la derecha, un círculo rojo con una
    barra blanca adentro. La «O» está en x 360–430, y 30–170; la barra, en x 632–648, y 70–130."""
    im = Image.new("RGB", (720, 200), (255, 255, 255))
    d = ImageDraw.Draw(im)
    _texto_negro(d, 30, 30, 140, NEGRO[:3])
    d.ellipse([585, 35, 715, 165], fill=(200, 30, 30))
    d.rectangle([632, 70, 648, 130], fill=(255, 255, 255))
    im.save(ruta, quality=92)
    return ruta


def tira_con_logo(ruta: Path) -> Path:
    """La imagen del layout: un bloque rojo (lo que recorta `srcRect`) y el logo del cliente a la derecha."""
    im = Image.new("RGBA", (1280, 260), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, 639, 259], fill=(200, 30, 30, 255))
    d.rectangle([660, 20, 1260, 240], fill=NEGRO)
    _letras_logo(d, 730, 60, 140, AMARILLO)
    im.save(ruta)
    return ruta


def _texto(slide, x, y, w, h, parrafos: list[str], tam=20, negrita=False):
    caja = slide.shapes.add_textbox(Emu(x), Emu(y), Emu(w), Emu(h))
    tf = caja.text_frame
    tf.word_wrap = True
    for i, linea in enumerate(parrafos):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        r = p.add_run()
        r.text = linea
        r.font.size, r.font.bold, r.font.name = Pt(tam), negrita, "Calibri"
        r.font.color.rgb = RGBColor(0x40, 0x40, 0x40)
    return caja


def _imagen_en(part, tree, imagen: Path, caja: tuple[int, int, int, int], nombre: str, recorte=None) -> None:
    """Una imagen en el árbol de formas de un layout o un master (python-pptx no trae `add_picture` ahí)."""
    _part, rid = part.get_or_add_image_part(str(imagen))
    ids = [int(v) for v in tree.xpath("//p:cNvPr/@id")] or [1]
    pic = CT_Picture.new_pic(max(ids) + 1, nombre, "", rid, *caja)
    if recorte:
        pic.srcRect_l, pic.srcRect_t, pic.srcRect_r, pic.srcRect_b = recorte
    tree.append(pic)


def deck_con_logo_en_layout(ruta: Path, tmp: Path) -> Path:
    """4 slides; el logo del cliente está solo en `slideLayout1` (la portada), recortado con
    `srcRect`. El master trae el logo NEO y un fondo: ninguno de los dos es candidato."""
    prs = Presentation()
    prs.slide_width, prs.slide_height = Emu(12192000), Emu(6858000)
    W, H = 12192000, 6858000
    portada, vacio = prs.slide_layouts[0], prs.slide_layouts[6]
    # Logo del cliente arriba a la derecha de la portada: la mitad izquierda de la tira se recorta.
    _imagen_en(portada.part, portada.shapes._spTree, tira_con_logo(tmp / "tira.png"),
               (W - 2400000 - 400000, 300000, 2400000, 1040000), "Logo cliente", recorte=(0.5, 0, 0, 0))
    master = prs.slide_master
    fondo = tmp / "fondo.png"
    Image.new("RGB", (320, 180), (235, 240, 245)).save(fondo)
    _imagen_en(master.part, master.shapes._spTree, fondo, (0, 0, W, H), "Fondo")
    _imagen_en(master.part, master.shapes._spTree, SKILL / "assets" / "brand" / "neo-logo-25.png",
               (300000, H - 600000, 1500000, 300000), "Logo NEO")

    s = prs.slides.add_slide(portada)
    s.shapes.title.text = "Reporte mensual de resultados"
    s.placeholders[1].text = "Octubre 2026"

    s = prs.slides.add_slide(vacio)
    E = W / 13.333
    _texto(s, int(0.7 * E), int(0.5 * E), int(11 * E), int(0.9 * E), ["Resultados del mes"], 32, True)
    for k, (titulo, cuerpo) in enumerate([("Ventas", "Crecieron en todas las regiones."),
                                          ("Servicio", "Menos reclamos que en septiembre."),
                                          ("Equipo", "Dos personas nuevas en soporte.")]):
        _texto(s, int((0.7 + 4 * k) * E), int(2 * E), int(3.6 * E), int(3 * E), [titulo, cuerpo], 18)

    s = prs.slides.add_slide(vacio)
    _texto(s, int(E), int(3 * E), int(11 * E), int(1.2 * E), ["Próximos pasos"], 40, True)

    s = prs.slides.add_slide(vacio)
    _texto(s, int(E), int(3 * E), int(11 * E), int(1.2 * E), ["Gracias"], 40, True)
    prs.save(str(ruta))
    return ruta


PLAN = [
    {"slide": 1, "family": "title_slide", "roles": {"s1:t1": "title", "s1:t2": "subtitle"}},
    {"slide": 2, "family": "three_cards",
     "roles": {"s2:t1": "title", "s2:t2": "card:1", "s2:t3": "card:2", "s2:t4": "card:3"},
     "paragraph_roles": {"s2:t2": ["title", "body"], "s2:t3": ["title", "body"], "s2:t4": ["title", "body"]}},
    {"slide": 3, "family": "section_divider", "roles": {"s3:t1": "title"}},
    {"slide": 4, "family": "closing_slide", "roles": {"s4:t1": "title"}},
]


# ---------------------------------------------------------------- medidas

def oscuros(im: Image.Image) -> float:
    """Fracción de los píxeles opacos que son negros o casi."""
    px = [p for p in im.convert("RGBA").get_flattened_data() if p[3] >= 200]
    return sum(1 for r, g, b, _a in px if max(r, g, b) < 60) / max(1, len(px))


def blancos(im: Image.Image) -> float:
    px = [p for p in im.convert("RGBA").get_flattened_data() if p[3] >= 200]
    return sum(1 for r, g, b, _a in px if min(r, g, b) > 230) / max(1, len(px))


def amarillos(im: Image.Image) -> float:
    px = [p for p in im.convert("RGBA").get_flattened_data() if p[3] >= 200]
    return sum(1 for r, g, b, _a in px if r > 200 and g > 150 and b < 90) / max(1, len(px))


# ---------------------------------------------------------------- pruebas

def prueba_variante_oscura(t: Path) -> None:
    """2.3 con `cobrand` directo: qué variante oscura sale de cada logo."""
    logos = {"bloque": logo_bloque(t / "bloque.png"), "bloque_y_texto": logo_bloque_y_texto(t / "bloque_texto.png"),
             "texto_negro": logo_texto_negro(t / "texto_negro.png"),
             "fondo_blanco": logo_fondo_blanco(t / "fondo_blanco.jpg")}
    codigo = f"""
import json, sys
from types import SimpleNamespace as N
sys.path.insert(0, {str(SKILL / "motor")!r})
from neo_refactor import cobrand
logos, out = json.loads(sys.argv[1]), sys.argv[2]
res = {{}}
for nombre, ruta in logos.items():
    for modo in ("auto", "original", "invertir"):
        c = cobrand.from_file(ruta, out + "/" + modo, dark_mode=modo)
        res[nombre + ":" + modo] = {{"light": c.light, "dark": c.dark, "dark_mode": c.dark_mode}}
# Con logo marcado en el plan y flag, gana el flag; lo marcado sigue contando como el logo.
src = N(slides=[N(index=2, images=[N(id="i1", sha="abcdef123456", path=logos["texto_negro"])])])
cls = N(asset_classes={{2: {{"i1": "client_logo"}}}})
c = cobrand.from_classification(src, cls, out + "/ambos", path=logos["bloque"])
res["ambos"] = {{"light": c.light, "shas": sorted(c.shas)}}
try:
    cobrand.from_file(logos["bloque"], out, dark_mode="otro")
    res["modo_invalido"] = False
except ValueError:
    res["modo_invalido"] = True
print(json.dumps(res))
"""
    proc = subprocess.run(["uv", "run", "--quiet", *MOTOR, "python", "-c", codigo,
                           json.dumps({k: str(v) for k, v in logos.items()}), str(t / "cobrand")],
                          capture_output=True, text=True)
    if proc.returncode:
        comprobar(False, f"cobrand: no corrió\n{proc.stderr[-1500:]}")
        return
    r = json.loads(proc.stdout)
    abrir = lambda ruta: Image.open(ruta).convert("RGBA")  # noqa: E731

    bloque = r["bloque:auto"]
    comprobar(bloque["dark_mode"] == "original", "bloque negro con texto amarillo: se detecta el fondo propio (borde opaco)")
    comprobar(oscuros(abrir(bloque["dark"])) > 0.5, "bloque negro: sigue negro en la variante oscura")
    comprobar(amarillos(abrir(bloque["dark"])) > 0.1, "bloque negro: el texto amarillo se conserva")
    mixto = r["bloque_y_texto:auto"]
    comprobar(mixto["dark_mode"] == "original" and oscuros(abrir(mixto["dark"])) > 0.3,
              "bloque negro a un lado y texto suelto: se detecta por la región llena")
    texto = r["texto_negro:auto"]
    comprobar(texto["dark_mode"] == "invertido", "texto negro sobre transparencia: no tiene fondo propio")
    comprobar(oscuros(abrir(texto["dark"])) < 0.02 and blancos(abrir(texto["dark"])) > 0.9,
              "texto negro sobre transparencia: pasa a blanco en fondo oscuro")
    comprobar(oscuros(abrir(texto["light"])) > 0.9, "texto negro: la variante clara queda negra")
    blanco = r["fondo_blanco:auto"]
    oscuro_jpg = abrir(blanco["dark"])
    transparentes = sum(1 for p in oscuro_jpg.get_flattened_data() if p[3] == 0) / (oscuro_jpg.width * oscuro_jpg.height)
    comprobar(blanco["dark_mode"] == "invertido" and oscuro_jpg.getpixel((oscuro_jpg.width - 1, 0))[3] == 0
              and transparentes > 0.4,
              f"JPG con fondo blanco: el blanco del borde queda transparente en la variante oscura ({transparentes:.0%})")
    comprobar(abrir(blanco["light"]).getpixel((abrir(blanco["light"]).width - 1, 0))[3] == 255,
              "JPG con fondo blanco: la variante clara queda igual")
    comprobar(oscuros(oscuro_jpg) < 0.02, "JPG con fondo blanco: el texto negro pasa a blanco")
    with Image.open(logos["fondo_blanco"]) as im:  # el recorte a la tinta corre las coordenadas
        x0, y0, _x1, _y1 = im.convert("L").point(lambda v: 255 if v < 245 else 0).getbbox()
    comprobar(oscuro_jpg.getpixel((395 - x0, 100 - y0))[3] == 0,
              "JPG con fondo blanco: el ojo de la «O» queda transparente (no un óvalo blanco lleno)")
    barra = oscuro_jpg.getpixel((640 - x0, 100 - y0))
    comprobar(barra[3] == 255 and min(barra[:3]) > 230,
              f"JPG con fondo blanco: el blanco dentro del círculo rojo se conserva ({barra})")
    comprobar(r["bloque:invertir"]["dark_mode"] == "invertido" and oscuros(abrir(r["bloque:invertir"]["dark"])) < 0.05,
              "--logo-cliente-oscuro invertir: el bloque negro pasa a blanco a pedido")
    comprobar(r["texto_negro:original"]["dark_mode"] == "original"
              and oscuros(abrir(r["texto_negro:original"]["dark"])) > 0.9,
              "--logo-cliente-oscuro original: el texto negro queda igual a pedido")
    comprobar(amarillos(abrir(r["ambos"]["light"])) > 0.1 and "abcdef1234" in r["ambos"]["shas"],
              "plan y flag a la vez: gana el flag y lo marcado sigue contando como logo del cliente")
    comprobar(r["modo_invalido"] is True, "un modo de logo oscuro desconocido se rechaza")


def prueba_leer_plantilla(t: Path) -> Path:
    deck_con_logo_en_layout(t / "deck.pptx", t)
    res = neo("leer", "deck.pptx", "--out", "lectura", "--sin-imagenes", cwd=t)
    lectura = json.loads((t / "lectura" / "lectura.json").read_text(encoding="utf-8"))
    imagenes = (lectura.get("plantilla") or {}).get("imagenes") or []
    logo = next((i for i in imagenes if i["origen"] == "slideLayout1"), None)
    comprobar(logo is not None and logo["candidata_client_logo"] and not logo["es_neo"],
              "leer: el logo que está solo en slideLayout1 aparece como candidato a client_logo")
    if logo:
        comprobar(logo["slides"] == [1], f"leer: el logo del layout se ve en la slide 1 ({logo['slides']})")
        archivo = t / logo["archivo"]
        with Image.open(archivo) as im:
            comprobar(archivo.parent.name == "plantilla" and im.size == (640, 260) and amarillos(im) > 0.05
                      and not any(p[0] > 150 and p[1] < 80 and p[3] > 200 for p in im.convert("RGBA").get_flattened_data()),
                      f"leer: el logo sale con el srcRect aplicado (sin la mitad roja, {im.size})")
        x, y, w, h = logo["caja_pt"]
        comprobar(abs(w - 2400000 / 12700) < 1 and x > 600, f"leer: caja del logo en pt ({logo['caja_pt']})")
    neo_logo = next((i for i in imagenes if i["origen"] == "slideMaster1" and i["es_neo"]), None)
    comprobar(neo_logo is not None and not neo_logo["candidata_client_logo"] and len(neo_logo["slides"]) == 4,
              "leer: el logo NEO del master se reconoce como NEO y no es candidato")
    fondo = next((i for i in imagenes if i["origen"] == "slideMaster1" and not i["es_neo"]), None)
    comprobar(fondo is not None and not fondo["candidata_client_logo"], "leer: el fondo del master no es candidato")
    comprobar(res.get("logo_cliente_en_plantilla") == ([logo["archivo"]] if logo else None),
              "leer: el resumen nombra el logo candidato de la plantilla")
    return t / logo["archivo"] if logo else t / "tira.png"


def prueba_redisenar_con_flag(t: Path, logo: Path) -> None:
    (t / "plan.json").write_text(json.dumps(PLAN), encoding="utf-8")
    red = neo("redisenar", "deck.pptx", "--plan", "plan.json", "--out", "v1.pptx", "--logo-cliente", str(logo), cwd=t)
    if not red:
        return
    modos = {s["slide"]: s["modo"] for s in red.get("slides", [])}
    comprobar(set(modos.values()) == {"redesign"}, f"redisenar --logo-cliente: todas con su familia ({modos})")
    integridad = red.get("integridad_motor") or {}
    comprobar(integridad.get("preserved") is True and integridad.get("removed_content") == 0,
              f"redisenar --logo-cliente: la integridad del motor no ve faltantes ni sobrantes ({integridad})")
    prs = Presentation(str(t / "v1.pptx"))
    con_bloque, oscura = [], None
    for n, slide in enumerate(prs.slides, 1):
        nombres = {sh.name for sh in slide.shapes}
        if {"NEO_BRAND_client_logo", "NEO_BRAND_cobrand_rule"} <= nombres:
            con_bloque.append(n)
        cliente = next((sh for sh in slide.shapes if sh.name == "NEO_BRAND_client_logo"), None)
        fondo = next((sh for sh in slide.shapes if sh.name == "NEO_BRAND_background"), None)
        if cliente is not None and fondo is not None:
            with Image.open(io.BytesIO(fondo.image.blob)) as im:
                if sum(im.convert("L").resize((16, 9)).get_flattened_data()) / 144 < 90:
                    oscura = (n, cliente.image.blob)
    comprobar(con_bloque == list(range(1, len(prs.slides) + 1)),
              f"redisenar --logo-cliente: bloque NEO | cliente en todas las slides ({con_bloque} de {len(prs.slides)})")
    comprobar(oscura is not None, "redisenar --logo-cliente: hay una slide oscura (el separador)")
    if oscura:
        with Image.open(io.BytesIO(oscura[1])) as im:
            comprobar(oscuros(im) > 0.5 and amarillos(im) > 0.05,
                      f"redisenar --logo-cliente: en la slide oscura {oscura[0]} el bloque negro se conserva")
    ver = neo("verificar", "deck.pptx", "v1.pptx", cwd=t)
    comprobar(ver.get("conservado") is True and not ver.get("slides"),
              f"verificar: el logo del flag no cuenta como contenido faltante ni sobrante ({ver.get('slides')})")
    malo = neo("redisenar", "deck.pptx", "--plan", "plan.json", "--out", "v2.pptx", "--logo-cliente", "no-existe.png",
               cwd=t, esperado=2)
    comprobar(malo.get("ok") is False and "--logo-cliente" in malo.get("error", ""),
              "redisenar --logo-cliente con un archivo que no existe: error claro")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="neo-logos-") as tmp:
        t = Path(tmp)
        prueba_variante_oscura(t)
        logo = prueba_leer_plantilla(t)
        prueba_redisenar_con_flag(t, logo)
    print()
    if fallas:
        print(f"{len(fallas)} falla(s)")
        sys.exit(1)
    print("todo en verde")


if __name__ == "__main__":
    main()
