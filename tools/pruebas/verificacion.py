"""Pruebas de la verificación 0.2.0: imágenes tratadas, textos aprobados y rótulos consolidados.

Arma sus propios decks con python-pptx y pillow y corre `neo.py` como lo corre la skill:
- 0.1/0.2: una PNG recodificada, una JPEG y una con el fondo blanco vuelto transparente no
  hacen caer `verificar` y cuentan como `imagenes_tratadas`; una imagen distinta, o una a la
  que se le borró contenido, sigue faltando.
- 3.2: un título corto aprobado (`text_overrides`) pasa por el motor, `verificar` y `entregar`
  sin `--cambios-pedidos`; una palabra perdida en otro lugar de la misma slide sigue bloqueando.
- 2.5: con `consolidate_labels`, los rótulos juntados pasan como `rotulos_consolidados`; una
  cifra cambiada o una palabra que desaparece del todo siguen bloqueando.

Uso: uv run --with python-pptx==1.0.2 --with pillow==12.3.0 python tools/pruebas/verificacion.py
Sale con 1 si algo falla.
"""
from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw
from pptx import Presentation
from pptx.util import Inches, Pt

RAIZ = Path(__file__).resolve().parents[2]
NEO = RAIZ / "skills" / "neo-presentaciones" / "scripts" / "neo.py"
fallas: list[str] = []


def neo(*args: str, cwd: Path) -> tuple[int, dict]:
    proc = subprocess.run(["uv", "run", "--quiet", str(NEO), *args], capture_output=True, text=True, cwd=cwd)
    try:
        datos = json.loads(proc.stdout) if proc.stdout.strip() else {}
    except json.JSONDecodeError:
        datos = {}
    if not datos:
        datos = {"_salida": proc.stdout[-1500:], "_error": proc.stderr[-1500:]}
    return proc.returncode, datos


def comprobar(condicion: bool, mensaje: str, detalle: object = None) -> None:
    print(("ok   " if condicion else "FALLA") + " " + mensaje)
    if not condicion:
        fallas.append(mensaje)
        if detalle is not None:
            print("      " + json.dumps(detalle, ensure_ascii=False, default=str)[:1500])


# ---------------------------------------------------------------- fixtures

def _deck() -> Presentation:
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    return prs


def _caja(slide, texto: str, x: float, y: float, w: float = 3.5, h: float = 1.0, tam: int = 18, negrita=False):
    caja = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    caja.text_frame.word_wrap = True
    caja.text_frame.text = texto
    for p in caja.text_frame.paragraphs:
        for r in p.runs:
            r.font.size, r.font.bold = Pt(tam), negrita
    return caja


def _png(img: Image.Image, **kw) -> bytes:
    out = io.BytesIO()
    img.save(out, format="PNG", **kw)
    return out.getvalue()


def captura() -> Image.Image:
    """Una «captura» sintética: tablero con barras y renglones sobre fondo blanco."""
    img = Image.new("RGB", (480, 300), "white")
    d = ImageDraw.Draw(img)
    d.rectangle([20, 20, 460, 60], fill=(45, 91, 255))
    for k, alto in enumerate((150, 90, 190, 120, 60)):
        d.rectangle([40 + 80 * k, 270 - alto, 90 + 80 * k, 270], fill=(0, 0, 51))
    for k in range(4):
        d.line([30, 80 + 12 * k, 200, 80 + 12 * k], fill=(60, 60, 60), width=3)
    return img


def distinta() -> Image.Image:
    """Otra imagen del mismo tamaño y fondo blanco, con otro contenido."""
    img = Image.new("RGB", (480, 300), "white")
    d = ImageDraw.Draw(img)
    for k in range(3):
        d.ellipse([30 + 150 * k, 60, 150 + 150 * k, 180], fill=(240, 120, 20))
    d.rectangle([20, 220, 460, 280], fill=(200, 30, 60))
    return img


