"""Composición libre: validación de la gramática v1 contra el plan de una slide (F1).

Gramática: `design_knowledge/free_layout/grammar.md`. Aquí se decide si una composición libre es
aceptable antes de dibujarla: guardas de marca y que cada rol de contenido quede en exactamente un
bloque (o en el encabezado / pie). La geometría y el dibujo son F2 y F3.
"""
from __future__ import annotations

import re
from collections import Counter

from .schemas import FreeBlock, FreeLayout, FreeNode, PlanValidationIssue, SlidePlan

# Roles que resuelve el encabezado o el pie, sin bloque.
HEADER_ROLES = {"kicker", "title", "subtitle", "tags", "title_note"}
FOOTER_ROLES = {"note"}

# Familias de roles que dibuja cada bloque cuando no nombra sus `units`.
FAMILIES: dict[str, tuple[str, ...]] = {
    "card": ("card",), "metric_card": ("metric",), "item_row": ("item",), "step": ("item",),
    "aside": ("aside",), "banner": ("banner",), "tag": ("tags",), "list_title": ("list_title",),
    "image_message": ("image", "body", "block"), "quadrant": ("quadrant", "axis_x", "axis_y"),
    "matrix": ("header", "row"), "worksheet": ("panel_title", "panel"), "circles": ("circle",),
}
COMPOSITE = {"image_message", "quadrant", "matrix", "worksheet", "circles"}
# Estilos que admite cada bloque; los demás parámetros de estilo no aplican.
STYLES = {"card": {"outline", "header", "rule"}, "item_row": {"card", "rule"}}
ICONS = {"card": {"auto", "top", "left", "header_right", "none"}, "aside": {"auto", "none"}}
# Ancho mínimo (columnas de 12) para que el componente no quede ilegible.
# El panel de trabajo va en un tercio en la referencia aprobada (Taller 1 v7, slide 22).
MIN_SPAN = {"card": 3, "metric_card": 2, "aside": 3, "item_row": 4, "step": 4,
            **{name: 6 for name in COMPOSITE}, "worksheet": 4}
MAX_COMPONENT_KINDS = 3
# La composición libre no aplica a la portada ni al cierre: ambos son canónicos.
NOT_FREE_FAMILIES = {"title_slide", "closing_slide"}

_ROLE = re.compile(r"^(?P<family>[a-z_]+)(?::(?P<index>\d+))?(?::[a-z_]+)?$")


def _key(role: str) -> tuple[str, str]:
    """`card:2:icon` → («card», «card:2»); `banner` → («banner», «banner»)."""
    match = _ROLE.match(role)
    if not match:
        return role, role
    family, index = match["family"], match["index"]
    return family, f"{family}:{index}" if index else family


def _walk(node: FreeNode, span: int = 12):
    """(bloque, ¿repetido?, ancho en columnas, nodo) de cada bloque del árbol."""
    if node.block is not None:
        yield node.block, node.repeat, span, node
    for cell in node.row or []:
        yield from _walk(cell, cell.span)
    for child in node.stack or []:
        yield from _walk(child, span)


def free_layout_issues(slide: SlidePlan) -> list[PlanValidationIssue]:
    """Hallazgos de la composición libre de una slide; vacío si se puede dibujar."""
    issues: list[PlanValidationIssue] = []

    def issue(code: str, detail: str) -> None:
        issues.append(PlanValidationIssue(source_slide_id=slide.source_slide_id, code=code, detail=detail))

    layout = slide.free_layout
    if layout is None:
        issue("free_layout_missing", "composition_layout «free» necesita free_layout.")
        return issues
    if slide.family in NOT_FREE_FAMILIES:
        issue("free_brand_guard", f"La {slide.family} es canónica: la portada y el cierre nunca son libres.")
        return issues
    blocks = list(_walk(layout.body))
    issues += _brand_guards(slide, layout, blocks)
    issues += _coverage(slide, blocks)
    return issues


