"""`geometry_audit`: reglas duras medidas sobre las cajas del PPTX de salida.

Subchecks con estado propio:

- `safe_zone`: todo elemento visible (salvo fondos a sangre) dentro de la zona
  segura, en **todas** las slides, incluidas las ocultas y las excluidas.
- `brand_position`: logo y footer en una posición registrada en `tokens.yaml`
  (canónica, espejo derecho o centrada) y sin colisionar con contenido.
- `composition_zone`: en slides rediseñadas, el contenido entre márgenes y sobre
  `bottom_limit` (la nota al pie puede bajar; la marca va en su guía).
- `parent_card`: texto que se sale de la card que lo contiene. Se reporta aparte de
  `outside_safe_zone`: una imagen puede sobresalir de su card por composición.
- `typography`: Montserrat y 11 pt como mínimo en slides rediseñadas; en las
  conservadas es aviso (su tipografía es la del origen).
- `palette`: rellenos de las rediseñadas dentro de la paleta (el texto lo audita `brand.py`).
"""
from __future__ import annotations

from ..renderer import BRAND_PREFIX
from ..schemas import Box
from .core import AuditContext, AuditResult, Finding

AUDITOR = "geometry_audit"
SUBCHECKS = ("safe_zone", "brand_position", "composition_zone", "parent_card", "collisions", "typography", "palette")
TOL = 0.5
# Cuánto debe meterse una caja en otra (en ancho y en alto) para que sea un choque y no un roce.
COLLISION_DEPTH = 2.0
POSITION_TOL = 2.0
FOOTER_AIR = 12.0


def role_of(name: str) -> str:
    """El renderer nombra `rol_n` o `NEO_BRAND_rol`: el rol sobrevive en los bytes."""
    if name.startswith(BRAND_PREFIX + "_"):
        return name[len(BRAND_PREFIX) + 1:]
    head, _sep, tail = name.rpartition("_")
    return head if tail.isdigit() and head else name


def is_background(box: Box, name: str, width: float, height: float) -> bool:
    if name == f"{BRAND_PREFIX}_background":
        return True
    return box.x <= 1 and box.y <= 1 and box.w >= 0.97 * width and box.h >= 0.97 * height


def canonical(box: Box, scale: float) -> Box:
    return Box(x=box.x / scale, y=box.y / scale, w=box.w / scale, h=box.h / scale)


def registered_brand_boxes(ctx: AuditContext) -> dict[str, list[tuple[float, ...]]]:
    """Posiciones de marca registradas; el espejo derecho es la secundaria documentada."""
    brand = ctx.kn.tokens["brand"]
    width = ctx.kn.tokens["canvas"]["width"]
    boxes: dict[str, list[tuple[float, ...]]] = {}
    for component, role in (("logo", "brand_logo"), ("phrase", "brand_phrase")):
        spec = brand[component]
        found = [tuple(spec[key]) for key in ("box", "right_box", "centered_box") if key in spec]
        x, y, w, h = spec["box"]
        found.append((width - x - w, y, w, h))
        boxes[role] = found
    # Bloque NEO | cliente (`cobrand.py`): el «NEO» solo, del alto del logo, en la misma esquina.
    from ..cobrand import neo_box
    boxes["brand_logo"].append(tuple(neo_box(ctx.kn, Box(x=brand["logo"]["box"][0], y=brand["logo"]["box"][1],
                                                          w=brand["logo"]["box"][2], h=brand["logo"]["box"][3])
                                             ).model_dump().values()))
    return boxes


def _at(box: Box, reference: tuple[float, ...]) -> bool:
    x, y, w, h = reference
    return all(abs(a - b) <= POSITION_TOL for a, b in ((box.x, x), (box.y, y), (box.w, w), (box.h, h)))


def _inside(box: Box, zone) -> bool:
    left, top, right, bottom = zone
    return box.x >= left - TOL and box.y >= top - TOL and box.right <= right + TOL and box.bottom <= bottom + TOL


