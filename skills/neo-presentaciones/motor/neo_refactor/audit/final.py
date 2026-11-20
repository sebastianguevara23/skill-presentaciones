"""Suite obligatoria, `final_acceptance_audit` y liberación del artefacto.

El veredicto se calcula sobre el archivo **ya guardado y optimizado**, reabierto desde
disco. `pass` exige que cada control obligatorio y cada compromiso del plan pasen
(un aviso no bloquea, pero queda en el reporte). Un `fail`, un `not_run`, contenido
perdido, una seleccionada en `brand_shell` o un margen fuera de regla dan `blocked`;
el puntaje es informativo y nunca cambia el veredicto. El auditor no reescribe el
plan: cambiar el alcance exige una revisión nueva aprobada por el usuario.

La liberación copia el PPTX al área de descarga solo si el veredicto es `pass` y el
archivo sigue teniendo el hash auditado; cualquier cambio posterior exige reauditar.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import shutil
from typing import Literal

from pydantic import BaseModel, Field

from . import content, fulfillment, geometry, render, style, visual
from .core import RULES_VERSION, AuditContext, AuditResult, Status, blocking, not_run, worst

MANDATORY = (
    "geometry_audit", "render_audit", "visual_quality_audit", "style_integrity_audit",
    "content_integrity", "optimization_audit", "plan_fulfillment_audit",
)
NEXT_ACTION = {
    "not_run": "ejecutar el control que falta (o revisar la preview en el host) y reauditar",
    "fail": "corregir la composición o aprobar una revisión nueva del plan y reauditar",
}


def run_suite(ctx: AuditContext) -> dict[str, AuditResult]:
    """Todos los auditores obligatorios, cada uno por separado, sobre los mismos bytes."""
    results: dict[str, AuditResult] = {}
    for module in (geometry, render, content, style, visual):
        result = module.audit(ctx)
        if ctx.untouched:
            result.demote_preexisting(ctx.untouched)
        results[result.auditor] = result
    results["optimization_audit"] = _optimization(ctx)
    results["plan_fulfillment_audit"] = fulfillment.audit(ctx, results)
    return results


def _optimization(ctx: AuditContext) -> AuditResult:
    record = ctx.optimization
    if not record:
        return not_run("optimization_audit", "no hay comparación antes/después de optimizar para este archivo")
    if record.get("post_sha") != ctx.output_sha:
        return not_run("optimization_audit", "la comparación de optimización es de otro archivo")
    return AuditResult.model_validate(record["result"])


class Verdict(BaseModel):
    status: Literal["pass", "blocked"]
    pptx_sha256: str
    source_hash: str
    plan_revision_id: str | None
    design_version: str
    rules_version: str = RULES_VERSION
    audited_at: str
    checks: dict[str, Status]
    subchecks: dict[str, dict[str, Status]]
    slides: list[dict]
    commitments: list[dict]
    blocked_reasons: list[dict] = Field(default_factory=list)
    exceptions: list[dict] = Field(default_factory=list)
    score: float = Field(description="Informativo: nunca cambia el veredicto.")


def final_acceptance_audit(ctx: AuditContext, results: dict[str, AuditResult] | None = None) -> tuple[Verdict, dict]:
    results = results or run_suite(ctx)
    reasons: list[dict] = []
    for name in MANDATORY:
        if name not in results:
            results[name] = not_run(name, "control obligatorio ausente de la suite")
    if ctx.plan is None or ctx.plan.status != "approved":
        reasons.append({"check": "plan", "code": "plan_not_approved", "status": "fail",
                        "symptom": "el candidato no tiene una revisión aprobada", "next_action": "aprobar el plan"})
    elif ctx.plan.plan.source_hash != ctx.source.source_hash:
        reasons.append({"check": "plan", "code": "stale_plan", "status": "fail",
                        "symptom": "la revisión es de otro deck", "next_action": "analizar de nuevo"})
    if ctx.design_version != ctx.contract.version:
        reasons.append({"check": "design", "code": "design_version_mismatch", "status": "fail",
                        "symptom": f"plan en {ctx.design_version}, sistema en {ctx.contract.version}",
                        "next_action": "reaprobar el plan con la versión visual vigente"})
    for name in MANDATORY:
        result = results[name]
        blocking_findings = [f for f in result.findings if blocking(f.status)]
        for finding in blocking_findings:
            reasons.append({
                "slide_id": finding.slide_id, "source_slide_id": finding.source_slide_id,
                "family": finding.family, "check": name, "subcheck": finding.subcheck, "code": finding.code,
                "status": finding.status, "symptom": finding.symptom,
                "next_action": finding.correction_proposed or NEXT_ACTION[finding.status],
            })
        if blocking(result.status) and not blocking_findings:
            reasons.append({"check": name, "code": f"{name}_{result.status}", "status": result.status,
                            "symptom": result.detail or f"{name} en {result.status}",
                            "next_action": NEXT_ACTION[result.status]})

    slides = []
    for slide in ctx.slides:
        statuses = {name: results[name].slides.get(slide.index, results[name].status) for name in MANDATORY}
        slides.append({
            "slide_id": slide.index, "source_slide_id": slide.source_slide_id, "family": slide.family,
            "mode": slide.mode, "hidden": slide.hidden, "checks": statuses, "status": worst(statuses.values()),
            "audited": ctx.in_scope(slide.index),
        })
    active = [s for s in slides if not s["hidden"]]
    score = round(100 * sum(not blocking(s["status"]) for s in active) / max(1, len(active)), 1)
    verdict = Verdict(
        status="blocked" if reasons else "pass",
        pptx_sha256=ctx.output_sha,
        source_hash=ctx.source.source_hash,
        plan_revision_id=ctx.plan.id if ctx.plan else None,
        design_version=ctx.design_version,
        audited_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        checks={name: results[name].status for name in MANDATORY},
        subchecks={name: results[name].subchecks for name in MANDATORY},
        slides=slides,
        commitments=results["plan_fulfillment_audit"].records,
        blocked_reasons=reasons,
        exceptions=[item for name in MANDATORY for item in results[name].exceptions_applied],
        score=score,
    )
    return verdict, results


def write_report(verdict: Verdict, results: dict[str, AuditResult], path: Path) -> Path:
    """Reporte privado completo: veredicto + hallazgos de cada auditor."""
    payload = {"verdict": verdict.model_dump(), "audits": {name: r.model_dump() for name, r in results.items()}}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1))
    return path


def blocked_report(verdict: Verdict) -> dict:
    """Lo único que se publica de un candidato bloqueado: causa y siguiente acción por slide."""
    by_slide: dict = {}
    for reason in verdict.blocked_reasons:
        key = reason.get("slide_id") or "deck"
        by_slide.setdefault(key, []).append({
            "check": reason["check"], "code": reason["code"], "status": reason["status"],
            "symptom": reason["symptom"], "next_action": reason["next_action"],
        })
    return {"status": verdict.status, "pptx_sha256": verdict.pptx_sha256,
            "plan_revision_id": verdict.plan_revision_id, "slides": by_slide}


class ReleaseBlocked(RuntimeError):
    pass


def release(candidate: Path, verdict: Verdict, releases_dir: Path) -> Path:
    """Habilita la descarga solo de los bytes que pasaron la auditoría final."""
    if verdict.status != "pass":
        raise ReleaseBlocked("el veredicto final no es pass: el candidato queda privado")
    digest = sha256(Path(candidate).read_bytes()).hexdigest()
    if digest != verdict.pptx_sha256:
        raise ReleaseBlocked("el archivo cambió después de auditarlo: hay que reauditar")
    releases_dir.mkdir(parents=True, exist_ok=True)
    destination = releases_dir / f"{digest[:16]}.pptx"
    shutil.copy2(candidate, destination)
    if sha256(destination.read_bytes()).hexdigest() != digest:
        destination.unlink()
        raise ReleaseBlocked("la copia liberada no coincide con el hash auditado")
    return destination
