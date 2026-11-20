"""Paquetes acotados de manifiesto para el modelo del host.

Nunca contienen el PPTX, rutas locales, hashes de auditoría ni el manifiesto
entero. Cuando una slide es grande se parte por bloques (o por fragmentos de
texto con el mismo ID), sin eliminar caracteres ni relaciones.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Collection, Mapping

import yaml

from .knowledge import ROOT
from .schemas import SourceElement, SourceManifest, SourceSlideManifest


class ModelPackageBudgetError(ValueError):
    """Un bloque indivisible no cabe ni siquiera aislado en el presupuesto."""


def load_policy(root: str | Path = ROOT) -> dict[str, Any]:
    return yaml.safe_load((Path(root) / "config" / "llmops.yaml").read_text())


def _bytes(value: object) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _text_chunks(text: str, maximum_bytes: int) -> list[str]:
    """Corta por bytes UTF-8, preservando cada carácter y su orden."""
    chunks, current, size = [], [], 0
    for character in text:
        character_size = len(character.encode("utf-8"))
        if current and size + character_size > maximum_bytes:
            chunks.append("".join(current))
            current, size = [], 0
        if character_size > maximum_bytes:
            raise ModelPackageBudgetError("un carácter excede el presupuesto de bloque")
        current.append(character)
        size += character_size
    if current:
        chunks.append("".join(current))
    return chunks or [""]


def _base(element: SourceElement) -> dict[str, Any]:
    return {
        "id": element.id,
        "kind": element.kind,
        "order": element.order,
        "box": element.box.model_dump(),
    }


def _element_blocks(element: SourceElement, text_budget: int) -> list[dict[str, Any]]:
    base = _base(element)
    if element.kind == "text":
        chunks = _text_chunks(element.text or "", text_budget)
        return [{
            **base,
            "text": chunk,
            "fragment": {"index": index, "total": len(chunks)},
            # Se repiten por fragmento para no dejar un enlace fuera del lote
            # que contiene su texto; son metadatos, no una copia del PPTX.
            "hyperlinks": element.hyperlinks,
            "numbers": element.numbers,
            # Cuántos roles de párrafo espera el plan si el bloque va a una unidad.
            "paragraph_count": len(element.paragraphs),
        } for index, chunk in enumerate(chunks, 1)]
    if element.kind == "image":
        prefix = "brand" if element.name.startswith("NEO_BRAND") else "image"
        return [{**base, "asset_ref": f"{prefix}:{element.image_hash}"}]
    if element.chart is not None:
        # Gráfico nativo: es contenido (nunca decorative) y sigue nativo; el modelo ve sus datos.
        return [{**base, "kind": "chart", "chart": element.chart.model_dump(exclude_none=True)}]
    return [{**base, "decorative_ref": "shape"}]


def _notes_blocks(slide: SourceSlideManifest, text_budget: int) -> list[dict[str, Any]]:
    if not slide.notes:
        return []
    chunks = _text_chunks(slide.notes, text_budget)
    return [{
        "id": f"{slide.id}:notes", "kind": "notes", "order": 10_000 + index,
        "text": chunk, "fragment": {"index": index, "total": len(chunks)},
    } for index, chunk in enumerate(chunks, 1)]


def _slide_segments(slide: SourceSlideManifest, budget: int) -> list[dict[str, Any]]:
    # Reservar holgura para IDs, cajas y el sobre del paquete; cada bloque podrá
    # entrar aislado aun si el texto usa caracteres multibyte.
    text_budget = max(1, budget // 4)
    blocks = [
        block
        for element in slide.elements
        for block in _element_blocks(element, text_budget)
    ] + _notes_blocks(slide, text_budget)
    relations = [relationship.model_dump() for relationship in slide.relationships if relationship.external]
    segments: list[list[dict[str, Any]]] = [[]]
    for block in blocks:
        candidate = {
            "slide_id": slide.id,
            "visible": slide.visible,
            "relationships": relations,
            "blocks": [*segments[-1], block],
        }
        if segments[-1] and _bytes(candidate) > budget // 2:
            segments.append([block])
        else:
            segments[-1].append(block)
    out = []
    for index, segment_blocks in enumerate(segments, 1):
        segment = {
            "slide_id": slide.id,
            "visible": slide.visible,
            "segment": index,
            "segments_total": len(segments),
            "relationships": relations,
            "blocks": segment_blocks,
        }
        if _bytes(segment) > budget:
            raise ModelPackageBudgetError(f"{slide.id}: un segmento no cabe dentro de max_visible_bytes_per_tool")
        out.append(segment)
    return out


def _package(
    package_id: str, manifest: SourceManifest, design_version: str, segments: list[dict[str, Any]]
) -> dict[str, Any]:
    assets = sorted({
        block["asset_ref"]
        for segment in segments
        for block in segment["blocks"]
        if "asset_ref" in block
    })
    payload: dict[str, Any] = {
        "package_id": package_id,
        "source_deck_id": manifest.source_deck_id,
        "source_hash": manifest.source_hash,
        "design_version": design_version,
        "assets": assets,
        "slides": segments,
        "visible_bytes": 0,
    }
    # El tamaño es parte del resultado visible; converger en pocos pasos evita
    # que sus propios dígitos hagan que el paquete rebase el límite.
    for _ in range(3):
        payload["visible_bytes"] = _bytes(payload)
    return payload


def build_model_packages(
    manifest: SourceManifest,
    *,
    design_version: str,
    policy: Mapping[str, Any] | None = None,
    slides: Collection[str] | None = None,
) -> list[dict[str, Any]]:
    """Divide un manifiesto por presupuesto sin truncar sus bloques de contenido.

    `slides` (ids `sN`) limita los paquetes a las slides en alcance: un pedido sobre 3
    slides de un deck de 76 no arma los 13 paquetes del deck.
    """
    policy = dict(policy or load_policy())
    budget = int(policy["model_context"]["max_visible_bytes_per_tool"])
    if budget < 1024:
        raise ModelPackageBudgetError("max_visible_bytes_per_tool debe ser al menos 1024")
    # Un paquete lleva como máximo `max_slides_per_batch` slides: es lo que el host puede leer con
    # su imagen de origen en un mismo intercambio (las previews van en la misma respuesta).
    max_slides = int(policy["model_context"].get("max_slides_per_batch", 0)) or None
    segments = [segment for slide in manifest.slides if slides is None or slide.id in slides
                for segment in _slide_segments(slide, budget)]
    packages: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    for segment in segments:
        candidate = _package(f"analysis-{len(packages) + 1}", manifest, design_version, [*current, segment])
        too_many = bool(max_slides) and len({s["slide_id"] for s in current} | {segment["slide_id"]}) > max_slides
        if current and (candidate["visible_bytes"] > budget or too_many):
            completed = _package(f"analysis-{len(packages) + 1}", manifest, design_version, current)
            packages.append(completed)
            current = [segment]
        else:
            current.append(segment)
    if current:
        packages.append(_package(f"analysis-{len(packages) + 1}", manifest, design_version, current))
    for package in packages:
        if package["visible_bytes"] > budget:
            raise ModelPackageBudgetError(f"{package['package_id']} excede el presupuesto configurado")
    return packages
