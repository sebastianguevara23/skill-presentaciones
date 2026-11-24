"""Optimización de peso del PPTX sin cambio visible.

1) Quita relaciones a imágenes que ya ningún shape usa (quedan tras redibujar slides).
2) Reduce cada imagen a la resolución con la que realmente se muestra (ppi sobre su tamaño en la slide).
3) Convierte a JPEG las fotos PNG opacas. Las PNG con transparencia siguen en PNG.
4) GIF animados y las imágenes usadas fuera de slides (layouts, masters, fondos) no se tocan.

Desde la fase 3 (2026-10-01) cada imagen sigue la política de su función (`asset_classes`
del plan): una captura, un diagrama, un gráfico en imagen o un ícono nunca pasa a JPEG y no
se reduce si pierde detalle a su tamaño de uso; un logo o un asset de origen no se toca. Sin
clase se usa la heurística de siempre. Cada imagen queda en el reporte con su razón.
"""
from __future__ import annotations

import io
import hashlib
from collections import defaultdict

from PIL import Image, ImageFilter, ImageStat
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.opc.constants import RELATIONSHIP_TYPE as RT
from pptx.opc.packuri import PackURI
from pptx.oxml.ns import qn

from .bg_clear import source_sha
from .parser import EMU_PER_PT, _Transform

R_EMBED = qn("r:embed")
R_ID = qn("r:id")
R_LINK = qn("r:link")
KNOWN_NEO_LOGO_MD5_PREFIXES = (
    "fe303385",  # assets/brand/neo-logo-25.png
    "1b5a9746",  # assets/brand/neo-logo-25-white.png
)


# Política por función de la imagen. `jpeg`: always (foto opaca), auto (heurística de color),
# never (solo PNG sin pérdida). `ppi` sube la resolución objetivo de las que llevan texto
# pequeño o líneas finas; `guard` descarta una reducción que pierde detalle a tamaño de uso.
POLICIES: dict[str, dict] = {
    "photo": {"jpeg": "always"},
    "illustration": {"jpeg": "auto"},
    "background": {"jpeg": "auto"},
    "chart": {"jpeg": "never", "ppi": 300, "guard": True},
    "diagram": {"jpeg": "never", "ppi": 300, "guard": True},
    "screenshot": {"jpeg": "never", "ppi": 300, "guard": True},
    "icon": {"jpeg": "never", "ppi": 300, "guard": True},
    "logo": {"frozen": True},
    "client_logo": {"frozen": True},
    "source": {"frozen": True},
}
UNCLASSIFIED = {"jpeg": "auto"}
# Si una misma imagen recibe dos clases, gana la más conservadora.
_RANK = {"source": 0, "logo": 0, "client_logo": 0, "chart": 1, "diagram": 1, "screenshot": 1, "icon": 1,
         "illustration": 2, "background": 2, "photo": 3}
# Detalle mínimo que debe conservar una imagen protegida (energía de bordes, después/antes).
DETAIL_GUARD = 0.9


def strictest(classes) -> str | None:
    known = [c for c in classes if c in POLICIES]
    return min(known, key=_RANK.__getitem__) if known else None


def detail_ratio(before: Image.Image, after: Image.Image, size: tuple[int, int]) -> float:
    """Energía de bordes de `after` sobre la de `before`, las dos al mismo tamaño de uso.

    Mide lo que la miniatura no ve: texto pequeño, ejes y líneas finas que se borronean al
    reducir o al pasar a JPEG. 1.0 = mismo detalle; menos de 1, detalle perdido.
    """
    size = (max(8, size[0]), max(8, size[1]))

    def energy(im: Image.Image) -> float:
        flat = im.convert("RGBA")
        canvas = Image.new("RGBA", flat.size, (255, 255, 255, 255))
        canvas.alpha_composite(flat)
        edges = canvas.convert("L").resize(size, Image.LANCZOS).filter(ImageFilter.FIND_EDGES)
        return ImageStat.Stat(edges).mean[0]

    base = energy(before)
    return 1.0 if base < 0.5 else round(energy(after) / base, 3)


def _drop_orphan_images(prs, skip_slides=frozenset()) -> int:
    dropped = 0
    for position, slide in enumerate(prs.slides, 1):
        if position in skip_slides:
            continue
        el = slide._element
        used = {v for node in el.iter() for k, v in node.attrib.items() if k in (R_EMBED, R_ID, R_LINK)}
        for rid, rel in list(slide.part.rels.items()):
            if rel.reltype == RT.IMAGE and rid not in used:
                slide.part.drop_rel(rid)
                dropped += 1
    return dropped


