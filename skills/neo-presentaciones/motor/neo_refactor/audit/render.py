"""`render_audit`: lo que se ve al renderizar, no lo que dicen las cajas.

Convierte el PPTX con LibreOffice (incluidas las ocultas, una página por slide) y
lee cada palabra dibujada con PyMuPDF. Para cada caja de texto compara las palabras
esperadas con las que caen dentro de ella:

- una palabra que aparece fuera de su caja es texto desbordado; si la caja pasaba la
  geometría, el hallazgo es `google_font_or_wrap_risk` (la primera corrección es una
  caja mayor, nunca bajar de 11 pt);
- si además cae dentro de otra caja de texto, es `render_collision`;
- si no aparece en la página, `text_not_rendered` (recortada o fuera del lienzo).

`orphans` mide el corte de líneas con las métricas calibradas de Montserrat: una
última línea de una sola palabra falla; en la banda segura de Google (97 %) avisa.
En slides conservadas (ocultas, excluidas) los hallazgos son avisos: no son una
composición del motor, pero quedan en el reporte.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unicodedata

import pymupdf

from ..schemas import Box, RPara, RRun
from ..textmetrics import is_orphan, orphan_free, wrap
from .core import AuditContext, AuditResult, Finding, not_run
from .geometry import canonical, role_of

AUDITOR = "render_audit"
SUBCHECKS = ("text_render", "orphans")
EXPAND = 3.0
EXPORT_FILTER = 'pdf:impress_pdf_Export:{"ExportHiddenSlides":{"type":"boolean","value":"true"}}'
_TRIM = re.compile(r"^[^\w]+|[^\w]+$")
HYPHENS = ("-", "\u2010", "\u2011")


def token(word: str) -> str:
    return _TRIM.sub("", unicodedata.normalize("NFKC", word).replace("\u2060", "").casefold())


def render_pdf(pptx: Path, destination: Path, timeout: int = 600) -> Path | None:
    """PDF de LibreOffice con perfil propio (no choca con otra instancia abierta)."""
    if destination.exists():
        return destination
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if soffice is None:
        return None
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="neo-render-") as tmp:
        tmp_path = Path(tmp)
        source = tmp_path / "deck.pptx"
        shutil.copy2(pptx, source)
        try:
            subprocess.run(
                [soffice, f"-env:UserInstallation=file://{tmp_path / 'profile'}", "--headless",
                 "--convert-to", EXPORT_FILTER, "--outdir", str(tmp_path / "out"), str(source)],
                check=True, capture_output=True, timeout=timeout,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return None
        produced = tmp_path / "out" / "deck.pdf"
        if not produced.exists():
            return None
        shutil.move(str(produced), destination)
    return destination


def rendered_pdf(ctx: AuditContext) -> Path | None:
    return render_pdf(ctx.output_path, ctx.workspace / "render" / f"{ctx.output_sha[:24]}.pdf")


def _rpara(paragraph, exempt: set[str], scale: float = 1.0) -> RPara:
    """Párrafo para el modelo de corte, en pt lógicos: `scale` lleva el lienzo de salida al lógico."""
    runs = [
        RRun(text=run.text, font=run.font or "Montserrat", size=(run.size or 11.0 * scale) / scale,
             bold=bool(run.bold), italic=bool(run.italic), color=run.color or "000000")
        for run in paragraph.runs if run.text and (run.font or "") not in exempt
    ]
    # La sangría del párrafo (viñeta) le quita ancho a cada línea: sin ella el corte medido
    # no es el que se ve.
    return RPara(runs=runs or [RRun(text="", font="Montserrat", size=11.0, color="000000")],
                 indent=paragraph.margin / scale)


def audit(ctx: AuditContext) -> AuditResult:
    slide_ids = [slide.index for slide in ctx.slides]
    pdf = rendered_pdf(ctx)
    if pdf is None:
        return not_run(AUDITOR, "LibreOffice no pudo convertir el PPTX", slide_ids, SUBCHECKS)
    document = pymupdf.open(pdf)
    try:
        if len(document) != len(ctx.slides):
            return not_run(AUDITOR, f"el PDF tiene {len(document)} páginas para {len(ctx.slides)} slides",
                           slide_ids, SUBCHECKS)
        result = AuditResult(auditor=AUDITOR)
        for slide in ctx.slides:
            _audit_slide(ctx, slide, document[slide.index - 1], result)
    finally:
        document.close()
    ctx.apply_exceptions(result)
    return result.finish(slide_ids, SUBCHECKS)


def _audit_slide(ctx: AuditContext, slide, page, result: AuditResult) -> None:
    kn = ctx.kn
    spec = ctx.deck.slide(slide.index)
    scale = ctx.deck.width / kn.tokens["canvas"]["width"]
    page_scale = page.rect.width / kn.tokens["canvas"]["width"]
    severity = "fail" if slide.redesigned else "warning"
    # Un espacio duro (el que une las dos últimas palabras contra huérfanas) no separa
    # palabras en el PDF: se parte aquí igual que el texto esperado.
    raw = [
        (Box(x=x0 / page_scale, y=y0 / page_scale, w=(x1 - x0) / page_scale, h=(y1 - y0) / page_scale), part)
        for x0, y0, x1, y1, text, *_rest in page.get_text("words")
        for part in unicodedata.normalize("NFKC", text).split()
    ]
    words = [(box, token(part)) for box, part in raw if token(part)]
    # Fragmentos que terminan en guion: el render cortó ahí la palabra (corte legítimo).
    hyphen_ends = [part.endswith(HYPHENS) for box, part in raw if token(part)]
    blocks = [(block, canonical(block.box, scale)) for block in spec.texts]

    def expanded(box: Box) -> Box:
        return Box(x=box.x - EXPAND, y=box.y - EXPAND, w=box.w + 2 * EXPAND, h=box.h + 2 * EXPAND)

    def center_in(word_box: Box, area: Box) -> bool:
        cx, cy = word_box.x + word_box.w / 2, word_box.y + word_box.h / 2
        return area.x <= cx <= area.right and area.y <= cy <= area.bottom

    def add(subcheck, code, status, block, symptom, cause, correction, acceptance, **measurement):
        result.findings.append(Finding(
            check=AUDITOR, subcheck=subcheck, code=code, status=status, slide_id=slide.index,
            source_slide_id=slide.source_slide_id, family=slide.family, source_reference=block.name,
            symptom=symptom, measurement=measurement, cause=cause,
            correction_proposed=correction, acceptance=acceptance,
        ))

    exempt = kn.exempt_families
    for block, box in blocks:
        expected = Counter(
            token(word) for paragraph in block.paragraphs for run in paragraph.runs
            if (run.font or "") not in exempt for word in run.text.split()
        )
        expected = Counter({word: count for word, count in expected.items() if word})
        if not expected:
            continue
        area = expanded(box)
        inside = Counter(word for word_box, word in words if center_in(word_box, area))
        missing = expected - inside
        if not missing:
            continue
        # Busca las palabras que faltan cerca de la caja: debajo (desborde vertical) o al lado.
        near = Box(x=box.x - 40, y=box.y - 20, w=box.w + 80, h=box.h + 120)
        outside = [
            (word_box, word) for word_box, word in words
            if word in missing and center_in(word_box, near) and not center_in(word_box, area)
        ]
        found = Counter(word for _box, word in outside)
        lost = missing - found
        # Una palabra partida entre dos líneas aparece como fragmentos consecutivos.
        ordered = [(word, hyphen_ends[i]) for i, (word_box, word) in enumerate(words) if center_in(word_box, area)]
        broken, hyphenated = Counter(), Counter()
        for word in lost:
            for size in (2, 3):
                for i in range(len(ordered) - size + 1):
                    parts = ordered[i:i + size]
                    # Corte en el guion propio de la palabra («lanzamiento-» + «iphone»): es tipografía
                    # correcta, no texto perdido. Antes `token` quitaba el guion y la daba por ausente.
                    if all(end for _word, end in parts[:-1]) and "-".join(w for w, _end in parts) == word:
                        hyphenated[word] = lost[word]
                        break
                    if "".join(w for w, _end in parts) == word:
                        broken[word] = lost[word]
                        break
                if word in broken or word in hyphenated:
                    break
        lost -= broken + hyphenated
        if broken:
            linked = {
                token(part) for paragraph in block.paragraphs for run in paragraph.runs if run.hyperlink
                for part in run.text.split()
            }
            only_links = set(broken) <= linked
            # LibreOffice dibuja un hipervínculo como campo y lo corta por carácter; Google
            # Slides no. Fuera de un enlace, una palabra partida es un corte real.
            add("text_render", "hyperlink_field_wrap" if only_links else "google_font_or_wrap_risk",
                "warning" if only_links else severity, block,
                f"{role_of(block.name)}: palabra partida entre líneas ({', '.join(sorted(broken))})",
                "LibreOffice corta el enlace como campo" if only_links else "el render corta la palabra: la caja es justa",
                None if only_links else "probar primero una caja más ancha; nunca bajar de 11 pt",
                "ninguna palabra partida en el render", box=box.model_dump(), words=sorted(broken))
        in_zone = ctx.contract.geometry_zone
        geometry_ok = box.x >= in_zone[0] and box.y >= in_zone[1] and box.right <= in_zone[2] and box.bottom <= in_zone[3]
        if outside:
            colliding = sorted({
                other.name for word_box, _word in outside for other, other_box in blocks
                if other is not block and center_in(word_box, other_box)
            })
            lowest = max(word_box.bottom for word_box, _word in outside)
            rightmost = max(word_box.right for word_box, _word in outside)
            if colliding:
                add("text_render", "render_collision", severity, block,
                    f"{role_of(block.name)}: el texto desbordado cae sobre {', '.join(colliding)}",
                    "la caja es menor que el texto renderizado",
                    "ampliar la caja hacia el espacio libre o redistribuir", "ninguna palabra fuera de su caja",
                    box=box.model_dump(), rendered_bottom=round(lowest, 1), rendered_right=round(rightmost, 1),
                    words_outside=sum(found.values()), collides_with=colliding)
            else:
                add("text_render", "google_font_or_wrap_risk" if geometry_ok else "render_overflow", severity, block,
                    f"{role_of(block.name)}: {sum(found.values())} palabras se dibujan fuera de su caja",
                    "geometría válida pero el render corta distinto" if geometry_ok else "caja fuera de regla y desbordada",
                    "probar primero una caja mayor; nunca bajar de 11 pt", "todas las palabras dentro de su caja",
                    box=box.model_dump(), rendered_bottom=round(lowest, 1), rendered_right=round(rightmost, 1),
                    words_outside=sum(found.values()))
        if lost:
            add("text_render", "text_not_rendered", severity, block,
                f"{role_of(block.name)}: {sum(lost.values())} palabras no aparecen en el render",
                "texto recortado, fuera del lienzo o con glifos que el render no dibuja",
                "revisar la caja y la fuente en la preview", "cada palabra de la caja aparece en el render",
                box=box.model_dump(), missing=sorted(lost)[:12])

    for block, box in blocks:
        width = box.w if slide.redesigned else max(1.0, box.w - 14.4)
        for number, paragraph in enumerate(block.paragraphs):
            para = _rpara(paragraph, exempt, scale)
            if len(para.text.split()) < 3:
                continue
            lines = [line for line in wrap(para, width) if line.words]
            if len(lines) < 2:
                continue
            exact = is_orphan(para, width)
            risky = not orphan_free(para, width, kn.safety)
            if not exact and not risky:
                continue
            add("orphans", "orphan" if exact else "google_font_or_wrap_risk",
                severity if exact else "warning", block,
                f"última línea de una palabra: «{' '.join(lines[-1].words)}»",
                "corte de línea al ancho medido" if exact else "corte solo en la banda segura de Google",
                "ajustar ancho de la caja o repartir; nunca bajar de 11 pt",
                "ningún párrafo termina con una palabra sola", paragraph=number, width=round(width, 1),
                lines=len(lines))
