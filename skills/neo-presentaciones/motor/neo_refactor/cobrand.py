"""Co-marca: el logo del cliente junto al de NEO en todas las slides.

Cuando el plan marca una imagen del deck como logo del cliente (`asset_classes` →
`client_logo`), la marca de cada slide deja de ser solo el logo NEO y pasa a ser el bloque
NEO | cliente: el logo NEO en su caja canónica, un filete vertical y el logo del cliente a la
derecha, todos centrados en la misma línea. La portada y la despedida lo llevan centrado.

Las medidas salen de un solo lugar (`lockup`) para que el compositor, el brand shell, la
portada, la despedida y la auditoría hablen del mismo bloque. En el bloque va el logo «NEO» solo
(`brand.logo.cobrand`), sin «25 años»: NEO | 25 | cliente eran tres marcas seguidas (deck de cliente,
2026-11-19).

El logo también puede venir de afuera del deck (`redisenar --logo-cliente RUTA`, `from_file`): en
un deck de cliente estaba solo en un layout de la plantilla y hubo que meterlo a mano en una slide.
"""
from __future__ import annotations

import colorsys
import hashlib
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

from .schemas import Box

CLASS = "client_logo"
# Cómo va el logo del cliente en fondo oscuro (`redisenar --logo-cliente-oscuro`):
# «auto» lo decide `_own_background`; «original» lo deja igual; «invertir» pasa a blanco lo oscuro
# y neutro, aunque el logo traiga su propio bloque.
DARK_MODES = ("auto", "original", "invertir")
# Lado mayor de la miniatura con la que se analiza el logo (bordes y regiones oscuras).
_SAMPLE = 200
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
    dark: str             # variante para fondo oscuro (`dark_version`)
    aspect: float         # ancho / alto de la tinta
    shas: frozenset[str]  # md5[:10] de las imágenes del deck que son este logo
    # Franja del texto dentro del logo (arriba, abajo; fracción del alto) cuando el logo es un
    # isotipo más alto que su texto: el texto va con el alto del «NEO» y el isotipo sobresale.
    band: tuple[float, float] | None = None
    # Cómo quedó la variante oscura: «original» (el logo trae su fondo o bloque) o «invertido».
    dark_mode: str = "invertido"

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


def _dark_neutral(r: int, g: int, b: int) -> bool:
    """Negro o gris oscuro: el texto típico de un logo, lo que pasa a blanco en fondo oscuro."""
    _h, light, sat = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    return light < 0.45 and sat < 0.25


def _near_white(r: int, g: int, b: int, floor: int = 245) -> bool:
    return r >= floor and g >= floor and b >= floor


def _dark_variant(im: Image.Image) -> Image.Image:
    """El texto negro o gris de un logo se vuelve blanco; los colores de marca se conservan."""
    out = im.convert("RGBA").copy()
    px = out.load()
    for y in range(out.height):
        for x in range(out.width):
            r, g, b, a = px[x, y]
            if a and _dark_neutral(r, g, b):
                px[x, y] = (255, 255, 255, a)
    return out


def _clear_white(im: Image.Image) -> Image.Image:
    """Un logo opaco con fondo blanco (un JPG): el blanco que toca los bordes se vuelve
    transparente (relleno por inundación). En fondo oscuro, el rectángulo blanco quedaba a la
    vista y el texto, ya pasado a blanco, desaparecía dentro de él. El blanco encerrado (el ojo
    de una «A», un texto calado) se conserva."""
    rgba = im.convert("RGBA")
    if rgba.split()[3].getextrema()[0] < 250:
        return rgba  # ya trae transparencia
    # Máscara del casi blanco (240: tolera el ruido del JPG) que se inunda desde cada píxel blanco
    # del borde; lo inundado (128) es el fondo.
    r, g, b, _a = (channel.point(lambda v: 255 if v >= 240 else 0) for channel in rgba.split())
    mask = ImageChops.darker(ImageChops.darker(r, g), b)
    w, h = mask.size
    border = [(x, y) for x in range(w) for y in (0, h - 1)] + [(x, y) for y in range(h) for x in (0, w - 1)]
    for xy in border:
        if mask.getpixel(xy) == 255:
            ImageDraw.floodfill(mask, xy, 128)
    if not any(mask.getpixel(xy) == 128 for xy in border):
        return rgba
    alpha = mask.point(lambda v: 0 if v == 128 else 255)
    out = rgba.copy()
    out.putalpha(alpha)
    return out


