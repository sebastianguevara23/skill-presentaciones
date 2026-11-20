"""`visual_quality_audit`: señales medibles + revisión del modelo del host.

La geometría no ve aire, balance ni jerarquía. Este auditor combina:

1. Señales medibles sobre los bytes (aviso, y obligan a revisar la slide a tamaño
   completo): media slide vacía bajo el contenido (`visually_unbalanced`), texto
   pegado al borde de su card (`visually_cramped`) y partes de una partición con
   pesos muy distintos (`split_unbalanced`).
2. La revisión del host de **todas** las slides de salida, en lotes que respetan
   `config/llmops.yaml`. Cada revisión se ata a la preview de estos bytes
   (`preview_key`, huella por slide): si esa slide cambia, deja de valer; si cambia otra o se
   mueve de posición (una partición desplaza los índices), sigue valiendo: una iteración solo
   obliga a revisar lo modificado. Sin revisión, con preview
   ilegible o sin la vista individual que pide una señal, el estado es `not_run`.
   Una heurística o el reconocimiento de familia nunca sustituyen la revisión.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import pymupdf
import yaml

from ..knowledge import ROOT
from ..renderer import BRAND_PREFIX
from ..schemas import Box
from .core import AuditContext, AuditResult, Finding, not_run
from .geometry import elements, is_background, role_of
from .render import rendered_pdf

AUDITOR = "visual_quality_audit"
SUBCHECKS = ("signals", "host_review")
EMPTY_BAND = 0.42      # fracción de la altura de composición vacía bajo el contenido
MIN_PADDING = 3.0      # pt entre texto y borde de su card (el matrix compone a 3 pt)
LABEL_COVER = 0.8      # un texto que ocupa ≥80 % de un eje de su forma se centra en ella
BADGE = 30.0           # pt: forma pequeña (paso numerado) que solo lleva un rótulo
SPLIT_RATIO = 0.5      # alto de contenido de la parte más ligera frente a la más pesada


def llmops(root: Path = ROOT) -> dict:
    return yaml.safe_load((root / "config" / "llmops.yaml").read_text())


def preview_key(ctx: AuditContext, index: int) -> str:
    """Huella de lo que pinta la slide: una slide intacta conserva su clave aunque cambie de posición."""
    return ctx.slide_digests[index][:24]


def previews(ctx: AuditContext, indices: list[int] | None = None) -> list[dict]:
    """JPEG por slide al ancho de `llmops.yaml`, bajo el tope de bytes por preview."""
    config = llmops(ctx.knowledge_root)["model_context"]
    pdf = rendered_pdf(ctx)
    if pdf is None:
        return []
    document = pymupdf.open(pdf)
    try:
        chosen = indices or list(range(1, len(document) + 1))
        result = []
        for index in chosen:
            page = document[index - 1]
            scale = config["preview_width_px"] / page.rect.width
            pixmap = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
            quality, data = 85, b""
            while quality >= 40:
                data = pixmap.tobytes("jpeg", jpg_quality=quality)
                if len(data) <= config["max_preview_jpeg_bytes"]:
                    break
                quality -= 10
            result.append({"slide_id": index, "preview_key": preview_key(ctx, index), "jpeg": data})
        return result
    finally:
        document.close()


def needs_review(ctx: AuditContext) -> list[int]:
    """Slides del alcance sin una revisión válida de sus bytes actuales, con el mismo criterio
    que `audit`: falta, ilegible, o hecha en lote cuando una señal pide verla individual."""
    by_key = {review.preview_key: review for review in ctx.reviews}
    flagged = {finding.slide_id for finding in signals(ctx)} if ctx.reviews else set()
    pending = []
    for slide in ctx.slides:
        if not ctx.in_scope(slide.index):
            continue
        review = by_key.get(preview_key(ctx, slide.index))
        if review is None or not review.legible or (slide.index in flagged and not review.individual):
            pending.append(slide.index)
    return pending


def review_batches(ctx: AuditContext) -> list[list[int]]:
    """Lotes solo con lo que falta revisar (fase 4): tras iterar una slide, o al retomar un
    trabajo a medio revisar, no se vuelven a leer previews que ya tienen revisión válida."""
    size = llmops(ctx.knowledge_root)["model_context"]["max_previews_per_batch"]
    indices = needs_review(ctx)
    return [indices[start:start + size] for start in range(0, len(indices), size)]


def signals(ctx: AuditContext) -> list[Finding]:
    kn = ctx.kn
    width, height = kn.tokens["canvas"]["width"], kn.tokens["canvas"]["height"]
    limit = kn.tokens["margins"]["bottom_limit"]
    top = ctx.contract.brand_zone[1]
    found: list[Finding] = []
    content_height: dict[int, float] = {}

    def add(slide, code, symptom, reference=None, **measurement):
        found.append(Finding(
            check=AUDITOR, subcheck="signals", code=code, status="warning", slide_id=slide.index,
            source_slide_id=slide.source_slide_id, family=slide.family, source_reference=reference,
            symptom=symptom, measurement=measurement, cause="señal medible de composición",
            correction_proposed="revisar la preview individual; redistribuir o ampliar si se confirma",
            acceptance="la revisión individual del host la aprueba o la composición cambia",
        ))

    for slide in ctx.slides:
        if not slide.redesigned:
            continue
        if slide.layout == "free":
            # Una organización nueva no tiene referencia aprobada contra la cual medir: siempre se
            # revisa a tamaño completo (plans/composicion-libre.md, F4).
            add(slide, "free_composition", "composición libre: se revisa a tamaño completo")
        items = [
            (name, kind, box) for name, kind, box, _block in elements(ctx, slide.index)
            if not name.startswith(BRAND_PREFIX) and not is_background(box, name, width, height)
            and role_of(name) != "note"
        ]
        if not items:
            continue
        bottom = max(box.bottom for _n, _k, box in items)
        upper = min(box.y for _n, _k, box in items)
        content_height[slide.index] = bottom - upper
        if (limit - bottom) > EMPTY_BAND * (limit - top):
            add(slide, "visually_unbalanced", "más de 40 % de la zona de composición vacía bajo el contenido",
                content_bottom=round(bottom, 1), limit=limit)
        cards = [(name, box) for name, kind, box in items if kind == "shape"]
        for name, kind, box in items:
            if kind != "text":
                continue
            parents = [c for c in cards if c[1].contains(box) and c[0] != name]
            if not parents:
                continue
            pname, pbox = min(parents, key=lambda item: item[1].w * item[1].h)
            if max(pbox.w, pbox.h) <= BADGE:
                continue  # un número dentro de un círculo pequeño es una insignia, no una card
            # Un eje en el que la caja ocupa toda la forma es un rótulo centrado en ella
            # (número en un círculo, texto de una etiqueta): el aire lo da el anclaje.
            gaps = []
            if box.w < LABEL_COVER * pbox.w:
                gaps += [box.x - pbox.x, pbox.right - box.right]
            if box.h < LABEL_COVER * pbox.h:
                gaps += [box.y - pbox.y, pbox.bottom - box.bottom]
            padding = min(gaps, default=MIN_PADDING)
            if padding < MIN_PADDING:
                add(slide, "visually_cramped", f"texto a {padding:.1f} pt del borde de {pname}", name,
                    padding=round(padding, 1), parent=pname)

    parts: dict[str, list[int]] = defaultdict(list)
    for slide in ctx.slides:
        if slide.redesigned and slide.source_slide_id:
            parts[slide.source_slide_id].append(slide.index)
    for indices in parts.values():
        heights = [content_height[i] for i in indices if i in content_height]
        if len(heights) > 1 and min(heights) < SPLIT_RATIO * max(heights):
            lightest = indices[heights.index(min(heights))]
            add(ctx.slide(lightest), "split_unbalanced", "una parte de la partición pesa mucho menos que otra",
                heights=[round(h, 1) for h in heights], parts=indices)
    return found


def audit(ctx: AuditContext) -> AuditResult:
    slide_ids = [slide.index for slide in ctx.slides]
    if rendered_pdf(ctx) is None:
        return not_run(AUDITOR, "sin render no hay previews que revisar", slide_ids, SUBCHECKS)
    result = AuditResult(auditor=AUDITOR)
    result.findings.extend(signals(ctx))
    flagged = {finding.slide_id for finding in result.findings}
    # Se busca la revisión de los bytes actuales, no la última registrada: al volver a un
    # diseño anterior, su revisión ya existe y no es la más reciente de la lista.
    by_key = {review.preview_key: review for review in ctx.reviews}
    codes = set(yaml.safe_load((ctx.knowledge_root / "design_knowledge" / "slide_families.yaml").read_text())
                ["audit_contract"]["visual_quality_failure_codes"])
    for slide in ctx.slides:
        if not ctx.in_scope(slide.index):
            continue  # intacta: no hay nada nuevo que revisar
        review = by_key.get(preview_key(ctx, slide.index))

        def add(code, status, symptom, cause, **measurement):
            result.findings.append(Finding(
                check=AUDITOR, subcheck="host_review", code=code, status=status, slide_id=slide.index,
                source_slide_id=slide.source_slide_id, family=slide.family, symptom=symptom,
                measurement=measurement, cause=cause,
                correction_proposed=None if status == "not_run" else "recomponer según las notas del host",
                acceptance="revisión del host en pass sobre la preview de estos bytes",
            ))

        if review is None or review.preview_key != preview_key(ctx, slide.index):
            add("visual_review_missing", "not_run", "la slide no tiene revisión visual de estos bytes",
                "falta la revisión del host o es de otra versión del PPTX")
        elif not review.legible:
            add("preview_illegible", "not_run", "el host no pudo leer la preview con detalle suficiente",
                "resolución o densidad de la preview")
        elif slide.index in flagged and not review.individual:
            add("individual_review_required", "not_run", "una señal pide revisar la preview individual",
                "se revisó solo en lote")
        elif review.status == "fail":
            unknown = sorted(set(review.codes) - codes)
            add(next((code for code in review.codes if code in codes), "visual_quality_fail"), "fail",
                review.notes or "el host rechazó la composición", "revisión visual del host",
                codes=review.codes, unregistered_codes=unknown)
    ctx.apply_exceptions(result)
    return result.finish(slide_ids, SUBCHECKS)