def _display_needs(prs, ppi: float, skip_slides=frozenset()) -> tuple[dict, set]:
    """Píxeles necesarios (ancho, alto) por parte de imagen, y partes que no se deben tocar."""
    need: dict = defaultdict(lambda: (0.0, 0.0))
    frozen: set = set()

    def walk(shapes, tr, part):
        for sh in shapes:
            if sh.shape_type == MSO_SHAPE_TYPE.GROUP:
                walk(sh.shapes, tr.child(sh), part)
            elif sh.shape_type == MSO_SHAPE_TYPE.PICTURE:
                blip = sh._element.find(".//" + qn("a:blip"))
                if blip is None or blip.get(R_EMBED) is None:
                    continue
                img = part.related_part(blip.get(R_EMBED))
                # Brand marks are source assets, not display photos.  Keep the
                # full-resolution logo even when it is displayed small; this
                # avoids the pixelation reported in the onboarding review.
                blob_hash = hashlib.md5(img.blob).hexdigest()
                if (getattr(sh, "name", "").startswith("NEO_BRAND") or
                        blob_hash.startswith(KNOWN_NEO_LOGO_MD5_PREFIXES)):
                    frozen.add(img)
                box = tr.apply(sh.left or 0, sh.top or 0, sh.width or 0, sh.height or 0)
                cw = max(0.05, 1 - sh.crop_left - sh.crop_right)
                ch = max(0.05, 1 - sh.crop_top - sh.crop_bottom)
                w_px = box.w / 72 * ppi / cw
                h_px = box.h / 72 * ppi / ch
                ow, oh = need[img]
                need[img] = (max(ow, w_px), max(oh, h_px))

    for position, slide in enumerate(prs.slides, 1):
        walk(slide.shapes, _Transform(), slide.part)
        if position in skip_slides:  # slide intacta: sus imágenes no se recomprimen
            frozen.update(rel.target_part for rel in slide.part.rels.values() if rel.reltype == RT.IMAGE)
        # imágenes referenciadas por algo que no es un p:pic (fondos, rellenos): no se tocan
        pic_ids = {b.get(R_EMBED) for p in slide._element.iter(qn("p:pic")) for b in p.iter(qn("a:blip"))}
        for b in slide._element.iter(qn("a:blip")):
            rid = b.get(R_EMBED)
            if rid and rid not in pic_ids and rid in slide.part.rels:
                frozen.add(slide.part.related_part(rid))
    for master in prs.slide_masters:
        for part in [master.part, *[l.part for l in master.slide_layouts]]:
            for rel in part.rels.values():
                if rel.reltype == RT.IMAGE:
                    frozen.add(rel.target_part)
    return need, frozen


def _is_photo(im: Image.Image) -> bool:
    thumb = im.convert("RGB").resize((96, 96))
    return len(set(thumb.getdata())) > 2500


