"""Contratos del motor. Todas las medidas en puntos (pt)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Box(BaseModel):
    x: float
    y: float
    w: float
    h: float

    @property
    def right(self) -> float:
        return self.x + self.w

    @property
    def bottom(self) -> float:
        return self.y + self.h

    def overlaps(self, other: "Box", tol: float = 0.5) -> bool:
        return not (
            self.right <= other.x + tol
            or other.right <= self.x + tol
            or self.bottom <= other.y + tol
            or other.bottom <= self.y + tol
        )

    def contains(self, other: "Box", tol: float = 0.5) -> bool:
        return (
            other.x >= self.x - tol
            and other.y >= self.y - tol
            and other.right <= self.right + tol
            and other.bottom <= self.bottom + tol
        )


# ---------------------------------------------------------------- deck original


class Run(BaseModel):
    text: str
    font: str | None = None
    size: float | None = None
    bold: bool | None = None
    italic: bool | None = None
    color: str | None = None
    hyperlink: str | None = None


class Paragraph(BaseModel):
    runs: list[Run] = Field(default_factory=list)
    align: str | None = None
    level: int = 0
    # Viñeta explícita del autor (`buChar`/`buAutoNum`): es formato, no texto.
    bullet: bool = False
    # Numeración automática del autor (`buAutoNum`): su esquema (`arabicPeriod`…) y su inicio.
    # Una lista numerada no es una de viñetas: «1. 2. 3.» salía como «• • •» (deck de inducción, 2026-11-02).
    numbering: str | None = None
    start_at: int | None = None
    # Margen izquierdo del párrafo (`marL`, pt): el texto corta a ese ancho menos.
    margin: float = 0.0

    @property
    def text(self) -> str:
        return "".join(r.text for r in self.runs)


class TextBlock(BaseModel):
    id: str
    name: str
    box: Box
    paragraphs: list[Paragraph]
    fill: str | None = None
    # Blanca, sin borde y con sombra exterior: la variante `white_card.shadowed` de la marca.
    shadowed: bool = False
    # Procedencia del XML: no se usa para redibujar, pero permite que el
    # manifiesto mantenga una identidad estable durante un trabajo.
    source_shape_id: int | None = None
    source_order: int | None = None

    @property
    def text(self) -> str:
        return "\n".join(p.text for p in self.paragraphs)


class ImageBlock(BaseModel):
    id: str
    name: str
    box: Box
    sha: str
    path: str
    crop: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)  # l, t, r, b
    source_shape_id: int | None = None
    source_order: int | None = None


class ChartSeries(BaseModel):
    name: str = ""
    values: list[float | None] = Field(default_factory=list)


class ChartData(BaseModel):
    """Datos de un gráfico nativo: lo que la integridad exige intacto. El estilo no entra."""

    chart_type: str
    title: str | None = None
    categories: list[str] = Field(default_factory=list)
    series: list[ChartSeries] = Field(default_factory=list)


class ShapeBlock(BaseModel):
    id: str
    name: str
    box: Box
    kind: str
    fill: str | None = None
    shadowed: bool = False
    # Gráfico nativo (2026-10-01: los únicos que se trabajan). Sigue siendo una forma `d…`
    # para no mover los ids de los planes, pero es contenido: nunca decorativo.
    chart: ChartData | None = None
    source_shape_id: int | None = None
    source_order: int | None = None


class SlideSpec(BaseModel):
    index: int
    hidden: bool = False
    texts: list[TextBlock] = Field(default_factory=list)
    images: list[ImageBlock] = Field(default_factory=list)
    shapes: list[ShapeBlock] = Field(default_factory=list)
    notes: str = ""

    def element_ids(self) -> set[str]:
        return {e.id for e in [*self.texts, *self.images, *self.shapes]}

    def text_by_id(self, id_: str) -> TextBlock:
        return next(t for t in self.texts if t.id == id_)

    def image_by_id(self, id_: str) -> ImageBlock:
        return next(i for i in self.images if i.id == id_)


class DeckSpec(BaseModel):
    source: str
    width: float
    height: float
    slides: list[SlideSpec]

    def slide(self, index: int) -> SlideSpec:
        return next(s for s in self.slides if s.index == index)


# ---------------------------------------------------------------- clasificación (la produce el host / LLM)

LayoutName = Literal[
    "section", "three_cards", "metrics_row",
    "card_grid", "item_list", "team_grid", "image_text", "circles", "closing",
    "matrix", "list_aside", "quadrant", "sections", "free",
]
CardRole = Literal["number", "title", "label", "body", "note"]
# `rule`: filas sin card, separadas por una línea fina (índices y listas de agenda).
CardStyle = Literal["outline", "header", "rule"]


class CardSlot(BaseModel):
    """Una unidad de texto con un rol por párrafo: tarjeta, fila, ficha o círculo."""

    text: str
    # `roles` cubre los párrafos no vacíos de `text` y luego los de `extra_texts`, en orden:
    # muchos decks traen el título y el cuerpo de una tarjeta en cajas separadas.
    roles: list[CardRole]
    extra_texts: list[str] = Field(default_factory=list)
    icon: str | None = None
    # Solo en fichas de equipo: la foto va arriba y forma un componente con nombre y rol.
    photo: str | None = None
    # Solo en bloques de imagen editorial (`block:N:image`): la imagen viaja con su bloque
    # cuando la slide se parte.
    image: str | None = None

    @property
    def text_ids(self) -> list[str]:
        return [self.text, *self.extra_texts]


class MetricSlot(BaseModel):
    value: str
    label: str | None = None
    description: str | None = None


class StripSlot(BaseModel):
    label: str | None = None
    items: list[str]


class SlideClassification(BaseModel):
    slide: int
    archetype: str
    layout: LayoutName
    # Familia del plan; viaja a la marca de la slide para que la auditoría la compruebe.
    family: str | None = None
    kicker: str | None = None
    # Obligatorio en casi todos los layouts; el cierre y la imagen editorial pueden no
    # tener título en el origen y no se inventa uno.
    title: str | None = None
    title_emphasis: str | None = None
    subtitle: str | None = None
    # `cards` sirve a three_cards, card_grid, item_list, team_grid y circles: todas son
    # unidades de texto con un rol por párrafo; el layout decide cómo se dibujan.
    cards: list[CardSlot] = Field(default_factory=list)
    metrics: list[MetricSlot] = Field(default_factory=list)
    strip: StripSlot | None = None
    banner: str | None = None
    # Imagen editorial: imágenes completas y bloques de mensaje junto a ellas.
    images: list[str] = Field(default_factory=list)
    # Fondo blanco de las capturas, gráficos y diagramas (D2, 0.2.0): en slides claras se quita
    # por defecto (`bg_clear.py`); "keep" lo conserva en esta slide. Nunca se quita en oscuras.
    image_background: Literal["clear", "keep"] = "clear"
    body: list[str] = Field(default_factory=list)
    # Roles por párrafo que el plan trae para una caja de `body` (el título y su lista en la
    # misma caja): id local → un rol por párrafo no vacío.
    body_roles: dict[str, list[CardRole]] = Field(default_factory=dict)
    # Variantes registradas en `visual_catalog.yaml` (`composition` de la familia).
    columns: int | None = None
    card_style: CardStyle = "outline"
    variant: str | None = None
    # Matriz: columna destacada (2.5), 1-based tal como se ve (la de rótulos cuenta como 1).
    # Cabecera en blue y celdas en blue_pale con alfa (`tokens.matrix.highlight_*`).
    highlight_column: int | None = Field(default=None, ge=1)
    # Plantilla para completar: los componentes crecen hasta ocupar el alto disponible.
    fill: bool = False
    # Piso de letra autorizado por la persona (`RuleException` min_font_size); None = el de marca.
    font_floor: float | None = None
    # Cambios de estilo pedidos por la persona (`StyleOverride`), aplicados al componer.
    style_overrides: list["StyleOverride"] = Field(default_factory=list)
    # Textos que la persona aprobó cambiar (un título corto): id local → `TextOverride`. El
    # motor los reemplaza antes de componer y la integridad compara el texto nuevo.
    text_overrides: dict[str, "TextOverride"] = Field(default_factory=dict)
    # Cita de la persona que aprobó juntar rótulos repetidos (cards → matriz): `verificar` no
    # bloquea una palabra que falta si sigue al menos una vez en la slide. Las cifras, sí.
    consolidate_labels: str | None = None
    # Composición libre (`layout: free`): el árbol de la gramática v1 y las unidades de sus
    # bloques compuestos que no son `card` (`quadrant`, `row`, `circle`, `block`).
    free_layout: "FreeLayout | None" = None
    free_units: dict[str, list[CardSlot]] = Field(default_factory=dict)
    # Íconos prestados de otra slide (F5b): id local en esta slide → elemento de origen (`s3:i2`).
    # El motor inyecta esas imágenes en la slide antes de componer.
    borrowed: dict[str, str] = Field(default_factory=dict)
    # Variante `template`: las cards ocupan al menos esta fracción del alto disponible.
    min_fill: float | None = None
    # Unidad destacada (1-based), p. ej. el cuadrante «alto valor · alta viabilidad».
    focus: int | None = None
    # Slots con nombre propios de cada layout (`tags`, `header`, `axis_x`, `panel`,
    # `list_title`, el resto de un `banner` de varias cajas…), en el orden del origen.
    named: dict[str, list[str]] = Field(default_factory=dict)
    # Grupos secundarios (paneles laterales `aside:N`): cajas libres + ícono opcional.
    groups: list[CardSlot] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    decorative: list[str] = Field(default_factory=list)
    brand: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _layout_slots(self) -> "SlideClassification":
        # El rango real vive en design_knowledge/layouts/*.yaml (`slots.<unidad>.count`)
        # y lo valida el puente con el catálogo; aquí solo se descarta lo absurdo.
        if self.layout == "three_cards" and not 2 <= len(self.cards) <= 3:
            raise ValueError(f"slide {self.slide}: three_cards admite 2 o 3 cards, llegaron {len(self.cards)}")
        if self.layout == "metrics_row" and not 2 <= len(self.metrics) <= 5:
            raise ValueError(f"slide {self.slide}: metrics_row requiere 2-5 métricas")
        if self.layout in ("card_grid", "item_list", "team_grid", "circles", "matrix", "list_aside",
                           "quadrant", "sections") and not self.cards:
            raise ValueError(f"slide {self.slide}: {self.layout} requiere al menos una unidad")
        # Una parte de una partición puede ser solo texto; la slide entera lleva imagen
        # (lo comprueba el puente con el plan completo).
        if self.layout == "image_text" and not (self.images or self.body or self.cards):
            raise ValueError(f"slide {self.slide}: image_text requiere imagen o mensaje")
        if self.title is None and self.layout not in ("image_text", "closing", "matrix"):
            raise ValueError(f"slide {self.slide}: {self.layout} requiere título")
        return self

    def assigned_ids(self) -> list[str]:
        ids = [*self.notes, *self.decorative, *self.brand, *self.images, *self.body]
        ids += [x for values in self.named.values() for x in values]
        for g in self.groups:
            ids += [*g.text_ids, *(x for x in (g.icon, g.photo, g.image) if x)]
        ids += [x for x in (self.title, self.kicker, self.subtitle, self.banner) if x]
        for c in [*self.cards, *(unit for units in self.free_units.values() for unit in units)]:
            ids += [*c.text_ids, *(x for x in (c.icon, c.photo, c.image) if x)]
        for m in self.metrics:
            ids += [x for x in (m.value, m.label, m.description) if x]
        if self.strip:
            ids += ([self.strip.label] if self.strip.label else []) + self.strip.items
        return ids


class DeckClassification(BaseModel):
    source: str
    slides: list[SlideClassification]
    # Slides conservadas (brand shell): formas (marcos, fondos) que el plan marcó como
    # decorativas y se retiran; índice de slide → `source_shape_id`. Nunca texto ni imagen.
    shell_decorative: dict[int, list[int]] = Field(default_factory=dict)
    # Función de cada imagen según el plan (fase 3): índice de slide → id local → clase.
    # El optimizador aplica la política de esa clase en vez de adivinar por el color.
    asset_classes: dict[int, dict[str, str]] = Field(default_factory=dict)
    # Slides que la persona pidió conservar con su layout y solo corregir de estilo:
    # índice de slide → familia del plan. Salen en brand shell encajado en el marco NEO.
    keep_layout: dict[int, str] = Field(default_factory=dict)
    # En esas slides, las imágenes que el plan marcó como marca (un logo antiguo que no está en
    # `known_logos`): se retiran, porque la marca vigente la pone el shell. Índice → shape ids.
    shell_brand: dict[int, list[int]] = Field(default_factory=dict)
    # Textos aprobados (`text_overrides`) de las slides que no se recomponen (keep_layout o no
    # seleccionadas): índice de slide → id local → `TextOverride`. Se reemplazan en el PPTX.
    shell_text_overrides: dict[int, dict[str, "TextOverride"]] = Field(default_factory=dict)


# ---------------------------------------------------------------- manifiesto y plan (MCP App)

# Estos contratos no reemplazan la clasificación heredada de los tres layouts.
# Describen el trabajo antes de componerlo y permiten rechazar un plan incompleto
# sin convertirlo en un ``brand_shell`` aparentemente aprobado.

ManifestElementKind = Literal["text", "image", "shape"]
ElementClassification = Literal["content", "decorative", "brand"]
DirectiveKind = Literal[
    "layout", "spacing", "emphasis", "image_treatment", "brand_placement", "split", "accessibility", "other"
]
CriterionKind = Literal[
    "content_integrity", "geometry", "render", "visual_quality", "style_integrity", "family", "custom"
]


class SourceRelationship(BaseModel):
    id: str
    kind: str
    target: str
    external: bool = False


class SourceElement(BaseModel):
    """Inventario de un elemento en la presentación fuente, sin editarla."""

    id: str
    local_id: str
    kind: ManifestElementKind
    name: str
    order: int
    source_shape_id: int | None = None
    box: Box
    text: str | None = None
    # Párrafos no vacíos tal como los compone el motor; `text` los une con saltos de línea
    # y no distingue un salto suave de un párrafo nuevo.
    paragraphs: list[str] = Field(default_factory=list)
    numbers: list[str] = Field(default_factory=list)
    image_hash: str | None = None
    hyperlinks: list[str] = Field(default_factory=list)
    chart: ChartData | None = None
    fingerprint: str


class SourceSlideManifest(BaseModel):
    id: str
    index: int
    visible: bool
    elements: list[SourceElement] = Field(default_factory=list)

    def element(self, element_id: str) -> SourceElement:
        return next(element for element in self.elements if element.id == element_id)
    notes: str = ""
    notes_hash: str
    relationships: list[SourceRelationship] = Field(default_factory=list)
    fingerprint: str


class SourceManifest(BaseModel):
    """Snapshot inmutable de la entrada; los paths locales no participan del contrato."""

    source_deck_id: str
    source_hash: str
    parser_version: str
    width: float
    height: float
    slides: list[SourceSlideManifest]

    def slide(self, source_slide_id: str) -> SourceSlideManifest:
        return next(slide for slide in self.slides if slide.id == source_slide_id)


class ElementAssignment(BaseModel):
    element_id: str
    classification: ElementClassification
    role: str | None = None
    # Solo aplica a slots de card de la ruta heredada. Mantiene un rol por
    # párrafo no vacío y no inventa texto para completar una card.
    paragraph_roles: list[CardRole] = Field(default_factory=list)


class VisualDirective(BaseModel):
    """Instrucción visual declarativa. Nunca contiene una operación de contenido."""

    kind: DirectiveKind
    instruction: str = Field(min_length=1, max_length=500)


class AcceptanceCriterion(BaseModel):
    id: str = Field(min_length=1)
    kind: CriterionKind
    description: str = Field(min_length=1, max_length=500)


class RuleException(BaseModel):
    """Regla de marca que la persona autorizó romper en una slide, dicho en el chat.

    Nunca la propone el modelo por su cuenta: `reason` cita lo que pidió la persona. Por ahora
    hay una: `min_font_size`, que deja bajar la letra hasta `min_pt` para que entre todo el
    contenido. El auditor la registra como excepción aprobada (aviso), no como fallo.
    """

    rule: Literal["min_font_size"]
    reason: str = Field(min_length=3, max_length=240)
    # Hasta 6 pt (2026-10-02): si la persona pide «letra 8» para una slide, se cumple; la marca
    # recomienda 11, pero la decisión explícita es suya y queda registrada como excepción.
    min_pt: float = Field(default=9.0, ge=6.0, le=11.0)


# Código de auditoría que cubre cada regla autorizable.
RULE_EXCEPTION_CODES = {"min_font_size": ("min_font_size",)}

# Peso pedido → familia de Montserrat registrada en la marca (`typography.allowed_families`).
FONT_WEIGHTS = {
    "regular": ("Montserrat", False), "medium": ("Montserrat Medium", False),
    "semibold": ("Montserrat SemiBold", False), "bold": ("Montserrat SemiBold", True),
    "extrabold": ("Montserrat ExtraBold", False), "black": ("Montserrat Black", False),
}
# Grupos de estilos que la persona nombra sin saber los roles internos.
STYLE_GROUPS = ("all", "titles", "text", "numbers")


class StyleOverride(BaseModel):
    """Cambio de estilo que la PERSONA pidió para una slide («el texto en Medium», «letra 13»).

    Se cumple tal cual mientras quede dentro de la línea gráfica: el peso es siempre una
    Montserrat de la marca y el color uno de la paleta de texto. `target` es un grupo
    (`all`, `titles`, `text`, `numbers`), un rol de `tokens.yaml → styles` (`card_body`) o un
    prefijo de roles (`card`). Un tamaño bajo el mínimo de marca queda como excepción aprobada.
    """

    target: str = Field(min_length=1, max_length=40)
    weight: Literal["regular", "medium", "semibold", "bold", "extrabold", "black"] | None = None
    size_pt: float | None = Field(default=None, ge=6.0, le=72.0)
    italic: bool | None = None
    color: Literal["navy", "blue", "blue_soft", "blue_pale", "white", "black", "separator_blue"] | None = None
    reason: str = Field(min_length=3, max_length=240)

    @model_validator(mode="after")
    def _something(self) -> "StyleOverride":
        if self.weight is None and self.size_pt is None and self.italic is None and self.color is None:
            raise ValueError("style_override sin cambios: indica weight, size_pt, italic o color")
        return self

    def matches(self, role: str) -> bool:
        if self.target == "all":
            return True
        is_title = role in ("title", "cover_title", "statement") or role.endswith("_title")
        is_number = role.endswith("_number") or role == "metric_value"
        if self.target == "titles":
            return is_title
        if self.target == "numbers":
            return is_number
        if self.target == "text":
            return not is_title and not is_number and role not in ("kicker",)
        return role == self.target or role.startswith(self.target + "_")


class TextOverride(BaseModel):
    """Texto que la PERSONA aprobó para un elemento (p. ej. el título corto que se le propuso).

    El motor reemplaza el texto del elemento antes de componer: conserva el formato del primer
    run y cada `\\n` abre un párrafo. La integridad saca de la comparación el texto viejo y
    exige el nuevo; el resto de la slide se verifica como siempre. `reason` cita la aprobación.
    """

    text: str = Field(min_length=1, max_length=2000)
    reason: str = Field(min_length=3, max_length=240)


# ---------------------------------------------------------------- composición libre
# Gramática v1: `design_knowledge/free_layout/grammar.md`. El modelo describe; el motor mide,
# dibuja y audita. Solo a pedido explícito de la persona (plans/composicion-libre.md).

FreeComponent = Literal[
    "card", "metric_card", "item_row", "step", "aside", "banner", "tag", "list_title",
    "image_message", "quadrant", "matrix", "worksheet", "circles",
]


class FreeBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")
    component: FreeComponent
    style: Literal["outline", "header", "rule", "card"] | None = None
    tone: Literal["light", "dark"] | None = None
    icon: Literal["auto", "top", "left", "header_right", "none"] | None = None
    # Numeración decorativa (decisión 2): «auto» usa la del autor; True la pone aunque no la haya.
    numbered: bool | Literal["auto"] | None = None
    # Roles que dibuja el bloque: `banner`, `aside:1`, `list_title`… o una familia entera (`aside`).
    units: list[str] = Field(default_factory=list)
    params: dict[str, float | int | str | bool | list[float]] = Field(default_factory=dict)


class FreeRepeat(BaseModel):
    """El mismo bloque para cada unidad (`card:1…N`): la pieza central de la gramática."""
    model_config = ConfigDict(extra="forbid")

    unit: Literal["card", "item", "metric", "aside"]
    columns: Literal["auto"] | int = "auto"
    order: Literal["row", "column"] = "row"
    max: int | None = Field(default=None, ge=1, le=12)
    max_rows: int | None = Field(default=None, ge=1, le=12)
    uniform: bool = True

    @model_validator(mode="after")
    def _columns(self) -> "FreeRepeat":
        if self.columns != "auto" and not 1 <= self.columns <= 4:
            raise ValueError("repeat.columns es «auto» o de 1 a 4")
        return self


class FreeNode(BaseModel):
    """Un nodo es exactamente uno de: bloque, repetición (con su bloque), fila o pila."""
    model_config = ConfigDict(extra="forbid")

    block: FreeBlock | None = None
    repeat: FreeRepeat | None = None
    row: list["FreeCell"] | None = None
    stack: list["FreeNode"] | None = None
    height: Literal["auto", "fill"] = "auto"
    optional: bool = False

    @model_validator(mode="after")
    def _one_kind(self) -> "FreeNode":
        kinds = [name for name in ("row", "stack") if getattr(self, name) is not None]
        if self.repeat is not None and self.block is None:
            raise ValueError("una repetición necesita su `block`")
        if self.block is not None or self.repeat is not None:
            kinds.append("repeat" if self.repeat is not None else "block")
        if len(kinds) != 1:
            raise ValueError(f"cada nodo es uno solo de block, repeat+block, row o stack (llegó: {kinds or 'nada'})")
        if self.row is not None:
            if not self.row:
                raise ValueError("una fila necesita al menos una celda")
            if sum(cell.span for cell in self.row) > 12:
                raise ValueError(f"la fila suma {sum(cell.span for cell in self.row)} columnas de 12")
        if self.stack is not None and not self.stack:
            raise ValueError("una pila necesita al menos un nodo")
        return self


class FreeCell(FreeNode):
    span: int = Field(ge=1, le=12)
    align: Literal["top", "center", "stretch"] = "stretch"


class FreeHeader(BaseModel):
    """Qué lleva el encabezado sale de los roles (kicker, title, subtitle, tags, title_note)."""
    model_config = ConfigDict(extra="forbid")

    title_style: Literal["title", "statement"] = "title"


class FreeLayout(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["light", "dark"] = "light"
    header: FreeHeader = Field(default_factory=FreeHeader)
    body: FreeNode
    # Acentos de marca sin contenido que la slide no tenía (por iniciativa propia, máximo 2).
    accents: list[Literal["accent_bar", "divider"]] = Field(default_factory=list, max_length=2)
    # La composición libre es solo a pedido explícito (decisión 3): el plan guarda la cita.
    reason: str | None = Field(default=None, max_length=240)


FreeNode.model_rebuild()
FreeCell.model_rebuild()


class SlidePlan(BaseModel):
    source_slide_id: str
    # Familia interna del deck (slides con la misma estructura). Un cambio de estilo se
    # decide por grupo: así no queda una slide huérfana con el estilo anterior.
    group_id: str | None = None
    family: str
    composition_layout: LayoutName | None = None
    archetype: str | None = None
    selected_for_redesign: bool = True
    # Partición por desborde: cada entrada es una slide de salida y lista las unidades
    # (`card:1`, `metric:3`) que le tocan, en el orden del origen. Vacío = una sola slide.
    # La política y sus condiciones están en `split.py`; aquí solo viaja la decisión.
    split_parts: list[list[str]] = Field(default_factory=list)
    assignments: list[ElementAssignment] = Field(default_factory=list)
    visual_directives: list[VisualDirective] = Field(default_factory=list)
    acceptance_criteria: list[AcceptanceCriterion] = Field(default_factory=list)
    exclusion_reason: str | None = None
    family_explanation: str | None = None
    # Decisión del clasificador (el modelo, con el texto y la imagen del original): cuánta
    # seguridad tiene, en qué se apoya y qué función cumple cada imagen. Solo las decisiones de
    # confianza baja llegan a la persona; `asset_classes` alimenta al optimizador (fase 3).
    confidence: Literal["high", "medium", "low"] | None = None
    evidence: str | None = Field(default=None, max_length=240)
    asset_classes: dict[str, str] = Field(default_factory=dict)
    # Fondo blanco de las capturas, gráficos y diagramas en slides claras: "clear" (por defecto)
    # lo quita; "keep" lo conserva en esta slide (D2, 0.2.0).
    image_background: Literal["clear", "keep"] = "clear"
    # Matriz: columna destacada, 1-based tal como se ve (la de rótulos cuenta como 1).
    highlight_column: int | None = Field(default=None, ge=1)
    rule_exceptions: list[RuleException] = Field(default_factory=list)
    style_overrides: list[StyleOverride] = Field(default_factory=list)
    # Textos que la persona aprobó cambiar: id del elemento (`s3:t1`) → `TextOverride`.
    text_overrides: dict[str, TextOverride] = Field(default_factory=dict)
    # Cita de la persona que aprobó juntar los rótulos repetidos de la slide (cards → matriz).
    consolidate_labels: str | None = Field(default=None, max_length=240)
    # Composición libre (`composition_layout: free`); None con cualquier layout del catálogo.
    free_layout: FreeLayout | None = None
    # F5b: diseño copiado de otra slide e íconos prestados de otra slide del mismo deck, solo a
    # pedido explícito de la persona (`copy_design.py`). Cada uno guarda la cita del pedido.
    copied_from: "CopiedDesign | None" = None
    borrowed_images: list["BorrowedImage"] = Field(default_factory=list)
    # «Mantén el layout, solo corrige el estilo»: la slide conserva su organización y recibe
    # la marca (brand shell + reglas de la referencia Taller 1 v7, encajada en el marco NEO). Es un
    # tratamiento aprobado, no un fallback: solo a pedido de la persona (2026-11-02).
    keep_layout: "KeepLayout | None" = None


class KeepLayout(BaseModel):
    """La persona pidió conservar la organización de la slide y corregir solo su estilo."""
    reason: str = Field(min_length=3, max_length=240)


class CopiedDesign(BaseModel):
    """De qué slide salió el diseño vigente y por qué (la cita del pedido de la persona)."""
    source_slide_id: str
    reason: str = Field(max_length=240)


class BorrowedImage(BaseModel):
    """Una imagen de otra slide del deck que esta slide muestra a pedido (un ícono prestado).

    No es contenido nuevo de esta slide ni contenido perdido de la de origen: la integridad lo
    sabe porque viaja aquí y no en `assignments`.
    """
    element_id: str            # elemento de origen, p. ej. `s3:i2`
    role: str                  # unidad de esta slide que lo lleva, p. ej. `card:1:icon`
    reason: str = Field(max_length=240)


SlidePlan.model_rebuild()


# `client_logo`: el logo del cliente; además de no tocarse, la marca de cada slide lo lleva junto al
# de NEO (`cobrand.py`).
ASSET_CLASSES = ("chart", "diagram", "photo", "illustration", "screenshot", "icon", "logo", "client_logo",
                 "background", "source")


class AnalysisPlan(BaseModel):
    source_deck_id: str
    source_hash: str
    design_version: str
    revision: int = Field(ge=1)
    slides: list[SlidePlan]


class PlanCommitment(BaseModel):
    id: str
    source_slide_id: str
    family: str
    criterion_ids: list[str] = Field(default_factory=list)


class PlanRevision(BaseModel):
    """Una revisión aprobada no se modifica; una corrección crea otra instancia."""

    id: str
    plan: AnalysisPlan
    commitments: list[PlanCommitment]
    status: Literal["draft", "approved", "superseded"] = "draft"
    parent_revision_id: str | None = None


class PlanValidationIssue(BaseModel):
    source_slide_id: str
    code: str
    detail: str
    severity: Literal["error", "warning"] = "error"


class PlanValidationResult(BaseModel):
    issues: list[PlanValidationIssue] = Field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)


class FamilyRecognition(BaseModel):
    """Resultado conservador: reconoce, pero no aprueba calidad ni composición."""

    source_slide_id: str
    family: str | None = None
    confidence: Literal["high", "ambiguous"]
    evidence: list[str] = Field(default_factory=list)
    requires_model: bool = True


class SourceOutputSlideMapping(BaseModel):
    """Destino de una slide fuente, incluso si en el futuro se divide en varias."""

    source_slide_id: str
    output_slide_indices: list[int] = Field(min_length=1)
    element_destinations: dict[str, list[int]] = Field(default_factory=dict)
    notes_output_indices: list[int] = Field(default_factory=list)
    relationship_output_indices: dict[str, list[int]] = Field(default_factory=dict)


class SourceOutputMapping(BaseModel):
    source_deck_id: str
    source_hash: str
    slides: list[SourceOutputSlideMapping]


class MappingValidationResult(BaseModel):
    issues: list[PlanValidationIssue] = Field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)


# ---------------------------------------------------------------- especificación renderizable


class RRun(BaseModel):
    text: str
    font: str
    size: float
    bold: bool = False
    italic: bool = False
    color: str
    hyperlink: str | None = None


class RPara(BaseModel):
    runs: list[RRun]
    align: Literal["l", "ctr", "r"] = "l"
    line: float = 1.0
    space_before: float = 0.0
    # Viñeta: el texto arranca `indent` pt a la derecha y la viñeta cuelga en la sangría.
    bullet: bool = False
    indent: float = 0.0
    # Numeración automática del autor (`buAutoNum`) en lugar de la viñeta.
    numbering: str | None = None
    start_at: int | None = None

    @property
    def text(self) -> str:
        return "".join(r.text for r in self.runs)


class RText(BaseModel):
    kind: Literal["text"] = "text"
    role: str
    box: Box
    paras: list[RPara]
    anchor: Literal["t", "ctr", "b"] = "t"
    group: str
    brand: bool = False
    sources: list[str] = Field(default_factory=list)


class RRect(BaseModel):
    kind: Literal["rect"] = "rect"
    role: str
    box: Box
    fill: str | None
    line: str | None = None
    line_width: float = 0.75
    radius: float = 0.0
    # `arrow`: flecha lineal (→) de la caja izquierda-centro a derecha-centro, color `line`.
    # `line`: línea recta del mismo trazo, sin punta (divisorias): un trazo de `line_width`
    # se dibuja igual en cualquier posición; un rectángulo de 0.75 pt no.
    shape: Literal["rect", "ellipse", "arrow", "line", "chevron", "diagonal"] = "rect"
    # Sombra exterior resuelta de `tokens.yaml` → `shadows` (color, blur_pt, distance_pt,
    # direction_deg, alpha_pct); None = sin sombra.
    shadow: dict | None = None
    group: str
    # Acento de marca sin contenido (composición libre): sale como `NEO_BRAND_<rol>`.
    brand: bool = False
    # Opacidad del relleno (0–1; la columna destacada de la matriz); None = opaco.
    alpha: float | None = None


class RPicture(BaseModel):
    kind: Literal["picture"] = "picture"
    role: str
    box: Box
    path: str
    crop: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    group: str
    brand: bool = False
    sources: list[str] = Field(default_factory=list)
    # Recorte circular (foto de ficha): la imagen ya viene recortada a cuadrado.
    # `arrow`: flecha lineal (→) de la caja izquierda-centro a derecha-centro, color `line`.
    shape: Literal["rect", "ellipse", "arrow"] = "rect"
    # Contorno de la foto (el aro azul de las fotos de persona); None = sin contorno.
    line: str | None = None
    line_width: float = 0.0


class RenderedSlide(BaseModel):
    source_index: int
    layout: str
    mode: Literal["light", "dark"]
    background: str
    elements: list[RText | RRect | RPicture]
    notes: str = ""
    compose_issues: list[str] = Field(default_factory=list)
    # Piso de letra con que se compuso (excepción autorizada); None = `typography.min_size`.
    font_floor: float | None = None


# ---------------------------------------------------------------- validación


class Issue(BaseModel):
    code: str
    severity: Literal["error", "warning"]
    detail: str


class SlideReport(BaseModel):
    slide: int
    mode: Literal["redesign", "brand_shell", "preserved", "hidden"]
    layout: str | None = None
    # Una partición produce varias slides de salida a partir de una de origen.
    parts: int = 1
    output_slides: list[int] = Field(default_factory=list)
    reason: str = ""
    score: int | None = None
    issues: list[Issue] = Field(default_factory=list)
    content_integrity: dict = Field(default_factory=dict)
    stats: dict = Field(default_factory=dict)
    # Textos aprobados que el motor aplicó: `{"id": "s3:t1", "original", "text", "reason"}`.
    # `verificar` los lee de aquí para sacarlos de la comparación.
    text_overrides: list[dict] = Field(default_factory=list)
    # Cita de la aprobación para juntar rótulos repetidos (la usa `verificar`).
    consolidate_labels: str | None = None


# `SlideClassification` nombra a `StyleOverride` y `TextOverride`, que se definen después.
SlideClassification.model_rebuild()
DeckClassification.model_rebuild()
