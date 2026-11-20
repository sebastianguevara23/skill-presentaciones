"""Co-marca: el logo del cliente junto al de NEO en todas las slides.

Cuando el plan marca una imagen del deck como logo del cliente (`asset_classes` →
`client_logo`), la marca de cada slide deja de ser solo el logo NEO y pasa a ser el bloque
NEO | cliente: el logo NEO en su caja canónica, un filete vertical y el logo del cliente a la
derecha, todos centrados en la misma línea. La portada y la despedida lo llevan centrado.

Las medidas salen de un solo lugar (`lockup`) para que el compositor, el brand shell, la
portada, la despedida y la auditoría hablen del mismo bloque. En el bloque va el logo «NEO» solo
(`brand.logo.cobrand`), sin «25 años»: NEO | 25 | cliente eran tres marcas seguidas (deck de cliente,
2026-11-19).
"""
from __future__ import annotations

import colorsys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PIL import Image

from .schemas import Box

CLASS = "client_logo"
# Proporciones del bloque, en altos del logo NEO (19.3 pt en la caja canónica).
GAP = 0.55        # aire a cada lado del filete
RULE_H = 1.0      # alto del filete
# Alto del logo del cliente: un isotipo con texto en dos líneas lee más chico que el «NEO» del
# mismo alto. 1.42 es el tamaño que aprobó la persona en un deck de cliente (2026-11-19).
CLIENT_H = 1.42
RULE_W = 0.75     # grosor del filete (pt)


@dataclass(frozen=True)
class ClientLogo:
    light: str            # PNG recortado a su tinta, para fondo claro
    dark: str             # variante para fondo oscuro: lo oscuro y neutro (el texto) pasa a blanco
    aspect: float         # ancho / alto de la tinta
    shas: frozenset[str]  # md5[:10] de las imágenes del deck que son este logo
    # Franja del texto dentro del logo (arriba, abajo; fracción del alto) cuando el logo es un
    # isotipo más alto que su texto: el texto va con el alto del «NEO» y el isotipo sobresale.
    band: tuple[float, float] | None = None

    def path(self, mode: str) -> str:
        return self.dark if mode == "dark" else self.light

    def matches(self, sha: str | None) -> bool:
        return bool(sha) and sha[:10] in self.shas


@dataclass(frozen=True)
class Lockup:
    neo: Box
    rule: Box
    client: Box

    @property
    def box(self) -> Box:
        x0 = self.neo.x
        y0 = min(self.neo.y, self.rule.y, self.client.y)
        y1 = max(self.neo.bottom, self.rule.bottom, self.client.bottom)
        return Box(x=x0, y=y0, w=self.client.right - x0, h=y1 - y0)


def _ink_box(im: Image.Image) -> tuple[int, int, int, int] | None:
    """Caja de la tinta: lo opaco si hay transparencia; si no, lo que no es fondo blanco. Un halo
    casi transparente no es tinta: agrandaba la caja y el logo se veía más chico que su lugar."""
    rgba = im.convert("RGBA")
    alpha = rgba.split()[3]
    if alpha.getextrema()[0] < 250:
        return alpha.point(lambda a: 255 if a > 64 else 0).getbbox()
    gray = rgba.convert("L").point(lambda v: 255 if v < 245 else 0)
    return gray.getbbox()


def _dark_variant(im: Image.Image) -> Image.Image:
    """El texto negro o gris de un logo se vuelve blanco; los colores de marca se conservan."""
    out = im.convert("RGBA").copy()
    px = out.load()
    for y in range(out.height):
        for x in range(out.width):
            r, g, b, a = px[x, y]
            if a == 0:
                continue
            _h, light, sat = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
            if light < 0.45 and sat < 0.25:
                px[x, y] = (255, 255, 255, a)
    return out


def _text_band(im: Image.Image) -> tuple[float, float] | None:
    """Franja vertical del texto de un logo «isotipo + texto»: las dos partes que separa el hueco
    más ancho entre columnas; la más baja es el texto si mide menos del 85 % de la otra."""
    rgba = im.convert("RGBA")
    alpha = rgba.split()[3].point(lambda a: 255 if a > 64 else 0)
    w, h = alpha.size
    px = alpha.load()
    cols = [any(px[x, y] for y in range(0, h, 2)) for x in range(w)]
    runs, start = [], None
    for x, ink in enumerate(cols + [False]):
        if ink and start is None:
            start = x
        elif not ink and start is not None:
            runs.append((start, x))
            start = None
    if len(runs) < 2:
        return None
    gap, k = max((runs[i + 1][0] - runs[i][1], i) for i in range(len(runs) - 1))
    if gap < 0.02 * w:
        return None
    parts = [alpha.crop((runs[0][0], 0, runs[k][1], h)).getbbox(), alpha.crop((runs[k + 1][0], 0, runs[-1][1], h)).getbbox()]
    if None in parts:
        return None
    (_, t0, _, b0), (_, t1, _, b1) = parts
    tall, short = ((t0, b0), (t1, b1)) if b0 - t0 >= b1 - t1 else ((t1, b1), (t0, b0))
    if short[1] - short[0] >= 0.85 * (tall[1] - tall[0]) or short[1] - short[0] < 0.3 * h:
        return None
    return short[0] / h, short[1] / h


