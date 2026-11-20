"""Carga del conocimiento de diseño curado (design_knowledge/)."""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE_DIR = ROOT / "design_knowledge"


@dataclass(frozen=True)
class Style:
    font: str
    size: float
    color: str
    bold: bool = False
    italic: bool = False
    line: float = 1.0
    min: float | None = None
    emphasis: "Style | None" = None

    def resized(self, size: float) -> "Style":
        emph = self.emphasis.resized(size) if self.emphasis else None
        return Style(self.font, size, self.color, self.bold, self.italic, self.line, self.min, emph)


@dataclass(frozen=True)
class Capacity:
    """Unidades repetidas que admite una composición (tarjetas, métricas, pasos…)."""

    unit: str
    minimum: int
    maximum: int

    def fits(self, count: int) -> bool:
        return self.minimum <= count <= self.maximum


@dataclass
class Knowledge:
    root: Path = ROOT
    tokens: dict = field(init=False)
    layouts: dict = field(init=False)

    def __post_init__(self):
        kdir = self.root / "design_knowledge"
        self.tokens = yaml.safe_load((kdir / "tokens.yaml").read_text())
        self.layouts = {
            p.stem: yaml.safe_load(p.read_text()) for p in sorted((kdir / "layouts").glob("*.yaml"))
        }

    def color(self, name: str | None) -> str | None:
        return None if name is None else self.tokens["colors"].get(name, name).upper()

    def shadow(self, name: str | None) -> dict | None:
        """Sombra resuelta de `shadows` con su color como hex; None si el componente no lleva."""
        if not name:
            return None
        spec = dict(self.tokens["shadows"][name])
        spec["color"] = self.color(spec["color"])
        return spec

    def path(self, rel: str) -> str:
        return str(self.root / rel)

    def _style(self, d: dict, base: Style | None = None) -> Style:
        font = d.get("font", base.font if base else "Montserrat")
        size = float(d.get("size", base.size if base else 11))
        color = self.color(d["color"]) if "color" in d else (base.color if base else self.color("navy"))
        return Style(
            font=font, size=size, color=color,
            bold=d.get("bold", False), italic=d.get("italic", False),
            line=float(d.get("line", base.line if base else 1.0)),
            min=d.get("min"),
            emphasis=None,
        )

    def style(self, mode: str, role: str) -> Style:
        d = self.tokens["styles"][mode][role]
        st = self._style(d)
        if "emphasis" in d:
            emph = self._style(d["emphasis"], base=st)
            st = Style(st.font, st.size, st.color, st.bold, st.italic, st.line, st.min, emph)
        return st

    def component(self, name: str) -> dict:
        return self.tokens["components"][name]

    def geometry(self, layout: str) -> dict:
        return self.layouts[layout]["geometry"]

    def splittable(self, family: str) -> bool:
        """Si la familia admite repartirse en slides consecutivas.

        Lo declara `design_knowledge/visual_catalog.yaml`; las singulares (portada,
        separador, cierre) dicen `splittable: false`. Una familia que el catálogo no
        conoce se trata como singular: no se parte lo que no está descrito.
        """
        entry = self.catalog.get("families", {}).get(family)
        return bool(entry.get("splittable", True)) if entry else False

    def composition(self, family: str, variant: str | None = None) -> dict:
        """Composición de una familia (`composition` del catálogo) con su variante aplicada.

        Una variante registrada en `composition.variants` sobrescribe parámetros (columnas,
        estilo de card, relleno) o incluso el layout. Devuelve `{}` para una familia sin
        composición (p. ej. `hidden`): el plan debe nombrar `composition_layout`.
        """
        entry = self.catalog.get("families", {}).get(family) or {}
        composition = dict(entry.get("composition") or {})
        variants = composition.pop("variants", {}) or {}
        if variant and variant in variants:
            composition.update(variants[variant] or {})
        return composition

    def layout_for(self, family: str, explicit: str | None = None, variant: str | None = None) -> str | None:
        """El layout efectivo de una slide: el explícito del plan o el de su familia."""
        return explicit or self.composition(family, variant).get("layout")

    def slots(self, layout: str) -> dict:
        return dict(self.layouts[layout].get("slots", {}))

    def brand_required(self, layout: str) -> list[str]:
        """Piezas de marca obligatorias; el cierre lleva solo el lockup, sin frase de footer."""
        return list(self.layouts.get(layout, {}).get("brand_required", ["brand_logo", "brand_phrase"]))

    @cached_property
    def catalog(self) -> dict:
        path = self.root / "design_knowledge" / "visual_catalog.yaml"
        return yaml.safe_load(path.read_text()) if path.exists() else {}

    def capacity(self, layout: str) -> "Capacity | None":
        """Cuántas unidades repetidas admite una composición, leído del layout.

        La fuente es `slots.<unidad>.count` (`3` o `"2-5"`). Ninguna regla de
        partición debe llevar el número escrito en el código: una composición que
        aprende a sostener otra cantidad se actualiza aquí y todo lo demás sigue.
        """
        for slot, definition in self.layouts[layout].get("slots", {}).items():
            if not isinstance(definition, dict) or "count" not in definition:
                continue
            count = definition["count"]
            if isinstance(count, int):
                minimum = maximum = count
            else:
                first, _, last = str(count).partition("-")
                minimum, maximum = int(first), int(last or first)
            return Capacity(unit=slot.rstrip("s"), minimum=minimum, maximum=maximum)
        return None

    @cached_property
    def min_size(self) -> float:
        return float(self.tokens["typography"]["min_size"])

    @cached_property
    def citation_size(self) -> float:
        return float(self.tokens["typography"]["citation"]["size"])

    def is_citation(self, text: str) -> bool:
        """Una cita de fuente («Fuente: Mercer, 2026»): va con `styles.<modo>.citation`, exenta del
        mínimo de 11 pt (`typography.citation`)."""
        head = " ".join(text.split()).lower()
        return any(head.startswith(prefix) for prefix in self.tokens["typography"]["citation"]["prefixes"])

    def size_floor(self, text: str) -> float:
        """Letra mínima de un texto: la de cita si es una cita; si no, el mínimo de marca."""
        return min(self.min_size, self.citation_size) if self.is_citation(text) else self.min_size

    @cached_property
    def exempt_families(self) -> set[str]:
        return set(self.tokens["typography"]["exempt_families"])

    @cached_property
    def allowed_families(self) -> set[str]:
        return set(self.tokens["typography"]["allowed_families"])

    @cached_property
    def safety(self) -> float:
        return float(self.tokens["typography"]["wrap_safety"])


def nearest_color(hex_: str, allowed: list[str]) -> str:
    """Color de `allowed` más cercano a `hex_` (distancia RGB ponderada por luminancia)."""
    def rgb(value: str) -> tuple[int, int, int]:
        return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)

    r, g, b = rgb(hex_)

    def distance(candidate: str) -> float:
        cr, cg, cb = rgb(candidate)
        return 0.3 * (r - cr) ** 2 + 0.59 * (g - cg) ** 2 + 0.11 * (b - cb) ** 2

    return min(allowed, key=distance)
