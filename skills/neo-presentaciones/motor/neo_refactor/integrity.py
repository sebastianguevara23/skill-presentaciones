"""Content Integrity Checker: compara el contenido original con el PPTX generado (re-parseado)."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
import re
from collections import Counter

from PIL import Image

from .cleanup import strip_emojis
from .icon_tint import same_glyph
from .renderer import BRAND_PREFIX
from .schemas import SlideClassification, SlideSpec

_WS = re.compile(r"\s+")  # \s incluye NBSP, tabs y saltos de línea
_NUM = re.compile(r"\d+(?:[.,]\d+)*\s?%?")
_DIGIT = re.compile(r"\d")

# Imagen tratada (`same_picture`): lado de la miniatura en px y diferencia media por canal
# (0–255) que todavía es la misma imagen a la vista (una recompresión JPEG queda en 1–4).
PICTURE_THUMB = 32
SAME_PICTURE = 8.0
# Lo que el candidato volvió transparente era fondo claro: brillo medio mínimo (0–255) del
# canal más oscuro del original en esa zona. Borrar contenido no es tratar la imagen.
CLEARED_LIGHT = 215.0


def normalize(text: str) -> str:
    """Sin emojis: el rediseño los quita por regla de marca (convenciones)."""
    return _WS.sub(" ", strip_emojis(text)).strip()


def _override_paragraphs(text: str) -> list[str]:
    """Párrafos de un texto pedido (`text_overrides`): cada `\\n` abre un párrafo."""
    return [line for line in (normalize(part) for part in text.split("\n")) if line]


def _paragraphs(slide: SlideSpec, skip_ids: set[str] = frozenset(), skip_brand: bool = False,
                overrides: Mapping[str, str] | None = None) -> Counter:
    """Párrafos de la slide. Un bloque con `overrides` cuenta con su texto nuevo, no el viejo."""
    c: Counter = Counter()
    for t in slide.texts:
        if t.id in skip_ids or (skip_brand and t.name.startswith(BRAND_PREFIX)):
            continue
        if overrides and t.id in overrides:
            c.update(_override_paragraphs(overrides[t.id]))
            continue
        for p in t.paragraphs:
            n = normalize(p.text)
            if n:
                c[n] += 1
    return c


def _numbers(paras: Counter) -> Counter:
    c: Counter = Counter()
    for text, k in paras.items():
        for m in _NUM.findall(text):
            c[m.replace(" ", "")] += k
    return c


def _words(paras: Counter) -> Counter:
    c: Counter = Counter()
    for text, k in paras.items():
        for w in text.split():
            if any(ch.isalnum() for ch in w):  # "•", "|", "-": ornamento, no contenido
                c[w] += k
    return c


def _charts(slide: SlideSpec, skip_ids: set[str] = frozenset(), skip_brand: bool = False) -> Counter:
    """Datos de cada gráfico nativo (tipo, título, categorías, series y valores), sin estilo."""
    return Counter(
        json.dumps(shape.chart.model_dump(), ensure_ascii=False, sort_keys=True)
        for shape in slide.shapes
        if shape.chart is not None and shape.id not in skip_ids
        and not (skip_brand and shape.name.startswith(BRAND_PREFIX))
    )


def _ids_paragraphs(slide: SlideSpec, ids: set[str], overrides: Mapping[str, str] | None = None) -> Counter:
    """Párrafos de un subconjunto de bloques: el marco que una partición repite."""
    c: Counter = Counter()
    for t in slide.texts:
        if t.id not in ids:
            continue
        if overrides and t.id in overrides:
            c.update(_override_paragraphs(overrides[t.id]))
            continue
        for p in t.paragraphs:
            n = normalize(p.text)
            if n:
                c[n] += 1
    return c


def _picture(path: str) -> Image.Image | None:
    """Primer cuadro en RGBA; None si no se puede abrir."""
    try:
        with Image.open(path) as image:
            image.seek(0)
            return image.convert("RGBA")
    except (OSError, ValueError):
        return None


def _frames(path: str) -> int:
    try:
        with Image.open(path) as image:
            return getattr(image, "n_frames", 1)
    except (OSError, ValueError):
        return 0


def same_picture(source: str, candidate: str) -> bool:
    """¿`candidate` es la imagen `source` tratada (recodificada, comprimida o sin su fondo)?

    - Misma proporción (±3 %).
    - En miniatura, el RGB de los píxeles opacos del candidato coincide con el del original;
      los transparentes del candidato no cuentan (un fondo blanco vuelto transparente).
    - Lo que el candidato volvió transparente era fondo claro en el original: borrar
      contenido no es tratar la imagen.
    Las dos se comparan como se ven sobre blanco, que es donde se quita el fondo (slides claras).
    """
    a, b = _picture(source), _picture(candidate)
    if a is None or b is None or _frames(source) != _frames(candidate):
        return False
    ratio_a, ratio_b = a.width / max(1, a.height), b.width / max(1, b.height)
    if abs(ratio_a - ratio_b) > 0.03 * max(ratio_a, ratio_b):
        return False
    size = (PICTURE_THUMB, PICTURE_THUMB)
    # `resize` en RGBA premultiplica el alfa: el borde de un glifo conserva su color.
    small_a, small_b = a.resize(size, Image.LANCZOS), b.resize(size, Image.LANCZOS)
    alpha_a, alpha_b = small_a.getchannel("A").tobytes(), small_b.getchannel("A").tobytes()
    white = Image.new("RGBA", size, (255, 255, 255, 255))
    flat_a = Image.alpha_composite(white, small_a).convert("RGB").tobytes()
    flat_b = Image.alpha_composite(white, small_b).convert("RGB").tobytes()
    weight = diff = 0.0
    cleared, cleared_light = 0, 0.0
    for i in range(PICTURE_THUMB * PICTURE_THUMB):
        rgb_a, rgb_b = flat_a[3 * i:3 * i + 3], flat_b[3 * i:3 * i + 3]
        opacity = alpha_b[i] / 255
        if opacity:
            weight += opacity
            diff += opacity * sum(abs(x - y) for x, y in zip(rgb_a, rgb_b)) / 3
        if alpha_b[i] < 128 <= alpha_a[i]:
            cleared += 1
            cleared_light += min(rgb_a)
    # Sin píxeles opacos no hay con qué comparar: una imagen vacía no es la del origen.
    if weight < 0.01 * PICTURE_THUMB * PICTURE_THUMB or diff / weight > SAME_PICTURE:
        return False
    return not cleared or cleared_light / cleared >= CLEARED_LIGHT


def match_images(missing: Counter, extra: Counter, src_paths: Mapping[str, str],
                 out_paths: Mapping[str, str]) -> tuple[list[dict], list[dict]]:
    """Empareja las imágenes del origen que no aparecen por sha con las que sobran en la salida.

    Devuelve (repintadas, tratadas): un ícono de un color repintado con la marca
    (`same_glyph`) y una imagen tratada (`same_picture`). Cada par es
    `{"source": sha, "output": sha}`; las que no se emparejan siguen faltando.
    `missing` y `extra` no se modifican.
    """
    recolored: list[dict] = []
    treated: list[dict] = []
    pool = Counter(extra)
    for sha in list(missing.elements()):
        source_path = src_paths.get(sha)
        if source_path is None:
            continue
        candidates = [other for other in +pool if other in out_paths]
        match = next((other for other in candidates if same_glyph(source_path, out_paths[other])), None)
        if match:
            recolored.append({"source": sha, "output": match})
        else:
            match = next((other for other in candidates if same_picture(source_path, out_paths[other])), None)
            if match:
                treated.append({"source": sha, "output": match})
        if match:
            pool[match] -= 1
    return recolored, treated


def consolidated(removed: Counter, out: Counter) -> Counter:
    """Rótulos consolidados (`consolidate_labels`): faltan copias, pero el texto sigue al menos
    una vez en la salida de la slide. Lo que lleva una cifra nunca se consolida."""
    return Counter({item: n for item, n in removed.items() if out[item] >= 1 and not _DIGIT.search(item)})


def check(source: SlideSpec, output: SlideSpec | Sequence[SlideSpec], skip_ids: set[str] = frozenset(),
          skip_shas: set[str] = frozenset(), granular: bool = False,
          repeated_ids: set[str] = frozenset(), text_overrides: Mapping[str, str] | None = None,
          consolidate: bool = False) -> dict:
    """skip_ids: bloques retirados a propósito (decorativos / logo antiguo); skip_shas: idem por imagen.

    `output` puede ser varias slides: una partición reparte una slide de origen en
    slides consecutivas y el contenido se compara contra su unión. `repeated_ids`
    son los bloques del marco (título, kicker, banner, notas) que cada parte vuelve a
    mostrar: repetirlos no es contenido añadido, pero omitirlos sí sería pérdida.

    `text_overrides` (id local → texto nuevo) son los textos que la persona aprobó cambiar:
    esos bloques salen de la comparación con su texto viejo y entran con el nuevo, que la
    salida tiene que mostrar completo. El resto de la slide se compara como siempre.
    `consolidate` (la persona aprobó juntar rótulos repetidos): una palabra o párrafo que
    falta pero sigue al menos una vez en la salida no bloquea; las cifras, sí.
    """
    outputs = [output] if isinstance(output, SlideSpec) else list(output)
    skip = set(skip_ids) | {i.id for i in source.images if i.sha in skip_shas}
    overrides = {key: value for key, value in (text_overrides or {}).items()
                 if key not in skip and any(t.id == key for t in source.texts)}
    src = _paragraphs(source, skip_ids=skip, overrides=overrides)
    out: Counter = Counter()
    for produced in outputs:
        out += _paragraphs(produced, skip_brand=True)
    copies = len(outputs) - 1
    if copies and repeated_ids:
        chrome = _ids_paragraphs(source, set(repeated_ids) - skip, overrides)
        out -= Counter({text: count * copies for text, count in chrome.items()})
    if granular:
        # el diseño puede partir un párrafo en piezas: se comparan las palabras y las
        # cifras del texto completo, que es lo que no puede cambiar
        src, out = _words(src), _words(out)
    lost = src - out
    merged = consolidated(lost, out) if consolidate else Counter()
    removed = list((lost - merged).elements())
    added = list((out - src).elements())
    num_src, num_out = _numbers(src), _numbers(out)

    src_imgs = Counter(i.sha for i in source.images if i.id not in skip)
    out_imgs = Counter(
        i.sha for produced in outputs for i in produced.images if not i.name.startswith(BRAND_PREFIX)
    )
    # Un ícono de un color sale repintado con el color de la marca (`icon_tint`) y una imagen
    # tratada (recodificada, sin fondo blanco) cambia de bytes: las dos siguen siendo la
    # imagen del origen. Las tratadas se informan aparte y no bloquean.
    recolored, treated = [], []
    missing, extra = src_imgs - out_imgs, out_imgs - src_imgs
    if missing and extra:
        src_paths = {i.sha: i.path for i in source.images}
        out_paths = {i.sha: i.path for produced in outputs for i in produced.images}
        recolored, treated = match_images(missing, extra, src_paths, out_paths)
        for pair in [*recolored, *treated]:
            src_imgs[pair["source"]] -= 1
    src_charts = _charts(source, skip_ids=skip)
    out_charts: Counter = Counter()
    for produced in outputs:
        out_charts += _charts(produced, skip_brand=True)
    charts_changed = len(list((src_charts - out_charts).elements())) + len(list((out_charts - src_charts).elements()))
    result = {
        "preserved": (not removed and not added and num_src == num_out and not (src_imgs - out_imgs)
                      and not charts_changed),
        "removed_content": removed,
        "modified_content": added,
        "numeric_changes": sum(((num_src - num_out) + (num_out - num_src)).values()),
        "images_missing": list((src_imgs - out_imgs).elements()),
        "icons_recolored": len(recolored),
        # Imágenes tratadas (`same_picture`): misma imagen con otros bytes; no bloquean.
        "images_treated": treated,
        # Gráficos nativos que faltan, sobran o cambiaron de datos (el estilo no cuenta).
        "charts_changed": charts_changed,
        "removed_on_purpose": sorted(skip),
    }
    if overrides:
        # Textos que la persona aprobó cambiar (`text_overrides`): `s3:t1`, …
        result["requested_changes"] = [f"s{source.index}:{key}" for key in sorted(overrides)]
    if consolidate:
        result["consolidated_labels"] = sorted(merged.elements())
    return result


def unassigned(source: SlideSpec, cls: SlideClassification) -> list[str]:
    """Bloques con contenido (texto o imagen) que la clasificación no asignó a ningún slot."""
    assigned = set(cls.assigned_ids())
    return [e.id for e in [*source.texts, *source.images] if e.id not in assigned]