def sin_fondo(img: Image.Image) -> Image.Image:
    """El fondo blanco (conectado al borde) vuelto transparente, como hará `bg_clear`."""
    rgba = img.convert("RGBA")
    ImageDraw.floodfill(rgba, (0, 0), (255, 255, 255, 0), thresh=10)
    return rgba


def sin_contenido(img: Image.Image) -> Image.Image:
    """Las barras azules borradas a transparente: no es tratar la imagen, es perder contenido."""
    rgba = img.convert("RGBA")
    px = rgba.load()
    for x in range(rgba.width):
        for y in range(rgba.height):
            r, g, b, _a = px[x, y]
            if (b > 200 and r < 100) or (r, g, b) == (0, 0, 51):
                px[x, y] = (0, 0, 0, 0)
    return rgba


def deck_con_imagen(ruta: Path, blob: bytes) -> None:
    prs = _deck()
    s = prs.slides.add_slide(prs.slide_layouts[6])
    _caja(s, "Tablero de ventas de octubre", 0.6, 0.4, 10, 1, 28, True)
    s.shapes.add_picture(io.BytesIO(blob), Inches(1), Inches(1.8), Inches(6.4), Inches(4))
    prs.save(ruta)


def reporte_simple(ruta: Path, n_slides: int, extra: dict | None = None) -> None:
    """Reporte mínimo del motor: cada slide va a sí misma (lo que `verificar` usa del reporte)."""
    datos = {
        "source_output_mapping": {"slides": [
            {"source_slide_id": f"s{i}", "output_slide_indices": [i]} for i in range(1, n_slides + 1)]},
        "slides": [{"slide": i, "mode": "brand_shell", "content_integrity": {}, **(extra or {}).get(i, {})}
                   for i in range(1, n_slides + 1)],
    }
    ruta.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------- 0.1 y 0.2: imágenes tratadas

def prueba_imagenes(t: Path) -> None:
    base = captura()
    deck_con_imagen(t / "img-orig.pptx", _png(base))
    jpeg = io.BytesIO()
    base.save(jpeg, format="JPEG", quality=82)
    casos = {
        "recodificada": _png(base, compress_level=1),
        "jpeg": jpeg.getvalue(),
        "sin-fondo": _png(sin_fondo(base)),
        "distinta": _png(distinta()),
        "sin-contenido": _png(sin_contenido(base)),
    }
    for nombre, blob in casos.items():
        deck_con_imagen(t / f"img-{nombre}.pptx", blob)
    reporte_simple(t / "img-reporte.json", 1)
    for nombre in ("recodificada", "jpeg", "sin-fondo"):
        for modo, extra in (("por_slide", ["--reporte", "img-reporte.json"]), ("deck_completo", [])):
            codigo, r = neo("verificar", "img-orig.pptx", f"img-{nombre}.pptx", *extra, cwd=t)
            comprobar(codigo == 0 and r.get("ok") is True and r.get("modo") == modo,
                      f"verificar ({modo}): la imagen {nombre} no hace caer verificar y pasa", r)
            comprobar(len(r.get("imagenes_tratadas", [])) == 1 and r.get("imagenes_faltantes") == 0,
                      f"verificar ({modo}): la imagen {nombre} cuenta como tratada", r.get("imagenes_tratadas"))
    for nombre in ("distinta", "sin-contenido"):
        for modo, extra in (("por_slide", ["--reporte", "img-reporte.json"]), ("deck_completo", [])):
            codigo, r = neo("verificar", "img-orig.pptx", f"img-{nombre}.pptx", *extra, cwd=t)
            faltantes = (r.get("slides") or [{}])[0].get("imagenes_faltantes") if modo == "por_slide" \
                else r.get("imagenes_faltantes")
            comprobar(codigo == 1 and faltantes == 1 and not r.get("imagenes_tratadas"),
                      f"verificar ({modo}): la imagen {nombre} sigue faltando", r)


# ---------------------------------------------------------------- 3.2: textos aprobados en el motor

