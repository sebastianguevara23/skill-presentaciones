"""Mirar por dentro un PPTX: formas, revisión de calidad y verificación del contenido.

- `formas`: qué hay en una slide (posición en pt, letra, colores) para corregirla con código.
- `revisar`: hallazgos con medida y forma afectada. Informa; no bloquea.
- `verificar`: el contenido del original (o del guion) sigue completo y visible. Es la única
  comprobación que decide si se entrega.
"""
from __future__ import annotations

import math
import re
import tempfile
from collections import Counter
from pathlib import Path

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.util import Emu

from neo_refactor.integrity import check as integrity_check
from neo_refactor.knowledge import ROOT, Knowledge
from neo_refactor.parser import parse_deck
from neo_refactor.renderer import BRAND_PREFIX

EMU_PT = 12700
EMOJI = re.compile("[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F2FF\U0001F900-\U0001F9FF️]")


def _pt(v) -> float:
    return round((v or 0) / EMU_PT, 1)


# ---------------------------------------------------------------- formas

def _hex(fill) -> str | None:
    try:
        if fill.type == 1:  # MSO_FILL.SOLID
            return str(fill.fore_color.rgb)
    except (AttributeError, TypeError, ValueError):
        return None
    return None


def _texto(shape) -> dict | None:
    if not getattr(shape, "has_text_frame", False) or not shape.text_frame.text.strip():
        return None
    tamanos, fuentes, colores, negrita = Counter(), Counter(), Counter(), False
    for p in shape.text_frame.paragraphs:
        for r in p.runs:
            if not r.text.strip():
                continue
            if r.font.size:
                tamanos[r.font.size.pt] += len(r.text)
            if r.font.name:
                fuentes[r.font.name] += len(r.text)
            try:
                if r.font.color and r.font.color.type is not None and r.font.color.rgb is not None:
                    colores[str(r.font.color.rgb)] += len(r.text)
            except (AttributeError, TypeError):
                pass
            negrita = negrita or bool(r.font.bold)
    tf = shape.text_frame
    return {
        "texto": tf.text.strip()[:160],
        "parrafos": sum(1 for p in tf.paragraphs if "".join(r.text for r in p.runs).strip()),
        "tamanos_pt": sorted(tamanos, reverse=True),
        "fuentes": list(fuentes),
        "colores": list(colores),
        "negrita": negrita,
        "ajuste": str(tf.auto_size) if tf.auto_size is not None else None,
        "margenes_pt": [_pt(tf.margin_left), _pt(tf.margin_top), _pt(tf.margin_right), _pt(tf.margin_bottom)],
    }


def _aplanar(shapes, dx=0, dy=0, sx=1.0, sy=1.0, nivel=0):
    """Formas con su caja absoluta en EMU (los grupos se resuelven con su transformación)."""
    for shape in shapes:
        x = dx + (shape.left or 0) * sx
        y = dy + (shape.top or 0) * sy
        w, h = (shape.width or 0) * sx, (shape.height or 0) * sy
        yield shape, (x, y, w, h), nivel
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            xfrm = shape._element.grpSpPr.find("{http://schemas.openxmlformats.org/drawingml/2006/main}xfrm")
            ch_off = xfrm.find("{http://schemas.openxmlformats.org/drawingml/2006/main}chOff") if xfrm is not None else None
            ch_ext = xfrm.find("{http://schemas.openxmlformats.org/drawingml/2006/main}chExt") if xfrm is not None else None
            cx, cy = (int(ch_off.get("x")), int(ch_off.get("y"))) if ch_off is not None else (0, 0)
            cw, chh = (int(ch_ext.get("cx")), int(ch_ext.get("cy"))) if ch_ext is not None else (shape.width, shape.height)
            gsx = w / cw if cw else sx
            gsy = h / chh if chh else sy
            yield from _aplanar(shape.shapes, x - cx * gsx, y - cy * gsy, gsx, gsy, nivel + 1)


