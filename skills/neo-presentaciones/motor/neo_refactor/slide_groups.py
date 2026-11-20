"""Familias internas del deck: slides que comparten estructura y deben cambiar juntas.

El catálogo (`design_knowledge/visual_catalog.yaml`) dice qué familias del sistema NEO
existen. Esto es otra cosa y complementaria: durante el análisis del deck de entrada se
agrupan **sus propias** slides por estructura —los seis separadores, las cuatro slides de
tarjetas, las tres de equipo— para que una decisión de estilo se aplique al grupo entero.
Sin esto, el rediseño se decide slide por slide y basta olvidar una para dejarla huérfana
con el estilo viejo en medio del deck.

La firma ignora el contenido a propósito: dos slides de tarjetas son la misma estructura
aunque digan cosas distintas. Lo que se compara es qué bloques hay y dónde caen sobre una
rejilla tolerante, de modo que un par de puntos de diferencia no rompa el grupo.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field

from .schemas import SourceManifest, SourceSlideManifest

COLUMNS = 12          # rejilla de tolerancia: un bloque movido unos puntos cae en la misma celda
ROWS = 8
MERGE_SIMILARITY = 0.8  # dos estructuras que comparten el 80 % de sus bloques son el mismo grupo


@dataclass(frozen=True)
class SlideSignature:
    """Qué bloques tiene la slide y dónde caen, sin mirar lo que dicen."""

    slots: tuple[tuple[str, int, int, int, int], ...]

    @property
    def counts(self) -> dict[str, int]:
        return dict(Counter(slot[0] for slot in self.slots))

    def similarity(self, other: "SlideSignature") -> float:
        """Jaccard sobre los bloques: tolera un decorativo de más sin fundir cosas distintas."""
        mine, theirs = Counter(self.slots), Counter(other.slots)
        shared = sum((mine & theirs).values())
        total = sum((mine | theirs).values())
        return shared / total if total else 1.0


@dataclass
class SlideGroup:
    """Un grupo del deck: sus slides, su estructura y por qué están juntas."""

    id: str
    source_slide_ids: list[str] = field(default_factory=list)
    signature: SlideSignature | None = None
    evidence: list[str] = field(default_factory=list)

    def view(self) -> dict:
        return {
            "id": self.id,
            "slides": list(self.source_slide_ids),
            "size": len(self.source_slide_ids),
            "structure": self.signature.counts if self.signature else {},
            "evidence": list(self.evidence),
        }


def signature_of(slide: SourceSlideManifest, width: float, height: float) -> SlideSignature:
    """Firma estructural: tipo de bloque y su celda de rejilla, ordenados."""
    slots = []
    for element in slide.elements:
        box = element.box
        slots.append((
            element.kind,
            _cell(box.x, width, COLUMNS),
            _cell(box.y, height, ROWS),
            max(1, _cell(box.w, width, COLUMNS)),
            max(1, _cell(box.h, height, ROWS)),
        ))
    return SlideSignature(slots=tuple(sorted(slots)))


def _cell(value: float, total: float, divisions: int) -> int:
    if total <= 0:
        return 0
    return max(0, min(divisions, int(round(value / total * divisions))))


def group_slides(manifest: SourceManifest) -> list[SlideGroup]:
    """Agrupa las slides visibles del deck por estructura, en orden de aparición.

    Las ocultas quedan fuera: no se rediseñan, así que arrastrarlas a un grupo solo
    invitaría a aplicarles un cambio que el contrato prohíbe.
    """
    signatures = {
        slide.id: signature_of(slide, manifest.width, manifest.height)
        for slide in manifest.slides if slide.visible
    }
    exact: dict[SlideSignature, list[str]] = defaultdict(list)
    for slide in manifest.slides:
        if slide.visible:
            exact[signatures[slide.id]].append(slide.id)

    groups: list[SlideGroup] = []
    for signature, slide_ids in exact.items():
        for group in groups:
            if group.signature and group.signature.similarity(signature) >= MERGE_SIMILARITY:
                group.source_slide_ids += slide_ids
                group.evidence.append(
                    f"estructura equivalente al {group.signature.similarity(signature):.0%} de los bloques"
                )
                break
        else:
            groups.append(SlideGroup(id="", source_slide_ids=list(slide_ids), signature=signature))

    order = {slide.id: slide.index for slide in manifest.slides}
    for group in groups:
        group.source_slide_ids.sort(key=lambda slide_id: order[slide_id])
    groups.sort(key=lambda group: order[group.source_slide_ids[0]])
    for position, group in enumerate(groups, start=1):
        group.id = f"g{position}"
        counts = group.signature.counts if group.signature else {}
        structure = ", ".join(f"{count} {kind}" for kind, count in sorted(counts.items()))
        group.evidence.insert(0, f"{len(group.source_slide_ids)} slides con {structure or 'sin bloques'}")
    return groups


def group_of(groups: list[SlideGroup], source_slide_id: str) -> SlideGroup | None:
    return next((group for group in groups if source_slide_id in group.source_slide_ids), None)
