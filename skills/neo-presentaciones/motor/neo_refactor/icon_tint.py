"""Íconos de un color: se repintan con el color de la marca.

Un ícono de contenido suele llegar del original como un glifo de un solo color sobre fondo
transparente (negro, gris, blanco). La paleta de la referencia Taller 1 v7 también manda en los íconos:
el glifo se repinta con el color del token y su forma (el canal alfa) queda tal cual. Los
íconos de varios colores (ilustraciones, logos a color), las imágenes sin transparencia y
los GIF animados no se tocan.

`same_glyph` reconoce después al ícono repintado: la integridad y la auditoría de contenido
lo cuentan como la misma imagen del origen, en otro color.
"""
from __future__ import annotations

import io
from pathlib import Path

from PIL import Image

# Un glifo deja ver el fondo: al menos esta fracción de la imagen es transparente.
MIN_TRANSPARENT = 0.15
# Píxeles del glifo (alfa ≥ 50 %) que pueden apartarse de su color dominante: bordes, ruido.
MAX_STRAY = 0.03
# Distancia por canal (0–255) dentro de la cual un píxel es del mismo color.
SAME_COLOR = 48
# Diferencia media del canal alfa (0–255), en miniatura, entre dos glifos de la misma forma.
SAME_SHAPE = 6.0


def _open(source: str | bytes) -> Image.Image:
    """Una imagen desde su ruta o desde sus bytes (la de una forma del PPTX)."""
    return Image.open(io.BytesIO(source) if isinstance(source, bytes) else source)


def _rgba(path: str | bytes) -> Image.Image | None:
    with _open(path) as image:
        if getattr(image, "n_frames", 1) > 1:
            return None
        image.seek(0)
        rgba = image.convert("RGBA")
    rgba.thumbnail((128, 128))
    return rgba


def glyph_color(path: str | bytes) -> str | None:
    """Color del glifo (hex) si la imagen es un ícono de un solo color sobre transparencia."""
    image = _rgba(path)
    if image is None:
        return None
    r, g, b, a = (channel.tobytes() for channel in image.split())
    total = len(a)
    clear = sum(1 for alpha in a if alpha < 16)
    solid = [(r[i], g[i], b[i]) for i in range(total) if a[i] >= 128]
    if clear < MIN_TRANSPARENT * total or len(solid) < 0.01 * total:
        return None
    base = sorted(solid, key=sum)[len(solid) // 2]
    stray = sum(1 for rgb in solid if max(abs(c - m) for c, m in zip(rgb, base)) > SAME_COLOR)
    if stray > MAX_STRAY * len(solid):
        return None
    return "{:02X}{:02X}{:02X}".format(*base)


def tint(path: str, color: str) -> str:
    """Ruta del glifo repintado en `color` (hex), con su canal alfa intacto.

    Devuelve la ruta original si la imagen no es un glifo de un color o si ya es de ese color:
    lo que no se repinta conserva sus bytes."""
    current = glyph_color(path)
    if current is None or _close(current, color):
        return path
    target = Path(path).with_name(f"{Path(path).stem}.tint-{color.lower()}.png")
    if not target.exists():
        _painted(path, color).save(target, optimize=True)
    return str(target)


def tint_bytes(blob: bytes, color: str) -> bytes | None:
    """Como `tint`, para la imagen de una forma: los bytes del PNG repintado, o None si no se
    repinta (no es un glifo de un color o ya es de ese color)."""
    current = glyph_color(blob)
    if current is None or _close(current, color):
        return None
    out = io.BytesIO()
    _painted(blob, color).save(out, format="PNG", optimize=True)
    return out.getvalue()


def _painted(source: str | bytes, color: str) -> Image.Image:
    with _open(source) as image:
        alpha = image.convert("RGBA").getchannel("A")
    rgb = tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))
    painted = Image.new("RGBA", alpha.size, (*rgb, 0))
    painted.putalpha(alpha)
    return painted


def same_glyph(source: str, candidate: str) -> bool:
    """¿`candidate` es el ícono `source` repintado? Misma forma (canal alfa) y un solo color."""
    a, b = _rgba(source), _rgba(candidate)
    if a is None or b is None or glyph_color(source) is None or glyph_color(candidate) is None:
        return False
    ratio_a, ratio_b = a.width / a.height, b.width / b.height
    if abs(ratio_a - ratio_b) > 0.03 * max(ratio_a, ratio_b):
        return False
    thumb_a = a.getchannel("A").resize((32, 32), Image.LANCZOS).tobytes()
    thumb_b = b.getchannel("A").resize((32, 32), Image.LANCZOS).tobytes()
    return sum(abs(x - y) for x, y in zip(thumb_a, thumb_b)) / len(thumb_a) <= SAME_SHAPE


def _close(a: str, b: str) -> bool:
    return max(abs(int(a[i:i + 2], 16) - int(b[i:i + 2], 16)) for i in (0, 2, 4)) <= 8