def elements(ctx: AuditContext, index: int):
    """(nombre, tipo, caja canónica, bloque) de cada elemento visible de la slide."""
    spec = ctx.deck.slide(index)
    scale = ctx.deck.width / ctx.kn.tokens["canvas"]["width"]
    for block in spec.texts:
        yield block.name, "text", canonical(block.box, scale), block
    for block in spec.images:
        yield block.name, "image", canonical(block.box, scale), block
    for block in spec.shapes:
        if block.kind == "placeholder" and not block.fill:
            continue  # un placeholder vacío no se dibuja en la presentación
        yield block.name, "shape", canonical(block.box, scale), block


def audit(ctx: AuditContext) -> AuditResult:
    result = AuditResult(auditor=AUDITOR)
    contract, kn = ctx.contract, ctx.kn
    width, height = kn.tokens["canvas"]["width"], kn.tokens["canvas"]["height"]
    brand_boxes = registered_brand_boxes(ctx)
    palette = {value.upper() for value in kn.tokens["colors"].values()}
    allowed_fonts = kn.allowed_families | kn.exempt_families

    for slide in ctx.slides:
        text_scale = ctx.deck.width / width
        def add(subcheck, code, status, name, symptom, cause, correction, acceptance, **measurement):
            result.findings.append(Finding(
                check=AUDITOR, subcheck=subcheck, code=code, status=status, slide_id=slide.index,
                source_slide_id=slide.source_slide_id, family=slide.family, source_reference=name,
                symptom=symptom, measurement=measurement, cause=cause,
                correction_proposed=correction, acceptance=acceptance,
            ))

        output_canvas = kn.tokens.get("output_canvas", {})
        target_w, target_h = output_canvas.get("width_pt"), output_canvas.get("height_pt")
        actual_w, actual_h = ctx.presentation.slide_width.pt, ctx.presentation.slide_height.pt
        if target_w is not None and target_h is not None and (
            abs(actual_w - float(target_w)) > TOL or abs(actual_h - float(target_h)) > TOL
        ):
            add("safe_zone", "output_canvas_mismatch", "fail", "presentation_canvas",
                "el PPTX no tiene el tamaño de salida 1920×1080 px", "el lienzo final no se normalizó al formato canónico",
                "normalizar la presentación a las dimensiones de salida del manifiesto",
                "todas las slides usan el lienzo 1920×1080 px",
                actual_pt=[actual_w, actual_h], expected_pt=[target_w, target_h],
                expected_px=[output_canvas.get("width_px"), output_canvas.get("height_px")])

        items = [
            item for item in elements(ctx, slide.index)
            if not is_background(item[2], item[0], width, height)
        ]
        content = [item for item in items if not item[0].startswith(BRAND_PREFIX)]
        for name, kind, box, _block in items:
            if not _inside(box, contract.geometry_zone):
                add("safe_zone", "outside_safe_zone", "fail", name,
                    f"{kind} fuera de la zona segura", "caja más allá de los límites del lienzo útil",
                    "mover o redimensionar dentro de la zona sin cambiar contenido",
                    "la caja queda dentro de la zona segura", box=box.model_dump(), zone=list(contract.geometry_zone))

        for name, kind, box, block in items:
            if not name.startswith(BRAND_PREFIX):
                continue
            role = role_of(name)
            references = list(brand_boxes.get(role, []))
            layout = (slide.marker or {}).get("layout")
            if slide.redesigned and layout in kn.layouts:
                # Un layout puede registrar su propio lockup (p. ej. el cierre centrado).
                component = "logo" if role == "brand_logo" else "phrase"
                references += [tuple(value) for key, value in kn.geometry(layout).items()
                               if key.startswith(f"{component}_box")]
            if references and not any(_at(box, ref) for ref in references):
                add("brand_position", "noncanonical_brand_position", "fail", name,
                    "marca fuera de sus posiciones registradas", "posición de marca no registrada",
                    "volver a la posición canónica o a la secundaria registrada",
                    "logo y footer en una posición de tokens.yaml", box=box.model_dump(),
                    registered=[list(ref) for ref in references])
            if role_of(name) == "brand_phrase":
                for other, other_kind, other_box, _b in content:
                    if other_kind not in ("text", "image"):
                        continue
                    if other_box.overlaps(box):
                        add("brand_position", "brand_collision", "fail", other,
                            "el contenido pisa el footer de marca", "caja de contenido sobre la franja de marca",
                            "subir el contenido o usar la posición secundaria del footer",
                            "ningún texto o imagen toca el footer", footer=box.model_dump(), box=other_box.model_dump())
                    elif Box(x=box.x - FOOTER_AIR, y=box.y - FOOTER_AIR, w=box.w + 2 * FOOTER_AIR,
                             h=box.h + 2 * FOOTER_AIR).overlaps(other_box):
                        add("brand_position", "footer_content_clearance", "warning", other,
                            "contenido a menos de 12 pt del footer", "poco aire sobre la franja de marca",
                            "subir el contenido o mover el footer a la posición secundaria",
                            "al menos 12 pt entre contenido y footer", footer=box.model_dump(), box=other_box.model_dump())

        if not slide.redesigned:
            for _name, kind, _box, block in content:
                if kind != "text":
                    continue
                floor = kn.size_floor(" ".join(p.text for p in block.paragraphs))
                small = sorted({round(run.size / text_scale, 2) for p in block.paragraphs for run in p.runs
                                if run.size and run.size / text_scale < floor - 0.01 and run.text.strip()})
                if small:
                    add("typography", "preserved_small_type", "warning", block.name,
                        "tipografía menor al mínimo en una slide conservada", "la slide no se rediseñó",
                        "rediseñar la slide o registrar la excepción", f"texto de al menos {kn.min_size:g} pt",
                        sizes=small)
            continue

        limit = kn.tokens["margins"]["bottom_limit"]
        for name, kind, box, block in content:
            role = role_of(name)
            if not _inside(box, contract.composition_zone) and not (role == "note" and box.bottom <= contract.geometry_zone[3]):
                add("composition_zone", "outside_composition_zone", "fail", name,
                    f"{role} fuera de la guía de composición", "el componente invade margen o franja inferior",
                    "redistribuir dentro de la guía o partir la slide", f"contenido entre márgenes y sobre y={limit}",
                    box=box.model_dump(), zone=list(contract.composition_zone))

        containers = [(name, box) for name, kind, box, _b in content if kind == "shape"]
        for name, kind, box, block in content:
            if kind == "shape":
                continue
            area = box.w * box.h
            parents = [
                (cname, cbox) for cname, cbox in containers
                if cname != name and cbox.w * cbox.h > area and cbox.overlaps(box)
                and _overlap_area(cbox, box) >= 0.5 * area
            ]
            if not parents:
                continue
            pname, pbox = min(parents, key=lambda item: item[1].w * item[1].h)
            # Un contenedor puede estar hecho de varias piezas (cabecera + base): basta con
            # que la unión de las piezas que tocan el texto lo cubra.
            if not pbox.contains(box) and not _covered(box, [c for _n, c in containers if c.overlaps(box)]):
                add("parent_card", "outside_parent_card", "fail" if kind == "text" else "warning", name,
                    f"{kind} se sale de su contenedor {pname}", "caja más grande que su card",
                    "ampliar la card o reducir la caja del texto", "el texto queda dentro de su card",
                    box=box.model_dump(), parent=pbox.model_dump())

        # Texto encima de una foto o de una card ajena: lo vio solo la revisión visual del host
        # (deck de inducción 2026-10-26: indicaciones sobre las fotos; deck interno 2026-10-27: la nota
        # al pie sobre la tercera card). Una card propia ya la juzga `parent_card`.
        texts = [(name, box) for name, kind, box, block in content if kind == "text" and block.text.strip()]
        for name, box in texts:
            # Dentro de un contenedor de varias piezas (cabecera + base) no es un choque.
            inside = _covered(box, [c for _n, c in containers if c.overlaps(box)])
            for other, other_kind, other_box, _b in content:
                if other == name or other_kind == "text" or not _collides(box, other_box):
                    continue
                if other_kind == "image":
                    add("collisions", "text_over_image", "fail", name,
                        "el texto se dibuja encima de una imagen", "la caja del texto invade la de la imagen",
                        "recomponer para que el texto quede fuera de la imagen", "ningún texto pisa una imagen",
                        box=box.model_dump(), image=other_box.model_dump(), image_name=other)
                elif not inside and _overlap_area(other_box, box) < 0.5 * box.w * box.h and not other_box.contains(box):
                    add("collisions", "text_over_card", "fail", name,
                        f"el texto pisa {other}, que no es su card", "la caja del texto invade otra card",
                        "recomponer para que el texto quede en su card o fuera de todas", "ningún texto pisa una card ajena",
                        box=box.model_dump(), card=other_box.model_dump(), card_name=other)

        for _name, kind, _box, block in content:
            if kind == "text":
                # Una cita de fuente tiene su propio mínimo (`typography.citation`).
                floor = kn.size_floor(" ".join(p.text for p in block.paragraphs))
                for paragraph in block.paragraphs:
                    for run in paragraph.runs:
                        if not run.text.strip():
                            continue
                        logical_size = run.size / text_scale if run.size is not None else None
                        if logical_size is not None and logical_size < floor - 0.01:
                            add("typography", "min_font_size", "fail", block.name,
                                f"texto a {logical_size:g} pt lógicos", "cuerpo menor al mínimo",
                                "ampliar caja o partir; nunca bajar de 11 pt", f"todo texto ≥ {kn.min_size:g} pt",
                                size=run.size, logical_size=logical_size, text=run.text[:30])
                        if run.font and run.font not in allowed_fonts:
                            add("typography", "font_family", "fail", block.name,
                                f"fuente {run.font}", "fuente fuera del sistema",
                                "usar Montserrat", "solo familias permitidas", font=run.font)
                        # El color del texto lo juzga `style_integrity_audit` (brand.py).
            elif kind == "shape" and block.fill and block.fill.upper() not in palette:
                add("palette", "off_palette_color", "fail", block.name,
                    f"relleno #{block.fill}", "color fuera de la paleta",
                    "usar el color del componente", "colores de la paleta", color=block.fill)

    ctx.apply_exceptions(result)
    return result.finish([slide.index for slide in ctx.slides], SUBCHECKS)


def _covered(box: Box, pieces: list[Box], steps: int = 6) -> bool:
    """¿La unión de `pieces` cubre la caja? Se muestrea una rejilla de puntos interiores."""
    for i in range(steps):
        for j in range(steps):
            x = box.x + box.w * (i + 0.5) / steps
            y = box.y + box.h * (j + 0.5) / steps
            if not any(p.x - TOL <= x <= p.right + TOL and p.y - TOL <= y <= p.bottom + TOL for p in pieces):
                return False
    return True


def _collides(a: Box, b: Box) -> bool:
    """Las cajas se meten una en otra al menos `COLLISION_DEPTH` en ancho y en alto."""
    return (min(a.right, b.right) - max(a.x, b.x) > COLLISION_DEPTH
            and min(a.bottom, b.bottom) - max(a.y, b.y) > COLLISION_DEPTH)


def _overlap_area(a: Box, b: Box) -> float:
    w = min(a.right, b.right) - max(a.x, b.x)
    h = min(a.bottom, b.bottom) - max(a.y, b.y)
    return max(0.0, w) * max(0.0, h)
