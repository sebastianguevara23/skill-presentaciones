"""Crear un deck desde un pedido: el guion aprobado es el contrato de contenido (C1).

El modelo escribe el guion (`DeckOutline`): por slide, una familia del catálogo y su texto
repartido en unidades. Este módulo lo convierte en un PPTX de origen sencillo —una caja de texto
por pieza y un recuadro «Colocar imagen» donde la familia lleva foto— y en el plan que asigna cada
caja a su slot. Desde ahí corre el pipeline de siempre (composer, render, auditorías, revisión
visual): la regla «no se toca el contenido» se aplica sola, porque el origen *es* el guion.

No hay un segundo motor ni geometría propia: si un texto no cabe, lo dice la misma composición de
un rediseño, hecha en seco al armar el guion (`engine.dry_compose`), y el modelo acorta o parte la slide.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from pptx import Presentation
from pptx.util import Pt
from pydantic import BaseModel, Field, model_validator

from .knowledge import ROOT, Knowledge
from .schemas import AnalysisPlan, SourceManifest

PLACEHOLDER_TEXT = "Colocar imagen"
FONT = ROOT / "assets" / "fonts" / "Montserrat-Medium.ttf"


@dataclass(frozen=True)
class Creatable:
    """Cómo se escribe una familia en el guion: qué piezas lleva y con qué rol."""

    layout: str
    unit: str | None = None          # rol de la unidad repetida (`card`, `item`…); None = sin unidades
    body: bool = False               # un cuerpo de texto suelto (image_text)
    images: tuple[int, int] = (0, 0)  # recuadros «Colocar imagen» admitidos (mín, máx)
    photo: bool = False              # cada unidad lleva su foto (equipo)
    fields: tuple[str, ...] = ("number", "title", "label", "body")  # piezas de una unidad, en orden
    hint: str = ""
    look: str = ""                   # forma visual (LOOKS): el ritmo del deck se mide con esto
    family: str | None = None        # familia del catálogo, si no es la misma clave (p. ej. key_metrics)
    archetype: str | None = None     # variante registrada de la familia (`rows`)
    parts: dict[str, str] | None = None  # campo → pieza propia de la unidad (metric:N:value)
    aside: bool = False              # admite paneles de apoyo a la derecha (`aside`)


# Las familias que se pueden crear: las del catálogo que componen sin un original de referencia
# (las de taller —matrices, hojas de trabajo— quedan para después). El layout sale del catálogo;
# aquí solo va cómo se reparte el texto.
CREATABLE: dict[str, Creatable] = {
    "title_slide": Creatable("section", hint="portada: título del deck y subtítulo", look="section"),
    "section_divider": Creatable("section", hint="separador de sección: título y subtítulo", look="section"),
    "three_cards": Creatable("three_cards", "card", hint="2-3 ideas paralelas con número/título/cuerpo", look="cards"),
    "ai_maturity_levels": Creatable("three_cards", "card", hint="3 niveles con título y cuerpo", look="cards"),
    "rules_cards": Creatable("card_grid", "card", hint="2-6 reglas, principios o tareas con título y cuerpo",
                             look="header_cards"),
    "benefits_content": Creatable("card_grid", "card", hint="2-6 beneficios con título y cuerpo", look="cards"),
    "tools_content": Creatable("card_grid", "card", hint="2-6 herramientas con título y cuerpo", look="cards"),
    "timeline": Creatable("card_grid", "card", hint="2-6 hitos con número (año), título y cuerpo", look="cards"),
    "workflow_steps": Creatable("card_grid", "card", hint="2-6 pasos con número, título y cuerpo", look="cards"),
    "paired_process": Creatable("card_grid", "card", hint="2 procesos, perfiles u opciones a comparar, con título, "
                                "etiqueta y cuerpo", look="header_cards"),
    "three_unit_overview": Creatable("circles", "circle", fields=("title",), hint="2-4 conceptos de una o dos palabras",
                                     look="circles"),
    "table_of_contents": Creatable("item_list", "item", fields=("number", "title"),
                                   hint="2-12 ítems con número y título", look="list"),
    "adr_framework": Creatable("item_list", "item", fields=("number", "title"), hint="2-12 componentes con título",
                               look="list"),
    "agenda_list": Creatable("image_text", body=True, images=(1, 1), hint="agenda: cuerpo con un tema por línea y una imagen",
                             look="image"),
    "image_text_clients": Creatable("image_text", body=True, images=(1, 2), hint="mensaje en el cuerpo con 1-2 imágenes",
                                    look="image"),
    "image_heavy_special": Creatable("image_text", body=True, images=(2, 4),
                                     hint="imagen protagonista: cuerpo corto y 2-4 imágenes", look="image"),
    "team_grid": Creatable("team_grid", "member", photo=True, fields=("title", "label"),
                           hint="1-10 personas: nombre (title) y cargo (label)", look="team"),
    "closing_slide": Creatable("closing", hint="cierre: lo reemplaza la despedida canónica de marca", look="closing"),
    # Formas sin tarjeta (2026-10-12): cifras, filas y lista con paneles. Usan familias del
    # catálogo con otra composición; el guion solo dice cómo se reparte el texto.
    "key_metrics": Creatable("metrics_row", "metric", family="benefits_content", fields=("number", "label", "body"),
                             parts={"number": "value", "label": "label", "body": "description"},
                             hint="2-5 cifras: el valor en number («3», «+40 %»), label corto y body opcional",
                             look="metrics"),
    "detail_rows": Creatable("item_list", "item", family="table_of_contents", archetype="rows",
                             fields=("number", "title", "body"),
                             hint="2-10 filas: número, título y una línea de detalle", look="rows"),
    "steps_aside": Creatable("list_aside", "item", family="activity_guide", fields=("number", "title", "body"),
                             aside=True, hint="1-8 pasos o puntos a la izquierda y 1-3 paneles en `aside` "
                             "(recursos, reglas, a quién preguntar)", look="steps_aside"),
}

# Nombre visible de las creables que no son una familia del catálogo (la vista del guion).
LABELS = {"key_metrics": "Cifras", "detail_rows": "Filas con detalle", "steps_aside": "Lista con paneles"}

# Cómo se ve cada forma: el modelo elige por lo que el contenido ES, no por costumbre.
LOOKS: dict[str, str] = {
    "cards": "tarjetas blancas con borde azul en fila o rejilla (ideas paralelas, pasos, hitos)",
    "header_cards": "tarjetas con cabecera navy y el cuerpo debajo (reglas, tareas, perfiles o procesos a comparar)",
    "list": "lista vertical numerada, una línea por ítem (índices, enumeraciones largas, componentes)",
    "rows": "filas sin tarjeta separadas por una línea fina, con detalle (preguntas, posts, puntos a aprobar)",
    "metrics": "cifras grandes en fila con su etiqueta (resultados, metas, ritmo, KPIs)",
    "steps_aside": "lista numerada a la izquierda y paneles de apoyo a la derecha (programa + reglas, pasos + recursos)",
    "circles": "círculos con un concepto corto cada uno (pilares, unidades, ejes)",
    "image": "mensaje con barra azul junto a 1-4 imágenes (casos, contexto, un mensaje fuerte)",
    "team": "fichas con foto circular, nombre y cargo (personas)",
    "section": "título grande solo (portada o separador de sección)",
    "closing": "cierre de marca",
}
# Formas de contenido que cuentan para el ritmo (portada, separador y cierre no).
RHYTHM_RUN = 3


class OutlineUnit(BaseModel):
    """Una tarjeta, ítem, círculo o persona. Solo las piezas que la familia admite."""

    number: str | None = Field(default=None, max_length=24, description="Número, año o cifra corta («01», «2026»).")
    title: str | None = Field(default=None, max_length=90)
    label: str | None = Field(default=None, max_length=60, description="Etiqueta o cargo, en una línea.")
    body: str | None = Field(default=None, max_length=1500, description=(
        "Cuerpo; un salto de línea = un párrafo. El tope es amplio para no recortar texto de la persona: "
        "si no cabe en la slide, lo dice la medición del guion."))


class OutlineSlide(BaseModel):
    family: str = Field(description="Una familia creable (ver la descripción de la tool).")
    title: str = Field(min_length=1, max_length=120)
    kicker: str | None = Field(default=None, max_length=60, description="Antetítulo corto, opcional.")
    subtitle: str | None = Field(default=None, max_length=200)
    body: str | None = Field(default=None, max_length=2500, description="Solo familias con cuerpo suelto.")
    units: list[OutlineUnit] = Field(default_factory=list)
    images: int = Field(default=0, ge=0, le=4, description="Recuadros «Colocar imagen» (familias con imagen).")
    note: str | None = Field(default=None, max_length=200, description="Nota o fuente al pie, opcional.")
    aside: list[str] = Field(default_factory=list, max_length=3, description=(
        "Solo steps_aside: 1-3 paneles de apoyo; la primera línea de cada uno es su título."))


class DeckOutline(BaseModel):
    """El guion: lo que la persona aprueba antes de generar la presentación."""

    title: str = Field(min_length=1, max_length=120, description="Nombre del deck (también va en la portada).")
    subtitle: str | None = Field(default=None, max_length=200, description="Subtítulo de la portada.")
    request: str = Field(min_length=1, max_length=600, description="El pedido de la persona, citado.")
    slides: list[OutlineSlide] = Field(min_length=1, max_length=40)

    @model_validator(mode="after")
    def _families_exist(self):
        unknown = sorted({slide.family for slide in self.slides} - set(CREATABLE))
        if unknown:
            raise ValueError(f"familias que no se pueden crear: {', '.join(unknown)}; "
                             f"válidas: {', '.join(CREATABLE)}")
        return self


class OutlineError(ValueError):
    """El guion no se puede convertir: el mensaje dice qué corregir."""


def with_cover(outline: DeckOutline) -> DeckOutline:
    """La portada clara es obligatoria: si el guion no abre con una, se arma con su título."""
    if outline.slides[0].family == "title_slide":
        return outline
    cover = OutlineSlide(family="title_slide", title=outline.title, subtitle=outline.subtitle)
    return outline.model_copy(update={"slides": [cover, *outline.slides]})


# En las listas el número va en una insignia angosta junto al ítem: más de tres caracteres
# no se dibujan (deck interno, 2026-10-27: «Lunes» como número quedó invisible).
BADGE_LAYOUTS = ("item_list", "list_aside")
BADGE_MAX_CHARS = 3


def _number_problem(number: str | None, spec: Creatable) -> str | None:
    """`number` es un número o una cifra; una palabra («Lunes», «Daniel») va en `title`."""
    value = (number or "").strip()
    if not value:
        return None
    if not any(char.isdigit() for char in value) and len(value) > BADGE_MAX_CHARS:
        return (f"«{value}» no es un número: `number` lleva un número o una cifra («01», «2026», «+40 %»); "
                "una palabra va en `title`")
    if spec.layout in BADGE_LAYOUTS and len(value) > BADGE_MAX_CHARS:
        return (f"«{value}» no cabe en la insignia del número (hasta {BADGE_MAX_CHARS} caracteres, como «01»); "
                "un año o una fecha va en `title`, o usa una familia con tarjetas")
    return None


def check(outline: DeckOutline, knowledge: Knowledge | None = None) -> list[str]:
    """Problemas de forma del guion (cantidades y piezas), antes de medir si cabe."""
    knowledge = knowledge or Knowledge(ROOT)
    problems = []
    for number, slide in enumerate(outline.slides, start=1):
        spec = CREATABLE[slide.family]
        where = f"slide {number} ({slide.family})"
        if spec.unit:
            capacity = knowledge.capacity(spec.layout)
            low, high = (capacity.minimum, capacity.maximum) if capacity else (1, 12)
            if not low <= len(slide.units) <= high:
                problems.append(f"{where}: lleva {len(slide.units)} unidades y admite de {low} a {high}; "
                                "si son más, pártela en dos slides de la misma familia")
            for index, unit in enumerate(slide.units, start=1):
                extra = [name for name in ("number", "title", "label", "body")
                         if getattr(unit, name) and name not in spec.fields]
                if extra:
                    problems.append(f"{where}, unidad {index}: esta familia no lleva {', '.join(extra)}")
                if not any(getattr(unit, name) for name in spec.fields):
                    problems.append(f"{where}, unidad {index}: está vacía")
                problem = _number_problem(unit.number, spec)
                if problem:
                    problems.append(f"{where}, unidad {index}: {problem}")
        elif slide.units:
            problems.append(f"{where}: esta familia no lleva unidades")
        if slide.aside and not spec.aside:
            problems.append(f"{where}: esta familia no lleva paneles `aside`")
        if spec.aside and not slide.aside:
            problems.append(f"{where}: falta al menos un panel en `aside`")
        if slide.body and not spec.body:
            problems.append(f"{where}: esta familia no lleva cuerpo suelto; reparte el texto en unidades")
        if spec.body and not (slide.body or "").strip():
            problems.append(f"{where}: falta el cuerpo")
        low, high = spec.images
        images = slide.images or low
        if not low <= images <= high:
            problems.append(f"{where}: admite de {low} a {high} imágenes" if high else f"{where}: no lleva imágenes")
    return problems


def _placeholder(path: Path, size: tuple[int, int], label: str, salt: int) -> Path:
    """Recuadro blanco de marca con «Colocar imagen»: se reemplaza a mano en el PPTX final.

    `salt` cambia un píxel invisible: dos recuadros iguales tendrían el mismo hash y la integridad
    los confundiría entre slides.
    """
    image = Image.new("RGB", size, (255, 255, 255))
    draw = ImageDraw.Draw(image)
    width, height = size
    edge = max(4, width // 200)
    draw.rectangle([edge // 2, edge // 2, width - edge, height - edge], outline=(197, 213, 247), width=edge)
    try:
        font = ImageFont.truetype(str(FONT), max(18, width // 18))
    except OSError:
        font = ImageFont.load_default()
    box = draw.textbbox((0, 0), label, font=font)
    draw.text(((width - (box[2] - box[0])) / 2, (height - (box[3] - box[1])) / 2), label,
              fill=(87, 87, 87), font=font)
    image.putpixel((width - 2, height - 2), (255, 255 - (salt % 7), 255 - (salt // 7 % 7)))
    image.save(path)
    return path


@dataclass
class _Piece:
    text: str | None          # None = imagen
    role: str
    paragraph_roles: list[str]
    image: Path | None = None


def _unit_paragraphs(unit: OutlineUnit, fields: tuple[str, ...]) -> tuple[str, list[str]]:
    lines, roles = [], []
    for name in fields:
        value = (getattr(unit, name) or "").strip()
        if not value:
            continue
        parts = [part.strip() for part in value.split("\n") if part.strip()] if name == "body" else [" ".join(value.split())]
        lines += parts
        roles += [name] * len(parts)
    return "\n".join(lines), roles


def _pieces(slide: OutlineSlide, number: int, media: Path) -> list[_Piece]:
    spec = CREATABLE[slide.family]
    pieces = []
    if slide.kicker and spec.layout != "closing":
        pieces.append(_Piece(slide.kicker, "kicker", []))
    pieces.append(_Piece(slide.title, "title", []))
    if slide.subtitle:
        pieces.append(_Piece(slide.subtitle, "subtitle", []))
    for index, unit in enumerate(slide.units, start=1):
        if spec.parts:
            # Cada campo es su propia caja (`metric:1:value`): el layout las coloca por separado.
            for name in spec.fields:
                value = " ".join((getattr(unit, name) or "").split())
                if value:
                    pieces.append(_Piece(value, f"{spec.unit}:{index}:{spec.parts[name]}", []))
            continue
        text, roles = _unit_paragraphs(unit, spec.fields)
        pieces.append(_Piece(text, f"{spec.unit}:{index}", roles))
    for index, panel in enumerate(slide.aside, start=1):
        lines = [line.strip() for line in panel.split("\n") if line.strip()]
        if lines:
            # Primera línea: título del panel (blanco negrita); el resto, cuerpo.
            pieces.append(_Piece("\n".join(lines), f"aside:{index}", ["title"] + ["body"] * (len(lines) - 1)))
    if spec.body and slide.body:
        pieces.append(_Piece("\n".join(line.strip() for line in slide.body.split("\n") if line.strip()), "body", []))
    if slide.note and spec.layout not in ("section", "closing"):
        pieces.append(_Piece(slide.note, "note", []))
    count = slide.images or spec.images[0]
    for index in range(1, count + 1):
        path = _placeholder(media / f"s{number}-image-{index}.png", (1600, 900),
                            PLACEHOLDER_TEXT if count == 1 else f"{PLACEHOLDER_TEXT} {index}", number * 10 + index)
        pieces.append(_Piece(None, f"image:{index}", [], path))
    if spec.photo:
        for index in range(1, len(slide.units) + 1):
            path = _placeholder(media / f"s{number}-photo-{index}.png", (600, 600), "Foto", number * 100 + index)
            pieces.append(_Piece(None, f"{spec.unit}:{index}:photo", [], path))
    return pieces


@dataclass
class Built:
    path: Path
    roles: dict[str, list[_Piece]]   # slide id → piezas en el orden de sus elementos


def build_pptx(outline: DeckOutline, target: Path) -> Built:
    """El PPTX de origen: una caja por pieza, en el orden en que el plan las asigna."""
    media = target.parent / f"{target.stem}-media"
    media.mkdir(parents=True, exist_ok=True)
    deck = Presentation()
    deck.slide_width, deck.slide_height = Pt(720), Pt(405)
    roles: dict[str, list[_Piece]] = {}
    for number, slide in enumerate(outline.slides, start=1):
        page = deck.slides.add_slide(deck.slide_layouts[6])
        pieces = _pieces(slide, number, media)
        texts = [piece for piece in pieces if piece.text is not None]
        images = [piece for piece in pieces if piece.text is None]
        # Las cajas no se superponen: la geometría del origen no importa (la pone el composer),
        # pero una caja tapada podría leerse como decorativa.
        for index, piece in enumerate(texts):
            box = page.shapes.add_textbox(Pt(30), Pt(20 + index * 24), Pt(400), Pt(22))
            frame = box.text_frame
            for position, line in enumerate(piece.text.split("\n")):
                paragraph = frame.paragraphs[0] if position == 0 else frame.add_paragraph()
                paragraph.text = line
        for index, piece in enumerate(images):
            page.shapes.add_picture(str(piece.image), Pt(460 + (index % 3) * 70), Pt(40 + (index // 3) * 50),
                                    Pt(64), Pt(36 if piece.role.startswith("image") else 64))
        roles[f"s{number}"] = texts + images
    target.parent.mkdir(parents=True, exist_ok=True)
    deck.save(target)
    return Built(target, roles)


def plan_from_outline(outline: DeckOutline, built: Built, manifest: SourceManifest, plan: AnalysisPlan) -> AnalysisPlan:
    """Asigna cada elemento del origen a su slot: el guion ya dice qué es cada pieza."""
    slides = []
    for slide_plan, outline_slide in zip(plan.slides, outline.slides):
        pieces = built.roles[slide_plan.source_slide_id]
        source = manifest.slide(slide_plan.source_slide_id)
        content = [element for element in source.elements if element.kind in ("text", "image")]
        if len(content) != len(pieces):
            raise OutlineError(f"{slide_plan.source_slide_id}: el origen tiene {len(content)} piezas y el guion "
                               f"{len(pieces)}; vuelve a enviar el guion")
        by_id = {element.id: piece for element, piece in zip(content, pieces)}
        assignments = [assignment.model_copy(update={
            "classification": "content", "role": by_id[assignment.element_id].role,
            "paragraph_roles": by_id[assignment.element_id].paragraph_roles,
        }) if assignment.element_id in by_id else assignment for assignment in slide_plan.assignments]
        spec = CREATABLE[outline_slide.family]
        slides.append(slide_plan.model_copy(update={
            "family": spec.family or outline_slide.family, "archetype": spec.archetype,
            "composition_layout": spec.layout, "assignments": assignments,
            "selected_for_redesign": True, "family_explanation": None, "confidence": "high",
            "evidence": "familia elegida en el guion aprobado",
            # Los recuadros «Colocar imagen» son de origen: el optimizador no los toca.
            "asset_classes": {element.id: "source" for element in content if element.kind == "image"},
        }))
    return plan.model_copy(update={"slides": slides})


def outline_view(outline: DeckOutline) -> dict:
    """Lo que la vista dibuja como guion (storyboard): sin geometría, solo el contenido."""
    return {
        "title": outline.title, "subtitle": outline.subtitle, "request": outline.request,
        "slides": [{
            "family": slide.family, "label": LABELS.get(slide.family), "title": slide.title,
            "kicker": slide.kicker, "subtitle": slide.subtitle,
            "body": slide.body, "note": slide.note, "aside": slide.aside,
            "images": slide.images or CREATABLE[slide.family].images[0],
            "units": [unit.model_dump(exclude_none=True) for unit in slide.units],
        } for slide in outline.slides],
    }


def creatable_description(knowledge: Knowledge | None = None) -> str:
    """Familias creables agrupadas por cómo se ven, con su capacidad (generado del catálogo)."""
    knowledge = knowledge or Knowledge(ROOT)
    lines = []
    for look, description in LOOKS.items():
        lines.append(f"[{description}]")
        for family, spec in CREATABLE.items():
            if spec.look != look:
                continue
            capacity = knowledge.capacity(spec.layout) if spec.unit else None
            units = f"; {spec.unit}: {capacity.minimum}-{capacity.maximum}" if capacity else ""
            fields = f" ({'/'.join(spec.fields)})" if spec.unit else ""
            lines.append(f"- {family}: {spec.hint}{units}{fields}")
    lines.append(
        "Ritmo: elige la forma por lo que el contenido es (pasos, comparación, personas, lista, un mensaje) "
        f"y alterna: {RHYTHM_RUN} o más slides seguidas con la misma forma se ven planas. Si el aviso de "
        "ritmo aparece, cambia la forma de alguna salvo que la repetición sea a propósito (p. ej. una "
        "serie de perfiles que deben leerse igual); en ese caso, dilo.")
    return "\n".join(lines)


def emoji_issues(outline: DeckOutline, plan: AnalysisPlan) -> list:
    """Avisos (no bloquean) por los emojis del guion: por marca no se dibujan.

    Se dice antes de aprobar el guion, con el texto como va a quedar. En IA (2026-10-27) una
    card sobre emojis salió «como , sin una función clara» y se descubrió en la revisión final.
    """
    from .cleanup import EMOJI, strip_emojis
    from .schemas import PlanValidationIssue

    issues = []
    for index, slide in enumerate(outline.slides):
        texts = [slide.title, slide.subtitle, slide.kicker, slide.body, slide.note, *slide.aside,
                 *(getattr(unit, name) for unit in slide.units for name in ("number", "title", "label", "body"))]
        found = [text for text in texts if text and EMOJI.search(text)]
        if not found or index >= len(plan.slides):
            continue
        sample = found[0]
        issues.append(PlanValidationIssue(
            source_slide_id=plan.slides[index].source_slide_id, code="outline_emoji_removed", severity="warning",
            detail=(f"Los emojis no se dibujan (regla de marca): «{' '.join(sample.split())[:80]}» quedará "
                    f"«{' '.join(strip_emojis(sample).split())[:80]}». Si el emoji es el contenido, pide a la "
                    "persona describirlo con palabras antes de aprobar el guion.")))
    return issues


def rhythm_issues(outline: DeckOutline, plan: AnalysisPlan, knowledge: Knowledge | None = None) -> list:
    """Avisos (no bloquean) cuando varias slides seguidas tienen la misma forma visual.

    No decide por el modelo: nombra las familias de otra forma en las que caben las mismas
    unidades, y él elige o explica por qué la repetición es buscada.
    """
    from .schemas import PlanValidationIssue

    knowledge = knowledge or Knowledge(ROOT)
    issues, run = [], []
    ignored = {"section", "closing"}

    def flush():
        if len(run) < RHYTHM_RUN:
            return
        look = CREATABLE[outline.slides[run[0]].family].look
        for index in run[RHYTHM_RUN - 1:]:
            slide = outline.slides[index]
            count = len(slide.units)
            options = []
            for family, spec in CREATABLE.items():
                if spec.look in ignored or spec.look == look or family == slide.family:
                    continue
                capacity = knowledge.capacity(spec.layout) if spec.unit else None
                if spec.unit and capacity and capacity.minimum <= count <= capacity.maximum:
                    options.append(family)
                elif not spec.unit and not count:
                    options.append(family)
            numbers = ", ".join(str(position + 1) for position in run)
            issues.append(PlanValidationIssue(
                source_slide_id=plan.slides[index].source_slide_id, code="deck_rhythm_repetitive",
                severity="warning",
                detail=(f"Las slides {numbers} usan la misma forma ({LOOKS[look].split(' (')[0]}). "
                        + (f"Con {count} unidades también caben: {', '.join(options)}. " if options else "")
                        + "Cambia la forma si el contenido lo permite, o explica por qué conviene repetirla."),
            ))

    for index, slide in enumerate(outline.slides):
        look = CREATABLE[slide.family].look
        if look in ignored or (run and CREATABLE[outline.slides[run[-1]].family].look != look):
            flush()
            run = []
        if look not in ignored:
            run.append(index)
    flush()
    return issues
