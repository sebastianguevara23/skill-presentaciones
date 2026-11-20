"""Reusable NEO policies approved against the Referencia v2 review (2026-09-30)."""
from __future__ import annotations

import re
from io import BytesIO

from PIL import Image, ImageStat
from pptx.dml.color import RGBColor
from pptx.oxml.xmlchemy import OxmlElement
from pptx.util import Pt

from . import cobrand
from .schemas import Box, RenderedSlide, RPara, RPicture, RRect, RRun, RText
from .slide_marker import read_marker, write_marker


def _box(values):
    return Box(x=values[0], y=values[1], w=values[2], h=values[3])


def closing_rendered(kn, source_index=0, notes="", client_logo=None):
    rule = kn.tokens["brand_rules"]["closing"]
    brand = kn.tokens["brand"]
    para = RPara(align="ctr", line=1.0, runs=[RRun(
        text=rule["text"], font="Montserrat", size=rule["text_size"],
        bold=True, color=kn.color("navy"))])
    footer = RPara(runs=[RRun(text=brand["phrase"]["text"], font="Montserrat",
                              size=12, bold=True, color=kn.color("blue"))])
    # Con logo del cliente, la despedida lleva el bloque NEO | cliente centrado donde va el logo.
    logo = (cobrand.elements(kn, client_logo, _box(rule["logo_box"]), "light", align="center")
            if client_logo is not None else
            [RPicture(role="brand_logo", box=_box(rule["logo_box"]),
                      path=kn.path(brand["logo"]["light"]), group="brand", brand=True)])
    return RenderedSlide(source_index=source_index, layout="closing", mode="light",
        background=kn.path(brand["backgrounds"]["light"]), notes=notes, elements=[
            *logo,
            RText(role="closing_copy", box=_box(rule["text_box"]),
                  paras=[para], group="brand", brand=True),
            RRect(role="closing_underline", box=_box(rule["underline_box"]),
                  fill=None, line=kn.color("blue"), line_width=0.6, shape="line", group="decorative"),
            RText(role="brand_phrase", box=_box(brand["phrase"]["box"]),
                  paras=[footer], group="brand", brand=True),
        ])


def separator_companion(kn):
    color = kn.color("separator_blue")
    return [
        RRect(role="separator_companion", shape="rect", fill=None, line=color, line_width=1.2,
              box=Box(x=450,y=148,w=100,h=100),group="decorative"),
        RRect(role="separator_companion", shape="diagonal", fill=None, line=color, line_width=1.2,
              box=Box(x=450,y=148,w=100,h=100),group="decorative"),
        RRect(role="separator_companion", shape="ellipse", fill=None, line=color, line_width=1.2,
              box=Box(x=560,y=148,w=100,h=100),group="decorative"),
    ]


def keep_white_card_variant(rendered, spec, kn):
    """Conserva la variante de card blanca del original: con sombra si el autor la usaba.

    La marca admite dos (`brand_rules.white_card`): borde azul o sombra. El compositor dibujaba
    siempre la de borde y las cards blancas con sombra del original salían con borde azul
    (feedback de cliente, 2026-10-01). La sombra se normaliza a la medida oficial (`shadows.card`).
    """
    blocks = [*spec.texts, *spec.shapes]
    if sum(1 for block in blocks if getattr(block, "shadowed", False)) < 2:
        return rendered
    shadow = kn.shadow("card")
    for element in rendered.elements:
        if isinstance(element, RRect) and element.role == "card" and (element.fill or "").upper() == "FFFFFF":
            element.line, element.shadow = None, shadow
    return rendered


