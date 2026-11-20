"""Independent checks for the policies approved in Referencia v2 (2026-09-30)."""
from __future__ import annotations

from ..design_policies import centered_body_top, centering_band_bottom, is_light
from ..renderer import BRAND_PREFIX
from .. import textmetrics as tm
from .brand import _Colors, _Shape, _fill, _line, _xp
from .core import Finding
from .geometry import elements, is_background
from .render import _rpara

SUBCHECKS = ("bookends", "table_style", "shape_palette", "separator_companion", "card_content_fit")


def card_rows(ctx, slide):
    """Measure content, rather than the deliberately roomy source text boxes."""
    scale = ctx.deck.width / ctx.kn.tokens["canvas"]["width"]
    items = list(elements(ctx, slide.index))
    # Todo texto de la card cuenta para lo que necesita (título, etiquetas y cuerpo apilados);
    # solo las que llevan un texto largo se someten a la regla, como antes.
    texts = [(name, box, block) for name, kind, box, block in items
             if kind == "text" and not name.startswith(BRAND_PREFIX) and block.text.strip()]
    rows = {}
    for name, kind, box, block in items:
        if kind != "shape" or box.w < 85 or box.h < 55 or is_background(box, name, 720, 405):
            continue
        if name.startswith(("matrix_", "head", "cell", "separator_", "NEO_TABLE_")):
            continue
        if any(kind=='image' and box.contains(image_box) for _,kind,image_box,_ in items):
            continue  # Cards with images have their own composition rules.
        children = [(n, b, t) for n, b, t in texts if box.contains(b)]
        if not any(len(t.text.strip()) > 60 for _n, _b, t in children):
            continue
        top, bottom = None, 0.0
        for child_name, text_box, text in children:
            paras = [_rpara(p, ctx.kn.exempt_families, scale) for p in text.paragraphs if p.text.strip()]
            top = text_box.y if top is None else min(top, text_box.y)
            measured = tm.block_height(paras, text_box.w * ctx.kn.safety)
            if slide.redesigned:
                # El PPTX reabierto no trae interlineado ni espacios entre párrafos, y `measured`
                # los ignora: en lo que el motor compuso, la caja ya viene ajustada a su texto
                # (contenido medido con esos espacios + 2 pt), así que esa es la altura real.
                measured = max(measured, text_box.h - 2.0)
            bottom = max(bottom, text_box.y + measured)
        needed = (bottom - top) + 2 * ctx.kn.tokens["brand_rules"]["card_content_fit"]["padding_pt"]
        # El panel lateral (aside) es otro componente: no se compara en tamaño con las cards que
        # tiene al lado en la misma fila (composición libre: cards + panel oscuro).
        kind = "aside" if name.startswith("aside_") else "card"
        rows.setdefault((round(box.y/2)*2, kind), []).append((name, box, needed))
    return list(rows.values())


def _card_header_bottom(items, box) -> float | None:
    """Borde inferior de la cabecera navy de una card (`card_header`), si la tiene."""
    heads = [b for n, k, b, _ in items if k == "shape" and n.startswith("card_header_") and
             not n.startswith("card_header_base") and box.contains(b)]
    return max((b.bottom for b in heads), default=None)


BODY_EXCLUDED = ("kicker_", "title_", "subtitle_", "note_", "tag")


def _body_boxes(ctx, index) -> list:
    """Cajas del cuerpo de una slide compuesta: todo menos marca, encabezado, pie y etiquetas."""
    return [b for n, k, b, t in elements(ctx, index)
            if not n.startswith(BRAND_PREFIX) and not n.startswith(BODY_EXCLUDED)
            and (k != "text" or t.text.strip())]