TITULO_LARGO = "Resultados del trimestre en los tres canales principales de la empresa"
TITULO_CORTO = "Resultados del trimestre por canal"
TITULO_SHELL = "Detalle operativo del mes con todas las áreas involucradas"
TITULO_SHELL_CORTO = "Detalle operativo\ndel mes"


def deck_textos(ruta: Path) -> None:
    prs = _deck()
    s1 = prs.slides.add_slide(prs.slide_layouts[6])
    _caja(s1, "Reporte mensual de prueba", 0.8, 2.5, 10, 1.2, 36, True)
    _caja(s1, "Octubre 2026", 0.8, 3.8, 6, 0.8, 20)
    s2 = prs.slides.add_slide(prs.slide_layouts[6])
    _caja(s2, TITULO_LARGO, 0.6, 0.4, 12, 1.2, 28, True)
    for k, (canal, cifra) in enumerate((("Buscadores", "12 %"), ("Redes", "8 %"), ("Correo", "5 %"))):
        _caja(s2, f"{canal}\nLas visitas crecieron {cifra} frente al mes anterior", 0.6 + 4.2 * k, 2.2, 3.8, 2.4)
    s3 = prs.slides.add_slide(prs.slide_layouts[6])
    _caja(s3, TITULO_SHELL, 0.6, 0.4, 12, 1.2, 28, True)
    _caja(s3, "Compras cerró 14 órdenes y Logística despachó 230 pedidos", 0.6, 2.2, 11, 1.5)
    prs.save(ruta)


def plan_textos(ruta: Path) -> None:
    plan = [
        {"slide": 1, "family": "title_slide", "roles": {"s1:t1": "title", "s1:t2": "subtitle"}},
        {"slide": 2, "family": "three_cards",
         "roles": {"s2:t1": "title", "s2:t2": "card:1", "s2:t3": "card:2", "s2:t4": "card:3"},
         "paragraph_roles": {"s2:t2": ["title", "body"], "s2:t3": ["title", "body"], "s2:t4": ["title", "body"]},
         "text_overrides": {"s2:t1": {"text": TITULO_CORTO, "reason": "la persona aprobó el título corto"}}},
        {"slide": 3, "keep_layout": "mantén el layout de esta slide",
         "text_overrides": {"s3:t1": {"text": TITULO_SHELL_CORTO, "reason": "aprobó el título corto en dos líneas"}}},
    ]
    ruta.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")


def _textos_de(pptx: Path, indice: int) -> list[str]:
    slide = Presentation(str(pptx)).slides[indice - 1]
    return [sh.text_frame.text for sh in slide.shapes if sh.has_text_frame and sh.text_frame.text.strip()]


def _quitar_palabra(origen: Path, destino: Path, indice: int, palabra: str) -> None:
    prs = Presentation(str(origen))
    for sh in prs.slides[indice - 1].shapes:
        if not sh.has_text_frame:
            continue
        for p in sh.text_frame.paragraphs:
            for r in p.runs:
                if palabra in r.text:
                    r.text = r.text.replace(palabra + " ", "", 1).replace(palabra, "", 1)
                    prs.save(destino)
                    return
    raise AssertionError(f"«{palabra}» no está en la slide {indice}")


