#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11,<3.14"
# dependencies = [
#   "python-pptx==1.0.2",
#   "pydantic==2.13.5",
#   "pillow==12.3.0",
#   "pyyaml==6.0.3",
#   "lxml==6.1.3",
#   "pymupdf==1.28.2",
# ]
# ///
"""Herramientas de la skill neo-presentaciones.

Uso: uv run <skill>/scripts/neo.py <comando> [opciones]

  preparar                 revisa LibreOffice, instala Montserrat y prueba un render
  leer DECK                texto e ids por slide + miniaturas del original
  catalogo                 familias, layouts y slots que el motor sabe componer
  redisenar DECK --plan P  aplica el plan con el motor (primera pasada)
  crear GUION              arma un deck nuevo desde un guion aprobado
  mirar PPTX               PNG por slide y cuadrículas (con --antes: antes/después)
  separar DECK --slide N   parte una lista de una caja en una caja por ítem (mismo texto)
  formas PPTX --slide N    formas de una slide con posición, letra y colores
  revisar PPTX             hallazgos de calidad y marca (informa, no bloquea)
  verificar ORIG CAND      el contenido sigue completo y visible
  entregar ORIG CAND       verifica, optimiza y escribe las salvedades

Todo imprime JSON en la salida estándar; los archivos quedan donde indique --out.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "motor"))
sys.path.insert(0, str(SKILL / "scripts"))

from neo_skill import entorno  # noqa: E402

entorno.exponer_soffice()


def _salida(data: dict, codigo: int = 0) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=1, default=str))
    raise SystemExit(codigo)


def _slides(texto: str | None) -> list[int] | None:
    if not texto:
        return None
    out: list[int] = []
    for parte in texto.split(","):
        a, _, b = parte.strip().partition("-")
        out += list(range(int(a), int(b) + 1)) if b else [int(a)]
    return out


def _trabajo(args) -> Path:
    ruta = Path(args.trabajo).expanduser() if args.trabajo else Path.cwd() / ".neo"
    ruta.mkdir(parents=True, exist_ok=True)
    return ruta


def _engine(args):
    from neo_refactor.engine import RefactorEngine

    return RefactorEngine(_trabajo(args))


def _reporte(pptx: Path) -> dict | None:
    ruta = pptx.with_name(pptx.stem + "_report.json")
    return json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else None


def _resumen_render(summary: dict) -> list[dict]:
    filas = []
    for r in summary.get("slides", []):
        if r.get("mode") == "hidden":
            continue
        codigos = sorted({i["code"] for i in r.get("issues", []) if i.get("severity") in ("error", "warning")})
        fila = {"slide": r["slide"], "modo": r.get("mode"), "layout": r.get("layout"),
                "salida": r.get("output_slides"), "avisos": codigos}
        if r.get("reason"):
            fila["motivo"] = r["reason"]
        ci = r.get("content_integrity") or {}
        if ci and not ci.get("preserved", True):
            fila["contenido"] = {"faltan": ci.get("removed_content", [])[:6], "sobran": ci.get("modified_content", [])[:6]}
        filas.append(fila)
    return filas


# ---------------------------------------------------------------- comandos

def cmd_preparar(args) -> None:
    info = entorno.resumen()
    info["fuentes"] = entorno.instalar_fuentes()
    info["montserrat_instalada"] = entorno.montserrat_instalada()
    prueba = SKILL / "assets" / "prueba-render.pptx"
    if info["libreoffice"] and prueba.exists():
        with tempfile.TemporaryDirectory(prefix="neo-prep-") as tmp:
            t0 = time.time()
            try:
                pdf = entorno.a_pdf(prueba, Path(tmp))
                fuentes = entorno.fuentes_del_pdf(pdf)
                info["render"] = {"ok": True, "segundos": round(time.time() - t0, 1), "fuentes_en_pdf": fuentes,
                                  "montserrat_en_pdf": any("Montserrat" in f for f in fuentes)}
            except Exception as exc:  # noqa: BLE001 - se informa tal cual
                info["render"] = {"ok": False, "error": str(exc)[:400]}
    listo = bool(info["libreoffice"]) and info.get("render", {}).get("montserrat_en_pdf", False)
    info["listo"] = listo
    if not listo:
        pasos = []
        if not info["libreoffice"]:
            pasos.append("Instalar LibreOffice: " + (info["como_instalar_libreoffice"] or "libreoffice.org"))
        elif not info.get("render", {}).get("montserrat_en_pdf"):
            pasos.append("Montserrat no llegó al render: cierra LibreOffice si está abierto y vuelve a correr preparar")
        info["pendiente"] = pasos
    _salida(info, 0 if listo else 1)


def cmd_leer(args) -> None:
    from neo_skill import vista

    deck = Path(args.deck)
    engine = _engine(args)
    analysis = engine.analyze(deck)
    manifest = analysis.manifest
    elegidas = set(_slides(args.slides) or [s.index for s in manifest.slides])
    sugeridas = {}
    try:
        for rec in engine.recognize_families(manifest):
            data = rec.model_dump()
            sid = data.get("source_slide_id")
            fam = data.get("family") or data.get("proposed_family")
            if sid and fam:
                sugeridas[sid] = fam
    except Exception:  # noqa: BLE001 - la sugerencia es opcional
        pass
    grupos = {sid: g.id for g in analysis.groups for sid in g.source_slide_ids}
    tam = {g.id: len(g.source_slide_ids) for g in analysis.groups}
    slides = []
    for s in manifest.slides:
        if s.index not in elegidas:
            continue
        elementos = []
        for e in s.elements:
            item = {"id": e.id, "tipo": e.kind, "nombre": e.name,
                    "caja_pt": [round(e.box.x, 1), round(e.box.y, 1), round(e.box.w, 1), round(e.box.h, 1)]}
            if e.paragraphs:
                item["parrafos"] = e.paragraphs
                from neo_skill.inspeccion import medida_titulo  # ¿cabe como título en una línea? (3.1)
                item.update(medida_titulo(e.paragraphs))
            elif e.text:
                item["texto"] = e.text
            if e.chart is not None:
                item["grafico"] = {"tipo": e.chart.chart_type, "categorias": e.chart.categories[:12],
                                   "series": [x.name for x in e.chart.series]}
            if e.hyperlinks:
                item["enlaces"] = e.hyperlinks
            elementos.append(item)
        fila = {"slide": s.index, "visible": s.visible, "elementos": elementos}
        if grupos.get(s.id) and tam.get(grupos[s.id], 1) > 1:
            fila["grupo"] = grupos[s.id]
        if s.id in sugeridas:
            fila["familia_sugerida"] = sugeridas[s.id]
        if s.notes:
            fila["notas"] = s.notes[:400]
        slides.append(fila)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    lectura = {"deck": str(deck), "lienzo_pt": [manifest.width, manifest.height], "slides_total": len(manifest.slides),
               "ocultas": [s.index for s in manifest.slides if not s.visible], "slides": slides}
    # Imágenes de layouts y masters: el logo del cliente puede estar solo en la plantilla.
    from neo_skill import plantilla
    lectura["plantilla"] = {"imagenes": plantilla.imagenes(deck, out)}
    candidatas = [i["archivo"] for i in lectura["plantilla"]["imagenes"] if i["candidata_client_logo"]]
    (out / "lectura.json").write_text(json.dumps(lectura, ensure_ascii=False, indent=1), encoding="utf-8")
    imagenes, hojas = [], []
    if not args.sin_imagenes:
        imagenes = vista.render(deck, out / "original", sorted(elegidas), ancho=args.ancho, prefijo="original")
        hojas = vista.cuadriculas(imagenes, out / "original", titulo="Slide")
    _salida({"lectura": str(out / "lectura.json"), "slides": len(slides), "ocultas": lectura["ocultas"],
             "cuadriculas": [str(h) for h in hojas], "imagenes": str(out / "original") if imagenes else None,
             "grupos_repetidos": sorted({f["grupo"] for f in slides if "grupo" in f}),
             "logo_cliente_en_plantilla": candidatas})


def cmd_catalogo(args) -> None:
    from neo_refactor.knowledge import ROOT, Knowledge
    from neo_refactor.outline import CREATABLE, LOOKS
    from neo_refactor.plan_adapter import layout_slots

    kn = Knowledge(ROOT)
    catalogo = kn.catalog["families"]
    familias = {}
    for nombre, entrada in sorted(catalogo.items()):
        if nombre == "hidden" or (args.familia and nombre != args.familia):
            continue
        comp = entrada.get("composition") or {}
        layout = comp.get("layout")
        dato = {"layout": layout, "variantes": entrada.get("allowed_variants") or [],
                "cuando": entrada.get("selection_conditions")}
        if layout and layout in kn.layouts:
            sl = layout_slots(kn, layout)
            dato["slots"] = {
                "unicos": sl.singular, "multiples": sorted(sl.multi),
                "unidad": sl.unit and {"rol": f"{sl.unit}:N", "min": sl.minimum, "max": sl.maximum,
                                       "roles_por_parrafo": sl.paragraph_roles, "piezas": list(sl.parts),
                                       "adjuntos": [f"{sl.unit}:N:{a}" for a in sl.attach]},
                "imagenes": sl.images and f"image:1..{sl.images}",
                "grupo": sl.group and {"rol": f"{sl.group}:N", "min": sl.group_minimum, "max": sl.group_maximum},
            }
        familias[nombre] = dato
    creables = {k: {"forma": LOOKS.get(v.look, v.look), "pista": v.hint} for k, v in CREATABLE.items()}
    _salida({"familias": familias, "layouts": sorted(kn.layouts), "creables_en_guion": creables})


def cmd_redisenar(args) -> None:
    from neo_refactor.engine import PlanRedesignBlocked
    from neo_skill import plan as plan_skill

    deck, out = Path(args.deck), Path(args.out)
    engine = _engine(args)
    if args.logo_cliente:
        # Logo del cliente que no está en ninguna slide (p. ej. el de la plantilla que lista `leer`):
        # va directo al bloque NEO | cliente de todas las slides y gana al que marque el plan.
        from PIL import Image

        logo = Path(args.logo_cliente).expanduser()
        try:
            with Image.open(logo) as im:
                im.load()
        except (OSError, ValueError):
            _salida({"ok": False, "error": f"--logo-cliente: no se puede leer la imagen {logo} (usa PNG o JPG)"}, 2)
        engine.client_logo_path = str(logo)
    engine.client_logo_dark = args.logo_cliente_oscuro
    manifest = engine.analyze(deck).manifest
    try:
        decisiones = plan_skill.cargar(Path(args.plan))
        plan, info = plan_skill.aplicar(engine, manifest, decisiones)
    except plan_skill.PlanError as exc:
        _salida({"ok": False, "error": str(exc)}, 2)
    errores = []
    for validacion in (engine.validate_plan(manifest, plan), engine.validate_render_plan(manifest, plan)):
        errores += [i.model_dump(exclude_none=True) for i in validacion.issues if i.severity == "error"]
    if errores:
        _salida({"ok": False, "error": "el motor no puede dibujar este plan; corrige estas slides y vuelve a correr",
                 "problemas": errores[:20]}, 2)
    bloqueadas = []
    try:
        summary = engine.redesign_plan(deck, plan, out, preserve_unselected=info["parcial"])
    except PlanRedesignBlocked as exc:
        summary = exc.report
        candidato = Path(summary["output"])
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(candidato, out)
        summary["output"] = str(out)
        out.with_name(out.stem + "_report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1))
        bloqueadas = summary.get("plan_blocked_slides", [])
    (out.with_name(out.stem + "_plan.json")).write_text(plan.model_dump_json(indent=1), encoding="utf-8")
    _salida({
        "ok": True, "salida": str(out), "reporte": str(out.with_name(out.stem + "_report.json")),
        "parcial": info["parcial"], "propagadas": info["propagadas"],
        "no_cupieron": bloqueadas,
        "nota_no_cupieron": ("Estas slides no cupieron en su layout y salieron con la marca sobre su organización "
                             "original (brand shell). Corrígelas: otro layout, partirlas, keep_layout o código.")
        if bloqueadas else None,
        "integridad_motor": summary.get("content_integrity"),
        "slides": _resumen_render(summary),
    })


def cmd_crear(args) -> None:
    from neo_refactor.engine import PlanRedesignBlocked
    from neo_refactor.outline import DeckOutline, build_pptx, check, plan_from_outline, with_cover

    guion = with_cover(DeckOutline.model_validate_json(Path(args.guion).read_text(encoding="utf-8")))
    problemas = check(guion)
    if problemas:
        _salida({"ok": False, "error": "el guion no se puede armar", "problemas": problemas}, 2)
    if not args.out and not args.medir:
        _salida({"ok": False, "error": "falta --out (o usa --medir para solo medir)"}, 2)
    out = Path(args.out) if args.out else _trabajo(args) / "medir" / "guion.pptx"
    out.parent.mkdir(parents=True, exist_ok=True)
    origen = out.with_name(out.stem + "_origen.pptx")
    built = build_pptx(guion, origen)
    engine = _engine(args)
    manifest = engine.analyze(built.path).manifest
    plan = plan_from_outline(guion, built, manifest, engine.default_plan(manifest))
    if args.medir:
        medida = engine.dry_compose(built.path, plan)
        no_caben = [s for s in medida.get("slides", []) if s.get("mode") != "redesign"]
        _salida({"ok": not no_caben, "no_caben": no_caben,
                 "nota": "Acorta esos textos o parte la slide en el guion antes de crear." if no_caben else
                 "Todo cabe: ya puedes crear."}, 0 if not no_caben else 1)
    bloqueadas = []
    try:
        summary = engine.redesign_plan(built.path, plan, out)
    except PlanRedesignBlocked as exc:
        summary = exc.report
        shutil.copy2(Path(summary["output"]), out)
        summary["output"] = str(out)
        out.with_name(out.stem + "_report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1))
        bloqueadas = summary.get("plan_blocked_slides", [])
    _salida({"ok": True, "salida": str(out), "origen": str(origen),
             "nota_origen": "El origen es el guion hecho PPTX: verifica contra él (neo.py verificar ORIGEN SALIDA).",
             "no_cupieron": bloqueadas, "slides": _resumen_render(summary)})


def cmd_mirar(args) -> None:
    from neo_skill import vista

    pptx, out = Path(args.pptx), Path(args.out)
    elegidas = _slides(args.slides)
    imagenes = vista.render(pptx, out, elegidas, ancho=args.ancho)
    hojas = vista.cuadriculas(imagenes, out, titulo="Slide") if len(imagenes) > 1 else []
    pares = []
    if args.antes:
        antes = Path(args.antes)
        reporte = _reporte(pptx) or {}
        mapa = {}
        for m in (reporte.get("source_output_mapping") or {}).get("slides", []):
            origen = int("".join(ch for ch in m["source_slide_id"] if ch.isdigit()))
            for i in m["output_slide_indices"]:
                mapa.setdefault(i, origen)
        indices_salida = [int(p.stem.split("-")[-1]) for p in imagenes]
        origenes = sorted({mapa.get(i, i) for i in indices_salida})
        previas = {int(p.stem.split("-")[-1]): p for p in vista.render(antes, out / "antes", origenes, ancho=args.ancho,
                                                                       prefijo="antes")}
        for img in imagenes:
            i = int(img.stem.split("-")[-1])
            o = mapa.get(i, i)
            if o in previas:
                pares.append(str(vista.antes_despues(previas[o], img, out / "antes-despues" / f"slide-{i:02d}.png",
                                                     f"slide {o} del original")))
    _salida({"imagenes": [str(p) for p in imagenes], "cuadriculas": [str(h) for h in hojas],
             "antes_despues": pares})


def cmd_separar(args) -> None:
    from neo_skill import preparar_deck

    try:
        _salida(preparar_deck.separar(Path(args.deck), args.slide, args.forma, Path(args.out), args.numeros))
    except ValueError as exc:
        _salida({"ok": False, "error": str(exc)}, 2)


def cmd_formas(args) -> None:
    from neo_skill import inspeccion

    _salida(inspeccion.formas(Path(args.pptx), args.slide))


def cmd_revisar(args) -> None:
    from neo_skill import inspeccion

    resultado = inspeccion.revisar(Path(args.pptx), _slides(args.slides))
    reporte = _reporte(Path(args.pptx))
    if reporte:
        resultado["motor"] = [f for f in _resumen_render(reporte) if f.get("avisos") or f.get("motivo")]
    _salida(resultado)


def _cierre() -> list[str]:
    from neo_refactor.knowledge import ROOT, Knowledge

    texto = Knowledge(ROOT).tokens.get("brand_rules", {}).get("closing", {}).get("text")
    return [texto] if texto else []


def cmd_verificar(args) -> None:
    from neo_skill import inspeccion

    original, candidato = Path(args.original), Path(args.candidato)
    reporte = json.loads(Path(args.reporte).read_text(encoding="utf-8")) if args.reporte else _reporte(candidato)
    resultado = inspeccion.verificar(original, candidato, reporte, _cierre())
    _salida(resultado, 0 if resultado["ok"] else 1)


def cmd_entregar(args) -> None:
    from pptx import Presentation

    from neo_refactor.optimize import optimize
    from neo_skill import inspeccion

    original, candidato, out = Path(args.original), Path(args.candidato), Path(args.out)
    reporte = json.loads(Path(args.reporte).read_text(encoding="utf-8")) if args.reporte else _reporte(candidato)
    verificacion = inspeccion.verificar(original, candidato, reporte, _cierre())
    if not verificacion["ok"] and not args.cambios_pedidos:
        _salida({"ok": False, "error": "el contenido no está completo o hay texto tapado: corrígelo, o si la "
                 "persona pidió cambiar el texto, entrega con --cambios-pedidos citando lo que pidió",
                 "verificacion": verificacion}, 1)
    out.parent.mkdir(parents=True, exist_ok=True)
    prs = Presentation(str(candidato))
    opt = optimize(prs)
    prs.save(str(out))
    revision = inspeccion.revisar(out)
    # Lo que la persona aprobó en el plan y `verificar` ya descontó sin abrir la verificación:
    # textos cambiados (`text_overrides`), rótulos juntados (`consolidate_labels`) e imágenes
    # tratadas (sin fondo blanco o recodificadas). Quedan a la vista en el informe.
    del_plan = {"textos_aprobados": verificacion.get("cambios_pedidos", []),
                "rotulos_consolidados": verificacion.get("rotulos_consolidados", []),
                "imagenes_tratadas": verificacion.get("imagenes_tratadas", [])}
    if not verificacion["ok"]:
        contenido = "con cambios pedidos por la persona"
    elif del_plan["textos_aprobados"] or del_plan["rotulos_consolidados"]:
        contenido = "completo, con los cambios aprobados en el plan"
    else:
        contenido = "completo"
    informe = {
        "archivo": str(out), "mb": round(out.stat().st_size / 1e6, 1), "optimizacion": opt,
        "contenido": contenido,
        "cambios_pedidos": args.cambios_pedidos, **del_plan, "verificacion": verificacion,
        "salvedades": revision["hallazgos"], "salvedades_por_codigo": revision["por_codigo"],
        "notas": args.nota or [],
    }
    ruta = out.with_name(out.stem + "_entrega.json")
    ruta.write_text(json.dumps(informe, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    _salida({"ok": True, "archivo": str(out), "mb": informe["mb"], "informe": str(ruta),
             "contenido": informe["contenido"], "salvedades_por_codigo": revision["por_codigo"],
             **{clave: len(valor) for clave, valor in del_plan.items() if valor}})


def main() -> None:
    ap = argparse.ArgumentParser(prog="neo.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--trabajo", help="carpeta de caché del motor (por defecto ./.neo)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("preparar").set_defaults(fn=cmd_preparar)

    p = sub.add_parser("leer")
    p.add_argument("deck")
    p.add_argument("--out", required=True)
    p.add_argument("--slides")
    p.add_argument("--ancho", type=int, default=960)
    p.add_argument("--sin-imagenes", action="store_true")
    p.set_defaults(fn=cmd_leer)

    p = sub.add_parser("catalogo")
    p.add_argument("--familia")
    p.set_defaults(fn=cmd_catalogo)

    p = sub.add_parser("redisenar")
    p.add_argument("deck")
    p.add_argument("--plan", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--logo-cliente", metavar="RUTA",
                   help="imagen del logo del cliente para el bloque NEO | cliente (gana al logo marcado en el plan)")
    p.add_argument("--logo-cliente-oscuro", choices=("auto", "original", "invertir"), default="auto",
                   help="logo del cliente en fondo oscuro: auto (conserva el logo si trae fondo o bloque propio), "
                        "original (siempre igual) o invertir (lo negro y gris pasa a blanco)")
    p.set_defaults(fn=cmd_redisenar)

    p = sub.add_parser("crear")
    p.add_argument("guion")
    p.add_argument("--out", help="PPTX de salida (no hace falta con --medir)")
    p.add_argument("--medir", action="store_true", help="solo mide qué cabe, sin generar")
    p.set_defaults(fn=cmd_crear)

    p = sub.add_parser("mirar")
    p.add_argument("pptx")
    p.add_argument("--out", required=True)
    p.add_argument("--slides")
    p.add_argument("--antes", help="PPTX original para armar antes/después")
    p.add_argument("--ancho", type=int, default=1280)
    p.set_defaults(fn=cmd_mirar)

    p = sub.add_parser("separar", help="una caja con varios párrafos → una caja por párrafo")
    p.add_argument("deck")
    p.add_argument("--slide", type=int, required=True)
    p.add_argument("--forma", required=True, help="nombre de la forma (de `leer`) o su id")
    p.add_argument("--numeros", action="store_true", help="saca el número inicial de cada ítem a su propio párrafo")
    p.add_argument("--out", required=True)
    p.set_defaults(fn=cmd_separar)

    p = sub.add_parser("formas")
    p.add_argument("pptx")
    p.add_argument("--slide", type=int, required=True)
    p.set_defaults(fn=cmd_formas)

    p = sub.add_parser("revisar")
    p.add_argument("pptx")
    p.add_argument("--slides")
    p.set_defaults(fn=cmd_revisar)

    p = sub.add_parser("verificar")
    p.add_argument("original")
    p.add_argument("candidato")
    p.add_argument("--reporte")
    p.set_defaults(fn=cmd_verificar)

    p = sub.add_parser("entregar")
    p.add_argument("original")
    p.add_argument("candidato")
    p.add_argument("--out", required=True)
    p.add_argument("--reporte")
    p.add_argument("--cambios-pedidos", help="cita de la persona si pidió cambiar el texto")
    p.add_argument("--nota", action="append", help="salvedad a dejar en el informe (repetible)")
    p.set_defaults(fn=cmd_entregar)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
