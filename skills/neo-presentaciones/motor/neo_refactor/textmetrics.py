"""Medición de texto con las métricas reales de Montserrat.

Modelo calibrado contra los PDF exportados por Google Slides:
- alto de línea = tamaño × 1.2 × interlineado (spcPct)
- "Montserrat SemiBold" + negrita se renderiza como Montserrat Bold.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PIL import ImageFont

from .schemas import RPara

FONT_DIR = Path(__file__).resolve().parents[2] / "assets" / "fonts"
LINE_FACTOR = 1.2
NBSP = "\u00a0"

_WEIGHTS = {
    "montserrat": "Regular",
    "montserrat medium": "Medium",
    "montserrat semibold": "SemiBold",
    "montserrat bold": "Bold",
    "montserrat extrabold": "ExtraBold",
    "montserrat black": "Black",
}
_BOLD_BUMP = {"Regular": "Bold", "Medium": "SemiBold", "SemiBold": "Bold"}


def font_file(family: str, bold: bool = False, italic: bool = False) -> Path:
    weight = _WEIGHTS.get(family.lower(), "Regular")
    if bold:
        weight = _BOLD_BUMP.get(weight, weight)
    if italic:
        name = "Italic" if weight == "Regular" else f"{weight}Italic"
    else:
        name = weight
    return FONT_DIR / f"Montserrat-{name}.ttf"


@lru_cache(maxsize=64)
def _font(path: str) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size=1000)


def text_width(text: str, family: str, size: float, bold=False, italic=False) -> float:
    if not text:
        return 0.0
    return _font(str(font_file(family, bold, italic))).getlength(text) * size / 1000


@dataclass
class Line:
    words: list[str]
    width: float
    # La línea abre un tramo tras un salto suave (<a:br>) puesto por el autor.
    after_break: bool = False


_TOKEN = re.compile(r"\n|[ \t]+|[^ \t\n]+")
# UAX #14 (LB13): no se corta antes de estos signos aunque haya un espacio antes
NO_BREAK_BEFORE = set("/!?;:)]}%,.»")
_WORD = re.compile(r"\w")


def wrap(para: RPara, width: float) -> list[Line]:
    """Corte de líneas greedy por palabras (como Google Slides). NBSP une palabras.

    Un párrafo con viñeta corta al ancho que le deja su sangría.
    """
    width -= getattr(para, "indent", 0.0)
    items: list[tuple[str, str, float]] = []  # (tipo, texto, ancho)
    for run in para.runs:
        for tok in _TOKEN.findall(run.text):
            if tok == "\n":
                items.append(("br", tok, 0.0))
                continue
            w = text_width(tok.replace("\t", " "), run.font, run.size, run.bold, run.italic)
            kind = "space" if tok.isspace() else "word"
            # palabras partidas entre runs (p.ej. cambio de color a mitad) se fusionan
            if kind == "word" and items and items[-1][0] == "word":
                _, t0, w0 = items.pop()
                items.append(("word", t0 + tok, w0 + w))
            elif (kind == "word" and tok[0] in NO_BREAK_BEFORE and len(items) >= 2
                  and items[-1][0] == "space" and items[-2][0] == "word"):
                _, sp, ws = items.pop()
                _, t0, w0 = items.pop()
                items.append(("word", t0 + sp + tok, w0 + ws + w))
            else:
                items.append((kind, tok, w))

    lines: list[Line] = []
    cur: list[str] = []
    cur_w = 0.0
    pending = 0.0
    after_break = False
    for kind, tok, w in items:
        if kind == "br":
            lines.append(Line(cur, cur_w, after_break))
            cur, cur_w, pending, after_break = [], 0.0, 0.0, True
        elif kind == "space":
            if cur:
                pending += w
        else:
            if cur and cur_w + pending + w > width:
                lines.append(Line(cur, cur_w, after_break))
                cur, cur_w, after_break = [tok], w, False
            else:
                cur_w += pending + w
                cur.append(tok)
            pending = 0.0
    lines.append(Line(cur, cur_w, after_break))
    return lines


def para_height(para: RPara, width: float) -> float:
    size = max((r.size for r in para.runs), default=11.0)
    return len(wrap(para, width)) * size * LINE_FACTOR * para.line + para.space_before


def block_height(paras: list[RPara], width: float) -> float:
    return sum(para_height(p, width) for p in paras)


def max_line_width(paras: list[RPara], width: float) -> float:
    return max((ln.width + getattr(p, "indent", 0.0) for p in paras for ln in wrap(p, width)), default=0.0)


# Una palabra sola que llena al menos esta fracción del ancho no cuelga: es una URL o un término
# largo que tampoco cabría junto a la anterior («(tienda.claro.com.pe).» ocupaba el 67 %).
ORPHAN_MAX_FILL = 0.5


def is_orphan(para: RPara, width: float) -> bool:
    """Huérfana = párrafo de ≥3 palabras y ≥2 líneas cuya última línea tiene una sola palabra visible
    y corta (menos de `ORPHAN_MAX_FILL` del ancho).
    (Un texto de dos palabras partido 1 + 1 no es una huérfana: es un corte simétrico.)"""
    lines = [ln for ln in wrap(para, width) if ln.words]
    if len(lines) < 2 or sum(_visible_words(w) for ln in lines for w in ln.words) < 3:
        return False
    # Una línea que empieza tras un salto suave es un corte del autor, no una huérfana:
    # solo cuenta si el último tramo se partió por ancho.
    if lines[-1].after_break:
        return False
    return sum(_visible_words(w) for w in lines[-1].words) == 1 and lines[-1].width < width * ORPHAN_MAX_FILL


def _visible_words(token: str) -> int:
    """Palabras visibles de un token (NBSP y signos pegados no cuentan como palabras)."""
    return sum(1 for piece in re.split(r"[\s\u00a0]+", token) if _WORD.search(piece))


def orphan_free(para: RPara, width: float, safety: float) -> bool:
    """Sin huérfanas en todo el rango de anchos [safety·w, w] (margen frente al motor de Google)."""
    steps = 4
    return not any(is_orphan(para, width * (safety + (1 - safety) * k / steps)) for k in range(steps + 1))


def overflows_width(para: RPara, width: float) -> bool:
    """True si alguna palabra (o grupo unido por NBSP) no cabe sola en el ancho: se cortaría a la mitad."""
    return any(ln.width > width + 0.01 for ln in wrap(para, width))


def bind_last_words(para: RPara) -> RPara:
    """Une con NBSP las dos últimas palabras visibles del párrafo.

    Los signos sueltos («&», «-», «|») no son palabras: «Talento & Cultura» une los tres
    tokens, porque unir solo «& Cultura» dejaría «Cultura» igual de sola. Nunca cruza un
    salto suave ni entra en un hipervínculo (algunos visores cortan mal ahí).
    """
    if para.runs and para.runs[-1].hyperlink:
        return para
    runs = [r.model_copy() for r in para.runs]
    chars = [(k, i) for k, r in enumerate(runs) for i in range(len(r.text))]
    text = "".join(r.text for r in runs)
    end = len(text.rstrip())
    words, spaces, position = 0, [], end
    while position > 0:
        start = position
        while start > 0 and text[start - 1] not in " \n":
            start -= 1
        words += _visible_words(text[start:position])
        if words >= 2 or start == 0 or text[start - 1] == "\n":
            break
        spaces.append(start - 1)
        position = start - 1
        while position > 0 and text[position - 1] == " ":
            position -= 1
    if words < 2 or not spaces:
        return para
    edits: dict[int, list[str]] = {}
    for index in spaces:
        k, i = chars[index]
        edits.setdefault(k, list(runs[k].text))[i] = NBSP
    for k, chars_k in edits.items():
        runs[k].text = "".join(chars_k)
    return para.model_copy(update={"runs": runs})