def prueba_textos(t: Path) -> None:
    deck_textos(t / "textos.pptx")
    plan_textos(t / "plan-textos.json")
    codigo, red = neo("redisenar", "textos.pptx", "--plan", "plan-textos.json", "--out", "v1.pptx", cwd=t)
    comprobar(codigo == 0 and red.get("ok") is True, "redisenar: aplica el plan con text_overrides", red)
    if codigo != 0:
        return
    reporte = json.loads((t / "v1_report.json").read_text(encoding="utf-8"))
    por_slide = {s["slide"]: s for s in reporte["slides"]}
    cambios2 = por_slide[2].get("text_overrides") or []
    comprobar(cambios2 == [{"id": "s2:t1", "original": TITULO_LARGO, "text": TITULO_CORTO,
                            "reason": "la persona aprobó el título corto"}],
              "reporte: registra el título original y el nuevo de la slide rediseñada", cambios2)
    comprobar(por_slide[2]["mode"] == "redesign" and por_slide[2]["content_integrity"].get("preserved") is True
              and por_slide[2]["content_integrity"].get("requested_changes") == ["s2:t1"],
              "motor: su integridad compara el título nuevo y lo lista en requested_changes",
              {k: por_slide[2].get(k) for k in ("mode", "reason", "content_integrity")})
    cambios3 = por_slide[3].get("text_overrides") or []
    comprobar(por_slide[3]["mode"] == "brand_shell" and [c.get("text") for c in cambios3] == [TITULO_SHELL_CORTO]
              and por_slide[3]["content_integrity"].get("preserved") is True,
              "motor: aplica el texto aprobado en una slide con keep_layout", por_slide[3])
    salida2, salida3 = por_slide[2]["output_slides"][0], por_slide[3]["output_slides"][0]
    textos2 = _textos_de(t / "v1.pptx", salida2)
    comprobar(any(TITULO_CORTO in x for x in textos2) and not any(TITULO_LARGO in x for x in textos2),
              "v1: la slide rediseñada lleva el título corto", textos2)
    shell = Presentation(str(t / "v1.pptx")).slides[salida3 - 1]
    titulo = next((sh for sh in shell.shapes if sh.has_text_frame and sh.text_frame.text.startswith("Detalle")), None)
    parrafos = [p.text for p in titulo.text_frame.paragraphs] if titulo else []
    tamanos = {r.font.size for p in titulo.text_frame.paragraphs for r in p.runs} if titulo else set()
    comprobar(parrafos == ["Detalle operativo", "del mes"] and len(tamanos) == 1,
              "v1: en keep_layout el título se parte en dos párrafos con el formato del primer run",
              {"parrafos": parrafos, "tamanos": [str(x) for x in tamanos]})

    codigo, ver = neo("verificar", "textos.pptx", "v1.pptx", cwd=t)
    comprobar(codigo == 0 and ver.get("ok") is True and ver.get("modo") == "por_slide",
              "verificar: los textos aprobados no bloquean", ver)
    comprobar(sorted(c["id"] for c in ver.get("cambios_pedidos", [])) == ["s2:t1", "s3:t1"]
              and all(c.get("original") and c.get("nuevo") for c in ver.get("cambios_pedidos", [])),
              "verificar: lista los textos aprobados en cambios_pedidos", ver.get("cambios_pedidos"))

    codigo, ent = neo("entregar", "textos.pptx", "v1.pptx", "--out", "final.pptx", cwd=t)
    informe = json.loads((t / "final_entrega.json").read_text(encoding="utf-8")) if codigo == 0 else {}
    comprobar(codigo == 0 and ent.get("ok") is True, "entregar: pasa sin --cambios-pedidos", ent)
    comprobar(len(informe.get("textos_aprobados", [])) == 2 and informe.get("cambios_pedidos") is None,
              "entregar: el informe lista los textos aprobados", informe.get("textos_aprobados"))

    # Una palabra perdida en otro lugar de la misma slide sigue bloqueando.
    _quitar_palabra(t / "v1.pptx", t / "v1-roto.pptx", salida2, "visitas")
    codigo, ver = neo("verificar", "textos.pptx", "v1-roto.pptx", "--reporte", "v1_report.json", cwd=t)
    fila = next((s for s in ver.get("slides", []) if s.get("slide") == 2), {})
    comprobar(codigo == 1 and ver.get("ok") is False and "visitas" in fila.get("faltan", []),
              "verificar: con el título aprobado, una palabra perdida en la misma slide sigue bloqueando", ver)
    codigo, _ent = neo("entregar", "textos.pptx", "v1-roto.pptx", "--reporte", "v1_report.json",
                       "--out", "final-roto.pptx", cwd=t)
    comprobar(codigo == 1, "entregar: no pasa con una palabra perdida aunque haya textos aprobados")