def _brand_guards(slide: SlidePlan, layout: FreeLayout, blocks) -> list[PlanValidationIssue]:
    found: list[PlanValidationIssue] = []

    def guard(detail: str) -> None:
        found.append(PlanValidationIssue(source_slide_id=slide.source_slide_id, code="free_brand_guard",
                                         detail=detail))

    kinds = {block.component for block, *_ in blocks}
    if len(kinds) > MAX_COMPONENT_KINDS:
        guard(f"{len(kinds)} tipos de bloque ({', '.join(sorted(kinds))}); la marca admite hasta "
              f"{MAX_COMPONENT_KINDS} por slide.")
    dark = [block for block, *_ in blocks if block.tone == "dark"]
    if any(block.component != "aside" for block in dark):
        guard("El tono oscuro solo existe en el panel lateral (aside).")
    if layout.mode == "light" and len(dark) > 1:
        guard(f"{len(dark)} paneles oscuros; en una slide clara va uno como máximo.")
    for block, repeat, span, _node in blocks:
        name = block.component
        if block.style is not None and block.style not in STYLES.get(name, set()):
            allowed = ", ".join(sorted(STYLES.get(name, set()))) or "ninguno"
            guard(f"{name} no tiene el estilo «{block.style}» (admite: {allowed}).")
        if block.icon is not None and block.icon not in ICONS.get(name, {"none"}):
            guard(f"{name} no lleva ícono «{block.icon}».")
        if block.numbered is not None and name not in ("step", "item_row", "card"):
            guard(f"{name} no admite numeración.")
        if name in COMPOSITE and repeat is not None:
            guard(f"{name} es un bloque compuesto: se dibuja una vez, no se repite.")
        if span < MIN_SPAN.get(name, 1):
            guard(f"{name} en {span} columnas queda ilegible; necesita al menos {MIN_SPAN[name]} de 12.")
        if repeat is not None and repeat.unit not in FAMILIES.get(name, ()):
            guard(f"repeat de «{repeat.unit}» con un bloque {name}: no dibuja esa unidad.")
    return found


def _coverage(slide: SlidePlan, blocks) -> list[PlanValidationIssue]:
    """Cada rol de contenido en exactamente un lugar; ningún bloque pide un rol que no existe."""
    found: list[PlanValidationIssue] = []
    present: dict[str, str] = {}
    for assignment in slide.assignments:
        if assignment.classification == "content" and assignment.role:
            family, key = _key(assignment.role)
            present.setdefault(key, family)
    owners: Counter[str] = Counter()
    for key, family in present.items():
        if family in HEADER_ROLES or family in FOOTER_ROLES:
            owners[key] += 1
    for block, repeat, _span, node in blocks:
        wanted = _wanted(block, repeat)
        taken = [key for key, family in present.items() if family in wanted or key in wanted]
        named = set(block.units) - {family for family in FAMILIES.get(block.component, ())}
        missing = sorted(unit for unit in named if unit not in present and unit not in present.values())
        if (missing or not taken) and not node.optional:
            what = ", ".join(missing) if missing else "/".join(sorted(wanted))
            found.append(PlanValidationIssue(
                source_slide_id=slide.source_slide_id, code="free_missing_role",
                detail=f"El bloque {block.component} pide {what}, que la slide no tiene; asígnalo en roles o "
                       "marca el nodo optional."))
        for key in taken:
            owners[key] += 1
    unplaced = sorted(key for key in present if owners[key] == 0)
    if unplaced:
        found.append(PlanValidationIssue(
            source_slide_id=slide.source_slide_id, code="free_unplaced_role",
            detail=f"Contenido sin bloque: {', '.join(unplaced)}. Todo el contenido se conserva: agrega un "
                   "bloque o una repetición que lo dibuje."))
    twice = sorted(key for key, count in owners.items() if count > 1)
    if twice:
        found.append(PlanValidationIssue(
            source_slide_id=slide.source_slide_id, code="free_role_twice",
            detail=f"Contenido en más de un bloque: {', '.join(twice)}."))
    return found