def balance_text_cards(rendered, kn):
    """Cards de texto iguales, texto anclado arriba con el mismo padding y la fila centrada en
    el espacio libre bajo el encabezado (que no se mueve)."""
    from . import textmetrics as tm
    cards=[e for e in rendered.elements if isinstance(e,RRect) and e.role=='card']
    if len(cards)<2 or max(c.box.y for c in cards)-min(c.box.y for c in cards)>1:
        return rendered
    if any(isinstance(e,RPicture) and e.group in {c.group for c in cards} for e in rendered.elements):
        return rendered
    if any(e.role.startswith(('banner','note')) for e in rendered.elements):return rendered
    bundles=[]
    for card in cards:
        texts=[e for e in rendered.elements if isinstance(e,RText) and e.group==card.group]
        if len(texts)!=1:return rendered
        text=texts[0]
        height=tm.block_height(text.paras,text.box.w*kn.safety)+4
        bundles.append((card,text,height))
    fit=kn.tokens['brand_rules']['card_content_fit'];pad=fit['padding_pt']
    height=max(h for c,t,h in bundles)+2*pad
    for card,text,h in bundles:
        # Anclado arriba con el mismo padding en todas: el texto de cada card arranca a la misma altura.
        card.box.h=height;text.box.h=h
        text.box.y=card.box.y+((height-h)/2 if fit['center_text_vertically'] else pad)
    _center_below_header(rendered, [*cards, *(t for c, t, h in bundles)], kn)
    return rendered


def _fit_card_heights(rendered, cards, kn, padding):
    """Iguala el alto de la fila al texto más largo más el padding de marca y ancla el texto arriba
    (o lo centra, si `center_text_vertically`).

    Solo cards formadas por la card y sus textos (sin íconos ni cabeceras propias) y que ya
    contienen su texto: si el contenido no cabe, el desborde se declara en otro sitio, no aquí.
    """
    from . import textmetrics as tm
    bundles = []
    for card in cards:
        members = [e for e in rendered.elements if e is not card and getattr(e, "group", None) == card.group]
        texts = [e for e in members if isinstance(e, RText)]
        if not texts or len(texts) != len(members):
            return
        top = min(t.box.y for t in texts)
        bottom = max(t.box.y + tm.block_height(t.paras, t.box.w * kn.safety) for t in texts)
        bundles.append((card, texts, top, bottom - top))
    height = max(content for _c, _t, _top, content in bundles) + 2 * padding
    if height > min(card.box.h for card, *_rest in bundles):
        return
    centered = kn.tokens["brand_rules"]["card_content_fit"]["center_text_vertically"]
    for card, texts, top, content in bundles:
        card.box.h = height
        slack = ((height - 2 * padding) - content) / 2 if centered else 0.0
        shift = card.box.y + padding + slack - top
        for text in texts:
            text.box.y += shift


def center_card_composition(rendered, kn):
    """Centra las cards de una sola fila en el espacio libre bajo el encabezado.

    Es la parte de `card_content_fit` que no depende de cómo se repartan los textos dentro de
    cada card: la rejilla ya dimensiona las cards a su contenido, pero las deja pegadas al
    encabezado aunque sobre alto. Con banner o notas al pie no se mueve nada.
    """
    cards = [e for e in rendered.elements if isinstance(e, RRect) and e.role == "card"]
    if len(cards) < 2 or max(c.box.y for c in cards) - min(c.box.y for c in cards) > 1:
        return rendered
    if any(e.role.startswith(("banner", "note")) for e in rendered.elements):
        return rendered
    fit = kn.tokens["brand_rules"]["card_content_fit"]
    _fit_card_heights(rendered, cards, kn, fit["padding_pt"])
    content = [e for e in rendered.elements
               if not getattr(e, "brand", False) and e.role not in HEADER_ROLES]
    _center_below_header(rendered, content, kn)
    return rendered


HEADER_ROLES = {"kicker", "title", "subtitle"}


def centering_band_bottom(fit: dict, notes_top: float | None, gap: float) -> float:
    """Borde inferior del espacio donde se centra el cuerpo: la banda, o el aire sobre las notas.

    Como `Composer._notes_top`: una nota en la línea del pie (más abajo que la banda) cuenta
    desde el borde de la banda, no desde su propia caja.
    """
    band = fit["composition_band"][1]
    return band if notes_top is None else min(band, notes_top) - gap


def centered_body_top(header_bottom: float, body_top: float, body_bottom: float, band_bottom: float,
                      fit: dict) -> float:
    """Dónde debe arrancar el cuerpo para quedar centrado bajo el encabezado.

    Una sola fórmula para el composer y la auditoría: cada uno tenía la suya (uno centraba la
    región reservada, el otro las cajas dibujadas; uno descontaba las notas, el otro no) y la
    auditoría bloqueaba por 6 pt lo que el motor no sabía corregir (deck de inducción, 2026-10-26).
    Si el cuerpo no cabe con aire, queda a `header_gap_pt` del encabezado.
    """
    area_top = header_bottom + fit["header_gap_pt"]
    return area_top + max(0.0, (band_bottom - area_top - (body_bottom - body_top)) / 2)


