"""SlideSpec + SlideClassification + Knowledge -> RenderedSlide.

El composer decide todas las coordenadas por reglas; el LLM solo asigna bloques a slots.
El texto nunca se reescribe: solo se re-estiliza, se reubica y, si hace falta, se une
con NBSP para evitar huérfanas.
"""
from __future__ import annotations

import dataclasses
import itertools

import re

from PIL import Image

from . import cobrand, textmetrics as tm
from .cleanup import strip_emojis_in_runs
from .cobrand import ClientLogo
from .design_policies import centered_body_top
from .icon_tint import glyph_color, tint
from .knowledge import Knowledge, Style, nearest_color as nearest
from .schemas import (
    Box, ImageBlock, Paragraph, RenderedSlide, RPara, RPicture, RRect, RRun, RText,
    SlideClassification, SlideSpec, TextBlock,
)

_ALIGN = {"l": "l", "ctr": "ctr", "r": "r"}
# Sangría por nivel de una viñeta del autor (pt): la viñeta cuelga en ella.
BULLET_INDENT = 12.0
# Sangría de un ítem numerado, en em del texto: «8.» ocupa casi un em y necesita aire después.
NUMBER_INDENT_EM = 1.5
# Resolución mínima al ampliar una imagen (1 px por punto): una GIF de 160 px a 333 pt ya
# se ve pixelada; a 72 ppi una ilustración de 400 px sigue nítida en pantalla.
MIN_PPI = 72
# Clases de imagen (`asset_classes` del plan) que conservan sus colores aunque vayan en el
# lugar de un ícono: un logo de partner en negro no es un glifo de NEO.
KEEP_ICON_COLORS = {"logo", "client_logo", "source", "photo", "screenshot", "chart", "diagram"}


# ---------------------------------------------------------------- texto


def restyle(par: Paragraph, st: Style, kn: Knowledge, *, inline_bold: bool = False, align: str = "l") -> RPara:
    """Aplica un estilo de rol a un párrafo conservando su texto, links, cursivas y negritas internas.

    Los emojis se quitan aquí (convenciones: el diseño pone sus propios íconos): así el
    párrafo sigue contando para los roles del plan aunque quede vacío.
    """
    clean = strip_emojis_in_runs([r.text for r in par.runs])
    par = par.model_copy(update={"runs": [r.model_copy(update={"text": t}) for r, t in zip(par.runs, clean)]})
    visible = [r for r in par.runs if r.text.strip()]
    bold_chars = sum(len(r.text.strip()) for r in visible if r.bold)
    total = sum(len(r.text.strip()) for r in visible)
    mixed_bold = inline_bold and 0 < bold_chars < total
    highlighted = _author_highlights(visible, kn)
    runs: list[RRun] = []
    for r in _trim(par.runs):
        font, color, italic = st.font, st.color, st.italic
        if mixed_bold and r.bold and st.emphasis:
            font, color = st.emphasis.font, st.emphasis.color
        elif (r.color or "").upper() in highlighted:
            # Resaltado del autor (un tramo en otro color de la paleta): se conserva su color si
            # contrasta con el contexto del rol; si no, el énfasis del rol. Antes se pintaba todo
            # del color del rol y el resaltado se perdía (Tienda Claro, 2026-10-01).
            author = r.color.upper()
            light_context = (st.color or "").upper() in DARK_TEXT
            if author in (DARK_TEXT | {"2D5BFF"} if light_context else LIGHT_TEXT):
                color = author
            elif st.emphasis:
                color = st.emphasis.color
        if inline_bold and r.italic:
            italic = True
        if r.font in kn.exempt_families:
            font = r.font
        if r.hyperlink:
            color = kn.tokens["brand_rules"]["hyperlink_color"]
        runs.append(RRun(text=r.text, font=font, size=st.size, bold=st.bold, italic=italic,
                         color=color, hyperlink=r.hyperlink))
    indent = max(BULLET_INDENT, round(st.size * NUMBER_INDENT_EM, 1)) if par.numbering else BULLET_INDENT
    return RPara(runs=_merge(runs), align=align, line=st.line, bullet=par.bullet,
                 indent=indent * (par.level + 1) if par.bullet else 0.0,
                 numbering=par.numbering, start_at=par.start_at)


# Colores de texto que contrastan sobre fondo claro (DARK_TEXT) y sobre fondo oscuro (LIGHT_TEXT).
DARK_TEXT = {"000033", "000000"}
LIGHT_TEXT = {"FFFFFF", "C5D5F7", "7E99FE", "9AAFFE"}


def _author_highlights(visible, kn: Knowledge) -> set[str]:
    """Colores con los que el autor resalta tramos de un párrafo de varios colores.

    El color mayoritario (por caracteres) es el del texto; los demás que están en la paleta de
    marca son resaltados. Un párrafo de un solo color no tiene resaltados: su color lo da el rol.
    """
    weight: dict[str, int] = {}
    for r in visible:
        color = (r.color or "").upper()
        weight[color] = weight.get(color, 0) + len(r.text.strip())
    if len(weight) < 2:
        return set()
    main = max(weight, key=weight.get)
    palette = {c.upper() for c in kn.tokens["brand_rules"]["text_colors"]}
    return {c for c in weight if c and c != main and c in palette}


def _trim(runs):
    """Quita espacios/tabs al inicio y final del párrafo (no son contenido; el integrity los normaliza)."""
    runs = [r.model_copy() for r in runs]
    while runs and not runs[0].text.strip(" \t"):
        runs.pop(0)
    while runs and not runs[-1].text.strip(" \t"):
        runs.pop()
    if runs:
        runs[0].text = runs[0].text.lstrip(" \t")
        runs[-1].text = runs[-1].text.rstrip(" \t")
    return runs


def _merge(runs: list[RRun]) -> list[RRun]:
    out: list[RRun] = []
    for r in runs:
        if out and out[-1].model_dump(exclude={"text"}) == r.model_dump(exclude={"text"}):
            out[-1] = out[-1].model_copy(update={"text": out[-1].text + r.text})
        else:
            out.append(r)
    return out


def emphasize(para: RPara, phrase: str, emph: Style) -> tuple[RPara, bool]:
    text = para.text
    i = text.find(phrase)
    if i < 0 or not phrase:
        return para, False
    j = i + len(phrase)
    out, pos = [], 0
    for r in para.runs:
        a, b = pos, pos + len(r.text)
        pos = b
        for s, e, flag in ((a, min(b, i), False), (max(a, i), min(b, j), True), (max(a, j), b, False)):
            if e > s:
                seg = r.text[s - a:e - a]
                upd = {"text": seg}
                if flag:
                    upd.update(font=emph.font, color=emph.color, italic=emph.italic)
                out.append(r.model_copy(update=upd))
    return para.model_copy(update={"runs": _merge(out)}), True


def resize(paras: list[RPara], size: float) -> list[RPara]:
    return [p.model_copy(update={"runs": [r.model_copy(update={"size": size}) for r in p.runs]}) for p in paras]


def n_lines(paras: list[RPara], width: float) -> int:
    return sum(len(tm.wrap(p, width)) for p in paras)


def fix_orphans(paras: list[RPara], width: float, min_width: float, safety: float,
                max_lines: int | None = None) -> tuple[list[RPara], float, list[str]]:
    """Orden acordado: 1) ajustar ancho, 2) (tamaño lo maneja el fit de overflow), 3) NBSP."""
    def ok(ps, w):
        return all(tm.orphan_free(p, w, safety) for p in ps) and (max_lines is None or n_lines(ps, w) <= max_lines)

    if ok(paras, width):
        return paras, width, []
    base_lines = n_lines(paras, width)
    w = width
    while w - width * 0.02 >= min_width:
        w -= width * 0.02
        if ok(paras, w) and n_lines(paras, w) <= base_lines:
            return paras, w, []
    fixed = []
    for p in paras:
        bound = tm.bind_last_words(p)
        # NBSP solo si las dos palabras unidas caben en la línea (si no, se cortarían a la mitad)
        use = not tm.orphan_free(p, width, safety) and not tm.overflows_width(bound, width * safety)
        fixed.append(bound if use else p)
    issues = [] if ok(fixed, width) else ["orphan_unresolved"]
    return fixed, width, issues


def fit_heading(paras: list[RPara], st: Style, width: float, max_lines: int, safety: float,
                min_width_ratio: float = 0.6) -> tuple[list[RPara], float, float, list[str]]:
    """Reduce tamaño (hasta st.min) si excede max_lines y luego corrige huérfanas.

    Solo se reducen los runs del título: una bajada dentro del título (`title_tail`) ya
    tiene su tamaño.
    """
    size = st.size
    floor = max(st.min or st.size, 11)
    while n_lines(paras, width * safety) > max_lines and size - 1 >= floor:
        paras = [p.model_copy(update={"runs": [r.model_copy(update={"size": size - 1}) if r.size == size else r
                                               for r in p.runs]}) for p in paras]
        size -= 1
    issues = [] if n_lines(paras, width * safety) <= max_lines else ["heading_too_long"]
    paras, w, orphan_issues = fix_orphans(paras, width, width * min_width_ratio, safety, max_lines)
    return paras, w, size, issues + orphan_issues


def make_text(role: str, paras: list[RPara], x: float, y: float, w: float, group: str,
              sources: list[str], safety: float) -> RText:
    """Caja de texto con alto medido al ancho reducido por el margen de seguridad (conservador)."""
    h = tm.block_height(paras, w * safety)
    return RText(role=role, box=Box(x=x, y=y, w=round(w, 2), h=round(h + 2, 2)), paras=paras,
                 group=group, sources=sources)


def hug_width(paras: list[RPara], safety: float) -> float:
    """Ancho de una caja de una línea que sigue siendo de una línea con el margen de seguridad."""
    return tm.max_line_width(paras, 10_000) / safety + 2


# ---------------------------------------------------------------- composer


def _overflows(rendered: RenderedSlide) -> bool:
    return any("overflow" in issue for issue in rendered.compose_issues)


# El encabezado no se escala con la excepción de tamaño: lo que no cabe es el contenido. La cita
# de fuente tampoco: tiene su tamaño fijo (`typography.citation`) y compactar la subía a 11 pt.
_HEADER_STYLES = ("title", "kicker", "subtitle", "section", "closing", "cover", "citation")


class _ScaledKnowledge:
    """`Knowledge` con la letra del contenido multiplicada por `factor`, nunca bajo `floor`."""

    def __init__(self, kn: Knowledge, factor: float, floor: float):
        self._kn, self._factor, self._floor = kn, factor, floor

    def __getattr__(self, name):
        return getattr(self._kn, name)

    def _scaled(self, st: Style) -> Style:
        # El piso de cada estilo (`min` del token) vale si `floor` es el de marca: compactar dentro
        # de la marca no lleva un título de card bajo su mínimo, solo lo acerca a él.
        compact = self._floor >= self._kn.min_size
        floor = max(self._floor, st.min or 0) if compact else self._floor
        size = max(floor, round(st.size * self._factor, 1))
        low = max(floor, round((st.min or st.size) * self._factor, 1))
        emphasis = self._scaled(st.emphasis) if st.emphasis else None
        # Al compactar dentro de la marca, el cuerpo ya está en 11 pt: lo que queda es el
        # interlineado, que se cierra hasta 1.0 (nunca menos: las líneas no se pisan).
        line = max(1.0, round(st.line * self._factor, 3)) if compact and st.line > 1.0 else st.line
        return dataclasses.replace(st, size=size, min=min(low, size), line=line, emphasis=emphasis)

    def style(self, mode: str, role: str) -> Style:
        st = self._kn.style(mode, role)
        return st if role.startswith(_HEADER_STYLES) else self._scaled(st)


class _StyledKnowledge:
    """`Knowledge` con los cambios de estilo que pidió la persona (`StyleOverride`) encima.

    Va por fuera de `_ScaledKnowledge`: un tamaño pedido explícitamente no se compacta.
    """

    def __init__(self, kn, overrides: list):
        self._kn, self._overrides = kn, overrides

    def __getattr__(self, name):
        return getattr(self._kn, name)

    def style(self, mode: str, role: str) -> Style:
        from .schemas import FONT_WEIGHTS

        st = self._kn.style(mode, role)
        for item in self._overrides:
            if not item.matches(role):
                continue
            if item.weight:
                font, bold = FONT_WEIGHTS[item.weight]
                st = dataclasses.replace(st, font=font, bold=bold)
            if item.size_pt:
                st = st.resized(item.size_pt)
                st = dataclasses.replace(st, min=item.size_pt)
            if item.italic is not None:
                st = dataclasses.replace(st, italic=item.italic)
            if item.color:
                st = dataclasses.replace(st, color=self._kn.color(item.color))
        return st


