"""Brand shell: para slides sin layout compatible o cuyo layout desborda.

Conserva la composición original y aplica solo la base de marca:
fondo de referencia, logo NEO 25 y "neoconsulting.ai", familia Montserrat,
mínimo 11 pt donde cabe sin chocar con otros elementos, y NBSP contra huérfanas.
Lo que no se puede resolver se reporta para revisión manual.
"""
from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass

from PIL import Image
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.enum.text import PP_ALIGN
from pptx.oxml.ns import qn
from pptx.text.text import _Run
from pptx.util import Pt

from . import cobrand, textmetrics as tm
from .icon_tint import tint_bytes
from .knowledge import Knowledge
from .parser import EMU_PER_PT, _Transform
from .renderer import BRAND_PREFIX, add_background, add_element, set_scale
from .schemas import Box, Issue, RPara, RRun

DEFAULT_SIZE = 14.0  # tamaño asumido cuando el run hereda (solo para medir)


# Lado máximo de un ícono, como fracción del ancho de la slide: más grande es una imagen.
ICON_MAX_WIDTH = 0.12
# Piezas del bloque NEO | cliente que acompañan al logo NEO (`cobrand.py`).
COBRAND_ROLES = ("cobrand_rule", "client_logo")


def _span(boxes) -> Box:
    boxes = list(boxes)
    x0, y0 = min(b.x for b in boxes), min(b.y for b in boxes)
    return Box(x=x0, y=y0, w=max(b.right for b in boxes) - x0, h=max(b.bottom for b in boxes) - y0)


@dataclass
class _Item:
    shape: object
    box: Box
    kind: str  # text | picture | shape
    sha: str | None = None
    preexisting: frozenset = frozenset()  # párrafos que ya desbordaban antes del shell


def _collect(shapes, tr: _Transform, out: list[_Item]):
    for sh in shapes:
        box = tr.apply(sh.left or 0, sh.top or 0, sh.width or 0, sh.height or 0)
        if sh.shape_type == MSO_SHAPE_TYPE.GROUP:
            _collect(sh.shapes, tr.child(sh), out)
        elif sh.shape_type == MSO_SHAPE_TYPE.PICTURE:
            out.append(_Item(sh, box, "picture", hashlib.md5(sh.image.blob).hexdigest()))
        elif getattr(sh, "has_text_frame", False) and sh.text_frame.text.strip():
            out.append(_Item(sh, box, "text"))
        else:
            out.append(_Item(sh, box, "shape"))


def _tint_icons(items: list[_Item], kn: Knowledge, W: float, keep: frozenset[str], stats: dict) -> None:
    """Íconos de un color (glifo sobre transparencia) en el azul de marca, como en las slides
    recompuestas (`icon_tint.py`). En «Las reglas del juego» con el layout conservado quedaban
    negros (deck de inducción, 2026-11-03). No se tocan el logo NEO, lo que el plan marcó como logo u
    otra clase que conserva colores (`keep`, md5[:10]), lo que no tiene tamaño de ícono ni el
    glifo que va sobre un relleno oscuro (blanco a propósito)."""
    color = kn.color(kn.component("icon_badge")["glyph"])
    logos = [*kn.tokens["brand"]["known_logos"]["current"], *kn.tokens["brand"]["known_logos"]["old"]]
    fills = [(it.box, _fill_hex(it.shape)) for it in items if it.kind != "picture"]
    for it in items:
        if (it.kind != "picture" or it.shape.name.startswith(BRAND_PREFIX) or it.sha[:10] in keep
                or any(it.sha.startswith(p) for p in logos) or max(it.box.w, it.box.h) > ICON_MAX_WIDTH * W):
            continue
        if any(fill and _luma(fill) < 0.5 and box.contains(it.box) for box, fill in fills):
            continue
        painted = tint_bytes(it.shape.image.blob, color)
        if painted is None:
            continue
        _part, rid = it.shape.part.get_or_add_image_part(io.BytesIO(painted))
        it.shape._element.blipFill.find(qn("a:blip")).set(qn("r:embed"), rid)
        stats["icons_tinted"] = stats.get("icons_tinted", 0) + 1


