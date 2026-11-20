"""Marca de procedencia que el motor deja en cada slide que toca.

Los auditores de la Fase 3 juzgan los bytes del PPTX, no el reporte del render: una
reparación o un rediseño que solo existe en un JSON no cuenta. Por eso el motor
escribe en `p:cSld/@name` qué hizo con la slide (modo, slide de origen, parte de una
partición, familia, layout y variante). Ni PowerPoint ni Google Slides lo muestran,
y sobrevive a `optimize.py` porque no es una relación ni una parte del paquete.
"""
from __future__ import annotations

import json

from pptx.oxml.ns import qn

PREFIX = "neo-refactor:"


def write_marker(slide, **fields) -> None:
    payload = {key: value for key, value in fields.items() if value is not None}
    slide._element.find(qn("p:cSld")).set("name", PREFIX + json.dumps(payload, ensure_ascii=False, sort_keys=True))


def read_marker(slide) -> dict | None:
    """Devuelve la marca o None si la slide no la tiene (oculta, o deck ajeno)."""
    name = slide._element.find(qn("p:cSld")).get("name", "")
    if not name.startswith(PREFIX):
        return None
    try:
        return json.loads(name[len(PREFIX):])
    except json.JSONDecodeError:
        return None
