"""Integridad de contenido contra el manifiesto de origen, sobre los bytes finales.

Por cada slide de origen se reúnen sus slides de salida (el mapa origen→salida) y se
comparan, cada uno con su estado:

- `text` y `numbers`: palabras y cifras; el marco que una partición repite (título,
  kicker) se descuenta tantas veces como el mapa lo declara.
- `images`: cada imagen de contenido está en su salida, idéntica o recodificada por
  `optimize.py` (misma imagen a la vista: se compara en miniatura). Un GIF animado
  debe conservar cuadros y duraciones.
- `links` y `notes`: enlaces de texto y relaciones externas; notas del orador. Un enlace
  que el autor partió en varios runs seguidos cuenta una vez: al componer se unen.
- `emoji`: ninguna slide visible de salida conserva emojis (convenciones: el diseño pone
  sus propios íconos; en Montserrat salen como □). Las palabras se comparan sin emojis.
- `split_duplication`: tras partir, un bloque común vive en una sola parte; solo el
  marco (`REPEATED_IN_PARTS`: título, kicker, encabezados de tabla…) se repite.
- `visibility`: una oculta sigue oculta y una visible sigue visible.

Lo retirado a propósito (decorativo y marca antigua según la revisión aprobada, o un
logo antiguo conocido en una slide conservada) se registra como excepción con su
condición y referencia; nunca pasa en silencio.
"""
from __future__ import annotations

from collections import Counter
from functools import lru_cache
from hashlib import md5, sha256
import io
from pathlib import Path
import re

from PIL import Image

from ..cleanup import EMOJI, strip_emojis
from ..icon_tint import same_glyph
from ..parser import parse_deck
from ..plan_adapter import REPEATED_IN_PARTS, absorbs_brand_phrase
from ..renderer import BRAND_PREFIX
from .core import AuditContext, AuditResult, Finding

AUDITOR = "content_integrity"
SUBCHECKS = ("text", "numbers", "images", "links", "notes", "emoji", "split_duplication", "visibility")
_NUM = re.compile(r"\d+(?:[.,]\d+)*\s?%?")
_WS = re.compile(r"\s+")
PERCEPTUAL_TOLERANCE = 8.0


def _norm(text: str) -> str:
    return _WS.sub(" ", strip_emojis(text)).strip()


def _words(texts) -> Counter:
    return Counter(word for text in texts for word in _norm(text).split() if any(ch.isalnum() for ch in word))


def _link_spans(links) -> list[str]:
    """Un enlace partido en runs seguidos es un solo enlace (el compositor une esos runs)."""
    spans: list[str] = []
    for link in links:
        if link and (not spans or spans[-1] != link):
            spans.append(link)
    return spans


def _numbers(texts) -> Counter:
    return Counter(match.replace(" ", "") for text in texts for match in _NUM.findall(_norm(text)))


@lru_cache(maxsize=512)
def _flat(path: str) -> Image.Image:
    """Primer cuadro sobre blanco: la transparencia se compara como se ve en la slide."""
    with Image.open(path) as image:
        image.seek(0)
        rgba = image.convert("RGBA")
        base = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        base.alpha_composite(rgba)
        return base.convert("RGB")


def _thumb(path: str, size: int = 48):
    image = _flat(path)
    return image.resize((size, size), Image.LANCZOS).tobytes(), image.width / max(1, image.height)


def animation(path: str) -> tuple[int, tuple[int, ...]] | None:
    """(cuadros, duraciones) de un GIF animado; None si es una imagen fija."""
    with Image.open(path) as image:
        frames = getattr(image, "n_frames", 1)
        if frames <= 1:
            return None
        durations = []
        for frame in range(frames):
            image.seek(frame)
            durations.append(int(image.info.get("duration", 0)))
        return frames, tuple(durations)


def same_picture(a: str, b: str) -> float | None:
    """Diferencia media por canal en miniatura; None si no es la misma imagen a la vista."""
    # Se compara a la menor resolución de las dos (máximo 48 px): un ícono reducido a
    # su tamaño de uso no se amplía para buscarle diferencias que no se ven.
    size = max(8, min(48, *_flat(a).size, *_flat(b).size))
    thumb_a, ratio_a = _thumb(a, size)
    thumb_b, ratio_b = _thumb(b, size)
    if abs(ratio_a - ratio_b) > 0.03 * max(ratio_a, ratio_b):
        return None
    diff = sum(abs(x - y) for x, y in zip(thumb_a, thumb_b)) / len(thumb_a)
    return diff if diff <= PERCEPTUAL_TOLERANCE else None


