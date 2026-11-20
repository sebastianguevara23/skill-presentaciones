"""Interfaz común de los auditores de la Fase 3.

Cada auditor es una función `audit(ctx) -> AuditResult`: el contexto reúne el
manifiesto de origen, el PPTX de salida (sus bytes, abiertos de nuevo), el mapa
origen→salida y la versión visual. Ningún auditor lee el reporte del render para
decidir: lo que no está en el PPTX no existe.

Estados: `pass`, `warning` (no bloquea, queda en el reporte), `fail` y `not_run`
(el control no se pudo ejecutar; bloquea igual que un fallo).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property
from hashlib import sha256
from pathlib import Path
from typing import Literal

from pptx import Presentation
from pydantic import BaseModel, Field

from ..knowledge import ROOT, Knowledge
from ..parser import parse_deck
from ..schemas import DeckSpec, PlanRevision, SourceManifest, SourceOutputMapping, SlidePlan
from ..slide_marker import read_marker
from ..visual_contract import VisualContract, load_visual_contract

RULES_VERSION = "phase3-audit-v1"
Status = Literal["pass", "warning", "fail", "not_run"]
_RANK = {"pass": 0, "warning": 1, "not_run": 2, "fail": 3}


def worst(statuses) -> Status:
    """El peor estado manda; sin estados es `pass` (nada que objetar)."""
    return max(statuses, key=_RANK.__getitem__, default="pass")


def blocking(status: Status) -> bool:
    return status in ("fail", "not_run")


class Finding(BaseModel):
    """Un hallazgo anclado a una slide concreta, con causa, corrección y aceptación."""

    check: str
    subcheck: str
    code: str
    status: Literal["warning", "fail", "not_run"]
    slide_id: int | None = None          # índice 1-based en el PPTX de salida
    source_slide_id: str | None = None   # `s5` del manifiesto de origen
    family: str | None = None
    source_reference: str | None = None  # shape, elemento del manifiesto o compromiso
    symptom: str
    measurement: dict = Field(default_factory=dict)
    cause: str
    correction_proposed: str | None = None
    correction_applied: str | None = None
    acceptance: str
    exception: dict | None = None        # excepción aprobada que convirtió el fallo en aviso
    rule_version: str = RULES_VERSION


class AuditResult(BaseModel):
    auditor: str
    rule_version: str = RULES_VERSION
    status: Status = "pass"
    subchecks: dict[str, Status] = Field(default_factory=dict)
    slides: dict[int, Status] = Field(default_factory=dict)
    findings: list[Finding] = Field(default_factory=list)
    exceptions_applied: list[dict] = Field(default_factory=list)
    # Registros propios del auditor (p. ej. un estado por compromiso del plan).
    records: list[dict] = Field(default_factory=list)
    detail: str | None = None

    def demote_preexisting(self, untouched) -> "AuditResult":
        """Trabajo parcial: lo que falla en una slide intacta ya venía así; se avisa, no bloquea."""
        touched = {f.subcheck for f in self.findings if f.slide_id in untouched and f.status != "warning" and f.subcheck != "bookends"}
        for finding in self.findings:
            if finding.slide_id in untouched and finding.status != "warning" and finding.subcheck != "bookends":
                finding.status = "warning"
                finding.cause = f"preexistente, slide no tocada: {finding.cause}"
        for slide_id in untouched & set(self.slides):
            self.slides[slide_id] = worst(f.status for f in self.findings if f.slide_id == slide_id)
        for name in touched & set(self.subchecks):
            self.subchecks[name] = worst(f.status for f in self.findings if f.subcheck == name)
        if touched and not self.detail:
            self.status = worst([*self.subchecks.values(), *(f.status for f in self.findings)])
        return self

    def finish(self, slide_ids, subchecks) -> "AuditResult":
        """Calcula el estado por slide, por subcheck y global a partir de los hallazgos."""
        for slide_id in slide_ids:
            self.slides[slide_id] = worst(f.status for f in self.findings if f.slide_id == slide_id)
        for name in subchecks:
            self.subchecks.setdefault(name, worst(f.status for f in self.findings if f.subcheck == name))
        self.status = worst([*self.subchecks.values(), *(f.status for f in self.findings)])
        return self


class ApprovedException(BaseModel):
    """Excepción autorizada: elemento, condición y referencia aprobada. Nunca ad hoc."""

    slide_id: int
    code: str
    element: str | None = None  # nombre del shape; None = toda la slide para ese código
    condition: str = Field(min_length=1)
    reference: str = Field(min_length=1)

    def covers(self, finding: Finding) -> bool:
        return (
            finding.slide_id == self.slide_id and finding.code == self.code
            and (self.element is None or finding.source_reference == self.element)
        )


class VisualReview(BaseModel):
    """Revisión del modelo del host sobre la preview de una slide de salida.

    `preview_key` ata la revisión a lo que pinta esa slide (`AuditContext.slide_digests`):
    si la slide cambia, la revisión deja de valer; si cambia otra o se mueve de posición, sigue
    valiendo. `slide_id` es la posición en el momento de revisar y no decide la validez. `individual` indica que se abrió la preview a tamaño completo.
    """

    slide_id: int
    preview_key: str
    status: Literal["pass", "fail"]
    legible: bool = True
    individual: bool = False
    codes: list[str] = Field(default_factory=list)
    notes: str = Field(default="", max_length=1000)
    # Compromisos cualitativos del plan que esta revisión comprobó: id → pass/fail.
    commitments: dict[str, Literal["pass", "fail"]] = Field(default_factory=dict)


@dataclass
class OutputSlide:
    index: int
    hidden: bool
    marker: dict | None
    source_slide_id: str | None
    family: str

    @property
    def mode(self) -> str:
        if self.marker:
            return self.marker.get("mode", "unknown")
        return "hidden" if self.hidden else "preserved"

    @property
    def redesigned(self) -> bool:
        return self.mode == "redesign"

    @property
    def layout(self) -> str | None:
        return (self.marker or {}).get("layout")


@dataclass
class AuditContext:
    source: SourceManifest
    output_path: Path
    mapping: SourceOutputMapping
    design_version: str
    workspace: Path
    plan: PlanRevision | None = None
    exceptions: list[ApprovedException] = field(default_factory=list)
    reviews: list[VisualReview] = field(default_factory=list)
    knowledge_root: Path = ROOT
    # PPTX de origen: solo para comparar imágenes a la vista (se verifica su hash).
    source_path: Path | None = None
    # Resultado de `optimization_audit` calculado al guardar el candidato (ver engine).
    optimization: dict | None = None
    # Slides de salida que el motor dejó intactas (trabajo parcial): no se revisan ni
    # bloquean; sus hallazgos previos se reportan como preexistentes. Vacío = deck completo.
    untouched: frozenset[int] = frozenset()

    @cached_property
    def output_sha(self) -> str:
        return sha256(self.output_path.read_bytes()).hexdigest()

    @cached_property
    def slide_digests(self) -> dict[int, str]:
        """Huella de lo que pinta cada slide (índice 1-based → sha256).

        Reúne el XML de la slide y los bytes de sus partes relacionadas (imágenes, medios,
        layout y master). Se excluyen las notas y las demás slides: cambiar otra slide, o el
        orden de las relaciones, no cambia esta huella. Tampoco entra la posición, salvo que la
        slide dibuje su número. Es la base de `preview_key`: la revisión visual de una slide
        intacta sigue valiendo aunque el deck cambie o una partición desplace los índices.
        """
        digests: dict[int, str] = {}
        for index, slide in enumerate(self.presentation.slides, start=1):
            blob = slide.part.blob
            digest = sha256(blob)
            if b'type="slidenum"' in blob:
                # El número de slide se dibuja según la posición: ahí el índice sí es contenido.
                digest.update(f"pos:{index}".encode())
            for rel in sorted((r for r in slide.part.rels.values() if not r.is_external),
                              key=lambda r: str(r.target_part.partname)):
                if rel.reltype.endswith(("/notesSlide", "/slide")):
                    continue
                digest.update(str(rel.target_part.partname).encode())
                digest.update(rel.target_part.blob)
            digests[index] = digest.hexdigest()
        return digests

    @cached_property
    def kn(self) -> Knowledge:
        return Knowledge(self.knowledge_root)

    @cached_property
    def contract(self) -> VisualContract:
        return load_visual_contract(self.knowledge_root)

    @cached_property
    def presentation(self):
        return Presentation(str(self.output_path))

    @cached_property
    def deck(self) -> DeckSpec:
        media = self.workspace / "audit-media" / self.output_sha[:16]
        media.mkdir(parents=True, exist_ok=True)
        return parse_deck(self.output_path, media)

    @cached_property
    def plan_slides(self) -> dict[str, SlidePlan]:
        return {slide.source_slide_id: slide for slide in self.plan.plan.slides} if self.plan else {}

    @cached_property
    def source_of(self) -> dict[int, str]:
        owner: dict[int, str] = {}
        for entry in self.mapping.slides:
            for index in entry.output_slide_indices:
                owner[index] = entry.source_slide_id
        return owner

    @cached_property
    def slides(self) -> list[OutputSlide]:
        result = []
        for index, slide in enumerate(self.presentation.slides, 1):
            marker = read_marker(slide)
            source_id = self.source_of.get(index)
            family = (marker or {}).get("family")
            if family is None and source_id in self.plan_slides:
                family = self.plan_slides[source_id].family
            result.append(OutputSlide(
                index=index, hidden=slide._element.get("show") == "0", marker=marker,
                source_slide_id=source_id, family=family or "unregistered",
            ))
        return result

    def in_scope(self, index: int) -> bool:
        return index not in self.untouched

    def slide(self, index: int) -> OutputSlide:
        return self.slides[index - 1]

    def apply_exceptions(self, result: AuditResult) -> AuditResult:
        """Una excepción aprobada convierte el fallo en aviso y queda registrada."""
        for finding in result.findings:
            if finding.status != "fail":
                continue
            for exception in self.exceptions:
                if exception.covers(finding):
                    finding.status = "warning"
                    finding.exception = exception.model_dump()
                    result.exceptions_applied.append({**exception.model_dump(), "check": finding.check})
                    break
        return result


def not_run(auditor: str, reason: str, slide_ids=(), subchecks=()) -> AuditResult:
    """Resultado explícito de un control que no pudo ejecutarse: bloquea, nunca se omite."""
    result = AuditResult(auditor=auditor, status="not_run", detail=reason)
    for name in subchecks:
        result.subchecks[name] = "not_run"
    for slide_id in slide_ids:
        result.slides[slide_id] = "not_run"
    return result
