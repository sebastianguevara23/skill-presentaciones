"""`plan_fulfillment_audit`: cada compromiso de la revisión aprobada, en el PPTX final.

Por slide del plan comprueba, con la marca que el motor dejó en los bytes (no con el
reporte del render):

- `treatment`: una seleccionada salió rediseñada (nunca `brand_shell`), con su
  familia, layout, variante y el número de partes del plan; una excluida no se
  rediseñó; una oculta sigue oculta y sin tocar. La excepción es `keep_layout`: la
  persona pidió conservar el layout y solo corregir el estilo, y entonces lo que se
  exige es justamente el brand shell con la variante `keep_layout`.
- `content`: el estado de integridad de contenido de sus slides de salida.
- `directive`: cada directiva visual es cualitativa: exige que el host la compare
  en la preview y la registre; sin ese registro queda `not_run` y bloquea.
- los criterios de aceptación congelados (`PlanCommitment`): cada tipo se resuelve
  con su auditor sobre las slides de salida; `custom` pide revisión del host.
"""
from __future__ import annotations

from ..plan_adapter import effective_layout
from .core import AuditContext, AuditResult, Finding, not_run, worst
from .visual import preview_key

AUDITOR = "plan_fulfillment_audit"
# Portada clara y despedida canónica: política universal (2026-09-30) que manda sobre el plan.
# Se aplican aunque la slide esté excluida o el pedido sea parcial, así que no son un desvío.
UNIVERSAL_POLICY_VARIANTS = {"light_cover", "canonical_light_farewell"}


def _universal_policy(slide) -> bool:
    return (slide.marker or {}).get("variant") in UNIVERSAL_POLICY_VARIANTS
SUBCHECKS = ("treatment", "content", "directive", "criteria")
CRITERION_AUDITOR = {
    "content_integrity": "content_integrity",
    "geometry": "geometry_audit",
    "render": "render_audit",
    "visual_quality": "visual_quality_audit",
    "style_integrity": "style_integrity_audit",
}