# ---------------------------------------------------------------- 2.5: rótulos consolidados

def deck_rotulos(ruta: Path, cifras=("1.200", "980", "450"), rotulos=1, impresiones=True) -> None:
    """El original repite «Clics» en cada card; la matriz lo deja una vez como rótulo de fila."""
    prs = _deck()
    s = prs.slides.add_slide(prs.slide_layouts[6])
    _caja(s, "Comparativo de canales", 0.6, 0.4, 10, 1, 28, True)
    if rotulos > 1:  # el original: cards con el rótulo repetido
        for k, (canal, cifra) in enumerate(zip(("Buscadores", "Redes", "Correo"), cifras)):
            _caja(s, f"{canal}\nClics\n{cifra}" + ("\nImpresiones" if impresiones else ""), 0.6 + 4.2 * k, 2, 3.8, 2.5)
    else:  # la matriz: una fila de rótulo y una columna por canal
        _caja(s, "Clics" + ("\nImpresiones" if impresiones else ""), 0.6, 3, 2, 1.5)
        for k, (canal, cifra) in enumerate(zip(("Buscadores", "Redes", "Correo"), cifras)):
            _caja(s, f"{canal}\n{cifra}", 3 + 3.2 * k, 2, 3, 1.5)
    prs.save(ruta)


def prueba_rotulos(t: Path) -> None:
    deck_rotulos(t / "rot-orig.pptx", rotulos=3)
    deck_rotulos(t / "rot-matriz.pptx")
    deck_rotulos(t / "rot-cifra.pptx", cifras=("1.200", "990", "450"))
    deck_rotulos(t / "rot-sin-palabra.pptx", impresiones=False)
    aprobacion = "la persona aprobó pasar las cards a matriz"
    reporte_simple(t / "rot-con.json", 1, {1: {"consolidate_labels": aprobacion}})
    reporte_simple(t / "rot-sin.json", 1)

    codigo, r = neo("verificar", "rot-orig.pptx", "rot-matriz.pptx", "--reporte", "rot-sin.json", cwd=t)
    comprobar(codigo == 1, "verificar: sin consolidate_labels, los rótulos juntados bloquean", r)
    codigo, r = neo("verificar", "rot-orig.pptx", "rot-matriz.pptx", "--reporte", "rot-con.json", cwd=t)
    consolidados = (r.get("rotulos_consolidados") or [{}])[0]
    comprobar(codigo == 0 and r.get("ok") is True, "verificar: con consolidate_labels los rótulos juntados pasan", r)
    comprobar(sorted(consolidados.get("palabras", [])) == ["Clics", "Clics", "Impresiones", "Impresiones"]
              and consolidados.get("aprobacion") == aprobacion,
              "verificar: informa los rotulos_consolidados con la cita de la aprobación", consolidados)
    codigo, r = neo("verificar", "rot-orig.pptx", "rot-cifra.pptx", "--reporte", "rot-con.json", cwd=t)
    fila = (r.get("slides") or [{}])[0]
    comprobar(codigo == 1 and fila.get("cifras_cambiadas", 0) > 0,
              "verificar: con consolidate_labels, una cifra cambiada sigue bloqueando", r)
    codigo, r = neo("verificar", "rot-orig.pptx", "rot-sin-palabra.pptx", "--reporte", "rot-con.json", cwd=t)
    fila = (r.get("slides") or [{}])[0]
    comprobar(codigo == 1 and "Impresiones" in fila.get("faltan", []),
              "verificar: una palabra que desaparece del todo sigue bloqueando", r)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="neo-prueba-verificacion-") as tmp:
        t = Path(tmp)
        prueba_imagenes(t)
        prueba_textos(t)
        prueba_rotulos(t)
    if fallas:
        print(f"\n{len(fallas)} falla(s)")
        sys.exit(1)
    print("\ntodo en verde")


if __name__ == "__main__":
    main()
