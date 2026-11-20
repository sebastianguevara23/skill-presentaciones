"""Validador determinista sobre la especificación renderizada."""
from __future__ import annotations

from . import textmetrics as tm
from .knowledge import Knowledge
from .schemas import Issue, RenderedSlide, RRect, RText

PENALTY = {"error": 15, "warning": 5}


def validate(rs: RenderedSlide, kn: Knowledge) -> tuple[int, list[Issue]]:
    issues: list[Issue] = []

    def add(code, sev, detail):
        issues.append(Issue(code=code, severity=sev, detail=detail))

    W, H = kn.tokens["canvas"]["width"], kn.tokens["canvas"]["height"]
    left = kn.tokens["margins"]["left"]
    right = W - kn.tokens["margins"]["right"]
    limit = kn.tokens["margins"]["bottom_limit"]
    # El contenedor de un grupo es su primer rectángulo (la tarjeta); los siguientes del
    # mismo grupo son piezas internas, como la cabecera navy de una card de reglas. Las
    # líneas y flechas (filas `rule`) no encierran nada: no son contenedores.
    rects: dict[str, RRect] = {}
    for e in rs.elements:
        if isinstance(e, RRect) and getattr(e, "shape", None) not in ("line", "arrow"):
            rects.setdefault(e.group, e)

    for el in rs.elements:
        b = el.box
        if b.x < 0 or b.y < 0 or b.right > W or b.bottom > H:
            add("out_of_canvas", "error", f"{el.role} {b}")
        if b.x < left - 0.5 or b.right > right + 0.5:
            add("margin", "error", f"{el.role} x={b.x:.1f}..{b.right:.1f}")
        if not getattr(el, "brand", False) and el.role != "note" and b.bottom > limit + 2:
            add("body_limit", "error", f"{el.role} termina en y={b.bottom:.1f} (límite {limit})")
        if not isinstance(el, RText):
            continue
        text = " ".join(p.text for p in el.paras)
        floor = min(rs.font_floor or kn.min_size, kn.size_floor(text))
        for p in el.paras:
            for r in p.runs:
                if r.size < floor - 0.01:
                    add("min_font_size", "error", f"{el.role}: {r.size}pt {r.text[:25]!r}")
                if r.font not in kn.allowed_families and r.font not in kn.exempt_families:
                    add("font_family", "error", f"{el.role}: {r.font}")
            for w, tag in ((b.w, ""), (b.w * kn.safety, " (margen)")):
                if tm.is_orphan(p, w):
                    add("orphan", "error" if not tag else "warning", f"{el.role}{tag}: …{p.text[-30:]!r}")
                    break
        need = tm.block_height(el.paras, b.w * kn.safety)
        if need > b.h + 1:
            add("text_overflow", "error", f"{el.role}: necesita {need:.1f}pt, caja {b.h:.1f}pt")
        box = rects.get(el.group)
        if box and not box.box.contains(el.box):
            add("container_overflow", "error", f"{el.role} se sale de su {box.role}")

    # colisiones entre grupos distintos
    solid = [e for e in rs.elements if e.role != "card_text"]
    for i, a in enumerate(solid):
        for c in solid[i + 1:]:
            if a.group != c.group and a.box.overlaps(c.box):
                add("collision", "error", f"{a.role}[{a.group}] × {c.role}[{c.group}]")

    roles = {e.role for e in rs.elements}
    for needed in kn.brand_required(rs.layout):
        if needed not in roles:
            add("brand_missing", "error", needed)

    for ci in rs.compose_issues:
        add("compose", "error" if "overflow" in ci or "unresolved" in ci else "warning", ci)

    score = max(0, 100 - sum(PENALTY[i.severity] for i in issues))
    return score, issues