def _clear_counters(im: Image.Image) -> Image.Image:
    """El blanco opaco encerrado por negro o gris (el ojo de una «o» en un JPG) se vuelve
    transparente. Al pasar el texto a blanco, ese blanco se fundía con la letra y la «o» quedaba
    como un óvalo lleno. El blanco encerrado por color (una letra blanca sobre un círculo rojo) se
    conserva, y un logo blanco sobre transparencia no se toca (su borde no cuenta como negro)."""
    rgba = im.convert("RGBA")
    # Solo se recorre la caja del blanco opaco que queda.
    r, g, b, a = (channel.point(lambda v: 255 if v >= 240 else 0) for channel in rgba.split())
    box = ImageChops.darker(ImageChops.darker(r, g), ImageChops.darker(b, a)).getbbox()
    if box is None:
        return rgba
    w, h = rgba.size
    px = rgba.load()
    out = rgba.copy()
    opx = out.load()

    def white(x: int, y: int) -> bool:
        p = px[x, y]
        return p[3] >= 250 and _near_white(*p[:3], floor=240)

    seen = bytearray(w * h)
    for y0 in range(box[1], box[3]):
        for x0 in range(box[0], box[2]):
            if seen[y0 * w + x0] or not white(x0, y0):
                continue
            seen[y0 * w + x0] = 1
            region, queue = [], deque([(x0, y0)])
            neutral = colored = 0
            while queue:
                x, y = queue.popleft()
                region.append((x, y))
                for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                    if not (0 <= nx < w and 0 <= ny < h) or seen[ny * w + nx]:
                        continue
                    if white(nx, ny):
                        seen[ny * w + nx] = 1
                        queue.append((nx, ny))
                        continue
                    pr, pg, pb, pa = px[nx, ny]
                    _h, light, sat = colorsys.rgb_to_hls(pr / 255, pg / 255, pb / 255)
                    if pa < 128 or light >= 0.9:
                        continue  # transparente o casi blanco: no dice qué lo encierra
                    if sat < 0.25:
                        neutral += 1
                    else:
                        colored += 1
            if neutral and neutral >= 0.8 * (neutral + colored):
                for x, y in region:
                    opx[x, y] = (*px[x, y][:3], 0)
    return out


def _largest_dark_region(px, w: int, h: int) -> tuple[int, tuple[int, int, int, int]] | None:
    """La mayor región conexa (4 vecinos) de píxeles opacos negros o grises: (píxeles, caja)."""
    dark = [[False] * w for _ in range(h)]
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            dark[y][x] = a >= 128 and _dark_neutral(r, g, b)
    seen = [[False] * w for _ in range(h)]
    best = None
    for y0 in range(h):
        for x0 in range(w):
            if not dark[y0][x0] or seen[y0][x0]:
                continue
            seen[y0][x0] = True
            queue, count = deque([(x0, y0)]), 0
            bx0, by0, bx1, by1 = x0, y0, x0, y0
            while queue:
                x, y = queue.popleft()
                count += 1
                bx0, by0, bx1, by1 = min(bx0, x), min(by0, y), max(bx1, x), max(by1, y)
                for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                    if 0 <= nx < w and 0 <= ny < h and dark[ny][nx] and not seen[ny][nx]:
                        seen[ny][nx] = True
                        queue.append((nx, ny))
            if best is None or count > best[0]:
                best = (count, (bx0, by0, bx1 + 1, by1 + 1))
    return best


