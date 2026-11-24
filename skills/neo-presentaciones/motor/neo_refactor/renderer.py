"""Dibuja sobre el deck original (in place): conserva todas las slides, su orden, notas y ocultas.

Las slides rediseñadas se vacían y se redibujan con lo que decidió el composer; el resto
lo maneja shell.py. Sin lógica de diseño aquí.
"""
from __future__ import annotations

from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Pt

from .schemas import RenderedSlide, RPicture, RRect, RText

BRAND_PREFIX = "NEO_BRAND"
_ALIGN = {"l": PP_ALIGN.LEFT, "ctr": PP_ALIGN.CENTER, "r": PP_ALIGN.RIGHT}
_ANCHOR = {"t": MSO_ANCHOR.TOP, "ctr": MSO_ANCHOR.MIDDLE, "b": MSO_ANCHOR.BOTTOM}
_SHAPE_TAGS = {qn(t) for t in ("p:sp", "p:pic", "p:grpSp", "p:graphicFrame", "p:cxnSp", "p:contentPart")}


def _rgb(hex_: str) -> RGBColor:
    return RGBColor.from_string(hex_)


# Factor del lienzo lógico (720×405 pt) al de la salida (1920×1080 px = 1440×810 pt).
# El composer trabaja en coordenadas lógicas y el renderer las escala al PPTX final.
_SCALE = [1.0]


def _pt(value: float):
    return Pt(value * _SCALE[0])


def add_picture(slide, el: RPicture, name: str):
    pic = slide.shapes.add_picture(el.path, _pt(el.box.x), _pt(el.box.y), _pt(el.box.w), _pt(el.box.h))
    pic.crop_left, pic.crop_top, pic.crop_right, pic.crop_bottom = el.crop
    if el.shape == "ellipse":
        pic._element.spPr.find(qn("a:prstGeom")).set("prst", "ellipse")
    if el.line:
        pic.line.color.rgb = _rgb(el.line)
        pic.line.width = _pt(el.line_width)
    pic.name = name
    return pic


def add_arrow_path(slide, x: float, y: float, w: float, color: str, width: float, name: str,
                   head: float = 4.0):
    """Flecha lineal (→) de un solo trazo: asta y punta abierta en la misma forma, con extremos
    y uniones redondeados. Un conector con `tailEnd` dibuja la punta aparte y se ve partida."""
    b = slide.shapes.build_freeform(_pt(x), _pt(y), scale=1.0)
    b.add_line_segments([(_pt(x + w), _pt(y)), (_pt(x + w - head), _pt(y - head))], close=False)
    b.move_to(_pt(x + w), _pt(y))
    b.add_line_segments([(_pt(x + w - head), _pt(y + head))], close=False)
    sh = b.convert_to_shape()
    sh.fill.background()
    sh.line.color.rgb = _rgb(color)
    sh.line.width = _pt(width)
    ln = sh.line._get_or_add_ln()
    ln.set("cap", "rnd")
    ln.append(ln.makeelement(qn("a:round"), {}))
    sh.shadow.inherit = False
    _drop_theme_style(sh)
    sh.name = name
    return sh


def _drop_theme_style(sh):
    """python-pptx crea formas libres y conectores con `p:style` (effectRef 1: el efecto del
    tema, que LibreOffice dibuja aunque haya `effectLst` vacío). Color y trazo ya son
    explícitos, así que el estilo sobra."""
    style = sh._element.find(qn("p:style"))
    if style is not None:
        sh._element.remove(style)


def _no_theme_effect(sh):
    """`add_shape` deja `p:style` con effectRef 2. PowerPoint lo anula con el `effectLst` vacío,
    pero Google Slides y LibreOffice dibujan la sombra del tema: una card con borde azul salía
    sombreada. Se apaga solo el efecto; fontRef y el resto del estilo siguen."""
    ref = sh._element.find(f"{qn('p:style')}/{qn('a:effectRef')}")
    if ref is not None:
        ref.set("idx", "0")


def _add_line(slide, el: RRect, name: str):
    """Línea divisoria: un conector recto sin punta ni efectos. Una caja más alta que ancha es
    un filete vertical (el que separa el logo NEO del logo del cliente)."""
    from pptx.enum.shapes import MSO_CONNECTOR

    if el.box.h > el.box.w:
        x = el.box.x + el.box.w / 2
        line = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, _pt(x), _pt(el.box.y), _pt(x), _pt(el.box.bottom))
    else:
        y = el.box.y + el.box.h / 2
        line = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, _pt(el.box.x), _pt(y), _pt(el.box.right), _pt(y))
    line.line.color.rgb = _rgb(el.line or el.fill)
    line.line.width = _pt(el.line_width)
    sp_pr = line._element.spPr
    sp_pr.append(sp_pr.makeelement(qn("a:effectLst"), {}))
    _drop_theme_style(line)
    line.name = name
    return line


