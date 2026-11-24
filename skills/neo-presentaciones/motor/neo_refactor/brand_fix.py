"""Aplica las reglas de marca de la referencia Taller 1 v7 a una slide conservada (brand shell).

Es la contraparte de `audit/brand.py`: usa el mismo detector de colores y de cards para
que lo que se corrige sea exactamente lo que el auditor mide. Solo cambia formato, nunca
texto ni geometría de contenido:

- texto fuera de paleta → el color permitido más cercano (un `2B5BFC` pasa a `2D5BFF`); un
  gris (`575757`) pasa a navy, como pide la referencia; un color derivado (`lumMod`, `tint`)
  se reemplaza por el color de paleta más cercano a su base;
- hipervínculos → `hyperlink_color`;
- radio de card → el radio permitido más cercano (3, 5 o 6 pt); una card recta pasa a
  `roundRect` de 6 pt;
- card blanca → borde azul 1.5 pt sin sombra si tenía borde, o sin borde con la sombra
  `card` si no lo tenía;
- relleno o borde de forma fuera de paleta → blanco si es claro (una card gris es una card
  blanca) o el color de paleta más cercano;
- viñetas que ya trae la slide → la de marca (`brand_rules.bullet`: «•» Arial, azul, 100 %);
  una numeración (`buAutoNum`) conserva su tipo y toma el mismo color y tamaño;
- runs, `endParaRPr`, `defRPr` y celdas de tabla → sin `a:highlight` (la «caja gris» de los
  rótulos de un deck de cliente) y con `ea`/`cs`/`sym` en la letra de `latin`.

Se llama desde `engine.py` para cada slide que sale como brand shell: las que conservan su
organización a pedido (`keep_layout`), las que no cupieron en su layout (`no_cupieron`), las que
no tienen layout compatible y las de gráfico nativo. Las rediseñadas las dibuja el renderer, que
ya escribe la viñeta de marca y solo `latin`, sin resaltado.
"""
from __future__ import annotations

import colorsys

from lxml import etree
from pptx.oxml.ns import qn

from .audit import brand as audit_brand
from .knowledge import Knowledge, nearest_color as nearest
from .renderer import BRAND_PREFIX, BULLET_TAGS, bullet_nodes, place_bullet

EMU = 12700


def _set_solid(props, hex_: str) -> None:
    """Relleno sólido sRGB sin modificadores, en la posición que pide el esquema."""
    fill = props.get_or_change_to_solidFill()
    for child in list(fill):
        fill.remove(child)
    etree.SubElement(fill, qn("a:srgbClr"), val=hex_)


def snap_text_color(hex_: str, allowed: list[str]) -> str:
    """Color de paleta para un texto fuera de ella. Un gris no es un azul: pasa a navy (como
    los cuerpos de la referencia), o a blanco si es casi blanco; el resto, al más cercano."""
    r, g, b = (int(hex_[k:k + 2], 16) for k in (0, 2, 4))
    if max(r, g, b) - min(r, g, b) <= 24:
        return "FFFFFF" if min(r, g, b) >= 217 else "000033"
    return nearest(hex_, allowed)


def _text_colors(slide, colors, rules) -> int:
    allowed = [c.upper() for c in rules["text_colors"]]
    link = str(rules["hyperlink_color"]).upper()
    changed = 0
    for run in slide.shapes._spTree.iter(qn("a:r"), qn("a:fld")):
        rpr = run.find(qn("a:rPr"))
        if rpr is None:
            continue
        linked = rpr.find(qn("a:hlinkClick")) is not None or rpr.find(qn("a:hlinkMouseOver")) is not None
        node = rpr.find(qn("a:solidFill"))
        color = colors.resolve(node[0]) if node is not None and len(node) else None
        if linked:
            if color != link:
                _set_solid(rpr, link)
                changed += 1
            continue
        if color is None or color in allowed:
            continue
        base = color.split(":", 1)[-1]
        _set_solid(rpr, snap_text_color(base, allowed) if len(base) == 6 else allowed[0])
        changed += 1
    return changed


