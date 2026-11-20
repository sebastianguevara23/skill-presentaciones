"""Puente explícito entre `AnalysisPlan` y los layouts renderizables.

No intenta adivinar slots ni degradar una decisión incompleta a `brand_shell`.
Los slots de cada layout se leen de `design_knowledge/layouts/<layout>.yaml`, y la
familia aporta su composición por defecto (`composition` en `visual_catalog.yaml`):
el host decide la familia y los roles, el puente comprueba que llenan el layout.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import re

from .knowledge import Knowledge
from .split import propose_parts, renumber, units_of
from .schemas import (
    AnalysisPlan,
    CardSlot,
    DeckClassification,
    ElementAssignment,
    MetricSlot,
    PlanValidationIssue,
    SlideClassification,
    SlidePlan,
    SourceManifest,
)

# Slots que admiten varios elementos con un rol distinto al nombre del slot.
MULTI_SLOTS = {"notes": "note", "body": "body"}
_UNIT_ROLE = re.compile(r"^(?P<unit>[a-z_]+):(?P<index>\d+)(?::(?P<part>[a-z_]+))?$")
# Claves de un slot que lo convierten en algo distinto de un texto único.
_STRUCTURAL = ("count", "max", "groups", "multiple")


@dataclass(frozen=True)
class LayoutSlots:
    """Lo que un layout acepta, leído de su YAML; ningún número vive en el código."""

    layout: str
    singular: dict[str, bool]                  # rol → obligatorio (title, kicker, list_title…)
    multi: set[str]                            # roles con varias cajas: note, body, tags, header…
    unit: str | None = None                    # "card", "item", "member", "circle", "row"…
    minimum: int = 0
    maximum: int = 0
    paragraph_roles: bool = False              # un rol por párrafo no vacío
    free: bool = False                         # la unidad acepta cajas sin roles de párrafo
    attach: tuple[str, ...] = ()               # imágenes de la unidad: icon, photo
    parts: tuple[str, ...] = ()                # piezas de texto de la unidad: value, label…
    images: int = 0                            # imágenes editoriales admitidas
    group: str | None = None                   # grupo secundario (aside:N): cajas libres
    group_minimum: int = 0
    group_maximum: int = 0
    group_attach: tuple[str, ...] = ()


def _range(value) -> tuple[int, int]:
    if isinstance(value, int):
        return value, value
    first, _, last = str(value).partition("-")
    return int(first), int(last or first)


def layout_slots(knowledge: Knowledge, layout: str) -> LayoutSlots:
    slots = knowledge.slots(layout)
    singular: dict[str, bool] = {}
    multi = {role for name, role in MULTI_SLOTS.items() if name in slots}
    group, group_range, group_attach = None, (0, 0), ()
    for name, definition in slots.items():
        if not isinstance(definition, dict) or definition.get("plan") is False or name in MULTI_SLOTS:
            continue
        if definition.get("multiple"):
            multi.add(name)
        elif "groups" in definition:
            group, group_range = name, _range(definition["groups"])
            group_attach = tuple(definition.get("attach", []))
        elif not any(key in definition for key in _STRUCTURAL):
            singular[name] = bool(definition.get("required"))
    capacity = knowledge.capacity(layout)
    unit_def = next(
        (definition for definition in slots.values() if isinstance(definition, dict) and "count" in definition),
        {},
    )
    images = int(slots.get("images", {}).get("max", 0)) if "images" in slots else 0
    return LayoutSlots(
        layout=layout,
        singular=singular,
        multi=multi,
        unit=capacity.unit if capacity else None,
        minimum=capacity.minimum if capacity else 0,
        maximum=capacity.maximum if capacity else 0,
        paragraph_roles="roles" in unit_def,
        free=bool(unit_def.get("free")),
        attach=tuple(unit_def.get("attach", [])),
        parts=tuple(unit_def.get("parts", [])),
        images=images,
        group=group,
        group_minimum=group_range[0],
        group_maximum=group_range[1],
        group_attach=group_attach,
    )


def reading_order(source, tolerance: float = 0.02) -> dict[str, tuple[int, float]]:
    """Clave de lectura por elemento: banda de fila y luego x.

    Dos cajas de la misma fila rara vez comparten y exacta (un número de paso suele ir
    2 pt más abajo que su texto); ordenar solo por y las invertiría. Las cajas cuyo borde
    superior cae dentro de `tolerance` × alto de la slide forman una banda. Una caja centrada
    verticalmente junto a otra de la banda (el número de una fila alta) también entra en ella
    aunque su borde superior quede más abajo.
    """
    height = max((element.box.y + element.box.h for element in source.elements), default=1.0)
    band_limit = tolerance * max(height, 1.0)
    order: dict[str, tuple[int, float]] = {}
    band, band_start, centers = -1, None, []
    for element in sorted(source.elements, key=lambda item: item.box.y):
        center = element.box.y + element.box.h / 2
        same_band = band_start is not None and (
            element.box.y - band_start <= band_limit or any(abs(center - c) <= band_limit for c in centers)
        )
        if not same_band:
            band, band_start, centers = band + 1, element.box.y, []
        centers.append(center)
        order[element.id] = (band, element.box.x)
    return order


def _paragraphs(element) -> list[str]:
    """Párrafos no vacíos del elemento, los mismos que el compositor recibirá."""
    if element.paragraphs:
        return element.paragraphs
    return [part for part in (element.text or "").split("\n") if part.strip()]


def effective_layout(slide: SlidePlan, knowledge: Knowledge) -> str | None:
    """El layout explícito del plan o, si no hay, la composición registrada de la familia."""
    return knowledge.layout_for(slide.family, slide.composition_layout, slide.archetype)


def _source_index(source_slide_id: str) -> int:
    if not source_slide_id.startswith("s") or not source_slide_id[1:].isdigit():
        raise ValueError(f"source_slide_id inválido: {source_slide_id}")
    return int(source_slide_id[1:])


def _split_issues(slide: SlidePlan, layout: str, knowledge: Knowledge) -> list[PlanValidationIssue]:
    """La partición se valida contra condiciones, no contra el deck del que vino.

    Comprueba que la familia admite partirse, que la composición declara capacidad,
    que cada unidad aparece exactamente una vez y en orden, y que ninguna parte queda
    fuera del rango que el layout sostiene.
    """
    issues: list[PlanValidationIssue] = []

    def issue(code: str, detail: str) -> None:
        issues.append(PlanValidationIssue(source_slide_id=slide.source_slide_id, code=code, detail=detail))

    if not slide.split_parts:
        return issues
    if not knowledge.splittable(slide.family):
        issue("family_not_splittable", f"La familia {slide.family} es singular: no se reparte en varias slides.")
    capacity = knowledge.capacity(layout)
    if capacity is None:
        issue("layout_without_capacity", f"El layout {layout} no declara unidades repetidas.")
        return issues
    units = units_of(slide.assignments, capacity.unit)
    flattened = [key for part in slide.split_parts for key in part]
    if sorted(flattened) != sorted(units.keys) or len(flattened) != len(set(flattened)):
        issue("split_parts_coverage", "Cada unidad de la slide debe aparecer exactamente una vez en las partes.")
    elif flattened != units.keys:
        issue("split_parts_order", "Las partes deben conservar el orden de las unidades de origen.")
    for position, part in enumerate(slide.split_parts, start=1):
        if not capacity.fits(len(part)):
            issue(
                "split_part_capacity",
                f"La parte {position} lleva {len(part)} {capacity.unit}(s) y {layout} "
                f"admite entre {capacity.minimum} y {capacity.maximum}.",
            )
    return issues


def _split_suggestion(slide: SlidePlan, layout: str, knowledge: Knowledge) -> list[PlanValidationIssue]:
    """Aviso, no veredicto: la slide trae más unidades de las que sostiene su composición.

    Se emite como advertencia con la propuesta ya calculada para que el host la acepte
    o la cambie; el motor no parte nada por su cuenta.
    """
    if slide.split_parts:
        return []
    capacity = knowledge.capacity(layout)
    if capacity is None or not knowledge.splittable(slide.family):
        return []
    units = units_of(slide.assignments, capacity.unit)
    parts, reason = propose_parts(units, capacity)
    if not parts:
        return []
    proposal = " | ".join(", ".join(part) for part in parts)
    return [PlanValidationIssue(
        source_slide_id=slide.source_slide_id,
        code="split_suggested",
        severity="warning",
        detail=(
            f"{len(units)} {capacity.unit}(s) para una composición de {capacity.minimum}-{capacity.maximum} "
            f"({reason}). Propuesta sin resumir: {proposal}."
        ),
    )]


def _issues_for_slide(
    slide: SlidePlan, manifest: SourceManifest, knowledge: Knowledge
) -> list[PlanValidationIssue]:
    """Comprueba que el plan puede llenar exactamente un layout conocido."""
    if not slide.selected_for_redesign or slide.keep_layout:
        # Con `keep_layout` la slide conserva su organización: no llena slots de ningún layout.
        return []
    issues = list(_borrowed_issues(slide, manifest, knowledge))

    def issue(code: str, detail: str) -> None:
        issues.append(PlanValidationIssue(source_slide_id=slide.source_slide_id, code=code, detail=detail))

    if slide.composition_layout == "free":
        # Composición libre (plans/composicion-libre.md): su propia validación. Todavía no se
        # dibuja: hasta F3 el plan se guarda pero no se aplica, y lo dice.
        from .free_layout import free_layout_issues, render_gaps
        issues += free_layout_issues(slide)
        # Cards, filas, pasos y círculos se dibujan por rol de párrafo, como en los layouts fijos.
        source_by_id = {element.id: element for element in manifest.slide(slide.source_slide_id).elements}
        for assignment in slide.assignments:
            match = _UNIT_ROLE.match(assignment.role or "")
            if (assignment.classification != "content" or not match or match["part"]
                    or match["unit"] not in FREE_PARAGRAPH_UNITS or assignment.element_id not in source_by_id):
                continue
            paragraphs = _paragraphs(source_by_id[assignment.element_id])
            if len(assignment.paragraph_roles) != len(paragraphs):
                issue("card_paragraph_roles",
                      f"{assignment.role} ({assignment.element_id}) requiere un rol por cada párrafo no vacío "
                      f"({len(paragraphs)}).")
        gaps = render_gaps(slide) if not any(found.severity == "error" for found in issues) else []
        if gaps:
            issue("free_not_supported_yet",
                  f"La composición es válida, pero el motor todavía no dibuja: {', '.join(gaps)}.")
        return issues
    layout = effective_layout(slide, knowledge)
    if layout is None:
        issue(
            "missing_composition_layout",
            f"La familia {slide.family} no tiene composición registrada y el plan no nombra un layout.",
        )
        return issues
    if layout not in knowledge.layouts:
        issue("unsupported_composition_layout", f"Layout no soportado: {layout}")
        return issues
    if any(element.chart is not None for element in manifest.slide(slide.source_slide_id).elements):
        issue(
            "native_chart_without_slot",
            "La slide tiene un gráfico nativo y ningún layout tiene slot de gráfico: déjala fuera del "
            "rediseño; se conserva en su lugar con la marca aplicada al gráfico.",
        )
        return issues
    issues += _split_issues(slide, layout, knowledge)
    issues += _split_suggestion(slide, layout, knowledge)
    if any(issue.severity == "error" for issue in issues):
        return issues
    source = manifest.slide(slide.source_slide_id)
    source_by_id = {element.id: element for element in source.elements}
    slots = layout_slots(knowledge, layout)
    for part_assignments in _part_assignments(slide, slots.unit):
        issues += _slot_issues(slide, slots, part_assignments, source_by_id)
    if slots.images and not any(
        (assignment.role or "").startswith("image:") or (assignment.role or "").endswith(":image")
        for assignment in slide.assignments if assignment.classification == "content"
    ):
        issues.append(PlanValidationIssue(
            source_slide_id=slide.source_slide_id, code="missing_required_slot",
            detail=f"El layout {layout} requiere al menos una imagen.",
        ))
    issues += _body_order_issues(slide, source)
    return issues


def accepts_icons(slide: SlidePlan, knowledge: Knowledge) -> bool:
    """¿El diseño de la slide dibuja un ícono por unidad? (layout con `attach: [icon]` o una
    composición libre con cards)."""
    if slide.composition_layout == "free":
        from .free_layout import _walk
        return slide.free_layout is not None and any(
            block.component == "card" for block, *_ in _walk(slide.free_layout.body))
    layout = effective_layout(slide, knowledge)
    return bool(layout) and layout in knowledge.layouts and "icon" in layout_slots(knowledge, layout).attach


def _borrowed_issues(slide: SlidePlan, manifest: SourceManifest, knowledge: Knowledge):
    """Íconos prestados (F5b): imagen de otra slide del deck, a una unidad que existe y lo dibuja."""
    if not slide.borrowed_images:
        return
    units = {(a.role or "").replace("item:", "card:", 1) for a in slide.assignments if a.classification == "content"}

    def issue(detail: str) -> PlanValidationIssue:
        return PlanValidationIssue(source_slide_id=slide.source_slide_id, code="borrowed_image_invalid", detail=detail)

    if not accepts_icons(slide, knowledge):
        yield issue("el diseño de esta slide no lleva íconos en sus unidades: elige uno con íconos "
                    "(o copia también el diseño de la slide de origen).")
    for item in slide.borrowed_images:
        source_id = item.element_id.split(":", 1)[0]
        element = next((e for e in manifest.slide(source_id).elements if e.id == item.element_id), None) \
            if any(s.id == source_id for s in manifest.slides) else None
        match = _UNIT_ROLE.match(item.role)
        if source_id == slide.source_slide_id:
            yield issue(f"{item.element_id} ya es de esta slide: se asigna con roles, no se presta.")
        elif element is None or element.kind != "image":
            yield issue(f"{item.element_id} no es una imagen del deck.")
        elif not match or match["part"] != "icon" or f"{match['unit']}:{match['index']}".replace("item:", "card:", 1) not in units:
            yield issue(f"{item.role}: el ícono prestado va a una unidad de esta slide (`card:N:icon`).")


def _columns_order(boxes: dict[str, object]) -> list[str]:
    """Orden por columnas: cajas que se solapan en x forman columna; se lee columna a columna."""
    return [element_id for column in _column_groups(boxes) for element_id in column]


def _column_groups(boxes: dict[str, object]) -> list[list[str]]:
    """Columnas de cajas (se solapan en x), cada una ordenada de arriba abajo."""
    columns: list[list[str]] = []
    spans: list[tuple[float, float]] = []
    for element_id in sorted(boxes, key=lambda key: boxes[key].x):
        box = boxes[element_id]
        for index, (left, right) in enumerate(spans):
            if box.x < right - 1 and box.x + box.w > left + 1:
                columns[index].append(element_id)
                spans[index] = (min(left, box.x), max(right, box.x + box.w))
                break
        else:
            columns.append([element_id])
            spans.append((box.x, box.x + box.w))
    return [sorted(column, key=lambda key: boxes[key].y) for column in columns]


def _body_order_issues(slide: SlidePlan, source) -> list[PlanValidationIssue]:
    """Aviso: varias cajas de `body` cuyo orden por filas y por columnas no coincide.

    El cuerpo sin numerar se lee por bandas de fila (`reading_order`); en un origen a dos
    columnas eso intercala los pasos (1, 3, 2, 4). El orden es contenido: el host lo fija
    con `block:N`.
    """
    body = [a.element_id for a in slide.assignments if a.classification == "content" and a.role == "body"]
    if len(body) < 2:
        return []
    by_id = {element.id: element for element in source.elements}
    reading = reading_order(source)
    band = sorted(body, key=lambda element_id: reading[element_id])
    columns = _columns_order({element_id: by_id[element_id].box for element_id in body})
    if band == columns:
        return []
    local = {element_id: by_id[element_id].local_id for element_id in body}
    return [PlanValidationIssue(
        source_slide_id=slide.source_slide_id, code="body_order_ambiguous", severity="warning",
        detail=(
            "El cuerpo se leería por filas (" + ", ".join(local[e] for e in band) + ") y el origen también "
            "admite columnas (" + ", ".join(local[e] for e in columns) + "). Fija el orden con block:1..n."
        ),
    )]


# Marco que cada parte de una partición repite: sin él la slide de continuación no se
# entiende (título, encabezados de columna de una tabla, etiquetas de meta).
REPEATED_IN_PARTS = {"kicker", "title", "tags", "header", "list_title"}


def _owned_by_part(assignment, position: int, last: int) -> bool:
    """Qué parte de una partición lleva cada bloque compartido.

    El marco se repite; la introducción va solo en la primera parte y el resto de lo
    compartido (banner, notas, mensaje, paneles) en la última: una slide de continuación
    no clona el texto explicativo (convenciones, `repeat_shared_intro`).
    """
    if assignment.classification != "content":
        return True
    base = (assignment.role or "").split(":")[0]
    if base in REPEATED_IN_PARTS:
        return True
    if base == "subtitle":
        return position == 0
    return position == last


def _part_assignments(slide: SlidePlan, unit: str | None = None) -> list[list]:
    """Las asignaciones de cada slide de salida: una sola lista si no hay partición."""
    if not slide.split_parts:
        return [list(slide.assignments)]
    last = len(slide.split_parts) - 1
    parts = []
    for position, part in enumerate(slide.split_parts):
        renumbered = renumber(slide.assignments, part, unit)
        parts.append([
            assignment for assignment in renumbered
            if _is_unit_role(assignment.role, unit) or _owned_by_part(assignment, position, last)
        ])
    return parts


def _is_unit_role(role: str | None, unit: str | None) -> bool:
    match = _UNIT_ROLE.match(role or "")
    return bool(match and unit and match["unit"] == unit)


def _slot_issues(slide: SlidePlan, slots: LayoutSlots, assignments: list, source_by_id: dict) -> list[PlanValidationIssue]:
    """Valida una sola slide de salida contra los slots de su layout."""
    issues: list[PlanValidationIssue] = []
    layout = slots.layout

    def issue(code: str, detail: str) -> None:
        issues.append(PlanValidationIssue(source_slide_id=slide.source_slide_id, code=code, detail=detail))

    def expect_kind(assignment, kind: str) -> None:
        element = source_by_id[assignment.element_id]
        if element.kind != kind:
            issue(
                "role_kind_mismatch",
                f"El rol {assignment.role} requiere un elemento de tipo {kind} y {assignment.element_id} es {element.kind}.",
            )

    unit_texts = slots.paragraph_roles or slots.free
    roles: dict[str, list] = defaultdict(list)
    units: dict[int, dict[str | None, list]] = defaultdict(lambda: defaultdict(list))
    groups: dict[int, dict[str | None, list]] = defaultdict(lambda: defaultdict(list))
    images: dict[int, list] = defaultdict(list)
    for assignment in assignments:
        if assignment.classification != "content":
            continue
        role = assignment.role
        if not role:
            issue("missing_content_role", f"El contenido {assignment.element_id} no tiene slot de composición.")
            continue
        roles[role].append(assignment)
        match = _UNIT_ROLE.match(role)
        if role in slots.singular or role in slots.multi:
            expect_kind(assignment, "text")
        elif match and match["unit"] == "image" and slots.images and match["part"] is None:
            images[int(match["index"])].append(assignment)
            expect_kind(assignment, "image")
        elif match and match["unit"] == slots.unit and (
            (match["part"] is None and unit_texts)
            or match["part"] in slots.attach or match["part"] in slots.parts
        ) and int(match["index"]) <= slots.maximum:
            units[int(match["index"])][match["part"]].append(assignment)
            expect_kind(assignment, "image" if match["part"] in slots.attach else "text")
        elif match and match["unit"] == slots.group and (
            match["part"] is None or match["part"] in slots.group_attach
        ) and int(match["index"]) <= slots.group_maximum:
            groups[int(match["index"])][match["part"]].append(assignment)
            expect_kind(assignment, "image" if match["part"] else "text")
        else:
            issue("unsupported_content_role", f"El rol {role} no pertenece a {layout}.")
    for role, items in roles.items():
        match = _UNIT_ROLE.match(role)
        several = role in slots.multi or bool(
            match and match["part"] is None and (
                (match["unit"] == slots.unit and unit_texts) or match["unit"] == slots.group
            )
        )
        if len(items) > 1 and not several:
            issue("duplicate_composition_role", f"El slot {role} tiene más de un elemento.")

    for role, required in slots.singular.items():
        if required and len(roles.get(role, [])) != 1:
            issue("missing_required_slot", f"El layout {layout} requiere exactamente un {role}.")

    if slots.unit and roles.get("body") and units:
        issue("body_and_blocks", f"Usa body o {slots.unit}:N, no ambos: el orden entre ellos quedaría sin definir.")
    if slots.unit and (units or slots.minimum > 0):
        indices = sorted(units)
        if not indices:
            issue("missing_required_slot", f"El layout {layout} requiere al menos {slots.minimum} {slots.unit}(s).")
        elif indices != list(range(1, len(indices) + 1)):
            issue("unit_numbering", f"Las unidades {slots.unit} deben numerarse 1..n sin huecos: {indices}.")
        elif not slots.minimum <= len(indices) <= slots.maximum:
            issue(
                "unit_count",
                f"{layout} admite entre {slots.minimum} y {slots.maximum} {slots.unit}(s); llegaron {len(indices)}.",
            )
        for index in indices:
            parts = units[index]
            if unit_texts:
                texts = parts.get(None, [])
                if not texts:
                    issue("missing_required_slot", f"La unidad {slots.unit}:{index} necesita al menos un texto.")
                    continue
                if not slots.paragraph_roles:
                    continue
                # Una unidad puede juntar varias cajas (título y cuerpo separados): cada
                # una trae un rol por párrafo no vacío.
                for text in texts:
                    paragraphs = _paragraphs(source_by_id[text.element_id])
                    if len(text.paragraph_roles) != len(paragraphs):
                        issue(
                            "card_paragraph_roles",
                            f"{slots.unit}:{index} ({text.element_id}) requiere un rol por cada "
                            f"párrafo no vacío ({len(paragraphs)}).",
                        )
            elif slots.parts and not parts.get(slots.parts[0]):
                issue(
                    "metric_slots",
                    f"{slots.unit}:{index} requiere su {slots.parts[0]}.",
                )
    if slots.group:
        indices = sorted(groups)
        if indices and indices != list(range(1, len(indices) + 1)):
            issue("unit_numbering", f"Los grupos {slots.group} deben numerarse 1..n sin huecos: {indices}.")
        elif not slots.group_minimum <= len(indices) <= slots.group_maximum:
            issue(
                "unit_count",
                f"{layout} admite entre {slots.group_minimum} y {slots.group_maximum} {slots.group}(s).",
            )
        for index in indices:
            if not groups[index].get(None):
                issue("missing_required_slot", f"El grupo {slots.group}:{index} necesita al menos un texto.")
    if slots.images:
        # Que haya al menos una imagen se comprueba sobre la slide entera: una parte de
        # una partición puede quedar solo con texto.
        indices = sorted(images)
        attached = sum(1 for parts in units.values() if parts.get("image"))
        if indices and (indices != list(range(1, len(indices) + 1)) or len(indices) > slots.images):
            issue("image_slots", f"{layout} admite image:1..image:{slots.images} sin huecos; llegaron {indices}.")
        elif len(indices) + attached > slots.images:
            issue("image_slots", f"{layout} admite hasta {slots.images} imágenes por slide; llegaron {len(indices) + attached}.")
    return issues


def renderability_issues(
    manifest: SourceManifest, plan: AnalysisPlan, knowledge: Knowledge | None = None
) -> list[PlanValidationIssue]:
    knowledge = knowledge or Knowledge()
    by_id = {slide.source_slide_id: slide for slide in plan.slides}
    return [
        issue
        for source_slide in manifest.slides
        for issue in _issues_for_slide(by_id[source_slide.id], manifest, knowledge)
    ]


def to_legacy_classification(
    manifest: SourceManifest, plan: AnalysisPlan, knowledge: Knowledge | None = None
) -> DeckClassification:
    """Convierte únicamente un plan renderizable; el llamador valida antes.

    Una slide partida produce varias entradas con el mismo índice de origen, en el
    orden de las partes: el renderizador las convierte en slides consecutivas.
    """
    knowledge = knowledge or Knowledge()
    issues = [issue for issue in renderability_issues(manifest, plan, knowledge) if issue.severity == "error"]
    if issues:
        raise ValueError("plan no renderizable: " + ", ".join(issue.code for issue in issues))
    classifications = []
    for slide in plan.slides:
        if not slide.selected_for_redesign or slide.keep_layout:
            continue
        source = manifest.slide(slide.source_slide_id)
        local_ids = {element.id: element.local_id for element in source.elements}
        layout = effective_layout(slide, knowledge)
        slots = layout_slots(knowledge, layout)
        # Las cajas de una misma unidad se leen en orden visual (arriba-abajo, izquierda-
        # derecha): el orden XML a veces pone el cuerpo antes que su título.
        reading = reading_order(source)
        boxes = {element.id: element.box for element in source.elements}
        slide = _absorb_brand_phrase(slide, source, knowledge)
        for assignments in _part_assignments(slide, slots.unit):
            classifications.append(_classify_part(slide, slots, assignments, local_ids, knowledge, reading, boxes))
    shell_decorative: dict[int, list[int]] = {}
    for slide in plan.slides:
        if slide.selected_for_redesign and not slide.keep_layout:
            continue
        by_id = {element.id: element for element in manifest.slide(slide.source_slide_id).elements}
        shapes = [by_id[a.element_id].source_shape_id for a in slide.assignments
                  if a.classification == "decorative" and a.element_id in by_id
                  and by_id[a.element_id].kind == "shape" and by_id[a.element_id].source_shape_id is not None]
        if shapes:
            shell_decorative[_source_index(slide.source_slide_id)] = shapes
    asset_classes = {
        _source_index(slide.source_slide_id): {element_id.split(":", 1)[1]: cls for element_id, cls in slide.asset_classes.items()}
        for slide in plan.slides if slide.asset_classes
    }
    # Un ícono prestado es un ícono también en su slide de origen: sin JPEG, con guarda de detalle.
    for slide in plan.slides:
        for item in slide.borrowed_images if slide.selected_for_redesign else []:
            source_id, local = item.element_id.split(":", 1)
            asset_classes.setdefault(_source_index(source_id), {}).setdefault(local, "icon")
    keep_layout: dict[int, str] = {}
    shell_brand: dict[int, list[int]] = {}
    for slide in plan.slides:
        if slide.selected_for_redesign and not slide.keep_layout:
            continue
        index = _source_index(slide.source_slide_id)
        if slide.keep_layout:
            keep_layout[index] = slide.family
        # También en una slide conservada sin rediseño: el logo que el plan marcó como marca (la
        # copia del logo del cliente en una esquina) lo reemplaza el bloque NEO | cliente.
        by_id = {element.id: element for element in manifest.slide(slide.source_slide_id).elements}
        logos = [by_id[a.element_id].source_shape_id for a in slide.assignments
                 if a.classification == "brand" and a.element_id in by_id
                 and by_id[a.element_id].kind == "image" and by_id[a.element_id].source_shape_id is not None]
        if logos:
            shell_brand[index] = logos
    return DeckClassification(source=manifest.source_deck_id, slides=classifications,
                              shell_decorative=shell_decorative, asset_classes=asset_classes,
                              keep_layout=keep_layout, shell_brand=shell_brand)


# Unidades de los bloques compuestos de la composición libre (además de `card`).
FREE_COMPOSITE_UNITS = ("quadrant", "row", "circle", "block")
# Unidades que se dibujan con un rol por párrafo (`paragraph_roles`).
FREE_PARAGRAPH_UNITS = ("card", "item", "circle")

# Slots sueltos donde una caja con solo la frase de marca es el pie del autor, no contenido.
_PHRASE_ROLES = {"note", "body", "subtitle", "kicker"}


def absorbs_brand_phrase(assignment, element, knowledge: Knowledge) -> bool:
    """Una caja suelta del origen que dice solo la frase de marca («neoconsulting.ai»)."""
    phrase = knowledge.tokens["brand"]["phrase"]["text"].casefold()
    return (assignment.classification == "content" and element is not None and element.kind == "text"
            and (assignment.role or "").split(":")[0] in _PHRASE_ROLES
            and " ".join(_paragraphs(element)).strip().casefold() == phrase)


def _absorb_brand_phrase(slide: SlidePlan, source, knowledge: Knowledge) -> SlidePlan:
    """La caja del origen que dice solo «neoconsulting.ai» pasa a `brand`.

    Toda slide rediseñada ya lleva el pie de marca; si el plan deja esa caja como nota, el
    pie sale dos veces (izquierda y derecha). Como `brand`, el pie de marca la reemplaza y
    la integridad no la exige (la auditoría de contenido aplica la misma excepción).
    """
    by_id = {element.id: element for element in source.elements}
    assignments = [
        assignment.model_copy(update={"classification": "brand", "role": None, "paragraph_roles": []})
        if absorbs_brand_phrase(assignment, by_id.get(assignment.element_id), knowledge) else assignment
        for assignment in slide.assignments
    ]
    return slide.model_copy(update={"assignments": assignments})


def _classify_part(
    slide: SlidePlan, slots: LayoutSlots, assignments: list, local_ids: dict, knowledge: Knowledge,
    reading: dict | None = None, boxes: dict | None = None,
) -> SlideClassification:
    """Una slide de salida: los roles ya vienen renumerados a 1..n para esta parte."""
    by_role: dict[str, list] = defaultdict(list)
    for assignment in assignments:
        if assignment.classification == "content":
            role = assignment.role
            if slots.layout == "free" and role and role.startswith("item:"):
                # En la composición libre, filas y pasos son la unidad `card` (free.yaml).
                role = "card:" + role[len("item:"):]
            by_role[role].append(assignment)
    # Íconos prestados de otra slide (F5b): entran como el ícono de su unidad, con un id local
    # propio; el motor inyecta la imagen antes de componer. Solo los de unidades de esta parte.
    borrowed: dict[str, str] = {}
    for item in slide.borrowed_images:
        role = item.role.replace("item:", "card:", 1) if slots.layout == "free" else item.role
        unit = role.rsplit(":", 1)[0]
        if unit in by_role and not by_role.get(role):
            local = "b" + item.element_id.replace(":", "_")
            local_ids = {**local_ids, item.element_id: local}
            by_role[role].append(ElementAssignment(element_id=item.element_id, classification="content", role=role))
            borrowed[local] = item.element_id

    def ordered(role: str) -> list[str]:
        """Las cajas de un rol en orden visual: el XML a veces pone el cuerpo primero."""
        entries = sorted(by_role.get(role, []), key=lambda item: (reading or {}).get(item.element_id, (0, 0)))
        return [local_ids[entry.element_id] for entry in entries]

    def optional(role: str) -> str | None:
        entries = by_role.get(role, [])
        return local_ids[entries[0].element_id] if len(entries) == 1 else None

    def indices(unit: str) -> list[int]:
        found = set()
        for role in by_role:
            match = _UNIT_ROLE.match(role)
            if match and match["unit"] == unit:
                found.add(int(match["index"]))
        return sorted(found)

    def text_unit(key: str) -> CardSlot:
        texts = sorted(by_role[key], key=lambda text: (reading or {}).get(text.element_id, (0, 0)))
        # Una unidad cuyas cajas forman una rejilla (2+ columnas de 2+ cajas: rótulo y texto
        # repetidos lado a lado) se lee columna por columna, no intercalando filas.
        # Un rótulo arriba que abarca varias de esas columnas va primero.
        if boxes and len(texts) >= 4:
            ids = [text.element_id for text in texts]
            first = boxes[ids[0]]

            def spans(column) -> bool:
                return any(first.x < boxes[e].x + boxes[e].w - 1 and first.x + first.w > boxes[e].x + 1 for e in column)

            for head in (1, 0):
                rest = ids[head:]
                columns = _column_groups({element_id: boxes[element_id] for element_id in rest})
                if head and sum(spans(column) for column in columns) < 2:
                    continue
                if len(columns) >= 2 and all(len(column) >= 2 for column in columns):
                    order = ids[:head] + [element_id for column in columns for element_id in column]
                    position = {element_id: k for k, element_id in enumerate(order)}
                    texts = sorted(texts, key=lambda text: position[text.element_id])
                    break
        return CardSlot(
            text=local_ids[texts[0].element_id],
            extra_texts=[local_ids[text.element_id] for text in texts[1:]],
            roles=[role for text in texts for role in text.paragraph_roles],
            icon=optional(f"{key}:icon"),
            photo=optional(f"{key}:photo"),
            image=optional(f"{key}:image"),
        )

    # Las variantes de la familia (columnas, estilo de card, relleno) solo aplican a su
    # propia composición: si el plan eligió otro layout, no se arrastran.
    composition = knowledge.composition(slide.family, slide.archetype)
    variants = {}
    if composition.get("layout") == slots.layout:
        variants = {key: composition[key] for key in ("columns", "card_style", "fill", "focus", "min_fill") if key in composition}
    elif slots.layout == "free":
        # El relleno es de la familia, no de la geometría: una plantilla para completar en libre
        # sigue llevando sus renglones (Taller 2: «las van a imprimir», 2026-10-28).
        variants = {key: composition[key] for key in ("fill", "min_fill") if key in composition}
    named: dict[str, list[str]] = {}
    for role in slots.multi - {"note", "body"}:
        values = ordered(role)
        if role == "banner":
            values = values[1:]   # la primera caja es `banner`; el resto la acompaña
        if values:
            named[role] = values
    for role in set(slots.singular) - {"kicker", "title", "subtitle", "banner"}:
        if optional(role):
            named[role] = [optional(role)]
    banner = ordered("banner")
    common = {
        "slide": _source_index(slide.source_slide_id),
        "archetype": slide.archetype or slide.family,
        "family": slide.family,
        "layout": slots.layout,
        "variant": slide.archetype,
        "kicker": optional("kicker"),
        "title": optional("title"),
        "subtitle": optional("subtitle"),
        "banner": banner[0] if banner else None,
        "notes": ordered("note"),
        "body": ordered("body"),
        "body_roles": {local_ids[item.element_id]: list(item.paragraph_roles)
                       for item in by_role.get("body", []) if item.paragraph_roles},
        "images": [local_ids[by_role[f"image:{index}"][0].element_id] for index in indices("image")],
        "named": named,
        "groups": [text_unit(f"{slots.group}:{index}") for index in indices(slots.group)] if slots.group else [],
        "decorative": [
            local_ids[assignment.element_id] for assignment in assignments
            if assignment.classification == "decorative"
        ],
        "brand": [
            local_ids[assignment.element_id] for assignment in assignments
            if assignment.classification == "brand"
        ],
        **variants,
        "font_floor": font_floor(slide, knowledge),
        "style_overrides": list(slide.style_overrides),
        "free_layout": slide.free_layout,
        "borrowed": borrowed,
    }
    if slots.unit == "metric":
        metrics = []
        for index in indices("metric"):
            value = optional(f"metric:{index}:value")
            if value:
                metrics.append(MetricSlot(
                    value=value, label=optional(f"metric:{index}:label"),
                    description=optional(f"metric:{index}:description"),
                ))
        return SlideClassification(**common, metrics=metrics)
    cards = [text_unit(f"{slots.unit}:{index}") for index in indices(slots.unit)] if slots.unit else []
    if slots.layout == "free":
        # Los bloques compuestos traen su propia unidad; las cifras, sus partes.
        units = {unit: [text_unit(f"{unit}:{index}") for index in indices(unit) if by_role.get(f"{unit}:{index}")]
                 for unit in FREE_COMPOSITE_UNITS}
        common["free_units"] = {unit: found for unit, found in units.items() if found}
        # Un bloque que es solo imagen (sin texto) es una imagen más del mensaje.
        common["images"] += [optional(f"block:{index}:image") for index in indices("block")
                             if not by_role.get(f"block:{index}") and optional(f"block:{index}:image")]
        common["metrics"] = [
            MetricSlot(value=optional(f"metric:{index}:value"), label=optional(f"metric:{index}:label"),
                       description=optional(f"metric:{index}:description"))
            for index in indices("metric") if optional(f"metric:{index}:value")
        ]
    return SlideClassification(**common, cards=cards)


def font_floor(slide: SlidePlan, knowledge: Knowledge) -> float | None:
    """Piso de letra que pidió la persona: el de su excepción o el tamaño más chico que pidió."""
    floors = [item.min_pt for item in slide.rule_exceptions if item.rule == "min_font_size"]
    floors += [item.size_pt for item in slide.style_overrides
               if item.size_pt is not None and item.size_pt < knowledge.min_size]
    return min(floors) if floors else None


def overflow_issues(plan: AnalysisPlan, report: dict, knowledge: Knowledge | None = None) -> list[PlanValidationIssue]:
    """Hallazgos de un render bloqueado: por qué no cupo y, si se puede, cómo partirlo.

    El desborde solo se conoce al componer con las métricas reales; el plan era válido.
    Se devuelve como error de la slide con la propuesta de partición ya calculada
    (`split_suggested`, condición `overflow_after_growth`), nunca aplicada por el motor.
    """
    knowledge = knowledge or Knowledge()
    by_index = {_source_index(slide.source_slide_id): slide for slide in plan.slides}
    issues: list[PlanValidationIssue] = []
    for slide_report in report.get("slides", []):
        slide = by_index.get(slide_report["slide"])
        if slide is None or not slide.selected_for_redesign or slide_report["mode"] == "redesign" \
                or (slide.keep_layout and slide_report["mode"] == "brand_shell"):
            continue
        issues.append(PlanValidationIssue(
            source_slide_id=slide.source_slide_id,
            code="composition_overflow",
            detail=slide_report.get("reason") or "La composición no cabe en la zona segura.",
        ))
        layout = effective_layout(slide, knowledge)
        capacity = knowledge.capacity(layout) if layout else None
        if slide.split_parts or capacity is None or not knowledge.splittable(slide.family):
            continue
        units = units_of(slide.assignments, capacity.unit)
        parts, reason = propose_parts(units, capacity, overflowed=True)
        if parts:
            issues.append(PlanValidationIssue(
                source_slide_id=slide.source_slide_id,
                code="split_suggested",
                severity="warning",
                detail=(
                    f"{len(units)} {capacity.unit}(s) no caben a tamaño mínimo ({reason}). "
                    f"Propuesta sin resumir: {' | '.join(', '.join(part) for part in parts)}."
                ),
            ))
    return issues