class Composer:
    def __init__(self, kn: Knowledge, asset_classes: dict[int, dict[str, str]] | None = None,
                 client_logo: ClientLogo | None = None):
        self.kn = kn
        self.safety = kn.safety
        # Clase de cada imagen por slide (`asset_classes` del plan): un logo puesto en el lugar
        # de un ícono conserva sus colores.
        self.asset_classes = asset_classes or {}
        # Logo del cliente (`asset_classes` → client_logo): la marca de cada slide es el bloque
        # NEO | cliente (`cobrand.py`).
        self.client_logo = client_logo

    # -- helpers
    def _tx(self, role, paras, x, y, w, group, sources) -> RText:
        return make_text(role, paras, x, y, w, group, sources, self.safety)

    def _paras(self, block: TextBlock, st: Style, **kw) -> list[RPara]:
        return [rp for rp in (restyle(p, st, self.kn, **kw) for p in block.paragraphs if p.text.strip())
                if rp.text.strip()]

    def brand_elements(self, mode: str, centered: bool = False) -> list:
        b = self.kn.tokens["brand"]
        lx, ly, lw, lh = b["logo"]["centered_box" if centered else "box"]
        px, py, pw, ph = b["phrase"]["centered_box" if centered else "box"]
        ps = b["phrase"][mode]
        run = RRun(text=b["phrase"]["text"], font=ps["font"], size=ps["size"], bold=ps["bold"],
                   color=self.kn.color(ps["color"]))
        para = RPara(runs=[run], align="ctr" if centered else "l")
        phrase = RText(role="brand_phrase", box=Box(x=px, y=py, w=pw, h=ph), paras=[para], group="brand", brand=True)
        if self.client_logo is not None:
            return [*cobrand.elements(self.kn, self.client_logo, Box(x=lx, y=ly, w=lw, h=lh), mode,
                                      align="center" if centered else "left"), phrase]
        return [
            RPicture(role="brand_logo", box=Box(x=lx, y=ly, w=lw, h=lh),
                     path=self.kn.path(b["logo"][mode]), group="brand", brand=True),
            phrase,
        ]

    def _base(self, spec: SlideSpec, cls: SlideClassification, mode: str) -> RenderedSlide:
        return RenderedSlide(
            source_index=spec.index, layout=cls.layout, mode=mode,
            background=self.kn.path(self.kn.tokens["brand"]["backgrounds"][mode]),
            elements=self.brand_elements(mode), notes=spec.notes,
        )

    def compose(self, spec: SlideSpec, cls: SlideClassification) -> RenderedSlide:
        def build(kn) -> "Composer":
            # Lo que pidió la persona va siempre encima: también al compactar o bajar la letra.
            return Composer(_StyledKnowledge(kn, cls.style_overrides) if cls.style_overrides else kn,
                            self.asset_classes, self.client_logo)

        rendered = build(self.kn)._compose_once(spec, cls)
        if cls.font_floor:
            rendered.font_floor = cls.font_floor
        if not _overflows(rendered):
            return rendered
        # Desborde chico (s12 de Prueba 2 no cabía por 1 pt): antes de rendirse se compacta dentro de
        # la marca. Bajan solo los estilos por encima de su mínimo (títulos, cifras); el cuerpo
        # sigue a 11 pt. Ningún texto se resume.
        for factor in (0.95, 0.9, 0.85):
            trial = build(_ScaledKnowledge(self.kn, factor, self.kn.min_size))._compose_once(spec, cls)
            if not _overflows(trial):
                trial.font_floor = cls.font_floor
                trial.compose_issues.append(f"brand_compaction:{factor:g}")
                return trial
        if not cls.font_floor:
            return rendered
        # Excepción autorizada por la persona («baja la letra para que entre todo»): se recompone
        # con la letra del contenido un 5 % menor cada vez, sin pasar del piso autorizado.
        factor = 1.0
        while self.kn.min_size * factor > cls.font_floor + 0.01:
            factor = max(round(factor - 0.05, 2), cls.font_floor / self.kn.min_size)
            trial = build(_ScaledKnowledge(self.kn, factor, cls.font_floor))._compose_once(spec, cls)
            if not _overflows(trial):
                trial.font_floor = cls.font_floor
                trial.compose_issues.append(f"font_floor_exception:{factor:g}")
                return trial
        return rendered

    def _compose_once(self, spec: SlideSpec, cls: SlideClassification) -> RenderedSlide:
        rendered = {
            "section": self._section, "three_cards": self._three_cards, "metrics_row": self._metrics_row,
            "card_grid": self._card_grid, "item_list": self._item_list, "team_grid": self._team_grid,
            "image_text": self._image_text, "circles": self._circles, "closing": self._closing,
            "matrix": self._matrix, "list_aside": self._list_aside, "quadrant": self._quadrant,
            "sections": self._sections, "free": self._free,
        }[cls.layout](spec, cls)
        from .design_policies import keep_white_card_variant
        keep_white_card_variant(rendered, spec, self.kn)
        if cls.layout == "three_cards" and cls.variant != "template":
            from .design_policies import balance_text_cards
            balance_text_cards(rendered,self.kn)
        elif cls.layout == "card_grid" and cls.variant != "template":
            from .design_policies import center_card_composition
            center_card_composition(rendered, self.kn)
        return rendered

    def _title(self, spec, cls, mode, role, width, max_lines, size: float | None = None, cover: bool = False):
        st = self.kn.style(mode, role)
        if size:
            st = st.resized(size)
        paras = [self._title_tail(p, st, mode) for p in spec.text_by_id(cls.title).paragraphs if p.text.strip()]
        paras = [p for p in paras if p.text.strip()]
        issues = []
        # Sin énfasis explícito en la clasificación, vale el que ya marca el autor.
        phrase = cls.title_emphasis or self.author_emphasis(spec.text_by_id(cls.title).paragraphs)
        if cover and not phrase:
            # La portada clara siempre lleva su tramo en azul, aunque el plan no lo indique.
            from .design_policies import cover_emphasis
            phrase = cover_emphasis([p.text for p in paras])
        if phrase and st.emphasis:
            for k, p in enumerate(paras):
                p2, hit = emphasize(p, phrase, st.emphasis)
                if hit:
                    paras[k] = p2
                    break
            else:
                issues.append(f"emphasis_not_found:{phrase!r}")
        paras, w, _, fit_issues = fit_heading(paras, st, width, max_lines, self.safety)
        return paras, w, issues + fit_issues

    def author_emphasis(self, paragraphs: list[Paragraph]) -> str | None:
        """Fragmento que el autor ya marcó en el título: runs en un azul de la paleta o en
        itálica frente al resto. Devuelve el primer tramo contiguo; None si todo el título
        (o nada) está marcado."""
        rules = self.kn.tokens["brand_rules"]
        plain = {"000000", "FFFFFF", "000033"}
        accents = [c.upper() for c in rules["text_colors"] if c.upper() not in plain]

        def marked(run) -> bool:
            color = (run.color or "").upper()
            if run.italic:
                return True
            if len(color) != 6 or color in plain:
                return False
            return nearest(color, [c.upper() for c in rules["text_colors"]]) in accents

        runs = [r for p in paragraphs for r in p.runs]
        visible = [r for r in runs if r.text.strip()]
        flags = [marked(r) for r in visible]
        if not visible or all(flags) or not any(flags):
            return None
        phrase, started = "", False
        for p in paragraphs:
            for r in p.runs:
                if not r.text.strip():
                    if started:
                        phrase += r.text
                    continue
                if marked(r):
                    phrase += r.text
                    started = True
                elif started:
                    return phrase.strip() or None
            if started:
                break  # el tramo no cruza párrafos
        return phrase.strip() or None

    def _title_tail(self, par: Paragraph, st: Style, mode: str) -> RPara:
        """Título con bajada del autor: tras un salto de línea, un tramo a la mitad del tamaño
        o menos (p. ej. «Status» + «(Ventas - Ingresos - …)»).

        La jerarquía la puso el origen; se conserva con el estilo de subtítulo del modo en
        vez de agrandar la bajada al tamaño del título. No cambia ninguna palabra.
        """
        runs = par.runs
        breaks = [k for k, run in enumerate(runs) if run.text == "\n"]
        sizes = [run.size for run in runs if run.size and run.text.strip()]
        if not breaks or not sizes:
            return restyle(par, st, self.kn)
        cut = breaks[-1]
        tail = [run for run in runs[cut + 1:] if run.text.strip()]
        head = [run for run in runs[:cut] if run.text.strip()]
        if not tail or not head or any(not run.size or run.size > max(sizes) / 2 for run in tail):
            return restyle(par, st, self.kn)
        sub = self.kn.style(mode, "subtitle")
        top = restyle(par.model_copy(update={"runs": runs[:cut]}), st, self.kn)
        bottom = restyle(par.model_copy(update={"runs": runs[cut + 1:]}), sub, self.kn)
        br = top.runs[-1].model_copy(update={"text": "\n"})
        return top.model_copy(update={"runs": [*top.runs, br, *bottom.runs]})

    def _header(self, spec, cls, out: RenderedSlide, title_role: str, max_lines: int,
                title_size: float | None = None, title_indent: float = 0.0, title_width: float | None = None) -> float:
        """Kicker, título y subtítulo; devuelve el borde inferior. La composición libre puede
        correr el título (`title_indent`, junto a la barra de acento) y angostarlo (`title_width`,
        para la nota a su derecha)."""
        g = self.kn.geometry(cls.layout)
        x, width = g["x"], g["width"]
        y = g["title_top"]
        if cls.kicker:
            kp = self._paras(spec.text_by_id(cls.kicker), self.kn.style("light", "kicker"))
            kp, kw, iss = fix_orphans(kp, width, width, self.safety)
            out.compose_issues += iss
            out.elements.append(self._tx("kicker", kp, x, g["kicker_top"], kw, "header", [cls.kicker]))
            y = g["title_top_with_kicker"]
        bottom = y
        if cls.title:
            room = (title_width or width) - title_indent
            tp, tw, iss = self._title(spec, cls, "light", title_role, room, max_lines, title_size)
            out.compose_issues += iss
            title = self._tx("title", tp, x + title_indent, y, tw, "header", [cls.title])
            out.elements.append(title)
            bottom = title.box.bottom
        if cls.subtitle:
            sp = self._paras(spec.text_by_id(cls.subtitle), self.kn.style("light", "subtitle"), inline_bold=True)
            width = title_width or width
            sp, sw, iss = fix_orphans(sp, width, width * 0.85, self.safety)
            out.compose_issues += iss
            gap = g["subtitle_gap"] if cls.title else 0
            sub = self._tx("subtitle", sp, x, bottom + gap, sw, "header", [cls.subtitle])
            out.elements.append(sub)
            bottom = sub.box.bottom
        return bottom

    def _notes(self, spec, cls, out: RenderedSlide):
        """Notas / links en la línea del footer, a la derecha (no compiten con el cuerpo).

        Caben en una fila → van lado a lado en el orden del origen (p. ej. «Programa ·
        Taller 1» y el número de página). Si no, se apilan hacia arriba desde el footer.
        """
        if not cls.notes:
            return
        mode = out.mode if out.mode in self.kn.tokens["styles"] and "note" in self.kn.tokens["styles"][out.mode] \
            else "light"
        note_style, citation_style = self.kn.style(mode, "note"), self.kn.style(mode, "citation")
        phrase_x, y, phrase_w, phrase_h = self.kn.tokens["brand"]["phrase"]["box"]
        right = self.kn.tokens["canvas"]["width"] - self.kn.tokens["margins"]["right"]
        gap = 14.0
        room = right - (phrase_x + phrase_w + gap)
        built = []
        for nid in cls.notes:
            # Una lista con viñetas se lee alineada a la izquierda aunque su caja vaya a la derecha.
            listed = any(p.bullet for p in spec.text_by_id(nid).paragraphs)
            # Una cita de fuente va chica y en navy, igual en todas las slides (`typography.citation`).
            style = citation_style if self.kn.is_citation(spec.text_by_id(nid).text) else note_style
            paras = self._paras(spec.text_by_id(nid), style, align="l" if listed else "r", inline_bold=True)
            # Todo el ancho libre a la derecha de la frase: una línea menos es menos alto robado al cuerpo.
            width = min(room, hug_width(paras, self.safety))
            # Una nota que se parte en dos líneas se equilibra: sin palabra sola al final.
            paras, width, iss = fix_orphans(paras, width, width * 0.6, self.safety)
            out.compose_issues += iss
            built.append((nid, paras, width))
        if sum(w for _, _, w in built) + gap * (len(built) - 1) <= room and all(
            tm.block_height(p, w * self.safety) <= phrase_h + 0.5 for _, p, w in built
        ):
            x = right
            for nid, paras, w in reversed(built):
                x -= w
                el = self._tx("note", paras, x, y, w, f"note:{nid}", [nid])
                el.box.h = phrase_h   # misma caja que la frase de marca: termina en la zona segura
                out.elements.append(el)
                x -= gap
            return
        for nid, paras, w in reversed(built):
            el = self._tx("note", paras, right - w, y, w, f"note:{nid}", [nid])
            el.box.y = round(y + phrase_h - el.box.h, 2) if el.box.h > phrase_h else y
            out.elements.append(el)
            y = el.box.y - 16

    def _notes_top(self, spec, cls, out: RenderedSlide) -> float:
        """Borde superior de las notas ya ubicadas (o el límite inferior si no hay): lo que un
        componente que crece para llenar la slide no debe invadir."""
        scratch = out.model_copy(update={"elements": []})
        self._notes(spec, cls, scratch)
        bottom = self.kn.tokens["margins"]["bottom_limit"]
        return min([bottom, *(el.box.y for el in scratch.elements)])

    # -- layouts
    def _section(self, spec: SlideSpec, cls: SlideClassification) -> RenderedSlide:
        mode = "light" if cls.family == "title_slide" or spec.index == 1 else "dark"
        out = self._base(spec, cls, mode)
        g = self.kn.geometry("section")
        x, width = g["x"], g["width"]
        # La portada clara usa su propio estilo: 45 pt navy con el énfasis en azul, sin itálica.
        tp, tw, iss = self._title(spec, cls, mode, "cover_title" if mode == "light" else "title", width, 2,
                                  cover=mode == "light")
        out.compose_issues += iss
        lines = n_lines(tp, tw)
        if lines > 1:   # en dos líneas o más el título va más apretado (section.yaml)
            tp = [p.model_copy(update={"line": self.kn.layouts["section"]["typography"]["multiline_line"]})
                  for p in tp]
        top = g["title_top_one_line"] if lines <= 1 else g["title_top_two_lines"]
        title = self._tx("title", tp, x, top, tw, "header", [cls.title])
        out.elements.append(title)
        if mode == "dark" and len(spec.text_by_id(cls.title).text.split()) == 1:
            from .design_policies import separator_companion
            out.elements.extend(separator_companion(self.kn))
        if cls.kicker:
            kp = self._paras(spec.text_by_id(cls.kicker), self.kn.style(mode, "kicker"))
            kh = tm.block_height(kp, width) + 2
            out.elements.append(self._tx("kicker", kp, x, top - g["kicker_gap"] - kh, width, "header", [cls.kicker]))
        if cls.subtitle:
            sp = self._paras(spec.text_by_id(cls.subtitle), self.kn.style(mode, "subtitle"), inline_bold=True)
            sp, sw, iss = fix_orphans(sp, width * 0.6, width * 0.5, self.safety)
            out.compose_issues += iss
            out.elements.append(self._tx("subtitle", sp, x, title.box.bottom + g["subtitle_gap"], sw, "header",
                                        [cls.subtitle]))
        self._notes(spec, cls, out)
        return out

    @staticmethod
    def _unit_block(spec: SlideSpec, card) -> TextBlock:
        """Los textos de una unidad unidos en un bloque, en el orden del plan."""
        blocks = [spec.text_by_id(text_id) for text_id in card.text_ids]
        if len(blocks) == 1:
            return blocks[0]
        return blocks[0].model_copy(update={"paragraphs": [p for block in blocks for p in block.paragraphs]})

    @staticmethod
    def _corner_tag(spec: SlideSpec, card) -> str | None:
        """Etiqueta breve que el origen pone en la misma línea que el rótulo de la unidad, a
        la derecha («SESIÓN #» … «#H»): se compone en esa línea en vez de apilarse."""
        if not card.extra_texts or len(card.roles) < 2 or card.roles[0] != "label":
            return None
        head, tag = spec.text_by_id(card.text), spec.text_by_id(card.extra_texts[0])
        head_p = [p for p in head.paragraphs if p.text.strip()]
        tag_p = [p for p in tag.paragraphs if p.text.strip()]
        if len(head_p) != 1 or len(tag_p) != 1 or len(tag_p[0].text.strip()) > 12:
            return None
        same_line = abs((head.box.y + head.box.h / 2) - (tag.box.y + tag.box.h / 2)) <= max(head.box.h, 6)
        return tag.id if same_line and tag.box.x >= head.box.x + head.box.w * 0.5 else None

    def _unit_style(self, prefix: str, role: str, sizes: dict[str, float]) -> tuple[Style, str]:
        """Estilo de un párrafo de unidad: `<prefijo>_<rol>` o, si no existe, el de card."""
        name = f"{prefix}_{role}"
        if name not in self.kn.tokens["styles"]["light"]:
            name = f"card_{role}"
        st = self.kn.style("light", name)
        return (st.resized(sizes[name]) if name in sizes else st), name

    def _card_paras(self, block: TextBlock, roles: list[str], sizes: dict[str, float],
                    prefix: str = "card", align: str = "l", start: int = 0, stop: int | None = None) -> list[RPara]:
        """Párrafos de una unidad con su rol; `start`/`stop` toman un tramo (cabecera o cuerpo)."""
        paras = [p for p in block.paragraphs if p.text.strip()]
        if len(paras) != len(roles):
            raise ValueError(f"{block.id}: {len(paras)} párrafos pero {len(roles)} roles")
        out, prev, prev_bullet = [], None, False
        for p, role in list(zip(paras, roles))[start:stop]:
            st, _ = self._unit_style(prefix, role, sizes)
            rp = restyle(p, st, self.kn, inline_bold=role in ("body", "note"), align=align)
            if not rp.text.strip():   # párrafo que solo tenía emojis
                continue
            # Párrafos de cuerpo seguidos son ítems de una lista: sin aire se leen como uno. Con
            # viñeta del autor la viñeta ya los separa y basta el aire de un título.
            same = 4 if role in ("body", "note") and not (p.bullet and prev_bullet) else 2
            rp.space_before = 0 if prev is None else (same if role == prev else 5)
            out.append(rp)
            prev, prev_bullet = role, p.bullet
        return out

    def _shrink(self, sizes: dict[str, float], names: list[str], fits, remeasure):
        """Baja un punto a la vez los estilos con mínimo declarado hasta que el contenido cabe.

        El cuerpo nunca baja: solo números y títulos tienen `min` en tokens.yaml.
        """
        built = remeasure(sizes)
        for name in names:
            st = self.kn.style("light", name)
            while not fits(built) and sizes.get(name, st.size) - 1 >= (st.min or st.size):
                sizes[name] = sizes.get(name, st.size) - 1
                built = remeasure(sizes)
        return built

    def _ornament_number(self, index: int, prefix: str, sizes: dict[str, float], width: int = 1,
                         align: str = "l") -> list[RPara]:
        """Numeración decorativa (decisión 2 de composición libre): 1, 2… o 01, 02… con el estilo
        del número del componente. No es contenido: su caja va marcada como de marca."""
        st, _ = self._unit_style(prefix, "number", sizes)
        return [RPara(runs=[RRun(text=f"{index:0{width}d}", font=st.font, size=st.size, bold=st.bold,
                                 italic=st.italic, color=st.color)], align=align, line=st.line)]

    @staticmethod
    def _author_numbered(cards: list) -> bool:
        """¿Alguna unidad trae su propio número? Entonces la numeración decorativa no aplica."""
        return any(len(c.roles) > 1 and c.roles[0] == "number" for c in cards)

    def _icon(self, spec: SlideSpec, img: ImageBlock, x: float, y: float, size: float, group: str,
              dark: bool = False) -> list:
        """Ícono de una unidad en una caja de `size`.

        Un glifo de un color (negro, gris, blanco) toma el color de la marca: azul dentro de un
        círculo `icon_badge` en la card blanca, blanco y sin círculo sobre la cabecera navy. Antes
        iba tal cual y salía negro (deck de inducción, 2026-11-03). Un logo o un ícono de varios colores
        conserva sus colores y ocupa el alto de la caja."""
        with Image.open(img.path) as im:
            iw, ih = im.size
        l, t, r, b = img.crop
        iw, ih = iw * (1 - l - r), ih * (1 - t - b)
        comp = self.kn.component("icon_badge")
        kept = self.asset_classes.get(spec.index, {}).get(img.id) in KEEP_ICON_COLORS
        if kept or glyph_color(img.path) is None:
            scale = min(size / ih, (size * 2) / iw)
            return [RPicture(role="icon", box=Box(x=x, y=y, w=round(iw * scale, 2), h=round(ih * scale, 2)),
                             path=img.path, crop=img.crop, group=group, sources=[img.id])]
        path = tint(img.path, self.kn.color(comp["glyph_on_dark" if dark else "glyph"]))
        if dark:
            scale = min(size / ih, size / iw)
            return [RPicture(role="icon", box=Box(x=x, y=y, w=round(iw * scale, 2), h=round(ih * scale, 2)),
                             path=path, crop=img.crop, group=group, sources=[img.id])]
        glyph = size * comp["glyph_ratio"]
        scale = min(glyph / ih, glyph / iw)
        w, h = iw * scale, ih * scale
        return [
            RRect(role="icon_badge", box=Box(x=x, y=y, w=size, h=size), fill=self.kn.color(comp["fill"]),
                  shape="ellipse", group=group),
            RPicture(role="icon", box=Box(x=round(x + (size - w) / 2, 2), y=round(y + (size - h) / 2, 2),
                                          w=round(w, 2), h=round(h, 2)),
                     path=path, crop=img.crop, group=group, sources=[img.id]),
        ]

    def _three_cards(self, spec: SlideSpec, cls: SlideClassification) -> RenderedSlide:
        out = self._base(spec, cls, "light")
        g, comp = self.kn.geometry("three_cards"), self.kn.component("card")
        header_bottom = self._header(spec, cls, out, "title", 2)
        top = header_bottom + g["body_gap"]
        # Las notas al pie que no caben en la línea del footer suben: las cards no las pisan.
        notes_top = self._notes_top(spec, cls, out)
        bottom = self.kn.tokens["margins"]["bottom_limit"]
        if notes_top < bottom:
            bottom = notes_top - g.get("banner_gap", 8)

        banner_paras, banner_h = self._banner_block(spec, cls, g["width"])
        if banner_paras:
            bottom -= banner_h + g["banner_gap"]

        pad = comp["padding"]
        # El ancho sale de cuántas tarjetas trae la slide, no de un tres fijo: así una
        # partición por desborde compone dos tarjetas anchas sin tocar el compositor.
        columns = len(cls.cards)
        card_w = (g["width"] - (columns - 1) * g["card_gutter"]) / columns
        inner_w = card_w - 2 * pad
        icon_h = g["icon_size"] + comp["gap"] if any(c.icon for c in cls.cards) else 0.0

        tags = {k: self._corner_tag(spec, c) for k, c in enumerate(cls.cards)}
        flow = [c.model_copy(update={"extra_texts": c.extra_texts[1:], "roles": [c.roles[0], *c.roles[2:]]})
                if tags[k] else c for k, c in enumerate(cls.cards)]

        def measure(sizes):
            built = []
            for c in flow:
                paras = self._card_paras(self._unit_block(spec, c), c.roles, sizes)
                paras, w, iss = fix_orphans(paras, inner_w, inner_w * 0.9, self.safety)
                built.append((paras, w, iss))
            content = max(tm.block_height(p, w * self.safety) for p, w, _ in built)
            return built, content + icon_h + 2 * pad

        sizes: dict[str, float] = {}
        built, card_h = measure(sizes)
        # overflow: primero se reducen los roles con mínimo (número, título); el cuerpo nunca baja de 11
        for name in ("card_number", "card_title"):
            st = self.kn.style("light", name)
            while top + card_h > bottom and sizes.get(name, st.size) - 1 >= (st.min or st.size):
                sizes[name] = sizes.get(name, st.size) - 1
                built, card_h = measure(sizes)
        if top + card_h > bottom:
            out.compose_issues.append(f"cards_overflow:{top + card_h - bottom:.0f}pt")

        for k, (c, (paras, w, iss)) in enumerate(zip(cls.cards, built)):
            out.compose_issues += iss
            cx = g["x"] + k * (card_w + g["card_gutter"])
            grp = f"card{k + 1}"
            out.elements.append(RRect(role="card", box=Box(x=cx, y=top, w=card_w, h=card_h),
                                      fill=self.kn.color(comp["fill"]), line=self.kn.color(comp["line"]),
                                      line_width=comp.get("line_width", 0.75), radius=comp["radius"],
                                      shadow=self.kn.shadow(comp.get("shadow")), group=grp))
            y = top + pad
            if c.icon:
                out.elements += self._icon(spec, spec.image_by_id(c.icon), cx + pad, y, g["icon_size"], grp)
                y += icon_h
            out.elements.append(self._tx("card_text", paras, cx + pad, y, w, grp, flow[k].text_ids))
            if tags[k]:
                tag_st, _ = self._unit_style("card", "label", sizes)
                tag_paras = [restyle(p, tag_st, self.kn, align="r")
                             for p in spec.text_by_id(tags[k]).paragraphs if p.text.strip()]
                tw = min(hug_width(tag_paras, self.safety), inner_w / 3)
                out.elements.append(self._tx("card_text", tag_paras, cx + card_w - pad - tw, y, tw, grp, [tags[k]]))

        if banner_paras:
            self._draw_banner(cls, out, banner_paras, banner_h, top + card_h + g["banner_gap"], g)
        self._notes(spec, cls, out)
        return out

    def _metrics_row(self, spec: SlideSpec, cls: SlideClassification) -> RenderedSlide:
        """Si el cuerpo no cabe, se reduce el statement (hasta su mínimo) antes de marcar overflow."""
        st = self.kn.style("light", "statement")
        label = self.kn.style("light", "metric_label")
        n = len(cls.metrics)
        # Una fila de métricas; si un rótulo queda con palabra huérfana, el rótulo baja hasta
        # su mínimo y, si aún queda, se prueba una rejilla de dos columnas (4 → 2×2).
        sizes = [label.size] + [float(z) for z in range(int(label.size) - 1, int(label.min or label.size) - 1, -1)]
        options = [(n, z) for z in sizes] + ([(2, z) for z in sizes] if n == 4 else [])
        first = None
        for columns, label_size in options:
            size = st.size
            while True:
                out = self._metrics_attempt(spec, cls, size, columns, label_size)
                overflow = any(i.startswith("body_overflow") for i in out.compose_issues)
                if not overflow or size - 1 < (st.min or size):
                    break
                size -= 1
            first = first or out
            if not overflow and "orphan_unresolved" not in out.compose_issues:
                return out
        return first

    def _metrics_attempt(self, spec: SlideSpec, cls: SlideClassification, title_size: float,
                         columns: int | None = None, label_size: float | None = None) -> RenderedSlide:
        out = self._base(spec, cls, "light")
        g = self.kn.geometry("metrics_row")
        header_bottom = self._header(spec, cls, out, "statement", 3, title_size)
        top = header_bottom + g["body_gap"]
        bottom = self._metric_cards(spec, cls.metrics, out, g["x"], g["width"], top, columns or len(cls.metrics),
                                    label_size)
        if cls.strip:
            bottom = self._strip(spec, cls, out, bottom + g["strip_gap"], g)
        limit = self.kn.tokens["margins"]["bottom_limit"]
        if bottom > limit:
            out.compose_issues.append(f"body_overflow:{bottom - limit:.0f}pt")
        self._notes(spec, cls, out)
        return out

    def _metric_cards(self, spec: SlideSpec, metrics: list, out: RenderedSlide, x: float, width: float,
                      top: float, columns: int, label_size: float | None = None) -> float:
        """Cards de cifra en filas dentro de una región (cuerpo de metrics_row, y bloque
        `metric_card` de la composición libre); devuelve el borde inferior usado."""
        g, comp = self.kn.geometry("metrics_row"), self.kn.component("metric_card")
        n = len(metrics)
        pad = comp["padding"]
        card_w = (width - (columns - 1) * g["metric_gutter"]) / columns
        inner_w = card_w - 2 * pad

        built = []
        for m in metrics:
            paras = []
            for role, bid in (("metric_value", m.value), ("metric_label", m.label), ("metric_desc", m.description)):
                if not bid:
                    continue
                role_st = self.kn.style("light", role)
                if role == "metric_label" and label_size:
                    role_st = role_st.resized(label_size)
                ps = self._paras(spec.text_by_id(bid), role_st, inline_bold=role == "metric_desc")
                for p in ps:
                    p.space_before = 0 if not paras else (2 if role == "metric_label" else 4)
                paras += ps
            paras, w, iss = fix_orphans(paras, inner_w, inner_w * 0.9, self.safety)
            out.compose_issues += iss
            built.append((m, paras, w))
        card_h = max(tm.block_height(p, w * self.safety) for _, p, w in built) + 2 * pad
        rows = -(-n // columns)
        for k, (m, paras, w) in enumerate(built):
            row, col = divmod(k, columns)
            cx = x + col * (card_w + g["metric_gutter"])
            cy = top + row * (card_h + g["metric_gutter"])
            grp = f"metric{k + 1}"
            out.elements.append(RRect(role="metric_card", box=Box(x=cx, y=cy, w=card_w, h=card_h),
                                      fill=self.kn.color(comp["fill"]), line=self.kn.color(comp["line"]),
                                      line_width=comp.get("line_width", 0.75), radius=comp["radius"],
                                      shadow=self.kn.shadow(comp.get("shadow")), group=grp))
            srcs = [x for x in (m.value, m.label, m.description) if x]
            out.elements.append(self._tx("metric_text", paras, cx + pad, cy + pad, w, grp, srcs))
        return top + rows * card_h + (rows - 1) * g["metric_gutter"]

    def _strip(self, spec, cls, out, y, g) -> float:
        h, gap = g["strip_item_height"], g["strip_item_gap"]
        items: list[tuple[str, object, float, float]] = []  # (tipo, payload, w, h)
        if cls.strip.label:
            ps = self._paras(spec.text_by_id(cls.strip.label), self.kn.style("light", "strip_label"))
            items.append(("text", (cls.strip.label, ps), hug_width(ps, self.safety), tm.block_height(ps, 1000)))
        for iid in cls.strip.items:
            if iid.startswith("i"):
                img = spec.image_by_id(iid)
                with Image.open(img.path) as im:
                    iw, ih = im.size
                l, t, r, b = img.crop
                iw, ih = iw * (1 - l - r), ih * (1 - t - b)
                scale = min(h / ih, 110 / iw)
                items.append(("img", img, iw * scale, ih * scale))
            else:
                ps = self._paras(spec.text_by_id(iid), self.kn.style("light", "strip_text"))
                items.append(("text", (iid, ps), hug_width(ps, self.safety), tm.block_height(ps, 1000)))
        total = sum(w for _, _, w, _ in items) + gap * (len(items) - 1)
        if total > g["width"]:
            out.compose_issues.append(f"strip_too_wide:{total - g['width']:.0f}pt")
        x = g["x"]
        for kind, payload, w, ih in items:
            yy = y + (h - ih) / 2
            if kind == "img":
                out.elements.append(RPicture(role="strip_image", box=Box(x=x, y=yy, w=round(w, 2), h=round(ih, 2)),
                                             path=payload.path, crop=payload.crop, group="strip", sources=[payload.id]))
            else:
                bid, ps = payload
                out.elements.append(RText(role="strip_text", box=Box(x=x, y=yy, w=round(w, 2), h=round(ih + 2, 2)),
                                          paras=ps, group="strip", sources=[bid]))
            x += w + gap
        return y + h

    # ------------------------------------------------------------ layouts por familia

    def _banner_block(self, spec, cls, width: float):
        """Mide el banner opcional; devuelve (párrafos, alto) o (None, 0).

        Un banner de una caja va centrado. Si trae varias (rótulo + mensaje, como un
        «Antes de irte»), la primera es el rótulo y el conjunto se alinea a la izquierda.
        """
        if not cls.banner:
            return None, 0.0
        bc = self.kn.component("banner")
        extra = cls.named.get("banner", [])
        align = "l" if extra else "ctr"
        paras = self._paras(spec.text_by_id(cls.banner), self.kn.style("light", "banner"),
                            inline_bold=True, align=align)
        for bid in extra:
            more = self._paras(spec.text_by_id(bid), self.kn.style("light", "banner_body"),
                               inline_bold=True, align=align)
            if more:
                more[0].space_before = 3
            paras += more
        bw = width - 2 * bc["padding_x"]
        paras, _, _iss = fix_orphans(paras, bw, bw, self.safety)
        return paras, tm.block_height(paras, bw * self.safety) + 2 * bc["padding_y"]

    def _draw_banner(self, cls, out, paras, height: float, y: float, g: dict) -> None:
        bc = self.kn.component("banner")
        out.elements.append(RRect(role="banner", box=Box(x=g["x"], y=y, w=g["width"], h=height),
                                  fill=self.kn.color(bc["fill"]), radius=bc["radius"], group="banner"))
        out.elements.append(self._tx("banner_text", paras, g["x"] + bc["padding_x"], y + bc["padding_y"],
                                    g["width"] - 2 * bc["padding_x"], "banner",
                                    [cls.banner, *cls.named.get("banner", [])]))

    def _writing_lines(self, out, x: float, top: float, width: float, bottom: float, group: str) -> None:
        """Renglones de una plantilla para completar: guía visual, no contenido."""
        spacing = self.kn.component("worksheet")["line_spacing"]
        room = bottom - top
        if room < spacing * 0.6:
            return
        # Renglones repartidos en el alto disponible: al menos uno, cerca del espaciado base.
        count = max(1, round(room / spacing))
        step = room / count
        for k in range(1, count + 1):
            out.elements.append(RRect(role="writing_line", box=Box(x=x, y=round(top + step * k, 2), w=width, h=0.75),
                                      fill=self.kn.color(self.kn.component("worksheet")["line"]), group=group))

    @staticmethod
    def _columns(cls, g: dict, n: int) -> int:
        """Columnas de la rejilla: la variante de la familia manda; si no, la tabla del layout."""
        wanted = cls.columns or g["columns_by_count"].get(n) or min(n, 3)
        return max(1, min(wanted, n))

    @staticmethod
    def _header_split(roles: list[str]) -> int:
        """Párrafos iniciales que van a la cabecera navy: número, título y etiqueta."""
        count = 0
        for role in roles:
            if role not in ("number", "title", "label"):
                break
            count += 1
        return count

    def _card_grid(self, spec: SlideSpec, cls: SlideClassification) -> RenderedSlide:
        """Rejilla de tarjetas; si no cabe con sus columnas, redistribuye antes de desbordar.

        Orden de la política (convenciones 2026-09-18): ampliar, crecer, **redistribuir**,
        y solo al final declarar desborde para que el host acepte una partición. Se prueban
        primero las columnas más cercanas a la variante de la familia.
        """
        n = len(cls.cards)
        preferred = self._columns(cls, self.kn.geometry("card_grid"), n)
        candidates = sorted(range(1, min(n, 5) + 1), key=lambda c: (abs(c - preferred), -c))
        first = None
        for columns in candidates:
            if columns == 1 and n > 2:
                break   # una columna de tres o más tarjetas ya no es una rejilla: mejor partir
            out = self._card_grid_attempt(spec, cls, columns)
            first = first or out
            if not any(issue.startswith("cards_overflow") for issue in out.compose_issues):
                if columns != preferred:
                    out.compose_issues.append(f"grid_redistributed:{preferred}->{columns}")
                return out
        return first

    def _card_grid_attempt(self, spec: SlideSpec, cls: SlideClassification, columns: int) -> RenderedSlide:
        """Rejilla de tarjetas uniformes; la última fila incompleta se centra."""
        out = self._base(spec, cls, "light")
        g = self.kn.geometry("card_grid")
        top = self._header(spec, cls, out, "title", 2) + g["body_gap"]
        bottom = self.kn.tokens["margins"]["bottom_limit"]
        banner_paras, banner_h = self._banner_block(spec, cls, g["width"])
        if banner_paras:
            bottom -= banner_h + g["banner_gap"]
        last_bottom = self._card_rows(spec, cls, cls.cards, out, g["x"], g["width"], top, bottom, columns, g)
        if banner_paras:
            self._draw_banner(cls, out, banner_paras, banner_h, last_bottom + g["banner_gap"], g)
        self._notes(spec, cls, out)
        return out

    def _card_rows(self, spec: SlideSpec, cls: SlideClassification, cards: list, out: RenderedSlide,
                   x: float, width: float, top: float, bottom: float, columns: int, g: dict,
                   icon_mode: str = "auto", decorate: bool = False) -> float:
        """Tarjetas uniformes en filas dentro de una región; devuelve el borde inferior usado.

        Es el cuerpo de card_grid, y lo reusa la composición libre en cada celda: así las dos
        dan la misma geometría por construcción. La composición libre puede fijar dónde va el
        ícono (`top`, `left`, `header_right`: dentro de la cabecera navy) y pedir numeración
        decorativa (01, 02… arriba del texto) cuando el autor no numeró.
        """
        comp = self.kn.component("card")
        n = len(cards)
        rows = -(-n // columns)
        card_w = (width - (columns - 1) * g["card_gutter"]) / columns
        pad = comp["padding"]
        has_icons = any(c.icon for c in cards)
        heads = [self._header_split(c.roles) for c in cards]
        header = cls.card_style == "header" and all(heads)
        # El ícono en la cabecera solo existe si hay cabecera; si no, se ubica solo.
        in_header = has_icons and header and icon_mode == "header_right"
        # En una tarjeta ancha el ícono va a la izquierda del texto: ocupa ancho que
        # sobra en vez de alto que falta. En una angosta va arriba.
        if icon_mode in ("top", "left"):
            icon_left = has_icons and icon_mode == "left"
        else:
            icon_left = has_icons and not in_header and card_w >= g["icon_left_min_width"]
        icon_w = g["icon_size"] + comp["gap"] * 2 if icon_left else 0.0
        inner_w = card_w - 2 * pad - icon_w
        icon_h = g["icon_size"] + comp["gap"] if has_icons and not icon_left and not in_header else 0.0
        hc = self.kn.component("card_header")
        head_icon = min(g["icon_size"], g["header_icon_size"]) if in_header else 0.0
        head_w = card_w - 2 * hc["padding"] - (head_icon + hc["padding"] if in_header else 0.0)
        ornament = decorate and not self._author_numbered(cards)
        available = bottom - top

        def measure(sizes):
            built = []
            for c, k in zip(cards, heads):
                block = self._unit_block(spec, c)
                head = None
                if header:
                    hp = self._card_paras(block, c.roles, sizes, prefix="card_header", stop=k)
                    head = fix_orphans(hp, head_w, head_w * 0.9, self.safety)
                    bp = self._card_paras(block, c.roles, sizes, start=k)
                else:
                    bp = self._card_paras(block, c.roles, sizes)
                body = fix_orphans(bp, inner_w, inner_w * 0.9, self.safety) if bp else ([], inner_w, [])
                built.append((head, body))
            head_h = max((tm.block_height(h[0], h[1] * self.safety) for h, _ in built if h), default=0.0)
            head_h = max(head_h, head_icon) + 2 * hc["padding"] if header else 0.0
            body_h = max((tm.block_height(b[0], b[1] * self.safety) for _, b in built if b[0]), default=0.0)
            if ornament:
                number_h = tm.block_height(self._ornament_number(len(cards), "card", sizes, 2), inner_w) + 2
                body_h += number_h + comp["gap"]
            if icon_left:
                body_h = max(body_h, g["icon_size"])
            card_h = head_h + icon_h + body_h + (2 * pad if body_h or not header else pad)
            return built, head_h, card_h

        def fits(result):
            return rows * result[2] + (rows - 1) * g["row_gap"] <= available

        names = (["card_header_number", "card_header_title"] if header else []) + ["card_number", "card_title"]
        sizes_used: dict[str, float] = {}
        built, head_h, card_h = self._shrink(sizes_used, names, fits, measure)
        if not fits((built, head_h, card_h)):
            need = rows * card_h + (rows - 1) * g["row_gap"]
            out.compose_issues.append(f"cards_overflow:{need - available:.0f}pt")
        elif cls.fill:
            # Plantilla para completar: el espacio libre es el área de escritura.
            card_h = (available - (rows - 1) * g["row_gap"]) / rows
        elif cls.min_fill:
            # Plantilla de propuesta: las cards reservan alto para el contenido que se completará.
            card_h = max(card_h, cls.min_fill * (available - (rows - 1) * g["row_gap"]) / rows)

        for k, (c, (head, body)) in enumerate(zip(cards, built)):
            row, col = divmod(k, columns)
            in_row = min(columns, n - row * columns)
            offset = (width - (in_row * card_w + (in_row - 1) * g["card_gutter"])) / 2
            cx = x + offset + col * (card_w + g["card_gutter"])
            cy = top + row * (card_h + g["row_gap"])
            grp = f"card{k + 1}"
            for issues in ([head[2]] if head else []) + [body[2]]:
                out.compose_issues += issues
            out.elements.append(RRect(role="card", box=Box(x=cx, y=cy, w=card_w, h=card_h),
                                      fill=self.kn.color(comp["fill"]), line=self.kn.color(comp["line"]),
                                      line_width=comp.get("line_width", 0.75), radius=comp["radius"],
                                      shadow=self.kn.shadow(comp.get("shadow")), group=grp))
            y = cy + pad
            if header:
                fill = self.kn.color(hc["fill"])
                out.elements.append(RRect(role="card_header", box=Box(x=cx, y=cy, w=card_w, h=head_h),
                                          fill=fill, radius=hc["radius"], group=grp))
                # Base recta: la cabecera se redondea arriba y se une en ángulo con el cuerpo.
                out.elements.append(RRect(role="card_header_base",
                                          box=Box(x=cx, y=cy + head_h / 2, w=card_w, h=head_h / 2),
                                          fill=fill, group=grp))
                text = self._tx("card_header_text", head[0], cx + hc["padding"], cy, head[1], grp, [c.text])
                text.box.y = round(cy + (head_h - text.box.h) / 2, 2)
                out.elements.append(text)
                if in_header and c.icon:
                    out.elements += self._icon(spec, spec.image_by_id(c.icon), cx + card_w - hc["padding"] - head_icon,
                                               cy + (head_h - head_icon) / 2, head_icon, grp, dark=True)
                y = cy + head_h + pad
            if c.icon and not in_header:
                out.elements += self._icon(spec, spec.image_by_id(c.icon), cx + pad, y, g["icon_size"], grp)
                y += icon_h
            if ornament:
                number = self._tx("card_number", self._ornament_number(k + 1, "card", sizes_used, 2),
                                  cx + pad + icon_w, y, inner_w, grp, [])
                number.brand = True
                out.elements.append(number)
                y = number.box.bottom + comp["gap"]
            if body[0]:
                text = self._tx("card_text", body[0], cx + pad + icon_w, y, body[1], grp, [c.text])
                out.elements.append(text)
                y = text.box.bottom
            if cls.fill:
                self._writing_lines(out, cx + pad, y, card_w - 2 * pad, cy + card_h - pad, grp)
        return top + rows * card_h + (rows - 1) * g["row_gap"]

    def _item_list(self, spec: SlideSpec, cls: SlideClassification) -> RenderedSlide:
        """Filas compactas, llenadas por columna para conservar el orden de lectura."""
        out = self._base(spec, cls, "light")
        g, comp = self.kn.geometry("item_list"), self.kn.component("item_row")
        header_bottom = self._header(spec, cls, out, "title", 2)
        top = header_bottom + g["body_gap"]
        rule = cls.card_style == "rule"
        if rule:   # la línea fina que cierra el encabezado, a todo el ancho
            out.elements.append(RRect(role="header_rule", box=Box(x=g["x"], y=round(header_bottom + g["body_gap"] / 2, 1),
                                                                 w=g["width"], h=0.75),
                                      fill=None, line=self.kn.color(g.get("rule_color", "blue_pale")),
                                      line_width=g.get("rule_width", 0.75), shape="line", group="header"))
        self._item_rows(spec, cls, cls.cards, out, g["x"], g["width"], top,
                        self.kn.tokens["margins"]["bottom_limit"], g)
        self._notes(spec, cls, out)
        return out

    def _item_rows(self, spec: SlideSpec, cls: SlideClassification, cards: list, out: RenderedSlide,
                   x: float, width: float, top: float, bottom: float, g: dict, decorate: bool = False) -> float:
        """Filas de item_list dentro de una región (una o dos columnas); devuelve el borde inferior."""
        comp = self.kn.component("item_row")
        available = bottom - top
        n = len(cards)
        columns = 1 if n <= g["max_rows"] else 2
        rows = -(-n // columns)
        col_w = (width - (columns - 1) * g["column_gutter"]) / columns
        pad = comp["padding"]
        numbered = [bool(c.roles) and c.roles[0] == "number" and len(c.roles) > 1 for c in cards]
        ornament = decorate and not any(numbered)
        if ornament:
            numbered = [True] * n
        num_w = comp["number_width"]
        rule = cls.card_style == "rule"
        rule_color = self.kn.color(g.get("rule_color", "blue_pale"))
        # Filas `rule`: sin card, con una flecha de navegación a la derecha.
        arrow_w = g.get("arrow_width", 12) + comp["gap"] if rule else 0.0
        text_w = lambda has_number: col_w - 2 * pad - (num_w + comp["gap"] if has_number else 0) - arrow_w

        def measure(sizes):
            built = []
            for index, (c, has_number) in enumerate(zip(cards, numbered), start=1):
                block = self._unit_block(spec, c)
                if ornament:
                    number = self._ornament_number(index, "item", sizes, 2)
                    rest = self._card_paras(block, c.roles, sizes, prefix="item")
                    width = text_w(True)
                    built.append((number, fix_orphans(rest, width, width * 0.9, self.safety)))
                    continue
                number = self._card_paras(block, c.roles, sizes, prefix="item", stop=1) if has_number else None
                rest = self._card_paras(block, c.roles, sizes, prefix="item", start=1 if has_number else 0)
                width = text_w(has_number)
                built.append((number, fix_orphans(rest, width, width * 0.9, self.safety)))
            heights = [
                max(tm.block_height(body[0], body[1] * self.safety),
                    tm.block_height(number, num_w) if number else 0.0)
                for number, body in built
            ]
            return built, max(heights) + 2 * pad

        def fits(result):
            return rows * result[1] + (rows - 1) * g["row_gap"] <= available

        built, row_h = self._shrink({}, ["item_number", "item_title"], fits, measure)
        if not fits((built, row_h)):
            out.compose_issues.append(f"cards_overflow:{rows * row_h + (rows - 1) * g['row_gap'] - available:.0f}pt")

        for k, (c, (number, body)) in enumerate(zip(cards, built)):
            col, row = divmod(k, rows)
            rx = x + col * (col_w + g["column_gutter"])
            ry = top + row * (row_h + g["row_gap"])
            grp = f"item{k + 1}"
            out.compose_issues += body[2]
            if rule:
                out.elements.append(RRect(role="item_rule", box=Box(x=rx, y=round(ry + row_h, 1), w=col_w, h=0.75),
                                          fill=None, line=rule_color, line_width=g.get("rule_width", 0.75),
                                          shape="line", group=grp))
                aw = g.get("arrow_width", 12)
                out.elements.append(RRect(role="item_arrow", box=Box(x=round(rx + col_w - pad - aw, 2),
                                                                     y=round(ry + row_h / 2 - 4, 2), w=aw, h=8),
                                          fill=None, line=self.kn.color("blue"), line_width=1.0, shape="arrow",
                                          group=grp))
            else:
                out.elements.append(RRect(role="item", box=Box(x=rx, y=ry, w=col_w, h=row_h),
                                          fill=self.kn.color(comp["fill"]), line=self.kn.color(comp["line"]),
                                          line_width=comp.get("line_width", 0.75), radius=comp["radius"],
                                          shadow=self.kn.shadow(comp.get("shadow")), group=grp))
            tx = rx + pad
            if number:
                el = self._tx("item_number", number, tx, ry, num_w, grp, [] if ornament else [c.text])
                el.box.y = round(ry + (row_h - el.box.h) / 2, 2)
                el.brand = ornament
                out.elements.append(el)
                tx += num_w + comp["gap"]
            el = self._tx("card_text", body[0], tx, ry, body[1], grp, [c.text])
            el.box.y = round(ry + (row_h - el.box.h) / 2, 2)
            out.elements.append(el)
        return top + rows * row_h + (rows - 1) * g["row_gap"]

    @staticmethod
    def _trim_transparent(img: ImageBlock, keep: float = 0.85) -> ImageBlock:
        """La imagen por su área visible: los márgenes transparentes (una maqueta pegada en un
        PNG del ancho de la slide) se recortan con `crop`, sin tocar el archivo."""
        with Image.open(img.path) as im:
            if im.mode not in ("RGBA", "LA", "PA"):
                return img
            iw, ih = im.size
            bbox = im.getchannel("A").point(lambda a: 255 if a > 8 else 0).getbbox()
        if not bbox:
            return img
        l, t, r, b = img.crop
        x0, y0, x1, y1 = bbox
        new = (max(l, x0 / iw), max(t, y0 / ih), max(r, 1 - x1 / iw), max(b, 1 - y1 / ih))
        visible = (1 - new[0] - new[2]) * (1 - new[1] - new[3])
        if visible >= keep * (1 - l - r) * (1 - t - b):
            return img
        fw, fh = (1 - new[0] - new[2]) / max(1 - l - r, 1e-6), (1 - new[1] - new[3]) / max(1 - t - b, 1e-6)
        box = img.box.model_copy(update={"w": img.box.w * fw, "h": img.box.h * fh})
        return img.model_copy(update={"crop": new, "box": box})

    def _fit_image(self, img: ImageBlock, x: float, y: float, w: float, h: float, group: str,
                   role: str = "image", align: tuple[float, float] = (0.5, 0.5)) -> RPicture:
        """Imagen completa y proporcional dentro de la celda: nunca se deforma.

        `align` ubica la imagen en el espacio sobrante (0 = izquierda/arriba, 1 = derecha/abajo).
        Tampoco se amplía más allá de lo que su resolución sostiene: no supera el mayor entre
        su tamaño en el origen y sus píxeles a `MIN_PPI` (una GIF chica ampliada se pixela).
        """
        with Image.open(img.path) as im:
            iw, ih = im.size
        l, t, r, b = img.crop
        iw, ih = iw * (1 - l - r), ih * (1 - t - b)
        scale = min(w / iw, h / ih, max(img.box.w / iw, 72 / MIN_PPI))
        pw, ph = iw * scale, ih * scale
        return RPicture(role=role, box=Box(x=round(x + (w - pw) * align[0], 2), y=round(y + (h - ph) * align[1], 2),
                                           w=round(pw, 2), h=round(ph, 2)),
                        path=img.path, crop=img.crop, group=group, sources=[img.id])

    def _round_photo(self, img: ImageBlock, x: float, y: float, size: float, group: str) -> RPicture:
        """Foto de ficha: recorte centrado a cuadrado y máscara circular, igual en todo el equipo.

        Recortar a círculo está permitido (convenciones); deformar no. Si el origen ya traía
        recorte, se conserva y se completa hasta el cuadrado.
        """
        with Image.open(img.path) as im:
            iw, ih = im.size
        l, t, r, b = img.crop
        w, h = iw * (1 - l - r), ih * (1 - t - b)
        if w > h:
            extra = (w - h) / iw / 2
            l, r = l + extra, r + extra
        elif h > w:
            extra = (h - w) / ih / 2
            t, b = t + extra, b + extra
        ring = self.kn.component("photo_ring")
        return RPicture(role="photo", box=Box(x=round(x, 2), y=round(y, 2), w=round(size, 2), h=round(size, 2)),
                        path=img.path, crop=(l, t, r, b), group=group, sources=[img.id], shape="ellipse",
                        line=self.kn.color(ring["line"]), line_width=ring["line_width"])

    @staticmethod
    def _photo_limit(img: ImageBlock) -> float:
        """Lado máximo de una foto de ficha sin ampliarla más de lo que sostiene (`_fit_image`)."""
        with Image.open(img.path) as im:
            iw, ih = im.size
        l, t, r, b = img.crop
        side = min(iw * (1 - l - r), ih * (1 - t - b))
        return max(min(img.box.w, img.box.h), side * 72 / MIN_PPI)

    def _team_grid(self, spec: SlideSpec, cls: SlideClassification) -> RenderedSlide:
        """Fichas foto-nombre-rol como un solo componente, todas del mismo tamaño."""
        out = self._base(spec, cls, "light")
        g, comp = self.kn.geometry("team_grid"), self.kn.component("team_card")
        top = self._header(spec, cls, out, "title", 2) + g["body_gap"]
        available = self.kn.tokens["margins"]["bottom_limit"] - top
        n = len(cls.cards)
        pad = comp["padding"]

        def attempt(columns: int):
            rows = -(-n // columns)
            card_w = (g["width"] - (columns - 1) * g["card_gutter"]) / columns
            inner_w = card_w - 2 * pad
            photo = g["photo_size"] if any(c.photo for c in cls.cards) else 0.0

            def measure_text(sizes):
                built = [
                    fix_orphans(self._card_paras(self._unit_block(spec, c), c.roles, sizes, prefix="member",
                                                 align="ctr"), inner_w, inner_w * 0.9, self.safety)
                    for c in cls.cards
                ]
                return built, max(tm.block_height(p, w * self.safety) for p, w, _ in built) + 2 * pad

            if photo:
                # Con pocas fichas la foto crece (hasta `photo_max`) en vez de dejar la slide vacía.
                text_h = measure_text({})[1]
                room = min(available, self._notes_top(spec, cls, out) - g["row_gap"] - top)
                per_row = (room - (rows - 1) * g["row_gap"]) / rows
                limit = min(self._photo_limit(spec.image_by_id(c.photo)) for c in cls.cards if c.photo)
                photo = max(photo, min(g.get("photo_max", photo), per_row - text_h - 6, inner_w * 0.6, limit))
            photo_h = photo + 6 if photo else 0.0

            def measure(sizes):
                built, height = measure_text(sizes)
                return built, height + photo_h

            def fits(result):
                return rows * result[1] + (rows - 1) * g["row_gap"] <= available

            built, card_h = self._shrink({}, ["member_title"], fits, measure)
            return fits((built, card_h)), (columns, rows, card_w, inner_w, photo, photo_h, built, card_h)

        # La rejilla por defecto sale de la cantidad; si sus filas no caben, se prueban filas
        # más anchas (hasta `max_columns`) antes de declarar el desborde.
        default = self._columns(cls, g, n)
        tries = [default] + [c for c in range(default + 1, min(n, g.get("max_columns", 5)) + 1)]
        for columns in tries:
            ok, result = attempt(columns)
            if ok:
                break
        else:
            ok, result = attempt(default)
        columns, rows, card_w, inner_w, photo, photo_h, built, card_h = result
        if not ok:
            out.compose_issues.append(f"cards_overflow:{rows * card_h + (rows - 1) * g['row_gap'] - available:.0f}pt")
        for k, (c, (paras, w, iss)) in enumerate(zip(cls.cards, built)):
            row, col = divmod(k, columns)
            in_row = min(columns, n - row * columns)
            offset = (g["width"] - (in_row * card_w + (in_row - 1) * g["card_gutter"])) / 2
            cx = g["x"] + offset + col * (card_w + g["card_gutter"])
            cy = top + row * (card_h + g["row_gap"])
            grp = f"member{k + 1}"
            out.compose_issues += iss
            # La ficha es foto con aro + nombre + rol; la card detrás es opcional (`member_card`).
            if g.get("member_card", False):
                out.elements.append(RRect(role="team_card", box=Box(x=cx, y=cy, w=card_w, h=card_h),
                                          fill=self.kn.color(comp["fill"]), line=self.kn.color(comp["line"]),
                                          line_width=comp.get("line_width", 0.75), radius=comp["radius"],
                                          shadow=self.kn.shadow(comp.get("shadow")), group=grp))
            if c.photo:
                out.elements.append(self._round_photo(spec.image_by_id(c.photo), cx + (card_w - photo) / 2,
                                                      cy + pad, photo, grp))
            text_x = cx + pad + (inner_w - w) / 2
            out.elements.append(self._tx("card_text", paras, text_x, cy + pad + photo_h, w, grp, [c.text]))
        self._notes(spec, cls, out)
        return out

    @staticmethod
    def _image_cells(sizes: list[tuple[float, float]], w: float, h: float, gap: float):
        """Elige la rejilla (columnas × filas) que muestra las imágenes más grandes.

        Devuelve cada celda con su alineación: las imágenes se juntan hacia el centro
        del collage para que el espacio sobrante quede afuera y no entre ellas.
        """
        n = len(sizes)
        best, best_area = None, -1.0
        for columns in range(1, n + 1):
            rows = -(-n // columns)
            cw, ch = (w - (columns - 1) * gap) / columns, (h - (rows - 1) * gap) / rows
            area = sum(min(cw / iw, ch / ih) ** 2 * iw * ih for iw, ih in sizes)
            if area > best_area:
                best, best_area = (columns, rows, cw, ch), area
        columns, rows, cw, ch = best

        def toward_center(position: int, count: int) -> float:
            if count == 1:
                return 0.5
            return 1.0 if position < (count - 1) / 2 else 0.0 if position > (count - 1) / 2 else 0.5

        cells = []
        for index in range(n):
            row, col = divmod(index, columns)
            cells.append(((col * (cw + gap), row * (ch + gap), cw, ch),
                          (toward_center(col, columns), toward_center(row, rows))))
        return cells

    def _image_text(self, spec: SlideSpec, cls: SlideClassification, ratio: float | None = None) -> RenderedSlide:
        """Imágenes completas a la izquierda; el mensaje arranca donde terminan.

        El mensaje son grupos de cajas en orden: los bloques `block:N` del plan (con su
        imagen opcional) o, sin bloques, cada caja de `body` en orden de lectura. Una parte
        de una partición puede quedar sin imagen: el mensaje ocupa todo el ancho.
        """
        out = self._base(spec, cls, "light")
        g = self.kn.geometry("image_text")
        has_header = bool(cls.title or cls.kicker or cls.subtitle)
        top = self._header(spec, cls, out, "title", 2) + g["body_gap"] if has_header else g["top_without_header"]
        self._image_message(spec, cls, out, g["x"], g["width"], top, self.kn.tokens["margins"]["bottom_limit"], ratio)
        self._notes(spec, cls, out)
        return out

    @staticmethod
    def _used_bottom(out: RenderedSlide, before: int, top: float) -> float:
        """Borde inferior de lo que se agregó a la slide desde `before`."""
        return max((el.box.bottom for el in out.elements[before:]), default=top)

    def _image_message(self, spec: SlideSpec, cls: SlideClassification, out: RenderedSlide, x: float,
                       width: float, top: float, bottom: float, ratio: float | None = None) -> float:
        """Cuerpo de image_text dentro de una región (bloque `image_message` de la composición
        libre); devuelve el borde inferior usado."""
        g = {**self.kn.geometry("image_text"), "x": x, "width": width}
        before, issues_before = len(out.elements), len(out.compose_issues)
        height = bottom - top
        groups = [card.text_ids for card in cls.cards] or [[bid] for bid in cls.body]
        if cls.cards and not cls.images and not any(c.image for c in cls.cards):
            self._block_gallery(spec, cls, out, top, height, g)
            return self._used_bottom(out, before, top)
        # Cada bloque con su foto (los tips, los pasos con su imagen): fichas iguales con la foto
        # y su texto. Antes salía un collage con la lista aparte o fotos de alturas distintas
        # con el texto a tres alturas (deck de inducción, 2026-11-03). Una imagen principal junto a un
        # retrato chico sigue siendo imagen + mensaje.
        areas = sorted((spec.image_by_id(c.image).box.w * spec.image_by_id(c.image).box.h
                        for c in cls.cards if c.image), reverse=True)
        if (len(cls.cards) >= 2 and not cls.images and len(areas) == len(cls.cards)
                and areas[0] < g["primary_ratio"] * areas[1]):
            self._photo_cards(spec, cls, out, top, height, g)
            return self._used_bottom(out, before, top)
        images = [self._trim_transparent(spec.image_by_id(iid))
                  for iid in [*cls.images, *(c.image for c in cls.cards if c.image)]]
        st = self.kn.style("light", "body")
        # Un bloque que es solo un rótulo breve con su imagen («Proceso y Demo:») es el rótulo
        # de esa imagen: va encima de ella, no suelto al final del mensaje.
        # Si todos los bloques son rótulos, no hay mensaje: es una galería y cada rótulo va
        # debajo de su foto («foto grande arriba y su indicación debajo», deck de inducción, 2026-10-26).
        caption_st = self.kn.style("light", "list_title")
        captions = {
            card.image: card.text for card in cls.cards
            if card.image and len(card.text_ids) == 1
            and 1 <= len([p for p in spec.text_by_id(card.text).paragraphs if p.text.strip()]) <= 2
            and len(" ".join(spec.text_by_id(card.text).text.split())) <= g["caption_max_chars"]
        }
        if captions and len(captions) < len(groups):
            # Con mensaje al lado, un ítem numerado («4. Realiza pausas activas») es parte de la
            # lista, no el rótulo de su foto: separarlo partía la enumeración.
            captions = {iid: bid for iid, bid in captions.items()
                        if not re.match(r"\s*\d+\s*[.)\-]", spec.text_by_id(bid).text)}
        if captions and len(captions) <= len(groups):
            groups = [group for group in groups if group[0] not in captions.values()]
        else:
            captions = {}
        captions_below = bool(captions) and not groups

        def natural(img: ImageBlock) -> tuple[float, float]:
            with Image.open(img.path) as im:
                iw, ih = im.size
            l, t, r, b = img.crop
            return iw * (1 - l - r), ih * (1 - t - b)

        # Imagen principal + retrato: la principal toma la columna y las menores van con el texto.
        areas = [img.box.w * img.box.h for img in images]
        primary = max(range(len(images)), key=areas.__getitem__) if images else None
        side: list[ImageBlock] = []
        if groups and len(images) > 1 and all(
            areas[primary] >= g["primary_ratio"] * area for k, area in enumerate(areas) if k != primary
        ):
            side = [img for k, img in enumerate(images) if k != primary]
            images = [images[primary]]

        if not groups:
            image_w = g["width"]
        elif not images:
            image_w = 0.0
        elif side:
            widest = max(hug_width(self._paras(spec.text_by_id(bid), st, inline_bold=True), self.safety)
                         for group in groups for bid in group)
            text_col = min(max(widest, g["text_column_min"]), g["width"] * (1 - g["image_ratio"]))
            image_w = g["width"] - text_col - g["column_gap"]
        else:
            image_w = g["width"] * (ratio or g["image_ratio"])

        pictures, captioned = [], {}
        cells = self._image_cells([natural(img) for img in images], image_w, height,
                                  g["image_gap"]) if images else []
        for k, (img, ((dx, dy, cw, ch), align)) in enumerate(zip(images, cells)):
            if groups and len(images) == 1:
                align = (0.0, 0.5)   # una sola imagen: pegada al margen, el mensaje a su lado
            bid = captions.get(img.id)
            if not bid:
                pictures.append(self._fit_image(img, g["x"] + dx, top + dy, cw, ch, f"image{k + 1}", align=align))
                continue
            # El rótulo vive dentro de la celda de su foto, medido al ancho en que se dibuja:
            # medido en una línea y reservado una sola vez arriba, en un collage de dos filas
            # tapaba la foto de la fila de arriba.
            paras = self._paras(spec.text_by_id(bid), caption_st)
            cap_h = tm.block_height(paras, cw * self.safety) + g["block_gap"]
            for _ in range(3):
                y = top + dy + (0.0 if captions_below else cap_h)
                picture = self._fit_image(img, g["x"] + dx, y, cw, max(ch - cap_h, 1.0), f"image{k + 1}",
                                          align=(align[0], 0.0 if captions_below else 1.0))
                fitted, w, iss = fix_orphans(paras, picture.box.w, picture.box.w * 0.85, self.safety)
                needed = tm.block_height(fitted, w * self.safety) + g["block_gap"]
                if needed <= cap_h + 0.5:
                    break
                cap_h = needed
            out.compose_issues += iss
            pictures.append(picture)
            captioned[id(picture)] = (bid, fitted, w, cap_h)
        used_right = g["x"] - g["column_gap"]
        if pictures:
            # El collage ocupa menos que su columna cuando las proporciones no la llenan: se
            # corre a la derecha hasta el mensaje en vez de dejar un hueco en medio.
            used_left = min(picture.box.x for picture in pictures)
            used_right = max(picture.box.right for picture in pictures)
            if not groups:
                shift = (g["x"] + (g["width"] - (used_right - used_left)) / 2) - used_left
            else:
                shift = g["x"] - used_left
            for picture in pictures:
                picture.box.x = round(picture.box.x + shift, 2)
            used_right += shift
        out.elements += pictures
        for picture in pictures:
            if id(picture) in captioned:
                bid, paras, w, cap_h = captioned[id(picture)]
                y = picture.box.bottom + g["block_gap"] if captions_below else picture.box.y - cap_h
                out.elements.append(self._tx("body", paras, picture.box.x, y, w, picture.group, [bid]))
        if not groups:
            return self._used_bottom(out, before, top)

        text_x = used_right + g["column_gap"] if pictures else g["x"]
        text_w = g["x"] + g["width"] - text_x
        card = self.kn.component("team_card")
        # Sin card (por defecto) el mensaje va sobre el fondo con una barra azul de acento a
        # su izquierda; `message_card: true` vuelve a la tarjeta blanca.
        message_card = g.get("message_card", False)
        pad = card["padding"] if message_card else 0.0          # margen vertical
        pad_left = pad if message_card else g["accent_inset"]
        inner_w = text_w - pad_left - pad
        gutter = g["number_gutter"]
        side_h = 0.0
        if side:
            side_h = min(g["side_image_max"], (inner_w - g["image_gap"] * (len(side) - 1)) / len(side))
        # Encabezados de bloque: número (va en un margen, a la izquierda de su texto) o rótulo.
        kinds = {}
        for group in groups if cls.cards else []:
            if self._block_number(spec, group):
                kinds[group[0]] = "card_number"
            elif self._block_heading(spec, group):
                kinds[group[0]] = "card_title"
        # Párrafos que el plan marcó `title` o `label` al inicio de un bloque cuya primera caja
        # sigue con más texto: el título y su lista en la misma caja («¡Elijamos una dinámica!»
        # sobre «1. Dato random…»). Antes salían con el peso del cuerpo y no se leían como título.
        # Sin roles, lo dice el autor: un primer párrafo en negrita seguido de su lista.
        unit_roles = {**{card.text: card.roles for card in cls.cards}, **cls.body_roles}
        leads: dict[str, list[str]] = {}
        for group in groups:
            bid = group[0]
            if kinds.get(bid):
                continue
            first = [p for p in spec.text_by_id(bid).paragraphs if p.text.strip()]
            roles = unit_roles.get(bid)
            if roles:
                head = list(itertools.takewhile(lambda role: role in ("title", "label"), roles))
            else:
                head = ["title"] if self._lead_heading(first) else []
            if head and len(head) < len(first):
                leads[bid] = head
        lead_style = {"title": self.kn.style("light", "title"), "label": self.kn.style("light", "card_label")}

        def lead_paras(bid: str, body_st: Style) -> list[RPara]:
            block = spec.text_by_id(bid)
            paras = [p for p in block.paragraphs if p.text.strip()]
            head = leads[bid]
            out = [rp for p, role in zip(paras, head) if (rp := restyle(p, lead_style[role], self.kn)).text.strip()]
            rest = self._paras(block.model_copy(update={"paragraphs": paras[len(head):]}), body_st, inline_bold=True)
            if out and rest:
                rest[0].space_before = g["paragraph_gap"]
            return out + rest

        def build(size: float, inner: float = inner_w):
            built, heights = [], []
            for group in groups:
                numbered = kinds.get(group[0]) == "card_number"
                parts = []
                for position, bid in enumerate(group):
                    kind = kinds.get(bid) if position == 0 else None
                    box_st = self.kn.style("light", kind) if kind else st.resized(size)
                    width = gutter if kind == "card_number" else inner - (gutter if numbered else 0.0)
                    paras = (lead_paras(bid, box_st) if position == 0 and bid in leads
                             else self._paras(spec.text_by_id(bid), box_st, inline_bold=kind is None))
                    if paras:
                        parts.append((kind, bid, *fix_orphans(paras, width, width * 0.85, self.safety)))
                sizes = [tm.block_height(p, w * self.safety) + 2 for _k, _b, p, w, _i in parts]
                if numbered and parts and parts[0][0] == "card_number":
                    body = sum(sizes[1:]) + g["block_gap"] * max(0, len(sizes) - 2)
                    heights.append(max(sizes[0], body))
                else:
                    heights.append(sum(sizes) + g["block_gap"] * max(0, len(sizes) - 1))
                built.append((numbered, parts))
            content = sum(heights) + g["paragraph_gap"] * max(0, len(heights) - 1)
            content += (side_h + g["paragraph_gap"]) if side else 0.0
            return built, heights, content

        # El cuerpo crece hasta `body_max` si cabe en el alto de las imágenes (el texto manda;
        # un mensaje chico junto a una imagen grande se pierde) y baja hasta el mínimo si no.
        image_top = min((p.box.y for p in pictures), default=top)
        image_h = (max(p.box.bottom for p in pictures) - image_top) if pictures else height
        target = min(image_h, height) - 2 * pad
        chosen = None
        for size in range(int(g["body_max"]), int(st.min or st.size) - 1, -1):
            built, heights, content = build(float(size))
            if content <= target or (size <= st.size and content + 2 * pad <= height):
                chosen = (built, heights, content)
                break
        # Bloques breves que apilados no caben: dos columnas dentro de la tarjeta, en orden
        # de lectura (primero la izquierda) y con la división que más equilibra las alturas.
        split_at, col_w = len(groups), inner_w
        if chosen is None and len(groups) >= 2 and not side:
            col_w = (inner_w - g["column_gap"]) / 2
            size = float(st.min or st.size)
            built2, heights2, _ = build(size, col_w)

            def column(hs):
                return sum(hs) + g["paragraph_gap"] * max(0, len(hs) - 1)

            k = min(range(1, len(groups)), key=lambda k: max(column(heights2[:k]), column(heights2[k:])))
            content2 = max(column(heights2[:k]), column(heights2[k:]))
            if content2 + 2 * pad <= height:
                chosen, split_at = (built2, heights2, content2), k
            else:
                col_w = inner_w
        if chosen is None:
            # Antes de declarar el desborde, la imagen cede ancho al mensaje.
            current = ratio or g["image_ratio"]
            narrower = [r for r in g.get("image_ratio_fallbacks", []) if r < current - 1e-6]
            if pictures and not side and narrower:
                del out.elements[before:]
                del out.compose_issues[issues_before:]
                return self._image_message(spec, cls, out, x, width, top, bottom, narrower[0])
            chosen = build(float(st.min or st.size))
            out.compose_issues.append(f"body_overflow:{chosen[2] + 2 * pad - height:.0f}pt")
        built, heights, content = chosen
        # Un mensaje muy breve (una fecha, un hashtag) va en una tarjeta a su medida, centrada
        # con la imagen: una tarjeta del alto de la imagen con una línea se ve vacía.
        compact = pictures and content < g["card_compact_ratio"] * image_h
        card_h = content + 2 * pad if compact or not message_card else max(content + 2 * pad,
                                                                           image_h if pictures else 0.0)
        card_h = min(card_h, height) if content + 2 * pad <= height else content + 2 * pad
        if compact or (not message_card and pictures and card_h <= image_h + 0.5):
            y = image_top + (image_h - card_h) / 2
        elif pictures and card_h <= image_h + 0.5:
            y = image_top
        else:
            y = top + max(0.0, (height - card_h) / 2)
        grp = "textcard1"
        if message_card:
            out.elements.append(RRect(role="text_card", box=Box(x=round(text_x, 2), y=round(y, 2),
                                                                w=round(text_w, 2), h=round(card_h, 2)),
                                      fill=self.kn.color(card["fill"]), line=self.kn.color(card["line"]),
                                      line_width=card.get("line_width", 0.75), radius=card["radius"],
                                      shadow=self.kn.shadow(card.get("shadow")), group=grp))
        else:
            out.elements.append(RRect(role="accent_bar", box=Box(x=round(text_x, 2), y=round(y, 2),
                                                                 w=g["accent_width"], h=round(card_h, 2)),
                                      # grupo propio: la barra acompaña al texto, no lo contiene
                                      fill=self.kn.color("blue"), line=None, radius=0, group="accent1"))
        cy = y + pad + max(0.0, card_h - 2 * pad - content) / 2
        if side:
            sx = text_x + pad_left
            for img in side:
                # Retrato de quien presenta: circular, como las fotos de las fichas de equipo.
                picture = self._round_photo(img, sx, cy, side_h, grp)
                out.elements.append(picture)
                sx = picture.box.right + g["image_gap"]
            cy += side_h + g["paragraph_gap"]
        top_y = cy
        for index, ((numbered, parts), group_h) in enumerate(zip(built, heights)):
            if index == split_at:
                cy = top_y   # segunda columna
            col_x = text_x + pad_left + (col_w + g["column_gap"] if index >= split_at else 0.0)
            start = cy
            by = cy
            for kind, bid, paras, w, iss in parts:
                out.compose_issues += iss
                if kind == "card_number":
                    out.elements.append(self._tx("body", paras, col_x, start, w, grp, [bid]))
                    continue
                bx = col_x + (gutter if numbered else 0.0)
                el = self._tx("body", paras, bx, by, w, grp, [bid])
                out.elements.append(el)
                by = el.box.bottom + g["block_gap"]
            cy = start + group_h + g["paragraph_gap"]
        return self._used_bottom(out, before, top)

    def _block_gallery(self, spec: SlideSpec, cls: SlideClassification, out: RenderedSlide,
                       top: float, height: float, g: dict) -> None:
        """Bloques con su propia imagen: tarjetas lado a lado, todas del mismo alto.

        Cada tarjeta lleva, de arriba abajo, su número o encabezado (si el bloque empieza con
        uno), su imagen completa y el resto del texto. La imagen toma el alto que deja el
        texto más largo de la fila, así las imágenes de una fila quedan alineadas.
        """
        card = self.kn.component("team_card")
        pad = card["padding"]
        n = len(cls.cards)
        st = self.kn.style("light", "body")

        def head_kind(group):
            if self._block_number(spec, group):
                return "card_number"
            return "card_title" if self._block_heading(spec, group) else None

        def attempt(columns: int, drop: float):
            """Tarjetas a `columns` por fila, con el cuerpo `drop` pt por debajo de su tamaño."""
            rows = -(-n // columns)
            card_w = (g["width"] - (columns - 1) * g["card_gap"]) / columns
            inner_w = card_w - 2 * pad
            row_h = (height - (rows - 1) * g["card_gap"]) / rows
            built = []
            for unit in cls.cards:
                kind = head_kind(unit.text_ids)
                parts = []
                for position, bid in enumerate(unit.text_ids):
                    heading = kind is not None and position == 0
                    base = self.kn.style("light", kind) if heading else st
                    box_st = base.resized(max(base.min or 11, base.size - drop))
                    paras = self._paras(spec.text_by_id(bid), box_st, inline_bold=not heading)
                    if paras:
                        parts.append((heading, bid, *fix_orphans(paras, inner_w, inner_w * 0.85, self.safety)))
                text_h = sum(tm.block_height(p, w * self.safety) + 2 for _h, _b, p, w, _i in parts)
                text_h += g["block_gap"] * max(0, len(parts) - 1)
                built.append((unit, parts, text_h))
            worst, image_area = 0.0, float("inf")
            for row in range(rows):
                members = built[row * columns:(row + 1) * columns]
                text_h = max(t for _u, _p, t in members)
                if any(unit.image for unit, _p, _t in members):
                    image_h = row_h - 2 * pad - text_h - g["paragraph_gap"]
                    image_area = min(image_area, image_h * inner_w)
                    worst = max(worst, row_h - image_h + g["gallery_image_min"])
                else:
                    worst = max(worst, text_h + 2 * pad)
            return {"columns": columns, "rows": rows, "card_w": card_w, "row_h": row_h, "built": built,
                    "overflow": worst - row_h, "area": image_area}

        # La rejilla que cabe con las imágenes más grandes; si ninguna cabe, se baja el cuerpo.
        options = sorted({min(n, c) for c in (g["gallery_columns"][min(n, max(g["gallery_columns"]))], n, 2, 3)})
        drop, max_drop = 0.0, st.size - (st.min or st.size)
        while True:
            tries = [attempt(columns, drop) for columns in options]
            fitting = [t for t in tries if t["overflow"] <= 0]
            if fitting or drop + 1 > max_drop:
                break
            drop += 1
        best = max(fitting, key=lambda t: t["area"]) if fitting else min(tries, key=lambda t: t["overflow"])
        if best["overflow"] > 0:
            out.compose_issues.append(f"body_overflow:{best['overflow']:.0f}pt")
        columns, row_h, card_w, built = best["columns"], best["row_h"], best["card_w"], best["built"]
        inner_w = card_w - 2 * pad
        for k, (unit, parts, _text_h) in enumerate(built):
            row, col = divmod(k, columns)
            members = built[row * columns:(row + 1) * columns]
            in_row = len(members)
            offset = (g["width"] - (in_row * card_w + (in_row - 1) * g["card_gap"])) / 2
            x = g["x"] + offset + col * (card_w + g["card_gap"])
            y = top + row * (row_h + g["card_gap"])
            grp = f"textcard{k + 1}"
            out.elements.append(RRect(role="text_card", box=Box(x=round(x, 2), y=round(y, 2), w=round(card_w, 2),
                                                                h=round(row_h, 2)),
                                      fill=self.kn.color(card["fill"]), line=self.kn.color(card["line"]),
                                      line_width=card.get("line_width", 0.75), radius=card["radius"],
                                      shadow=self.kn.shadow(card.get("shadow")), group=grp))
            # Alto de imagen común a la fila: lo que deja el texto más largo.
            row_text = max(t for _u, _p, t in members)
            image_h = row_h - 2 * pad - row_text - g["paragraph_gap"]
            cy = y + pad
            heads = [part for part in parts if part[0]]
            rest = [part for part in parts if not part[0]]
            for _heading, bid, paras, w, iss in heads:
                out.compose_issues += iss
                el = self._tx("body", paras, x + pad, cy, w, grp, [bid])
                out.elements.append(el)
                cy = el.box.bottom + g["block_gap"]
            if unit.image and image_h > 0:
                picture = self._fit_image(spec.image_by_id(unit.image), x + pad, cy, inner_w, image_h, grp,
                                          align=(0.5, 0.5))
                out.elements.append(picture)
                cy += image_h + g["paragraph_gap"]
            for _heading, bid, paras, w, iss in rest:
                out.compose_issues += iss
                el = self._tx("body", paras, x + pad, cy, w, grp, [bid])
                out.elements.append(el)
                cy = el.box.bottom + g["block_gap"]

    def _photo_cards(self, spec: SlideSpec, cls: SlideClassification, out: RenderedSlide,
                     top: float, height: float, g: dict) -> None:
        """Bloques que llevan cada uno su foto: fichas iguales con la foto y su texto.

        Todas las fotos comparten el alto (el que deja la más ancha en su espacio, el que
        sostiene la resolución de cada una y `photo_card_max`), así los textos arrancan a la
        misma altura; ninguna se recorta ni se deforma. La foto va arriba del texto o a su
        izquierda: se elige la disposición con las fotos más grandes y todo el texto a su
        tamaño. La ficha mide lo que lleva (estirada al alto libre quedaba medio vacía) y la
        rejilla se centra en el alto disponible.
        """
        card = self.kn.component("team_card")
        pad = card["padding"]
        units = cls.cards
        n = len(units)
        images = {unit.image: self._trim_transparent(spec.image_by_id(unit.image)) for unit in units}

        def shape(img: ImageBlock) -> tuple[float, float]:
            """(ancho / alto, alto máximo sin ampliarla de más), con la regla de `_fit_image`."""
            with Image.open(img.path) as im:
                iw, ih = im.size
            l, t, r, b = img.crop
            iw, ih = iw * (1 - l - r), ih * (1 - t - b)
            return iw / ih, ih * max(img.box.w / iw, 72 / MIN_PPI)

        shapes = {iid: shape(img) for iid, img in images.items()}

        def short(unit) -> bool:
            block = spec.text_by_id(unit.text)
            return (len(unit.text_ids) == 1 and 1 <= len([p for p in block.paragraphs if p.text.strip()]) <= 2
                    and len(" ".join(block.text.split())) <= g["caption_max_chars"])

        # Rótulos breves en todas las fichas: van como rótulo; si alguna trae un texto, todas
        # van con el cuerpo (las fichas de una rejilla no mezclan estilos).
        base = self.kn.style("light", "item_title" if all(short(unit) for unit in units) else "body")

        def head_kind(group):
            if self._block_number(spec, group):
                return "card_number"
            return "card_title" if self._block_heading(spec, group) else None

        def counted(unit) -> int:
            return sum(1 for bid in unit.text_ids for p in spec.text_by_id(bid).paragraphs if p.text.strip())

        # Si el plan dio la jerarquía de cada ficha (rótulo, título, cuerpo), manda el plan: la
        # imagen arriba y debajo el texto con el estilo de su rol. Antes se adivinaba el
        # encabezado y el rótulo «IA GENERATIVA» salía como título y el título como texto
        # corrido (deck de cliente, 2026-11-19).
        by_role = all(len(unit.roles) == counted(unit) for unit in units) and any(
            role != "body" for unit in units for role in unit.roles)

        def texts(width: float, drop: float):
            built = []
            for unit in units:
                if by_role:
                    title = self.kn.style("light", "card_title")
                    sizes = {"card_title": max(title.min or title.size, title.size - drop)}
                    paras = self._card_paras(self._unit_block(spec, unit), unit.roles, sizes)
                    built.append([(False, tuple(unit.text_ids), *fix_orphans(paras, width, width * 0.85, self.safety))])
                    continue
                kind = head_kind(unit.text_ids)
                parts = []
                for position, bid in enumerate(unit.text_ids):
                    heading = kind is not None and position == 0
                    st = self.kn.style("light", kind) if heading else base
                    st = st.resized(max(st.min or 11, st.size - drop))
                    paras = self._paras(spec.text_by_id(bid), st, inline_bold=not heading)
                    if paras:
                        parts.append((heading, bid, *fix_orphans(paras, width, width * 0.85, self.safety)))
                built.append(parts)
            return built

        def stacked(parts) -> float:
            return (sum(tm.block_height(p, w * self.safety) + 2 for _h, _b, p, w, _i in parts)
                    + g["block_gap"] * max(0, len(parts) - 1))

        def attempt(columns: int, side: bool, drop: float) -> dict:
            rows = -(-n // columns)
            card_w = (g["width"] - (columns - 1) * g["card_gap"]) / columns
            inner = card_w - 2 * pad
            photo_w = inner * g["photo_side_ratio"] if side else inner
            text_w = inner - photo_w - pad if side else inner
            built = texts(text_w, drop)
            room = (height - (rows - 1) * g["card_gap"]) / rows - 2 * pad
            photo_h = min(g["photo_card_max"], *(min(photo_w / shapes[u.image][0], shapes[u.image][1])
                                                  for u in units))
            if side:
                text_h = max(stacked(parts) for parts in built)
                photo_h = min(photo_h, room)
                heads_h, rest_h, content = 0.0, text_h, max(photo_h, text_h)
                overflow = text_h - room
            else:
                # Encabezados arriba de la foto y el resto debajo, al mismo alto en todas.
                heads_h = max(stacked([p for p in parts if p[0]]) for parts in built)
                rest_h = max(stacked([p for p in parts if not p[0]]) for parts in built)
                around = (heads_h + g["block_gap"] if heads_h else 0.0) + (rest_h + g["paragraph_gap"] if rest_h else 0.0)
                photo_h = min(photo_h, room - around)
                content = around + photo_h
                overflow = g["gallery_image_min"] - photo_h
            return {"columns": columns, "side": side, "rows": rows, "card_w": card_w, "inner": inner,
                    "photo_w": photo_w, "photo_h": photo_h, "built": built, "heads_h": heads_h,
                    "card_h": content + 2 * pad, "overflow": overflow}

        tops = sorted({min(n, c) for c in (g["gallery_columns"][min(n, max(g["gallery_columns"]))], n, 2, 3)})
        options = [(c, False) for c in tops] + [(c, True) for c in sorted({1, min(n, 2)})]
        st = base
        drop, max_drop = 0.0, st.size - (st.min or st.size)
        while True:
            tries = [attempt(columns, side, drop) for columns, side in options]
            fitting = [t for t in tries if t["overflow"] <= 0 and t["photo_h"] >= g["gallery_image_min"]]
            if fitting or drop + 1 > max_drop:
                break
            drop += 1
        if fitting:
            # Las fotos más grandes; a 2 pt o menos, la foto arriba y menos filas.
            tallest = max(t["photo_h"] for t in fitting)
            best = min((t for t in fitting if t["photo_h"] >= tallest - 2), key=lambda t: (t["side"], t["rows"]))
        else:
            best = min(tries, key=lambda t: t["overflow"])
            out.compose_issues.append(f"body_overflow:{max(best['overflow'], 0):.0f}pt")

        columns, rows, card_w, card_h = best["columns"], best["rows"], best["card_w"], best["card_h"]
        photo_w, photo_h, inner = best["photo_w"], best["photo_h"], best["inner"]
        grid_h = rows * card_h + (rows - 1) * g["card_gap"]
        y0 = top + max(0.0, (height - grid_h) / 2)
        for k, (unit, parts) in enumerate(zip(units, best["built"])):
            row, col = divmod(k, columns)
            in_row = min(columns, n - row * columns)
            offset = (g["width"] - (in_row * card_w + (in_row - 1) * g["card_gap"])) / 2
            x = g["x"] + offset + col * (card_w + g["card_gap"])
            y = y0 + row * (card_h + g["card_gap"])
            grp = f"textcard{k + 1}"
            out.elements.append(RRect(role="text_card", box=Box(x=round(x, 2), y=round(y, 2), w=round(card_w, 2),
                                                                h=round(card_h, 2)),
                                      fill=self.kn.color(card["fill"]), line=self.kn.color(card["line"]),
                                      line_width=card.get("line_width", 0.75), radius=card["radius"],
                                      shadow=self.kn.shadow(card.get("shadow")), group=grp))
            img = images[unit.image]
            if best["side"]:
                out.elements.append(self._fit_image(img, x + pad, y + pad, photo_w, photo_h, grp, align=(0.5, 0.0)))
                tx, cy = x + pad + photo_w + pad, y + pad
                for _heading, bid, paras, w, iss in parts:
                    out.compose_issues += iss
                    el = self._tx("body", paras, tx, cy, w, grp, list(bid) if isinstance(bid, tuple) else [bid])
                    out.elements.append(el)
                    cy = el.box.bottom + g["block_gap"]
                continue
            cy = y + pad
            for _heading, bid, paras, w, iss in (p for p in parts if p[0]):
                out.compose_issues += iss
                el = self._tx("body", paras, x + pad, cy, w, grp, [bid])
                out.elements.append(el)
                cy = el.box.bottom
            cy = y + pad + (best["heads_h"] + g["block_gap"] if best["heads_h"] else 0.0)
            out.elements.append(self._fit_image(img, x + pad, cy, inner, photo_h, grp, align=(0.5, 0.0)))
            cy += photo_h + g["paragraph_gap"]
            for _heading, bid, paras, w, iss in (p for p in parts if not p[0]):
                out.compose_issues += iss
                el = self._tx("body", paras, x + pad, cy, w, grp, list(bid) if isinstance(bid, tuple) else [bid])
                out.elements.append(el)
                cy = el.box.bottom + g["block_gap"]

    @staticmethod
    def _block_number(spec: SlideSpec, group: list[str]) -> bool:
        """La primera caja de un bloque es su número (1, 2), si el bloque sigue con texto."""
        head = spec.text_by_id(group[0]).text.strip()
        return len(group) > 1 and bool(re.fullmatch(r"\d{1,2}[.)]?", head))

    @staticmethod
    def _lead_heading(paras: list[Paragraph]) -> bool:
        """El primer párrafo de una caja es su título cuando el autor lo puso entero en negrita,
        es breve, no es un ítem y le sigue una lista con viñetas o numerada."""
        if len(paras) < 2 or paras[0].bullet:
            return False
        visible = [run for run in paras[0].runs if run.text.strip()]
        return (bool(visible) and all(run.bold for run in visible) and len(paras[0].text.strip()) <= 60
                and any(p.bullet for p in paras[1:]))

    @staticmethod
    def _block_heading(spec: SlideSpec, group: list[str]) -> bool:
        """La primera caja de un bloque es su encabezado cuando es un rótulo: un solo párrafo
        breve seguido de más texto (o más grande que ese texto en el origen)."""
        if len(group) < 2:
            return False
        blocks = [spec.text_by_id(bid) for bid in group]
        head = [p for p in blocks[0].paragraphs if p.text.strip()]
        if len(head) != 1:
            return False

        def largest(block):
            return max((r.size for p in block.paragraphs for r in p.runs if r.size and r.text.strip()), default=None)

        rest = [largest(block) for block in blocks[1:]]
        bigger = largest(blocks[0]) is not None and all(rest) and largest(blocks[0]) > max(rest)
        label = len(head[0].text.strip()) <= 60 and sum(len(b.text) for b in blocks[1:]) > len(head[0].text)
        # Un rótulo en mayúsculas («ACTIVIDADES CLAVE») es encabezado aunque su cuerpo sea breve.
        caps = head[0].text.strip()
        upper = caps.isupper() and len(caps) <= 40 and any(b.text.strip() for b in blocks[1:])
        return bigger or label or upper

    def _circles(self, spec: SlideSpec, cls: SlideClassification) -> RenderedSlide:
        """Unidades como un grupo de círculos alineados; la variante de foco agranda uno."""
        out = self._base(spec, cls, "light")
        g = self.kn.geometry("circles")
        top = self._header(spec, cls, out, "title", 2) + g["body_gap"]
        self._circle_row(spec, cls, out, g["x"], g["width"], top, self.kn.tokens["margins"]["bottom_limit"])
        self._notes(spec, cls, out)
        return out

    def _circle_row(self, spec: SlideSpec, cls: SlideClassification, out: RenderedSlide, x: float, width: float,
                    top: float, bottom: float, natural: bool = False) -> float:
        """Círculos alineados y centrados en una región; devuelve el borde inferior usado.
        `natural`: arriba de la región (para medir), no centrados en su alto."""
        g, comp = self.kn.geometry("circles"), self.kn.component("circle")
        available = bottom - top
        n = len(cls.cards)
        focus = {"center_focus": n // 2 if n % 2 else None, "right_focus": n - 1}.get(cls.variant or "")
        scales = [g["focus_scale"] if index == focus else 1.0 for index in range(n)]
        base = min(g["max_diameter"], (width - (n - 1) * g["circle_gap"]) / sum(scales),
                   available / max(scales))
        diameters = [base * scale for scale in scales]

        def measure(sizes):
            built = []
            for c, d in zip(cls.cards, diameters):
                width = d * g["text_inset"]
                paras = self._card_paras(self._unit_block(spec, c), c.roles, sizes, prefix="circle", align="ctr")
                built.append(fix_orphans(paras, width, width * 0.85, self.safety))
            return built

        def fits(built):
            return all(tm.block_height(p, w * self.safety) <= d * g["text_inset"]
                       for (p, w, _), d in zip(built, diameters))

        built = self._shrink({}, ["circle_number", "circle_title"], fits, measure)
        if not fits(built):
            out.compose_issues.append("cards_overflow:circle_text")
        total_w = sum(diameters) + (n - 1) * g["circle_gap"]
        x = x + (width - total_w) / 2
        center_y = top + (max(diameters) if natural else available) / 2
        for k, (c, d, (paras, w, iss)) in enumerate(zip(cls.cards, diameters, built)):
            grp = f"circle{k + 1}"
            out.compose_issues += iss
            fill = comp["focus_fill"] if k == focus else comp["fill"]
            out.elements.append(RRect(role="circle", shape="ellipse",
                                      box=Box(x=round(x, 2), y=round(center_y - d / 2, 2), w=round(d, 2), h=round(d, 2)),
                                      fill=self.kn.color(fill), group=grp))
            el = self._tx("card_text", paras, x + (d - w) / 2, center_y, w, grp, [c.text])
            el.box.y = round(center_y - el.box.h / 2, 2)
            out.elements.append(el)
            x += d + g["circle_gap"]
        return center_y + max(diameters, default=0.0) / 2

    def _closing(self, spec: SlideSpec, cls: SlideClassification) -> RenderedSlide:
        """Despedida universal aprobada; sustituye las variantes históricas de cierre."""
        from .design_policies import closing_rendered
        return closing_rendered(self.kn, spec.index, spec.notes, client_logo=self.client_logo)

    # ------------------------------------------------------------ tablas, guías y matrices

    def _styled(self, block: TextBlock, first: str, rest: str, align: str = "l") -> list[RPara]:
        """Primer párrafo con un estilo y los siguientes con otro (rótulo + detalle)."""
        paras = [p for p in block.paragraphs if p.text.strip()]
        out = []
        for index, paragraph in enumerate(paras):
            st = self.kn.style("light", first if index == 0 else rest)
            rp = restyle(paragraph, st, self.kn, inline_bold=True, align=align)
            if not rp.text.strip():
                continue
            rp.space_before = 2 if out else 0
            out.append(rp)
        return out

    def _aside_paras(self, spec, group) -> list[RPara]:
        """Panel lateral: con roles por párrafo del plan, rótulo en azul pálido, título en
        blanco negrita y cuerpo en blanco; sin roles, la primera caja es el rótulo."""
        block = self._unit_block(spec, group)
        paras = [p for p in block.paragraphs if p.text.strip()]
        if not group.roles or len(group.roles) != len(paras):
            return self._boxes_paras(spec, group.text_ids, "aside_title", "aside_body")
        out, prev = [], None
        for paragraph, role in zip(paras, group.roles):
            st = self.kn.style("light", "aside_title" if role in ("label", "number") else "aside_body")
            rp = restyle(paragraph, st, self.kn, inline_bold=True)
            if role == "title":
                rp.runs = [r.model_copy(update={"bold": True}) for r in rp.runs]
            if not rp.text.strip():
                continue
            rp.space_before = 0 if prev is None else (6 if role == "title" else 2)
            out.append(rp)
            prev = role
        return out

    def _boxes_paras(self, spec, ids: list[str], first: str, rest: str, align: str = "l") -> list[RPara]:
        """Varias cajas en un bloque: la primera caja con `first`, las demás con `rest`."""
        out = []
        for index, bid in enumerate(ids):
            st = first if index == 0 else rest
            paras = self._paras(spec.text_by_id(bid), self.kn.style("light", st), inline_bold=True, align=align)
            if out and paras:
                paras[0].space_before = 4
            out += paras
        return out

    def _matrix(self, spec: SlideSpec, cls: SlideClassification) -> RenderedSlide:
        """Tabla: fila de encabezados navy, columna de rótulos y celdas con borde.

        Las celdas de cada fila se leen de izquierda a derecha en el origen y las
        proporciones de columna también salen de ahí: se cambia el estilo, no la tabla.
        """
        out = self._base(spec, cls, "light")
        g = self.kn.geometry("matrix")
        top = self._header(spec, cls, out, "title", 2) + g["body_gap"]
        bottom = self.kn.tokens["margins"]["bottom_limit"]
        if cls.notes:
            bottom = min(bottom, self._notes_top(spec, cls, out) - g["banner_gap"])
        banner_paras, banner_h = self._banner_block(spec, cls, g["width"])
        if banner_paras:
            bottom -= banner_h + g["banner_gap"]
        used = self._matrix_table(spec, cls, out, g["x"], g["width"], top, bottom)
        if banner_paras:
            self._draw_banner(cls, out, banner_paras, banner_h, used + g["banner_gap"], g)
        self._notes(spec, cls, out)
        return out

    def _matrix_table(self, spec: SlideSpec, cls: SlideClassification, out: RenderedSlide, x: float,
                      width: float, top: float, bottom: float) -> float:
        """La tabla de matrix dentro de una región; devuelve el borde inferior usado."""
        comp = self.kn.component("matrix")
        gap, pad = comp["gap"], comp["padding"]

        rows = [sorted(card.text_ids, key=lambda bid: spec.text_by_id(bid).box.x) for card in cls.cards]
        ncols = max(len(row) for row in rows)
        centers, widths = [], []
        for col in range(ncols):
            boxes = [spec.text_by_id(row[col]).box for row in rows if len(row) > col]
            centers.append(sum(b.x + b.w / 2 for b in boxes) / len(boxes))
            widths.append(sum(b.w for b in boxes) / len(boxes))
        usable = width - gap * (ncols - 1)
        col_w = [usable * w / sum(widths) for w in widths]
        if ncols > 1 and col_w[0] < usable * comp["label_ratio"]:
            # La columna de rótulos tiene un ancho mínimo: un rótulo partido en cuatro
            # líneas estira toda la fila. El resto conserva las proporciones del origen.
            col_w[0] = usable * comp["label_ratio"]
            rest = sum(widths[1:])
            col_w[1:] = [(usable - col_w[0]) * w / rest for w in widths[1:]]
        labelled = ncols > 1
        # Una columna que parte un contenido breve cede la línea que le falta a otra con aire:
        # cada columna pide el ancho de su celda más larga en una línea (hasta la mitad).
        pad0 = comp["padding"]
        need = []
        for col in range(ncols):
            style = "matrix_label" if labelled and col == 0 else "matrix_cell"
            hugs = [hug_width(self._paras(spec.text_by_id(row[col]), self.kn.style("light", style),
                                          inline_bold=True), self.safety)
                    for row in rows if len(row) > col]
            need.append(min(max(hugs, default=0.0) + 2 * pad0 + 1, usable / 2))
        deficit = sum(max(0.0, n - w) for n, w in zip(need, col_w))
        slack = [max(0.0, w - n) for n, w in zip(need, col_w)]
        if 0 < deficit <= sum(slack):
            give = deficit / sum(slack)
            col_w = [max(n, w) if n > w else w - s * give for n, w, s in zip(need, col_w, slack)]
        col_x = [x + sum(col_w[:k]) + gap * k for k in range(ncols)]

        header_cols: dict[int, list[str]] = {}
        for bid in cls.named.get("header", []):
            box = spec.text_by_id(bid).box
            col = min(range(ncols), key=lambda k: abs(centers[k] - (box.x + box.w / 2)))
            header_cols.setdefault(col, []).append(bid)
        for col in header_cols:
            header_cols[col].sort(key=lambda bid: spec.text_by_id(bid).box.y)

        def cell_paras(col: int, bid: str):
            width = col_w[col] - 2 * pad
            if labelled and col == 0:
                paras = self._styled(spec.text_by_id(bid), "matrix_label", "matrix_label_sub")
            else:
                paras = self._paras(spec.text_by_id(bid), self.kn.style("light", "matrix_cell"), inline_bold=True)
            return fix_orphans(paras, width, width * 0.9, self.safety)

        def build_heads(title_size: float | None):
            heads = {}
            for col, ids in header_cols.items():
                width = col_w[col] - 2 * pad
                paras = self._boxes_paras(spec, ids, "matrix_head_label" if len(ids) > 1 else "matrix_head_title",
                                          "matrix_head_title")
                if title_size:
                    paras = [p if p.runs and p.runs[0].size != self.kn.style("light", "matrix_head_title").size
                             else resize([p], title_size)[0] for p in paras]
                heads[col] = fix_orphans(paras, width, width * 0.9, self.safety)
            height = max((tm.block_height(p, w * self.safety) for p, w, _ in heads.values()), default=0.0)
            return heads, (height + 2 * pad if heads else 0.0)

        # Una fila con menos celdas que columnas («Total» y su monto) ubica cada celda en la
        # columna más cercana a su posición de origen, no en la siguiente libre.
        def row_columns(row: list[str]) -> list[int]:
            if len(row) >= ncols:
                return list(range(len(row)))
            mapped, used = [], -1
            for position, bid in enumerate(row):
                box = spec.text_by_id(bid).box
                free = [k for k in range(used + 1, ncols - (len(row) - position - 1))]
                col = 0 if labelled and position == 0 else min(free, key=lambda k: abs(centers[k] - (box.x + box.w / 2)))
                mapped.append(col)
                used = col
            return mapped

        row_cols = [row_columns(row) for row in rows]
        cells = [[cell_paras(col, bid) for col, bid in zip(cols, row)] for cols, row in zip(row_cols, rows)]
        row_h = [max(tm.block_height(p, w * self.safety) for p, w, _ in row) + 2 * pad for row in cells]
        head_style = self.kn.style("light", "matrix_head_title")
        heads, head_h = build_heads(None)
        size = head_style.size
        # El encabezado baja hasta su mínimo antes de declarar desborde; las celdas no.
        while (sum(row_h) > bottom - top - (head_h + gap if heads else 0.0) - gap * (len(rows) - 1)
               and heads and size - 1 >= (head_style.min or size)):
            size -= 1
            heads, head_h = build_heads(size)
        available = bottom - top - (head_h + gap if heads else 0.0) - gap * (len(rows) - 1)
        if sum(row_h) > available:
            out.compose_issues.append(f"cards_overflow:{sum(row_h) - available:.0f}pt")
        elif cls.fill:
            extra = (available - sum(row_h)) / len(rows)
            row_h = [h + extra for h in row_h]

        y = top
        if heads:
            for col, (paras, w, iss) in heads.items():
                out.compose_issues += iss
                grp = f"head{col + 1}"
                out.elements.append(RRect(role="matrix_head", box=Box(x=col_x[col], y=y, w=col_w[col], h=head_h),
                                          fill=self.kn.color(comp["header_fill"]), line=self.kn.color(comp["label_line"]),
                                          line_width=comp["label_line_width"], radius=comp["radius"], group=grp))
                text = self._tx("matrix_head_text", paras, col_x[col] + pad, y + pad, w, grp, header_cols[col])
                text.box.h = round(max(0.0, head_h - 2 * pad), 2)
                text.box.y = round(y + head_h - pad - text.box.h, 2)   # los títulos se alinean abajo
                out.elements.append(text)
            y += head_h + gap
        for r, (row, height) in enumerate(zip(cells, row_h)):
            for position, (col, (paras, w, iss)) in enumerate(zip(row_cols[r], row)):
                out.compose_issues += iss
                grp = f"cell{r + 1}_{col + 1}"
                label = labelled and col == 0
                fill = comp["label_fill"] if label else comp["cell_fill"]
                out.elements.append(RRect(role="matrix_cell", box=Box(x=col_x[col], y=y, w=col_w[col], h=height),
                                          fill=self.kn.color(fill),
                                          line=self.kn.color(comp["label_line"]),
                                          line_width=comp["label_line_width"], radius=comp["radius"],
                                          shadow=None if label else self.kn.shadow(comp["cell_shadow"]), group=grp))
                text = self._tx("matrix_text", paras, col_x[col] + pad, y + pad, w, grp, [rows[r][position]])
                text.box.h = round(max(0.0, height - 2 * pad), 2)
                if label and not cls.fill:
                    text.box.y = round(y + (height - text.box.h) / 2, 2)
                out.elements.append(text)
                if cls.fill and not label:
                    self._writing_lines(out, col_x[col] + pad, text.box.bottom, col_w[col] - 2 * pad,
                                        y + height - pad, grp)
            y += height + gap
        return y - gap

    def _sections(self, spec: SlideSpec, cls: SlideClassification) -> RenderedSlide:
        """Secciones: rótulo como etiqueta navy, párrafo introductorio y una card breve por
        subtítulo con su texto, en dos columnas. Nunca una card enorme con un solo rótulo."""
        out = self._base(spec, cls, "light")
        g, comp, tag = self.kn.geometry("sections"), self.kn.component("card"), self.kn.component("tag")
        top = self._header(spec, cls, out, "title", 2) + g["body_gap"]
        bottom = self.kn.tokens["margins"]["bottom_limit"]
        if cls.notes:
            bottom = min(bottom, self._notes_top(spec, cls, out) - g["row_gap"])
        pad = comp["padding"]
        y = top
        for s_index, unit in enumerate(cls.cards):
            block = self._unit_block(spec, unit)
            paras = [p for p in block.paragraphs if p.text.strip()]
            roles = list(unit.roles)
            grp = f"section{s_index + 1}"
            k, tag_right = 0, None
            while k < len(roles) and roles[k] == "label":
                tp = [restyle(paras[k], self.kn.style("light", "tag"), self.kn, align="ctr")]
                w = hug_width(tp, self.safety) + 2 * tag["padding_x"]
                out.elements.append(RRect(role="tag", box=Box(x=g["x"], y=round(y, 2), w=round(w, 2), h=tag["height"]),
                                          fill=self.kn.color(tag["fill"]), radius=tag["radius"], group=grp))
                el = self._tx("tag_text", tp, g["x"] + tag["padding_x"], y, w - 2 * tag["padding_x"], grp, [unit.text])
                el.box.y = round(y + (tag["height"] - el.box.h) / 2, 2)
                out.elements.append(el)
                tag_right = (g["x"] + w, y)
                y += tag["height"] + g["tag_gap"]
                k += 1
            lead = []
            while k < len(roles) and roles[k] != "title":
                lead.append(restyle(paras[k], self.kn.style("light", "list_title"), self.kn, inline_bold=True))
                k += 1
            if lead:
                # Una bajada breve va en la línea de la etiqueta, a su derecha.
                room = g["x"] + g["width"] - (tag_right[0] + g["tag_gap"]) if tag_right else 0.0
                if tag_right and len(lead) == 1 and hug_width(lead, self.safety) <= room:
                    lx, ly = tag_right[0] + g["tag_gap"], tag_right[1]
                    el = self._tx("list_title", lead, lx, ly, room, grp, unit.text_ids)
                    el.box.y = round(ly + (tag["height"] - el.box.h) / 2, 2)
                    out.elements.append(el)
                    y += g["lead_gap"] - g["tag_gap"]
                else:
                    el = self._tx("list_title", lead, g["x"], y, g["width"], grp, unit.text_ids)
                    out.elements.append(el)
                    y = el.box.bottom + g["lead_gap"]
            groups: list[tuple[list, list[str]]] = []
            for paragraph, role in zip(paras[k:], roles[k:]):
                if role == "title" or not groups:
                    groups.append(([], []))
                groups[-1][0].append(paragraph)
                groups[-1][1].append(role)
            if not groups:
                continue
            columns = min(g["columns"], len(groups))
            card_w = (g["width"] - (columns - 1) * g["column_gap"]) / columns
            inner = card_w - 2 * pad
            rows = -(-len(groups) // columns)

            def measure(sizes):
                built = []
                for group_paras, group_roles in groups:
                    sub = block.model_copy(update={"paragraphs": group_paras})
                    ps = self._card_paras(sub, group_roles, sizes)
                    built.append(fix_orphans(ps, inner, inner * 0.9, self.safety))
                heights = [tm.block_height(p, w * self.safety) + 2 * pad for p, w, _ in built]
                row_h = [max(heights[r * columns:(r + 1) * columns]) for r in range(rows)]
                return built, row_h

            def fits(result):
                return y + sum(result[1]) + (rows - 1) * g["row_gap"] <= bottom

            built, row_h = self._shrink({}, ["card_title"], fits, measure)
            if not fits((built, row_h)):
                out.compose_issues.append(f"cards_overflow:{y + sum(row_h) + (rows - 1) * g['row_gap'] - bottom:.0f}pt")
            for index, (ps, w, iss) in enumerate(built):
                row, col = divmod(index, columns)
                cx = g["x"] + col * (card_w + g["column_gap"])
                cy = y + sum(row_h[:row]) + row * g["row_gap"]
                cgrp = f"{grp}_card{index + 1}"
                out.compose_issues += iss
                out.elements.append(RRect(role="card", box=Box(x=cx, y=round(cy, 2), w=card_w, h=round(row_h[row], 2)),
                                          fill=self.kn.color(comp["fill"]), line=self.kn.color(comp["line"]),
                                          line_width=comp.get("line_width", 0.75), radius=comp["radius"],
                                          shadow=self.kn.shadow(comp.get("shadow")), group=cgrp))
                out.elements.append(self._tx("card_text", ps, cx + pad, cy + pad, w, cgrp, unit.text_ids))
            y += sum(row_h) + (rows - 1) * g["row_gap"] + g["section_gap"]
        self._notes(spec, cls, out)
        return out

    def _tags(self, spec, cls, out) -> None:
        """Etiquetas de meta (modalidad, duración) como píldoras arriba a la derecha."""
        ids = cls.named.get("tags", [])
        if not ids:
            return
        g, comp = self.kn.geometry(cls.layout), self.kn.component("tag")
        right = g["x"] + g["width"]
        for index, bid in enumerate(reversed(ids)):
            paras = self._paras(spec.text_by_id(bid), self.kn.style("light", "tag"), align="ctr")
            w = hug_width(paras, self.safety) + 2 * comp["padding_x"]
            x = right - w
            grp = f"tag{len(ids) - index}"
            out.elements.append(RRect(role="tag", box=Box(x=round(x, 2), y=g["tag_top"], w=round(w, 2), h=comp["height"]),
                                      fill=self.kn.color(comp["fill"]), radius=comp["radius"], group=grp))
            text = self._tx("tag_text", paras, x + comp["padding_x"], g["tag_top"], w - 2 * comp["padding_x"], grp, [bid])
            text.box.y = round(g["tag_top"] + (comp["height"] - text.box.h) / 2, 2)
            out.elements.append(text)
            right = x - comp["gap"]

    def _list_aside(self, spec: SlideSpec, cls: SlideClassification) -> RenderedSlide:
        """Pasos numerados a la izquierda y paneles navy a la derecha (guías de dinámica)."""
        out = self._base(spec, cls, "light")
        g = self.kn.geometry("list_aside")
        self._tags(spec, cls, out)
        top = self._header(spec, cls, out, "title", 2) + g["body_gap"]
        bottom = self.kn.tokens["margins"]["bottom_limit"]
        has_aside = bool(cls.groups)
        list_w = g["width"] * g["list_ratio"] if has_aside else g["width"]
        x = g["x"]
        list_bottom = self._steps(spec, cls, cls.cards, out, x, list_w, top, bottom - g["footer_air"], g)
        if has_aside:
            ax = x + list_w + g["column_gap"]
            if cls.fill:
                self._asides(spec, cls.groups, out, ax, g["x"] + g["width"] - ax, top, bottom,
                             max(list_bottom, bottom))
            else:
                # Los paneles miden lo que su texto y se centran frente a la lista. Estirados al
                # alto de la lista quedaban con el doble de navy que de texto, y la auditoría
                # (`excessive_card_space`) los bloqueaba sin que el plan pudiera corregirlo
                # (dos decks internos, 2026-10-27).
                before = len(out.elements)
                aside_bottom = self._asides(spec, cls.groups, out, ax, g["x"] + g["width"] - ax, top, bottom, top)
                shift = max(0.0, (list_bottom - aside_bottom) / 2)
                for el in out.elements[before:]:
                    el.box.y = round(el.box.y + shift, 2)
        self._notes(spec, cls, out)
        return out

    def _steps(self, spec: SlideSpec, cls: SlideClassification, cards: list, out: RenderedSlide,
               x: float, list_w: float, top: float, bottom: float, g: dict, decorate: bool = False) -> float:
        """Título de lista opcional y pasos (número en círculo si el autor numeró) en una región.

        Reparte el aire sobrante entre los pasos hasta `max_item_gap`; devuelve el borde inferior.
        """
        step = self.kn.component("step")
        y = top
        if cls.named.get("list_title"):
            bid = cls.named["list_title"][0]
            paras = self._paras(spec.text_by_id(bid), self.kn.style("light", "list_title"))
            el = self._tx("list_title", paras, x, y, list_w, "list_title", [bid])
            out.elements.append(el)
            y = el.box.bottom + 8

        numbered = [len(c.roles) > 1 and c.roles[0] == "number" for c in cards]
        ornament = decorate and not any(numbered)
        text_x = x + (step["diameter"] + step["gap"] if any(numbered) or ornament else 0)
        text_w = x + list_w - text_x
        items = []
        for index, (card, has_number) in enumerate(zip(cards, numbered), start=1):
            block = self._unit_block(spec, card)
            number = self._card_paras(block, card.roles, {}, prefix="step", stop=1) if has_number else None
            if ornament:
                number = self._ornament_number(index, "step", {})
            rest = self._card_paras(block, card.roles, {}, prefix="step", start=1 if has_number else 0)
            rest, w, iss = fix_orphans(rest, text_w, text_w * 0.85, self.safety)
            out.compose_issues += iss
            items.append((card, number, rest, w))
        # Alto real de cada caja (el texto lleva 2 pt de holgura) y aire hasta el footer.
        heights = [max(tm.block_height(rest, w * self.safety) + 2, step["diameter"]) for _, _, rest, w in items]
        available = bottom - y
        spare = available - sum(heights)
        item_gap = min(g["max_item_gap"], spare / max(1, len(items) - 1)) if len(items) > 1 else 0
        if spare < g["item_gap"] * (len(items) - 1):
            out.compose_issues.append(f"cards_overflow:{g['item_gap'] * (len(items) - 1) - spare:.0f}pt")
        for k, ((card, number, rest, w), height) in enumerate(zip(items, heights)):
            grp = f"step{k + 1}"
            if number:
                d = step["diameter"]
                out.elements.append(RRect(role="step", shape="ellipse", box=Box(x=x, y=round(y, 2), w=d, h=d),
                                          fill=self.kn.color(step["fill"]), group=f"{grp}n"))
                num_paras = [p.model_copy(update={"align": "ctr"}) for p in number]
                nt = self._tx("step_number", num_paras, x, y, d, f"{grp}n", [] if ornament else [card.text])
                nt.box.y = round(y + (d - nt.box.h) / 2, 2)
                nt.brand = ornament
                out.elements.append(nt)
            body = self._tx("step_text", rest, text_x, y, w, grp, card.text_ids)
            if number and body.box.h < step["diameter"]:
                body.box.y = round(y + (step["diameter"] - body.box.h) / 2, 2)
            out.elements.append(body)
            y += height + item_gap
        return y - item_gap

    def _asides(self, spec: SlideSpec, groups: list, out: RenderedSlide, ax: float, aw: float,
                top: float, bottom: float, area_bottom: float) -> float:
        """Paneles navy apilados en una región; crecen hasta `area_bottom`. Devuelve su borde inferior."""
        aside = self.kn.component("aside")
        inner = aw - 2 * aside["padding"]
        built = []
        for group in groups:
            paras = self._aside_paras(spec, group)
            paras, w, iss = fix_orphans(paras, inner, inner * 0.85, self.safety)
            out.compose_issues += iss
            built.append((group, paras, w, tm.block_height(paras, w * self.safety) + 2 * aside["padding"]))
        total = sum(h for *_, h in built) + aside["gap"] * (len(built) - 1)
        area = area_bottom - top
        if total > bottom - top:
            out.compose_issues.append(f"cards_overflow:{total - (bottom - top):.0f}pt")
        extra = max(0.0, (area - total) / len(built))
        ay = top
        for k, (group, paras, w, h) in enumerate(built):
            h += extra
            grp = f"aside{k + 1}"
            out.elements.append(RRect(role="aside", box=Box(x=ax, y=round(ay, 2), w=aw, h=round(h, 2)),
                                      fill=self.kn.color(aside["fill"]), radius=aside["radius"], group=grp))
            out.elements.append(self._tx("aside_text", paras, ax + aside["padding"], ay + aside["padding"], w, grp,
                                         group.text_ids))
            ay += h + aside["gap"]
        return ay - aside["gap"]

    # -- composición libre (plans/composicion-libre.md, gramática v1)
    def _free(self, spec: SlideSpec, cls: SlideClassification) -> RenderedSlide:
        """Encabezado y pie de marca; el cuerpo lo reparte la gramática en regiones.

        Cada bloque se dibuja con la función de su layout de origen (`_card_rows`, `_item_rows`,
        `_steps`, `_asides`) y su geometría: misma salida que el layout fijo en la misma región.
        """
        layout = cls.free_layout
        out = self._base(spec, cls, "light")
        g = self.kn.geometry("free")
        if cls.named.get("tags"):
            self._tags(spec, cls, out)
        statement = layout.header.title_style == "statement"
        note = self._title_note(spec, cls)
        bar = self.kn.component("accent_bar") if "accent_bar" in layout.accents and cls.title else None
        indent = bar["width"] + bar["gap"] if bar else 0.0
        header_bottom = self._header(spec, cls, out, "statement" if statement else "title", 3 if statement else 2,
                                     title_indent=indent,
                                     title_width=g["width"] - note[2] - g["title_note_gap"] if note else None)
        if bar:
            title = next(el for el in out.elements if el.role == "title")
            out.elements.append(RRect(role="accent_bar", box=Box(x=g["x"], y=title.box.y, w=bar["width"],
                                                                 h=bar["height"]),
                                      fill=self.kn.color(bar["fill"]), radius=bar["radius"],
                                      shadow=self.kn.shadow(bar.get("shadow")), group="accent", brand=True))
        if note:
            header_bottom = max(header_bottom, self._draw_title_note(cls, out, note, g))
        top = header_bottom + g["body_gap"]
        if "divider" in layout.accents:
            # En medio del aire entre el encabezado y el cuerpo: no lo empuja.
            line = self.kn.component("divider")
            out.elements.append(RRect(role="divider", box=Box(x=g["x"], y=round(header_bottom + g["body_gap"] / 2, 2),
                                                              w=g["width"], h=0),
                                      fill=None, line=self.kn.color(line["line"]), line_width=line["line_width"],
                                      shape="line", group="accent", brand=True))
        bottom = self.kn.tokens["margins"]["bottom_limit"]
        if cls.notes:
            bottom = min(bottom, self._notes_top(spec, cls, out) - g["stack_gap"])
        before = len(out.elements)
        self._free_node(spec, cls, layout.body, out, g["x"], g["width"], top, bottom)
        self._center_free_body(out.elements[before:], header_bottom, bottom if cls.notes else None)
        # Una celda que no cabe se dibuja igual y solo el validador la veía (body_limit): sin declarar
        # el desborde, ni la compactación ni la excepción de letra (`font_floor`) recomponían.
        body_bottom = max((el.box.bottom for el in out.elements[before:]), default=top)
        if body_bottom > bottom + 2 and not _overflows(out):
            out.compose_issues.append(f"cards_overflow:{body_bottom - bottom:.0f}pt")
        self._notes(spec, cls, out)
        return out

    def _title_note(self, spec, cls):
        """Nota corta a la derecha del título (`title_note`): (ids, párrafos, ancho) o None."""
        ids = cls.named.get("title_note", [])
        if not ids:
            return None
        g = self.kn.geometry("free")
        paras = []
        for bid in ids:
            more = self._paras(spec.text_by_id(bid), self.kn.style("light", "title_note"), inline_bold=True)
            if paras and more:
                more[0].space_before = 3
            paras += more
        limit = g["width"] * g["title_note_max"]
        width = min(limit, hug_width(paras, self.safety))
        paras, width, _iss = fix_orphans(paras, width, width * 0.8, self.safety)
        return ids, paras, width

    def _draw_title_note(self, cls, out: RenderedSlide, note, g: dict) -> float:
        """La nota va arriba a la derecha, a la altura del título (bajo los tags, si hay)."""
        ids, paras, width = note
        title = next((el for el in out.elements if el.role in ("title", "statement")), None)
        y = title.box.y if title else g["title_top"]
        tags = [el for el in out.elements if el.role == "tag"]
        if tags:
            y = max(y, max(el.box.bottom for el in tags) + 6)
        el = self._tx("title_note", paras, g["x"] + g["width"] - width, y, width, "title_note", ids)
        out.elements.append(el)
        return el.box.bottom

    def _center_free_body(self, body: list, header_bottom: float, above_notes: float | None) -> None:
        """El cuerpo entero (filas, paneles y banda) se centra en el espacio libre bajo el
        encabezado, como las cards de los layouts fijos (`card_content_fit`). El encabezado no
        se mueve. Se mide lo dibujado, no la región reservada: una imagen que no llena su
        región deja aire arriba, y la auditoría (que ve las cajas) lo leía descentrado.
        `above_notes`: el borde de la región cuando hay notas al pie (ya descuenta su aire)."""
        fit = self.kn.tokens["brand_rules"]["card_content_fit"]
        drawn = [el for el in body if not getattr(el, "brand", False)
                 and (not isinstance(el, RText) or any(run.text.strip() for p in el.paras for run in p.runs))]
        if not fit.get("center_content_below_header") or not drawn:
            return
        top, bottom = min(el.box.y for el in drawn), max(el.box.bottom for el in drawn)
        band_bottom = fit["composition_band"][1] if above_notes is None else min(fit["composition_band"][1], above_notes)
        shift = centered_body_top(header_bottom, top, bottom, band_bottom, fit) - top
        for el in body:
            el.box.y = round(el.box.y + shift, 2)

    def _free_present(self, cls: SlideClassification, node) -> bool:
        """¿El nodo tiene contenido? Un nodo `optional` sin contenido no ocupa lugar."""
        if node.row is not None:
            return any(self._free_present(cls, cell) for cell in node.row)
        if node.stack is not None:
            return any(self._free_present(cls, child) for child in node.stack)
        return bool(self._free_units(cls, node))

    @staticmethod
    def _free_units(cls: SlideClassification, node) -> list:
        """Lo que dibuja un bloque: unidades (cards o grupos) o ids de texto.

        Una repetición, o un bloque sin `units` por índice, toma toda su familia; `card:2` (o
        `item:2`, que en el libre es la misma unidad) toma solo esa.
        """
        block = node.block
        name = block.component

        def pick(pool: list, prefixes: tuple[str, ...]) -> list:
            wanted = [int(unit.split(":")[1]) for unit in block.units
                      if unit.startswith(prefixes) and unit.split(":")[1].isdigit()]
            if node.repeat is not None or not wanted:
                return list(pool)
            return [pool[index - 1] for index in wanted if index <= len(pool)]

        if name in ("card", "item_row", "step"):
            return pick(cls.cards, ("card:", "item:"))
        if name == "aside":
            return pick(cls.groups, ("aside:",))
        if name == "banner":
            return [cls.banner] if cls.banner else []
        if name == "list_title":
            return list(cls.named.get("list_title", []))
        if name == "metric_card":
            return pick(cls.metrics, ("metric:",))
        if name == "quadrant":
            return list(cls.free_units.get("quadrant", []))
        if name == "matrix":
            return list(cls.free_units.get("row", []))
        if name == "circles":
            return list(cls.free_units.get("circle", []))
        if name == "worksheet":
            return [*cls.named.get("panel_title", []), *cls.named.get("panel", [])]
        if name == "image_message":
            return [*cls.free_units.get("block", []), *cls.images, *cls.body]
        return []

    def _free_measure(self, spec, cls, node, x: float, width: float, top: float, bottom: float) -> float:
        """Alto natural del nodo: se dibuja en borrador y se mide lo usado."""
        scratch = self._base(spec, cls, "light")
        scratch.elements, scratch.compose_issues = [], []
        return self._free_node(spec, cls, node, scratch, x, width, top, bottom, natural=True) - top

    def _free_node(self, spec, cls, node, out: RenderedSlide, x: float, width: float, top: float, bottom: float,
                   natural: bool = False) -> float:
        """Dibuja el nodo en la región; devuelve el borde inferior usado."""
        g = self.kn.geometry("free")
        if node.stack is not None:
            children = [child for child in node.stack if self._free_present(cls, child)]
            heights = [self._free_measure(spec, cls, child, x, width, top, bottom) for child in children]
            # Lo que no es `fill` toma su alto natural; el resto del alto es de los `fill`.
            fixed = sum(h for child, h in zip(children, heights) if child.height != "fill")
            fixed += g["stack_gap"] * (len(children) - 1)
            fills = sum(1 for child in children if child.height == "fill")
            share = (bottom - top - fixed) / fills if fills else 0.0
            excess = fixed - (bottom - top)
            elastic = [k for k, child in enumerate(children) if child.height != "fill"
                       and child.block is not None and child.block.component == "image_message"]
            if not fills and excess > 0 and elastic:
                # Las fotos se achican sin deformarse; las cards no. Con su alto natural, las
                # fotos dejaban sin lugar a las cards de abajo, que terminaban sobre el pie
                # (deck de inducción, 2026-10-26).
                pool = sum(heights[k] for k in elastic)
                heights = [max(h - excess * h / pool, h * 0.25) if k in elastic else h
                           for k, h in enumerate(heights)]
            y = top
            for child, height in zip(children, heights):
                # Un `fill` recibe lo que sobra, aunque su contenido pida más: así el desborde se
                # detecta y se reporta en vez de empujar lo de abajo fuera de la slide.
                region = share if child.height == "fill" else height
                y = self._free_node(spec, cls, child, out, x, width, y, y + region, natural) + g["stack_gap"]
            return y - g["stack_gap"] if children else top
        if node.row is not None:
            cells = [cell for cell in node.row if self._free_present(cls, cell)]
            gap = g["cell_gap"]
            unit = (width - gap * (len(cells) - 1)) / max(1, sum(cell.span for cell in cells))
            spans = [cell.span * unit for cell in cells]
            if natural:
                row_bottom = top + max((self._free_measure(spec, cls, cell, 0, w, top, bottom)
                                        for cell, w in zip(cells, spans)), default=0.0)
            else:
                row_bottom = bottom if node.height == "fill" else top + max(
                    (self._free_measure(spec, cls, cell, 0, w, top, bottom) for cell, w in zip(cells, spans)),
                    default=0.0)
            cx, used = x, top
            for cell, w in zip(cells, spans):
                cell_top = top
                if cell.align == "center":
                    cell_top = top + (row_bottom - top - self._free_measure(spec, cls, cell, cx, w, top, bottom)) / 2
                stretch = cell.align == "stretch" and not natural
                used = max(used, self._free_node(spec, cls, cell, out, cx, w, cell_top, row_bottom, natural=not stretch))
                cx += w + gap
            return max(used, row_bottom if not natural else used)
        return self._free_block(spec, cls, node, out, x, width, top, bottom, natural)

    def _free_block(self, spec, cls, node, out, x: float, width: float, top: float, bottom: float,
                    natural: bool) -> float:
        block = node.block
        units = self._free_units(cls, node)
        if not units:
            return top
        name = block.component
        if name == "card":
            g = self.kn.geometry("card_grid")
            style = cls.model_copy(update={"card_style": block.style or "outline"})
            n = len(units)
            if node.repeat is not None and node.repeat.columns != "auto":
                candidates = [min(node.repeat.columns, n)]
            else:
                preferred = g["columns_by_count"].get(n, min(n, 4))
                candidates = sorted(range(1, min(n, 5) + 1), key=lambda c: (abs(c - preferred), -c))
                candidates = [c for c in candidates if not (c == 1 and n > 2)] or [preferred]
            # Como card_grid: se prueban columnas desde la preferida; si ninguna cabe, queda la
            # preferida con su desborde (el que se reporta y propone partir).
            first = None
            for columns in candidates:
                trial = out.model_copy(update={"elements": [], "compose_issues": []})
                used = self._card_rows(spec, style, units, trial, x, width, top, bottom, columns, g,
                                       icon_mode=block.icon or "auto", decorate=block.numbered is True)
                first = first or (trial, used)
                if not any(issue.startswith("cards_overflow") for issue in trial.compose_issues):
                    break
            else:
                trial, used = first
            out.elements += trial.elements
            out.compose_issues += trial.compose_issues
            return used
        if name == "item_row":
            g = self.kn.geometry("item_list")
            style = cls.model_copy(update={"card_style": "rule" if block.style == "rule" else "outline"})
            return self._item_rows(spec, style, units, out, x, width, top, bottom, g, decorate=block.numbered is True)
        if name == "step":
            g = self.kn.geometry("list_aside")
            # El título de lista lo dibuja su propio bloque.
            plain = cls.model_copy(update={"named": {k: v for k, v in cls.named.items() if k != "list_title"}})
            return self._steps(spec, plain, units, out, x, width, top, bottom - g["footer_air"], g,
                               decorate=block.numbered is True)
        if name == "aside":
            return self._asides(spec, units, out, x, width, top, bottom, top if natural else bottom)
        if name == "banner":
            paras, height = self._banner_block(spec, cls, width)
            self._draw_banner(cls, out, paras, height, top, {"x": x, "width": width})
            return top + height
        if name == "metric_card":
            g = self.kn.geometry("metrics_row")
            if node.repeat is not None and node.repeat.columns != "auto":
                columns = min(node.repeat.columns, len(units))
            else:
                # Una fila, como metrics_row, mientras cada card conserve un ancho legible.
                fit = int((width + g["metric_gutter"]) // (g["metric_min_width"] + g["metric_gutter"]))
                columns = max(1, min(len(units), fit))
                if columns < len(units) and len(units) == 4 and columns >= 2:
                    columns = 2
            return self._metric_cards(spec, units, out, x, width, top, columns)
        if name in ("quadrant", "matrix", "circles", "image_message"):
            family = {"quadrant": "quadrant", "matrix": "row", "circles": "circle", "image_message": "block"}[name]
            update = {"cards": cls.free_units.get(family, [])}
            focus = block.params.get("focus")
            if name == "quadrant":
                update["focus"] = focus if isinstance(focus, int) and not isinstance(focus, bool) else cls.focus
            if name == "circles":
                update["variant"] = {"center": "center_focus", "right": "right_focus"}.get(str(focus))
            sub = cls.model_copy(update=update)
            if name == "quadrant":
                return self._quadrant_plot(spec, sub, out, x, width, top, bottom)
            if name == "matrix":
                return self._matrix_table(spec, sub, out, x, width, top, bottom)
            if name == "circles":
                return self._circle_row(spec, sub, out, x, width, top, bottom, natural)
            ratio = block.params.get("image_ratio")
            return self._image_message(spec, sub, out, x, width, top, bottom,
                                       float(ratio) if isinstance(ratio, (int, float)) else None)
        if name == "worksheet":
            return self._worksheet(spec, cls, out, x, width, top, bottom)
        if name == "list_title":
            bid = units[0]
            paras = self._paras(spec.text_by_id(bid), self.kn.style("light", "list_title"))
            el = self._tx("list_title", paras, x, top, width, "list_title", [bid])
            out.elements.append(el)
            return el.box.bottom
        out.compose_issues.append(f"free_block_not_drawn:{name}")
        return top

    def _quadrant(self, spec: SlideSpec, cls: SlideClassification) -> RenderedSlide:
        """Matriz 2×2 con ejes rotulados; el cuadrante foco va en azul. Panel opcional."""
        out = self._base(spec, cls, "light")
        g = self.kn.geometry("quadrant")
        top = self._header(spec, cls, out, "title", 2) + g["body_gap"]
        bottom = self.kn.tokens["margins"]["bottom_limit"]
        has_panel = bool(cls.named.get("panel") or cls.named.get("panel_title"))
        plot_w = g["width"] * g["plot_ratio"] if has_panel else g["width"]
        self._quadrant_plot(spec, cls, out, g["x"], plot_w, top, bottom)
        if has_panel:
            px = g["x"] + plot_w + g["column_gap"]
            self._worksheet(spec, cls, out, px, g["x"] + g["width"] - px, top, bottom)
        self._notes(spec, cls, out)
        return out

    def _quadrant_plot(self, spec: SlideSpec, cls: SlideClassification, out: RenderedSlide, x: float,
                       plot_w: float, top: float, bottom: float) -> float:
        """Matriz 2×2 con sus ejes dentro de una región; ocupa todo su alto."""
        g, comp = self.kn.geometry("quadrant"), self.kn.component("quadrant")
        box_of = lambda bid: spec.text_by_id(bid).box
        text_of = lambda bid: spec.text_by_id(bid).text

        def split_axis(ids, key):
            """El rótulo más largo es el título del eje; los otros, sus extremos."""
            if not ids:
                return None, []
            title = max(ids, key=lambda bid: len(text_of(bid)))
            ends = sorted((bid for bid in ids if bid != title), key=key)
            return title, ends

        y_title, y_ends = split_axis(cls.named.get("axis_y", []), lambda bid: box_of(bid).y)
        x_title, x_ends = split_axis(cls.named.get("axis_x", []), lambda bid: box_of(bid).x)
        label = lambda bid, style, align="l": self._paras(spec.text_by_id(bid), self.kn.style("light", style), align=align)

        plot_top = top
        if y_title:
            el = self._tx("axis_title", label(y_title, "axis_title"), x, top, plot_w, "axis_y_title", [y_title])
            out.elements.append(el)
            plot_top = el.box.bottom + g["axis_gap"]
        end_w = max((hug_width(label(bid, "axis_label"), self.safety) for bid in y_ends), default=0.0)
        plot_x = x + end_w + (g["axis_gap"] if end_w else 0)
        row_h = max((tm.block_height(label(bid, "axis_label"), 1000) + 2 for bid in [x_title, *x_ends] if bid),
                    default=0.0)
        plot_bottom = bottom - g["footer_air"] - (row_h + g["axis_gap"] if row_h else 0)
        plot_right = x + plot_w

        axis = self.kn.color(comp["axis"])
        aw = comp["axis_width"]
        out.elements.append(RRect(role="axis_line", box=Box(x=plot_x, y=plot_top, w=aw, h=plot_bottom - plot_top),
                                  fill=axis, group="axis"))
        out.elements.append(RRect(role="axis_line", box=Box(x=plot_x, y=plot_bottom - aw, w=plot_right - plot_x, h=aw),
                                  fill=axis, group="axis"))
        for index, bid in enumerate(y_ends):
            paras = label(bid, "axis_label", "r")
            el = self._tx("axis_label", paras, x, plot_top, end_w, f"axis_y{index}", [bid])
            if index == len(y_ends) - 1 and len(y_ends) > 1:
                el.box.y = round(plot_bottom - aw - el.box.h, 2)
            out.elements.append(el)
        if row_h:
            y_row = plot_bottom + g["axis_gap"]
            if x_ends:
                out.elements.append(self._tx("axis_label", label(x_ends[0], "axis_label"), plot_x, y_row,
                                             hug_width(label(x_ends[0], "axis_label"), self.safety), "axis_x0", [x_ends[0]]))
            if len(x_ends) > 1:
                paras = label(x_ends[-1], "axis_label", "r")
                w = hug_width(paras, self.safety)
                out.elements.append(self._tx("axis_label", paras, plot_right - w, y_row, w, "axis_x1", [x_ends[-1]]))
            if x_title:
                paras = label(x_title, "axis_title", "ctr")
                w = hug_width(paras, self.safety)
                out.elements.append(self._tx("axis_title", paras, plot_x + (plot_right - plot_x - w) / 2, y_row, w,
                                             "axis_x_title", [x_title]))

        gap, inset, pad = comp["gap"], comp["gap"] + aw, comp["padding"]
        qx0, qy0 = plot_x + inset, plot_top
        qw = (plot_right - qx0 - gap) / 2
        qh = (plot_bottom - inset - qy0 - gap) / 2
        focus = (cls.focus or 0) - 1
        for k, card in enumerate(cls.cards[:4]):
            row, col = divmod(k, 2)
            cx, cy = qx0 + col * (qw + gap), qy0 + row * (qh + gap)
            grp = f"quadrant{k + 1}"
            is_focus = k == focus
            out.elements.append(RRect(role="quadrant", box=Box(x=round(cx, 2), y=round(cy, 2), w=round(qw, 2), h=round(qh, 2)),
                                      fill=self.kn.color(comp["focus_fill"] if is_focus else comp["fill"]),
                                      line=None if is_focus else self.kn.color(comp["line"]),
                                      line_width=comp["line_width"], radius=comp["radius"], group=grp))
            prefix = "quadrant_focus" if is_focus else "quadrant"
            ids = sorted(card.text_ids, key=lambda bid: box_of(bid).y)
            merged = TextBlock(id=ids[0], name="quadrant", box=box_of(ids[0]),
                               paragraphs=[p for bid in ids for p in spec.text_by_id(bid).paragraphs])
            paras = self._styled(merged, f"{prefix}_title", f"{prefix}_body", align="ctr")
            paras, w, iss = fix_orphans(paras, qw - 2 * pad, (qw - 2 * pad) * 0.8, self.safety)
            out.compose_issues += iss
            el = self._tx("quadrant_text", paras, cx + (qw - w) / 2, cy, w, grp, ids)
            el.box.y = round(cy + (qh - el.box.h) / 2, 2)
            if el.box.h > qh - 2 * pad:
                out.compose_issues.append(f"cards_overflow:quadrant{k + 1}")
            out.elements.append(el)
        return bottom

    def _worksheet(self, spec: SlideSpec, cls: SlideClassification, out: RenderedSlide, px: float, pw: float,
                   top: float, bottom: float) -> float:
        """Panel de trabajo: cabecera navy y consignas con su renglón; ocupa todo el alto."""
        comp = self.kn.component("quadrant")
        pad = comp["padding"]
        label = lambda bid, style, align="l": self._paras(spec.text_by_id(bid), self.kn.style("light", style), align=align)
        hc = self.kn.component("card_header")
        card = self.kn.component("card")
        out.elements.append(RRect(role="panel", box=Box(x=px, y=top, w=pw, h=bottom - top),
                                  fill=self.kn.color(card["fill"]), line=self.kn.color(card["line"]),
                                  line_width=card["line_width"], radius=card["radius"], group="panel"))
        y = top
        if cls.named.get("panel_title"):
            bid = cls.named["panel_title"][0]
            paras = label(bid, "panel_title")
            text = self._tx("panel_title", paras, px + hc["padding"], y + hc["padding"], pw - 2 * hc["padding"],
                            "panel", [bid])
            head_h = text.box.h + 2 * hc["padding"]
            out.elements.append(RRect(role="panel_header", box=Box(x=px, y=y, w=pw, h=head_h),
                                      fill=self.kn.color(hc["fill"]), radius=hc["radius"], group="panel"))
            out.elements.append(RRect(role="panel_header_base", box=Box(x=px, y=y + head_h / 2, w=pw, h=head_h / 2),
                                      fill=self.kn.color(hc["fill"]), group="panel"))
            out.elements.append(text)
            y += head_h
        prompts = cls.named.get("panel", [])
        inner = pw - 2 * pad - 4
        built = []
        for bid in prompts:
            paras, w, iss = fix_orphans(label(bid, "panel_prompt"), inner, inner * 0.85, self.safety)
            out.compose_issues += iss
            built.append((bid, paras, w, tm.block_height(paras, w * self.safety) + 2))
        # Cada consigna lleva su renglón debajo; el alto libre se reparte entre ellas.
        need = sum(h + 12 for *_, h in built)
        room = bottom - y - pad
        if need > room:
            out.compose_issues.append(f"cards_overflow:panel:{need - room:.0f}pt")
        extra = max(0.0, (room - need) / max(1, len(built)))
        sy = y + pad
        for bid, paras, w, h in built:
            text = self._tx("panel_prompt", paras, px + pad + 2, sy + 3, w, "panel", [bid])
            out.elements.append(text)
            line_y = sy + h + 9 + extra
            out.elements.append(RRect(role="writing_line", box=Box(x=px + pad + 2, y=round(line_y, 2), w=inner, h=0.75),
                                      fill=self.kn.color(self.kn.component("worksheet")["line"]), group="panel"))
            sy = line_y + 0.75
        return bottom