def _apparent(node, colors) -> str | None:
    """Hex que se ve: la base con sus modificadores (lumMod/lumOff, tint, shade) aplicados.

    `_Colors.resolve` deja `derived:<base>`; para elegir el reemplazo importa lo que se ve: un
    celeste `accent1 lumMod 20 lumOff 80` no es el azul de su base."""
    value = colors.resolve(node)
    if not value or not value.startswith("derived:"):
        return value
    base = value.split(":", 1)[1]
    if len(base) != 6:
        return None
    r, g, b = (int(base[k:k + 2], 16) / 255 for k in (0, 2, 4))
    mods = {etree.QName(child).localname: int(child.get("val", "100000")) / 100000 for child in node}
    if "lumMod" in mods or "lumOff" in mods:
        h, light, sat = colorsys.rgb_to_hls(r, g, b)
        light = min(1.0, max(0.0, light * mods.get("lumMod", 1.0) + mods.get("lumOff", 0.0)))
        r, g, b = colorsys.hls_to_rgb(h, light, sat)
    if "tint" in mods:
        r, g, b = (1 - (1 - c) * mods["tint"] for c in (r, g, b))
    if "shade" in mods:
        r, g, b = (c * mods["shade"] for c in (r, g, b))
    return "".join(f"{round(min(1.0, max(0.0, c)) * 255):02X}" for c in (r, g, b))


def _shape_palette(slide, colors, kn: Knowledge) -> int:
    """Rellenos y bordes de forma fuera de la paleta, como los mide `style_integrity_audit`
    (`off_palette_shape`, formas de primer nivel). Un relleno claro pasa a blanco: una card
    gris es la card blanca de la marca, y `_cards` le pone después su borde o su sombra. El
    resto va al color de la paleta más cercano a lo que se ve."""
    allowed = [value.upper() for value in kn.tokens["colors"].values()]
    changed = 0
    boxes = [(shape.shape_id, shape.left, shape.top, shape.width, shape.height) for shape in slide.shapes
             if shape.shape_type == 1 and None not in (shape.left, shape.top, shape.width, shape.height)]

    def nested(shape) -> bool:
        """Forma dentro de otra (la pista de una barra de avance dentro de su card)."""
        if None in (shape.left, shape.top, shape.width, shape.height):
            return False
        x, y, w, h = shape.left, shape.top, shape.width, shape.height
        return any(sid != shape.shape_id and ox <= x and oy <= y and x + w <= ox + ow and y + h <= oy + oh
                   and ow * oh > w * h for sid, ox, oy, ow, oh in boxes)

    for shape in slide.shapes:
        if shape.shape_type != 1 or shape.name.startswith(BRAND_PREFIX):
            continue
        sp_pr = shape._element.find(qn("p:spPr"))
        if sp_pr is None:
            continue
        wrapped = audit_brand._Shape(shape._element, shape.name, 0.0, 0.0, 0.0, 0.0, "")
        fill = audit_brand._fill(wrapped, colors)
        if fill and fill != "gradient" and fill not in allowed:
            node = sp_pr.find(f"{qn('a:solidFill')}/*")
            if node is None:
                node = audit_brand._first(shape._element, "./p:style/a:fillRef/*")
            seen = _apparent(node, colors)
            if seen:
                r, g, b = (int(seen[k:k + 2], 16) / 255 for k in (0, 2, 4))
                light = 0.2126 * r + 0.7152 * g + 0.0722 * b >= 0.85
                _set_solid(sp_pr, "FFFFFF" if light else nearest(seen, allowed))
                changed += 1
                if light and nested(shape):
                    # Blanca sobre una card blanca desaparecía (la pista de una barra de avance):
                    # conserva el contorno en el celeste de la paleta para seguir viéndose.
                    ln = sp_pr.get_or_add_ln()
                    ln.set("w", str(round(1.5 * EMU)))
                    _set_solid(ln, kn.color("blue_pale"))
                    continue
        line, _width = audit_brand._line(wrapped, colors)
        if line and line not in allowed:
            ln = sp_pr.find(qn("a:ln"))
            node = ln.find(f"{qn('a:solidFill')}/*") if ln is not None else None
            if node is None:
                node = audit_brand._first(shape._element, "./p:style/a:lnRef/*")
            seen = _apparent(node, colors)
            if seen:
                _set_solid(sp_pr.get_or_add_ln(), nearest(seen, allowed))
                changed += 1
    return changed


def _set_radius(element, geom, radius: float, short_side: float) -> None:
    geom.set("prst", "roundRect")
    av = geom.find(qn("a:avLst"))
    if av is None:
        av = etree.SubElement(geom, qn("a:avLst"))
    for gd in list(av):
        av.remove(gd)
    etree.SubElement(av, qn("a:gd"), name="adj", fmla=f"val {round(radius / max(short_side, 1.0) * 100000)}")


