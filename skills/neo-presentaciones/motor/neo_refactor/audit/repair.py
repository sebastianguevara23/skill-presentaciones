"""Ciclo de reparación: hallazgo → propuesta → nueva composición → suite completa.

Las reparaciones deterministas corren aquí, sobre el PPTX, y solo mueven o amplían
cajas (nunca bajan de 11 pt ni tocan texto):

- `outside_safe_zone` / `outside_composition_zone`: trasladar la caja dentro de su
  zona si cabe y no choca con otra.
- `google_font_or_wrap_risk` / `render_overflow` del render: primero una caja mayor,
  hacia abajo hasta lo que midió el render, si hay espacio libre en la zona.

Nunca se reparan slides ocultas (se conservan intactas). Tras cada ronda se vuelve a
ejecutar la **suite completa**; una reparación que no cambia el hallazgo no cuenta
como resuelta. Lo que queda se agrupa por familia y causa y se entrega como delta
al host, que decide con una revisión nueva del plan. El presupuesto de rondas sale
de `config/llmops.yaml`; agotarlo deja el trabajo `blocked` y reanudable.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
import shutil
from typing import Callable

from pptx import Presentation
from pptx.util import Pt

from ..schemas import Box
from .core import AuditContext, AuditResult, blocking
from .visual import llmops

GEOMETRY_CODES = {"outside_safe_zone", "outside_composition_zone"}
RENDER_CODES = {"google_font_or_wrap_risk", "render_overflow"}
EMU = 12700


@dataclass
class RepairState:
    rounds: int = 0
    applied: list[dict] = field(default_factory=list)
    ineffective: list[dict] = field(default_factory=list)
    exhausted: bool = False
    history: list[dict] = field(default_factory=list)


def _box(shape) -> Box:
    return Box(x=shape.left / EMU, y=shape.top / EMU, w=shape.width / EMU, h=shape.height / EMU)


def _set(shape, box: Box) -> None:
    shape.left, shape.top, shape.width, shape.height = Pt(box.x), Pt(box.y), Pt(box.w), Pt(box.h)


def _collides(slide, shape, box: Box) -> bool:
    """Choca con otra caja de texto o imagen que no sea su contenedor ni un fondo."""
    for other in slide.shapes:
        if other.shape_id == shape.shape_id or other.width is None:
            continue
        if not (getattr(other, "has_text_frame", False) and other.text_frame.text.strip()) and other.shape_type != 13:
            continue
        other_box = _box(other)
        if other_box.w >= 700:
            continue
        if other_box.overlaps(box) and not other_box.contains(_box(shape)):
            return True
    return False


def propose(ctx: AuditContext, results: dict[str, AuditResult]) -> list[dict]:
    """Propuestas deterministas para los hallazgos que las admiten."""
    proposals = []
    zones = {"outside_safe_zone": ctx.contract.geometry_zone, "outside_composition_zone": ctx.contract.composition_zone}
    for name in ("geometry_audit", "render_audit"):
        for finding in results.get(name, AuditResult(auditor=name)).findings:
            if finding.status != "fail" or finding.slide_id is None or ctx.slide(finding.slide_id).hidden:
                continue
            if finding.code in GEOMETRY_CODES:
                proposals.append({"finding": finding, "action": "move_inside", "zone": zones[finding.code]})
            elif finding.code in RENDER_CODES and "rendered_bottom" in finding.measurement:
                proposals.append({"finding": finding, "action": "grow_box",
                                  "bottom": finding.measurement["rendered_bottom"] + 2,
                                  "right": finding.measurement.get("rendered_right")})
    return proposals


def apply(pptx: Path, proposals: list[dict], ctx: AuditContext) -> list[dict]:
    """Aplica las propuestas sobre una copia del PPTX y devuelve lo que cambió."""
    if not proposals:
        return []
    presentation = Presentation(str(pptx))
    scale = presentation.slide_width / EMU / ctx.kn.tokens["canvas"]["width"]
    applied = []
    for proposal in proposals:
        finding = proposal["finding"]
        slide = presentation.slides[finding.slide_id - 1]
        shape = next((s for s in slide.shapes if s.name == finding.source_reference), None)
        if shape is None:
            continue
        current = _box(shape)
        box = Box(x=current.x / scale, y=current.y / scale, w=current.w / scale, h=current.h / scale)
        if proposal["action"] == "move_inside":
            left, top, right, bottom = proposal["zone"]
            if box.w > right - left or box.h > bottom - top:
                continue
            new = Box(x=min(max(box.x, left), right - box.w), y=min(max(box.y, top), bottom - box.h), w=box.w, h=box.h)
        else:
            limit = ctx.contract.composition_zone[3] if ctx.slide(finding.slide_id).redesigned else ctx.contract.geometry_zone[3]
            bottom = min(proposal["bottom"], limit)
            if bottom <= box.bottom + 0.5:
                continue
            new = Box(x=box.x, y=box.y, w=box.w, h=bottom - box.y)
        scaled = Box(x=new.x * scale, y=new.y * scale, w=new.w * scale, h=new.h * scale)
        if _collides(slide, shape, scaled):
            continue
        _set(shape, scaled)
        applied.append({
            "slide_id": finding.slide_id, "shape": shape.name, "code": finding.code, "action": proposal["action"],
            "before": box.model_dump(), "after": new.model_dump(),
        })
    if applied:
        presentation.save(str(pptx))
    return applied


def findings_key(result_map: dict[str, AuditResult]) -> set[tuple]:
    return {
        (f.check, f.code, f.slide_id, f.source_reference)
        for result in result_map.values() for f in result.findings if blocking(f.status)
    }


def group_findings(results: dict[str, AuditResult], previous: set[tuple] | None = None) -> list[dict]:
    """Hallazgos bloqueantes por familia y causa; con `previous`, solo el delta."""
    current = findings_key(results)
    groups: dict[tuple, dict] = defaultdict(lambda: {"slides": set(), "count": 0})
    for result in results.values():
        for finding in result.findings:
            key = (finding.check, finding.code, finding.slide_id, finding.source_reference)
            if not blocking(finding.status) or (previous is not None and key in previous):
                continue
            group = groups[(finding.family or "unregistered", finding.check, finding.code)]
            group["slides"].add(finding.slide_id)
            group["count"] += 1
            group.setdefault("symptom", finding.symptom)
            group.setdefault("proposal", finding.correction_proposed)
    delta = [
        {"family": family, "check": check, "code": code, "slides": sorted(s for s in g["slides"] if s),
         "count": g["count"], "symptom": g["symptom"], "proposal": g["proposal"]}
        for (family, check, code), g in sorted(groups.items())
    ]
    if previous is not None:
        resolved = previous - current
        delta.append({"resolved": len(resolved)})
    return delta


def repair_loop(
    candidate: Path, make_context: Callable[[Path], AuditContext],
    run: Callable[[AuditContext], dict[str, AuditResult]], *, max_rounds: int | None = None,
) -> tuple[RepairState, dict[str, AuditResult]]:
    """Rondas deterministas con suite completa entre cada una, hasta el presupuesto."""
    max_rounds = llmops()["workflow"]["max_deterministic_repair_rounds"] if max_rounds is None else max_rounds
    state = RepairState()
    ctx = make_context(candidate)
    results = run(ctx)
    while True:
        proposals = propose(ctx, results)
        if not proposals:
            break
        if state.rounds >= max_rounds:
            state.exhausted = True
            break
        before = findings_key(results)
        work = candidate.with_name(candidate.stem + f".repair{state.rounds + 1}.pptx")
        shutil.copy2(candidate, work)
        applied = apply(work, proposals, ctx)
        state.rounds += 1
        if not applied:
            work.unlink()
            state.ineffective += [{"code": p["finding"].code, "slide_id": p["finding"].slide_id,
                                   "shape": p["finding"].source_reference} for p in proposals]
            break
        ctx = make_context(work)
        results = run(ctx)
        after = findings_key(results)
        # La reparación solo cuenta si el hallazgo desaparece al reauditar los bytes nuevos.
        for item in applied:
            key = next((k for k in after if k[2] == item["slide_id"] and k[3] == item["shape"] and k[1] == item["code"]), None)
            (state.ineffective if key else state.applied).append(item)
        state.history.append({"round": state.rounds, "applied": len(applied), "delta": group_findings(results, before)})
        if after >= before:
            work.unlink()
            ctx = make_context(candidate)
            results = run(ctx)
            break
        shutil.move(str(work), candidate)
        ctx = make_context(candidate)  # mismos bytes que se acaban de auditar
    return state, results
