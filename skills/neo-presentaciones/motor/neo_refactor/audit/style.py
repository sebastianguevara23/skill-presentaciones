"""`style_integrity_audit` genérico: componentes repetidos de una familia son iguales.

La familia y la variante salen de la marca de cada slide rediseñada, no de un número
de slide histórico. Dentro de cada (familia, variante) se agrupan los shapes por rol
(el renderer los nombra `rol_n`) y se toma como canónica la firma más frecuente. Lo
que cambia con el contenido (tamaño de la caja, cantidad de cards, cuerpo de un título
que se ajusta a su largo) no forma parte de la firma.

Códigos: `component_style_drift` (relleno, borde, radio, geometría),
`shadow_drift`, `typography_drift` (familia, peso, color) y `footer_scale_drift`
(el footer de marca con un cuerpo distinto en cualquier slide del deck).

Además aplica las reglas absolutas de marca de la referencia Taller 1 v7
(`brand.py`): `off_palette_text`, `off_palette_vector`, `card_corner_radius` y
`white_card_style`. No dependen de hermanos: una sola slide basta para fallar.
"""
from __future__ import annotations

from collections import Counter, defaultdict

from lxml import etree

from ..renderer import BRAND_PREFIX
from . import brand
from .core import AuditContext, AuditResult, Finding
from .geometry import role_of

AUDITOR = "style_integrity_audit"
from . import policies

SUBCHECKS = ("components", "shadows", "typography", "footer", *brand.SUBCHECKS, *policies.SUBCHECKS)
NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
}
EMU = 12700


def _xp(node, path: str) -> list:
    """XPath con prefijos explícitos (los elementos de python-pptx traen su propio xpath)."""
    return etree._Element.xpath(node, path, namespaces=NS)


def _first(node, path: str):
    values = _xp(node, path)
    return values[0] if values else None


def component_signature(shape) -> tuple:
    element = shape._element
    adj = _first(element, "./p:spPr/a:prstGeom/a:avLst/a:gd/@fmla")
    radius = None
    if adj and adj.startswith("val ") and shape.width and shape.height:
        radius = round(int(adj[4:]) / 100000 * min(shape.width, shape.height) / EMU * 2) / 2
    width = _first(element, "./p:spPr/a:ln/@w")
    return (
        _first(element, "./p:spPr/a:prstGeom/@prst"),
        _first(element, "./p:spPr/a:solidFill/a:srgbClr/@val")
        or ("none" if _first(element, "./p:spPr/a:noFill") is not None else None),
        _first(element, "./p:spPr/a:ln/a:solidFill/a:srgbClr/@val")
        or ("none" if _first(element, "./p:spPr/a:ln/a:noFill") is not None else None),
        round(int(width) / EMU, 2) if width else None,
        radius,
    )


def shadow_signature(shape) -> tuple:
    return tuple(
        (etree.QName(effect).localname, tuple(sorted(effect.attrib.items())))
        for effect in _xp(shape._element, "./p:spPr/a:effectLst/*")
    )


def run_styles(shape) -> set[tuple]:
    """Estilos de run (familia, peso, cursiva, color) que usa un shape con texto."""
    return {
        (_first(run, "./a:rPr/a:latin/@typeface"), _first(run, "./a:rPr/@b"),
         _first(run, "./a:rPr/@i"), _first(run, "./a:rPr/a:solidFill/a:srgbClr/@val"))
        for run in _xp(shape._element, ".//a:r") if "".join(_xp(run, "./a:t/text()")).strip()
    }


def _style_signature(style) -> tuple:
    """Firma de run (familia, peso, cursiva, color) que el renderer escribe para un estilo."""
    return (style.font, "1" if style.bold else "0", "1" if style.italic else "0", style.color.upper())


def inner_styles(kn, role: str) -> set[tuple]:
    """Estilos internos registrados de un rol singular: no son deriva aunque solo una slide
    los use. El énfasis del rol (negrita del autor en un subtítulo) y, en el título, la
    bajada del autor tras un salto de línea (estilo de subtítulo del modo)."""
    allowed = set()
    for mode, styles in kn.tokens["styles"].items():
        if not isinstance(styles, dict) or role not in styles:
            continue
        style = kn.style(mode, role)
        if style.emphasis:
            allowed.add(_style_signature(style.emphasis))
        if role == "title" and "subtitle" in styles:
            allowed.add(_style_signature(kn.style(mode, "subtitle")))
    return allowed