def _center_below_header(rendered, content, kn) -> None:
    """Centra el contenido en el espacio libre entre el encabezado y el pie de la banda.

    El encabezado (kicker, título, subtítulo) se queda donde lo pone el layout: antes se
    centraba el conjunto encabezado + cards y el título bajaba (feedback de cliente,
    2026-10-01). Si el contenido no cabe con aire, queda a `header_gap_pt` del encabezado.
    """
    fit = kn.tokens["brand_rules"]["card_content_fit"]
    if not fit.get("center_content_below_header") or not content:
        return
    headings = [e for e in rendered.elements if isinstance(e, RText) and e.role in HEADER_ROLES]
    if not headings:
        return
    # La extensión la dan las cards (lo que se ve); una caja de texto puede ser más alta que su card.
    frame = [e for e in content if isinstance(e, RRect) and e.role == "card"] or content
    top, bottom = min(e.box.y for e in frame), max(e.box.bottom for e in frame)
    delta = centered_body_top(max(e.box.bottom for e in headings), top, bottom,
                              fit["composition_band"][1], fit) - top
    for element in content:
        element.box.y += delta


def cover_emphasis(paragraphs: list[str]) -> str | None:
    """Tramo del título de portada que va en el azul de marca cuando nadie marcó uno.

    En la portada clara la primera palabra va en navy y lo que sigue en azul («Neo
    **Consulting**», pedido de la persona, 2026-10-01). Con un salto del autor, el azul es la
    última línea. Una sola palabra no lleva énfasis. No cambia ninguna palabra.
    """
    lines = [text.strip() for text in paragraphs if text.strip()]
    if len(lines) >= 2:
        return lines[-1]
    match = re.match(r"\S+\s+(\S.*)$", lines[0], re.S) if lines else None
    return match[1].strip() if match else None


def is_light(slide):
    """Read the dominant full-bleed image instead of relying on a theme label."""
    size = slide.part.package.presentation_part.presentation
    area = size.slide_width * size.slide_height
    backgrounds = [s for s in slide.shapes if s.width*s.height >= area*0.9]
    pictures = [s for s in backgrounds if s.shape_type == 13]
    if not pictures:
        for shape in backgrounds:
            try:
                rgb = str(shape.fill.fore_color.rgb)
                return sum(int(rgb[i:i+2],16) for i in (0,2,4))/3 >= 180
            except (AttributeError, TypeError):
                pass
        nodes = slide._element.xpath('./p:cSld/p:bg/p:bgPr/a:solidFill/a:srgbClr')
        if nodes:
            rgb = nodes[0].get('val')
            return sum(int(rgb[i:i+2],16) for i in (0,2,4))/3 >= 180
        return True
    background = max(pictures, key=lambda s: s.width*s.height)
    with Image.open(BytesIO(background.image.blob)) as im:
        rgb = im.convert("RGB").resize((16, 16))
        means = ImageStat.Stat(rgb).mean
    return sum(means)/3 >= 180


def _is_client_logo(shape, client_logo) -> bool:
    import hashlib
    return client_logo is not None and client_logo.matches(hashlib.md5(shape.image.blob).hexdigest())


