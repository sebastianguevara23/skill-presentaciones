# Rediseñar un deck

El deck llega como PPTX. Si está en Google Slides, la persona lo descarga con
Archivo → Descargar → Microsoft PowerPoint, o lo toma de su carpeta de Google Drive para
escritorio ([google.md](google.md)).

## 1. Leer

```bash
uv run "$NEO" leer "Deck.pptx" --out "Deck - NEO/lectura"
```

(`$NEO` es la ruta a `scripts/neo.py` de la skill.)

- `lectura.json` trae cada slide con sus elementos: `id` (`s3:t2` es texto, `s3:i1` es
  imagen), nombre, caja en pt, párrafos, gráficos y enlaces. Las ocultas se conservan tal
  cual y no llevan decisión.
- `grupo` marca slides con la misma estructura. Decide una y usa `apply_to_group` para que
  ninguna quede con otro estilo.
- Mira las cuadrículas (`original/cuadricula-N.png`) y muéstraselas a la persona. Para ver
  un gráfico o un texto chico, abre la PNG suelta de esa slide.

## 2. Decidir la familia de cada slide

Abre [familias.md](familias.md) y mira la galería. Elige por lo que el contenido **es**, no
por cómo está dibujado:

| El contenido es… | Familia |
|---|---|
| Portada | `title_slide` |
| Separador de sección | `section_divider` |
| Agenda o índice (lista de temas) | `table_of_contents` (variante `rows` para filas sin card) o `agenda_list` si trae una ilustración |
| 2-3 ideas paralelas | `three_cards` |
| 2-6 reglas, principios o tareas | `rules_cards` (cabecera navy) |
| 2-6 beneficios, herramientas o módulos | `benefits_content`, `tools_content` |
| Pasos o fases | `workflow_steps` |
| Hitos con año | `timeline` |
| Dos opciones a comparar | `paired_process` |
| Cifras o KPI | cualquier familia de cards con `composition_layout: metrics_row` |
| Lista con detalle (preguntas, puntos) | `table_of_contents` con variante `rows`, o `adr_framework` |
| Pasos + paneles de apoyo | `activity_guide` (layout `list_aside`, grupo `aside:N`) |
| 2-4 conceptos cortos | `three_unit_overview` (círculos) |
| Mensaje con imagen | `image_text_clients`; varias imágenes protagonistas: `image_heavy_special` |
| Personas | `team_grid` |
| Matriz comparativa (filas × columnas) | `comparison_matrix` |
| Matriz 2×2 | `priority_matrix` |
| Cierre | `closing_slide` (lo reemplaza la despedida canónica) |
| Gráfico nativo | déjala sin seleccionar (`selected: false`): conserva su lugar y el motor le aplica la marca a sus colores sin tocar los datos |

`catalogo` da los slots exactos de cada familia: `catalogo --familia rules_cards`.

### Preparar la estructura antes de asignar

El motor compone por unidades: una card, un ítem, una cifra. Si el original junta varias
unidades en una sola caja, sepáralas primero; si no, la slide no puede tomar su diseño:

```bash
uv run "$NEO" separar "Deck.pptx" --slide 2 --forma "TextBox 2" --numeros --out "Deck - NEO/preparado.pptx"
uv run "$NEO" leer "Deck - NEO/preparado.pptx" --out "Deck - NEO/lectura" --sin-imagenes
```

- `--numeros` saca el «1.», «02» o «a)» de cada ítem a su propio párrafo para asignarlo al
  rol `number`. El texto no cambia.
- Para varias slides, encadena `separar` sobre el mismo PPTX preparado.
- `separar` comprueba que el texto del preparado sea idéntico al del original
  (`texto_igual: true`). Desde ahí, el preparado es tu original: úsalo en `redisenar`,
  `verificar` y `entregar`, porque sus ids coinciden con el plan.

## 3. Escribir el plan

El plan es un JSON con una decisión por slide. Las slides que no nombres quedan intactas
(sirve para pedidos parciales: «solo la 4 y la 7»).

```json
[
  {"slide": 1, "family": "title_slide", "roles": {"s1:t1": "title", "s1:t2": "subtitle"}},
  {"slide": 2, "family": "table_of_contents",
   "roles": {"s2:t1": "title", "s2:t2": "item:1", "s2:t3": "item:2", "s2:t4": "item:3"},
   "paragraph_roles": {"s2:t2": ["number", "title"], "s2:t3": ["number", "title"], "s2:t4": ["number", "title"]}},
  {"slide": 3, "family": "three_cards",
   "roles": {"s3:t1": "title", "s3:t2": "card:1", "s3:t3": "card:2", "s3:t4": "card:3", "s3:t5": "decorative"},
   "paragraph_roles": {"s3:t2": ["title", "body"], "s3:t3": ["title", "body"], "s3:t4": ["title", "body"]}},
  {"slide": 4, "family": "benefits_content", "composition_layout": "metrics_row",
   "roles": {"s4:t1": "title", "s4:t2": "metric:1:value", "s4:t3": "metric:1:label",
             "s4:t4": "metric:2:value", "s4:t5": "metric:2:label"}},
  {"slide": 5, "family": "image_text_clients",
   "roles": {"s5:t1": "title", "s5:t2": "body", "s5:i1": "image:1"}, "asset_classes": {"s5:i1": "photo"}},
  {"slide": 6, "family": "closing_slide", "roles": {"s6:t1": "title"}}
]
```

