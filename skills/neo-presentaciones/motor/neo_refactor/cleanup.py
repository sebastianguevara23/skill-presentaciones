"""Limpieza de contenido por decisión de marca, antes de rediseñar.

Son las excepciones de `plans/convenciones.md` a "no se cambia el contenido":
- los emojis se eliminan (el diseño pone sus propios íconos),
- el texto tachado es una corrección del autor ("~~2030~~ 2027") y se elimina;
- los prompts de trabajo incrustados accidentalmente en una slide se eliminan.

Se trabaja sobre el XML de todas las slides (ocultas incluidas), así que el resto del
motor, y el chequeo de integridad, parten del deck ya limpio.
"""
from __future__ import annotations

import re
from pathlib import Path

from pptx import Presentation
from pptx.oxml.ns import qn

# pictogramas, dingbats, selectores de variante y ZWJ. Las flechas tipográficas (→) no
# son emojis y se quedan.
EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF\u2300-\u23FF\u2600-\u27BF\u2B00-\u2BFF\uFE0E\uFE0F\u200D\u20E3]"
)
_EMOJI_RUN = re.compile(f"([ \t]*)((?:{EMOJI.pattern})+)([ \t]*)")
# Un emoji solo entre paréntesis o corchetes («(🚀)») se va con ellos.
_EMOJI_ALONE = re.compile(f"[ \t]*[(\\[][ \t]*(?:{EMOJI.pattern})+[ \t]*[)\\]]")
_EMOJI_AT_START = re.compile(f"[ \t]*(?:{EMOJI.pattern})")
_EMOJI_AT_END = re.compile(f"(?:{EMOJI.pattern})[ \t]*$")
_EMBEDDED_PROMPT = re.compile(r"^\s*Necesito un slide\b", re.IGNORECASE)
# Lo que se pega a la palabra anterior: sin el emoji, el espacio que los separaba sobra
# («como 🚀✨💡, sin» quedaba «como , sin» en el deck liberado de IA, 2026-10-27).
CLOSERS = ",.;:!?)]»…"
OPENERS = "([«¿¡"


def _emoji_gap(match: re.Match) -> str:
    before, after = match.string[:match.start()], match.string[match.end():]
    if not before or before[-1] in OPENERS or not after or after[0] in CLOSERS:
        return ""
    return " " if match.group(1) or match.group(3) else ""


def strip_emojis(text: str) -> str:
    """Quita los emojis sin dejar espacios sueltos: entre palabras queda uno; antes de una
    coma o un cierre, y al principio o al final, ninguno."""
    return _EMOJI_RUN.sub(_emoji_gap, _EMOJI_ALONE.sub("", text))


def strip_emojis_in_runs(texts: list[str]) -> list[str]:
    """`strip_emojis` en los runs de un párrafo, mirando los vecinos: si el emoji era un run
    propio, el espacio del run anterior también sobra delante de la coma que sigue."""
    result: list[str] = []
    gap = False   # se quitó un emoji justo antes de este run
    for text in texts:
        clean = strip_emojis(text)
        if (gap or _EMOJI_AT_START.match(text)) and clean and clean[0] in CLOSERS:
            for k in range(len(result) - 1, -1, -1):
                result[k] = result[k].rstrip(" \t")
                if result[k]:
                    break
        result.append(clean)
        gap = bool(_EMOJI_AT_END.search(text)) or (gap and not clean.strip())
    return result


def has_emoji(text: str) -> bool:
    return bool(EMOJI.search(text))


def _struck(run) -> bool:
    rpr = run.find(qn("a:rPr"))
    return rpr is not None and rpr.get("strike") in ("sngStrike", "dblStrike")


def strip_slide_emojis(slide) -> list[str]:
    """Quita los emojis de los runs de una slide ya abierta; devuelve los que quitó.

    Es el mismo corte de `clean_deck`, para las slides que el rediseño conserva (brand
    shell): el rediseño parte del deck original para no mover los ids del plan.
    """
    removed = []
    for p in slide._element.iter(qn("a:p")):
        runs = [(r, r.find(qn("a:t"))) for r in p.findall(qn("a:r"))]
        runs = [(r, t) for r, t in runs if t is not None and t.text]
        if not any(has_emoji(t.text) for _r, t in runs):
            continue
        removed += ["".join(EMOJI.findall(t.text)) for _r, t in runs if has_emoji(t.text)]
        for (r, t), clean in zip(runs, strip_emojis_in_runs([t.text for _r, t in runs])):
            t.text = clean
            if not clean:
                p.remove(r)
    return removed


def clean_deck(src: Path, dst: Path) -> dict:
    """Copia `src` sin emojis, tachados ni prompts de trabajo incrustados."""
    prs = Presentation(str(src))
    report: dict[int, dict] = {}
    for idx, slide in enumerate(prs.slides, 1):
        struck, prompts = [], []
        for shape in list(slide.shapes):
            if not getattr(shape, "has_text_frame", False):
                continue
            if _EMBEDDED_PROMPT.search(shape.text_frame.text or ""):
                prompts.append(shape.text_frame.text.strip())
                shape._element.getparent().remove(shape._element)
        for p in slide._element.iter(qn("a:p")):
            for r in list(p.findall(qn("a:r"))):
                t = r.find(qn("a:t"))
                if t is not None and t.text and _struck(r):
                    struck.append(t.text)
                    p.remove(r)
        emojis = strip_slide_emojis(slide)
        if emojis or struck or prompts:
            report[idx] = {"emojis": emojis, "struck_text": struck, "embedded_prompts": prompts}
    dst.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(dst))
    return report
