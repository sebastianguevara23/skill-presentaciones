# skill-presentaciones

Skill de Claude Code para hacer presentaciones con la línea gráfica de NEO Consulting:

- **Rediseñar** un PPTX (o un Google Slides descargado) con la marca NEO, sin tocar su
  contenido.
- **Crear** un deck o una plantilla desde un pedido o desde documentos.

Claude diseña con el motor de composición de NEO: arma la primera pasada con los diseños
establecidos de cada familia de slide (agenda, cards, cifras, pasos, equipo, imagen con
texto, portada y cierre), mira cada slide, corrige con código lo que haga falta y verifica
que el contenido esté completo antes de entregar. La persona ve cada paso en imágenes y
puede pedir cualquier cambio.

## Instalar

Requisito: **Node 18 o superior** (solo para instalar).

```bash
npx skills add https://github.com/sebastianguevara23/skill-presentaciones -g --skill neo-presentaciones --agent claude-code -y
```

La skill queda en `~/.claude/skills/neo-presentaciones/` y Claude Code la carga sola.

La primera vez que se usa, Claude revisa el equipo y, con permiso de la persona, instala lo
que falte:

- **uv** (trae Python y las librerías).
- **LibreOffice** (dibuja las slides para mirarlas).
- **Montserrat** (para el usuario, sin permisos de administrador).

Funciona en Windows, Mac y Linux, en la app de escritorio (pestaña Code) o en la terminal.

### Actualizar

Se vuelve a correr el mismo comando de instalación.

## Probar con otra persona

1. Que instale la skill con el comando de arriba.
2. Que abra Claude Code (la pestaña Code de Claude Desktop sirve) en una carpeta con un
   deck suyo y pida, con sus palabras:
   - «Rediseña `<deck>.pptx` con la marca NEO».
   - «Hazme una presentación de 6 slides sobre `<tema>` para `<público>`».
3. Para una prueba sin material propio: el deck `ejemplos/deck-de-prueba.pptx` de este repo.

Qué observar: si Claude muestra la cuadrícula del original y el plan antes de rediseñar,
si cada slide sale con el diseño de su familia, si corrige lo que no queda bien, si la
persona logra pedir cambios y si el contenido salió completo. El informe
`<deck>_entrega.json` deja las salvedades.

## Qué hay adentro

```
skills/neo-presentaciones/
  SKILL.md              cómo trabaja Claude con la skill
  references/           rediseñar, crear, marca, familias (con galería), reparar, Google, entorno
  scripts/neo.py        las herramientas (leer, redisenar, crear, mirar, revisar, verificar, entregar…)
  scripts/neo_skill/    entorno, plan, vista, inspección, preparación y ajustes probados
  motor/neo_refactor/   el motor de composición de NEO (ver motor/ORIGEN.md)
  design_knowledge/     tokens de marca, catálogo de familias y layouts
  assets/               Montserrat, logos y fondos de marca, galería de familias
ejemplos/               deck de prueba, su plan y un guion de ejemplo
tools/                  prueba de humo, pruebas por tema (pruebas/), galería y deck de prueba
plans/estado.md         dónde quedó el trabajo
```

## Mantenimiento

```bash
python3 tools/probar.py                                    # punta a punta (14) + tools/pruebas/ (138); --rapido salta las segundas
uv run --with pillow==12.3.0 python tools/generar-galeria.py   # regenera assets/galeria/
uv run --with python-pptx==1.0.2 --with pillow==12.3.0 python tools/crear-deck-de-prueba.py
```

- Todo en español neutro: código, comentarios, documentación y mensajes.
- Commits en Conventional Commits, en español: `tipo(ámbito): qué cambia`.
- Antes de subir, `tools/probar.py` en verde.
- **Privacidad:** el repo es público. No se nombran clientes en el código, los comentarios
  ni la documentación: las referencias de marca van como «Taller 1 v7» o «Referencia v2» y
  los casos como «deck de cliente» o «deck interno». Los decks de clientes no se versionan
  (`.gitignore` excluye `*.pptx`, salvo los ejemplos).

## Licencias

La fuente Montserrat (`skills/neo-presentaciones/assets/fonts/`) se distribuye con la SIL
Open Font License 1.1 (`OFL.txt` en esa carpeta). Los logos, fondos y la línea gráfica son
marca de NEO Consulting.
