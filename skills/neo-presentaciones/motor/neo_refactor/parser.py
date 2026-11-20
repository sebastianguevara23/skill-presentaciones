"""PPTX -> DeckSpec. Coordenadas absolutas en pt (resuelve transformaciones de grupos)."""
from __future__ import annotations

import hashlib
from pathlib import Path

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.oxml.ns import qn

from .charts import chart_data
from .schemas import Box, DeckSpec, ImageBlock, Paragraph, Run, ShapeBlock, SlideSpec, TextBlock

EMU_PER_PT = 12700
R_ID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"


class _Transform:
    """Mapea coordenadas del espacio hijo de un grupo al espacio del slide."""

    def __init__(self, ox=0.0, oy=0.0, sx=1.0, sy=1.0):
        self.ox, self.oy, self.sx, self.sy = ox, oy, sx, sy

    def apply(self, x, y, w, h) -> Box:
        return Box(
            x=round((self.ox + x * self.sx) / EMU_PER_PT, 2),
            y=round((self.oy + y * self.sy) / EMU_PER_PT, 2),
            w=round(w * self.sx / EMU_PER_PT, 2),
            h=round(h * self.sy / EMU_PER_PT, 2),
        )

    def child(self, group) -> "_Transform":
        xfrm = group._element.grpSpPr.find(qn("a:xfrm"))
        off, ext = xfrm.find(qn("a:off")), xfrm.find(qn("a:ext"))
        ch_off, ch_ext = xfrm.find(qn("a:chOff")), xfrm.find(qn("a:chExt"))
        gx, gy = int(off.get("x")), int(off.get("y"))
        gw, gh = int(ext.get("cx")), int(ext.get("cy"))
        cx, cy = int(ch_off.get("x")), int(ch_off.get("y"))
        cw, ch = int(ch_ext.get("cx")) or 1, int(ch_ext.get("cy")) or 1
        sx, sy = gw / cw, gh / ch
        # posición en el padre = gx + (x - cx) * sx ; luego se aplica el transform del padre
        return _Transform(
            ox=self.ox + (gx - cx * sx) * self.sx,
            oy=self.oy + (gy - cy * sy) * self.sy,
            sx=self.sx * sx,
            sy=self.sy * sy,
        )


def _color(rpr) -> str | None:
    if rpr is None:
        return None
    fill = rpr.find(qn("a:solidFill"))
    if fill is None:
        return None
    srgb = fill.find(qn("a:srgbClr"))
    if srgb is not None:
        return srgb.get("val").upper()
    scheme = fill.find(qn("a:schemeClr"))
    return f"scheme:{scheme.get('val')}" if scheme is not None else None


def _bool(v: str | None) -> bool | None:
    return None if v is None else v in ("1", "true")


def _run_from(el, rels) -> Run:
    rpr = el.find(qn("a:rPr"))
    t = el.find(qn("a:t"))
    font = size = bold = italic = link = None
    if rpr is not None:
        latin = rpr.find(qn("a:latin"))
        font = latin.get("typeface") if latin is not None else None
        size = int(rpr.get("sz")) / 100 if rpr.get("sz") else None
        bold, italic = _bool(rpr.get("b")), _bool(rpr.get("i"))
        hl = rpr.find(qn("a:hlinkClick"))
        if hl is not None and hl.get(R_ID) in rels:
            link = rels[hl.get(R_ID)]
    return Run(
        text=t.text or "" if t is not None else "",
        font=font, size=size, bold=bold, italic=italic, color=_color(rpr), hyperlink=link,
    )


def _paragraphs(txBody, rels) -> list[Paragraph]:
    paras = []
    for p in txBody.findall(qn("a:p")):
        ppr = p.find(qn("a:pPr"))
        runs = []
        for child in p:
            if child.tag in (qn("a:r"), qn("a:fld")):
                runs.append(_run_from(child, rels))
            elif child.tag == qn("a:br"):
                runs.append(Run(text="\n"))
        autonum = ppr.find(qn("a:buAutoNum")) if ppr is not None else None
        paras.append(Paragraph(
            runs=[r for r in runs if r.text],
            align=ppr.get("algn") if ppr is not None else None,
            level=int(ppr.get("lvl", 0)) if ppr is not None else 0,
            bullet=ppr is not None and (ppr.find(qn("a:buChar")) is not None or autonum is not None),
            numbering=autonum.get("type") if autonum is not None else None,
            start_at=int(autonum.get("startAt")) if autonum is not None and autonum.get("startAt") else None,
            margin=int(ppr.get("marL", 0)) / EMU_PER_PT if ppr is not None else 0.0,
        ))
    return paras


def _fill(shape) -> str | None:
    try:
        if shape.fill.type == 1:
            return str(shape.fill.fore_color.rgb)
    except Exception:
        pass
    return None


def _shadowed(shape) -> bool:
    """Card blanca sin borde con sombra exterior (explícita o del estilo del tema)."""
    if (_fill(shape) or "").upper() != "FFFFFF":
        return False
    sp_pr = shape._element.find(qn("p:spPr"))
    if sp_pr is None:
        return False
    line = sp_pr.find(qn("a:ln"))
    if line is not None and line.find(qn("a:noFill")) is None:
        return False
    effects = sp_pr.find(qn("a:effectLst"))
    if effects is not None:
        return effects.find(qn("a:outerShdw")) is not None
    ref = shape._element.find(f"{qn('p:style')}/{qn('a:effectRef')}")
    return ref is not None and ref.get("idx") not in (None, "0")