def formas(pptx: Path, numero: int) -> dict:
    prs = Presentation(str(pptx))
    if not 1 <= numero <= len(prs.slides):
        raise ValueError(f"la slide {numero} no existe ({len(prs.slides)} slides)")
    slide = prs.slides[numero - 1]
    lista = []
    for z, (shape, (x, y, w, h), nivel) in enumerate(_aplanar(slide.shapes)):
        item = {
            "z": z, "id": shape.shape_id, "nombre": shape.name, "nivel": nivel,
            "tipo": str(shape.shape_type).split(".")[-1].split(" ")[0] if shape.shape_type else "?",
            "caja_pt": [_pt(x), _pt(y), _pt(w), _pt(h)],
        }
        if shape.rotation:
            item["rotacion"] = shape.rotation
        if shape.name.startswith(BRAND_PREFIX):
            item["marca"] = True
        if hasattr(shape, "fill"):
            relleno = _hex(shape.fill)
            if relleno:
                item["relleno"] = relleno
        if hasattr(shape, "line"):
            try:
                if shape.line.fill.type == 1:
                    item["borde"] = [str(shape.line.color.rgb), round(shape.line.width.pt, 2)]
            except (AttributeError, TypeError, ValueError):
                pass
        texto = _texto(shape)
        if texto:
            item.update(texto)
        if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
            try:
                item["imagen_px"] = list(shape.image.size)
            except (AttributeError, ValueError):
                pass
        lista.append(item)
    return {"slide": numero, "lienzo_pt": [_pt(prs.slide_width), _pt(prs.slide_height)], "formas": lista}


# ---------------------------------------------------------------- revisar

def _interseccion(a, b) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    w = min(ax + aw, bx + bw) - max(ax, bx)
    h = min(ay + ah, by + bh) - max(ay, by)
    return w * h if w > 0 and h > 0 else 0.0


def _alto_necesario(shape, ancho_pt: float) -> float | None:
    """Alto que pide el texto con las métricas de Montserrat (None si no es Montserrat)."""
    from neo_refactor.schemas import RPara, RRun
    from neo_refactor.textmetrics import block_height

    parrafos = []
    for p in shape.text_frame.paragraphs:
        runs = []
        for r in p.runs:
            nombre = (r.font.name or "Montserrat")
            if "montserrat" not in nombre.lower():
                return None
            tam = r.font.size.pt if r.font.size else 18.0
            runs.append(RRun(text=r.text, font=nombre, size=tam, bold=bool(r.font.bold),
                             italic=bool(r.font.italic), color="000000"))
        if not runs:
            runs = [RRun(text=" ", font="Montserrat", size=11.0, color="000000")]
        linea = 1.0
        try:
            if p.line_spacing and isinstance(p.line_spacing, float):
                linea = p.line_spacing
        except (AttributeError, ValueError):
            pass
        parrafos.append(RPara(runs=runs, line=linea))
    return block_height(parrafos, ancho_pt)


