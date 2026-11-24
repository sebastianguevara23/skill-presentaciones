"""Capturas sin fondo blanco (decisión D2 de la 0.2.0, deck de cliente, 2026-11-23).

Una captura, un gráfico o un diagrama pegado con su fondo blanco se ve como un recuadro
blanco sobre el fondo claro de la marca. Aquí se vuelve transparente ese fondo: un relleno
por inundación desde todos los bordes sobre lo casi blanco y opaco (todos los canales
≥ `umbral`). Solo lo que está conectado con el borde: el blanco encerrado por el contenido
(las celdas de una tabla con borde, el interior de una caja) se queda como está.

No se aplica (devuelve None) si la imagen ya trae transparencia, si no hay fondo que quitar
o si se quitaría más de `max_ratio` de la imagen (casi todo blanco: no es un fondo, es la
imagen). El composer lo usa solo en slides claras y para `screenshot`, `chart` y `diagram`.

Solo Pillow: el relleno avanza por tramos de fila (`bytearray.find`), no píxel a píxel, y
una captura de 1920 × 1080 se limpia en una fracción de segundo.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image, ImageChops

# Valores del mapa de trabajo: candidato (casi blanco), otro píxel y fondo ya rellenado.
_CAND, _OTHER, _FILLED = 0xFF, 0x00, 0x80
_ALPHA = bytes(0 if value == _FILLED else 255 for value in range(256))


def _has_transparency(im: Image.Image) -> bool:
    if im.mode in ("RGBA", "LA", "PA"):
        return im.getchannel("A").getextrema()[0] < 255
    if im.mode == "P" and "transparency" in im.info:
        return im.convert("RGBA").getchannel("A").getextrema()[0] < 255
    return "transparency" in im.info


def _run_end(m: bytearray, start: int, stop: int) -> int:
    """Fin (exclusivo) del tramo de candidatos que empieza en `start`, sin pasar de `stop`."""
    ends = [k for k in (m.find(b"\x00", start, stop), m.find(b"\x80", start, stop)) if k >= 0]
    return min(ends) if ends else stop


def _flood_from_edges(m: bytearray, w: int, h: int) -> int:
    """Rellena (con `_FILLED`) los candidatos conectados con el borde, en 4 vecinos.
    Devuelve la cantidad de píxeles rellenados."""
    stack: list[int] = []

    def seeds(start: int, stop: int) -> None:
        """Una semilla por tramo de candidatos dentro de [start, stop)."""
        i = m.find(b"\xff", start, stop)
        while i >= 0:
            stack.append(i)
            i = m.find(b"\xff", _run_end(m, i, stop), stop)

    seeds(0, w)
    seeds((h - 1) * w, h * w)
    for y in range(1, h - 1):
        for i in (y * w, y * w + w - 1):
            if m[i] == _CAND:
                stack.append(i)
    filled = 0
    while stack:
        i = stack.pop()
        if m[i] != _CAND:
            continue
        row = i - i % w
        left = max(m.rfind(b"\x00", row, i), m.rfind(b"\x80", row, i), row - 1) + 1
        right = _run_end(m, i, row + w)
        m[left:right] = bytes([_FILLED]) * (right - left)
        filled += right - left
        if row:
            seeds(left - w, right - w)
        if row + w < w * h:
            seeds(left + w, right + w)
    return filled


def _clear(im: Image.Image, umbral: int, max_ratio: float) -> tuple[Image.Image | None, str]:
    """(imagen sin fondo o None, motivo): `cleared`, `animated`, `transparent`, `nothing`, `too_much`."""
    if getattr(im, "n_frames", 1) > 1:
        return None, "animated"
    if _has_transparency(im):
        return None, "transparent"
    rgb = im.convert("RGB")
    w, h = rgb.size
    if not w or not h:
        return None, "nothing"
    near = [channel.point(lambda v: 255 if v >= umbral else 0) for channel in rgb.split()]
    mask = ImageChops.darker(ImageChops.darker(near[0], near[1]), near[2])
    m = bytearray(mask.tobytes())
    filled = _flood_from_edges(m, w, h)
    if not filled:
        return None, "nothing"
    if filled > max_ratio * w * h:
        return None, "too_much"
    out = rgb.convert("RGBA")
    out.putalpha(Image.frombytes("L", (w, h), bytes(m.translate(_ALPHA))))
    return out, "cleared"


def clear_white_background(imagen: Image.Image | str | Path, umbral: int = 245,
                           max_ratio: float = 0.7) -> Image.Image | None:
    """La imagen en RGBA con el fondo blanco transparente, o None si no corresponde.

    `imagen` puede ser una imagen de Pillow o una ruta. None: ya tiene transparencia, no
    se quitó nada, se quitaría más de `max_ratio` de los píxeles o es una GIF animada.
    """
    if isinstance(imagen, (str, Path)):
        with Image.open(imagen) as im:
            im.load()
            return _clear(im, umbral, max_ratio)[0]
    return _clear(imagen, umbral, max_ratio)[0]


def cleared_path(path: str | Path) -> Path:
    """Dónde se guarda la versión sin fondo de una imagen de la media del trabajo."""
    path = Path(path)
    return path.with_name(f"{path.stem}_sinfondo.png")


# Resultado por imagen en este proceso: el composer recompone una slide varias veces
# (compactación, otro ancho de imagen) y la limpieza se hace una sola vez.
_DONE: dict[str, tuple[str | None, str]] = {}
# Huella (md5, 10 caracteres, como `ImageBlock.sha`) de cada PNG sin fondo → la de su original:
# el optimizador le da a la imagen limpia la política de la clase del original (300 ppi y
# guarda de detalle para una captura), que si no se perdía con la huella nueva.
_SOURCE_SHA: dict[str, str] = {}


def _sha(path: str | Path) -> str:
    return hashlib.md5(Path(path).read_bytes()).hexdigest()[:10]


def source_sha(sha: str) -> str | None:
    """Huella del original de un PNG sin fondo escrito en este proceso (None si no es uno)."""
    return _SOURCE_SHA.get(sha)


def cleared_copy(path: str | Path, umbral: int = 245, max_ratio: float = 0.7) -> tuple[str | None, str]:
    """(ruta del PNG sin fondo junto a `path`, motivo). Lo escribe la primera vez; la ruta es
    None si no corresponde y el motivo dice por qué (ver `_clear`)."""
    key = f"{Path(path).resolve()}|{umbral}|{max_ratio}"
    if key not in _DONE:
        target = cleared_path(path)
        with Image.open(path) as im:
            im.load()
            out, reason = _clear(im, umbral, max_ratio)
        if out is not None:
            out.save(target, "PNG", optimize=True)
            _SOURCE_SHA[_sha(target)] = _sha(path)
        _DONE[key] = (str(target) if out is not None else None, reason)
    return _DONE[key]
