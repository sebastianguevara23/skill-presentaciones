"""Preparar el original para que el motor lo pueda componer, sin cambiar su contenido.

`separar`: una caja con varios párrafos (una agenda, una lista de pasos) pasa a una caja por
párrafo, con el mismo texto y el mismo estilo. Así cada ítem puede ir a su propia unidad
(`item:N`, `card:N`) y la slide toma el diseño de su familia en vez de quedarse como lista.
"""
from __future__ import annotations

import copy
import re
from pathlib import Path

from lxml import etree
from pptx import Presentation

A = "http://schemas.openxmlformats.org/drawingml/2006/main"
P = "http://schemas.openxmlformats.org/presentationml/2006/main"


def _q(ns: str, tag: str) -> str:
    return f"{{{ns}}}{tag}"


def _texto(p_el) -> str:
    return "".join(t.text or "" for t in p_el.iter(_q(A, "t")))


def _palabras(pptx: Path) -> list[str]:
    """Las palabras del deck en orden de slide, sin espacios ni saltos: lo que no puede cambiar."""
    prs = Presentation(str(pptx))
    out: list[str] = []
    for slide in prs.slides:
        palabras = []
        for el in slide._element.iter(_q(A, "t")):
            palabras += (el.text or "").split()
        out += sorted(palabras)
    return out


def _siguiente_id(slide) -> int:
    ids = [int(el.get("id")) for el in slide._element.iter(_q(P, "cNvPr")) if el.get("id", "").isdigit()]
    return max(ids, default=1) + 1


NUMERO = re.compile(r"^\s*((?:\d{1,3}|[IVXivx]{1,5}|[A-Za-z])[.)\-–:]?)\s+(\S.*)$", re.S)


def _sacar_numero(p_el) -> bool:
    """«1. Contexto» → dos párrafos, «1.» y «Contexto», con el mismo estilo. El texto no cambia."""
    texto = _texto(p_el)
    m = NUMERO.match(texto)
    if not m:
        return False
    runs = p_el.findall(_q(A, "r"))
    if not runs:
        return False
    numero, resto = m.group(1), m.group(2)
    p2 = copy.deepcopy(p_el)
    for r in runs[1:]:
        p_el.remove(r)
    runs[0].find(_q(A, "t")).text = numero
    r2 = p2.findall(_q(A, "r"))
    consumido = len(texto) - len(resto)
    for r in r2:
        t = r.find(_q(A, "t"))
        largo = len(t.text or "")
        if consumido >= largo:
            p2.remove(r)
            consumido -= largo
            continue
        t.text = (t.text or "")[consumido:]
        break
    p_el.addnext(p2)
    return True


def separar(pptx: Path, numero: int, forma: str, out: Path, numeros: bool = False) -> dict:
    """Parte la forma (por nombre o id de forma) en una caja por párrafo no vacío.

    Con `numeros`, el número inicial de cada ítem («1.», «02», «a)») pasa a su propio párrafo
    dentro de su caja, para asignarlo al rol `number` de la unidad."""
    prs = Presentation(str(pptx))
    if not 1 <= numero <= len(prs.slides):
        raise ValueError(f"la slide {numero} no existe ({len(prs.slides)} slides)")
    slide = prs.slides[numero - 1]
    objetivo = None
    for shape in slide.shapes:
        if shape.name == forma or str(shape.shape_id) == forma:
            objetivo = shape
            break
    if objetivo is None or not getattr(objetivo, "has_text_frame", False):
        nombres = [s.name for s in slide.shapes if getattr(s, "has_text_frame", False)]
        raise ValueError(f"no encuentro una caja de texto «{forma}» en la slide {numero}; hay: {', '.join(nombres)}")
    sp = objetivo._element
    tx = sp.find(_q(P, "txBody"))
    parrafos = [p for p in tx.findall(_q(A, "p")) if _texto(p).strip()]
    if len(parrafos) < 2:
        raise ValueError(f"«{objetivo.name}» tiene un solo párrafo: no hay nada que separar")
    top, alto = objetivo.top, objetivo.height
    paso = alto // len(parrafos)
    nuevo_id = _siguiente_id(slide)
    padre = sp.getparent()
    posicion = list(padre).index(sp)
    creadas = []
    for i, parrafo in enumerate(parrafos):
        copia = copy.deepcopy(sp)
        cuerpo = copia.find(_q(P, "txBody"))
        for p in cuerpo.findall(_q(A, "p")):
            cuerpo.remove(p)
        nuevo_p = copy.deepcopy(parrafo)
        num = nuevo_p.find(f"{_q(A, 'pPr')}/{_q(A, 'buAutoNum')}")
        if num is not None:
            # La numeración automática seguiría en 1 en cada caja: se fija el número que tenía.
            inicio = int(num.get("startAt", "1"))
            num.set("startAt", str(inicio + i))
        cuerpo.append(nuevo_p)
        if numeros:
            _sacar_numero(nuevo_p)
        cnv = copia.find(f".//{_q(P, 'cNvPr')}")
        cnv.set("id", str(nuevo_id + i))
        cnv.set("name", f"{objetivo.name} · {i + 1}")
        off = copia.find(f".//{_q(A, 'xfrm')}/{_q(A, 'off')}")
        ext = copia.find(f".//{_q(A, 'xfrm')}/{_q(A, 'ext')}")
        if off is not None and ext is not None:
            off.set("y", str(int(top + i * paso)))
            ext.set("cy", str(int(paso)))
        padre.insert(posicion + i, copia)
        creadas.append(f"{objetivo.name} · {i + 1}")
    padre.remove(sp)
    out.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(out))
    return {"slide": numero, "forma": objetivo.name, "cajas_nuevas": creadas, "salida": str(out),
            "texto_igual": _palabras(pptx) == _palabras(out),
            "siguiente": "corre `neo.py leer` sobre el PPTX preparado: los ids de esa slide cambiaron"}
