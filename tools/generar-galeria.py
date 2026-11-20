"""Genera `assets/galeria/`: una imagen por familia con su diseño establecido.

Arma un guion con texto neutro (sin material de cliente), lo crea con el motor y guarda cada
slide como `<familia>.jpg`, más variantes registradas que cambian la forma (filas, cifras).
Claude mira estas imágenes antes de elegir la familia de una slide.

Uso: uv run --with pillow==12.3.0 python tools/generar-galeria.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

RAIZ = Path(__file__).resolve().parents[1]
SKILL = RAIZ / "skills" / "neo-presentaciones"
NEO = SKILL / "scripts" / "neo.py"
DESTINO = SKILL / "assets" / "galeria"

U = lambda **k: {key: value for key, value in k.items() if value is not None}  # noqa: E731

SLIDES = [
    ("title_slide", {"title": "Programa de bienvenida 2027", "subtitle": "Guía para nuevos integrantes"}),
    ("section_divider", {"title": "Quiénes somos", "subtitle": "Nuestra forma de trabajar"}),
    ("table_of_contents", {"title": "Agenda", "units": [U(number=f"0{i}", title=t) for i, t in enumerate(
        ["Bienvenida", "Cómo trabajamos", "Herramientas", "Tu primer mes", "Preguntas"], 1)]}),
    ("adr_framework", {"title": "Componentes del marco", "units": [U(number=f"{i}", title=t) for i, t in enumerate(
        ["Contexto de la decisión", "Opciones evaluadas", "Decisión y motivo", "Consecuencias"], 1)]}),
    ("agenda_list", {"title": "Agenda del día", "body": "Bienvenida del equipo\nRecorrido por la oficina\n"
                     "Almuerzo de integración\nConfiguración de equipos", "images": 1}),
    ("three_cards", {"title": "Tres pilares de nuestro trabajo", "units": [
        U(number="01", title="Datos", body="Decisiones con información confiable y actualizada."),
        U(number="02", title="Personas", body="Equipos que aprenden y se acompañan."),
        U(number="03", title="Tecnología", body="Herramientas simples que ahorran tiempo.")]}),
    ("ai_maturity_levels", {"title": "Niveles de madurez", "units": [
        U(title="Inicial", body="Pruebas aisladas sin medición."),
        U(title="En desarrollo", body="Casos de uso con dueño y métrica."),
        U(title="Integrado", body="La IA es parte del proceso diario.")]}),
    ("rules_cards", {"title": "Acuerdos del equipo", "units": [
        U(title="Puntualidad", body="Las reuniones empiezan a la hora."),
        U(title="Transparencia", body="Los avances se comparten cada semana."),
        U(title="Respeto", body="Se escucha antes de opinar.")]}),
    ("benefits_content", {"title": "Beneficios", "units": [
        U(title="Horario flexible", body="Organiza tu jornada con tu equipo."),
        U(title="Formación", body="Cursos y certificaciones cada año."),
        U(title="Salud", body="Seguro médico desde el primer día."),
        U(title="Bienestar", body="Actividades y pausas activas.")]}),
    ("tools_content", {"title": "Herramientas que usarás", "units": [
        U(title="Correo y calendario", body="Toda la coordinación del día."),
        U(title="Documentos", body="Trabajo compartido en tiempo real."),
        U(title="Mensajería", body="Canales por proyecto y por equipo."),
        U(title="Asistentes de IA", body="Apoyo para redactar y analizar.")]}),
    ("timeline", {"title": "Nuestra historia", "units": [
        U(number="2001", title="Inicio", body="Primer equipo de consultores."),
        U(number="2010", title="Crecimiento", body="Nuevas oficinas y clientes."),
        U(number="2026", title="IA", body="Soluciones con inteligencia artificial.")]}),
    ("workflow_steps", {"title": "Tu primer mes", "units": [
        U(number="1", title="Semana 1", body="Bienvenida y accesos."),
        U(number="2", title="Semana 2", body="Acompañamiento en un proyecto."),
        U(number="3", title="Semana 3", body="Primeras tareas propias."),
        U(number="4", title="Semana 4", body="Revisión con tu líder.")]}),
    ("paired_process", {"title": "Dos formas de empezar", "units": [
        U(title="Proyecto", label="Con cliente", body="Te sumas a un equipo en curso y aprendes en la práctica."),
        U(title="Laboratorio", label="Interno", body="Desarrollas una prueba de concepto con acompañamiento.")]}),
    ("three_unit_overview", {"title": "Nuestras áreas", "units": [
        U(title="Estrategia"), U(title="Datos"), U(title="Tecnología")]}),
    ("key_metrics", {"title": "En cifras", "units": [
        U(number="25", label="años de trayectoria", body="Desde 2001."),
        U(number="+300", label="proyectos", body="En la región."),
        U(number="90 %", label="clientes recurrentes", body="Relaciones de largo plazo.")]}),
    ("detail_rows", {"title": "Preguntas frecuentes", "units": [
        U(number="1", title="¿Dónde pido accesos?", body="Mesa de ayuda, desde el primer día."),
        U(number="2", title="¿Quién es mi contacto?", body="Tu líder y tu compañero guía."),
        U(number="3", title="¿Cómo registro horas?", body="En la herramienta de proyectos."),
        U(number="4", title="¿Dónde están las plantillas?", body="En la carpeta compartida de marca.")]}),
    ("steps_aside", {"title": "Checklist de ingreso", "units": [
        U(number="1", title="Firmar documentos", body="Contrato y políticas."),
        U(number="2", title="Configurar equipo", body="Correo, VPN y accesos."),
        U(number="3", title="Conocer al equipo", body="Reunión de presentación."),
        U(number="4", title="Primer proyecto", body="Asignación y objetivos.")],
        "aside": ["Recursos\nGuía de marca y plantillas", "A quién preguntar\nTu compañero guía"]}),
    ("image_text_clients", {"title": "Lo que nos mueve", "body": "Ayudamos a las organizaciones a decidir "
                            "mejor con datos e inteligencia artificial.", "images": 1}),
    ("image_heavy_special", {"title": "Nuestra oficina", "body": "Espacios abiertos para colaborar.", "images": 3}),
    ("team_grid", {"title": "Tu equipo", "units": [
        U(title="Ana Pérez", label="Líder de proyecto"), U(title="Luis Gómez", label="Analista de datos"),
        U(title="María Ruiz", label="Consultora"), U(title="Jorge Díaz", label="Desarrollador")]}),
    ("closing_slide", {"title": "Gracias"}),
]


def correr(*args: str) -> dict:
    proc = subprocess.run(["uv", "run", "--quiet", str(NEO), *args], capture_output=True, text=True)
    if proc.returncode not in (0, 1):
        raise SystemExit(proc.stderr[-2000:] or proc.stdout[-2000:])
    return json.loads(proc.stdout)


def main() -> None:
    guion = {"title": "Programa de bienvenida 2027", "subtitle": "Guía para nuevos integrantes",
             "request": "galería de familias NEO con texto neutro",
             "slides": [{"family": fam, **datos} for fam, datos in SLIDES]}
    with tempfile.TemporaryDirectory(prefix="neo-galeria-") as tmp:
        tmp_p = Path(tmp)
        (tmp_p / "guion.json").write_text(json.dumps(guion, ensure_ascii=False), encoding="utf-8")
        creado = correr("--trabajo", str(tmp_p / ".neo"), "crear", str(tmp_p / "guion.json"),
                        "--out", str(tmp_p / "galeria.pptx"))
        if not creado.get("ok"):
            raise SystemExit(json.dumps(creado, ensure_ascii=False, indent=1))
        vista = correr("mirar", str(tmp_p / "galeria.pptx"), "--out", str(tmp_p / "png"), "--ancho", "1280")
        if DESTINO.exists():
            shutil.rmtree(DESTINO)
        DESTINO.mkdir(parents=True)
        salida = {int(Path(p).stem.split("-")[-1]): Path(p) for p in vista["imagenes"]}
        for fila in creado["slides"]:
            familia = SLIDES[fila["slide"] - 1][0]
            for n in fila["salida"] or []:
                if n in salida:
                    Image.open(salida[n]).convert("RGB").resize((960, 540), Image.LANCZOS).save(
                        DESTINO / f"{familia}.jpg", quality=86, optimize=True)
                    break
    print(sorted(p.name for p in DESTINO.iterdir()))


if __name__ == "__main__":
    main()
