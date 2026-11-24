"""El plan de la skill: una decisión por slide que el motor convierte en su plan completo.

Es el mismo formato que usaba el MCP (`DeckPlanUpdate`), sin sus puertas: aquí nada se
rechaza por política. Solo se rechaza lo que el motor no puede dibujar (un id que no existe,
una familia o un layout que no están en el catálogo), con un mensaje que dice qué corregir.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from neo_refactor.schemas import (
    ASSET_CLASSES, STYLE_GROUPS, AnalysisPlan, CardRole, FreeLayout, KeepLayout, RuleException, StyleOverride,
    TextOverride,
)

NON_CONTENT_ROLES = ("decorative", "brand")
PENDIENTE = "needs_model_classification"


class PlanError(ValueError):
    """El plan no se puede aplicar: el mensaje dice qué corregir."""


class DecisionSlide(BaseModel):
    """Lo que Claude decide para una slide del original."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    slide: int = Field(description="Número de la slide en el original (1-based).")
    selected: bool = True
    family: str | None = None
    composition_layout: str | None = None
    variant: str | None = None
    # Matriz: columna destacada, 1-based tal como se ve (la de rótulos cuenta como 1).
    highlight_column: int | None = Field(default=None, ge=1)
    roles: dict[str, str] = Field(default_factory=dict)
    paragraph_roles: dict[str, list[CardRole]] = Field(default_factory=dict)
    split_parts: list[list[str]] | None = None
    # "keep": las capturas, gráficos y diagramas de esta slide conservan su fondo blanco.
    image_background: Literal["keep"] | None = None
    apply_to_group: bool = False
    keep_layout: str | None = None
    free_layout: FreeLayout | None = None
    style_overrides: list[StyleOverride] | None = None
    # Textos que la persona aprobó cambiar (título corto): `{"s3:t1": {"text", "reason"}}`.
    text_overrides: dict[str, TextOverride] | None = None
    # Cita de la persona que aprobó juntar los rótulos repetidos (cards → matriz).
    consolidate_labels: str | None = Field(default=None, max_length=240)
    rule_exceptions: list[RuleException] | None = None
    asset_classes: dict[str, str] = Field(default_factory=dict)
    evidence: str | None = Field(default=None, max_length=240)
    exclusion_reason: str | None = None


class PlanSkill(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slides: list[DecisionSlide]


def cargar(ruta: Path) -> PlanSkill:
    data = json.loads(ruta.read_text(encoding="utf-8"))
    if isinstance(data, list):
        data = {"slides": data}
    try:
        return PlanSkill.model_validate(data)
    except ValidationError as exc:
        problemas = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:8])
        raise PlanError(f"el plan no cumple el formato ({problemas})") from exc


def _asignar(assignment, decision: DecisionSlide):
    role = decision.roles.get(assignment.element_id)
    cambios: dict = {"paragraph_roles": decision.paragraph_roles.get(assignment.element_id, assignment.paragraph_roles)}
    if role in NON_CONTENT_ROLES:
        cambios.update(classification=role, role=None, paragraph_roles=[])
    elif role is not None:
        cambios.update(classification="content", role=role)
    return assignment.model_copy(update=cambios)


def _propagar(decision: DecisionSlide, slide, por_id: dict, manifest, saltar: set[str]) -> list[str]:
    """Lleva la decisión a las slides con la misma estructura (mismo `group_id`)."""
    aplicadas = []
    origen = [a for a in slide.assignments
              if manifest.slide(slide.source_slide_id).element(a.element_id).kind != "shape"]
    for otra in por_id.values():
        if otra is slide or otra.source_slide_id in saltar or otra.group_id != slide.group_id:
            continue
        if not manifest.slide(otra.source_slide_id).visible:
            continue
        otra.family, otra.selected_for_redesign = slide.family, slide.selected_for_redesign
        otra.composition_layout, otra.keep_layout = slide.composition_layout, slide.keep_layout
        destino = [a for a in otra.assignments
                   if manifest.slide(otra.source_slide_id).element(a.element_id).kind != "shape"]
        iguales = len(destino) == len(origen) and all(
            manifest.slide(otra.source_slide_id).element(b.element_id).kind
            == manifest.slide(slide.source_slide_id).element(a.element_id).kind
            for a, b in zip(origen, destino))
        if iguales:
            reemplazos = {b.element_id: b.model_copy(update={
                "classification": a.classification, "role": a.role, "paragraph_roles": list(a.paragraph_roles)})
                for a, b in zip(origen, destino)}
            otra.assignments = [reemplazos.get(a.element_id, a) for a in otra.assignments]
        aplicadas.append(otra.source_slide_id if iguales else f"{otra.source_slide_id} (sin roles: revísala)")
    return aplicadas


