"""Trazabilidad explícita entre el manifiesto fuente y las slides de salida."""
from __future__ import annotations

from .schemas import (
    MappingValidationResult,
    PlanValidationIssue,
    SourceManifest,
    SourceOutputMapping,
    SourceOutputSlideMapping,
)


def identity_mapping(manifest: SourceManifest) -> SourceOutputMapping:
    """Mapa 1:1, útil cuando ninguna slide se parte."""
    return mapping_from_outputs(manifest, {slide.id: [slide.index] for slide in manifest.slides})


def mapping_from_outputs(
    manifest: SourceManifest,
    slide_outputs: dict[str, list[int]],
    element_outputs: dict[str, dict[str, list[int]]] | None = None,
) -> SourceOutputMapping:
    """Mapa real del render: cada slide de origen declara las salidas que produjo.

    Una partición envía cada elemento a la parte que lo muestra (`element_outputs`);
    el marco que se repite —título, notas, relaciones— apunta a todas las salidas de
    esa slide. Lo que no se declara va a todas: es el caso 1:1 y el del brand shell.
    """
    element_outputs = element_outputs or {}
    slides = []
    for slide in manifest.slides:
        outputs = slide_outputs.get(slide.id, [slide.index])
        per_element = element_outputs.get(slide.id, {})
        slides.append(SourceOutputSlideMapping(
            source_slide_id=slide.id,
            output_slide_indices=sorted(outputs),
            element_destinations={
                element.id: sorted(per_element.get(element.id, outputs)) for element in slide.elements
            },
            notes_output_indices=sorted(outputs),
            relationship_output_indices={
                relationship.id: sorted(outputs) for relationship in slide.relationships
            },
        ))
    return SourceOutputMapping(
        source_deck_id=manifest.source_deck_id,
        source_hash=manifest.source_hash,
        slides=slides,
    )


def validate_mapping(manifest: SourceManifest, mapping: SourceOutputMapping) -> MappingValidationResult:
    """Verifica destino y orden sin confundir un split legítimo con una duplicación."""
    issues: list[PlanValidationIssue] = []

    def issue(slide_id: str, code: str, detail: str) -> None:
        issues.append(PlanValidationIssue(source_slide_id=slide_id, code=code, detail=detail))

    if mapping.source_deck_id != manifest.source_deck_id or mapping.source_hash != manifest.source_hash:
        for source_slide in manifest.slides:
            issue(source_slide.id, "stale_source_mapping", "El mapa no pertenece al manifiesto de origen actual.")
    source_by_id = {slide.id: slide for slide in manifest.slides}
    mapped_ids = [entry.source_slide_id for entry in mapping.slides]
    for source_slide in manifest.slides:
        if source_slide.id not in mapped_ids:
            issue(source_slide.id, "unmapped_slide", "La slide de origen no tiene salida asociada.")
    for source_slide_id in sorted({value for value in mapped_ids if mapped_ids.count(value) > 1}):
        issue(source_slide_id, "duplicate_source_slide_mapping", "La slide de origen tiene más de una entrada de mapa.")

    previous_output = 0
    for entry in mapping.slides:
        source_slide = source_by_id.get(entry.source_slide_id)
        if source_slide is None:
            issue(entry.source_slide_id, "unknown_source_slide_mapping", "El mapa referencia una slide inexistente.")
            continue
        if entry.output_slide_indices != sorted(set(entry.output_slide_indices)):
            issue(source_slide.id, "invalid_output_order", "Los destinos de la slide deben ser únicos y crecientes.")
        if entry.output_slide_indices[0] <= previous_output:
            issue(source_slide.id, "source_order_changed", "La secuencia de slides de origen no puede invertirse en salida.")
        previous_output = max(previous_output, *entry.output_slide_indices)
        expected_elements = {element.id for element in source_slide.elements}
        for element_id in sorted(expected_elements - set(entry.element_destinations)):
            issue(source_slide.id, "unmapped_element", f"El elemento {element_id} no tiene destino de salida.")
        for element_id, outputs in entry.element_destinations.items():
            if element_id not in expected_elements:
                issue(source_slide.id, "unknown_source_element_mapping", f"El elemento {element_id} no existe en la slide.")
            elif not outputs or outputs != sorted(set(outputs)):
                issue(source_slide.id, "invalid_element_destinations", f"El elemento {element_id} tiene destinos inválidos.")
        if not entry.notes_output_indices:
            issue(source_slide.id, "unmapped_notes", "Las notas deben conservar un destino, incluso si están vacías.")
        expected_relationships = {relationship.id for relationship in source_slide.relationships}
        for relationship_id in sorted(expected_relationships - set(entry.relationship_output_indices)):
            issue(source_slide.id, "unmapped_relationship", f"La relación {relationship_id} no tiene destino de salida.")
    return MappingValidationResult(issues=issues)
