"""`optimization_audit`: el PPTX antes y después de `optimize.py` muestra lo mismo.

Compara slide a slide: texto, enlaces, notas, visibilidad, marca de procedencia y
relaciones que no son imágenes deben ser idénticos. Cada imagen conserva su lugar:
o es la misma, o es la misma a la vista (recodificada o reducida), y eso queda como
excepción registrada con su condición. Un GIF animado debe salir con los mismos
cuadros y duraciones; convertirlo en imagen fija es un fallo.

Fase 3 (2026-10-01): la miniatura no ve texto pequeño ni líneas finas, así que además se
mide el detalle (energía de bordes) al tamaño de uso ampliado ×2. Una imagen con detalle
fino según el plan (captura, diagrama, gráfico en imagen, ícono) no puede pasar a JPEG.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from pptx import Presentation
from pptx.opc.constants import RELATIONSHIP_TYPE as RT

from PIL import Image

from ..optimize import DETAIL_GUARD, POLICIES, detail_ratio
from ..parser import parse_deck
from ..slide_marker import read_marker
from .content import animation, same_picture
from .core import AuditResult, Finding

AUDITOR = "optimization_audit"
SUBCHECKS = ("text", "links", "notes", "relationships", "images", "animation")
# Detalle mínimo de cualquier imagen optimizada; las protegidas exigen DETAIL_GUARD. Calibrado
# con el deck de inducción (205 imágenes, 200 ppi): el peor caso conservó 0.934.
DETAIL_FLOOR = 0.85
ZOOM_DPI = 192  # la slide de 1920 px vista al doble


def _sha(path: str) -> str:
    return sha256(Path(path).read_bytes()).hexdigest()


def audit(pre: Path, post: Path, workspace: Path, classes: dict[str, str] | None = None) -> AuditResult:
    """`classes`: función de cada imagen por su huella después de optimizar."""
    classes = classes or {}
    result = AuditResult(auditor=AUDITOR)
    before = parse_deck(pre, workspace / "opt-media" / "pre")
    after = parse_deck(post, workspace / "opt-media" / "post")
    pre_prs, post_prs = Presentation(str(pre)), Presentation(str(post))

    def add(index, subcheck, code, symptom, **measurement):
        result.findings.append(Finding(
            check=AUDITOR, subcheck=subcheck, code=code, status="fail", slide_id=index, symptom=symptom,
            measurement=measurement, cause="la optimización cambió algo más que el peso de las imágenes",
            correction_proposed="excluir ese elemento de la optimización", acceptance="mismo contenido antes y después",
        ))

    if len(before.slides) != len(after.slides):
        add(None, "text", "slide_count_changed", "la optimización cambió la cantidad de slides",
            before=len(before.slides), after=len(after.slides))
        return result.finish([], SUBCHECKS)

    for a, b, sa, sb in zip(before.slides, after.slides, pre_prs.slides, post_prs.slides):
        index = a.index
        if [t.text for t in a.texts] != [t.text for t in b.texts]:
            add(index, "text", "text_changed", "el texto cambió al optimizar")
        links = lambda spec: [r.hyperlink for t in spec.texts for p in t.paragraphs for r in p.runs if r.hyperlink]
        if links(a) != links(b):
            add(index, "links", "link_changed", "los enlaces cambiaron al optimizar")
        if a.notes != b.notes:
            add(index, "notes", "notes_changed", "las notas cambiaron al optimizar")
        if a.hidden != b.hidden or read_marker(sa) != read_marker(sb):
            add(index, "relationships", "slide_state_changed", "visibilidad o marca de procedencia cambió")
        rels = lambda slide: sorted(
            (rel.reltype, rel.target_ref if rel.is_external else "") for rel in slide.part.rels.values()
            if rel.reltype != RT.IMAGE
        )
        if rels(sa) != rels(sb):
            add(index, "relationships", "relationship_changed", "relaciones que no son imágenes cambiaron")
        if len(a.images) != len(b.images):
            add(index, "images", "image_count_changed", "cambió la cantidad de imágenes",
                before=len(a.images), after=len(b.images))
            continue
        for image_a, image_b in zip(a.images, b.images):
            if _sha(image_a.path) == _sha(image_b.path):
                continue
            frames = animation(image_a.path)
            if frames is not None:
                add(index, "animation", "gif_animation_altered", "un GIF animado cambió al optimizar",
                    element=image_a.name, frames_before=frames[0],
                    frames_after=(animation(image_b.path) or (1,))[0])
                continue
            diff = same_picture(image_a.path, image_b.path)
            if diff is None:
                add(index, "images", "image_changed", "la imagen optimizada se ve distinta", element=image_a.name)
                continue
            cls = classes.get(image_b.sha)
            protected = bool(POLICIES.get(cls, {}).get("guard"))
            with Image.open(image_a.path) as picture_a, Image.open(image_b.path) as picture_b:
                if protected and picture_b.format == "JPEG" and picture_a.format != "JPEG":
                    add(index, "images", "protected_image_to_jpeg",
                        f"una imagen de clase {cls} pasó a JPEG y pierde texto fino", element=image_a.name)
                    continue
                size = (round(image_a.box.w / 72 * ZOOM_DPI), round(image_a.box.h / 72 * ZOOM_DPI))
                ratio = detail_ratio(picture_a, picture_b, size)
            floor = DETAIL_GUARD if protected else DETAIL_FLOOR
            if ratio < floor:
                add(index, "images", "fine_detail_lost", "la imagen optimizada pierde detalle a tamaño de uso",
                    element=image_a.name, detail_ratio=ratio, floor=floor, asset_class=cls)
                continue
            result.exceptions_applied.append({
                "check": AUDITOR, "slide_id": index, "element": image_a.name, "code": "optimized_image",
                "condition": (f"recodificada o reducida; diferencia media en miniatura {diff:.2f}; "
                              f"detalle a tamaño de uso {ratio:.3f} (clase {cls or 'sin clase'})"),
                "reference": "optimize.py (política por clase; sin clase: 200 ppi, PNG opaca → JPEG)",
            })
    return result.finish([slide.index for slide in after.slides], SUBCHECKS)
