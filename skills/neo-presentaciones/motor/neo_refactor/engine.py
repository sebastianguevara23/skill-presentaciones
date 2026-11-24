"""Módulo profundo del rediseño: una interfaz común para CLI y MCP.

La interfaz es deliberadamente corta. El consumidor aporta el directorio de
trabajo y recibe datos o resultados; parser, medios temporales y composición se
mantienen detrás de este límite.
"""
from __future__ import annotations

import hashlib

from collections import defaultdict
from dataclasses import dataclass, field
from hashlib import sha256
import json
from pathlib import Path
import re
import shutil
import time
from uuid import uuid4

import yaml
from pptx import Presentation

from . import cobrand, integrity
from .charts import apply_brand as apply_chart_brand, charts_in, scale_text as scale_chart_text
from .cleanup import strip_slide_emojis
from .composer import KEEP_ICON_COLORS, Composer
from .knowledge import ROOT, Knowledge
from .model_packages import build_model_packages
from .optimize import classes_after, optimize, strictest
from .parser import parse_deck, summarize
from .plan_adapter import renderability_issues, to_legacy_classification
from .renderer import redraw
from .recognizer import recognize_families
from .slide_groups import SlideGroup, group_of, group_slides
from .schemas import (
    AcceptanceCriterion,
    AnalysisPlan,
    DeckClassification,
    ElementAssignment,
    PlanCommitment,
    PlanRevision,
    PlanValidationIssue,
    PlanValidationResult,
    FamilyRecognition,
    SlidePlan,
    SlideReport,
    SourceManifest,
)
from .brand_fix import apply_brand_rules, drop_embedded_brand_fonts, fix_theme_links
from .shell import apply_shell
from .slide_marker import write_marker
from .source_manifest import build_source_manifest
from .source_manifest import PARSER_VERSION
from .source_output_mapping import mapping_from_outputs, validate_mapping
from . import text_overrides as texts_ok
from .validator import validate
from .visual_contract import load_visual_contract, visual_hash


