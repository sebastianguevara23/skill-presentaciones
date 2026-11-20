"""Reglas de marca de la referencia oficial Taller 1 v7 (`tokens.yaml` → `brand_rules`).

Se leen de los bytes del PPTX, no del plan ni del reporte del render:

- `text_palette`: todo run con texto usa negro `000000`, blanco o un color de la paleta.
- `vector_palette`: SVG embebidos y formas libres editables (íconos) usan esa misma paleta.
- `card_radius`: toda card, de cualquier color, tiene un radio de la referencia (3/5/6 pt) o
  es una pill. Una card de esquinas rectas o con otro radio falla.
- `white_cards`: una card blanca solo puede ser blanca con borde `2D5BFF` de 1.5 pt (2 px)
  y sin sombra, o blanca sin borde con la sombra `card` de la referencia.

Los colores de tema (`schemeClr`) se resuelven contra el tema del master; un color con
modificadores (`lumMod`, `tint`…) ya no es el color de la paleta y se reporta como derivado.
Una card es un rectángulo con relleno o borde visible, de al menos `card_min_side_pt` de
lado, que lleva texto o tiene texto encima. No son cards las piezas que cuadran la base de
una cabecera redondeada (dentro de un rectángulo redondeado del mismo relleno, como
`card_header_base`), la marca ni los fondos a sangre.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from lxml import etree
from pptx.opc.constants import RELATIONSHIP_TYPE as RT

from ..renderer import BRAND_PREFIX
from ..slide_marker import read_marker
from .core import AuditContext, Finding

NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "asvg": "http://schemas.microsoft.com/office/drawing/2016/SVG/main",
}
EMU = 12700
SUBCHECKS = ("text_palette", "vector_palette", "card_radius", "white_cards")
ROUND_GEOMS = {"roundRect", "round1Rect", "round2SameRect", "round2DiagRect", "snipRoundRect"}
CARD_GEOMS = ROUND_GEOMS | {"rect", "snip1Rect", "snip2SameRect", "snip2DiagRect"}
DEFAULT_ADJ = 16667
CLR_MAP = {"bg1": "lt1", "tx1": "dk1", "bg2": "lt2", "tx2": "dk2"}
PRESET = {"black": "000000", "white": "FFFFFF"}
SVG_NAMED = {"black": "000000", "white": "FFFFFF"}
SVG_SKIP = {"none", "transparent", "currentcolor", "inherit"}
SVG_COLOR = re.compile(r"(?:fill|stroke|stop-color|flood-color|color)\s*[:=]\s*[\"']?\s*([#\w(),.\s%]+?)\s*[\"';)}]",
                       re.IGNORECASE)


def _xp(node, path: str) -> list:
    return etree._Element.xpath(node, path, namespaces=NS)


def _first(node, path: str):
    values = _xp(node, path)
    return values[0] if values else None


@dataclass
class Issue:
    slide: int
    subcheck: str
    code: str
    shape: str
    symptom: str
    measurement: dict = field(default_factory=dict)


@dataclass
class _Shape:
    element: etree._Element
    name: str
    x: float
    y: float
    w: float
    h: float
    text: str

    def encloses(self, other: "_Shape", tolerance: float = 0.5) -> bool:
        return (self.x - tolerance <= other.x and self.y - tolerance <= other.y
                and other.x + other.w <= self.x + self.w + tolerance
                and other.y + other.h <= self.y + self.h + tolerance)

    def contains_center(self, other: "_Shape") -> bool:
        cx, cy = other.x + other.w / 2, other.y + other.h / 2
        return self.x <= cx <= self.x + self.w and self.y <= cy <= self.y + self.h


class _Colors:
    """Resuelve un nodo de color DrawingML a hex usando el tema del master de la slide."""

    def __init__(self, slide):
        master = slide.slide_layout.slide_master
        self.clr_map = dict(CLR_MAP)
        mapping = _first(master._element, "./p:clrMap")
        if mapping is not None:
            self.clr_map.update(mapping.attrib)
        self.scheme: dict[str, str] = {}
        try:
            theme = etree.fromstring(master.part.part_related_by(RT.THEME).blob)
        except (KeyError, ValueError):
            return
        for node in _xp(theme, "//a:clrScheme/*"):
            value = _first(node, "./a:srgbClr/@val") or _first(node, "./a:sysClr/@lastClr")
            if value:
                self.scheme[etree.QName(node).localname] = value.upper()

    def resolve(self, node) -> str | None:
        """Hex del color; `derived:<hex>` si lleva modificadores; None si no se puede saber."""
        if node is None:
            return None
        kind = etree.QName(node).localname
        if kind == "srgbClr":
            value = node.get("val", "").upper()
        elif kind == "schemeClr":
            name = node.get("val")
            value = self.scheme.get(self.clr_map.get(name, name))
        elif kind == "sysClr":
            value = (node.get("lastClr") or "").upper() or None
        elif kind == "prstClr":
            value = PRESET.get(node.get("val"), node.get("val"))
        else:
            return None
        if value is None:
            return None
        modifiers = [etree.QName(child).localname for child in node if etree.QName(child).localname != "alpha"]
        return f"derived:{value}" if modifiers else value


def _flatten(container, colors, transform=(0.0, 0.0, 1.0, 1.0)):
    """Shapes con su caja en pt de la slide, bajando por los grupos."""
    ox, oy, sx, sy = transform
    for element in container:
        tag = etree.QName(element).localname
        if tag == "grpSp":
            off = _first(element, "./p:grpSpPr/a:xfrm/a:off")
            ext = _first(element, "./p:grpSpPr/a:xfrm/a:ext")
            ch_off = _first(element, "./p:grpSpPr/a:xfrm/a:chOff")
            ch_ext = _first(element, "./p:grpSpPr/a:xfrm/a:chExt")
            if off is None or ext is None or ch_off is None or ch_ext is None:
                yield from _flatten(element, colors, transform)
                continue
            gsx = int(ext.get("cx")) / max(int(ch_ext.get("cx")), 1)
            gsy = int(ext.get("cy")) / max(int(ch_ext.get("cy")), 1)
            inner = (ox + sx * (int(off.get("x")) - int(ch_off.get("x")) * gsx),
                     oy + sy * (int(off.get("y")) - int(ch_off.get("y")) * gsy), sx * gsx, sy * gsy)
            yield from _flatten(element, colors, inner)
            continue
        if tag not in ("sp", "pic", "graphicFrame", "cxnSp"):
            continue
        off = _first(element, "./p:spPr/a:xfrm/a:off | ./p:xfrm/a:off")
        ext = _first(element, "./p:spPr/a:xfrm/a:ext | ./p:xfrm/a:ext")
        if off is None or ext is None:
            continue
        name = _first(element, "./*/p:cNvPr/@name") or ""
        text = "".join(_xp(element, ".//a:t/text()")).strip()
        yield _Shape(element, name,
                     (ox + sx * int(off.get("x"))) / EMU, (oy + sy * int(off.get("y"))) / EMU,
                     sx * int(ext.get("cx")) / EMU, sy * int(ext.get("cy")) / EMU, text)


def _fill(shape: _Shape, colors: _Colors) -> str | None:
    """Relleno visible (hex) o None; `gradient` si es degradado."""
    sp_pr = _first(shape.element, "./p:spPr")
    if sp_pr is None:
        return None
    if _first(sp_pr, "./a:noFill") is not None:
        return None
    solid = _first(sp_pr, "./a:solidFill/*")
    if solid is not None:
        return colors.resolve(solid)
    if _first(sp_pr, "./a:gradFill | ./a:pattFill | ./a:blipFill") is not None:
        return "gradient"
    return colors.resolve(_first(shape.element, "./p:style/a:fillRef[@idx!='0']/*"))


def _line(shape: _Shape, colors: _Colors) -> tuple[str | None, float]:
    """(color, grosor en pt) del borde visible; (None, 0) sin borde."""
    line = _first(shape.element, "./p:spPr/a:ln")
    if line is not None and _first(line, "./a:noFill") is not None:
        return None, 0.0
    width = int(line.get("w")) / EMU if line is not None and line.get("w") else 0.75
    solid = _first(line, "./a:solidFill/*") if line is not None else None
    if solid is not None:
        return colors.resolve(solid), width
    styled = _first(shape.element, "./p:style/a:lnRef[@idx!='0']/*")
    return (colors.resolve(styled), width) if styled is not None else (None, 0.0)


def _shadow(shape: _Shape) -> dict | None:
    """Sombra exterior explícita en pt; `{"theme": idx}` si sale del estilo del tema."""
    node = _first(shape.element, "./p:spPr/a:effectLst/a:outerShdw")
    if node is not None:
        return {
            "blur_pt": round(int(node.get("blurRad", 0)) / EMU, 2),
            "distance_pt": round(int(node.get("dist", 0)) / EMU, 2),
            "direction_deg": round(int(node.get("dir", 0)) / 60000, 1),
            "color": _first(node, "./a:srgbClr/@val") or _first(node, "./a:prstClr/@val"),
            "alpha_pct": round(int(_first(node, "./*/a:alpha/@val") or 100000) / 1000, 1),
        }
    # Sin `outerShdw` propio, el efecto del tema cuenta aunque haya `effectLst` vacío:
    # PowerPoint lo anula, pero Google Slides y LibreOffice lo dibujan.
    ref = _first(shape.element, "./p:style/a:effectRef/@idx")
    if ref and ref != "0":
        return {"theme": int(ref)}
    return None


def _radius(shape: _Shape, geom: str) -> float:
    if geom not in ROUND_GEOMS:
        return 0.0
    adj = _first(shape.element, "./p:spPr/a:prstGeom/a:avLst/a:gd[@name='adj' or @name='adj1']/@fmla")
    value = int(adj[4:]) if adj and adj.startswith("val ") else DEFAULT_ADJ
    return round(value / 100000 * min(shape.w, shape.h), 2)


def _shadow_matches(actual: dict | None, spec: dict) -> bool:
    return bool(actual) and "theme" not in actual and (actual["color"] or "").upper() == spec["color"].upper() \
        and abs(actual["blur_pt"] - spec["blur_pt"]) <= 0.5 \
        and abs(actual["distance_pt"] - spec["distance_pt"]) <= 0.5 \
        and abs(actual["direction_deg"] - spec.get("direction_deg", 90)) <= 5 \
        and abs(actual["alpha_pct"] - spec["alpha_pct"]) <= 2


def _svg_colors(blob: bytes) -> set[str]:
    """Colores que usa un SVG (atributos y estilos), normalizados a hex o al nombre."""
    found = set()
    for raw in SVG_COLOR.findall(blob.decode("utf-8", "replace")):
        value = raw.strip().lower()
        if not value or value in SVG_SKIP or value.startswith("url"):
            continue
        if value.startswith("#"):
            digits = value[1:]
            if len(digits) in (3, 4):
                digits = "".join(c * 2 for c in digits[:3])
            found.add(digits[:6].upper())
        elif value.startswith("rgb"):
            parts = [p for p in re.split(r"[^\d.]+", value) if p][:3]
            if len(parts) == 3:
                found.add("".join(f"{min(255, int(float(p))):02X}" for p in parts))
        else:
            found.add(SVG_NAMED.get(value, value))
    return found


def inspect_slide(slide, index: int, kn, scale: float = 1.0) -> list[Issue]:
    """Incumplimientos de las reglas de marca en una slide (sin decidir su gravedad)."""
    rules = kn.tokens["brand_rules"]
    text_ok = {c.upper() for c in rules["text_colors"]}
    vector_ok = {c.upper() for c in rules["vector_colors"]}
    radii, tolerance = rules["card_radius_pt"], rules["radius_tolerance_pt"]
    min_side = rules["card_min_side_pt"]
    outlined, shadowed = rules["white_card"]["outlined"], rules["white_card"]["shadowed"]
    card_shadow = kn.shadow(shadowed["shadow"])
    width, height = kn.tokens["canvas"]["width"], kn.tokens["canvas"]["height"]
    colors = _Colors(slide)
    issues: list[Issue] = []
    marker = read_marker(slide) or {}
    is_dark_section = marker.get("family") == "section_divider"
    dark_accent = kn.color("separator_blue")

    shapes = [s for s in _flatten(slide.shapes._spTree, colors)]
    for s in shapes:
        s.x, s.y, s.w, s.h = s.x / scale, s.y / scale, s.w / scale, s.h / scale
    content = [s for s in shapes if not s.name.startswith(BRAND_PREFIX)]
    texts = [s for s in content if s.text]
    all_text = [s for s in shapes if s.text]

    for s in all_text:
        # Texto: color resuelto de cada run/campo con texto visible, incluso en marca.
        for run in _xp(s.element, ".//a:r | .//a:fld"):
            text = "".join(_xp(run, "./a:t/text()")).strip()
            if not text:
                continue
            rpr = _first(run, "./a:rPr")
            color = colors.resolve(_first(run, "./a:rPr/a:solidFill/*"))
            if (is_dark_section and s.name.startswith("title_") and rpr is not None
                    and rpr.get("i", "0").lower() in {"1", "true"} and color != dark_accent):
                issues.append(Issue(index, "text_palette", "noncanonical_dark_purple_emphasis", s.name,
                                    f"énfasis de título dark en #{color or 'sin color'}; debe usar #{dark_accent}",
                                    {"color": color, "canonical_color": dark_accent, "text": text[:30]}))
            if color and color not in text_ok:
                issues.append(Issue(index, "text_palette", "off_palette_text", s.name,
                                    f"texto en #{color}", {"color": color, "text": text[:30],
                                                           "allowed": sorted(text_ok)}))

            # Un hyperlink tiene un único color semántico en NEO, independiente de la
            # paleta general de roles: azul canónico. Si el run hereda color, el fallback
            # visible es el color hlink del theme, que también debe estar registrado.
            linked = _first(rpr, "./a:hlinkClick | ./a:hlinkMouseOver") if rpr is not None else None
            if linked is not None:
                link_color = color or colors.scheme.get("hlink")
                canonical = str(rules["hyperlink_color"]).upper()
                if link_color != canonical:
                    issues.append(Issue(
                        index, "text_palette", "noncanonical_link_color", s.name,
                        f"hipervínculo en #{link_color or 'sin color resuelto'}; debe usar #{canonical}",
                        {"color": link_color, "canonical_color": canonical, "text": text[:30]},
                    ))

    for s in content:
        # Vectores editables: formas libres y SVG embebidos.
        if _first(s.element, "./p:spPr/a:custGeom") is not None:
            used = {c for c in (_fill(s, colors), _line(s, colors)[0]) if c}
            used |= {colors.resolve(n) for n in _xp(s.element, "./p:spPr/a:gradFill/a:gsLst/a:gs/*")} - {None}
            used.discard("gradient")
            bad = sorted(c for c in used if c not in vector_ok)
            if bad:
                issues.append(Issue(index, "vector_palette", "off_palette_vector", s.name,
                                    "forma libre (ícono editable) fuera de la paleta", {"colors": bad}))
        for rid in _xp(s.element, ".//asvg:svgBlip/@r:embed"):
            try:
                blob = slide.part.related_part(rid).blob
            except KeyError:
                continue
            bad = sorted(c for c in _svg_colors(blob) if c not in vector_ok)
            if bad:
                issues.append(Issue(index, "vector_palette", "off_palette_vector", s.name,
                                    "SVG editable fuera de la paleta", {"colors": bad}))

        # Cards.
        if s.name.startswith(("matrix_head_", "matrix_cell_", "matrix_label_")):
            continue  # Flat table cells follow the registered matrix border policy.
        geom = _first(s.element, "./p:spPr/a:prstGeom/@prst")
        if etree.QName(s.element).localname != "sp" or geom not in CARD_GEOMS:
            continue
        if min(s.w, s.h) < min_side:
            continue
        if s.x <= 1 and s.y <= 1 and s.w >= 0.97 * width and s.h >= 0.97 * height:
            continue
        fill = _fill(s, colors)
        line, line_width = _line(s, colors)
        line_width /= scale  # grosor en pt del lienzo lógico, como las cajas
        if not fill and not line:
            continue
        if not s.text and not any(t is not s and s.contains_center(t) for t in texts):
            continue
        if any(o is not s and o.encloses(s) and _first(o.element, "./p:spPr/a:prstGeom/@prst") in ROUND_GEOMS
               and _fill(o, colors) == fill for o in content):
            continue  # pieza que cuadra la base de una cabecera redondeada: no es una card aparte
        radius = _radius(s, geom)
        pill = geom in ROUND_GEOMS and radius >= min(s.w, s.h) / 2 - tolerance
        if geom.startswith("snip") or not (pill or any(abs(radius - r) <= tolerance for r in radii)):
            issues.append(Issue(index, "card_radius", "card_corner_radius", s.name,
                                f"card con radio {radius:g} pt" if geom in ROUND_GEOMS else f"card {geom} sin radio",
                                {"radius_pt": radius, "geometry": geom, "allowed_pt": radii, "pill": pill}))
        if fill == "FFFFFF":
            shadow = _shadow(s)
            if shadow and "theme" not in shadow:
                shadow = {**shadow, "blur_pt": round(shadow["blur_pt"] / scale, 2),
                          "distance_pt": round(shadow["distance_pt"] / scale, 2)}
            is_outlined = line == outlined["line"].upper() and abs(line_width - outlined["line_width_pt"]) <= 0.1 \
                and not shadow
            is_shadowed = line is None and _shadow_matches(shadow, card_shadow)
            if not (is_outlined or is_shadowed):
                issues.append(Issue(index, "white_cards", "white_card_style", s.name,
                                    "card blanca fuera de las dos variantes de la referencia",
                                    {"line": line, "line_width_pt": round(line_width, 2), "shadow": shadow,
                                     "allowed": [f"borde {outlined['line']} {outlined['line_width_pt']} pt sin sombra",
                                                 f"sin borde con sombra {shadowed['shadow']}"]}))
    return issues


CORRECTION = {
    "off_palette_text": ("color de texto fuera de 000000, blanco y la paleta NEO",
                         "usar negro, blanco o el color de rol de tokens.yaml"),
    "noncanonical_dark_purple_emphasis": ("énfasis morado de título dark fuera del único color permitido",
                                            "usar exactamente #9AAFFE en el fragmento de énfasis"),
    "noncanonical_link_color": ("hipervínculo fuera del azul canónico NEO",
                                "usar el color hyperlink_color de tokens.yaml en el run y el theme"),
    "off_palette_vector": ("ícono o SVG editable con colores fuera de la paleta",
                           "recolorear el vector a la paleta (navy, azul, azules claros, negro o blanco)"),
    "card_corner_radius": ("radio de card que no existe en la referencia oficial",
                           "usar radio 3, 5 o 6 pt o una pill"),
    "white_card_style": ("card blanca con borde, grosor o sombra fuera de la referencia",
                         "borde 2D5BFF de 1.5 pt sin sombra, o sin borde con la sombra `card`"),
}


def findings(ctx: AuditContext, auditor: str) -> list[Finding]:
    """Los colores de texto fallan en cualquier slide; otras reglas conservan el aviso."""
    scale = ctx.presentation.slide_width / EMU / ctx.kn.tokens["canvas"]["width"]
    result = []
    for slide in ctx.slides:
        pptx_slide = ctx.presentation.slides[slide.index - 1]
        for issue in inspect_slide(pptx_slide, slide.index, ctx.kn, scale):
            cause, correction = CORRECTION[issue.code]
            strict_text_rule = issue.subcheck == "text_palette"
            result.append(Finding(
                check=auditor, subcheck=issue.subcheck, code=issue.code,
                status="fail" if strict_text_rule or slide.redesigned else "warning", slide_id=slide.index,
                source_slide_id=slide.source_slide_id, family=slide.family, source_reference=issue.shape,
                symptom=issue.symptom, measurement=issue.measurement, cause=cause,
                correction_proposed=correction,
                acceptance="reglas de marca de la referencia Taller 1 v7",
            ))
    return result
