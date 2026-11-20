"""Inventario inmutable y serializable de una presentación de entrada.

El parser mantiene sus IDs heredados (``t1``, ``i1`` y ``d1``) para que las
clasificaciones existentes sigan funcionando. Este módulo les antepone el ID de
slide y registra orden, relaciones y huellas; por tanto el plan nunca necesita
confiar en una posición histórica de una referencia visual.
"""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import re
from zipfile import ZipFile

from lxml import etree

from .parser import parse_deck
from .schemas import (
    DeckSpec,
    ImageBlock,
    ShapeBlock,
    SourceElement,
    SourceManifest,
    SourceRelationship,
    SourceSlideManifest,
    TextBlock,
)


PARSER_VERSION = "source-manifest-v5"   # v3: celdas de tablas nativas; v4: datos de gráficos nativos; v5: cards con sombra
_NUMBERS = re.compile(r"\d+(?:[.,]\d+)*\s?%?")
_REL_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"


def _digest(value: object) -> str:
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _box_value(block: TextBlock | ImageBlock | ShapeBlock) -> dict[str, float]:
    return block.box.model_dump()


def _relationships(path: Path, slide_index: int) -> list[SourceRelationship]:
    """Lee relaciones de la slide sin mutar el OPC ni materializar sus destinos."""
    rel_path = f"ppt/slides/_rels/slide{slide_index}.xml.rels"
    with ZipFile(path) as package:
        if rel_path not in package.namelist():
            return []
        root = etree.fromstring(package.read(rel_path))
    relations = []
    for relation in root.findall(f"{_REL_NS}Relationship"):
        kind = relation.get("Type", "").rsplit("/", 1)[-1]
        relations.append(SourceRelationship(
            id=relation.get("Id", ""),
            kind=kind,
            target=relation.get("Target", ""),
            external=relation.get("TargetMode") == "External",
        ))
    return relations


def _element(slide_index: int, block: TextBlock | ImageBlock | ShapeBlock, fallback_order: int) -> SourceElement:
    element_id = f"s{slide_index}:{block.id}"
    common = {
        "id": element_id,
        "local_id": block.id,
        "name": block.name,
        "order": block.source_order if block.source_order is not None else fallback_order,
        "source_shape_id": block.source_shape_id,
        "box": _box_value(block),
    }
    if isinstance(block, TextBlock):
        hyperlinks = [run.hyperlink for paragraph in block.paragraphs for run in paragraph.runs if run.hyperlink]
        payload = {
            **common,
            "kind": "text",
            "text": block.text,
            # Párrafos reales (no líneas): un salto suave <a:br> no abre párrafo, y los
            # roles de párrafo del plan se cuentan contra esta lista.
            "paragraphs": [paragraph.text for paragraph in block.paragraphs if paragraph.text.strip()],
            "numbers": _NUMBERS.findall(block.text),
            "hyperlinks": hyperlinks,
        }
    elif isinstance(block, ImageBlock):
        image_hash = sha256(Path(block.path).read_bytes()).hexdigest()
        payload = {**common, "kind": "image", "image_hash": image_hash, "crop": block.crop}
    else:
        payload = {**common, "kind": "shape", "shape_kind": block.kind, "fill": block.fill}
        if block.chart is not None:
            payload["chart"] = block.chart.model_dump()
    return SourceElement(**payload, fingerprint=_digest(payload))


def build_source_manifest(
    source_path: str | Path,
    *,
    deck: DeckSpec | None = None,
    media_dir: str | Path | None = None,
    slides: list[int] | None = None,
) -> SourceManifest:
    """Devuelve una foto del original; ni el PPTX ni el manifiesto se modifican.

    ``deck`` permite que el motor reutilice un parseo ya hecho. Si no se entrega,
    ``media_dir`` es obligatorio: no existe una ruta de trabajo global implícita.
    """
    path = Path(source_path)
    if deck is None:
        if media_dir is None:
            raise ValueError("media_dir es obligatorio cuando no se proporciona deck")
        deck = parse_deck(path, media_dir, slides)
    source_hash = sha256(path.read_bytes()).hexdigest()
    manifest_slides = []
    for slide in deck.slides:
        blocks = [*slide.texts, *slide.images, *slide.shapes]
        elements = sorted(
            (_element(slide.index, block, order) for order, block in enumerate(blocks, 1)),
            key=lambda element: (element.order, element.id),
        )
        relations = _relationships(path, slide.index)
        slide_payload = {
            "id": f"s{slide.index}",
            "index": slide.index,
            "visible": not slide.hidden,
            "elements": [element.model_dump() for element in elements],
            "notes": slide.notes,
            "notes_hash": sha256(slide.notes.encode("utf-8")).hexdigest(),
            "relationships": [relation.model_dump() for relation in relations],
        }
        manifest_slides.append(SourceSlideManifest(**slide_payload, fingerprint=_digest(slide_payload)))
    return SourceManifest(
        source_deck_id=f"deck-{source_hash[:16]}",
        source_hash=source_hash,
        parser_version=PARSER_VERSION,
        width=deck.width,
        height=deck.height,
        slides=manifest_slides,
    )
