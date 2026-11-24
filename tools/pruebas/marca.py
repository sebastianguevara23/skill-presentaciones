"""Prueba de la marca por defecto del motor (0.2.0, tareas 1.1–1.4, 3.1 y 3.6).

Arma un deck propio sin la marca (contenido inventado y neutro), lo lee, lo rediseña y lo
revisa con `neo.py`, y comprueba los bytes del resultado:

- viñetas y numeraciones con `buClr 2D5BFF` y `buSzPct 100000`, en orden de esquema válido,
  en las slides rediseñadas y en la que conserva su organización (`keep_layout`);
- la slide `keep_layout` sin `a:highlight` y con `ea`/`cs`/`sym` iguales a `latin`;
- el separador de dos palabras con la primera en blanco y el resto en `blue_pale`, sin
  itálica, con su línea azul y sin el patrón geométrico (y el de una palabra, todo en blanco);
- todos los títulos de slide a 42 pt en el archivo final;
- `titulo_dos_lineas` en `revisar` y `cabe_como_titulo` en `leer` donde corresponde;
- `ajustes.flecha_escuadra`: forma libre ortogonal con punta, a la separación pedida.

Uso: uv run --with python-pptx==1.0.2 --with pillow==12.3.0 python tools/pruebas/marca.py
(necesita uv, como la skill). Sale con 1 si algo falla.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from lxml import etree
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.oxml.ns import qn
from pptx.util import Emu, Pt

RAIZ = Path(__file__).resolve().parents[2]
SKILL = RAIZ / "skills" / "neo-presentaciones"
NEO = SKILL / "scripts" / "neo.py"
PT = 12700
AZUL, AZUL_PALIDO, BLANCO = "2D5BFF", "C5D5F7", "FFFFFF"
fallas: list[str] = []

# Orden de los hijos de `a:pPr` en el esquema (CT_TextParagraphProperties).
ORDEN_PPR = {tag: k for k, grupo in enumerate((
    ("lnSpc",), ("spcBef",), ("spcAft",), ("buClrTx", "buClr"), ("buSzTx", "buSzPct", "buSzPts"),
    ("buFontTx", "buFont"), ("buNone", "buAutoNum", "buChar", "buBlip"), ("tabLst",), ("defRPr",), ("extLst",),
)) for tag in grupo}
PARRAFOS = tuple(qn(t) for t in ("a:pPr", *(f"a:lvl{k}pPr" for k in range(1, 10))))

TITULO_LARGO = "Tres frentes de trabajo para transformar la operación comercial"
SEPARADOR_LARGO = "Cómo trabajamos con nuestros clientes en toda la región"
PARRAFO_LARGO = ("Este texto es largo a propósito: tiene más de veinticinco palabras, así que nunca sería un "
                 "título de slide y la lectura no debe medirlo como candidato a título corto en ninguna pasada.")


def comprobar(condicion: bool, mensaje: str) -> None:
    print(("ok   " if condicion else "FALLA") + " " + mensaje)
    if not condicion:
        fallas.append(mensaje)


def neo(*args: str, cwd: Path, esperado: int = 0) -> dict:
    proc = subprocess.run(["uv", "run", "--quiet", str(NEO), *args], capture_output=True, text=True, cwd=cwd)
    if proc.returncode != esperado:
        fallas.append(f"{args[0]}: código {proc.returncode}\n{proc.stdout[-1500:]}{proc.stderr[-1500:]}")
        print(f"FALLA neo.py {args[0]} (código {proc.returncode})")
        return {}
    return json.loads(proc.stdout) if proc.stdout.strip() else {}


# ---------------------------------------------------------------- deck de prueba

def _caja(slide, x, y, w, h, parrafos, tam=18, negrita=False, color="404040"):
    """Caja de texto en pt de una slide de 960 × 540 (13.33 × 7.5 in)."""
    forma = slide.shapes.add_textbox(Emu(int(x * PT)), Emu(int(y * PT)), Emu(int(w * PT)), Emu(int(h * PT)))
    tf = forma.text_frame
    tf.word_wrap = True
    for k, texto in enumerate(parrafos):
        p = tf.paragraphs[0] if k == 0 else tf.add_paragraph()
        r = p.add_run()
        r.text = texto
        r.font.size, r.font.bold, r.font.name = Pt(tam), negrita, "Calibri"
        r.font.color.rgb = RGBColor.from_string(color)
    return forma


def _sub(padre, tag, **attrs):
    return etree.SubElement(padre, qn(tag), **attrs)


def _vineta_google(p, *, char="●", autonum=None, start=None, sin_marca=False):
    """Viñeta como la exporta Google Slides: color del tema, tamaño en puntos y su letra."""
    ppr = p._p.get_or_add_pPr()
    ppr.set("marL", "457200")
    ppr.set("indent", "-342900")
    clr = _sub(ppr, "a:buClr")
    _sub(clr, "a:schemeClr", val="dk1")
    _sub(ppr, "a:buSzPts", val="1800")
    if sin_marca:
        return
    if autonum:
        _sub(ppr, "a:buAutoNum", type=autonum, **({"startAt": str(start)} if start else {}))
    else:
        _sub(ppr, "a:buFont", typeface="Wingdings")
        _sub(ppr, "a:buChar", char=char)


def _resaltado_y_fuentes(rpr):
    """`a:highlight` y `ea`/`cs`/`sym` en Arial mientras `latin` dice Calibri (como Google)."""
    latin = rpr.find(qn("a:latin"))
    alto = etree.Element(qn("a:highlight"))
    _sub(alto, "a:srgbClr", val="D9D9D9")
    latin.addprevious(alto)
    for tag in ("a:sym", "a:cs", "a:ea"):
        latin.addnext(etree.Element(qn(tag), typeface="Arial", pitchFamily="34", charset="0"))


def crear_deck(ruta: Path) -> None:
    prs = Presentation()
    prs.slide_width, prs.slide_height = Emu(960 * PT), Emu(540 * PT)
    vacio = prs.slide_layouts[6]

    s = prs.slides.add_slide(vacio)  # 1 portada
    _caja(s, 60, 190, 840, 70, ["Informe de prueba de la marca"], 40, True, "C0392B")
    _caja(s, 60, 270, 840, 40, ["Para el equipo de diseño"], 20)

    s = prs.slides.add_slide(vacio)  # 2 separador de dos palabras
    _caja(s, 60, 200, 840, 70, ["Quiénes somos"], 44, True, "C0392B")
    _caja(s, 60, 280, 840, 40, ["Nuestra forma de trabajar"], 20)

    s = prs.slides.add_slide(vacio)  # 3 separador de una palabra
    _caja(s, 60, 220, 840, 70, ["Resultados"], 44, True, "C0392B")

    s = prs.slides.add_slide(vacio)  # 4 keep_layout con viñetas, resaltado, fuentes y tabla
    _caja(s, 40, 30, 880, 50, ["Estado del proyecto"], 30, True, "C0392B")
    lista = _caja(s, 40, 100, 520, 260, ["Avance del piloto", "Riesgos abiertos", "Primero", "Segundo",
                                         "Color heredado"], 18)
    ps = lista.text_frame.paragraphs
    _vineta_google(ps[0], char="●")
    _vineta_google(ps[1], char="○")
    _vineta_google(ps[2], autonum="arabicPeriod")
    _vineta_google(ps[3], autonum="arabicPeriod", start=2)
    _vineta_google(ps[4], sin_marca=True)
    lst = lista.text_frame._txBody.find(qn("a:lstStyle"))
    nivel = _sub(lst, "a:lvl1pPr")
    _sub(nivel, "a:buSzPts", val="1400")
    _sub(nivel, "a:buChar", char="■")
    for p in ps[:2]:
        _resaltado_y_fuentes(p.runs[0]._r.get_or_add_rPr())
    fin = ps[0]._p.get_or_add_endParaRPr()
    fin.set("lang", "es")
    _sub(fin, "a:highlight").append(etree.Element(qn("a:srgbClr"), val="FFFF00"))
    _sub(fin, "a:latin", typeface="Calibri")
    _sub(fin, "a:ea", typeface="Arial")
    tabla = s.shapes.add_table(2, 2, Emu(600 * PT), Emu(110 * PT), Emu(320 * PT), Emu(120 * PT)).table
    for k, texto in enumerate(["CR", "38 %", "Clics", "1 200"]):
        celda = tabla.cell(k // 2, k % 2)
        celda.text = texto
        r = celda.text_frame.paragraphs[0].runs[0]
        r.font.name, r.font.size = "Calibri", Pt(16)
        _resaltado_y_fuentes(r._r.get_or_add_rPr())

    s = prs.slides.add_slide(vacio)  # 5 three_cards con título largo, viñetas y numeración
    _caja(s, 40, 30, 880, 60, [TITULO_LARGO], 30, True, "C0392B")
    cards = [("Clientes", ["Unificar los canales de atención", "Medir la satisfacción cada mes"]),
             ("Procesos", ["Automatizar la aprobación", "Reducir el papel"]),
             ("Personas", ["Formar a los equipos en datos y en herramientas de IA."])]
    for k, (titulo, cuerpo) in enumerate(cards):
        caja = _caja(s, 40 + k * 300, 140, 280, 220, [titulo, *cuerpo], 18)
        for j, p in enumerate(caja.text_frame.paragraphs[1:]):
            if k == 0:
                _vineta_google(p, char="●")
            elif k == 1:
                _vineta_google(p, autonum="arabicPeriod")

    s = prs.slides.add_slide(vacio)  # 6 cifras
    _caja(s, 40, 30, 880, 60, ["Resultados del piloto"], 30, True, "C0392B")
    for k, (valor, rotulo) in enumerate([("38 %", "menos tiempo de respuesta"), ("2,4 M", "soles ahorrados al año"),
                                         ("+12", "puntos de satisfacción")]):
        _caja(s, 60 + k * 300, 180, 260, 70, [valor], 44, True, "27AE60")
        _caja(s, 60 + k * 300, 260, 260, 40, [rotulo], 18)

    s = prs.slides.add_slide(vacio)  # 7 título corto
    _caja(s, 40, 30, 880, 60, ["Tres frentes"], 30, True, "C0392B")
    for k, (titulo, cuerpo) in enumerate([("Clientes", "Canales unificados."), ("Procesos", "Menos papel."),
                                         ("Personas", PARRAFO_LARGO)]):
        _caja(s, 40 + k * 300, 140, 280, 220, [titulo, cuerpo], 18)

    s = prs.slides.add_slide(vacio)  # 8 separador largo: no entra en una línea ni a 32 pt
    _caja(s, 60, 200, 840, 90, [SEPARADOR_LARGO], 44, True, "C0392B")

    s = prs.slides.add_slide(vacio)  # 9 cierre
    _caja(s, 60, 230, 840, 70, ["¡Gracias!"], 44, True, "C0392B")
    prs.save(str(ruta))


PLAN = [
    {"slide": 1, "family": "title_slide", "roles": {"s1:t1": "title", "s1:t2": "subtitle"}},
    {"slide": 2, "family": "section_divider", "roles": {"s2:t1": "title", "s2:t2": "subtitle"}},
    {"slide": 3, "family": "section_divider", "roles": {"s3:t1": "title"}},
    # El marco de la tabla va como contenido: por defecto el plan lo deja `decorative` y el brand
    # shell lo retira con sus celdas (pendiente fuera de esta prueba; `verificar` lo atrapa).
    {"slide": 4, "keep_layout": "mantén el layout que tiene, solo corrige el estilo", "roles": {"s4:d1": "body"}},
    {"slide": 5, "family": "three_cards",
     "roles": {"s5:t1": "title", "s5:t2": "card:1", "s5:t3": "card:2", "s5:t4": "card:3"},
     "paragraph_roles": {"s5:t2": ["title", "body", "body"], "s5:t3": ["title", "body", "body"],
                         "s5:t4": ["title", "body"]}},
    {"slide": 6, "family": "benefits_content", "composition_layout": "metrics_row",
     "roles": {"s6:t1": "title", "s6:t2": "metric:1:value", "s6:t3": "metric:1:label", "s6:t4": "metric:2:value",
               "s6:t5": "metric:2:label", "s6:t6": "metric:3:value", "s6:t7": "metric:3:label"}},
    {"slide": 7, "family": "three_cards",
     "roles": {"s7:t1": "title", "s7:t2": "card:1", "s7:t3": "card:2", "s7:t4": "card:3"},
     "paragraph_roles": {"s7:t2": ["title", "body"], "s7:t3": ["title", "body"], "s7:t4": ["title", "body"]}},
    {"slide": 8, "family": "section_divider", "roles": {"s8:t1": "title"}},
    {"slide": 9, "family": "closing_slide", "roles": {"s9:t1": "title"}},
]


# ---------------------------------------------------------------- comprobaciones

def marcador(slide) -> dict:
    nombre = slide._element.find(qn("p:cSld")).get("name", "")
    return json.loads(nombre.split(":", 1)[1]) if nombre.startswith("neo-refactor:") else {}


def _local(el) -> str:
    return etree.QName(el).localname


def vinetas_de_marca(slide, n: int) -> int:
    """Cada viñeta o numeración: azul, 100 %, en orden de esquema. Devuelve cuántas vio."""
    vistas = 0
    for ppr in slide._element.iter(*PARRAFOS):
        hijos = [_local(c) for c in ppr]
        if not {"buChar", "buAutoNum", "buClr", "buSzPts", "buSzPct"} & set(hijos):
            continue
        vistas += 1
        rangos = [ORDEN_PPR.get(h, 99) for h in hijos]
        clr = ppr.find(f"{qn('a:buClr')}/{qn('a:srgbClr')}")
        tam = ppr.find(qn("a:buSzPct"))
        ok = (rangos == sorted(rangos) and clr is not None and clr.get("val") == AZUL
              and tam is not None and tam.get("val") == "100000"
              and not {"buSzPts", "buSzTx", "buClrTx"} & set(hijos))
        if ppr.find(qn("a:buChar")) is not None:
            fuente = ppr.find(qn("a:buFont"))
            ok = ok and ppr.find(qn("a:buChar")).get("char") == "•" and fuente is not None \
                and fuente.get("typeface") == "Arial"
        if not ok:
            comprobar(False, f"slide {n}: viñeta fuera de marca o de orden: {etree.tostring(ppr).decode()[:300]}")
    return vistas


def comprobar_salida(ruta: Path) -> None:
    prs = Presentation(str(ruta))
    escala = prs.slide_width / PT / 720
    slides = list(prs.slides)
    marcas = [marcador(s) for s in slides]

    # 1.1 y 1.2 · viñetas
    rediseno = [k for k, m in enumerate(marcas) if m.get("mode") == "redesign" and m.get("layout") == "three_cards"]
    vistas = sum(vinetas_de_marca(slides[k], k + 1) for k in rediseno)
    comprobar(vistas >= 4, f"rediseño: viñetas y numeraciones azules al 100 % en orden de esquema ({vistas})")
    kl = next((k for k, m in enumerate(marcas) if m.get("variant") == "keep_layout"), None)
    comprobar(kl is not None, "keep_layout: la slide conserva su organización (brand shell)")
    if kl is None:
        return
    keep = slides[kl]
    vistas = vinetas_de_marca(keep, kl + 1)
    comprobar(vistas >= 6, f"keep_layout: viñetas normalizadas a «•» Arial azul 100 % ({vistas})")
    autonum = [(n.get("type"), n.get("startAt")) for n in keep._element.iter(qn("a:buAutoNum"))]
    comprobar(sorted(autonum, key=str) == sorted([("arabicPeriod", None), ("arabicPeriod", "2")], key=str),
              f"keep_layout: las numeraciones conservan su tipo y su inicio ({autonum})")
    heredada = [p for p in keep._element.iter(qn("a:p")) if "Color heredado" in "".join(p.itertext())]
    pp = heredada[0].find(qn("a:pPr")) if heredada else None
    comprobar(pp is not None and pp.find(qn("a:buChar")) is None and pp.find(qn("a:buClr")) is not None,
              "keep_layout: una viñeta heredada toma color y tamaño sin inventar la marca")

    # 1.2 · resaltado y fuentes
    resaltados = len(list(keep._element.iter(qn("a:highlight"))))
    comprobar(resaltados == 0, f"keep_layout: sin a:highlight ({resaltados})")
    distintas = []
    for rpr in keep._element.iter(qn("a:rPr"), qn("a:endParaRPr"), qn("a:defRPr")):
        latin = rpr.find(qn("a:latin"))
        if latin is None:
            continue
        for tag in ("a:ea", "a:cs", "a:sym"):
            otra = rpr.find(qn(tag))
            if otra is not None and otra.get("typeface") != latin.get("typeface"):
                distintas.append((tag, otra.get("typeface"), latin.get("typeface")))
    comprobar(not distintas, f"keep_layout: ea/cs/sym iguales a latin, también en la tabla ({distintas[:3]})")
    celdas = [rpr for tc in keep._element.iter(qn("a:tc")) for rpr in tc.iter(qn("a:rPr"))]
    comprobar(celdas and all(r.find(qn("a:ea")).get("typeface") == r.find(qn("a:latin")).get("typeface")
                             for r in celdas if r.find(qn("a:ea")) is not None),
              "keep_layout: la tabla también queda limpia")

    # 1.3 · separadores
    seps = [k for k, m in enumerate(marcas) if m.get("layout") == "section" and k > 0]
    comprobar(len(seps) == 3, f"separadores: tres en layout section ({seps})")
    for k in seps:
        s = slides[k]
        nombres = [sh.name for sh in s.shapes]
        titulo = next(sh for sh in s.shapes if sh.name.startswith("title_"))
        linea = next((sh for sh in s.shapes if sh.name == "NEO_BRAND_separator_line"), None)
        comprobar(not any(nm.startswith("separator_companion") for nm in nombres),
                  f"slide {k + 1}: sin el patrón geométrico")
        comprobar(linea is not None, f"slide {k + 1}: tiene la línea del separador")
        if linea is not None:
            caja = [round(v / PT / escala, 1) for v in (linea.left, linea.top, linea.width, linea.height)]
            relleno = str(linea.fill.fore_color.rgb) if linea.fill.type == 1 else None
            debajo = (linea.top - (titulo.top + titulo.height)) / PT / escala
            comprobar(caja[2:] == [125.0, 4.0] and relleno == AZUL and abs(linea.left - titulo.left) < PT
                      and abs(debajo - 14) < 0.6,
                      f"slide {k + 1}: línea 125 × 4 lógicos, azul, a la x del título y 14 bajo él "
                      f"({caja}, {relleno}, {debajo:.1f})")
            sub = next((sh for sh in s.shapes if sh.name.startswith("subtitle_")), None)
            if sub is not None:
                comprobar(sub.top >= linea.top + linea.height, f"slide {k + 1}: el subtítulo va bajo la línea")
        runs = [r for p in titulo.text_frame.paragraphs for r in p.runs if r.text.strip()]
        colores = [(r.text.strip(), str(r.font.color.rgb)) for r in runs]
        italica = any(r.font.italic for r in runs)
        fuentes = {r.font.name for r in runs}
        tamanos = {r.font.size.pt for r in runs}
        texto = titulo.text_frame.text.replace(" ", " ")
        primera = texto.split()[0]
        if len(texto.split()) == 1:
            comprobar(all(c == BLANCO for _, c in colores), f"slide {k + 1}: título de una palabra todo en blanco {colores}")
        else:
            comprobar(colores[0] == (primera, BLANCO) and all(c == AZUL_PALIDO for _, c in colores[1:])
                      and len(colores) > 1,
                      f"slide {k + 1}: primera palabra en blanco y el resto en blue_pale {colores}")
        comprobar(not italica and fuentes == {"Montserrat ExtraBold"},
                  f"slide {k + 1}: ExtraBold sin itálica ({fuentes})")
        if texto == SEPARADOR_LARGO:
            # No entra en una línea ni a 32 pt: dos líneas, con su interlineado apretado.
            dos = titulo.text_frame.paragraphs[0]._p.find(f"{qn('a:pPr')}/{qn('a:lnSpc')}/{qn('a:spcPct')}")
            comprobar(dos is not None and dos.get("val") == "80000" and min(tamanos) >= 64,
                      f"slide {k + 1}: título largo en dos líneas, entre 45 y 32 lógicos ({tamanos})")
        else:
            comprobar(tamanos == {90.0}, f"slide {k + 1}: una línea a 45 lógicos ({tamanos})")

    # 1.4 · títulos de slide a 42
    tamanos = {}
    for k, (s, m) in enumerate(zip(slides, marcas)):
        if m.get("mode") != "redesign" or m.get("layout") in ("section", "closing", "metrics_row"):
            continue
        for sh in s.shapes:
            if sh.name.startswith("title_"):
                tamanos[k + 1] = sorted({r.font.size.pt for p in sh.text_frame.paragraphs for r in p.runs
                                         if r.text.strip()})
    comprobar(tamanos and all(v == [42.0] for v in tamanos.values()), f"títulos de slide a 42 pt: {tamanos}")
    largo = next((k for k, s in enumerate(slides)
                  if any(sh.name.startswith("title_") and TITULO_LARGO in sh.text_frame.text.replace(" ", " ")
                         for sh in s.shapes)), None)
    comprobar(largo is not None and marcas[largo].get("mode") == "redesign",
              "el título largo de dos líneas a 21 no saca la slide del rediseño")
    cifras = next((s for s, m in zip(slides, marcas) if m.get("layout") == "metrics_row"), None)
    if cifras is not None:
        st = [r.font.size.pt for sh in cifras.shapes if sh.name.startswith("title_")
              for p in sh.text_frame.paragraphs for r in p.runs if r.text.strip()]
        print(f"info  metrics_row usa el estilo statement: {sorted(set(st))} pt")


def comprobar_revisar(rev: dict) -> None:
    hallazgos = [h for h in rev.get("hallazgos", []) if h["codigo"] == "titulo_dos_lineas"]
    por_slide = {h["slide"] for h in hallazgos}
    comprobar(5 in por_slide, f"revisar: titulo_dos_lineas en la slide del título largo ({sorted(por_slide)})")
    comprobar(not por_slide & {1, 2, 3, 7}, "revisar: sin titulo_dos_lineas en portada, separadores ni títulos cortos")
    h5 = next((h for h in hallazgos if h["slide"] == 5), None)
    if h5:
        m = h5.get("medida", {})
        comprobar(m.get("lineas") == 2 and m.get("necesario_pt", 0) > m.get("disponible_pt", 1),
                  f"revisar: el detalle trae el ancho necesario y el disponible ({h5['detalle']})")


def comprobar_leer(lectura: dict) -> None:
    elementos = {e["id"]: e for s in lectura["slides"] for e in s["elementos"]}
    corto, largo, parrafo = elementos.get("s2:t1", {}), elementos.get("s5:t1", {}), elementos.get("s7:t4", {})
    comprobar(corto.get("cabe_como_titulo") is True and 0 < corto.get("ancho_titulo_pt", 0) < 611,
              f"leer: «Quiénes somos» cabe como título ({corto.get('ancho_titulo_pt')} pt)")
    comprobar(largo.get("cabe_como_titulo") is False and largo.get("ancho_titulo_pt", 0) > 611,
              f"leer: el título largo no cabe en una línea ({largo.get('ancho_titulo_pt')} pt)")
    comprobar("cabe_como_titulo" not in parrafo, "leer: un párrafo de más de 25 palabras no se mide como título")


def comprobar_flecha(tmp: Path) -> None:
    sys.path.insert(0, str(SKILL / "scripts"))
    from neo_skill.ajustes import flecha_escuadra

    prs = Presentation()
    prs.slide_width, prs.slide_height = Emu(1440 * PT), Emu(810 * PT)
    s = prs.slides.add_slide(prs.slide_layouts[6])
    paso1 = s.shapes.add_shape(1, Emu(200 * PT), Emu(200 * PT), Emu(600 * PT), Emu(100 * PT))
    paso2 = (300, 340, 400, 100)        # embudo: debajo, más angosto y más a la izquierda
    derecha = (1000, 400, 200, 80)      # a la derecha y más abajo
    casos = [(flecha_escuadra(s, paso1, paso2), (700 + 6, 390), "embudo"),
             (flecha_escuadra(s, paso1, derecha, color="000033", grosor_pt=2, separacion_pt=10), (990, 440), "en Z")]
    for flecha, punta, nombre in casos:
        geo = flecha._element.find(f".//{qn('a:custGeom')}")
        path = geo.find(f".//{qn('a:path')}")
        x0, y0 = flecha.left / PT, flecha.top / PT
        sx, sy = flecha.width / PT / max(int(path.get("w")), 1), flecha.height / PT / max(int(path.get("h")), 1)
        puntos = [(x0 + int(pt.get("x")) * sx, y0 + int(pt.get("y")) * sy)
                  for pt in path.iter(qn("a:pt"))]
        ortogonal = all(abs(a[0] - b[0]) < 0.05 or abs(a[1] - b[1]) < 0.05 for a, b in zip(puntos, puntos[1:]))
        ln = flecha._element.find(f".//{qn('a:ln')}")
        cola = ln.find(qn("a:tailEnd"))
        fin = puntos[-1]
        comprobar(ortogonal and len(puntos) >= 3 and cola is not None and cola.get("type") == "triangle"
                  and abs(fin[0] - punta[0]) < 0.1 and abs(fin[1] - punta[1]) < 0.1
                  and flecha._element.find(qn("p:style")) is None,
                  f"flecha_escuadra ({nombre}): ortogonal, con punta, termina a la separación ({puntos})")
    color = casos[1][0].line.color.rgb
    comprobar(str(color) == "000033" and abs(casos[1][0].line.width.pt - 2) < 0.01, "flecha_escuadra: color y grosor")
    prs.save(str(tmp / "flechas.pptx"))
    reabierta = Presentation(str(tmp / "flechas.pptx"))
    comprobar(len(reabierta.slides[0].shapes) == 3, "flecha_escuadra: el archivo se guarda y se vuelve a abrir")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="neo-marca-") as tmp:
        t = Path(tmp)
        crear_deck(t / "deck.pptx")
        (t / "plan.json").write_text(json.dumps(PLAN, ensure_ascii=False), encoding="utf-8")

        neo("leer", "deck.pptx", "--out", "lectura", "--sin-imagenes", cwd=t)
        if (t / "lectura" / "lectura.json").exists():
            comprobar_leer(json.loads((t / "lectura" / "lectura.json").read_text(encoding="utf-8")))

        red = neo("redisenar", "deck.pptx", "--plan", "plan.json", "--out", "v1.pptx", cwd=t)
        comprobar(red.get("ok") is True and not red.get("no_cupieron"),
                  f"redisenar: sin slides que no cupieron ({red.get('no_cupieron')})")
        if (t / "v1_report.json").exists():
            reporte = json.loads((t / "v1_report.json").read_text(encoding="utf-8"))
            avisos = {s["slide"]: [i.get("detail") for i in s.get("issues", [])] for s in reporte.get("slides", [])}
            comprobar("separator_title_two_lines" in avisos.get(8, []) and
                      not any("separator_title_two_lines" in v for n, v in avisos.items() if n != 8),
                      f"redisenar: separator_title_two_lines solo en el separador largo ({avisos.get(8)})")
        if (t / "v1.pptx").exists():
            comprobar_salida(t / "v1.pptx")
            comprobar_revisar(neo("revisar", "v1.pptx", cwd=t))
            ver = neo("verificar", "deck.pptx", "v1.pptx", cwd=t)
            comprobar(ver.get("ok") is True, f"verificar: el contenido sigue completo ({ver.get('slides')})")
        comprobar_flecha(t)

    if fallas:
        print("\n" + "\n\n".join(fallas))
        sys.exit(1)
    print("\nTodo bien.")


if __name__ == "__main__":
    main()