def findings(ctx, auditor):
    out = []
    rules = ctx.kn.tokens["brand_rules"]
    scale = ctx.presentation.slide_width / 12700 / 720

    def add(index, subcheck, code, shape, symptom, measurement, correction):
        slide = ctx.slide(index)
        out.append(Finding(check=auditor, subcheck=subcheck, code=code, status="fail",
            slide_id=index, source_slide_id=slide.source_slide_id, family=slide.family,
            source_reference=shape, symptom=symptom, measurement=measurement,
            cause="incumplimiento de la regla registrada tras la revisión de Referencia v2",
            correction_proposed=correction, acceptance="tokens.yaml → brand_rules, revisión 2026-09-30"))

    if not is_light(ctx.presentation.slides[0]):
        add(1, "bookends", "cover_not_light", "cover", "la portada usa dark mode", {}, "usar fondo light y contraste navy/azul")
    last_index = len(ctx.presentation.slides)
    last = ctx.presentation.slides[-1]
    closing = rules["closing"]
    copies = [s.text.strip() for s in last.shapes if s.has_text_frame and s.text.strip()]
    if not is_light(last) or closing["text"] not in copies:
        add(last_index, "bookends", "noncanonical_closing", "closing", "la última slide no es la despedida NEO light obligatoria",
            {"texts": copies}, "aplicar la despedida canónica; añadirla si la última slide contiene contenido operativo")
    else:
        expected = {"NEO_BRAND_brand_logo": closing["logo_box"], "NEO_BRAND_closing_copy": closing["text_box"]}
        client = next((s for s in last.shapes if s.name == "NEO_BRAND_client_logo"), None)
        if client is not None and client.height:
            # Despedida con co-marca: el logo NEO va a la izquierda del bloque centrado.
            from ..cobrand import lockup, neo_box
            from ..schemas import Box
            box = Box(x=closing["logo_box"][0], y=closing["logo_box"][1], w=closing["logo_box"][2],
                      h=closing["logo_box"][3])
            neo_h = box.h
            # El alto real del logo del cliente fija el ancho del bloque (con o sin franja de texto).
            band = (0.0, neo_h * scale * 12700 / client.height)
            neo = lockup(neo_box(ctx.kn, box, "center"), client.width / client.height, align="center", band=band).neo
            expected["NEO_BRAND_brand_logo"] = [neo.x, neo.y, neo.w, neo.h]
        for name, coords in expected.items():
            shape = next((s for s in last.shapes if s.name == name), None)
            actual = [getattr(shape, k)/12700/scale for k in ("left", "top", "width", "height")] if shape else []
            if not actual or any(abs(a-b)>2 for a,b in zip(actual,coords)):
                add(last_index, "bookends", "closing_geometry_drift", name, "la despedida cambia su composición registrada",
                    {"actual":actual,"expected":coords}, "usar el componente canonical_light_farewell")

    allowed = {value.upper() for value in ctx.kn.tokens["colors"].values()}
    table_rule = rules["table"]
    for info in ctx.slides:
        if not ctx.in_scope(info.index):
            continue
        slide = ctx.presentation.slides[info.index-1]
        colors = _Colors(slide)
        for shape in slide.shapes:
            if shape.has_table:
                for ri, row in enumerate(shape.table.rows):
                    for ci, cell in enumerate(row.cells):
                        fill_nodes = _xp(cell._tc, "./a:tcPr/a:solidFill/*")
                        fill = colors.resolve(fill_nodes[0]) if fill_nodes else None
                        ref = f"{shape.name}:r{ri+1}c{ci+1}"
                        if fill not in table_rule["allowed_fills"]:
                            add(info.index, "table_style", "off_palette_table_fill", ref,
                                "relleno de tabla fuera de la paleta específica", {"fill":fill}, "usar blanco, navy, azul o celeste C5D5F7 exactos")
                        expected_text = "FFFFFF" if fill in {"000033", "2D5BFF"} else "000033"
                        for node in _xp(cell._tc, ".//a:rPr/a:solidFill/* | .//a:defRPr/a:solidFill/*"):
                            color = colors.resolve(node)
                            if color != expected_text:
                                add(info.index, "table_style", "noncanonical_table_text", ref,
                                    "texto de tabla sin contraste canónico", {"color":color,"expected":expected_text},
                                    "usar blanco sobre navy/azul y navy sobre blanco/celeste")
                        for side in "LRTB":
                            lines = _xp(cell._tc, f"./a:tcPr/a:ln{side}")
                            line = lines[0] if lines else None
                            nodes = _xp(line, "./a:solidFill/*") if line is not None else []
                            color = colors.resolve(nodes[0]) if nodes else None
                            width = int(line.get("w",0))/12700/scale if line is not None else 0
                            if color != table_rule["border_color"] or abs(width-table_rule["border_width_pt"]) > 0.05:
                                add(info.index, "table_style", "noncanonical_table_border", ref,
                                    "borde de tabla ausente o con estilo de Google", {"side":side,"color":color,"width":width},
                                    "escribir explícitamente todos los bordes en C5D5F7 a 0.6 pt lógicos")
            elif shape.shape_type == 1:
                wrapped = _Shape(shape._element, shape.name, shape.left/12700, shape.top/12700,
                                 shape.width/12700, shape.height/12700, shape.text if shape.has_text_frame else "")
                fill = _fill(wrapped, colors)
                line, _ = _line(wrapped, colors)
                for color in (fill, line):
                    if color and color != "gradient" and color not in allowed:
                        add(info.index,"shape_palette","off_palette_shape",shape.name,
                            "forma o celda con color no registrado",{"color":color},"usar un token exacto sin tint/lumMod")
        if info.family == "section_divider" and not is_light(slide):   # la portada clara no es un separador
            titles = [s.text.strip() for s in slide.shapes if s.has_text_frame and s.name.startswith("title_")]
            if titles and len(titles[0].split()) == 1 and not any(s.name.startswith("separator_companion") for s in slide.shapes):
                add(info.index,"separator_companion","single_word_separator_empty","title",
                        "separador de una palabra sin componente visual adicional",{},"añadir neo_outline_geometry; no inventar subtítulos")
        fit = rules["card_content_fit"]
        if info.redesigned and info.layout == "free" and fit.get("center_content_below_header"):
            # Composición libre: se centra el cuerpo entero (filas, paneles y banda), no una fila,
            # con la misma fórmula que el composer (`centered_body_top`), notas al pie incluidas.
            body=_body_boxes(ctx,info.index)
            items=list(elements(ctx,info.index))
            headings=[b for n,k,b,t in items if k=='text' and n.startswith(("kicker_","title_","subtitle_"))]
            notes=[b.y for n,k,b,t in items if k=='text' and n.startswith("note_") and t.text.strip()]
            if body and headings:
                top=min(b.y for b in body);bottom=max(b.bottom for b in body)
                band_bottom=centering_band_bottom(fit,min(notes) if notes else None,ctx.kn.geometry("free")["stack_gap"])
                expected=centered_body_top(max(b.bottom for b in headings),top,bottom,band_bottom,fit)
                if abs(top-expected)>fit["centering_tolerance_pt"]:
                    add(info.index,"card_content_fit","content_not_centered_below_header","body",
                        "el contenido no está centrado en el espacio libre bajo el encabezado",
                        {"top":round(top,2),"expected":round(expected,2)},"centrar el cuerpo entre el encabezado y el pie; el encabezado no se mueve")
        for row in card_rows(ctx, info):
            row_need = max(item[2] for item in row)
            if len(row)>1 and fit["equal_height_row_uses_longest_text"]:
                widths=[b.w for _,b,_ in row];heights=[b.h for _,b,_ in row]
                if max(widths)-min(widths)>fit["equal_size_tolerance_pt"] or max(heights)-min(heights)>fit["equal_size_tolerance_pt"]:
                    add(info.index,"card_content_fit","unequal_card_sizes","card_row",
                        "cards de una fila con tamaños distintos",{"widths":widths,"heights":heights},"igualar ancho y alto según el texto más largo")
            for name, box, need in row:
                if fit["equal_height_row_uses_longest_text"]:need=row_need
                limit = max(fit["maximum_extra_height_pt"], need*fit["maximum_extra_height_ratio"])
                if box.h-need > limit:
                    add(info.index,"card_content_fit","excessive_card_space",name,
                        "card demasiado alta para el texto de su fila",{"height":box.h,"needed":round(need,2),"extra":round(box.h-need,2)},
                        "ajustar alto de la fila al texto más largo más padding; conservar aire uniforme")
                if len(row)>1 and not fit["center_text_vertically"]:
                    items_=list(elements(ctx,info.index))
                    # En una card con cabecera navy, el cuerpo arranca con el padding bajo la cabecera.
                    head=_card_header_bottom(items_,box)
                    children=[b for n,k,b,t in items_ if k=='text' and not n.startswith(BRAND_PREFIX) and t.text.strip()
                              and box.contains(b) and not n.startswith("card_header_text")]
                    if children:
                        offset=min(b.y for b in children)-(head if head is not None else box.y)
                        if abs(offset-fit["padding_pt"])>fit["centering_tolerance_pt"]:
                            add(info.index,"card_content_fit","card_text_not_top_aligned",name,
                                "el texto de la card no arranca con el padding superior de la fila",{"offset":round(offset,2),"padding":fit["padding_pt"]},"anclar el texto arriba con el mismo padding en todas las cards")
                if len(row)>1 and fit["center_text_vertically"]:
                    children=[b for n,k,b,t in elements(ctx,info.index) if k=='text' and not n.startswith(BRAND_PREFIX) and len(t.text.strip())>60 and box.contains(b)]
                    if children:
                        center=(min(b.y for b in children)+max(b.bottom for b in children))/2
                        if abs(center-(box.y+box.h/2))>fit["centering_tolerance_pt"]:
                            add(info.index,"card_content_fit","card_text_not_centered",name,
                                "texto descentrado dentro de una card de fila",{"center":center,"card_center":box.y+box.h/2},"centrar verticalmente el texto conservando padding")
            # Como `design_policies.center_card_composition`: con notas al pie o banner el composer
            # no mueve las cards, así que exigirlo bloqueaba sin que el plan pudiera arreglarlo
            # (bucle de start_redesign en un deck interno, 2026-10-12).
            footed=any(n.startswith(("note_","banner")) for n,k,b,t in elements(ctx,info.index) if k=='text')
            if len(row)>1 and fit.get("center_content_below_header") and info.layout != "free" and not footed:
                boxes=[b for _,b,_ in row]
                top=min(b.y for b in boxes);bottom=max(b.bottom for b in boxes)
                headings=[b for n,k,b,t in elements(ctx,info.index) if k=='text' and not n.startswith(BRAND_PREFIX) and 64<=b.y<top and t.text.strip()]
                if headings:
                    expected=centered_body_top(max(b.bottom for b in headings),top,bottom,fit["composition_band"][1],fit)
                    if abs(top-expected)>fit["centering_tolerance_pt"]:
                        add(info.index,"card_content_fit","content_not_centered_below_header","cards",
                            "el contenido no está centrado en el espacio libre bajo el encabezado",{"top":round(top,2),"expected":round(expected,2)},"centrar las cards entre el encabezado y el pie; el encabezado no se mueve")
            if len(row)>1 and fit["center_composition_vertically"]:
                boxes=[b for _,b,_ in row]
                top=min(b.y for b in boxes);bottom=max(b.bottom for b in boxes)
                headings=[b for n,k,b,t in elements(ctx,info.index) if k=='text' and not n.startswith(BRAND_PREFIX) and 64<=b.y<top and t.text.strip()]
                if headings:
                    group_top=min(b.y for b in headings);center=(group_top+bottom)/2
                    target=sum(fit["composition_band"])/2
                    if abs(center-target)>fit["centering_tolerance_pt"]:
                        add(info.index,"card_content_fit","composition_not_centered","heading_and_cards",
                            "kicker, título y cards descentrados verticalmente",{"center":center,"target":target},"centrar el conjunto entre 64 y 350 pt; mantener logo y footer")
    return out