def aplicar(engine, manifest, plan_skill: PlanSkill) -> tuple[AnalysisPlan, dict]:
    """Plan del motor a partir de las decisiones. Las slides sin decisión quedan intactas."""
    plan = engine.default_plan(manifest)
    por_id = {s.source_slide_id: s for s in plan.slides}
    ids = {slide.index: slide.id for slide in manifest.slides}
    familias = set(engine.families())
    layouts = set(engine.layouts()) | {"free"}
    estilos = set(_roles_de_estilo(engine))
    decididas: set[str] = set()
    avisos: list[str] = []
    propagadas: list[str] = []
    for d in plan_skill.slides:
        sid = ids.get(d.slide)
        if sid not in por_id:
            raise PlanError(f"la slide {d.slide} no existe en el original ({len(por_id)} slides)")
        if not manifest.slide(sid).visible:
            raise PlanError(f"la slide {d.slide} está oculta: se conserva tal cual y no lleva decisión")
        s = por_id[sid]
        decididas.add(sid)
        s.selected_for_redesign = d.selected
        if d.family is not None:
            if d.family not in familias:
                raise PlanError(f"slide {d.slide}: familia desconocida «{d.family}» (mira `neo.py catalogo`)")
            s.family = d.family
        if d.composition_layout is not None:
            if d.composition_layout not in layouts:
                raise PlanError(f"slide {d.slide}: layout desconocido «{d.composition_layout}»")
            s.composition_layout = d.composition_layout
        if d.variant is not None:
            permitidas = engine.variants(s.family)
            if d.variant not in permitidas:
                raise PlanError(f"slide {d.slide}: la variante «{d.variant}» no existe para {s.family} "
                                f"({', '.join(permitidas) or 'sin variantes'})")
            s.archetype = d.variant
        if d.highlight_column is not None:
            s.highlight_column = d.highlight_column
        if d.image_background is not None:
            s.image_background = d.image_background
        if d.split_parts is not None:
            s.split_parts = d.split_parts
        if d.roles or d.paragraph_roles:
            conocidos = {a.element_id for a in s.assignments}
            faltan = sorted((set(d.roles) | set(d.paragraph_roles)) - conocidos)
            if faltan:
                raise PlanError(f"slide {d.slide}: elementos inexistentes {', '.join(faltan)} "
                                f"(los ids salen de `neo.py leer`)")
            s.assignments = [_asignar(a, d) for a in s.assignments]
        if d.rule_exceptions is not None:
            s.rule_exceptions = list(d.rule_exceptions)
        if d.free_layout is not None:
            s.free_layout, s.composition_layout, s.keep_layout = d.free_layout, "free", None
        if d.keep_layout is not None:
            texto = d.keep_layout.strip()
            s.keep_layout = KeepLayout(reason=texto if len(texto) >= 3 else "mantener su organización") if texto else None
            if s.keep_layout:
                s.selected_for_redesign, s.free_layout = True, None
                if s.family == PENDIENTE:
                    # Con keep_layout la familia solo marca la slide: no elige composición.
                    s.family = "benefits_content"
        if d.style_overrides is not None:
            malos = sorted({o.target for o in d.style_overrides if o.target not in STYLE_GROUPS
                            and not any(o.matches(r) for r in estilos)})
            if malos:
                raise PlanError(f"slide {d.slide}: style_overrides con destino desconocido {', '.join(malos)}")
            s.style_overrides = list(d.style_overrides)
        if d.text_overrides is not None:
            textos = {e.id for e in manifest.slide(sid).elements if e.kind == "text"}
            malos = sorted(set(d.text_overrides) - textos)
            if malos:
                raise PlanError(f"slide {d.slide}: text_overrides solo acepta textos de la slide "
                                f"({', '.join(malos)}; los ids salen de `neo.py leer`)")
            s.text_overrides = dict(d.text_overrides)
        if d.consolidate_labels is not None:
            s.consolidate_labels = d.consolidate_labels.strip() or None
        if d.asset_classes:
            imagenes = {e.id for e in manifest.slide(sid).elements if e.kind == "image"}
            malos = sorted(set(d.asset_classes) - imagenes)
            clases = sorted({v for v in d.asset_classes.values() if v not in ASSET_CLASSES})
            if malos:
                raise PlanError(f"slide {d.slide}: asset_classes solo acepta imágenes ({', '.join(malos)})")
            if clases:
                raise PlanError(f"clase de imagen desconocida {', '.join(clases)}; válidas: {', '.join(ASSET_CLASSES)}")
            s.asset_classes = {**s.asset_classes, **d.asset_classes}
        if d.evidence:
            s.evidence = d.evidence
        if not s.selected_for_redesign:
            s.exclusion_reason = d.exclusion_reason or "se conserva tal cual"
        else:
            s.exclusion_reason = None
            if s.family == PENDIENTE:
                raise PlanError(f"slide {d.slide}: falta `family` (o usa keep_layout para conservar su organización)")
    for d in plan_skill.slides:
        s = por_id[ids[d.slide]]
        if d.apply_to_group and s.group_id:
            propagadas += _propagar(d, s, por_id, manifest, decididas)
            decididas |= {p.split()[0] for p in propagadas}
    parcial = False
    for s in plan.slides:
        if s.source_slide_id not in decididas and manifest.slide(s.source_slide_id).visible:
            s.selected_for_redesign, s.exclusion_reason, parcial = False, "fuera del alcance de este pedido", True
    try:
        plan = AnalysisPlan.model_validate(plan.model_dump())
    except ValidationError as exc:
        problemas = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:6])
        raise PlanError(f"el plan resultante no es válido ({problemas})") from exc
    return plan, {"parcial": parcial, "propagadas": propagadas, "avisos": avisos}


def _roles_de_estilo(engine) -> list[str]:
    from neo_refactor.knowledge import Knowledge

    return list(Knowledge(engine.knowledge_root).tokens["styles"]["light"])