def _luma(hex_: str) -> float:
    r, g, b = (int(hex_[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _fill_hex(shape) -> str | None:
    try:
        if shape.fill.type == 1:
            return str(shape.fill.fore_color.rgb)
    except Exception:
        pass
    return None


def _is_dark(slide, items: list[_Item], canvas: float) -> bool:
    bg = slide._element.cSld.find(qn("p:bg"))
    if bg is not None:
        clr = bg.find(".//" + qn("a:srgbClr"))
        if clr is not None:
            return _luma(clr.get("val")) < 0.35
    for it in items:
        if it.box.w * it.box.h >= 0.9 * canvas:
            if it.kind == "shape" and _fill_hex(it.shape):
                return _luma(_fill_hex(it.shape)) < 0.35
            if it.kind == "picture":
                with Image.open(io.BytesIO(it.shape.image.blob)) as im:
                    px = im.convert("L").resize((8, 8)).getdata()
                return sum(px) / len(px) / 255 < 0.35
    return False


def _run_elements(p):
    return [c for c in p._p if c.tag in (qn("a:r"), qn("a:br"))]


ICON_FAMILIES = ("material icons", "material symbols")


def _runs(tf) -> list[tuple[tuple[int, int], object, object]]:
    """(clave estable (párrafo, run), elemento a:r, párrafo). No usar id(): lxml recrea los proxies."""
    out = []
    for pi, p in enumerate(tf.paragraphs):
        ri = 0
        for el in _run_elements(p):
            if el.tag == qn("a:r"):
                out.append(((pi, ri), el, p))
                ri += 1
    return out


def _measure_paras(tf, sizes: dict[tuple[int, int], float]) -> list[RPara]:
    """Párrafos para medir, con la fuente ya en Montserrat y los tamaños propuestos (id(run) -> pt).
    Las palabras en fuentes de íconos (ligaduras) se miden como un solo glifo."""
    paras = []
    for pi, p in enumerate(tf.paragraphs):
        runs = []
        ri = 0
        for el in _run_elements(p):
            if el.tag == qn("a:br"):
                runs.append(RRun(text="\n", font="Montserrat", size=DEFAULT_SIZE, color="0"))
                continue
            r = _Run(el, p)
            size = sizes.get((pi, ri), r.font.size.pt if r.font.size else DEFAULT_SIZE)
            ri += 1
            text = r.text
            if (r.font.name or "").lower().startswith(ICON_FAMILIES):
                text = "M" * len(text.split())
            runs.append(RRun(text=text, font=r.font.name or "Montserrat", size=size,
                             bold=bool(r.font.bold), italic=bool(r.font.italic), color="0"))
        line = p.line_spacing if isinstance(p.line_spacing, float) else 1.0
        paras.append(RPara(runs=runs or [RRun(text="", font="Montserrat", size=DEFAULT_SIZE, color="0")], line=line))
    return paras


def _inner(tf, box: Box) -> tuple[float, float, bool]:
    bp = tf._txBody.find(qn("a:bodyPr"))
    ins = {k: int(bp.get(k)) / EMU_PER_PT if bp.get(k) else d
           for k, d in (("lIns", 7.2), ("rIns", 7.2), ("tIns", 3.6), ("bIns", 3.6))}
    nowrap = bp.get("wrap") == "none"
    return box.w - ins["lIns"] - ins["rIns"], box.h - ins["tIns"] - ins["bIns"], nowrap


def _extent(tf, box: Box, height: float) -> Box:
    """La franja que ocupa un texto de `height` pt dentro de su caja, según su anclaje."""
    bp = tf._txBody.find(qn("a:bodyPr"))
    top = int(bp.get("tIns")) / EMU_PER_PT if bp.get("tIns") else 3.6
    bottom = int(bp.get("bIns")) / EMU_PER_PT if bp.get("bIns") else 3.6
    room = box.h - top - bottom
    offset = {"ctr": (room - height) / 2, "b": room - height}.get(bp.get("anchor"), 0.0)
    return Box(x=box.x, y=box.y + top + offset, w=box.w, h=max(height, 0.0))


def _invades(text: Box, other: Box) -> float:
    """Cuánto alto de `other` cubre la franja de texto (0 si no se tocan)."""
    if text.right <= other.x or other.right <= text.x:
        return 0.0
    return max(0.0, min(text.bottom, other.bottom) - max(text.y, other.y))


def _bind_last_words_xml(p) -> bool:
    """NBSP entre las dos últimas palabras; nunca dentro de un hipervínculo (los visores lo cortan mal)."""
    runs = [el for el in p._p if el.tag == qn("a:r")]
    ts = [el.find(qn("a:t")) for el in runs]
    ts = [t for t in ts if t is not None and t.text]
    if runs and runs[-1].find(qn("a:rPr")) is not None and runs[-1].find(qn("a:rPr")).find(qn("a:hlinkClick")) is not None:
        return False
    seen_word = False
    for t in reversed(ts):
        text = t.text
        for i in range(len(text) - 1, -1, -1):
            if text[i] == " " and seen_word:
                t.text = text[:i] + tm.NBSP + text[i + 1:]
                return True
            if not text[i].isspace():
                seen_word = True
    return False



def _preview(it: _Item) -> str:
    return it.shape.text_frame.text.strip().replace("\n", " ")[:40]


def _free(box: Box, it: _Item, blockers: list[_Item], W: float, H: float,
          containers: list[_Item] = ()) -> bool:
    """La caja agrandada no sale del canvas, no choca con otros textos/imágenes y,
    si el texto estaba dentro de una tarjeta/forma, sigue dentro de ella."""
    if box.x < 0 or box.right > W or box.bottom > H - 10:
        return False
    for c in containers:
        if c is not it and c.box.w * c.box.h < 0.9 * W * H and c.box.contains(it.box) and not c.box.contains(box):
            return False
    return not any(b is not it and box.overlaps(b.box) and not b.box.contains(it.box)
                   and not it.box.contains(b.box) for b in blockers)


def _indents(tf) -> list[float]:
    """Sangría izquierda (marL, pt) de cada párrafo: las viñetas reducen el ancho útil."""
    out = []
    for p in tf.paragraphs:
        ppr = p._p.find(qn("a:pPr"))
        out.append(int(ppr.get("marL", 0)) / EMU_PER_PT if ppr is not None else 0.0)
    return out


def _problems(paras: list[RPara], width: float, safety: float,
              indents: list[float] | None = None) -> tuple[list[int], list[int]]:
    """(párrafos con palabras que no caben, párrafos con huérfana)."""
    widths = [width - (indents[k] if indents else 0.0) for k in range(len(paras))]
    too_wide = [k for k, p in enumerate(paras) if tm.overflows_width(p, widths[k] * safety)]
    orphans = [k for k, p in enumerate(paras) if not tm.orphan_free(p, widths[k], safety)]
    return too_wide, orphans


def _fit_lines(it: _Item, tf, kn: Knowledge, blockers, W, H, issues: list[Issue], stats: dict,
               containers: list[_Item] = (), min_pt: float | None = None):
    """Resuelve palabras cortadas a la mitad y huérfanas, en este orden:
    1) NBSP (solo si las dos palabras unidas caben), 2) ensanchar la caja si hay espacio libre,
    3) reducir la fuente hasta 85 % (nunca bajo 11 pt). Si nada funciona, se reporta."""
    iw, _, _ = _inner(tf, it.box)
    ind = _indents(tf)
    paras = _measure_paras(tf, {})
    for k in _problems(paras, iw, kn.safety, ind)[1]:
        bound = tm.bind_last_words(paras[k])
        if not tm.overflows_width(bound, (iw - ind[k]) * kn.safety) and _bind_last_words_xml(tf.paragraphs[k]):
            stats["nbsp"] += 1
    paras = _measure_paras(tf, {})
    too_wide, orphans = _problems(paras, iw, kn.safety, ind)
    if not too_wide and not orphans:
        return
    top_level = it.shape._element.getparent().tag == qn("p:spTree")
    if top_level:
        align = paras[0].align if paras else "l"
        algn = tf.paragraphs[0].alignment
        centered = algn is not None and int(algn) == 2
        for extra in range(4, int(it.box.w * 0.4) + 1, 4):
            dx = extra / 2 if centered else 0
            box = Box(x=it.box.x - dx, y=it.box.y, w=it.box.w + extra, h=it.box.h)
            if not _free(box, it, blockers, W, H, containers):
                break
            tw, orph = _problems(paras, iw + extra, kn.safety, ind)
            if not tw and not orph:
                it.shape.left, it.shape.width = Pt(box.x), Pt(box.w)
                it.box = box
                stats["boxes_widened"] = stats.get("boxes_widened", 0) + 1
                return
    runs = _runs(tf)
    base = {key: (_Run(el, p).font.size.pt if _Run(el, p).font.size else DEFAULT_SIZE) for key, el, p in runs}
    for factor in (0.95, 0.9, 0.85):
        sizes = {i: max(min_pt or kn.min_size, round(sz * factor, 1)) for i, sz in base.items()}
        tw, orph = _problems(_measure_paras(tf, sizes), iw, kn.safety, ind)
        if not tw and not orph:
            for key, el, p in runs:
                _Run(el, p).font.size = Pt(sizes[key])
            stats["fonts_reduced"] = stats.get("fonts_reduced", 0) + 1
            return
    new_wide = [k for k in too_wide if k not in it.preexisting]
    if new_wide:
        issues.append(Issue(code="word_too_wide", severity="error",
                            detail=f"una palabra no cabe en su caja con Montserrat: {_preview(it)!r}"))
    elif too_wide:
        issues.append(Issue(code="word_too_wide_preexisting", severity="warning",
                            detail=f"ya se desbordaba en el original: {_preview(it)!r}"))
    if orphans:
        issues.append(Issue(code="orphan_unresolved", severity="warning", detail=_preview(it)))


def _fit_height(it: _Item, tf, kn: Knowledge, blockers, W, H, issues: list[Issue], stats: dict,
                containers: list[_Item] = (), scale: float = 1.0):
    """Evita que Montserrat haga crecer un bloque hasta cortarlo por abajo.

    El shell conserva la composición del PPTX, pero cambiar de fuente puede añadir una
    línea dentro de una tarjeta. Primero se aprovecha el espacio libre del contenedor;
    después se reduce solo ese bloque hasta 8 pt (los textos que ya eran menores que el
    mínimo se consideran preexistentes). Si ninguna opción es segura, se reporta en vez
    de dejar un recorte silencioso.
    """
    iw, ih, nowrap = _inner(tf, it.box)
    if nowrap:
        return
    paras = _measure_paras(tf, {})
    width = max(iw, 10.0) * kn.safety
    need = tm.block_height(paras, width)
    if need <= ih + 1.0:
        return

    grown = Box(x=it.box.x, y=it.box.y, w=it.box.w, h=max(it.box.h, need + 7.2))
    # `_free` también permite crecer dentro de la caja de un shape, pero el texto necesita
    # dejar unos puntos de aire antes del borde para que LibreOffice/Google Slides no lo
    # pinte fuera de la tarjeta por el descent de la fuente.
    limits = [c.box.bottom - it.box.y - 3.0 for c in containers
              if c is not it and c.kind == "shape" and c.box.w * c.box.h < 0.9 * W * H
              # El PPTX original puede sobresalir unos puntos de la tarjeta; sigue
              # siendo su contenedor visual y no una invitación a crecer hasta el
              # borde de la slide.
              and c.box.x - 3.0 <= it.box.x and it.box.right <= c.box.right + 3.0
              and c.box.y - 3.0 <= it.box.y and it.box.bottom <= c.box.bottom + 6.0]
    max_h = min(limits, default=H - 10.0 - it.box.y)
    if grown.h <= max_h and _free(grown, it, blockers, W, H, containers):
        it.shape.height = Pt(grown.h)
        it.box = grown
        stats["boxes_grown"] = stats.get("boxes_grown", 0) + 1
        return

    runs = _runs(tf)
    base = {key: (_Run(el, p).font.size.pt if _Run(el, p).font.size else DEFAULT_SIZE)
            for key, el, p in runs}
    floor8 = 8.0 * scale
    floor = floor8 if min(base.values(), default=DEFAULT_SIZE) >= floor8 else min(base.values(), default=floor8)
    for factor in (0.95, 0.9, 0.85, 0.8, 0.75, 0.7):
        sizes = {key: max(floor, round(size * factor, 1)) for key, size in base.items()}
        cand = _measure_paras(tf, sizes)
        if not tm.overflows_width(cand[0], width) and tm.block_height(cand, width) <= ih + 1.0:
            for key, el, p in runs:
                _Run(el, p).font.size = Pt(sizes[key])
            stats["fonts_reduced"] = stats.get("fonts_reduced", 0) + 1
            return
    issues.append(Issue(code="body_overflow", severity="error",
                        detail=f"el texto queda cortado verticalmente: {_preview(it)!r}"))


def _small_sizes(tf, min_pt: float) -> tuple[float, ...]:
    return tuple(sorted({round(_Run(el, p).font.size.pt, 1) for _key, el, p in _runs(tf)
                         if _Run(el, p).font.size is not None and _Run(el, p).font.size.pt < min_pt - 0.01
                         and _Run(el, p).text.strip()}))


def _citations(items: list[_Item], kn: Knowledge, mode: str, s: float, stats: dict) -> None:
    """Las citas de fuente («Fuente: …») con su estilo de cita, iguales en todas las slides y antes
    de encajar el marco: subidas a 11 pt quedaban enormes y en dos líneas bajo las cards
    (deck de cliente, 2026-11-19). Su tamaño es el de `typography.citation`, no el mínimo de marca."""
    st = kn.style(mode, "citation")
    for it in items:
        if it.kind != "text" or not kn.is_citation(it.shape.text_frame.text):
            continue
        for _key, el, p in _runs(it.shape.text_frame):
            run = _Run(el, p)
            run.font.size = Pt(st.size * s)
            run.font.name = st.font
            run.font.bold = st.bold
            run.font.color.rgb = RGBColor.from_string(st.color)
        stats["citations"] = stats.get("citations", 0) + 1


def _sibling_veto(items: list[_Item], kn: Knowledge, min_pt: float) -> set[int]:
    """Textos que no suben a 11 pt porque un hermano no puede: las cajas con la misma letra
    chica (el cuerpo de cada card de una rejilla) suben juntas o no sube ninguna. Antes subía la que cabía y la rejilla quedaba con tamaños mezclados (Master
    Talent, 2026-11-19: dos de seis cards a 11 pt y el resto a 7.5)."""
    groups: dict[tuple, list[tuple[_Item, bool]]] = {}
    for it in items:
        if it.kind != "text":
            continue
        tf = it.shape.text_frame
        sizes = _small_sizes(tf, min_pt)
        if not sizes or kn.is_citation(tf.text):
            continue
        iw, ih, nowrap = _inner(tf, it.box)
        small = {key: min_pt for key, el, p in _runs(tf)
                 if _Run(el, p).font.size is not None and _Run(el, p).font.size.pt < min_pt - 0.01}
        after = tm.block_height(_measure_paras(tf, small), (10_000 if nowrap else max(iw, 10)) * kn.safety)
        # Por la letra, no por el ancho: el shell angosta a su tinta una caja que se sale del
        # marco y la card del borde quedaba fuera de su grupo.
        groups.setdefault(sizes, []).append((it, after <= ih - 3.0))
    return {id(it) for members in groups.values() if len(members) > 1 and not all(ok for _it, ok in members)
            for it, _ok in members}


def _restack(items: list[_Item], kn: Knowledge, W: float, H: float, stats: dict, min_pt: float | None = None,
             veto: set[int] | None = None) -> None:
    """Textos apilados dentro de una card que a 11 pt ya no caben con sus márgenes internos:
    se reapilan juntos (sin margen vertical) desde el borde superior del primero, si así
    caben dentro de la card. Un rótulo y su valor («◆ TIEMPO X» sobre «XXXX») no se pisan.

    No se toca una card que lleva formas dentro (barras de avance, píldoras, pistas): sus
    textos están ubicados respecto de esas formas y reapilarlos los ponía encima de las barras
    (deck de cliente, 2026-11-19). Tampoco una card con un texto vetado (`_sibling_veto`)."""
    min_pt = min_pt or kn.min_size
    veto = veto or set()
    texts = [it for it in items if it.kind == "text"]
    shapes = [it for it in items if it.kind == "shape"]
    for card in [it for it in shapes if it.box.w * it.box.h < 0.5 * W * H]:
        inside = sorted([t for t in texts if card.box.contains(t.box)], key=lambda t: t.box.y)
        if len(inside) < 2 or any(a.box.right <= b.box.x or b.box.right <= a.box.x
                                  for a, b in zip(inside, inside[1:])):
            continue
        if any(id(t) in veto for t in inside):
            continue
        if any(other is not card and card.box.contains(other.box) and other.box.w * other.box.h > 4
               and not any(t.box.contains(other.box) for t in inside) for other in shapes):
            continue
        layout, y, small_any = [], inside[0].box.y, False
        for t in inside:
            tf = t.shape.text_frame
            small = {key: min_pt for key, el, p in _runs(tf)
                     if _Run(el, p).font.size is not None and _Run(el, p).font.size.pt < min_pt
                     and _Run(el, p).text.strip()} if not kn.is_citation(tf.text) else {}
            small_any |= bool(small)
            iw, _ih, nowrap = _inner(tf, t.box)
            h = tm.block_height(_measure_paras(tf, small), (10_000 if nowrap else iw) * kn.safety) + 1
            layout.append((t, small, y, h))
            y += h
        if not small_any or y > card.box.bottom - 1:
            continue
        for t, small, top, h in layout:
            tf = t.shape.text_frame
            bp = tf._txBody.find(qn("a:bodyPr"))
            bp.set("tIns", "0")
            bp.set("bIns", "0")
            for key, el, p in _runs(tf):
                if key in small:
                    _Run(el, p).font.size = Pt(min_pt)
            t.shape.top, t.shape.height = Pt(top), Pt(h)
            t.box = Box(x=t.box.x, y=top, w=t.box.w, h=h)
        stats["cards_restacked"] = stats.get("cards_restacked", 0) + 1


def _scaled(box: Box, s: float) -> Box:
    return Box(x=box.x * s, y=box.y * s, w=box.w * s, h=box.h * s)


def _shrink_text(element, k: float) -> None:
    """Letra, interlineado fijo, márgenes internos y celdas de tabla de un shape, a escala `k`."""
    for node in element.iter(qn("a:rPr"), qn("a:endParaRPr"), qn("a:defRPr")):
        if node.get("sz"):
            node.set("sz", str(max(100, round(int(node.get("sz")) * k))))
    for node in element.iter(qn("a:spcPts")):
        node.set("val", str(round(int(node.get("val")) * k)))
    for body in element.iter(qn("a:bodyPr")):
        for key in ("lIns", "rIns", "tIns", "bIns"):
            if body.get(key):
                body.set(key, str(round(int(body.get(key)) * k)))
    for column in element.iter(qn("a:gridCol")):
        column.set("w", str(round(int(column.get("w")) * k)))
    for row in element.iter(qn("a:tr")):
        row.set("h", str(round(int(row.get("h")) * k)))


def _plain_text(sh) -> bool:
    """Caja con texto y sin relleno ni borde visibles: lo único que se ve es su texto."""
    if sh.shape_type == MSO_SHAPE_TYPE.GROUP or not getattr(sh, "has_text_frame", False) \
            or not sh.text_frame.text.strip():
        return False
    sp_pr = sh._element.find(qn("p:spPr"))
    if sp_pr is None:
        return False
    style = sh._element.find(qn("p:style"))

    def themed(ref: str) -> bool:
        node = style.find(qn(f"a:{ref}")) if style is not None else None
        return node is not None and node.get("idx", "0") != "0"

    if any(sp_pr.find(qn(f"a:{tag}")) is not None for tag in ("solidFill", "gradFill", "pattFill", "blipFill")):
        return False
    if sp_pr.find(qn("a:noFill")) is None and themed("fillRef"):
        return False
    ln = sp_pr.find(qn("a:ln"))
    return ln.find(qn("a:noFill")) is not None if ln is not None else not themed("lnRef")


def _montserrat(tf) -> list[RPara]:
    """Párrafos medidos como quedarán: el paso de marca los pasa a Montserrat."""
    return [para.model_copy(update={"runs": [run.model_copy(update={"font": "Montserrat"})
                                             for run in para.runs]})
            for para in _measure_paras(tf, {})]


def _ink(sh, box: Box, safety: float = 1.0) -> Box:
    """La parte de una caja sin relleno que ocupa su texto a lo ancho, con el corte de líneas
    actual: al estrecharla a esto ninguna línea se vuelve a partir. Con el margen de ancho del
    motor (`wrap_safety`): justa a la tinta, la fuente de una card se partía en el render."""
    tf = sh.text_frame
    iw, _ih, nowrap = _inner(tf, box)
    used = tm.max_line_width(_montserrat(tf), 10_000 if nowrap else max(iw, 10.0)) / safety + 2.0
    insets = box.w - iw
    w = min(box.w, used + insets)
    align = tf.paragraphs[0].alignment
    if align is not None and int(align) == 2:      # centrado
        x = box.x + (box.w - w) / 2
    elif align is not None and int(align) == 3:    # derecha
        x = box.right - w
    else:
        x = box.x
    return Box(x=x, y=box.y, w=w, h=box.h)


def _left_text(sh) -> bool:
    """Texto suelto (sin relleno ni borde) con todos sus párrafos alineados a la izquierda."""
    return _plain_text(sh) and all(p.alignment in (None, PP_ALIGN.LEFT) for p in sh.text_frame.paragraphs)


def _fit_frame(slide, kn: Knowledge, W: float, H: float, s: float, stats: dict):
    """«Mantener el layout» a pedido de la persona: la composición original entra entera en el
    marco NEO (bajo el logo, sobre el pie y dentro de los márgenes de `keep_layout.zone`) con
    una escala uniforme y moviéndose lo mínimo. Orden, proporciones y alineación quedan como
    estaban; solo cambia dónde cae el conjunto. Devuelve la función que lleva una caja de la
    slide original a su lugar nuevo (None si ya cabía).

    Dos cosas no son composición y no achican el resto: el ancho vacío de una caja de texto
    sin relleno (un título centrado en una caja de lado a lado) y una nota suelta en la franja
    del pie, que va a la línea del pie a la derecha de la frase, como en las slides NEO."""
    from .charts import scale_text as scale_chart_text
    from .visual_contract import load_visual_contract

    left, top, right, bottom = (value * s for value in kn.tokens["keep_layout"]["zone"])
    current = kn.tokens["brand"]["known_logos"]["current"]
    phrase = kn.tokens["brand"]["phrase"]
    px, py, pw, ph = (value * s for value in phrase["box"])
    safe_bottom = load_visual_contract(kn.root).geometry_zone[3] * s
    movable: list[tuple[object, Box]] = []
    notes: list[tuple[object, Box]] = []
    # Cards (formas con relleno, sin texto): la fuente al pie de una card es de esa card, no
    # una nota suelta del pie de la slide.
    cards = [Box(x=sh.left / EMU_PER_PT, y=sh.top / EMU_PER_PT, w=sh.width / EMU_PER_PT, h=sh.height / EMU_PER_PT)
             for sh in slide.shapes
             if sh.shape_type != MSO_SHAPE_TYPE.PICTURE and sh.left is not None and sh.width is not None
             and not (getattr(sh, "has_text_frame", False) and sh.text_frame.text.strip())
             and not sh.name.startswith(BRAND_PREFIX) and _fill_hex(sh) is not None
             and sh.width * sh.height < 0.5 * W * H * EMU_PER_PT ** 2]
    for sh in slide.shapes:
        if sh.left is None or sh.top is None or sh.width is None or sh.height is None:
            continue
        box = Box(x=sh.left / EMU_PER_PT, y=sh.top / EMU_PER_PT, w=sh.width / EMU_PER_PT, h=sh.height / EMU_PER_PT)
        text = sh.text_frame.text.strip() if getattr(sh, "has_text_frame", False) else ""
        if (sh.name.startswith(BRAND_PREFIX) or text == phrase["text"]
                or (box.x <= 1 and box.y <= 1 and box.w >= 0.97 * W and box.h >= 0.97 * H)
                or (sh.shape_type == MSO_SHAPE_TYPE.PICTURE
                    and any(hashlib.md5(sh.image.blob).hexdigest().startswith(p) for p in current))
                or (sh.is_placeholder and not text and _fill_hex(sh) is None)):
            continue  # fondo, marca o un placeholder vacío: no forman parte de la composición
        plain = _plain_text(sh)
        if plain and (box.x < left or box.right > right):
            box = _ink(sh, box, kn.safety)
            sh.left, sh.width = Pt(box.x), Pt(box.w)
        # Una cita de fuente («Fuente: …») va siempre a la línea del pie, aunque sea larga o el
        # autor la haya puesto al fondo de una card: es la fuente de la slide.
        if plain and box.y >= bottom - 0.5 and (kn.is_citation(text) or (
                len(text) <= 120 and not any(card.contains(box) for card in cards))):
            notes.append((sh, box))
        else:
            movable.append((sh, box))

    # Notas del pie, de derecha a izquierda desde el margen, centradas en la línea de la frase.
    cursor = right
    for sh, box in sorted(notes, key=lambda item: -item[1].x):
        tf = sh.text_frame
        room = cursor - (px + pw + 14.0 * s)
        paras = _montserrat(tf)
        # Con el margen de seguridad de ancho del compositor y el que el auditor descuenta a una
        # caja conservada (14.4 pt): una caja justa se parte en el render y deja una huérfana.
        # Las líneas se parten en el ancho que queda después de esos márgenes: medida con todo el
        # espacio libre, una nota de dos líneas nunca cabía (la cita de fuentes de un deck de cliente).
        line = tm.max_line_width(paras, max((room - 2.0 - 14.4 * s) * kn.safety, 10.0))
        w = line / kn.safety + 2.0 + 14.4 * s
        h = tm.block_height(paras, max(line / kn.safety, 10.0)) + 1.0
        # Centrada en la línea de la frase; si es más alta, apoyada en el borde de la zona segura.
        y = min(py + ph / 2 - h / 2, safe_bottom - h)
        if w > room or y < bottom:
            movable.append((sh, box))  # no entra en la franja del pie: es parte del cuerpo
            continue
        # Sin márgenes internos, como las notas del compositor: alineada al margen y a la frase.
        body = tf._txBody.find(qn("a:bodyPr"))
        for key in ("lIns", "rIns", "tIns", "bIns"):
            body.set(key, "0")
        for paragraph in tf.paragraphs:
            paragraph.alignment = PP_ALIGN.RIGHT
        sh.left, sh.top, sh.width, sh.height = Pt(cursor - w), Pt(y), Pt(w), Pt(h)
        cursor -= w + 14.0 * s
        stats["footer_notes"] = stats.get("footer_notes", 0) + 1
    if not movable:
        return None
    x0, y0 = min(b.x for _s, b in movable), min(b.y for _s, b in movable)
    x1, y1 = max(b.right for _s, b in movable), max(b.bottom for _s, b in movable)
    if x0 >= left - 0.5 and y0 >= top - 0.5 and x1 <= right + 0.5 and y1 <= bottom + 0.5:
        return None
    # Una composición que el autor apoyó en el margen izquierdo sigue apoyada en él (la línea del
    # logo y de neoconsulting.ai): centrarla después de achicarla la dejaba con sangría (Master
    # Talent, slides 5 a 7, 2026-11-19). Su encabezado (antetítulo y título alineados a la
    # izquierda, arriba de todo lo demás) va en el margen y a su tamaño; lo que se achica es el
    # cuerpo, debajo de él.
    anchored = x0 <= left + 2.0 * s
    header: list[tuple[object, Box]] = []
    if anchored:
        body_top = min((b.y for sh, b in movable if not _left_text(sh)), default=None)
        if body_top is not None:
            header = [(sh, b) for sh, b in movable if _left_text(sh) and b.bottom <= body_top + 0.5]
    body = [(sh, b) for sh, b in movable if all(sh is not h for h, _b in header)]
    region_top = top
    if header and body:
        hx0, hy0 = min(b.x for _s, b in header), min(b.y for _s, b in header)
        hy1 = max(b.bottom for _s, b in header)
        dx, dy = left - hx0, max(0.0, top - hy0)
        for sh, b in header:
            nw = min(b.w, right - (b.x + dx))
            sh.left, sh.top, sh.width = Pt(b.x + dx), Pt(b.y + dy), Pt(nw)
        gap = max(min(b.y for _s, b in body) - hy1, 6.0 * s)
        region_top = hy1 + dy + gap
        movable = body
        x0, y0 = min(b.x for _s, b in movable), min(b.y for _s, b in movable)
        x1, y1 = max(b.right for _s, b in movable), max(b.bottom for _s, b in movable)
        stats["header_aligned"] = len(header)
    k = min(1.0, (right - left) / max(x1 - x0, 1.0), (bottom - region_top) / max(y1 - y0, 1.0))
    w, h = (x1 - x0) * k, (y1 - y0) * k
    cx = left + w / 2 if anchored else min(max((x0 + x1) / 2, left + w / 2), right - w / 2)
    cy = min(max((y0 + y1) / 2, region_top + h / 2), bottom - h / 2)
    nx, ny = cx - w / 2, cy - h / 2

    def move(box: Box) -> Box:
        return Box(x=nx + (box.x - x0) * k, y=ny + (box.y - y0) * k, w=box.w * k, h=box.h * k)

    for sh, box in movable:
        new = move(box)
        sh.left, sh.top, sh.width, sh.height = Pt(new.x), Pt(new.y), Pt(new.w), Pt(new.h)
        if k < 1.0:
            _shrink_text(sh._element, k)
            if getattr(sh, "has_chart", False) and sh.has_chart:
                scale_chart_text(sh, k)
    stats["frame_scale"] = round(k, 3)
    return move


def _cobrand_pairs(items: list[_Item], hero: list[Box], client, W: float) -> list[tuple[Box, list[_Item]]]:
    """Bloques de co-marca que ya trae el autor: un logo NEO protagonista (`hero`) con el logo del
    cliente al lado, en la misma fila (la portada «NEO | cliente»). Devuelve, por cada logo NEO,
    la caja que ocupaba el bloque entero y lo que hay que retirar: el logo del cliente y el
    filete que los separaba. El bloque canónico se dibuja en esa misma caja."""
    out = []
    for box in hero:
        cy = box.y + box.h / 2
        partners = [it for it in items if it.kind == "picture" and client.matches(it.sha)
                    and abs(it.box.y + it.box.h / 2 - cy) <= 0.5 * max(it.box.h, box.h)
                    and min(abs(it.box.x - box.right), abs(box.x - it.box.right)) <= 0.12 * W]
        if not partners:
            continue
        boxes = [box, *(it.box for it in partners)]
        x0, y0 = min(b.x for b in boxes), min(b.y for b in boxes)
        span = Box(x=x0, y=y0, w=max(b.right for b in boxes) - x0, h=max(b.bottom for b in boxes) - y0)

        def between(it: _Item) -> bool:
            # Filete del autor: una forma delgada y vertical entre el logo NEO y el del cliente.
            cx = it.box.x + it.box.w / 2
            return any(min(box.right, p.box.right) - 1 <= cx <= max(box.x, p.box.x) + 1 for p in partners)

        rules = [it for it in items if it.kind == "shape" and it.box.w <= 3 < it.box.h
                 and span.contains(it.box, tol=2.0) and between(it)]
        out.append((span, partners + rules))
    return out


def apply_shell(slide, kn: Knowledge, brand_elements, width_emu, height_emu, *,
                keep_layout: bool = False, keep_colors: frozenset[str] | None = None,
                client_logo=None,
                ) -> tuple[list[Issue], set[str], dict]:
    """Devuelve (issues, shas de imágenes retiradas como logo antiguo, estadísticas).

    `keep_layout`: la persona pidió conservar la organización de la slide y corregir solo su
    estilo; además de la base de marca, la composición se encaja en el marco NEO (`_fit_frame`).
    `keep_colors`: con un valor (aunque vacío), los íconos de un color de una slide clara pasan
    al azul de marca salvo esas imágenes (md5[:10]: logos y otras clases que conservan colores).
    `client_logo` (`cobrand.ClientLogo`): la marca es el bloque NEO | cliente que traen los
    `brand_elements`; si la slide ya muestra el logo del cliente, solo se agrega el de NEO.
    """
    issues: list[Issue] = []
    W, H = width_emu / EMU_PER_PT, height_emu / EMU_PER_PT
    # La slide ya viene normalizada a la salida (1440×810 pt) y tokens.yaml está en el lienzo
    # lógico (720×405): el mínimo de letra y las cajas de marca se llevan a la escala real.
    # Comparar en escalas distintas dejaba sin pie las slides con contenido a media altura y
    # nunca subía a 11 pt un texto chico (deck de inducción, 2026-11-02).
    s = W / kn.tokens["canvas"]["width"]
    set_scale(s)
    min_pt = kn.min_size * s
    items: list[_Item] = []
    _collect(slide.shapes, _Transform(), items)
    stats = {"fonts_changed": 0, "runs_bumped_to_min": 0, "runs_kept_small": 0, "nbsp": 0,
             "boxes_grown": 0, "fonts_reduced": 0}
    logos = kn.tokens["brand"]["known_logos"]

    # 1) retirar logos antiguos (con su placa de fondo) y fondos planos a sangre
    removed_shas: set[str] = set()
    old = [it for it in items if it.kind == "picture" and any(it.sha.startswith(p) for p in logos["old"])]

    def backs_old_logo(it: _Item) -> bool:
        return it.kind == "shape" and any(
            Box(x=it.box.x - 12, y=it.box.y - 12, w=it.box.w + 24, h=it.box.h + 24).contains(o.box)
            and it.box.w * it.box.h <= 3 * o.box.w * o.box.h for o in old)

    keep: list[_Item] = []
    for it in items:
        full_plain = it.kind == "shape" and it.box.w * it.box.h >= 0.95 * W * H and _fill_hex(it.shape)
        if it in old or full_plain or backs_old_logo(it):
            if it in old:
                removed_shas.add(it.sha[:10])
            it.shape._element.getparent().remove(it.shape._element)
        else:
            keep.append(it)
    items = keep
    dark = _is_dark(slide, items, W * H)
    mode = "dark" if dark else "light"
    _citations(items, kn, mode, s, stats)
    # logo antiguo protagonista (centrado, no en una esquina): se reemplaza en el mismo lugar
    hero = [o.box for o in old
            if 0.25 * W < o.box.x + o.box.w / 2 < 0.75 * W and 0.2 * H < o.box.y + o.box.h / 2 < 0.8 * H]
    if keep_layout and (move := _fit_frame(slide, kn, W, H, s, stats)):
        hero = [move(box) for box in hero]
        items = []
        _collect(slide.shapes, _Transform(), items)

    veto = _sibling_veto(items, kn, min_pt)
    _restack(items, kn, W, H, stats, min_pt, veto)
    if keep_colors is not None and not dark:
        _tint_icons(items, kn, W, keep_colors, stats)
    # 2) Montserrat + mínimo 11 pt donde cabe + palabras que no caben + huérfanas
    blockers = [it for it in items if it.kind in ("text", "picture") and it.box.w * it.box.h < 0.9 * W * H]
    current_logos = [it for it in items if it.kind == "picture" and any(it.sha.startswith(p) for p in logos["current"])]
    for it in [i for i in items if i.kind == "text"]:
        if any(lg.box.overlaps(it.box) for lg in current_logos):
            continue  # texto que forma parte del logo actual ("AÑOS"): es marca
        tf = it.shape.text_frame
        # La fila de partners es una sola línea en la referencia de Figma. El cuadro
        # original quedó demasiado estrecho y Montserrat partía el rótulo en dos.
        if it.shape.text_frame.text.strip() == "Ecosistema de Partners:":
            # Los logos empiezan en x=188 pt en la slide original; dejamos unos puntos
            # de separación y movemos el rótulo hacia la izquierda para que entre entero.
            target_w = 168.0 * s
            target_x = min(it.box.x, (188.0 - 168.0 - 4.0) * s)
            widened = Box(x=max(0.0, target_x), y=it.box.y, w=max(it.box.w, target_w), h=it.box.h)
            if _free(widened, it, blockers, W, H, items):
                it.shape.left, it.shape.width = Pt(widened.x), Pt(widened.w)
                it.box = widened
                stats["boxes_widened"] = stats.get("boxes_widened", 0) + 1
        fonts = {_Run(el, p).font.name for p in tf.paragraphs for el in _run_elements(p) if el.tag == qn("a:r")}
        if fonts <= kn.allowed_families | kn.exempt_families:
            iw0 = _inner(tf, it.box)[0]
            it.preexisting = set(_problems(_measure_paras(tf, {}), iw0, kn.safety, _indents(tf))[0])
        for p in tf.paragraphs:
            for el in _run_elements(p):
                if el.tag != qn("a:r"):
                    continue
                r = _Run(el, p)
                if r.hyperlink.address:
                    r.font.color.rgb = RGBColor.from_string(kn.tokens["brand_rules"]["hyperlink_color"])
                if r.font.name in kn.exempt_families or r.font.name in kn.allowed_families:
                    continue
                r.font.name = "Montserrat"
                stats["fonts_changed"] += 1
        iw, ih, nowrap = _inner(tf, it.box)
        wrap_w = 10_000 if nowrap else max(iw, 10)
        small = {key: min_pt for key, el, p in _runs(tf)
                 if _Run(el, p).font.size is not None and _Run(el, p).font.size.pt < min_pt - 0.01
                 and _Run(el, p).text.strip()} if not kn.is_citation(tf.text) else {}
        if small:
            before = tm.block_height(_measure_paras(tf, {}), wrap_w * kn.safety)
            after_paras = _measure_paras(tf, small)
            after = tm.block_height(after_paras, wrap_w * kn.safety)
            need_w = tm.max_line_width(after_paras, wrap_w) + 14.4 if nowrap else it.box.w
            grown = Box(x=it.box.x, y=it.box.y, w=max(it.box.w, need_w), h=max(it.box.h, after + 7.2))
            # El alto original no es una garantía: al cambiar a Montserrat puede
            # aparecer una línea adicional dentro de la misma caja.
            fits = after <= ih - 3.0
            room = id(it) not in veto and (fits or _free(grown, it, blockers, W, H, items))
            if room:
                # Caber no basta: un ícono o una foto puestos dentro de la caja del texto (la
                # card de «Las reglas del juego») quedaban tapados por el texto agrandado.
                was, now = _extent(tf, it.box, before), _extent(tf, it.box if fits else grown, after)
                room = not any(b is not it and not b.box.contains(it.box)
                               and _invades(now, b.box) > _invades(was, b.box) + 0.5 * s for b in blockers)
            if room:
                for key, el, p in _runs(tf):
                    if key in small:
                        _Run(el, p).font.size = Pt(min_pt)
                stats["runs_bumped_to_min"] += len(small)
            else:
                stats["runs_kept_small"] += len(small)
                issues.append(Issue(code="min_font_size_kept", severity="error",
                                    detail=f"no cabe a {kn.min_size:g} pt sin chocar: {_preview(it)!r}"))
        if not nowrap:
            _fit_lines(it, tf, kn, blockers, W, H, issues, stats, items, min_pt)
            _fit_height(it, tf, kn, blockers, W, H, issues, stats, items, s)
    # 3) fondo de referencia, logo y frase (solo si hay espacio libre)
    add_background(slide, kn.path(kn.tokens["brand"]["backgrounds"][mode]), width_emu, height_emu)
    has_logo = any(it.kind == "picture" and any(it.sha.startswith(p) for p in logos["current"]) for it in items)
    logo_el = next(e for e in brand_elements(mode) if e.role == "brand_logo")
    if client_logo is not None:
        # El bloque NEO | cliente del autor (portada) se rearma en su lugar con las piezas
        # canónicas, del mismo ancho: logo NEO vigente, filete y logo del cliente.
        for k, (span, drop) in enumerate(_cobrand_pairs(items, hero, client_logo, W)):
            hero = [o for o in hero if not span.contains(o)]
            for it in drop:
                it.shape._element.getparent().remove(it.shape._element)
                items.remove(it)
            lw, lh = logo_el.box.w, logo_el.box.h
            center = Box(x=(span.x + span.w / 2) / s - lw / 2, y=(span.y + span.h / 2) / s - lh / 2, w=lw, h=lh)
            neo = cobrand.fit_width(kn, center, client_logo.aspect, span.w / s, client_logo.band)
            for j, el in enumerate(cobrand.elements(kn, client_logo, neo, mode, align="center")):
                add_element(slide, el, 110 + 3 * k + j)
            has_logo = True
            stats["cobrand_lockup_rebuilt"] = stats.get("cobrand_lockup_rebuilt", 0) + 1
    has_client = client_logo is not None and any(
        it.kind == "picture" and client_logo.matches(it.sha) for it in items)
    for k, o in enumerate(hero):
        # `hero` está en la escala real; la marca se dibuja en la lógica.
        w = max(o.w / s, logo_el.box.w)
        h = w * logo_el.box.h / logo_el.box.w
        cx, cy = (o.x + o.w / 2) / s, (o.y + o.h / 2) / s
        add_element(slide, logo_el.model_copy(update={"box": Box(x=cx - w / 2, y=cy - h / 2, w=w, h=h)}), 100 + k)
        has_logo = True
    phrase_items = [it for it in items if it.kind == "text" and "neoconsulting.ai" in it.shape.text_frame.text]
    has_phrase = bool(phrase_items)
    # La frase que ya trae el origen va a su caja canónica si está en la esquina inferior
    # izquierda: un punto más abajo ya sale de la zona segura.
    px, py, pw, ph = kn.tokens["brand"]["phrase"]["box"]
    for it in phrase_items:
        if it.shape.text_frame.text.strip() == kn.tokens["brand"]["phrase"]["text"] and it.box.y > 0.8 * H \
                and it.box.x < W / 3 and (abs(it.box.y - py * s) > 0.2 or abs(it.box.h - ph * s) > 0.2):
            it.shape.left, it.shape.top, it.shape.height = Pt(px * s), Pt(py * s), Pt(ph * s)
            it.box = Box(x=px * s, y=py * s, w=it.box.w, h=ph * s)
            stats["phrase_aligned"] = 1
    elements = brand_elements(mode)
    # El filete y el logo del cliente van con el logo NEO: se ubican (o se mueven) juntos. Si la
    # slide ya muestra el logo del cliente, el bloque se reduce al logo NEO.
    companions = [] if has_client else [el for el in elements if el.role in COBRAND_ROLES]
    for k, el in enumerate(elements):
        if el.role in COBRAND_ROLES:
            continue
        if (el.role == "brand_logo" and has_logo) or (el.role == "brand_phrase" and has_phrase):
            continue
        unit = [el, *companions] if el.role == "brand_logo" else [el]
        span = _span([u.box for u in unit])
        clash = [b for b in blockers if _scaled(span, s).overlaps(b.box)]
        if clash:
            if el.role == "brand_logo":
                # La esquina izquierda es la regla. Si el contenido la ocupa, el
                # logo (o el bloque NEO | cliente) conserva su tamaño y pasa a la esquina
                # derecha segura, apoyado en el mismo margen.
                rx, ry, rw, rh = kn.tokens["brand"]["logo"]["right_box"]
                dx = rx + rw - span.right
                moved = [u.model_copy(update={"box": u.box.model_copy(update={"x": u.box.x + dx})}) for u in unit]
                right_clash = [b for b in blockers if _scaled(_span([u.box for u in moved]), s).overlaps(b.box)]
                if not right_clash:
                    for j, u in enumerate(moved):
                        add_element(slide, u, k + j)
                    issues.append(Issue(code="brand_logo_movido_derecha", severity="warning",
                                        detail="la posición izquierda estaba ocupada"))
                    continue
            issues.append(Issue(code=f"{el.role}_sin_espacio", severity="error",
                                detail=f"{len(clash)} elemento(s) ocupan la posición canónica"))
            continue
        for j, u in enumerate(unit):
            add_element(slide, u, k + j)
    stats["mode"] = mode
    return issues, removed_shas, stats