def _white_card(sp_pr, rules, kn: Knowledge, had_line: bool, scale: float = 1.0) -> None:
    """Las dos variantes de la referencia; grosor y sombra en la escala real de la slide (el
    auditor los divide por ella: escritos en pt lógicos quedaban a la mitad)."""
    ln = sp_pr.get_or_add_ln()
    for child in list(ln):
        ln.remove(child)
    effects = sp_pr.get_or_add_effectLst()
    for child in list(effects):
        effects.remove(child)
    # Google Slides y LibreOffice dibujan el efecto del tema aunque `effectLst` esté vacío.
    ref = sp_pr.getparent().find(f"{qn('p:style')}/{qn('a:effectRef')}")
    if ref is not None:
        ref.set("idx", "0")
    if had_line:
        spec = rules["white_card"]["outlined"]
        ln.set("w", str(round(spec["line_width_pt"] * scale * EMU)))
        _set_solid(ln, str(spec["line"]).upper())
        return
    etree.SubElement(ln, qn("a:noFill"))
    shadow = kn.shadow(rules["white_card"]["shadowed"]["shadow"])
    node = etree.SubElement(effects, qn("a:outerShdw"), blurRad=str(round(shadow["blur_pt"] * scale * EMU)),
                            dist=str(round(shadow["distance_pt"] * scale * EMU)),
                            dir=str(round(shadow.get("direction_deg", 90) * 60000)), rotWithShape="0")
    color = etree.SubElement(node, qn("a:srgbClr"), val=shadow["color"])
    etree.SubElement(color, qn("a:alpha"), val=str(round(shadow["alpha_pct"] * 1000)))


def _cards(slide, colors, rules, kn: Knowledge, scale: float) -> dict[str, int]:
    """Las mismas cards que mide el auditor, con su radio y variante blanca corregidos."""
    codes: dict[str, set[str]] = {}
    for issue in audit_brand.inspect_slide(slide, 0, kn, scale):
        if issue.code in ("card_corner_radius", "white_card_style"):
            codes.setdefault(issue.shape, set()).add(issue.code)
    radii = sorted(rules["card_radius_pt"])
    stats = {"card_radius": 0, "white_card": 0}
    for shape in audit_brand._flatten(slide.shapes._spTree, colors):
        found = codes.get(shape.name, set())
        sp_pr = shape.element.find(qn("p:spPr"))
        geom = sp_pr.find(qn("a:prstGeom")) if sp_pr is not None else None
        if not found or geom is None:
            continue
        if "card_corner_radius" in found:
            prst = geom.get("prst")
            # el auditor mide en pt del lienzo; el adj se expresa sobre la caja real
            current = audit_brand._radius(shape, prst) / scale if prst in audit_brand.ROUND_GEOMS else 0.0
            target = min(radii, key=lambda r: abs(r - current)) if current else max(radii)
            _set_radius(shape.element, geom, target * scale, min(shape.w, shape.h))
            stats["card_radius"] += 1
        if "white_card_style" in found:
            line, _width = audit_brand._line(shape, colors)
            _white_card(sp_pr, rules, kn, had_line=line is not None, scale=scale)
            stats["white_card"] += 1
    return stats


_PARA_PROPS = tuple(qn(t) for t in ("a:pPr", *(f"a:lvl{k}pPr" for k in range(1, 10))))
_MARKERS = tuple(qn(f"a:{t}") for t in ("buChar", "buAutoNum", "buBlip"))


def _bullets(slide, kn: Knowledge) -> int:
    """Viñetas que ya trae la slide conservada → la de marca, en el orden del esquema.

    Se quitan `buSzPts`, `buSzTx`, `buClrTx` y los `buClr`/`buFont` del original. Una marca
    («●», «○», «■», una imagen) pasa a «•» en Arial; una numeración conserva su tipo y su
    `startAt`. Un párrafo que solo da color o tamaño a una viñeta heredada del layout recibe
    el color y el tamaño de marca y conserva lo demás. `buNone` (sin viñeta) no se toca.
    """
    spec = kn.tokens["brand_rules"]["bullet"]
    color = kn.color(spec["color"])
    changed = 0
    for ppr in slide.shapes._spTree.iter(*_PARA_PROPS):
        if ppr.find(qn("a:buNone")) is not None or not any(child.tag in BULLET_TAGS for child in ppr):
            continue
        auto = ppr.find(qn("a:buAutoNum"))
        if auto is not None:
            nodes = bullet_nodes(ppr, auto.get("type"), auto.get("startAt"), color)
        elif any(ppr.find(tag) is not None for tag in _MARKERS):
            nodes = bullet_nodes(ppr, color=color)
        else:
            kept = [child for child in ppr if child.tag in (qn("a:buFontTx"), qn("a:buFont"))]
            nodes = [*bullet_nodes(ppr, color=color, marker=False), *kept]
        before = [etree.tostring(child) for child in ppr if child.tag in BULLET_TAGS]
        place_bullet(ppr, nodes)
        if [etree.tostring(child) for child in ppr if child.tag in BULLET_TAGS] != before:
            changed += 1
    return changed