def add_rect(slide, el: RRect, name: str):
    if el.shape == "diagonal":
        from pptx.enum.shapes import MSO_CONNECTOR
        sh=slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT,_pt(el.box.x),_pt(el.box.y),_pt(el.box.right),_pt(el.box.bottom))
        sh.line.color.rgb=_rgb(el.line)
        sh.line.width=_pt(el.line_width)
        sh.shadow.inherit=False
        _drop_theme_style(sh)
        sh.name=name
        return sh
    if el.shape == "arrow":
        return add_arrow_path(slide, el.box.x, el.box.y + el.box.h / 2, el.box.w, el.line or el.fill,
                              el.line_width, name, head=min(4.0, el.box.h / 2))
    if el.shape == "line":
        return _add_line(slide, el, name)
    if el.shape == "chevron":
        shape_type = MSO_SHAPE.CHEVRON
    elif el.shape == "ellipse":
        shape_type = MSO_SHAPE.OVAL
    else:
        shape_type = MSO_SHAPE.ROUNDED_RECTANGLE if el.radius else MSO_SHAPE.RECTANGLE
    sh = slide.shapes.add_shape(shape_type, _pt(el.box.x), _pt(el.box.y), _pt(el.box.w), _pt(el.box.h))
    if el.radius and el.shape == "rect":
        sh.adjustments[0] = min(0.5, el.radius / min(el.box.w, el.box.h))
    if el.fill:
        sh.fill.solid()
        sh.fill.fore_color.rgb = _rgb(el.fill)
        if el.alpha is not None and el.alpha < 1:
            # Color de la paleta con alfa (`a:alpha`): la auditoría lo sigue leyendo como el token.
            color = sh._element.spPr.find(qn("a:solidFill"))[0]
            color.append(color.makeelement(qn("a:alpha"), {"val": str(round(el.alpha * 100000))}))
    else:
        sh.fill.background()
    if el.line:
        sh.line.color.rgb = _rgb(el.line)
        sh.line.width = _pt(el.line_width)
    else:
        sh.line.fill.background()
    sh.shadow.inherit = False
    _no_theme_effect(sh)
    if el.shadow:
        _outer_shadow(sh, el.shadow)
    sh.name = name
    return sh


def _outer_shadow(sh, spec: dict):
    """Sombra exterior explícita (la de la card blanca sin borde de la referencia)."""
    effects = sh._element.spPr.find(qn("a:effectLst"))
    shadow = effects.makeelement(qn("a:outerShdw"), {
        "blurRad": str(int(_pt(spec["blur_pt"]))), "dist": str(int(_pt(spec["distance_pt"]))),
        "dir": str(int(spec.get("direction_deg", 90) * 60000)), "rotWithShape": "0",
    })
    color = shadow.makeelement(qn("a:srgbClr"), {"val": spec["color"]})
    color.append(color.makeelement(qn("a:alpha"), {"val": str(int(spec["alpha_pct"] * 1000))}))
    shadow.append(color)
    effects.append(shadow)


def add_text(slide, el: RText, name: str):
    tb = slide.shapes.add_textbox(_pt(el.box.x), _pt(el.box.y), _pt(el.box.w), _pt(el.box.h))
    tb.name = name
    tf = tb.text_frame
    tf.word_wrap = True
    tf.auto_size = MSO_AUTO_SIZE.NONE
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = _ANCHOR[el.anchor]
    for k, para in enumerate(el.paras):
        p = tf.paragraphs[0] if k == 0 else tf.add_paragraph()
        p.alignment = _ALIGN[para.align]
        p.line_spacing = para.line
        p.space_before = _pt(para.space_before)
        p.space_after = Pt(0)
        if para.bullet:
            _bullet(p, para.indent, para.numbering, para.start_at)
        for run in para.runs:
            for j, seg in enumerate(run.text.split("\n")):
                if j > 0:
                    p._p.add_br()
                if not seg:
                    continue
                r = p.add_run()
                r.text = seg
                f = r.font
                f.name = run.font
                f.size = _pt(run.size)
                f.bold = run.bold
                f.italic = run.italic
                f.color.rgb = _rgb(run.color)
                if run.hyperlink:
                    r.hyperlink.address = run.hyperlink
    return tb


def _bullet(p, indent: float, numbering: str | None = None, start_at: int | None = None):
    """Viñeta del autor: marca en la sangría, colgada, con la viñeta de marca (`BULLET`). Con
    `numbering`, la numeración automática del autor (`1.`, `a)`…) en vez de «•»."""
    ppr = p._p.get_or_add_pPr()
    ppr.set("marL", str(int(_pt(indent))))
    ppr.set("indent", str(-int(_pt(indent if numbering else min(indent, 10.0)))))
    write_bullet(ppr, numbering, start_at)