def prepare(images: list[tuple[str, str]], out_dir: str | Path) -> ClientLogo | None:
    """`images`: (sha, ruta) de las imágenes que el plan marcó como logo del cliente.

    Se usa la de más resolución; las demás cuentan como el mismo logo (el deck suele traerlo en
    varios tamaños). Devuelve None si ninguna se puede leer.
    """
    best: tuple[int, str, Image.Image] | None = None
    shas: set[str] = set()
    for sha, path in images:
        shas.add(sha[:10])
        try:
            im = Image.open(path)
            im.load()
        except (OSError, ValueError):
            continue
        area = im.width * im.height
        if best is None or area > best[0]:
            best = (area, sha[:10], im)
    if best is None:
        return None
    _area, sha, im = best
    ink = _ink_box(im)
    if ink:
        im = im.crop(ink)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    light, dark = out / f"client-logo-{sha}.png", out / f"client-logo-{sha}-dark.png"
    im.convert("RGBA").save(light)
    _dark_variant(im).save(dark)
    return ClientLogo(light=str(light), dark=str(dark), aspect=im.width / max(im.height, 1),
                      shas=frozenset(shas), band=_text_band(im))


def from_classification(src, classification, out_dir: str | Path) -> ClientLogo | None:
    """El logo del cliente que marcó el plan, o None si el deck no lo trae."""
    images = [(image.sha, image.path) for spec in src.slides for image in spec.images
              if classification.asset_classes.get(spec.index, {}).get(image.id) == CLASS]
    return prepare(images, out_dir) if images else None


def lockup(neo_box: Box, aspect: float, *, align: str = "left", band: tuple[float, float] | None = None) -> Lockup:
    """Bloque NEO | cliente con el logo NEO del alto de `neo_box`.

    `align`: «left» deja el logo NEO en `neo_box` (la caja canónica); «center» centra el bloque
    entero en el centro de `neo_box`; «right» apoya el bloque en el borde derecho de `neo_box`.
    `band` (`ClientLogo.band`): el texto del logo del cliente toma el alto del «NEO», arriba con
    arriba y base con base, y el isotipo sobresale; sin franja, el logo va centrado a `CLIENT_H`.
    Centrar un isotipo alto con su texto dejaba el logo corrido hacia abajo (deck de cliente).
    """
    h = neo_box.h
    cy = neo_box.y + h / 2
    client_h = h / (band[1] - band[0]) if band else h * CLIENT_H
    client_w = client_h * aspect
    total = neo_box.w + 2 * GAP * h + client_w
    if align == "center":
        x0 = neo_box.x + neo_box.w / 2 - total / 2
    elif align == "right":
        x0 = neo_box.right - total
    else:
        x0 = neo_box.x
    neo = Box(x=round(x0, 2), y=neo_box.y, w=neo_box.w, h=h)
    rule_x = x0 + neo_box.w + GAP * h
    rule = Box(x=round(rule_x, 2), y=round(cy - RULE_H * h / 2, 2), w=0.0, h=round(RULE_H * h, 2))
    client_y = neo_box.y - band[0] * client_h if band else cy - client_h / 2
    client = Box(x=round(rule_x + GAP * h, 2), y=round(client_y, 2),
                 w=round(client_w, 2), h=round(client_h, 2))
    return Lockup(neo=neo, rule=rule, client=client)


@lru_cache(maxsize=8)
def _aspect(path: str) -> float:
    with Image.open(path) as im:
        return im.width / im.height


def neo_logo(kn, mode: str) -> str:
    """El logo NEO del bloque de co-marca («NEO» solo, recortado a su tinta)."""
    return kn.path(kn.tokens["brand"]["logo"]["cobrand"]["dark" if mode == "dark" else "light"])


def neo_aspect(kn) -> float:
    return _aspect(neo_logo(kn, "light"))


def neo_box(kn, box: Box, align: str = "left") -> Box:
    """Caja del «NEO» del bloque con el alto de `box` (la caja del logo canónico), apoyada como
    pide `align`: a la izquierda de la caja, en su centro o en su borde derecho."""
    w = box.h * neo_aspect(kn)
    x = box.x + box.w / 2 - w / 2 if align == "center" else (box.right - w if align == "right" else box.x)
    return Box(x=round(x, 2), y=box.y, w=round(w, 2), h=box.h)


def elements(kn, client: ClientLogo, box: Box, mode: str, *, align: str = "left") -> list:
    """Logo NEO, filete y logo del cliente listos para el renderer (marca: `NEO_BRAND_*`).
    `box` es la caja del logo canónico: el bloque toma su alto y su apoyo."""
    from .schemas import RPicture, RRect

    parts = lockup(neo_box(kn, box, align), client.aspect, align=align, band=client.band)
    return [
        RPicture(role="brand_logo", box=parts.neo, path=neo_logo(kn, mode), group="brand", brand=True),
        RRect(role="cobrand_rule", box=parts.rule, fill=None, shape="line", line_width=RULE_W,
              line=kn.color("white" if mode == "dark" else "navy"), group="brand", brand=True),
        RPicture(role="client_logo", box=parts.client, path=client.path(mode), group="brand", brand=True),
    ]


def fit_width(kn, center: Box, aspect: float, width: float, band: tuple[float, float] | None = None) -> Box:
    """Caja del «NEO» para que el bloque completo mida `width` (portada), centrada en `center`."""
    na = neo_aspect(kn)
    ratio = 1 / (band[1] - band[0]) if band else CLIENT_H
    h = width / (na + 2 * GAP + ratio * aspect)
    cx, cy = center.x + center.w / 2, center.y + center.h / 2
    return Box(x=cx - na * h / 2, y=cy - h / 2, w=na * h, h=h)