_RUN_PROPS = tuple(qn(t) for t in ("a:rPr", "a:endParaRPr", "a:defRPr"))


def _clean_runs(slide) -> dict[str, int]:
    """Sin `a:highlight` y con `ea`/`cs`/`sym` en la letra de `latin`, en runs, finales de
    párrafo, estilos de lista y tablas. El shell pasa `latin` a Montserrat y deja las otras
    tres en la letra del original (Arial, Calibri…): un visor que las usa dibuja otra letra."""
    stats = {"highlight_removed": 0, "fonts_matched": 0}
    for rpr in slide.shapes._spTree.iter(*_RUN_PROPS):
        for mark in rpr.findall(qn("a:highlight")):
            rpr.remove(mark)
            stats["highlight_removed"] += 1
        latin = rpr.find(qn("a:latin"))
        face = latin.get("typeface") if latin is not None else None
        if not face:
            continue
        for tag in ("a:ea", "a:cs", "a:sym"):
            node = rpr.find(qn(tag))
            if node is not None and node.get("typeface") != face:
                node.set("typeface", face)
                for attr in ("panose", "pitchFamily", "charset"):
                    node.attrib.pop(attr, None)
                stats["fonts_matched"] += 1
    return stats


def apply_brand_rules(slide, kn: Knowledge, scale: float = 1.0) -> dict[str, int]:
    """Corrige en sitio paleta de texto, vínculos, radios, cards blancas, viñetas y runs;
    devuelve el conteo."""
    rules = kn.tokens["brand_rules"]
    colors = audit_brand._Colors(slide)
    stats = {"text_colors": _text_colors(slide, colors, rules)}
    # Antes que las cards: una card gris que pasa a blanca recibe ahí su variante de marca.
    stats["shape_colors"] = _shape_palette(slide, colors, kn)
    stats.update(_cards(slide, colors, rules, kn, scale))
    stats["bullets"] = _bullets(slide, kn)
    stats.update(_clean_runs(slide))
    return {key: value for key, value in stats.items() if value}


def fix_theme_links(presentation, kn: Knowledge) -> int:
    """`hlink` y `folHlink` de cada tema con el azul canónico de vínculos."""
    from pptx.opc.constants import RELATIONSHIP_TYPE as RT

    link = str(kn.tokens["brand_rules"]["hyperlink_color"]).upper()
    changed = 0
    for master in presentation.slide_masters:
        part = master.part.part_related_by(RT.THEME)
        theme = etree.fromstring(part.blob)
        dirty = False
        for tag in ("hlink", "folHlink"):
            for node in theme.iter(qn(f"a:{tag}")):
                current = node.find(qn("a:srgbClr"))
                if current is not None and current.get("val", "").upper() == link and len(node) == 1:
                    continue
                for child in list(node):
                    node.remove(child)
                etree.SubElement(node, qn("a:srgbClr"), val=link)
                dirty = True
        if dirty:
            part._blob = etree.tostring(theme, xml_declaration=True, encoding="UTF-8", standalone=True)
            changed += 1
    return changed


def drop_embedded_brand_fonts(presentation, kn: Knowledge) -> int:
    """Quita las Montserrat embebidas: el export de Google Slides declara «SemiBold»,
    «Medium», «Black»… pero embebe las mismas cuatro caras genéricas para todas (la
    «regular» de SemiBold es una Light). Un visor que las usa (LibreOffice, PowerPoint sin
    Montserrat instalada) dibuja otro peso; la marca exige la tipografía instalada."""
    from pptx.oxml.ns import qn as _qn

    families = {name.lower() for name in kn.allowed_families}
    root = presentation.part._element
    embedded = root.find(_qn("p:embeddedFontLst"))
    if embedded is None:
        return 0
    dropped = 0
    for font in list(embedded):
        face = font.find(_qn("p:font"))
        if face is None or (face.get("typeface") or "").lower() not in families:
            continue
        for node in font:
            rid = node.get(_qn("r:id"))
            if rid:
                presentation.part.drop_rel(rid)
        embedded.remove(font)
        dropped += 1
    if not len(embedded):
        root.remove(embedded)
    return dropped
