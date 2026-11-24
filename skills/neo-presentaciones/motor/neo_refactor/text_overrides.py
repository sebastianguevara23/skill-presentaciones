"""Textos que la persona aprobó cambiar (`text_overrides` del plan): p. ej. un título corto.

El motor reemplaza el texto del elemento antes de componer. Cada párrafo nuevo conserva el
formato del primer run del párrafo que reemplaza (o del primero del elemento, si el texto
nuevo trae más párrafos) y sus propiedades de párrafo (alineación, nivel, viñeta). Cada `\\n`
del texto nuevo abre un párrafo.

- `apply_to_spec`: en la slide parseada, para las slides que se recomponen.
- `apply_to_slide`: en el PPTX, para las que conservan su organización (brand shell).
- `report_entries`: lo que queda en el reporte (`vN_report.json`): texto original y nuevo.

La integridad (`integrity.check`) saca de la comparación el texto viejo y exige el nuevo.
"""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import re

from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.oxml.ns import qn

from .schemas import Paragraph, Run, SlideSpec, TextBlock, TextOverride

# Nombre que el parser le da al bloque de una celda de tabla nativa.
_CELL = re.compile(r"\[celda (\d+),(\d+)\]$")


def lines(text: str) -> list[str]:
    """Los párrafos del texto nuevo: uno por cada `\\n`."""
    return text.replace("\r\n", "\n").replace("\r", "\n").split("\n")


def _first_run(runs) -> Run | None:
    return next((run for run in runs if run.text.strip()), None)


def _paragraphs(old: list[Paragraph], text: str) -> list[Paragraph]:
    first = _first_run(run for paragraph in old for run in paragraph.runs) or Run(text="")
    new = []
    for k, line in enumerate(lines(text)):
        base = old[min(k, len(old) - 1)] if old else Paragraph()
        run = _first_run(base.runs) or first
        new.append(base.model_copy(update={"runs": [run.model_copy(update={"text": line})]}))
    return new


def apply_to_spec(spec: SlideSpec, overrides: Mapping[str, TextOverride]) -> SlideSpec:
    """La slide con los textos aprobados en lugar de los originales (ids locales: `t1`)."""
    if not overrides:
        return spec
    texts: list[TextBlock] = [
        block.model_copy(update={"paragraphs": _paragraphs(block.paragraphs, overrides[block.id].text)})
        if block.id in overrides else block
        for block in spec.texts
    ]
    return spec.model_copy(update={"texts": texts})


def unknown(spec: SlideSpec, overrides: Mapping[str, TextOverride]) -> list[str]:
    """Ids de `overrides` que no son un texto de la slide."""
    texts = {block.id for block in spec.texts}
    return sorted(key for key in overrides if key not in texts)


def _shape(shapes, shape_id: int):
    for shape in shapes:
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            found = _shape(shape.shapes, shape_id)
            if found is not None:
                return found
        elif shape.shape_id == shape_id:
            return shape
    return None


def _text_frame(slide, block: TextBlock):
    """El marco de texto del PPTX que corresponde al bloque parseado (también una celda)."""
    if block.source_shape_id is None:
        return None
    shape = _shape(slide.shapes, block.source_shape_id)
    if shape is None:
        return None
    cell = _CELL.search(block.name)
    if cell and getattr(shape, "has_table", False) and shape.has_table:
        return shape.table.cell(int(cell[1]) - 1, int(cell[2]) - 1).text_frame
    return shape.text_frame if getattr(shape, "has_text_frame", False) else None


def _template_run(paragraph):
    return next((run for run in paragraph.findall(qn("a:r")) if (run.findtext(qn("a:t")) or "").strip()), None)


def replace_text(frame, text: str) -> None:
    """El texto nuevo en un marco de texto del PPTX, con el formato del texto que reemplaza."""
    body = frame._txBody
    old = body.findall(qn("a:p"))
    if not old:
        frame.text = text
        return
    first = next((run for paragraph in old if (run := _template_run(paragraph)) is not None), None)
    for k, line in enumerate(lines(text)):
        base = old[min(k, len(old) - 1)]
        paragraph = deepcopy(base)
        for child in list(paragraph):
            if child.tag in (qn("a:r"), qn("a:br"), qn("a:fld")):
                paragraph.remove(child)
        template = _template_run(base)
        template = template if template is not None else first
        if template is not None:
            run = deepcopy(template)
        else:
            run = paragraph.makeelement(qn("a:r"), {})
            run.append(paragraph.makeelement(qn("a:t"), {}))
        run.find(qn("a:t")).text = line
        end = paragraph.find(qn("a:endParaRPr"))
        if end is not None:
            end.addprevious(run)
        else:
            paragraph.append(run)
        old[0].addprevious(paragraph)
    for paragraph in old:
        body.remove(paragraph)


def apply_to_slide(slide, spec: SlideSpec, overrides: Mapping[str, TextOverride]) -> list[str]:
    """Reemplaza en el PPTX los textos aprobados de una slide que no se recompone.

    `spec` es la misma slide parseada del original: da el id de forma de cada bloque.
    Devuelve los ids locales que se aplicaron."""
    applied = []
    for block in spec.texts:
        override = overrides.get(block.id)
        if override is None:
            continue
        frame = _text_frame(slide, block)
        if frame is None:
            continue
        replace_text(frame, override.text)
        applied.append(block.id)
    return applied


def report_entries(spec: SlideSpec, overrides: Mapping[str, TextOverride]) -> list[dict]:
    """Lo que el reporte registra de cada texto aplicado: id, texto original, nuevo y la cita."""
    by_id = {block.id: block for block in spec.texts}
    return [
        {"id": f"s{spec.index}:{key}", "original": by_id[key].text, "text": override.text, "reason": override.reason}
        for key, override in overrides.items() if key in by_id
    ]