# Viñeta de marca (`tokens.yaml` → `brand_rules.bullet`): «•» en Arial, azul NEO y al 100 % del
# texto. Sin `buClr` ni `buSzPct` la viñeta tomaba el navy y el tamaño del texto (deck de
# cliente, 2026-11-23). El renderer no lee tokens: `brand_fix` pasa el color resuelto.
BULLET = {"char": "•", "font": "Arial", "color": "2D5BFF", "size_pct": 100}
# Hijos de viñeta de `a:pPr` / `a:lvlNpPr`, y los que el esquema (CT_TextParagraphProperties)
# pone después: lnSpc, spcBef, spcAft, buClr*, buSz*, buFont*, buNone|buAutoNum|buChar|buBlip,
# tabLst, defRPr, extLst. PowerPoint rechaza el archivo si una viñeta va después de `defRPr`.
BULLET_TAGS = tuple(qn(f"a:{t}") for t in ("buClrTx", "buClr", "buSzTx", "buSzPct", "buSzPts",
                                           "buFontTx", "buFont", "buNone", "buAutoNum", "buChar", "buBlip"))
_AFTER_BULLET = frozenset(qn(f"a:{t}") for t in ("tabLst", "defRPr", "extLst"))


def bullet_nodes(ppr, numbering: str | None = None, start_at: int | None = None,
                 color: str = BULLET["color"], marker: bool = True) -> list:
    """Hijos de la viñeta de marca en el orden del esquema: color, tamaño y, con `marker`, la
    marca («•» en Arial, o `buAutoNum` sin `buFont`: el número usa la letra del texto)."""
    clr = ppr.makeelement(qn("a:buClr"), {})
    clr.append(clr.makeelement(qn("a:srgbClr"), {"val": color.upper()}))
    nodes = [clr, ppr.makeelement(qn("a:buSzPct"), {"val": str(int(BULLET["size_pct"] * 1000))})]
    if not marker:
        return nodes
    if numbering:
        return [*nodes, ppr.makeelement(qn("a:buAutoNum"), {"type": numbering, **(
            {"startAt": str(start_at)} if start_at else {})})]
    return [*nodes, ppr.makeelement(qn("a:buFont"), {"typeface": BULLET["font"]}),
            ppr.makeelement(qn("a:buChar"), {"char": BULLET["char"]})]


def place_bullet(ppr, nodes: list) -> None:
    """Quita la viñeta que tenga `ppr` y escribe `nodes` en su lugar del esquema: después de
    lnSpc/spcBef/spcAft y antes de tabLst/defRPr/extLst."""
    for child in [c for c in ppr if c.tag in BULLET_TAGS]:
        ppr.remove(child)
    anchor = next((child for child in ppr if child.tag in _AFTER_BULLET), None)
    for node in nodes:
        if anchor is None:
            ppr.append(node)
        else:
            anchor.addprevious(node)


def write_bullet(ppr, numbering: str | None = None, start_at: int | None = None,
                 color: str = BULLET["color"]) -> None:
    """Viñeta de marca completa en `ppr` (un `a:pPr` o `a:lvlNpPr`)."""
    place_bullet(ppr, bullet_nodes(ppr, numbering, start_at, color))


def add_element(slide, el, index: int):
    name = f"{BRAND_PREFIX}_{el.role}" if getattr(el, "brand", False) else f"{el.role}_{index}"
    return {"picture": add_picture, "rect": add_rect, "text": add_text}[el.kind](slide, el, name)


def send_to_back(shape):
    sp_tree = shape._element.getparent()
    sp_tree.remove(shape._element)
    sp_tree.insert(2, shape._element)  # después de nvGrpSpPr y grpSpPr


def add_background(slide, path: str, width, height):
    bg = slide.shapes.add_picture(path, 0, 0, width, height)
    bg.name = f"{BRAND_PREFIX}_background"
    send_to_back(bg)
    return bg


def set_scale(scale: float) -> None:
    """Lienzo canónico → slide real para lo que se dibuja fuera de `redraw` (la marca del
    brand shell). Antes el shell heredaba la escala del último `redraw`, o 1.0 si no hubo."""
    _SCALE[0] = scale


def redraw(slide, rs: RenderedSlide, width, height, scale: float = 1.0):
    """Vacía la slide (las notas se conservan) y dibuja la especificación del composer.

    `scale` lleva el lienzo canónico al tamaño real de la slide cuando no coinciden.
    """
    set_scale(scale)
    sp_tree = slide.shapes._spTree
    for el in list(sp_tree):
        if el.tag in _SHAPE_TAGS:
            sp_tree.remove(el)
    add_background(slide, rs.background, width, height)
    for k, el in enumerate(rs.elements):
        add_element(slide, el, k)