def _wanted(block: FreeBlock, repeat) -> set[str]:
    """Familias o claves exactas que dibuja el bloque."""
    if repeat is not None:
        return {repeat.unit}
    return set(block.units) if block.units else set(FAMILIES.get(block.component, ()))


# Lo que el motor ya dibuja (F2 y F3). El resto de la gramática es válido, pero todavía no se dibuja.
DRAWN = {"card", "item_row", "step", "aside", "banner", "list_title", "metric_card",
         "quadrant", "matrix", "worksheet", "circles", "image_message"}


def render_gaps(slide: SlidePlan) -> list[str]:
    """Lo que la composición pide y el motor todavía no dibuja; vacío si se puede componer."""
    layout = slide.free_layout
    gaps: list[str] = []
    for block, repeat, _span, _node in _walk(layout.body):
        if block.component not in DRAWN:
            gaps.append(f"bloque {block.component}")
        if block.component == "card" and block.style == "rule":
            gaps.append("card con estilo rule")
    if layout.mode == "dark":
        gaps.append("modo oscuro")
    return sorted(set(gaps))


# Nombre (rol) con que el renderer deja cada componente en el PPTX: `<rol>_<n>`.
DRAWN_ROLE = {"card": "card", "item_row": "item", "step": "step_text", "aside": "aside",
              "banner": "banner", "list_title": "list_title", "metric_card": "metric_card",
              "quadrant": "quadrant", "matrix": "matrix_cell", "worksheet": "panel", "circles": "circle"}
# Otra forma dibujada del mismo componente: una fila `style: rule` no lleva caja, su marca es la
# línea. Sin esto la auditoría contaba «item 0/4» con las filas a la vista (IA, 2026-10-27).
DRAWN_ALIASES = {"item_rule": "item"}


def expected_components(slide: SlidePlan) -> Counter:
    """Cuántos componentes de cada rol debe tener la slide dibujada, según su gramática."""
    keys: dict[str, set[str]] = {}
    for assignment in slide.assignments:
        if assignment.classification == "content" and assignment.role:
            family, key = _key(assignment.role)
            keys.setdefault("card" if family == "item" else family, set()).add(
                key.replace("item:", "card:", 1) if family == "item" else key)
    expected: Counter = Counter()
    for block, repeat, _span, node in _walk(slide.free_layout.body):
        role = DRAWN_ROLE.get(block.component)
        if role is None:
            continue
        family = {"card": "card", "item_row": "card", "step": "card", "aside": "aside"}.get(block.component)
        if family:
            pool = keys.get(family, set())
            named = {unit.replace("item:", "card:", 1) for unit in block.units if ":" in unit}
            expected[role] += len(pool) if repeat is not None or not named else len(named & pool)
        elif block.component == "banner":
            expected[role] += 1 if "banner" in keys else 0
        elif block.component == "list_title":
            expected[role] += 1 if "list_title" in keys else 0
        elif block.component == "metric_card":
            pool = keys.get("metric", set())
            named = {unit for unit in block.units if ":" in unit}
            expected[role] += len(pool) if repeat is not None or not named else len(named & pool)
        elif block.component == "quadrant":
            expected[role] += min(4, len(keys.get("quadrant", set())))
        elif block.component == "circles":
            expected[role] += len(keys.get("circle", set()))
        elif block.component == "matrix":
            # Una celda por caja de cada fila.
            expected[role] += sum(1 for assignment in slide.assignments
                                  if assignment.classification == "content" and assignment.role
                                  and _key(assignment.role)[0] == "row")
        elif block.component == "worksheet":
            expected[role] += 1 if keys.keys() & {"panel", "panel_title"} else 0
    return +expected


