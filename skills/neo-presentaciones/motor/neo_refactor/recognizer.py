"""Reconocimiento de familias sin depender del índice de una referencia histórica."""
from __future__ import annotations

from pathlib import Path

import yaml

from .knowledge import ROOT
from .schemas import FamilyRecognition, SourceManifest, SourceSlideManifest


def _load_patterns(root: Path) -> dict:
    return yaml.safe_load((root / "design_knowledge" / "recognition_patterns.yaml").read_text())["patterns"]


def _recognize_slide(slide: SourceSlideManifest, patterns: dict) -> FamilyRecognition:
    if not slide.visible:
        return FamilyRecognition(
            source_slide_id=slide.id, family="hidden", confidence="high",
            evidence=["source visibility=hidden"], requires_model=False,
        )
    texts = [element for element in slide.elements if element.kind == "text" and element.text]
    images = [element for element in slide.elements if element.kind == "image" and not element.name.startswith("NEO_BRAND")]
    section_match = patterns["section_divider"]["match"]
    markers = [
        element.id for element in texts
        if element.text.strip().upper() in set(section_match["exact_text"])
    ]
    if markers and len(images) <= int(section_match["max_content_images"]):
        return FamilyRecognition(
            source_slide_id=slide.id, family="section_divider", confidence="high",
            evidence=[*(f"section marker in {element_id}" for element_id in markers), "no content images"],
            # A high-confidence pattern still needs the host's visual review and
            # the phase-3 quality gates; it merely avoids asking it to guess.
            requires_model=True,
        )
    return FamilyRecognition(
        source_slide_id=slide.id, confidence="ambiguous", requires_model=True,
        evidence=["no registered deterministic pattern matched"],
    )


def recognize_families(manifest: SourceManifest, *, knowledge_root: str | Path = ROOT) -> list[FamilyRecognition]:
    """Solo emite una familia cuando un patrón versionado y estrecho la respalda."""
    # Cargar el registro es intencional: cualquier patrón nuevo debe quedar
    # versionado junto con sus tests, no implícito en una condición de Python.
    patterns = _load_patterns(Path(knowledge_root))
    if {"hidden", "section_divider"} - set(patterns):
        raise ValueError("faltan patrones de reconocimiento registrados")
    return [_recognize_slide(slide, patterns) for slide in manifest.slides]