def parse_deck(path: str | Path, media_dir: str | Path, slides: list[int] | None = None) -> DeckSpec:
    path, media_dir = Path(path), Path(media_dir)
    media_dir.mkdir(parents=True, exist_ok=True)
    prs = Presentation(str(path))
    out = []
    for idx, slide in enumerate(prs.slides, 1):
        if slides and idx not in slides:
            continue
        rels = {rid: rel.target_ref for rid, rel in slide.part.rels.items() if rel.is_external}
        spec = SlideSpec(index=idx, hidden=slide._element.get("show") == "0")
        counters = {"t": 0, "i": 0, "d": 0}
        source_order = 0

        def nid(kind: str) -> str:
            counters[kind] += 1
            return f"{kind}{counters[kind]}"

        def walk(shapes, tr: _Transform):
            nonlocal source_order
            for sh in shapes:
                box = tr.apply(sh.left or 0, sh.top or 0, sh.width or 0, sh.height or 0)
                if sh.shape_type == MSO_SHAPE_TYPE.GROUP:
                    walk(sh.shapes, tr.child(sh))
                    continue

                # El orden de recorrido XML y el id de ``cNvPr`` se conservan como
                # procedencia. Los IDs t1/i1/d1 permanecen para no romper las
                # clasificaciones heredadas, pero el manifiesto puede trazar cada
                # bloque del trabajo sin depender de su tipo de layout.
                source_order += 1
                shape_id = getattr(sh, "shape_id", None)
                if sh.shape_type == MSO_SHAPE_TYPE.PICTURE:
                    blob = sh.image.blob
                    sha = hashlib.md5(blob).hexdigest()[:10]
                    file = media_dir / f"{sha}.{sh.image.ext}"
                    if not file.exists():
                        file.write_bytes(blob)
                    spec.images.append(ImageBlock(
                        id=nid("i"), name=sh.name, box=box, sha=sha, path=str(file),
                        crop=(sh.crop_left, sh.crop_top, sh.crop_right, sh.crop_bottom),
                        source_shape_id=shape_id, source_order=source_order,
                    ))
                elif getattr(sh, "has_text_frame", False) and sh.text_frame.text.strip():
                    spec.texts.append(TextBlock(
                        id=nid("t"), name=sh.name, box=box,
                        paragraphs=_paragraphs(sh.text_frame._txBody, rels), fill=_fill(sh),
                        shadowed=_shadowed(sh), source_shape_id=shape_id, source_order=source_order,
                    ))
                else:
                    kind = str(sh.shape_type).split(" ")[0].lower() if sh.shape_type else "other"
                    spec.shapes.append(ShapeBlock(
                        id=nid("d"), name=sh.name, box=box, kind=kind, fill=_fill(sh),
                        shadowed=_shadowed(sh), source_shape_id=shape_id, source_order=source_order,
                        chart=chart_data(sh.chart) if getattr(sh, "has_chart", False) and sh.has_chart else None,
                    ))
                    if getattr(sh, "has_table", False) and sh.has_table:
                        table_cells(sh, tr)

        def table_cells(frame, tr: _Transform):
            """Cada celda con texto es un bloque: sin esto el texto de una tabla nativa no
            llega al plan ni al control de integridad, y se perdería sin que nadie lo vea.

            El marco de la tabla queda como forma (`d`); las celdas combinadas se leen una
            vez, con el tamaño de toda la combinación.
            """
            nonlocal source_order
            table = frame.table
            widths = [column.width for column in table.columns]
            heights = [row.height for row in table.rows]
            for r, row in enumerate(table.rows):
                for c, cell in enumerate(row.cells):
                    if cell.is_spanned or not cell.text_frame.text.strip():
                        continue
                    source_order += 1
                    box = tr.apply(
                        (frame.left or 0) + sum(widths[:c]), (frame.top or 0) + sum(heights[:r]),
                        sum(widths[c:c + cell.span_width]), sum(heights[r:r + cell.span_height]),
                    )
                    spec.texts.append(TextBlock(
                        id=nid("t"), name=f"{frame.name} [celda {r + 1},{c + 1}]", box=box,
                        paragraphs=_paragraphs(cell.text_frame._txBody, rels),
                        source_shape_id=getattr(frame, "shape_id", None), source_order=source_order,
                    ))

        walk(slide.shapes, _Transform())
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame is not None:
            spec.notes = slide.notes_slide.notes_text_frame.text
        out.append(spec)
    return DeckSpec(
        source=str(path),
        width=prs.slide_width / EMU_PER_PT,
        height=prs.slide_height / EMU_PER_PT,
        slides=out,
    )


def summarize(deck: DeckSpec) -> dict:
    """Vista compacta del deck para que el host (LLM) clasifique cada slide."""
    slides = []
    for s in deck.slides:
        texts = []
        for t in s.texts:
            sizes = sorted({r.size for p in t.paragraphs for r in p.runs if r.size})
            fonts = sorted({r.font for p in t.paragraphs for r in p.runs if r.font})
            texts.append({
                "id": t.id,
                "box": [round(t.box.x), round(t.box.y), round(t.box.w), round(t.box.h)],
                "paragraphs": [p.text for p in t.paragraphs if p.text.strip()],
                "sizes": sizes, "fonts": fonts,
            })
        slides.append({
            "slide": s.index, "hidden": s.hidden,
            "texts": texts,
            "images": [{"id": i.id, "box": [round(i.box.x), round(i.box.y), round(i.box.w), round(i.box.h)], "sha": i.sha}
                       for i in s.images],
            "shapes": [{"id": d.id, "kind": d.kind, "box": [round(d.box.x), round(d.box.y), round(d.box.w), round(d.box.h)],
                        "fill": d.fill} for d in s.shapes],
        })
    return {"source": deck.source, "slides": slides}