OVERFLOW_CODES = ("cards_overflow", "body_overflow", "heading_too_long")
_CONTENT_COMMAND = re.compile(
    r"\b(reescrib\w*|resum\w*|traduc\w*|elimin\w*|agreg\w*|invent\w*|modific\w*|cambi\w*)\b"
    r".*\b(texto|contenido|t[ií]tulo|cifra|palabra|copy)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class AnalysisResult:
    source: SourceManifest
    manifest: SourceManifest
    summary: dict
    # Familias internas del deck: slides con la misma estructura, para que un cambio
    # de estilo se decida por grupo y no deje una slide huérfana con el estilo viejo.
    groups: list[SlideGroup] = field(default_factory=list)


class PlanRedesignBlocked(RuntimeError):
    """El candidato queda privado; la ruta solicitada no recibe un PPTX descargable."""

    def __init__(self, report: dict):
        self.report = report
        super().__init__("el plan no se pudo cumplir sin degradar una slide seleccionada a brand_shell")


def _mapping_from_render(source_manifest, plan, rendered) -> "SourceOutputMapping":
    """Traza el mapa con las slides que el render produjo, no con una identidad supuesta.

    Insertar una parte corre los índices de todo lo que va detrás; el mapa lo refleja y
    `validate_mapping` comprueba que cada elemento, nota y relación tiene destino, que
    ninguna slide de origen se duplica y que el orden no se invierte.
    """
    slide_outputs = {}
    element_outputs: dict[str, dict[str, list[int]]] = {}
    for slide in source_manifest.slides:
        report = plan[slide.index]
        slide_outputs[slide.id] = report.output_slides or [slide.index]
        if report.mode != "redesign" or report.parts < 2:
            continue
        by_local = {element.local_id: element.id for element in slide.elements}
        destinations: dict[str, list[int]] = {}
        for output_index, (entry, _rendered) in zip(report.output_slides, rendered[slide.index]):
            for local_id in entry.assigned_ids():
                element_id = by_local.get(local_id)
                if element_id:
                    destinations.setdefault(element_id, []).append(output_index)
        element_outputs[slide.id] = destinations
    return mapping_from_outputs(source_manifest, slide_outputs, element_outputs)


def _insert_slide_after(presentation, reference, position: int):
    """Crea una slide vacía y la coloca en `position` (0-based) del deck de salida.

    python-pptx solo sabe añadir al final, así que se mueve su entrada en `sldIdLst`.
    Hereda el layout de la slide de origen porque `redraw` la dibuja entera: lo único
    que importa es que pertenezca al mismo master.
    """
    inserted = presentation.slides.add_slide(reference.slide_layout)
    slide_ids = presentation.slides._sldIdLst
    element = list(slide_ids)[-1]
    slide_ids.remove(element)
    slide_ids.insert(position, element)
    return inserted


def _normalize_canvas(presentation, kn: Knowledge, plan: dict) -> float:
    """Normaliza el PPTX a la salida 1920×1080 px y conserva la escala visual.

    El motor compone en coordenadas lógicas 720×405 pt. La salida de 1440×810 pt
    corresponde a 1920×1080 px a 96 dpi. El contenido conservado se encaja con
    escala uniforme y centrado; los fondos que cubrían la página siguen a sangre.
    """
    from pptx.util import Pt

    width, height = kn.tokens["canvas"]["width"], kn.tokens["canvas"]["height"]
    output = kn.tokens["output_canvas"]
    target_w, target_h = float(output["width_pt"]), float(output["height_pt"])
    source_w, source_h = presentation.slide_width.pt, presentation.slide_height.pt
    source_emu_w, source_emu_h = presentation.slide_width, presentation.slide_height
    factor = min(target_w / source_w, target_h / source_h)
    offset_x = (target_w - source_w * factor) / 2
    offset_y = (target_h - source_h * factor) / 2
    if abs(factor - 1.0) > 1e-6:
        for slide in presentation.slides:
            for shape in slide.shapes:
                covers_slide = (
                    shape.left <= 1 and shape.top <= 1
                    and shape.width >= 0.97 * source_emu_w and shape.height >= 0.97 * source_emu_h
                )
                for attr in ("left", "top", "width", "height"):
                    try:
                        setattr(shape, attr, int(getattr(shape, attr) * factor))
                    except (AttributeError, TypeError, ValueError):
                        pass
                if covers_slide:
                    shape.left, shape.top = 0, 0
                    shape.width, shape.height = Pt(target_w), Pt(target_h)
                else:
                    shape.left = int(shape.left + offset_x * 12700)
                    shape.top = int(shape.top + offset_y * 12700)
                if getattr(shape, "has_text_frame", False):
                    frame = shape.text_frame
                    for attr in ("margin_left", "margin_right", "margin_top", "margin_bottom"):
                        value = getattr(frame, attr)
                        if value is not None:
                            setattr(frame, attr, int(value * factor))
                    for paragraph in frame.paragraphs:
                        for attr in ("space_before", "space_after"):
                            value = getattr(paragraph, attr, None)
                            if value is not None:
                                setattr(paragraph, attr, Pt(value.pt * factor))
                        for run in paragraph.runs:
                            if run.font.size is not None:
                                run.font.size = Pt(run.font.size.pt * factor)
                if getattr(shape, "has_chart", False) and shape.has_chart:
                    scale_chart_text(shape, factor)
                if getattr(shape, "has_table", False):
                    table = shape.table
                    for row in table.rows:
                        row.height = int(row.height * factor)
                    for column in table.columns:
                        column.width = int(column.width * factor)
                    for row in table.rows:
                        for cell in row.cells:
                            for attr in ("margin_left", "margin_right", "margin_top", "margin_bottom"):
                                value = getattr(cell, attr)
                                if value is not None:
                                    setattr(cell, attr, int(value * factor))
                            for paragraph in cell.text_frame.paragraphs:
                                for run in paragraph.runs:
                                    if run.font.size is not None:
                                        run.font.size = Pt(run.font.size.pt * factor)
    presentation.slide_width, presentation.slide_height = Pt(target_w), Pt(target_h)
    return target_w / width


def _mark_redesign(slide, source_index: int, parts, offset: int) -> None:
    """Deja en los bytes lo que se compuso: la auditoría no confía en el reporte."""
    entry = parts[offset][0]
    write_marker(
        slide, mode="redesign", source=f"s{source_index}", part=offset + 1, parts=len(parts),
        family=entry.family or entry.archetype, layout=entry.layout, variant=entry.variant,
    )


def optimization_record(pre: Path, post: Path, workdir: Path, classes: dict[str, str] | None = None) -> dict:
    """Compara el PPTX antes y después de optimizar y lo ata al hash del resultado.

    `classes`: función de cada imagen por su huella de salida (`optimize.classes_after`).
    """
    from .audit import optimization

    result = optimization.audit(pre, post, workdir, classes=classes)
    return {
        "pre_sha": sha256(pre.read_bytes()).hexdigest(),
        "post_sha": sha256(post.read_bytes()).hexdigest(),
        "result": result.model_dump(),
    }


def _with_borrowed(spec, entries, deck):
    """La slide con los íconos prestados de otras slides (F5b), con su id local de préstamo.
    La integridad sigue comparando contra la slide de origen sin ellos: un préstamo no es
    contenido de esta slide."""
    extra = []
    for entry in entries:
        for local, element_id in entry.borrowed.items():
            source_id, source_local = element_id.split(":", 1)
            owner = next(item for item in deck.slides if item.index == int(source_id[1:]))
            if local not in {image.id for image in [*spec.images, *extra]}:
                extra.append(owner.image_by_id(source_local).model_copy(update={"id": local}))
    return spec.model_copy(update={"images": [*spec.images, *extra]}) if extra else spec


def _image_classes(src, classification: DeckClassification) -> dict[str, str]:
    """Clase de cada imagen por su huella (md5, como la ve el optimizador). Si la misma imagen
    aparece con dos clases, gana la más conservadora."""
    found: dict[str, set[str]] = defaultdict(set)
    for spec in src.slides:
        for image in spec.images:
            if cls := classification.asset_classes.get(spec.index, {}).get(image.id):
                found[image.sha].add(cls)
    return {sha: chosen for sha, classes in found.items() if (chosen := strictest(classes))}


def _shared_slot_ids(parts) -> set[str]:
    """Bloques del marco que **todas** las partes vuelven a mostrar (título, kicker).

    La introducción, el banner y las notas van en una sola parte; contarlos como
    repetidos haría pasar por pérdida el texto que sí se entregó una vez.
    """
    if len(parts) < 2:
        return set()
    frames = [
        {value for value in (entry.kicker, entry.title, entry.subtitle, entry.banner) if value}
        | set(entry.notes) | {value for values in entry.named.values() for value in values}
        for entry, _rendered in parts
    ]
    return set.intersection(*frames)


def _unassigned_in_part(element_id: str, entries) -> bool:
    """Un elemento solo está sin asignar si ninguna parte de la slide lo usa."""
    return all(element_id not in entry.assigned_ids() for entry in entries)


class RefactorEngine:
    """API de biblioteca sin rutas temporales implícitas.

    ``workspace`` pertenece al adaptador (CLI, MCP o worker); nunca se deriva
    de ``ROOT/work`` dentro del motor. El conocimiento visual sí es una entrada
    explícita y versionada, con el root del paquete como valor por defecto.
    """

    def __init__(self, workspace: str | Path, *, knowledge_root: str | Path = ROOT):
        self.workspace = Path(workspace)
        self.knowledge_root = Path(knowledge_root)

    def _job_dir(self, deck: str | Path) -> Path:
        digest = sha256(Path(deck).read_bytes()).hexdigest()[:16]
        return self.workspace / "jobs" / digest

    def _run_dir(self, deck: str | Path, output: str | Path) -> Path:
        digest = sha256(Path(deck).read_bytes()).hexdigest()[:12]
        return self.workspace / "runs" / f"{digest}-{Path(output).stem}"

    def _analysis_cache_path(self, deck: str | Path) -> Path:
        source_hash = sha256(Path(deck).read_bytes()).hexdigest()
        cache_key = sha256(f"{source_hash}:{PARSER_VERSION}:{visual_hash(self.knowledge_root)}".encode("utf-8")).hexdigest()
        return self.workspace / "cache" / f"analysis-{cache_key}.json"

    def _revision_path(self, manifest: SourceManifest, revision_id: str) -> Path:
        return self.workspace / "jobs" / manifest.source_hash[:16] / "plans" / f"{revision_id}.json"

    def _recognition_cache_path(self, manifest: SourceManifest) -> Path:
        patterns = (self.knowledge_root / "design_knowledge" / "recognition_patterns.yaml").read_bytes()
        cache_key = sha256(f"{manifest.source_hash}:{sha256(patterns).hexdigest()}".encode("utf-8")).hexdigest()
        return self.workspace / "cache" / f"recognition-{cache_key}.json"

    def _design_version(self) -> str:
        return load_visual_contract(self.knowledge_root).version

    def design_version(self) -> str:
        """Versión visual activa: la que recibe toda revisión nueva del plan."""
        return self._design_version()

    def families(self) -> list[str]:
        """Catálogo de familias registradas, en orden estable (para CLI, MCP y UI)."""
        return sorted(self._families())

    def variants(self, family: str) -> list[str]:
        """Variantes registradas de una familia (`allowed_variants` del catálogo)."""
        entry = Knowledge(self.knowledge_root).catalog.get("families", {}).get(family) or {}
        return list(entry.get("allowed_variants") or [])

    def layouts(self) -> list[str]:
        """Composiciones registradas en `design_knowledge/layouts/`."""
        return sorted(Knowledge(self.knowledge_root).layouts)

    def _families(self) -> set[str]:
        catalog = yaml.safe_load((self.knowledge_root / "design_knowledge" / "visual_catalog.yaml").read_text())
        return set(catalog["families"])

    def analyze(self, deck: str | Path, *, slides: list[int] | None = None) -> AnalysisResult:
        """Parsea una vez y expone resumen + manifiesto sin alterar el PPTX."""
        deck_path = Path(deck)
        # Un análisis parcial tiene una vista distinta y no puede reutilizar el
        # snapshot completo como si sus decisiones aplicaran a todas las slides.
        cache_path = self._analysis_cache_path(deck_path) if slides is None else None
        if cache_path and cache_path.exists():
            cached = json.loads(cache_path.read_text())
            manifest = SourceManifest.model_validate(cached["manifest"])
            return self._with_groups(manifest, cached["summary"])
        spec = parse_deck(deck_path, self._job_dir(deck_path) / "media", slides)
        manifest = build_source_manifest(deck_path, deck=spec)
        summary = summarize(spec)
        if cache_path:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps({"manifest": manifest.model_dump(), "summary": summary}, ensure_ascii=False))
        return self._with_groups(manifest, summary)

    def _with_groups(self, manifest: SourceManifest, summary: dict) -> AnalysisResult:
        """Los grupos se derivan del manifiesto: no se cachean ni se guardan como hechos."""
        groups = group_slides(manifest)
        summary = {**summary, "groups": [group.view() for group in groups]}
        return AnalysisResult(source=manifest, manifest=manifest, summary=summary, groups=groups)

    def default_plan(self, manifest: SourceManifest) -> AnalysisPlan:
        """Crea el borrador explícito: visibles seleccionadas, ocultas protegidas."""
        visible_criteria = [
            AcceptanceCriterion(id="content-integrity", kind="content_integrity", description="Conservar texto, cifras, imágenes, notas y enlaces."),
            AcceptanceCriterion(id="geometry", kind="geometry", description="Cumplir zona segura y geometría de familia."),
            AcceptanceCriterion(id="render", kind="render", description="No producir cortes ni colisiones al renderizar."),
            AcceptanceCriterion(id="visual-quality", kind="visual_quality", description="Mantener jerarquía y aire visual suficientes."),
            AcceptanceCriterion(id="style-integrity", kind="style_integrity", description="Usar componentes y tokens aprobados."),
            AcceptanceCriterion(id="family", kind="family", description="Componer la familia aprobada o documentar su excepción."),
        ]
        groups = group_slides(manifest)
        group_ids = {
            slide_id: group.id for group in groups for slide_id in group.source_slide_ids
        }
        slides = []
        for source_slide in manifest.slides:
            assignments = [ElementAssignment(
                element_id=element.id,
                # Una forma es decorativa salvo que sea un gráfico nativo: ese es contenido.
                classification=("brand" if element.name.startswith("NEO_BRAND")
                                else "decorative" if element.kind == "shape" and element.chart is None else "content"),
            ) for element in source_slide.elements]
            if source_slide.visible:
                slides.append(SlidePlan(
                    source_slide_id=source_slide.id,
                    group_id=group_ids.get(source_slide.id),
                    family="needs_model_classification",
                    selected_for_redesign=True,
                    assignments=assignments,
                    acceptance_criteria=visible_criteria,
                    family_explanation="La familia se decide durante la revisión de análisis; no se aplicará brand_shell como aprobación.",
                ))
            else:
                slides.append(SlidePlan(
                    source_slide_id=source_slide.id,
                    family="hidden",
                    selected_for_redesign=False,
                    assignments=assignments,
                    acceptance_criteria=[visible_criteria[0], visible_criteria[1]],
                    exclusion_reason="slide oculta: se conserva intacta",
                ))
        return AnalysisPlan(
            source_deck_id=manifest.source_deck_id,
            source_hash=manifest.source_hash,
            design_version=self._design_version(),
            revision=1,
            slides=slides,
        )

    def recognize_families(self, manifest: SourceManifest):
        """Propone únicamente patrones registrados; los ambiguos van al host."""
        cache_path = self._recognition_cache_path(manifest)
        if cache_path.exists():
            return [FamilyRecognition.model_validate(item) for item in json.loads(cache_path.read_text())]
        recognitions = recognize_families(manifest, knowledge_root=self.knowledge_root)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps([item.model_dump() for item in recognitions], ensure_ascii=False))
        return recognitions

    def model_packages(
        self, manifest: SourceManifest, *, policy: dict | None = None, slides: set[str] | None = None,
    ) -> list[dict]:
        """Entrega lotes compactos para el host, nunca el PPTX ni el inventario total."""
        return build_model_packages(
            manifest, design_version=self._design_version(), policy=policy, slides=slides
        )

    def validate_plan(self, manifest: SourceManifest, plan: AnalysisPlan) -> PlanValidationResult:
        """Valida un plan completo antes de abrir el renderer.

        Los problemas se devuelven por slide para que la UI pueda señalar y
        corregir solo la tarjeta afectada.
        """
        issues: list[PlanValidationIssue] = []

        def issue(slide_id: str, code: str, detail: str, severity: str = "error") -> None:
            issues.append(PlanValidationIssue(
                source_slide_id=slide_id, code=code, detail=detail, severity=severity
            ))

        plan_ids = [slide.source_slide_id for slide in plan.slides]
        context_ids = plan_ids or [slide.id for slide in manifest.slides] or ["deck"]
        if plan.source_deck_id != manifest.source_deck_id:
            for slide_id in context_ids:
                issue(slide_id, "stale_source_deck", "El plan pertenece a otro deck de origen.")
        if plan.source_hash != manifest.source_hash:
            for slide_id in context_ids:
                issue(slide_id, "stale_source_hash", "El hash del PPTX no coincide; vuelve a analizarlo.")
        if plan.design_version != self._design_version():
            for slide_id in context_ids:
                issue(slide_id, "stale_design_version", "El plan usa una versión visual distinta de la activa.")

        manifest_by_id = {slide.id: slide for slide in manifest.slides}
        for slide_id in sorted({slide_id for slide_id in plan_ids if plan_ids.count(slide_id) > 1}):
            issue(slide_id, "duplicate_slide", "La slide aparece más de una vez en la revisión.")
        for source_slide in manifest.slides:
            if source_slide.id not in plan_ids:
                issue(source_slide.id, "unplanned_slide", "Falta una decisión explícita para esta slide de origen.")

        families = self._families()
        for slide_plan in plan.slides:
            source_slide = manifest_by_id.get(slide_plan.source_slide_id)
            if source_slide is None:
                issue(slide_plan.source_slide_id, "unknown_slide", "La slide no existe en el manifiesto de origen.")
                continue
            source_ids = {element.id for element in source_slide.elements}
            assigned_ids = [assignment.element_id for assignment in slide_plan.assignments]
            for element_id in sorted({element_id for element_id in assigned_ids if element_id not in source_ids}):
                issue(source_slide.id, "unknown_element", f"El elemento {element_id} no existe en la slide.")
            for element_id in sorted({element_id for element_id in assigned_ids if assigned_ids.count(element_id) > 1}):
                issue(source_slide.id, "duplicate_element", f"El elemento {element_id} tiene más de una asignación.")
            for element_id in sorted(source_ids - set(assigned_ids)):
                issue(source_slide.id, "unassigned_element", f"El elemento {element_id} no tiene destino en el plan.")
            charts = {element.id for element in source_slide.elements if element.chart is not None}
            for assignment in slide_plan.assignments:
                if assignment.element_id in charts and assignment.classification != "content":
                    issue(source_slide.id, "native_chart_not_content",
                          f"{assignment.element_id} es un gráfico nativo: es contenido, nunca decorativo ni marca.")

            if source_slide.visible and not slide_plan.selected_for_redesign and not slide_plan.exclusion_reason:
                issue(source_slide.id, "missing_exclusion_reason", "Excluir una slide visible requiere una razón explícita.")
            if not source_slide.visible:
                if slide_plan.selected_for_redesign or slide_plan.visual_directives or slide_plan.family != "hidden":
                    issue(source_slide.id, "hidden_slide_read_only", "Las slides ocultas se conservan intactas y sin directivas.")
            elif slide_plan.family == "hidden":
                issue(source_slide.id, "family_visibility_mismatch", "La familia hidden solo corresponde a una slide oculta.")

            if slide_plan.family not in families and not slide_plan.family_explanation:
                issue(source_slide.id, "unregistered_family", "Una familia no registrada requiere explicación de compatibilidad.")
            if slide_plan.selected_for_redesign and not slide_plan.acceptance_criteria:
                issue(source_slide.id, "missing_acceptance_criteria", "Una slide seleccionada necesita criterios de aceptación comprobables.")
            for directive in slide_plan.visual_directives:
                if _CONTENT_COMMAND.search(directive.instruction):
                    issue(source_slide.id, "content_change_directive", "Una directiva visual no puede alterar, resumir ni reescribir contenido.")

        issues += self._group_divergence(plan)

        return PlanValidationResult(issues=issues)

    def _group_divergence(self, plan: AnalysisPlan) -> list[PlanValidationIssue]:
        """Avisa cuando slides de la misma estructura reciben decisiones distintas.

        No es un error: a veces una slide del grupo merece otra familia y para eso está
        la explicación. Pero por omisión, decidir slide por slide es justamente lo que
        deja una huérfana con el estilo viejo, así que el plan lo dice en voz alta.
        """
        by_group: dict[str, list[SlidePlan]] = defaultdict(list)
        for slide_plan in plan.slides:
            if slide_plan.group_id:
                by_group[slide_plan.group_id].append(slide_plan)
        issues: list[PlanValidationIssue] = []
        for group_id, members in sorted(by_group.items()):
            decisions = {
                (member.family, member.composition_layout, member.selected_for_redesign, bool(member.keep_layout))
                for member in members
            }
            if len(members) < 2 or len(decisions) == 1:
                continue
            detail = "; ".join(
                f"{member.source_slide_id}: {member.family}"
                f"{'/' + member.composition_layout if member.composition_layout else ''}"
                f"{'' if member.selected_for_redesign else ' (excluida)'}"
                for member in members
            )
            for member in members:
                issues.append(PlanValidationIssue(
                    source_slide_id=member.source_slide_id,
                    code="group_decision_divergent",
                    severity="warning",
                    detail=(
                        f"El grupo {group_id} comparte estructura y recibió decisiones distintas "
                        f"({detail}). Aplícalo a todo el grupo o explica la excepción."
                    ),
                ))
        return issues

    def validate_render_plan(self, manifest: SourceManifest, plan: AnalysisPlan) -> PlanValidationResult:
        """Añade a la validación estructural los slots que el compositor ya sabe ejecutar."""
        structural = self.validate_plan(manifest, plan)
        if not structural.valid:
            return structural
        return PlanValidationResult(issues=[*structural.issues, *renderability_issues(manifest, plan)])

    def freeze_plan(
        self, manifest: SourceManifest, plan: AnalysisPlan, *, revision_id: str | None = None,
        parent_revision_id: str | None = None,
    ) -> PlanRevision:
        """Cierra una revisión válida y materializa un compromiso por criterio."""
        result = self.validate_plan(manifest, plan)
        if not result.valid:
            raise ValueError("el plan no es aprobable: " + ", ".join(issue.code for issue in result.issues))
        revision_id = revision_id or f"plan-{uuid4()}"
        commitments = [
            PlanCommitment(
                id=f"{revision_id}:{slide.source_slide_id}:{criterion.id}",
                source_slide_id=slide.source_slide_id,
                family=slide.family,
                criterion_ids=[criterion.id],
            )
            for slide in plan.slides
            for criterion in slide.acceptance_criteria
        ]
        frozen = PlanRevision(
            id=revision_id, plan=plan, commitments=commitments,
            status="approved", parent_revision_id=parent_revision_id,
        )
        path = self._revision_path(manifest, revision_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            existing = PlanRevision.model_validate_json(path.read_text())
            if existing != frozen:
                raise ValueError(f"la revisión {revision_id} ya existe con otro contenido")
            return existing
        path.write_text(frozen.model_dump_json(indent=2))
        return frozen

    def load_revision(self, manifest: SourceManifest, revision_id: str) -> PlanRevision:
        return PlanRevision.model_validate_json(self._revision_path(manifest, revision_id).read_text())

    def revise_plan(
        self, manifest: SourceManifest, previous: PlanRevision, corrected: AnalysisPlan, *, revision_id: str | None = None,
    ) -> PlanRevision:
        """Una corrección crea una nueva revisión; no altera la aprobada."""
        if previous.status != "approved":
            raise ValueError("solo se puede corregir una revisión aprobada")
        if corrected.revision != previous.plan.revision + 1:
            raise ValueError("la corrección debe incrementar revision exactamente en uno")
        if (corrected.source_deck_id, corrected.source_hash, corrected.design_version) != (
            previous.plan.source_deck_id, previous.plan.source_hash, previous.plan.design_version,
        ):
            raise ValueError("una corrección no puede cambiar el deck ni la versión visual")
        return self.freeze_plan(manifest, corrected, revision_id=revision_id, parent_revision_id=previous.id)

    def plan_delta(self, previous: PlanRevision, current: PlanRevision) -> dict:
        """Expone al host solo las decisiones cambiadas de la revisión siguiente."""
        if current.parent_revision_id != previous.id:
            raise ValueError("las revisiones no forman una secuencia directa")
        before = {slide.source_slide_id: slide.model_dump() for slide in previous.plan.slides}
        changed = [
            slide.model_dump() for slide in current.plan.slides
            if before.get(slide.source_slide_id) != slide.model_dump()
        ]
        return {
            "source_deck_id": current.plan.source_deck_id,
            "source_hash": current.plan.source_hash,
            "from_revision": previous.id,
            "to_revision": current.id,
            "slides": changed,
        }

    def redesign(
        self, deck: str | Path, classification: str | Path | DeckClassification, out: str | Path,
        *, optimize_images: bool = True, preserve_unclassified: bool = False,
    ) -> dict:
        """Compatibilidad de composición actual; no acepta un plan parcial como éxito.

        La migración de cada familia desde ``DeckClassification`` se mantiene
        explícita. La API ya no depende de rutas de CLI, y conserva exactamente
        la semántica del rediseñador legado hasta que las familias nuevas entren
        con sus pruebas de regresión.
        """
        deck_path, out_path = Path(deck), Path(out)
        t0 = time.time()
        kn = Knowledge(self.knowledge_root)
        if isinstance(classification, DeckClassification):
            classification_model = classification
        else:
            classification_model = DeckClassification.model_validate_json(Path(classification).read_text())
        cls: dict[int, list] = defaultdict(list)
        for entry in classification_model.slides:
            cls[entry.slide].append(entry)
        src = parse_deck(deck_path, self._job_dir(deck_path) / "media")
        source_manifest = build_source_manifest(deck_path, deck=src)
        # Logo del cliente que marcó el plan: la marca de cada slide pasa a ser NEO | cliente.
        # `redisenar --logo-cliente RUTA` deja la imagen en `client_logo_path` (gana al plan) y
        # `--logo-cliente-oscuro`, el modo de la variante oscura en `client_logo_dark`.
        client_logo = cobrand.from_classification(
            src, classification_model, self._job_dir(deck_path) / "cobrand",
            path=getattr(self, "client_logo_path", None), dark_mode=getattr(self, "client_logo_dark", "auto"))
        composer = Composer(kn, classification_model.asset_classes, client_logo)

        plan: dict[int, SlideReport] = {}
        rendered = {}
        keep_layout = classification_model.keep_layout
        # Textos que la persona aprobó cambiar (`text_overrides`) y su cita para juntar rótulos
        # repetidos (`consolidate_labels`), por slide de origen. `applied_texts`: los que se aplicaron.
        requested_texts = {**classification_model.shell_text_overrides}
        consolidate = {}
        for entry in classification_model.slides:
            if entry.text_overrides:
                requested_texts.setdefault(entry.slide, entry.text_overrides)
            if entry.consolidate_labels:
                consolidate.setdefault(entry.slide, entry.consolidate_labels)
        applied_texts: dict[int, dict] = {}
        for spec in src.slides:
            entries = cls.get(spec.index, [])
            if spec.hidden:
                plan[spec.index] = SlideReport(slide=spec.index, mode="hidden", reason="slide oculta: se copia intacta")
                continue
            if spec.index in keep_layout:
                # Pedido de la persona: su organización se conserva y solo cambia el estilo.
                plan[spec.index] = SlideReport(
                    slide=spec.index, mode="brand_shell",
                    reason="layout conservado a pedido de la persona: solo se corrige el estilo",
                )
                continue
            if not entries:
                plan[spec.index] = SlideReport(
                    slide=spec.index,
                    mode="preserved" if preserve_unclassified else "brand_shell",
                    reason="sin layout compatible; se conserva" if preserve_unclassified else "sin layout compatible",
                )
                continue
            spec = _with_borrowed(spec, entries, src)
            for entry in entries:
                missing = [element_id for element_id in entry.assigned_ids() if element_id not in spec.element_ids()]
                if missing:
                    raise ValueError(f"slide {entry.slide}: ids inexistentes en la clasificación: {missing}")
            if spec.index in requested_texts:
                if wrong := texts_ok.unknown(spec, requested_texts[spec.index]):
                    raise ValueError(f"slide {spec.index}: text_overrides apunta a textos inexistentes: {wrong}")
                # El texto aprobado entra antes de componer: el layout se mide con él.
                spec = texts_ok.apply_to_spec(spec, requested_texts[spec.index])
                applied_texts[spec.index] = requested_texts[spec.index]
            if any(shape.chart is not None for shape in spec.shapes):
                # Ningún layout tiene slot de gráfico todavía y `redraw` vacía la slide: el
                # gráfico nativo se perdería. Se queda en su lugar, con la marca (fase 2).
                plan[spec.index] = SlideReport(
                    slide=spec.index, mode="brand_shell", layout=entries[0].layout,
                    reason="gráfico nativo: se conserva en su lugar con la marca; ningún layout tiene slot de gráfico",
                )
                continue
            # Una partición se compone entera o no se compone: media slide rediseñada y
            # media en brand_shell no es un resultado que se pueda entregar.
            composed = []
            overflow: list[str] = []
            for entry in entries:
                rendered_slide = composer.compose(spec, entry)
                rendered_slide.compose_issues += [
                    f"unassigned:{element_id}" for element_id in integrity.unassigned(spec, entry)
                    if len(entries) == 1 or _unassigned_in_part(element_id, entries)
                ]
                overflow += [item for item in rendered_slide.compose_issues if item.startswith(OVERFLOW_CODES)]
                composed.append((entry, rendered_slide))
            if overflow:
                plan[spec.index] = SlideReport(
                    slide=spec.index, mode="brand_shell", layout=entries[0].layout,
                    reason=f"el contenido no cabe a {kn.min_size:g} pt en {entries[0].layout} "
                           f"({', '.join(overflow)}); nunca se resume",
                )
            else:
                rendered[spec.index] = composed
                plan[spec.index] = SlideReport(
                    slide=spec.index, mode="redesign", layout=entries[0].layout,
                    parts=len(composed),
                )
        t_compose = time.time()

        presentation = Presentation(str(deck_path))
        scale = _normalize_canvas(presentation, kn, plan)
        # Imágenes que conservan sus colores aunque sean de un color (logos, capturas…): el shell
        # repinta los demás íconos con el azul de marca.
        keep_colors = frozenset(sha for sha, kind in _image_classes(src, classification_model).items()
                                if kind in KEEP_ICON_COLORS)
        removed: dict[int, set[str]] = {}
        outputs: dict[int, list[int]] = {}
        position = 0  # posición 0-based de la slide de origen dentro del deck de salida
        for idx, slide in enumerate(list(presentation.slides), 1):
            report = plan[idx]
            if report.mode in ("brand_shell", "preserved") and requested_texts.get(idx):
                # La slide conserva su organización: el texto aprobado se reemplaza en el PPTX.
                done = texts_ok.apply_to_slide(slide, src.slide(idx), requested_texts[idx])
                applied_texts[idx] = {key: requested_texts[idx][key] for key in done}
            if report.mode == "redesign":
                parts = rendered[idx]
                redraw(slide, parts[0][1], presentation.slide_width, presentation.slide_height, scale)
                _mark_redesign(slide, idx, parts, 0)
                indices = [position + 1]
                for offset, (_entry, rendered_part) in enumerate(parts[1:], start=1):
                    inserted = _insert_slide_after(presentation, slide, position + offset)
                    redraw(inserted, rendered_part, presentation.slide_width, presentation.slide_height, scale)
                    _mark_redesign(inserted, idx, parts, offset)
                    indices.append(position + offset + 1)
                outputs[idx] = indices
                report.output_slides = indices
                position += len(parts)
                continue
            if report.mode == "preserved":
                outputs[idx] = [position + 1]
                report.output_slides = outputs[idx]
                position += 1
                continue
            if report.mode == "brand_shell":
                # Marcos y fondos que el plan retiró de la slide conservada (solo formas).
                drop = set(classification_model.shell_decorative.get(idx, []))
                logos = set(classification_model.shell_brand.get(idx, []))
                dropped = 0
                brand_shas: set[str] = set()
                for shape in list(slide.shapes):
                    has_text = getattr(shape, "has_text_frame", False) and shape.text_frame.text.strip()
                    # Una imagen o una forma con texto nunca es un marco retirable.
                    # Un gráfico nativo es contenido: tampoco (shape_type 3).
                    if shape.shape_id in drop and shape.shape_type not in (3, 13) and not has_text:
                        shape._element.getparent().remove(shape._element)
                        dropped += 1
                    elif shape.shape_id in logos and shape.shape_type == 13:
                        # Logo antiguo que el plan marcó como marca: lo reemplaza el del shell.
                        # La integridad lo descuenta como retirado a propósito, igual que los
                        # logos que retira el propio shell.
                        brand_shas.add(hashlib.md5(shape.image.blob).hexdigest()[:10])
                        shape._element.getparent().remove(shape._element)
                        dropped += 1
                issues, shas, stats = apply_shell(
                    slide, kn, composer.brand_elements, presentation.slide_width, presentation.slide_height,
                    keep_layout=idx in keep_layout, keep_colors=keep_colors, client_logo=client_logo,
                )
                report.issues, report.stats, removed[idx] = issues, stats, shas | brand_shas
                if dropped:
                    report.stats = {**report.stats, "decorative_removed": dropped}
                # La slide conservada también sigue la regla de marca: sin emojis.
                if emojis := strip_slide_emojis(slide):
                    report.stats = {**(report.stats or {}), "emojis_removed": len(emojis)}
                # Y las reglas de marca de la referencia Taller 1 v7: paleta, vínculos, radios y cards blancas.
                if brand_fixes := apply_brand_rules(slide, kn, presentation.slide_width / 12700 / kn.tokens["canvas"]["width"]):
                    report.stats = {**(report.stats or {}), "brand_rules_fixed": brand_fixes}
                # Gráficos nativos: siguen nativos, con la paleta y la tipografía de marca.
                if native := charts_in(slide):
                    chart_scale = presentation.slide_width / 12700 / kn.tokens["canvas"]["width"]
                    for chart_shape in native:
                        apply_chart_brand(chart_shape, kn, dark=stats.get("mode") == "dark", scale=chart_scale)
                    report.stats = {**(report.stats or {}), "native_charts_branded": len(native)}
                if idx in keep_layout:
                    write_marker(slide, mode="brand_shell", source=f"s{idx}", family=keep_layout[idx],
                                 variant="keep_layout")
                else:
                    write_marker(slide, mode="brand_shell", source=f"s{idx}")
            outputs[idx] = [position + 1]
            report.output_slides = outputs[idx]
            position += 1
        if not preserve_unclassified:
            fix_theme_links(presentation, kn)
            drop_embedded_brand_fonts(presentation, kn)
        source_output_mapping = _mapping_from_render(source_manifest, plan, rendered)
        mapping_result = validate_mapping(source_manifest, source_output_mapping)
        if not mapping_result.valid:
            raise ValueError(
                "el mapa de origen a salida no es válido: "
                + ", ".join(sorted({issue.code for issue in mapping_result.issues}))
            )

        from .design_policies import ensure_bookends
        closing_appended = ensure_bookends(presentation, kn, client_logo)
        if plan[1].mode == "preserved":
            plan[1].mode = "brand_shell"
            plan[1].reason = "portada light obligatoria (regla universal 2026-09-30)"
        removed.setdefault(1, set()).update(image.sha for image in src.slide(1).images
            if image.box.w * image.box.h >= src.width * src.height * 0.9
            or (image.box.w < src.width*0.3 and image.box.y < src.height*0.2))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        run_dir = self._run_dir(deck_path, out_path)
        pre = run_dir / "pre_optimize.pptx"
        pre.parent.mkdir(parents=True, exist_ok=True)
        presentation.save(str(pre))
        t_render = time.time()
        produced = parse_deck(pre, run_dir / "media")
        kept = {outputs[idx][0] for idx, report in plan.items() if report.mode == "preserved" and idx in outputs}
        classes = _image_classes(src, classification_model)
        # Un ícono repintado (`icon_tint`) es un archivo nuevo: conserva la política de ícono.
        classes.update({image.sha: "icon" for spec in produced.slides for image in spec.images
                        if image.name.startswith("icon_") and image.sha not in classes})
        opt_stats = optimize(presentation, skip_slides=kept, classes=classes) if optimize_images else {}
        presentation.save(str(out_path))
        optimization = optimization_record(pre, out_path, run_dir, classes_after(opt_stats))
        if optimization["result"]["subchecks"].get("images") == "fail" and any(
            finding["code"] == "image_count_changed" for finding in optimization["result"]["findings"]
        ):
            slides_lost = sorted({f["slide_id"] for f in optimization["result"]["findings"] if f["code"] == "image_count_changed"})
            raise ValueError(f"la optimización cambió la cantidad de imágenes en slides {slides_lost}")
        pre.unlink()
        for idx, report in plan.items():
            if report.mode == "hidden":
                continue
            if idx == len(src.slides) and not closing_appended:
                report.content_integrity = {"preserved": True, "numeric_changes": 0,
                    "removed_content": [], "images_missing": [],
                    "policy_exception": "despedida universal de marca autorizada, Referencia v2, slide 32"}
                report.score = 100
                continue
            # Textos aprobados: el reporte guarda el original y el nuevo, y la integridad compara
            # el nuevo. Con `consolidate_labels`, los rótulos juntados no bloquean (las cifras, sí).
            approved = applied_texts.get(idx) or {}
            report.text_overrides = texts_ok.report_entries(src.slide(idx), approved)
            report.consolidate_labels = consolidate.get(idx)
            requested = {"text_overrides": {key: item.text for key, item in approved.items()},
                         "consolidate": bool(report.consolidate_labels)}
            if report.mode == "redesign":
                parts = rendered[idx]
                scores, issues = zip(*(validate(rendered_part, kn) for _entry, rendered_part in parts))
                # Una partición vale lo que su peor parte: ninguna slide entregada queda sin auditar.
                report.score, report.issues = min(scores), [issue for group in issues for issue in group]
                report.content_integrity = integrity.check(
                    src.slide(idx),
                    [produced.slide(index) for index in report.output_slides],
                    skip_ids=set().union(*(set(entry.brand) | set(entry.decorative) for entry, _ in parts)),
                    repeated_ids=_shared_slot_ids(parts), **requested,
                )
            else:
                report.content_integrity = integrity.check(
                    src.slide(idx), [produced.slide(index) for index in report.output_slides],
                    skip_shas=removed.get(idx, set()), **requested,
                )
                report.score = max(0, 100 - sum(15 if item.severity == "error" else 5 for item in report.issues))
            if not report.content_integrity["preserved"]:
                report.score = 0
        reports = [plan[index] for index in sorted(plan)]
        active = [report for report in reports if report.mode != "hidden"]
        approved = [report for report in active if report.score >= 85]
        summary = {
            "presentation": str(deck_path.name),
            "output": str(out_path),
            "knowledge_version": kn.tokens["version"],
            "slides_total": len(presentation.slides),
            "canonical_closing_appended": closing_appended,
            "slides_redesigned": sum(report.mode == "redesign" for report in reports),
            "slides_brand_shell": sum(report.mode == "brand_shell" for report in reports),
            "slides_preserved": sum(report.mode == "preserved" for report in reports),
            "slides_hidden_untouched": sum(report.mode == "hidden" for report in reports),
            "slides_approved_first_pass": len(approved),
            "slides_flagged_for_review": [report.slide for report in active if report.score < 85],
            "content_integrity": {
                "preserved": all(report.content_integrity["preserved"] for report in active),
                "numeric_changes": sum(report.content_integrity["numeric_changes"] for report in active),
                "removed_content": sum(len(report.content_integrity["removed_content"]) for report in active),
                # Textos aprobados por la persona y aplicados (`text_overrides`).
                "requested_changes": sum(len(report.text_overrides) for report in active),
                # Imágenes con otros bytes que siguen siendo la del origen (`same_picture`).
                "images_treated": sum(len(report.content_integrity.get("images_treated", [])) for report in active),
            },
            "average_design_score": round(sum(report.score for report in active) / max(1, len(active)), 1),
            "file_mb": round(out_path.stat().st_size / 1e6, 1),
            "image_optimization": opt_stats,
            "optimization_audit": optimization,
            "source_output_mapping": source_output_mapping.model_dump(),
            "timing_s": {
                "parse+compose": round(t_compose - t0, 2),
                "render": round(t_render - t_compose, 2),
                "validate": round(time.time() - t_render, 2),
            },
            "slides": [report.model_dump() for report in reports],
        }
        out_path.with_name(out_path.stem + "_report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1))
        return summary

    def dry_compose(self, deck: str | Path, plan: AnalysisPlan) -> dict:
        """Compone las slides seleccionadas sin renderizar: qué cabe y qué no, con métricas reales.

        Devuelve un reporte con la forma de `redesign` (`slides[].mode/reason`) para que
        `overflow_issues` lo lea igual. Sirve para avisar antes de aplicar (el guion de un deck
        creado se mide al armarlo, no al generar).
        """
        deck_path = Path(deck)
        manifest = self.analyze(deck_path).manifest
        if not self.validate_render_plan(manifest, plan).valid:
            return {"slides": []}
        kn = Knowledge(self.knowledge_root)
        classification = to_legacy_classification(manifest, plan)
        entries_by_slide: dict[int, list] = defaultdict(list)
        for entry in classification.slides:
            entries_by_slide[entry.slide].append(entry)
        src = parse_deck(deck_path, self._job_dir(deck_path) / "media")
        composer = Composer(kn, classification.asset_classes)
        slides = []
        for spec in src.slides:
            entries = entries_by_slide.get(spec.index, [])
            if spec.hidden or not entries:
                continue
            spec = texts_ok.apply_to_spec(_with_borrowed(spec, entries, src), entries[0].text_overrides)
            overflow = [item for entry in entries for item in composer.compose(spec, entry).compose_issues
                        if item.startswith(OVERFLOW_CODES)]
            slides.append({"slide": spec.index, "mode": "brand_shell" if overflow else "redesign",
                           "reason": (f"el contenido no cabe a {kn.min_size:g} pt en {entries[0].layout} "
                                      f"({', '.join(overflow)}); acorta el texto o parte la slide") if overflow else None})
        return {"slides": slides}

    def redesign_plan(
        self, deck: str | Path, plan: AnalysisPlan, out: str | Path, *, preserve_unselected: bool = False,
    ) -> dict:
        """Renderiza un plan aprobado sin ofrecer un fallback como resultado aceptable.

        Con `preserve_unselected` (alcance parcial) las slides que el plan no selecciona quedan
        intactas: sin brand shell y sin recomprimir sus imágenes.
        """
        deck_path, out_path = Path(deck), Path(out)
        analysis = self.analyze(deck_path)
        validation = self.validate_render_plan(analysis.manifest, plan)
        if not validation.valid:
            raise ValueError("plan no renderizable: " + ", ".join(issue.code for issue in validation.issues))
        classification = to_legacy_classification(analysis.manifest, plan)
        candidate = self._run_dir(deck_path, out_path) / "plan-candidate.pptx"
        summary = self.redesign(deck_path, classification, candidate, preserve_unclassified=preserve_unselected)
        selected_indices = {
            int(slide.source_slide_id[1:]) for slide in plan.slides if slide.selected_for_redesign
        }
        kept = {int(slide.source_slide_id[1:]) for slide in plan.slides if slide.keep_layout}
        blocked = [
            report for report in summary["slides"]
            if report["slide"] in selected_indices and report["mode"] != "redesign"
            and not (report["slide"] in kept and report["mode"] == "brand_shell")
        ]
        if blocked:
            summary["plan_status"] = "blocked"
            summary["plan_blocked_slides"] = [report["slide"] for report in blocked]
            candidate.with_name(candidate.stem + "_report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1))
            raise PlanRedesignBlocked(summary)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(candidate, out_path)
        summary["output"] = str(out_path)
        summary["plan_status"] = "candidate_needs_phase3_audits"
        out_path.with_name(out_path.stem + "_report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1))
        return summary

    def audit_context(
        self, deck: str | Path, revision: PlanRevision | None, candidate: str | Path, report: dict, *,
        reviews=(), exceptions=(),
    ):
        """Contexto de auditoría sobre los bytes de `candidate`, reabiertos desde disco."""
        from .audit import AuditContext
        from .schemas import SourceOutputMapping

        deck_path, candidate_path = Path(deck), Path(candidate)
        manifest = self.analyze(deck_path).manifest
        mapping = SourceOutputMapping.model_validate(report["source_output_mapping"])
        exceptions = [*exceptions, *_plan_exceptions(revision, mapping)]
        return AuditContext(
            source=manifest,
            output_path=candidate_path,
            mapping=mapping,
            design_version=revision.plan.design_version if revision else self._design_version(),
            workspace=self._run_dir(deck_path, candidate_path) / "audit",
            plan=revision,
            exceptions=list(exceptions),
            reviews=list(reviews),
            knowledge_root=self.knowledge_root,
            source_path=deck_path,
            optimization=report.get("optimization_audit"),
            untouched=frozenset(
                index for entry in report.get("slides", []) if entry.get("mode") == "preserved"
                for index in entry.get("output_slides", [])
            ),
        )

    def accept(
        self, deck: str | Path, revision: PlanRevision, candidate: str | Path, report: dict, *,
        reviews=(), exceptions=(), repair: bool = True,
    ) -> dict:
        """Reparación determinista + `final_acceptance_audit` del candidato privado.

        Si una reparación cambia el PPTX, se vuelve a optimizar y a comparar antes/después:
        el veredicto siempre corresponde a los bytes guardados, optimizados y reabiertos.
        """
        from .audit import final_acceptance_audit, run_suite
        from .audit.final import write_report
        from .audit.repair import repair_loop

        candidate_path = Path(candidate)
        state = None
        results = None

        def make_context(path: Path):
            return self.audit_context(deck, revision, path, report, reviews=reviews, exceptions=exceptions)

        if repair:
            state, results = repair_loop(candidate_path, make_context, run_suite)
            if state.applied:
                pre = candidate_path.with_name(candidate_path.stem + ".pre_optimize.pptx")
                shutil.copy2(candidate_path, pre)
                presentation = Presentation(str(candidate_path))
                # Las clases del primer pase: sin ellas una captura volvería a pasar por la heurística.
                classes = classes_after(report.get("image_optimization"))
                stats = optimize(presentation, classes=classes)
                presentation.save(str(candidate_path))
                report["optimization_audit"] = optimization_record(
                    pre, candidate_path, self._run_dir(deck, candidate_path), classes_after(stats) | classes)
                pre.unlink()
                results = None  # bytes nuevos: la suite se ejecuta otra vez sobre el archivo guardado
        verdict, results = final_acceptance_audit(make_context(candidate_path), results)
        run_dir = self._run_dir(deck, candidate_path)
        report_path = write_report(verdict, results, run_dir / "audit" / f"{verdict.pptx_sha256[:16]}.json")
        return {
            "verdict": verdict,
            "results": results,
            "repairs": state,
            "report_path": report_path,
            "report": report,
        }


def _plan_exceptions(revision, mapping) -> list:
    """Excepciones que la persona autorizó en el chat (`SlidePlan.rule_exceptions`), por slide de salida.

    El fallo que cubren pasa a aviso y queda registrado con lo que dijo la persona.
    """
    from .audit.core import ApprovedException
    from .schemas import RULE_EXCEPTION_CODES

    if revision is None:
        return []
    outputs = {entry.source_slide_id: entry.output_slide_indices for entry in mapping.slides}
    found = [
        ApprovedException(slide_id=index, code=code, condition=f"{item.rule} hasta {item.min_pt:g} pt",
                          reference=f"autorizado por la persona: {item.reason}")
        for slide in revision.plan.slides for item in slide.rule_exceptions
        for index in outputs.get(slide.source_slide_id, []) for code in RULE_EXCEPTION_CODES[item.rule]
    ]
    # Un tamaño pedido explícitamente bajo el mínimo de marca («usa letra 8») es la misma excepción.
    from .knowledge import Knowledge
    min_size = Knowledge().min_size
    found += [
        ApprovedException(slide_id=index, code="min_font_size", condition=f"{item.target} a {item.size_pt:g} pt",
                          reference=f"pedido por la persona: {item.reason}")
        for slide in revision.plan.slides for item in getattr(slide, "style_overrides", [])
        if item.size_pt is not None and item.size_pt < min_size
        for index in outputs.get(slide.source_slide_id, [])
    ]
    return found