### Roles

Cada texto e imagen va a un rol. Los marcos, fondos, flechas y adornos van a `decorative`;
el logo viejo de NEO, a `brand`. Lo que no asignes y tenga contenido aparece como aviso.

| Rol | Qué es |
|---|---|
| `title`, `subtitle`, `kicker` | Encabezado de la slide (el kicker es un antetítulo corto) |
| `banner` | Franja de texto destacada (familias de cards) |
| `note` | Nota o fuente al pie |
| `body` | Cuerpo suelto (familias con imagen) |
| `card:N`, `item:N`, `circle:N`, `member:N`, `row:N`, `quadrant:N` | La unidad N. Varias cajas pueden ir a la misma unidad |
| `card:N:icon`, `member:N:photo`, `block:N:image` | La imagen de esa unidad |
| `metric:N:value`, `metric:N:label`, `metric:N:description` | Piezas de una cifra (`metrics_row`) |
| `aside:N` | Panel de apoyo (`list_aside`) |
| `image:N` | Imagen editorial |
| `block:N` | Bloque de texto con su imagen en `image_text` (fija el orden de lectura) |
| `decorative`, `brand` | Se retira: no es contenido |

`paragraph_roles` da un rol por **párrafo no vacío** de la caja de una unidad: `number`,
`title`, `label`, `body` o `note`. Una card «Clientes / Unificar canales…» es
`["title", "body"]`.

### Otros campos

- `variant`: una variante registrada de la familia (`rows`, `four_card_row`, `two_by_two_cards`…).
- `composition_layout`: otro layout para la misma familia (`metrics_row`, `item_list`…).
- `split_parts`: parte la slide en varias. Ejemplo para 8 cards en dos slides:
  `[["card:1","card:2","card:3","card:4"],["card:5","card:6","card:7","card:8"]]`.
- `apply_to_group: true`: lleva la decisión a todas las slides de su grupo.
- `asset_classes`: qué es cada imagen: `photo`, `illustration`, `screenshot`, `diagram`,
  `chart`, `icon`, `logo`, `client_logo` o `source`. Las capturas, diagramas, gráficos e
  íconos no pierden detalle al optimizar. `client_logo` pone el logo del cliente junto al de
  NEO en todas las slides.
- `style_overrides`: pedidos de estilo de la persona (`{"target": "titles", "color": "blue",
  "reason": "pidió los títulos en azul"}`). `target`: `all`, `titles`, `text`, `numbers`, un
  rol (`card_body`) o un prefijo (`card`).
- `rule_exceptions`: solo si la persona lo pide; hoy, letra bajo el mínimo:
  `{"rule": "min_font_size", "min_pt": 9, "reason": "pidió que entre todo"}`.
- `keep_layout: "<cita de la persona>"`: conserva la organización original y le pone la
  marca. **Solo a pedido de la persona.**
- `free_layout`: composición libre con bloques de la marca, cuando la persona pide otra
  organización y ninguna familia la da. Gramática: `design_knowledge/free_layout/grammar.md`.
- `selected: false` con `exclusion_reason`: la slide queda como está (gráficos nativos).

## 4. Primera pasada

```bash
uv run "$NEO" redisenar "Deck - NEO/preparado.pptx" --plan "Deck - NEO/plan.json" --out "Deck - NEO/v1.pptx"
```

- Si el plan tiene un problema, la salida dice qué slide y qué falta. Corrige el plan y
  vuelve a correr.
- `no_cupieron`: slides que no entraron en su layout y salieron con la marca sobre su
  organización original. No las entregues así. Prueba otra familia o variante, pártelas, o
  corrígelas con código.
- Junto al PPTX quedan `v1_report.json` (el mapa de slides que usa `verificar`) y
  `v1_plan.json`.

## 5. Mirar, revisar y corregir

```bash
uv run "$NEO" mirar "Deck - NEO/v1.pptx" --out "Deck - NEO/vista-v1" --antes "Deck.pptx"
uv run "$NEO" revisar "Deck - NEO/v1.pptx"
```

Compara cada slide con su imagen de la galería. Lo que no esté a la altura lo corriges en
el plan (otra familia o variante) y vuelves a correr, o con código sobre una copia `v2.pptx`
([reparar.md](reparar.md)). Muéstrale a la persona el antes y después de las slides que
cambiaron.

## 6. Verificar y entregar

```bash
uv run "$NEO" verificar "Deck - NEO/preparado.pptx" "Deck - NEO/v3.pptx" --reporte "Deck - NEO/v1_report.json"
uv run "$NEO" entregar "Deck - NEO/preparado.pptx" "Deck - NEO/v3.pptx" --reporte "Deck - NEO/v1_report.json" --out "Deck - NEO/Deck NEO.pptx"
```

(Si no usaste `separar`, el original es el deck que llegó.)

- Pasa siempre el reporte de la pasada del motor de la que sale la versión: con él la
  verificación compara slide por slide.
- Si la verificación falla, corrige: un texto perdido se recupera, una cifra se restituye,
  una forma que tapa texto se mueve.
- `--nota "…"` deja salvedades en el informe (por ejemplo, una slide que conservó su
  organización a pedido de la persona).