# Qué hace cada bloque, para la guía del modelo (`grammar_guide`).
BLOCK_HELP = {
    "card": "una card por unidad card:N (roles por párrafo)",
    "metric_card": "una cifra por metric:N (value, label, description)",
    "item_row": "una fila por item:N",
    "step": "un paso por item:N (número en círculo si el autor numeró)",
    "aside": "panel lateral aside:N; tone dark = panel navy",
    "banner": "banda de cierre (rol banner)",
    "list_title": "rótulo de lista (rol list_title)",
    "image_message": "imágenes (image:N) con su mensaje (body o block:N; block:N:image lleva su imagen; "
                     "si cada bloque lleva la suya, fichas iguales con la foto y su texto)",
    "quadrant": "matriz 2×2 (quadrant:1..4) con ejes (axis_x, axis_y); params.focus = cuadrante en azul",
    "matrix": "tabla: encabezados (header) y filas (row:N, una caja por celda)",
    "worksheet": "panel de trabajo: panel_title y consignas (panel) con renglones",
    "circles": "círculos (circle:N); params.focus center | right agranda uno",
}


# Estilos válidos en la gramática que el motor todavía no dibuja (no se anuncian).
UNDRAWN_STYLES = {"card": {"rule"}}


def grammar_guide() -> str:
    """Descripción de `free_layout` para el modelo, generada de las tablas de este módulo: si un
    bloque o una guarda cambian aquí, la descripción cambia con ellos."""
    drawn = [name for name in BLOCK_HELP if name in DRAWN]
    blocks = "; ".join(
        f"{name} ({BLOCK_HELP[name]}; span mín. {MIN_SPAN.get(name, 1)}"
        + (f"; style {'|'.join(sorted(STYLES[name] - UNDRAWN_STYLES.get(name, set())))}" if name in STYLES else "")
        + (f"; icon {'|'.join(sorted(ICONS[name]))}" if name in ICONS else "") + ")"
        for name in drawn)
    return (
        "Composición libre, SOLO si la persona pidió otro diseño u otra organización para esta slide "
        "(«no me gusta, dame otro diseño», «organízala distinto», «usa un panel oscuro»); nunca como salida "
        "cuando un layout no cabe. reason cita lo que dijo. Describe la organización y el motor mide y dibuja "
        "con la marca: no das coordenadas ni tamaños. Árbol: body es un nodo = {block} | {repeat, block} "
        "(el mismo bloque por cada unidad: repeat.unit card|item|metric|aside, columns auto|1-4) | "
        "{row: [celdas con span 1-12 que suman ≤ 12, align top|center|stretch]} | {stack: [nodos]}; cualquier "
        "nodo admite height auto|fill y optional. header.title_style title|statement; el encabezado toma "
        "kicker, title, subtitle, tags (arriba a la derecha) y title_note (nota corta a la derecha del título). "
        f"Bloques: {blocks}. numbered: true pone 1, 2, 3 decorativos en step, item_row o card cuando el autor no "
        "numeró. accents (máx. 2, sin contenido): accent_bar (barra junto al título), divider (línea bajo el "
        f"encabezado). Guardas: hasta {MAX_COMPONENT_KINDS} tipos de bloque, un solo panel oscuro, los compuestos "
        "no se repiten, portada y cierre nunca son libres. Todo rol de contenido va en exactamente un bloque o "
        "en el encabezado/pie (note). Nunca agregues íconos que la slide no tenga. Ej.: {\"reason\": \"pidió las "
        "cifras arriba y la conclusión en un panel\", \"body\": {\"stack\": [{\"repeat\": {\"unit\": "
        "\"metric\"}, \"block\": {\"component\": \"metric_card\"}}, {\"row\": [{\"span\": 8, \"repeat\": "
        "{\"unit\": \"item\"}, \"block\": {\"component\": \"step\"}}, {\"span\": 4, \"block\": "
        "{\"component\": \"aside\", \"tone\": \"dark\"}}]}]}}."
    )