def audit(ctx: AuditContext, results: dict) -> AuditResult:
    slide_ids = [slide.index for slide in ctx.slides]
    if ctx.plan is None:
        return not_run(AUDITOR, "sin revisión aprobada no hay compromisos que comprobar", slide_ids, SUBCHECKS)
    result = AuditResult(auditor=AUDITOR)
    reviewed: dict[str, str] = {}
    current = {preview_key(ctx, slide.index) for slide in ctx.slides}
    for review in ctx.reviews:
        if review.preview_key in current:  # una revisión de otros bytes no prueba estos
            reviewed.update(review.commitments)
    mapping = {entry.source_slide_id: entry for entry in ctx.mapping.slides}
    criteria = {
        (commitment.source_slide_id, criterion_id): commitment
        for commitment in ctx.plan.commitments for criterion_id in commitment.criterion_ids
    }

    for plan_slide in ctx.plan.plan.slides:
        sid = plan_slide.source_slide_id
        entry = mapping.get(sid)
        outputs = [ctx.slide(i) for i in (entry.output_slide_indices if entry else []) if i <= len(ctx.slides)]
        anchor = outputs[0].index if outputs else None

        def record(commitment_id, subcheck, status, evidence, code=None, symptom=None):
            result.records.append({
                "commitment": commitment_id, "source_slide_id": sid, "kind": subcheck,
                "output_slides": [s.index for s in outputs], "status": status, "evidence": evidence,
            })
            if status != "pass":
                result.findings.append(Finding(
                    check=AUDITOR, subcheck=subcheck, code=code or f"{subcheck}_{status}", status=status,
                    slide_id=anchor, source_slide_id=sid, family=plan_slide.family, source_reference=commitment_id,
                    symptom=symptom or evidence, measurement={"output_slides": [s.index for s in outputs]},
                    cause="el PPTX final no muestra el compromiso de la revisión aprobada",
                    correction_proposed="recomponer la slide según la revisión o aprobar una revisión nueva",
                    acceptance="el compromiso se comprueba en el PPTX reabierto",
                ))

        if not outputs:
            record(f"{sid}:treatment", "treatment", "fail", "la slide no tiene salida en el PPTX", "slide_missing")
            continue

        # ---- tratamiento
        if plan_slide.family == "hidden" or not ctx.source.slide(sid).visible:
            ok = all(s.hidden and s.marker is None for s in outputs) and len(outputs) == 1
            record(f"{sid}:treatment", "treatment", "pass" if ok else "fail",
                   "oculta e intacta" if ok else "la oculta cambió de visibilidad o fue rediseñada",
                   "hidden_changed")
        elif not plan_slide.selected_for_redesign:
            ok = all(not s.redesigned or _universal_policy(s) for s in outputs)
            record(f"{sid}:treatment", "treatment", "pass" if ok else "fail",
                   f"excluida ({plan_slide.exclusion_reason})" if ok else "una slide excluida salió rediseñada",
                   "excluded_redesigned")
        elif plan_slide.keep_layout:
            # La persona pidió conservar su organización: el compromiso es el brand shell
            # encajado en el marco, con la marca de que fue a pedido (no un fallback).
            ok = len(outputs) == 1 and all(
                _universal_policy(s) or (s.mode == "brand_shell" and (s.marker or {}).get("variant") == "keep_layout")
                for s in outputs)
            record(f"{sid}:treatment", "treatment", "pass" if ok else "fail",
                   f"layout conservado a pedido: «{plan_slide.keep_layout.reason}»" if ok
                   else "la slide no salió con su layout conservado", "keep_layout_not_applied")
        else:
            expected_parts = max(1, len(plan_slide.split_parts))
            layout = effective_layout(plan_slide, ctx.kn)
            problems = []
            if len(outputs) != expected_parts:
                problems.append(f"{len(outputs)} slides de salida para {expected_parts} partes")
            for number, slide in enumerate(outputs, 1):
                marker = slide.marker or {}
                if _universal_policy(slide):
                    continue  # portada clara o despedida canónica: política universal, manda sobre el plan
                if slide.mode != "redesign":
                    problems.append(f"slide {slide.index} en {slide.mode}")
                    continue
                for key, want in (("source", sid), ("family", plan_slide.family), ("layout", layout),
                                  ("variant", plan_slide.archetype), ("part", number), ("parts", expected_parts)):
                    if marker.get(key) != want:
                        problems.append(f"slide {slide.index}: {key}={marker.get(key)!r}, plan={want!r}")
            code = "selected_slide_brand_shell" if any(s.mode == "brand_shell" for s in outputs) else "approved_change_missing"
            record(f"{sid}:treatment", "treatment", "fail" if problems else "pass",
                   "; ".join(problems) or f"{plan_slide.family}/{layout} en {len(outputs)} parte(s)", code)
            if layout == "free" and plan_slide.free_layout is not None and not problems:
                _free_components(ctx, plan_slide, outputs, record)

        # ---- contenido
        content = results.get("content_integrity")
        if content is None:
            record(f"{sid}:content", "content", "not_run", "integridad de contenido sin ejecutar")
        else:
            status = worst(content.slides.get(s.index, "not_run") for s in outputs)
            status = "pass" if status == "warning" else status
            record(f"{sid}:content", "content", status, f"integridad de contenido: {status}", "content_not_preserved")

        # ---- directivas visuales: solo las confirma el host sobre la preview
        for number, directive in enumerate(plan_slide.visual_directives, 1):
            commitment_id = f"{sid}:directive:{number}"
            verdict = reviewed.get(commitment_id)
            record(commitment_id, "directive", verdict or "not_run",
                   f"{directive.kind}: {directive.instruction}" if verdict else
                   f"sin comparación visual del host: {directive.instruction}",
                   "directive_not_met" if verdict == "fail" else "directive_not_reviewed")

        # ---- criterios de aceptación congelados
        for criterion in plan_slide.acceptance_criteria:
            commitment = criteria.get((sid, criterion.id))
            commitment_id = commitment.id if commitment else f"{sid}:{criterion.id}"
            if criterion.kind == "family":
                treatment = next(r for r in result.records if r["commitment"] == f"{sid}:treatment")
                record(commitment_id, "criteria", treatment["status"], criterion.description, "family_not_met")
            elif criterion.kind in CRITERION_AUDITOR:
                audited = results.get(CRITERION_AUDITOR[criterion.kind])
                status = "not_run" if audited is None else worst(
                    audited.slides.get(s.index, "not_run") for s in outputs
                )
                status = "pass" if status == "warning" else status
                record(commitment_id, "criteria", status, f"{criterion.kind}: {criterion.description}",
                       "criterion_not_met")
            else:
                verdict = reviewed.get(commitment_id)
                record(commitment_id, "criteria", verdict or "not_run", criterion.description,
                       "criterion_not_met" if verdict == "fail" else "criterion_not_reviewed")

    return result.finish(slide_ids, SUBCHECKS)


def _free_components(ctx: AuditContext, plan_slide, outputs, record) -> None:
    """Composición libre: lo dibujado cumple la gramática del plan (qué componentes y cuántos)."""
    import re
    from collections import Counter

    from ..free_layout import DRAWN_ALIASES, DRAWN_ROLE, expected_components
    from .geometry import elements

    expected = expected_components(plan_slide)
    names = sorted(set(DRAWN_ROLE.values()) | set(DRAWN_ALIASES), key=len, reverse=True)
    pattern = re.compile(rf"^({'|'.join(names)})_\d+$")
    drawn: Counter = Counter()
    for slide in outputs:
        for name, _kind, _box, _block in elements(ctx, slide.index):
            match = pattern.match(name)
            if match:
                drawn[DRAWN_ALIASES.get(match[1], match[1])] += 1
    missing = {role: count for role, count in expected.items() if drawn[role] != count}
    sid = plan_slide.source_slide_id
    evidence = ", ".join(f"{role} {drawn[role]}/{count}" for role, count in sorted(expected.items()))
    record(f"{sid}:free_layout", "treatment", "fail" if missing else "pass",
           f"composición libre: {evidence}", "free_layout_not_followed",
           None if not missing else "lo dibujado no sigue la composición libre del plan: " + evidence)