def light_cover(slide, kn, width, height, client_logo=None):
    """Change only cover brand/background and contrast, retaining source copy.

    Un logo chico arriba pasa a ser el logo NEO vigente, encajado en su caja sin deformarse.
    No se tocan la marca que ya puso el motor (`NEO_BRAND_*`) ni el logo del cliente: antes
    cualquier imagen chica de arriba se volvía un logo NEO estirado, también el del cliente.
    """
    from PIL import Image

    # Con co-marca, el logo NEO es el «NEO» solo del bloque NEO | cliente.
    neo_path = cobrand.neo_logo(kn, "light") if client_logo is not None else kn.path(kn.tokens["brand"]["logo"]["light"])
    with Image.open(neo_path) as im:
        neo_aspect = im.width / im.height
    for shape in list(slide.shapes):
        if shape.shape_type == 13 and shape.width*shape.height >= width*height*0.9:
            shape._element.getparent().remove(shape._element)
        elif (shape.shape_type == 13 and shape.width/width < 0.3 and shape.top/height < 0.2
              and not shape.name.startswith("NEO_BRAND") and not _is_client_logo(shape, client_logo)):
            w, h = shape.width, shape.height
            fw, fh = (w, round(w / neo_aspect)) if w / h <= neo_aspect else (round(h * neo_aspect), h)
            pos = (shape.left + (w - fw) // 2, shape.top + (h - fh) // 2, fw, fh)
            shape._element.getparent().remove(shape._element)
            logo = slide.shapes.add_picture(neo_path, *pos)
            logo.name = "NEO_BRAND_brand_logo"
    bg = slide.shapes.add_picture(kn.path(kn.tokens["brand"]["backgrounds"]["light"]),
                                  0, 0, width=width, height=height)
    bg.name = "NEO_BRAND_background"
    tree = bg._element.getparent()
    tree.remove(bg._element)
    tree.insert(2, bg._element)
    from .knowledge import nearest_color

    # Lo que el autor puso en un azul (el de marca u otro cercano) sigue en el azul de marca:
    # antes solo los celestes pasaban a azul y el azul de marca del autor quedaba navy, con lo
    # que el énfasis de la portada se movía a otro tramo del título (deck de cliente, 2026-11-19).
    palette = [value.upper() for value in kn.tokens["colors"].values()]
    blues = {kn.color(name) for name in ("blue", "blue_soft", "blue_pale", "separator_blue")}
    for shape in slide.shapes:
        if not shape.has_text_frame:
            continue
        for paragraph in shape.text_frame.paragraphs:
            for run in paragraph.runs:
                old = str(run.font.color.rgb) if run.font.color.type == 1 else ""
                blue = shape.text.strip() == "neoconsulting.ai" or (old and nearest_color(old, palette) in blues)
                run.font.color.rgb = RGBColor.from_string("2D5BFF" if blue else "000033")
    emphasize_cover_title(slide)


def _split_run(run, at: int):
    """Parte un run en dos en la posición `at`; devuelve el segundo (mismo formato)."""
    from copy import deepcopy
    tail = deepcopy(run._r)
    run._r.addnext(tail)
    text = run.text
    run.text = text[:at]
    from pptx.text.text import _Run
    second = _Run(tail, run._parent)
    second.text = text[at:]
    return second


def emphasize_cover_title(slide) -> bool:
    """El título de la portada (la caja de letra más grande) con su tramo en azul de marca.

    Solo si el autor no marcó ya algo en azul: entonces manda su énfasis. Parte los runs en el
    borde del tramo; el texto no cambia.
    """
    sized = [(max((run.font.size.pt for p in shape.text_frame.paragraphs for run in p.runs
                   if run.font.size is not None and run.text.strip()), default=0), shape)
             for shape in slide.shapes if shape.has_text_frame and shape.text.strip()
             and shape.text.strip() != "neoconsulting.ai"]
    size, title = max(sized, key=lambda item: item[0], default=(0, None))
    if title is None or size < 24:
        return False
    # El título puede venir en varias cajas del mismo tamaño («Círculo de Gestión» / «de Talento
    # + IA»): si el autor marcó el azul en cualquiera de ellas, manda su énfasis.
    runs = [run for _size, shape in sized if abs(_size - size) < 0.5
            for p in shape.text_frame.paragraphs for run in p.runs]
    if any(run.font.color.type == 1 and str(run.font.color.rgb) == "2D5BFF" for run in runs):
        return False
    # Las posiciones se cuentan sobre los runs: un salto <a:br> no es run y `paragraph.text` lo cuenta.
    joined = lambda paragraph: "".join(run.text for run in paragraph.runs)
    paragraphs = [p for p in title.text_frame.paragraphs if joined(p).strip()]
    phrase = cover_emphasis([joined(p) for p in paragraphs])
    if not phrase:
        return False
    for paragraph in reversed(paragraphs):
        start = joined(paragraph).rfind(phrase)
        if start < 0:
            continue
        end, pos = start + len(phrase), 0
        for run in list(paragraph.runs):
            a, b = pos, pos + len(run.text)
            pos = b
            if b <= start or a >= end:
                continue
            if a < start:
                run, a = _split_run(run, start - a), start
            if b > end:
                _split_run(run, end - a)
            run.font.color.rgb = RGBColor.from_string("2D5BFF")
        return True
    return False


def blank_layout(presentation):
    """Layout del deck con menos placeholders: la despedida se dibuja entera, no hereda cajas.

    El layout 6 de la plantilla por defecto es el vacío, pero un deck real puede traer menos
    de siete layouts o ninguno vacío; se elige el más cercano al vacío sin asumir un índice.
    """
    layouts = list(presentation.slide_layouts)
    return min(layouts, key=lambda layout: len(layout.placeholders))


def ensure_bookends(presentation, kn, client_logo=None):
    """Normalize a cover and append a farewell when the last slide is operational."""
    from .renderer import redraw
    first = presentation.slides[0]
    # Una portada que el compositor ya rediseñó en claro es la portada: no se degrada a
    # brand_shell ni se le vuelve a cambiar el fondo. La política solo corrige lo que no lo es.
    if not ((read_marker(first) or {}).get("mode") == "redesign" and is_light(first)):
        light_cover(first, kn, presentation.slide_width, presentation.slide_height, client_logo)
        write_marker(first, mode="brand_shell", family="title_slide", source="s1", variant="light_cover")
    last = presentation.slides[-1]
    copy = " ".join(s.text for s in last.shapes if s.has_text_frame)
    marker = read_marker(last) or {}
    canonical = kn.tokens["brand_rules"]["closing"]["text"]
    farewell = marker.get("family") == "closing_slide" or canonical in copy or (
        len(copy) < 200 and not any(s.has_table for s in last.shapes) and bool(
            re.search(r"\b(gracias|thank you|thankyou|hasta pronto)\b", copy, re.I)))
    if not farewell:
        last = presentation.slides.add_slide(blank_layout(presentation))
    scale = presentation.slide_width / 12700 / kn.tokens["canvas"]["width"]
    redraw(last, closing_rendered(kn, len(presentation.slides), client_logo=client_logo),
           presentation.slide_width, presentation.slide_height, scale)
    write_marker(last, mode="redesign", family="closing_slide", layout="closing",
                 variant="canonical_light_farewell", brand_generated=True)
    return not farewell


def style_table(shape, kn, scale=2):
    """Explicit cell borders survive Google Slides without default gray grid lines."""
    rule = kn.tokens["brand_rules"]["table"]
    table = shape.table
    table.first_row = False
    table.horz_banding = False
    for row_index, row in enumerate(table.rows):
        for cell in row.cells:
            try:
                fill = str(cell.fill.fore_color.rgb) if cell.fill.type == 1 else "FFFFFF"
            except (AttributeError, TypeError):
                fill = "FFFFFF"
            fill = rule["header_fill"] if row_index == 0 else (
                fill if fill in rule["allowed_fills"] else rule["negative_fill"])
            cell.fill.solid()
            cell.fill.fore_color.rgb = RGBColor.from_string(fill)
            props = cell._tc.get_or_add_tcPr()
            for side in ("L", "R", "T", "B"):
                tag = "a:ln" + side
                for node in list(props):
                    if node.tag == OxmlElement(tag).tag:
                        props.remove(node)
                line = OxmlElement(tag)
                line.set("w", str(round(rule["border_width_pt"]*scale*12700)))
                solid = OxmlElement("a:solidFill")
                color = OxmlElement("a:srgbClr")
                color.set("val", rule["border_color"])
                solid.append(color)
                line.append(solid)
                dash = OxmlElement("a:prstDash")
                dash.set("val", "solid")
                line.append(dash)
                props.append(line)
            for paragraph in cell.text_frame.paragraphs:
                for run in paragraph.runs:
                    run.font.color.rgb = RGBColor.from_string(
                        "FFFFFF" if fill in {"000033", "2D5BFF"} else "000033")