def _luminancia(hex6: str) -> float:
    def canal(v: int) -> float:
        c = v / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (int(hex6[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * canal(r) + 0.7152 * canal(g) + 0.0722 * canal(b)


def _contraste(a: str, b: str) -> float:
    la, lb = sorted((_luminancia(a), _luminancia(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _color_imagen(shape) -> str | None:
    try:
        from io import BytesIO

        from PIL import Image
        img = Image.open(BytesIO(shape.image.blob)).convert("RGB").resize((24, 24))
        px = list(img.getdata())
        r, g, b = (sum(c[i] for c in px) // len(px) for i in range(3))
        return f"{r:02X}{g:02X}{b:02X}"
    except Exception:  # noqa: BLE001
        return None


def _fondo_bajo(caja, planas, z_texto, W, H) -> str:
    """Color de lo que hay debajo de un texto: la card que lo contiene o el fondo de la slide."""
    debajo = "FFFFFF"
    for z, (forma, cf, _nivel) in enumerate(planas):
        if z >= z_texto or forma.shape_type == MSO_SHAPE_TYPE.GROUP:
            continue
        area = caja[2] * caja[3] or 1
        if _interseccion(caja, cf) / area < 0.8:
            continue
        if forma.shape_type == MSO_SHAPE_TYPE.PICTURE:
            if cf[2] * cf[3] >= 0.8 * W * H:
                debajo = _color_imagen(forma) or debajo
        elif hasattr(forma, "fill") and _hex(forma.fill):
            debajo = _hex(forma.fill)
    return debajo


def revisar(pptx: Path, slides: list[int] | None = None) -> dict:
    """Hallazgos medibles por slide. Ninguno bloquea: son para decidir qué corregir."""
    from neo_refactor.audit.brand import inspect_slide

    prs = Presentation(str(pptx))
    kn = Knowledge(ROOT)
    escala = prs.slide_width / EMU_PT / kn.tokens["canvas"]["width"]
    minimo = kn.min_size * escala
    W, H = prs.slide_width, prs.slide_height
    elegidas = set(slides or range(1, len(prs.slides) + 1))
    hallazgos = []

    def add(n, codigo, forma, detalle, medida=None):
        hallazgos.append({"slide": n, "codigo": codigo, "forma": forma, "detalle": detalle,
                          **({"medida": medida} if medida else {})})

    for n, slide in enumerate(prs.slides, 1):
        if n not in elegidas:
            continue
        for issue in inspect_slide(slide, n, kn, escala):
            add(n, issue.code, issue.shape, issue.symptom, issue.measurement)
        planas = list(_aplanar(slide.shapes))
        textos = []
        for z, (shape, caja, _nivel) in enumerate(planas):
            nombre = shape.name
            if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
                continue
            x, y, w, h = caja
            fuera = max(-x, -y, x + w - W, y + h - H, 0) / EMU_PT
            if fuera > 2 and not nombre.startswith(BRAND_PREFIX) and w < W * 1.05:
                add(n, "fuera_del_lienzo", nombre, f"sale {fuera:.0f} pt del borde de la slide")
            if getattr(shape, "has_text_frame", False) and shape.text_frame.text.strip():
                texto = shape.text_frame.text
                if EMOJI.search(texto):
                    add(n, "emoji", nombre, "el texto tiene emojis (la marca no los usa)")
                chicos = sorted({r.font.size.pt for p in shape.text_frame.paragraphs for r in p.runs
                                 if r.text.strip() and r.font.size and r.font.size.pt < minimo - 0.05})
                if chicos and not nombre.startswith(BRAND_PREFIX):
                    add(n, "letra_bajo_minimo", nombre, f"letra de {chicos[0]:g} pt; el mínimo es {minimo:g} pt",
                        {"min_pt": chicos[0], "minimo_pt": round(minimo, 1)})
                tf = shape.text_frame
                ancho = (w - (tf.margin_left or 0) - (tf.margin_right or 0)) / EMU_PT
                alto = (h - (tf.margin_top or 0) - (tf.margin_bottom or 0)) / EMU_PT
                necesario = _alto_necesario(shape, ancho) if ancho > 0 and tf.word_wrap is not False else None
                if necesario and necesario > alto * 1.08 + 2 and not nombre.startswith(BRAND_PREFIX):
                    add(n, "texto_desborda", nombre, f"el texto pide {necesario:.0f} pt de alto y la caja tiene {alto:.0f}",
                        {"necesario_pt": round(necesario), "caja_pt": round(alto)})
                if not nombre.startswith(BRAND_PREFIX):
                    textos.append((z, shape, caja))
                    fondo = _fondo_bajo(caja, planas, z, W, H)
                    colores = {str(r.font.color.rgb) for p in shape.text_frame.paragraphs for r in p.runs
                               if r.text.strip() and r.font.color is not None and r.font.color.type is not None
                               and getattr(r.font.color, "rgb", None) is not None}
                    malos = sorted((c, round(_contraste(c, fondo), 1)) for c in colores
                                   if len(c) == 6 and _contraste(c, fondo) < 3.0)
                    if malos:
                        add(n, "contraste_bajo", nombre, f"texto {malos[0][0]} sobre {fondo}: contraste {malos[0][1]}:1 "
                            "(mínimo 3:1; en fondo claro usa navy 000033 o azul 2D5BFF)",
                            {"color": malos[0][0], "fondo": fondo, "contraste": malos[0][1]})
        for i, (za, a, ca) in enumerate(textos):
            for zb, b, cb in textos[i + 1:]:
                inter = _interseccion(ca, cb)
                menor = min(ca[2] * ca[3], cb[2] * cb[3]) or 1
                if inter / menor > 0.15:
                    add(n, "textos_encimados", f"{a.name} / {b.name}", f"se pisan en un {100 * inter / menor:.0f} %")
        for z, shape, caja in textos:
            for zo, (otra, co, _nv) in enumerate(planas):
                if zo <= z or otra.shape_type == MSO_SHAPE_TYPE.GROUP or otra.name.startswith(BRAND_PREFIX):
                    continue
                opaca = (otra.shape_type == MSO_SHAPE_TYPE.PICTURE or getattr(otra, "has_chart", False)
                         or getattr(otra, "has_table", False) or (hasattr(otra, "fill") and _hex(otra.fill)))
                if not opaca or (getattr(otra, "has_text_frame", False) and otra.text_frame.text.strip()):
                    continue
                inter = _interseccion(caja, co)
                if caja[2] * caja[3] and inter / (caja[2] * caja[3]) > 0.25:
                    add(n, "texto_tapado", shape.name, f"«{otra.name}» está encima y tapa el {100 * inter / (caja[2] * caja[3]):.0f} % del texto")
    por_codigo = Counter(h["codigo"] for h in hallazgos)
    return {"slides_revisadas": len(elegidas), "total": len(hallazgos), "por_codigo": dict(por_codigo),
            "hallazgos": hallazgos}


# ---------------------------------------------------------------- verificar

def _palabras(spec_slides, saltar_marca=True) -> Counter:
    c: Counter = Counter()
    for s in spec_slides:
        for t in s.texts:
            if saltar_marca and t.name.startswith(BRAND_PREFIX):
                continue
            for p in t.paragraphs:
                for w in re.findall(r"[\wáéíóúñü%$€.,:/+-]+", p.text.lower()):
                    w = w.strip(".,:")
                    if w:
                        c[w] += 1
    return c


def _cifras(c: Counter) -> Counter:
    return Counter({w: n for w, n in c.items() if re.search(r"\d", w)})


def verificar(original: Path, candidato: Path, reporte: dict | None = None,
              cierre_canonico: list[str] | None = None) -> dict:
    """¿El contenido del original sigue completo, sin inventos y visible?

    Con el reporte del motor (mapa slide de origen → slides de salida) compara slide por slide;
    sin él, compara el deck entero. El cierre canónico de marca y las formas NEO_BRAND no cuentan.
    """
    with tempfile.TemporaryDirectory(prefix="neo-ver-") as tmp:
        src = parse_deck(original, Path(tmp) / "a")
        out = parse_deck(candidato, Path(tmp) / "b")
    cierre = Counter()
    for linea in cierre_canonico or []:
        for w in re.findall(r"[\wáéíóúñü%$€.,:/+-]+", linea.lower()):
            w = w.strip(".,:")
            if w:
                cierre[w] += 1
    resultado: dict = {"modo": None, "conservado": True, "slides": [], "faltan": [], "sobran": [],
                       "cifras_cambiadas": 0, "imagenes_faltantes": 0}
    # Sin reporte del motor (un PPTX editado a mano o armado con código) se compara el deck entero.
    mapa = ((reporte or {}).get("source_output_mapping") or {}).get("slides") or []
    por_slide = {s["slide"]: s for s in (reporte or {}).get("slides", [])}
    if mapa:
        resultado["modo"] = "por_slide"
        salida = {s.index: s for s in out.slides}
        fuentes = {s.index: s for s in src.slides}
        for entrada in mapa:
            idx = int("".join(ch for ch in entrada["source_slide_id"] if ch.isdigit()))
            outs = entrada.get("output_slide_indices") or []
            fuente = fuentes.get(idx)
            info = por_slide.get(idx, {})
            ci_motor = info.get("content_integrity") or {}
            if fuente is None or fuente.hidden or info.get("mode") == "hidden" or ci_motor.get("policy_exception"):
                continue
            producidas = [salida[i] for i in outs if i in salida]
            if not producidas:
                resultado["slides"].append({"slide": idx, "conservado": False, "detalle": "no aparece en el resultado"})
                resultado["conservado"] = False
                continue
            saltar = set(ci_motor.get("removed_on_purpose") or [])
            repetidos = {eid for eid, dest in (entrada.get("element_destinations") or {}).items() if len(dest) > 1}
            r = integrity_check(fuente, producidas if len(producidas) > 1 else producidas[0],
                                skip_ids=saltar, granular=True, repeated_ids=repetidos)
            if not r["preserved"]:
                resultado["conservado"] = False
                resultado["slides"].append({"slide": idx, "conservado": False, "salida": outs,
                                            "faltan": r["removed_content"][:12], "sobran": r["modified_content"][:12],
                                            "cifras_cambiadas": r["numeric_changes"],
                                            "imagenes_faltantes": len(r["images_missing"]),
                                            "graficos_cambiados": r.get("charts_changed", 0)})
    else:
        resultado["modo"] = "deck_completo"
        a = _palabras([s for s in src.slides if not s.hidden])
        # El cierre canónico va en formas NEO_BRAND: ya queda fuera de la cuenta.
        b = _palabras(out.slides)
        faltan, sobran = a - b, b - a
        resultado["faltan"] = sorted(faltan.elements())[:40]
        resultado["sobran"] = sorted(sobran.elements())[:40]
        resultado["cifras_cambiadas"] = sum(((_cifras(a) - _cifras(b)) + (_cifras(b) - _cifras(a))).values())
        img_a = Counter(i.sha for s in src.slides if not s.hidden for i in s.images)
        img_b = Counter(i.sha for s in out.slides for i in s.images)
        resultado["imagenes_faltantes"] = sum((img_a - img_b).values())
        resultado["conservado"] = not faltan and not sobran and resultado["imagenes_faltantes"] == 0
    tapados = [h for h in revisar(candidato)["hallazgos"] if h["codigo"] in ("texto_tapado", "emoji")]
    resultado["textos_tapados"] = [h for h in tapados if h["codigo"] == "texto_tapado"]
    resultado["emojis"] = [h for h in tapados if h["codigo"] == "emoji"]
    resultado["ok"] = resultado["conservado"] and not resultado["textos_tapados"]
    return resultado
