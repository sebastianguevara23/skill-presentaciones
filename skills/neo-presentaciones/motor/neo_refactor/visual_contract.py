"""Contrato visual de Fase 0.

Los tres rectángulos no son intercambiables: la zona segura protege el lienzo,
la guía de composición ordena el contenido nuevo y la guía de marca reserva las
posiciones canónicas del logo y footer.  Los valores siguen teniendo una única
fuente de verdad en los YAML de conocimiento.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path

import yaml

from .knowledge import ROOT
from .schemas import Box


Rect = tuple[float, float, float, float]


@dataclass(frozen=True)
class VisualContract:
    version: str
    geometry_zone: Rect
    brand_zone: Rect
    composition_zone: Rect
    min_font_size: float


def _rect(values: list[float] | tuple[float, ...], name: str) -> Rect:
    if len(values) != 4:
        raise ValueError(f"{name} debe tener cuatro coordenadas")
    left, top, right, bottom = (float(value) for value in values)
    if right <= left or bottom <= top:
        raise ValueError(f"{name} no describe un rectángulo válido: {values}")
    return left, top, right, bottom


def load_visual_contract(root: Path = ROOT) -> VisualContract:
    """Carga los límites sin duplicar sus valores en código."""
    tokens = yaml.safe_load((root / "design_knowledge" / "tokens.yaml").read_text())
    families = yaml.safe_load((root / "design_knowledge" / "slide_families.yaml").read_text())
    audit = families["audit_contract"]
    margins = tokens["margins"]
    canvas = tokens["canvas"]
    return VisualContract(
        version=str(tokens["version"]),
        geometry_zone=_rect(audit["geometry_zone_pt"], "geometry_zone_pt"),
        brand_zone=_rect(audit["brand_zone_pt"], "brand_zone_pt"),
        composition_zone=(
            float(margins["left"]),
            0.0,
            float(canvas["width"]) - float(margins["right"]),
            float(margins["bottom_limit"]),
        ),
        min_font_size=float(tokens["typography"]["min_size"]),
    )


def _in_zone(box: Box, zone: Rect, tolerance: float = 0.01) -> bool:
    left, top, right, bottom = zone
    return (
        box.x >= left - tolerance
        and box.y >= top - tolerance
        and box.right <= right + tolerance
        and box.bottom <= bottom + tolerance
    )


def in_geometry_zone(box: Box, contract: VisualContract) -> bool:
    return _in_zone(box, contract.geometry_zone)


def in_composition_zone(box: Box, contract: VisualContract) -> bool:
    return _in_zone(box, contract.composition_zone)


def in_brand_zone(box: Box, contract: VisualContract) -> bool:
    return _in_zone(box, contract.brand_zone)


def visual_hash(root: Path = ROOT) -> str:
    """Huella reproducible de las dos fuentes del contrato visual v1."""
    digest = hashlib.sha256()
    for relative in ("design_knowledge/tokens.yaml", "design_knowledge/slide_families.yaml"):
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update((root / relative).read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()