def optimize(prs, ppi: float = 200, jpeg_quality: int = 85, skip_slides=frozenset(),
             classes: dict[str, str] | None = None) -> dict:
    """`skip_slides`: posiciones 1-based de slides que no se tocan (trabajo parcial).

    `classes`: función de cada imagen por su huella (md5, 10 caracteres, como `ImageBlock.sha`).
    """
    classes = classes or {}
    stats = {"orphan_images_dropped": _drop_orphan_images(prs, skip_slides), "images_resized": 0,
             "png_to_jpeg": 0, "bytes_before": 0, "bytes_after": 0, "images": [], "by_class": {}}
    need, frozen = _display_needs(prs, ppi, skip_slides)
    for n, (part, (w_px, h_px)) in enumerate(need.items()):
        blob = part.blob
        sha = hashlib.md5(blob).hexdigest()[:10]
        # Una captura sin fondo blanco (`bg_clear`) es un archivo nuevo: hereda la clase de su
        # original, así sigue en PNG, a 300 ppi y con la guarda de detalle.
        cls = classes.get(sha) or classes.get(source_sha(sha) or "")
        policy = POLICIES.get(cls, UNCLASSIFIED)
        record = {"part": str(part.partname), "sha": sha, "class": cls, "format_before": part.content_type,
                  "bytes_before": len(blob)}

        def keep(action: str) -> None:
            record.update(action=action, format_after=part.content_type, bytes_after=len(blob),
                          px_after=record["px_before"], sha_after=sha)
            stats["bytes_after"] += len(blob)

        stats["bytes_before"] += len(blob)
        im = Image.open(io.BytesIO(blob))
        record["px_before"] = [im.width, im.height]
        # Pulgadas a las que se muestra: el ppi efectivo se mide contra esto.
        inches = (w_px / ppi, h_px / ppi)
        if part in frozen or policy.get("frozen"):
            keep("frozen")
        elif getattr(im, "n_frames", 1) > 1:  # GIF animado
            keep("animated")
        else:
            target = policy.get("ppi", ppi) / ppi
            scale = max(w_px * target / im.width, h_px * target / im.height)
            resized = scale < 0.9
            original = im
            if resized:
                if im.mode in ("P", "1", "L", "LA", "PA"):
                    # Pillow reduce en paleta con vecino más cercano: el ícono sale dentado.
                    im = im.convert("RGBA")
                im = im.resize((max(1, round(im.width * scale)), max(1, round(im.height * scale))), Image.LANCZOS)
            has_alpha = im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info)
            opaque = not has_alpha or im.convert("RGBA").getextrema()[3][0] == 255
            convertible = part.content_type in ("image/png", "image/gif", "image/bmp", "image/tiff") and opaque
            to_jpeg = convertible and (policy["jpeg"] == "always" or (policy["jpeg"] == "auto" and _is_photo(im)))
            out = io.BytesIO()
            if to_jpeg:
                im.convert("RGB").save(out, "JPEG", quality=jpeg_quality, optimize=True, progressive=True)
                new_type, ext = "image/jpeg", "jpg"
            elif part.content_type == "image/jpeg" and resized:  # sin re-codificar JPEG que no se achica
                im.convert("RGB").save(out, "JPEG", quality=jpeg_quality, optimize=True, progressive=True)
                new_type, ext = "image/jpeg", "jpg"
            elif resized:
                im.save(out, "PNG", optimize=True)
                new_type, ext = "image/png", "png"
            else:
                out = None
            new = out.getvalue() if out is not None else None
            display = (round(inches[0] * 192), round(inches[1] * 192))  # pantalla 1920 px ampliada ×2
            if new is None:
                keep("kept")
            elif len(new) >= len(blob) * 0.95:  # no vale la pena
                keep("no_gain")
            elif policy.get("guard") and (ratio := detail_ratio(original, Image.open(io.BytesIO(new)), display)) < DETAIL_GUARD:
                record["detail_ratio"] = ratio
                keep("detail_guard")
            else:
                part._blob = new
                if new_type != part.content_type:
                    part._content_type = new_type
                    part.__dict__.pop("content_type", None)  # lazyproperty cacheada
                    part.partname = PackURI(f"/ppt/media/opt_image{n}.{ext}")
                    stats["png_to_jpeg"] += 1
                stats["images_resized"] += int(resized)
                stats["bytes_after"] += len(new)
                record.update(action="to_jpeg" if to_jpeg else "resized" if resized else "recoded",
                              format_after=new_type, bytes_after=len(new), px_after=[im.width, im.height],
                              sha_after=hashlib.md5(new).hexdigest()[:10])
        record["ppi_effective"] = round(record["px_after"][0] / inches[0]) if inches[0] > 0 else None
        stats["images"].append(record)
        group = stats["by_class"].setdefault(cls or "unclassified", {"images": 0, "bytes_before": 0, "bytes_after": 0})
        group["images"] += 1
        group["bytes_before"] += record["bytes_before"]
        group["bytes_after"] += record["bytes_after"]
    _refresh_rel_targets(prs)
    stats["mb_saved"] = round((stats["bytes_before"] - stats["bytes_after"]) / 1e6, 1)
    return stats


def classes_after(stats: dict | None) -> dict[str, str]:
    """Clase de cada imagen por su huella **después** de optimizar: la usan el auditor y una
    segunda pasada (reparación), que si no la recibe vuelve a adivinar por el color."""
    return {item["sha_after"]: item["class"] for item in (stats or {}).get("images", []) if item.get("class")}


def _refresh_rel_targets(prs):
    """python-pptx cachea la ruta de destino de cada relación (lazyproperty): tras renombrar partes
    (png -> jpg) hay que invalidarla o el .rels apunta a archivos que ya no existen."""
    for part in prs.part.package.iter_parts():
        for rel in part.rels.values():
            rel.__dict__.pop("target_ref", None)
            rel.__dict__.pop("target_partname", None)