def _sha(path: str) -> str:
    return sha256(Path(path).read_bytes()).hexdigest()


def audit(ctx: AuditContext) -> AuditResult:
    result = AuditResult(auditor=AUDITOR)
    source_deck = None
    source_path = ctx.source_path
    if source_path is not None:
        if sha256(Path(source_path).read_bytes()).hexdigest() != ctx.source.source_hash:
            raise ValueError("el PPTX de origen no corresponde al manifiesto")
        media = ctx.workspace / "audit-media" / f"source-{ctx.source.source_hash[:16]}"
        media.mkdir(parents=True, exist_ok=True)
        source_deck = parse_deck(Path(source_path), media)
    old_logos = tuple(ctx.kn.tokens["brand"]["known_logos"]["old"])
    revision_id = ctx.plan.id if ctx.plan else None

    for entry in ctx.mapping.slides:
        source = ctx.source.slide(entry.source_slide_id)
        outputs = [ctx.slide(index) for index in entry.output_slide_indices if index <= len(ctx.slides)]
        if len(outputs) != len(entry.output_slide_indices):
            result.findings.append(Finding(
                check=AUDITOR, subcheck="text", code="output_slide_missing", status="fail",
                source_slide_id=source.id, symptom="el mapa apunta a slides que el PPTX no tiene",
                cause="salida incompleta", acceptance="cada destino del mapa existe",
                measurement={"expected": entry.output_slide_indices, "slides": len(ctx.slides)},
            ))
            continue
        first = outputs[0]
        if first.family == "closing_slide" and (first.marker or {}).get("brand_generated"):
            result.exceptions_applied.append({"check": AUDITOR, "slide_id": first.index,
                "condition": "despedida universal autorizada por el usuario, Referencia v2, slide 32",
                "reference": "tokens.yaml → brand_rules.closing"})
            continue
        plan_slide = ctx.plan_slides.get(source.id)
        classes = {a.element_id: a for a in plan_slide.assignments} if plan_slide else {}
        redesigned = any(slide.redesigned for slide in outputs)
        source_images = {img.id: img for img in source_deck.slide(source.index).images} if source_deck else {}

        def add(subcheck, code, symptom, cause, acceptance, *, status="fail", slide=first, reference=None,
                correction=None, **measurement):
            result.findings.append(Finding(
                check=AUDITOR, subcheck=subcheck, code=code, status=status, slide_id=slide.index,
                source_slide_id=source.id, family=slide.family, source_reference=reference,
                symptom=symptom, cause=cause, acceptance=acceptance, correction_proposed=correction,
                measurement=measurement,
            ))

        def removed_on_purpose(element) -> dict | None:
            if first.index == 1 and element.kind == "image" and element.local_id in source_images:
                image = source_images[element.local_id]
                if image.box.w*image.box.h >= ctx.source.width*ctx.source.height*0.9 or (
                    image.box.w < ctx.source.width*0.3 and image.box.y < ctx.source.height*0.2):
                    return {"element": element.id, "condition": "fondo y logo de portada light obligatoria",
                            "reference": "tokens.yaml → brand_rules.cover_mode"}
            assignment = classes.get(element.id)
            if redesigned and assignment and absorbs_brand_phrase(assignment, element, ctx.kn):
                return {"element": element.id, "condition": "frase de marca del autor: la reemplaza el pie de marca",
                        "reference": "tokens.yaml → brand.phrase"}
            if redesigned and assignment and assignment.classification in ("decorative", "brand"):
                return {"element": element.id, "condition": f"clasificado {assignment.classification} en el plan",
                        "reference": revision_id or "plan"}
            if element.kind == "image" and element.local_id in source_images:
                digest = md5(Path(source_images[element.local_id].path).read_bytes()).hexdigest()
                if digest.startswith(old_logos):
                    return {"element": element.id, "condition": "logo antiguo conocido (tokens.brand.known_logos.old)",
                            "reference": "design_knowledge/tokens.yaml"}
            return None

        expected = []
        for element in source.elements:
            if element.kind == "shape":
                continue
            exception = removed_on_purpose(element)
            if exception:
                result.exceptions_applied.append({**exception, "check": AUDITOR, "slide_id": first.index})
            else:
                expected.append(element)
        texts = [e for e in expected if e.kind == "text"]
        images = [e for e in expected if e.kind == "image"]
        specs = [ctx.deck.slide(slide.index) for slide in outputs]
        out_blocks = [(slide, block) for slide, spec in zip(outputs, specs) for block in spec.texts
                      if not block.name.startswith(BRAND_PREFIX)]

        # ---- texto y cifras: el marco repetido se descuenta tantas veces como se declara
        source_texts = [p for e in texts for p in e.paragraphs]
        output_texts = [p.text for _slide, block in out_blocks for p in block.paragraphs]
        out_words, out_numbers = _words(output_texts), _numbers(output_texts)
        for element in texts:
            copies = len(entry.element_destinations.get(element.id, [])) - 1
            if copies > 0:
                out_words -= Counter({w: c * copies for w, c in _words(element.paragraphs).items()})
                out_numbers -= Counter({n: c * copies for n, c in _numbers(element.paragraphs).items()})
        src_words, src_numbers = _words(source_texts), _numbers(source_texts)
        removed, added = src_words - out_words, out_words - src_words
        if removed:
            add("text", "content_removed", f"{sum(removed.values())} palabras del origen no están en la salida",
                "contenido perdido al componer", "cada palabra del origen está en su salida",
                correction="reasignar el bloque a un slot o partir la slide", words=sorted(removed)[:20])
        if added:
            add("text", "content_added", f"{sum(added.values())} palabras nuevas o duplicadas",
                "texto que el origen no tiene", "la salida no agrega texto",
                correction="quitar la copia o el texto inventado", words=sorted(added)[:20])
        if src_numbers != out_numbers:
            add("numbers", "numeric_change", "las cifras cambiaron", "cifra perdida, duplicada o alterada",
                "las cifras del origen se conservan exactas",
                missing=sorted((src_numbers - out_numbers).elements())[:20],
                extra=sorted((out_numbers - src_numbers).elements())[:20])

        # ---- enlaces: de texto y relaciones externas
        want_links = Counter(link for e in texts for link in _link_spans(e.hyperlinks))
        have_links = Counter(link for _slide, block in out_blocks for link in _link_spans(
            run.hyperlink for p in block.paragraphs for run in p.runs))
        external = {rel.target for rel in source.relationships if rel.external and rel.kind == "hyperlink"}
        have_external = {
            rel.target_ref for slide in outputs
            for rel in ctx.presentation.slides[slide.index - 1].part.rels.values() if rel.is_external
        }
        lost_links = sorted((want_links - have_links).elements()) + sorted(external - have_external - set(want_links))
        if lost_links:
            add("links", "link_lost", f"{len(lost_links)} enlaces del origen no están en la salida",
                "el enlace no se copió al componer", "cada enlace del origen sigue activo",
                correction="copiar el hipervínculo al run de destino", links=lost_links[:10])

        # ---- emojis: la regla de marca vale para toda slide visible de salida
        for slide, block in out_blocks:
            found = EMOJI.findall(block.text)
            if found and not slide.hidden:
                add("emoji", "emoji_kept", f"{len(found)} emoji(s) en la salida",
                    "el texto no pasó por la limpieza de marca", "ninguna slide visible conserva emojis",
                    slide=slide, reference=block.name, correction="quitar el emoji y el espacio que lo sigue",
                    emojis="".join(found)[:20])

        # ---- notas del orador
        want_notes = _norm(source.notes)
        notes_slides = [ctx.presentation.slides[i - 1] for i in entry.notes_output_indices if i <= len(ctx.slides)]
        have_notes = [
            _norm(s.notes_slide.notes_text_frame.text) if s.has_notes_slide and s.notes_slide.notes_text_frame else ""
            for s in notes_slides
        ]
        if want_notes and want_notes not in have_notes:
            add("notes", "notes_lost", "las notas del orador no se conservaron", "notas perdidas o alteradas",
                "las notas del origen están intactas en su salida")

        # ---- visibilidad
        for slide in outputs:
            if slide.hidden != (not source.visible):
                add("visibility", "hidden_state_changed", "la visibilidad de la slide cambió",
                    "una oculta se mostró o una visible se ocultó", "misma visibilidad que el origen", slide=slide)

        # ---- imágenes
        if images:
            _images(ctx, result, add, images, source_images, outputs, specs)

        # ---- duplicación tras partir
        if len(outputs) > 1:
            roles = {a.element_id: (a.role or "").split(":")[0] for a in classes.values()}
            joined = {slide.index: _norm(" ".join(block.text for s, block in out_blocks if s is slide))
                      for slide in outputs}
            normed = {element.id: _norm(" ".join(element.paragraphs)) for element in texts}
            for element in texts:
                text = normed[element.id]
                if len(text.split()) < 4:
                    continue
                frame = roles.get(element.id) in REPEATED_IN_PARTS
                declared = entry.element_destinations.get(element.id, [])
                present = [index for index, content in joined.items() if text in content]
                # Una aparición la explica cualquier bloque de origen de esa parte que contenga
                # el texto (un placeholder breve dentro de un párrafo mayor no es un clon).
                cloned = [index for index in present if joined[index].count(text) > sum(
                    normed[other.id].count(text) for other in texts
                    if index in entry.element_destinations.get(other.id, []))]
                if cloned or (not frame and len(declared) > 1):
                    add("split_duplication", "split_duplicate",
                        f"el bloque «{text[:40]}…» aparece en {len(present)} partes",
                        "la partición clonó un bloque común en vez de asignarlo a una parte",
                        "cada bloque común vive en una sola parte; solo el marco se repite",
                        reference=element.id, correction="dejar el bloque solo en la parte propietaria",
                        outputs=present, declared=declared)

    slide_ids = [slide.index for slide in ctx.slides]
    return result.finish(slide_ids, SUBCHECKS)


