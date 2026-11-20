"""Partición de una slide por desborde, gobernada por condiciones y no por decks.

La política está escrita en `plans/convenciones.md` (2026-09-17): primero se crece
dentro de la zona segura; si el contenido sigue sin caber, la slide se parte en
slides consecutivas **sin resumir ni reescribir**. Lo que aquí se implementa es esa
regla en abstracto:

- la **unidad** repetida (tarjeta, métrica, paso…) se deduce del rol del plan
  (`card:2`, `metric:3:label`), no del nombre del deck;
- la **capacidad** sale del layout (`slots.<unidad>.count` en
  `design_knowledge/layouts/`), no de un número escrito en el código;
- la **condición** de partir es objetiva: hay más unidades de las que la
  composición sostiene, o el compositor reportó desborde con el mínimo tipográfico.

Las familias singulares (portada, título, separador, cierre) no se parten: no
tienen unidades repetidas, y eso se declara en `design_knowledge/visual_catalog.yaml`.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

from .knowledge import Capacity

UNIT_ROLE = re.compile(r"^(?P<unit>[a-z_]+):(?P<index>\d+)(?::.+)?$")
SplitReason = str


@dataclass(frozen=True)
class SlideUnits:
    """Unidades repetidas de una slide y los elementos que llenan cada una."""

    unit: str
    keys: list[str]                       # "card:1", "card:2"… en orden de origen
    elements: dict[str, list[str]]        # clave de unidad → ids de elemento
    shared: list[str]                     # título, kicker, banner, notas: van en cada parte

    def __len__(self) -> int:
        return len(self.keys)


def unit_key(role: str | None) -> str | None:
    """`card:2:icon` → `card:2`; un rol compartido (title, banner…) devuelve None."""
    match = UNIT_ROLE.match(role or "")
    return f"{match['unit']}:{match['index']}" if match else None


def units_of(assignments, unit: str | None = None) -> SlideUnits:
    """Agrupa las asignaciones de contenido por unidad, conservando el orden del plan.

    `unit` fija cuál es la unidad repetida (la del layout); otros grupos numerados, como
    los paneles `aside:N`, cuentan como compartidos y no se reparten.
    """
    keys: list[str] = []
    elements: dict[str, list[str]] = {}
    shared: list[str] = []
    unit_name = unit or ""
    for assignment in assignments:
        if assignment.classification != "content":
            continue
        key = unit_key(assignment.role)
        if key is not None and unit and key.split(":")[0] != unit:
            key = None
        if key is None:
            shared.append(assignment.element_id)
            continue
        unit_name = unit_name or key.split(":")[0]
        if key not in elements:
            keys.append(key)
            elements[key] = []
        elements[key].append(assignment.element_id)
    keys.sort(key=lambda key: int(key.split(":")[1]))
    return SlideUnits(unit=unit_name, keys=keys, elements=elements, shared=shared)


def balanced_parts(keys: list[str], capacity: Capacity) -> list[list[str]]:
    """Reparte las unidades en el menor número de partes, lo más parejas posible.

    Parejas y no «llenar y dejar el resto»: cuatro tarjetas con capacidad tres dan
    2+2, que es la composición registrada en la bitácora, y no 3+1, que deja una
    slide coja. El orden de origen nunca se altera.
    """
    if not keys:
        return []
    parts_count = -(-len(keys) // capacity.maximum)  # techo de la división
    if parts_count <= 1:
        return [list(keys)]
    base, extra = divmod(len(keys), parts_count)
    if base < capacity.minimum:
        # Con partes parejas alguna quedaría por debajo del mínimo: se usan menos
        # partes, llenas hasta el máximo, antes que emitir una composición inválida.
        parts_count = len(keys) // capacity.minimum
        base, extra = divmod(len(keys), parts_count)
    parts: list[list[str]] = []
    cursor = 0
    for index in range(parts_count):
        size = base + (1 if index < extra else 0)
        parts.append(list(keys[cursor:cursor + size]))
        cursor += size
    return parts


def needs_split(unit_count: int, capacity: Capacity | None, *, overflowed: bool = False) -> SplitReason | None:
    """Condición objetiva de partición; devuelve la razón o None si la slide cabe."""
    if capacity is None:
        return None
    if unit_count > capacity.maximum:
        return "unit_capacity"
    if overflowed and unit_count > capacity.minimum:
        return "overflow_after_growth"
    return None


def propose_parts(
    units: SlideUnits, capacity: Capacity | None, *, overflowed: bool = False
) -> tuple[list[list[str]], SplitReason | None]:
    """Propuesta determinista: partes de unidades o nada cuando la slide cabe."""
    reason = needs_split(len(units), capacity, overflowed=overflowed)
    if reason is None or capacity is None:
        return [], None
    if reason == "overflow_after_growth":
        # Desbordó con el mínimo tipográfico: se busca la parte más holgada posible
        # respetando el mínimo de la composición, sin bajar de él.
        capacity = Capacity(unit=capacity.unit, minimum=capacity.minimum, maximum=max(capacity.minimum, len(units) - 1))
    return balanced_parts(units.keys, capacity), reason


def renumber(assignments, part_keys: list[str], unit: str | None = None):
    """Renumera los roles de una parte a 1..n para que la composición los reconozca.

    `card:3` en la segunda parte pasa a `card:1`. Los roles compartidos no cambian:
    el título, el kicker o el banner se repiten en cada parte porque son el marco de
    la slide, no contenido que se pueda dejar fuera.
    """
    position = {key: index + 1 for index, key in enumerate(part_keys)}
    selected = set(part_keys)
    result = []
    for assignment in assignments:
        if assignment.classification != "content":
            result.append(assignment)
            continue
        key = unit_key(assignment.role)
        if key is None or (unit and key.split(":")[0] != unit):
            result.append(assignment)
            continue
        if key not in selected:
            continue
        unit_name, index = key.split(":")
        suffix = (assignment.role or "")[len(key):]
        result.append(assignment.model_copy(update={"role": f"{unit_name}:{position[key]}{suffix}"}))
    return result