def audit(ctx: AuditContext) -> AuditResult:
    result = AuditResult(auditor=AUDITOR)
    groups: dict[tuple, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    footer_sizes: dict[int, list[str]] = {}
    for slide in ctx.slides:
        pptx_slide = ctx.presentation.slides[slide.index - 1]
        for shape in pptx_slide.shapes:
            if shape.name == f"{BRAND_PREFIX}_brand_phrase":
                footer_sizes[slide.index] = sorted({
                    size for size in _xp(shape._element, ".//a:r/a:rPr/@sz")
                })
        if not slide.redesigned:
            continue
        key = (slide.family, (slide.marker or {}).get("variant"))
        for shape in pptx_slide.shapes:
            if shape.name.startswith(BRAND_PREFIX):
                continue
            groups[key][role_of(shape.name)].append((slide, shape))

    def add(subcheck, code, slide, shape, symptom, canonical_value, actual, reference_slides):
        result.findings.append(Finding(
            check=AUDITOR, subcheck=subcheck, code=code, status="fail", slide_id=slide.index,
            source_slide_id=slide.source_slide_id, family=slide.family, source_reference=shape.name,
            symptom=symptom, measurement={"canonical": list(canonical_value), "actual": list(actual),
                                          "canonical_slides": reference_slides},
            cause="el componente repetido no usa la firma canónica de su familia",
            correction_proposed="aplicar el componente canónico de la familia",
            acceptance="mismo relleno, borde, radio, sombra y tipografía en toda la familia",
        ))

    def is_text(shape) -> bool:
        return getattr(shape, "has_text_frame", False) and bool(shape.text_frame.text.strip())

    for (_family, _variant), roles in groups.items():
        for role, members in roles.items():
            by_slide: dict[int, list] = defaultdict(list)
            for slide, shape in members:
                by_slide[slide.index].append((slide, shape))
            if len(by_slide) < 2:
                continue  # sin hermanos en otra slide no hay deriva que medir
            # Formas (cards, barras, cabeceras): un rol repetido puede tener varias
            # firmas legítimas (celda de encabezado y de cuerpo); es deriva la firma que
            # solo aparece en una slide de la familia.
            for subcheck, code, signature in (("components", "component_style_drift", component_signature),
                                              ("shadows", "shadow_drift", shadow_signature)):
                seen: dict[tuple, set[int]] = defaultdict(set)
                for index, items in by_slide.items():
                    for _slide, shape in items:
                        if not is_text(shape):
                            seen[signature(shape)].add(index)
                if len(seen) < 2:
                    continue
                shared = {sig for sig, slides in seen.items() if len(slides) > 1}
                if not shared:
                    continue
                reference = sorted({i for sig in shared for i in seen[sig]})
                canonical_value = max(shared, key=lambda sig: len(seen[sig]))
                for index, items in by_slide.items():
                    for slide, shape in items:
                        sig = signature(shape)
                        if not is_text(shape) and sig not in shared:
                            add(subcheck, code, slide, shape, f"{role} difiere de su familia", canonical_value,
                                sig, reference)
            # Tipografía: solo roles singulares (título, kicker, subtítulo…), que deben
            # verse iguales en toda la familia. Un título puede llevar énfasis o no, así
            # que se comparan los estilos usados: es deriva el que solo aparece en una
            # slide. En unidades repetidas el estilo depende del rol de cada párrafo.
            singular = [items[0] for items in by_slide.values() if len(items) == 1 and is_text(items[0][1])]
            if len(singular) == len(by_slide):
                used = {slide.index: run_styles(shape) for slide, shape in singular}
                seen: dict[tuple, set[int]] = defaultdict(set)
                for index, styles in used.items():
                    for style_sig in styles:
                        seen[style_sig].add(index)
                shared = {sig for sig, slides in seen.items() if len(slides) > 1}
                if shared:
                    reference = sorted({i for sig in shared for i in seen[sig]})
                    canonical_value = max(shared, key=lambda sig: len(seen[sig]))
                    allowed = inner_styles(ctx.kn, role)
                    for slide, shape in singular:
                        for style_sig in sorted(used[slide.index] - shared - allowed, key=str):
                            add("typography", "typography_drift", slide, shape, f"{role} difiere de su familia",
                                canonical_value, style_sig, reference)

    if len({tuple(sizes) for sizes in footer_sizes.values()}) > 1:
        canonical_value = Counter(tuple(s) for s in footer_sizes.values()).most_common(1)[0][0]
        for index, sizes in footer_sizes.items():
            if tuple(sizes) != canonical_value:
                slide = ctx.slide(index)
                shape = next(s for s in ctx.presentation.slides[index - 1].shapes
                             if s.name == f"{BRAND_PREFIX}_brand_phrase")
                result.findings.append(Finding(
                    check=AUDITOR, subcheck="footer", code="footer_scale_drift", status="fail",
                    slide_id=index, source_slide_id=slide.source_slide_id, family=slide.family,
                    source_reference=shape.name, symptom="el footer de marca cambia de cuerpo",
                    measurement={"canonical_sz": list(canonical_value), "actual_sz": sizes},
                    cause="footer fuera del componente de marca", correction_proposed="footer a 12 pt en todo el deck",
                    acceptance="un solo cuerpo para neoconsulting.ai",
                ))
    result.findings.extend(brand.findings(ctx, AUDITOR))
    result.findings.extend(policies.findings(ctx, AUDITOR))
    ctx.apply_exceptions(result)
    return result.finish([slide.index for slide in ctx.slides], SUBCHECKS)