def _images(ctx, result, add, images, source_images, outputs, specs) -> None:
    candidates = [(slide, image) for slide, spec in zip(outputs, specs) for image in spec.images
                  if not image.name.startswith(BRAND_PREFIX)]
    by_hash: dict[str, list] = {}
    for slide, image in candidates:
        by_hash.setdefault(_sha(image.path), []).append((slide, image))
    unmatched = []
    for element in images:
        pool = by_hash.get(element.image_hash)
        if pool:
            pool.pop()
            continue
        unmatched.append(element)
    leftovers = [item for pool in by_hash.values() for item in pool]
    for element in unmatched:
        source_image = source_images.get(element.local_id)
        if source_image is None:
            add("images", "image_not_comparable", "imagen recodificada sin el PPTX de origen para compararla",
                "el auditor no recibió el origen", "comparar contra el PPTX de origen",
                status="not_run", reference=element.id, image=element.image_hash[:12])
            continue
        source_animation = animation(source_image.path)
        match = None
        for slide, image in leftovers:
            if source_animation is not None:
                if animation(image.path) == source_animation:
                    match = (slide, image, 0.0)
                    break
                continue
            diff = same_picture(source_image.path, image.path)
            if diff is not None:
                match = (slide, image, diff)
                break
        if match is None and source_animation is None:
            # Ícono de un color repintado con el color de la marca: misma forma, otro color.
            recolored = next(((slide, image) for slide, image in leftovers
                              if same_glyph(source_image.path, image.path)), None)
            if recolored:
                leftovers.remove(recolored)
                result.exceptions_applied.append({
                    "check": AUDITOR, "slide_id": recolored[0].index, "element": element.id,
                    "code": "recolored_icon", "condition": "glifo de un color repintado con el color de la marca",
                    "reference": "icon_tint.py (tokens.yaml → components.icon_badge)",
                })
                continue
        if match is None:
            if source_animation is not None:
                still = any(same_picture(source_image.path, image.path) is not None for _s, image in leftovers)
                add("images", "gif_animation_lost" if still else "image_missing",
                    "el GIF animado quedó fijo o alterado" if still else "GIF animado ausente en la salida",
                    "la animación no se conservó", "mismos cuadros y duraciones que el origen",
                    reference=element.id, frames=source_animation[0])
            else:
                add("images", "image_missing", "imagen del origen ausente en la salida",
                    "la imagen no se copió o cambió a la vista", "cada imagen del origen está en su salida",
                    reference=element.id, image=element.image_hash[:12])
            continue
        slide, image, diff = match
        leftovers.remove((slide, image))
        result.exceptions_applied.append({
            "check": AUDITOR, "slide_id": slide.index, "element": element.id, "code": "optimized_image",
            "condition": f"recodificada por optimize.py; diferencia media en miniatura {diff:.2f}",
            "reference": "optimize.py (200 ppi, PNG opaca → JPEG)",
        })