def _own_background(im: Image.Image) -> bool:
    """¿El logo trae su propio fondo o bloque sólido? Entonces va igual sobre fondo oscuro.

    Pasar a blanco todo lo oscuro dejó blanco el bloque negro de un logo de cliente (deck de
    cliente): el texto amarillo quedó sobre blanco. Hay fondo propio si (a) el borde del logo,
    ya recortado a su tinta, es casi todo opaco y no blanco (≥ 90 % de sus píxeles), o (b) la
    mayor región oscura y neutra es un área llena (densidad ≥ 0.6 en su caja) que ocupa al menos
    el 10 % del logo. Las letras sueltas de un texto negro no llegan a ninguna de las dos.
    """
    rgba = im.convert("RGBA")
    scale = min(1.0, _SAMPLE / max(rgba.width, rgba.height))
    if scale < 1.0:
        # NEAREST no mezcla colores: un borde negro sigue negro y la transparencia, transparente.
        rgba = rgba.resize((max(1, round(rgba.width * scale)), max(1, round(rgba.height * scale))),
                           Image.Resampling.NEAREST)
    w, h = rgba.size
    px = rgba.load()
    border = {(x, y) for x in range(w) for y in (0, h - 1)} | {(x, y) for y in range(h) for x in (0, w - 1)}
    solid = sum(1 for x, y in border if px[x, y][3] >= 250 and not _near_white(*px[x, y][:3]))
    if solid >= 0.9 * len(border):
        return True
    region = _largest_dark_region(px, w, h)
    if region is None:
        return False
    count, (x0, y0, x1, y1) = region
    return count >= 0.6 * (x1 - x0) * (y1 - y0) and count >= 0.10 * w * h


def dark_version(im: Image.Image, mode: str = "auto") -> tuple[Image.Image, str]:
    """Variante para fondo oscuro y cómo quedó («original» o «invertido»). `mode`: `DARK_MODES`."""
    if mode == "original":
        return im.convert("RGBA"), "original"
    clear = _clear_white(im)
    if mode == "auto" and _own_background(clear):
        return clear, "original"
    return _dark_variant(_clear_counters(clear)), "invertido"


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


def prepare(images: list[tuple[str, str]], out_dir: str | Path, *, dark_mode: str = "auto",
            also: Iterable[str] = ()) -> ClientLogo | None:
    """`images`: (sha, ruta) de las imágenes que el plan marcó como logo del cliente.

    Se usa la de más resolución; las demás cuentan como el mismo logo (el deck suele traerlo en
    varios tamaños). Devuelve None si ninguna se puede leer. `dark_mode` (`DARK_MODES`): cómo
    se arma la variante para fondo oscuro (`dark_version`). `also`: más huellas del mismo logo.
    """
    if dark_mode not in DARK_MODES:
        raise ValueError(f"modo de logo oscuro desconocido: {dark_mode!r} (usa {', '.join(DARK_MODES)})")
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
    dark_im, result = dark_version(im, dark_mode)
    dark_im.save(dark)
    return ClientLogo(light=str(light), dark=str(dark), aspect=im.width / max(im.height, 1),
                      shas=frozenset(shas | {s[:10] for s in also}), band=_text_band(im), dark_mode=result)


def from_file(path: str | Path, out_dir: str | Path, *, dark_mode: str = "auto",
              also: Iterable[str] = ()) -> ClientLogo | None:
    """El logo del cliente desde una imagen suelta (`redisenar --logo-cliente RUTA`), sin que esté
    en ninguna slide. `also`: huellas de imágenes del deck que cuentan como el mismo logo."""
    sha = hashlib.md5(Path(path).read_bytes()).hexdigest()
    return prepare([(sha, str(path))], out_dir, dark_mode=dark_mode, also=also)


def from_classification(src, classification, out_dir: str | Path, *, path: str | Path | None = None,
                        dark_mode: str = "auto") -> ClientLogo | None:
    """El logo del cliente que marcó el plan, o None si el deck no lo trae.

    Con `path` (`redisenar --logo-cliente`) el bloque usa esa imagen aunque el plan marque otra:
    gana el flag. Las imágenes que marcó el plan siguen contando como el logo del cliente (la
    portada no las cambia por el logo NEO y el shell rearma el bloque del autor).
    """
    images = [(image.sha, image.path) for spec in src.slides for image in spec.images
              if classification.asset_classes.get(spec.index, {}).get(image.id) == CLASS]
    if path is not None:
        return from_file(path, out_dir, dark_mode=dark_mode, also=[sha for sha, _ in images])
    return prepare(images, out_dir, dark_mode=dark_mode) if images else None


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
