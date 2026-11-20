"""Content Integrity Checker: compara el contenido original con el PPTX generado (re-parseado)."""
from __future__ import annotations

from collections.abc import Sequence
import json
import re
from collections import Counter

from .cleanup import strip_emojis
from .icon_tint import same_glyph
from .renderer import BRAND_PREFIX
from .schemas import SlideClassification, SlideSpec

_WS = re.compile(r"\s+")  # \s incluye NBSP, tabs y saltos de línea
_NUM = re.compile(r"\d+(?:[.,]\d+)*\s?%?")


def normalize(text: str) -> str:
    """Sin emojis: el rediseño los quita por regla de marca (convenciones)."""
    return _WS.sub(" ", strip_emojis(text)).strip()


def _paragraphs(slide: SlideSpec, skip_ids: set[str] = frozenset(), skip_brand: bool = False) -> Counter:
    c: Counter = Counter()
    for t in slide.texts:
        if t.id in skip_ids or (skip_brand and t.name.startswith(BRAND_PREFIX)):
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


def _ids_paragraphs(slide: SlideSpec, ids: set[str]) -> Counter:
    """Párrafos de un subconjunto de bloques: el marco que una partición repite."""
    c: Counter = Counter()
    for t in slide.texts:
        if t.id not in ids:
            continue
        for p in t.paragraphs:
            n = normalize(p.text)
            if n:
                c[n] += 1
    return c


def check(source: SlideSpec, output: SlideSpec | Sequence[SlideSpec], skip_ids: set[str] = frozenset(),
          skip_shas: set[str] = frozenset(), granular: bool = False,
          repeated_ids: set[str] = frozenset()) -> dict:
    """skip_ids: bloques retirados a propósito (decorativos / logo antiguo); skip_shas: idem por imagen.

    `output` puede ser varias slides: una partición reparte una slide de origen en
    slides consecutivas y el contenido se compara contra su unión. `repeated_ids`
    son los bloques del marco (título, kicker, banner, notas) que cada parte vuelve a
    mostrar: repetirlos no es contenido añadido, pero omitirlos sí sería pérdida.
    """
    outputs = [output] if isinstance(output, SlideSpec) else list(output)
    skip = set(skip_ids) | {i.id for i in source.images if i.sha in skip_shas}
    src = _paragraphs(source, skip_ids=skip)
    out: Counter = Counter()
    for produced in outputs:
        out += _paragraphs(produced, skip_brand=True)
    copies = len(outputs) - 1
    if copies and repeated_ids:
        chrome = _ids_paragraphs(source, set(repeated_ids) - skip)
        out -= Counter({text: count * copies for text, count in chrome.items()})
    if granular:
        # el diseño puede partir un párrafo en piezas: se comparan las palabras y las
        # cifras del texto completo, que es lo que no puede cambiar
        src, out = _words(src), _words(out)
    removed = list((src - out).elements())
    added = list((out - src).elements())
    num_src, num_out = _numbers(src), _numbers(out)

    src_imgs = Counter(i.sha for i in source.images if i.id not in skip)
    out_imgs = Counter(
        i.sha for produced in outputs for i in produced.images if not i.name.startswith(BRAND_PREFIX)
    )
    # Un ícono de un color sale repintado con el color de la marca (`icon_tint`): el mismo
    # glifo en otro color sigue siendo la imagen del origen.
    recolored = 0
    missing, extra = src_imgs - out_imgs, out_imgs - src_imgs
    if missing and extra:
        src_paths = {i.sha: i.path for i in source.images}
        out_paths = {i.sha: i.path for produced in outputs for i in produced.images}
        for sha in list(missing.elements()):
            match = next((other for other in +extra if same_glyph(src_paths[sha], out_paths[other])), None)
            if match:
                src_imgs[sha] -= 1
                extra[match] -= 1
                recolored += 1
    src_charts = _charts(source, skip_ids=skip)
    out_charts: Counter = Counter()
    for produced in outputs:
        out_charts += _charts(produced, skip_brand=True)
    charts_changed = len(list((src_charts - out_charts).elements())) + len(list((out_charts - src_charts).elements()))
    return {
        "preserved": (not removed and not added and num_src == num_out and not (src_imgs - out_imgs)
                      and not charts_changed),
        "removed_content": removed,
        "modified_content": added,
        "numeric_changes": sum(((num_src - num_out) + (num_out - num_src)).values()),
        "images_missing": list((src_imgs - out_imgs).elements()),
        "icons_recolored": recolored,
        # Gráficos nativos que faltan, sobran o cambiaron de datos (el estilo no cuenta).
        "charts_changed": charts_changed,
        "removed_on_purpose": sorted(skip),
    }


def unassigned(source: SlideSpec, cls: SlideClassification) -> list[str]:
    """Bloques con contenido (texto o imagen) que la clasificación no asignó a ningún slot."""
    assigned = set(cls.assigned_ids())
    return [e.id for e in [*source.texts, *source.images] if e.id not in assigned]
