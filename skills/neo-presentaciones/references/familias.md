# Familias de slide y su diseño establecido

Cada familia tiene un diseño aprobado. Antes de decidir, **mira la imagen** de la familia
(ábrela con tu herramienta de lectura de imágenes): es la vara contra la que se compara el
resultado. Las imágenes están en `assets/galeria/` y se generan con texto neutro
(`tools/generar-galeria.py` del repo).

Los slots exactos de cada una salen de `neo.py catalogo --familia <nombre>`.

## Navegación

| Familia | Imagen | Cuándo | Unidad y piezas |
|---|---|---|---|
| `title_slide` | [portada](../assets/galeria/title_slide.jpg) | Primera slide, siempre clara | `title` (con énfasis en blue al final), `subtitle` |
| `section_divider` | [separador](../assets/galeria/section_divider.jpg) | Cambio de sección, fondo oscuro | `title` (en una línea: la primera palabra en blanco y el resto en blue_pale, con la línea del separador debajo), `subtitle` |
| `table_of_contents` | [agenda](../assets/galeria/table_of_contents.jpg) | Agenda o índice | `item:N` (2-12) con `number`, `title`. Variante `rows`: filas con flecha, sin card |
| `agenda_list` | [agenda con imagen](../assets/galeria/agenda_list.jpg) | Agenda con una ilustración | `body` (un tema por párrafo) e `image:1` |
| `closing_slide` | [cierre](../assets/galeria/closing_slide.jpg) | Última slide | La reemplaza la despedida canónica |

## Cards

| Familia | Imagen | Cuándo | Unidad y piezas |
|---|---|---|---|
| `three_cards` | [tres cards](../assets/galeria/three_cards.jpg) | 2-3 ideas paralelas | `card:N` con `number`, `title`, `body`; ícono en `card:N:icon` |
| `ai_maturity_levels` | [niveles](../assets/galeria/ai_maturity_levels.jpg) | 3 niveles o etapas | `card:N` con `title`, `body` |
| `rules_cards` | [reglas](../assets/galeria/rules_cards.jpg) | Reglas, principios, tareas | `card:N` (2-6) con cabecera navy: `title` arriba, `body` abajo |
| `benefits_content` | [beneficios](../assets/galeria/benefits_content.jpg) | Beneficios, módulos | `card:N` (2-6). Variante `four_card_row` para 4 en fila |
| `tools_content` | [herramientas](../assets/galeria/tools_content.jpg) | Herramientas, recursos | `card:N` (2-6) en rejilla |
| `workflow_steps` | [pasos](../assets/galeria/workflow_steps.jpg) | Pasos o fases | `card:N` con `number`, `title`, `body`. Variante `two_by_two_cards` |
| `timeline` | [hitos](../assets/galeria/timeline.jpg) | Hitos con año | `card:N` con `number` (año), `title`, `body` |
| `paired_process` | [comparación](../assets/galeria/paired_process.jpg) | 2 opciones o perfiles | `card:N` con `title`, `label`, `body` (cabecera navy) |
| *cifras* | [cifras](../assets/galeria/key_metrics.jpg) | KPI, resultados | Familia de cards con `composition_layout: metrics_row`: `metric:N:value`, `metric:N:label`, `metric:N:description` (2-5) |

## Listas y paneles

| Familia | Imagen | Cuándo | Unidad y piezas |
|---|---|---|---|
| `adr_framework` | [lista](../assets/galeria/adr_framework.jpg) | Componentes, enumeraciones | `item:N` con `number`, `title` |
| *filas con detalle* | [filas](../assets/galeria/detail_rows.jpg) | Preguntas, puntos a aprobar | `table_of_contents` con variante `rows`: `item:N` con `number`, `title`, `body` |
| `activity_guide` | [pasos y paneles](../assets/galeria/steps_aside.jpg) | Programa + reglas, pasos + recursos | `item:N` (1-8) a la izquierda; `aside:N` (1-3) paneles navy a la derecha |
| `three_unit_overview` | [círculos](../assets/galeria/three_unit_overview.jpg) | 2-4 conceptos de una o dos palabras | `circle:N` con `title` |

## Imagen y personas

| Familia | Imagen | Cuándo | Unidad y piezas |
|---|---|---|---|
| `image_text_clients` | [imagen y mensaje](../assets/galeria/image_text_clients.jpg) | Un mensaje con 1-2 imágenes | `title`, `body` con barra de acento, `image:N`. Con un texto por foto: `block:N` y `block:N:image`. Con capturas, gráficos o diagramas sale en modo **imagen protagonista** (abajo) |
| `image_heavy_special` | [imágenes protagonistas](../assets/galeria/image_heavy_special.jpg) | 2-4 imágenes, texto corto | `body`, `image:N` |
| `team_grid` | [equipo](../assets/galeria/team_grid.jpg) | Personas | `member:N` (1-10) con `title` (nombre) y `label` (cargo); foto en `member:N:photo` |

### Imagen protagonista (capturas, gráficos y diagramas)

Cuando todas las imágenes de una slide `image_text` están marcadas como `screenshot`,
`chart` o `diagram` en `asset_classes`, el motor invierte el reparto:
- El texto va en una columna de 250 pt (500), o más angosta si ocupa menos.
- La imagen toma el resto del ancho sin deformarse.
- El bloque imagen + texto queda centrado en alto y en ancho, con los dos alineados arriba.
- En slide clara, además, la captura pierde el fondo blanco que toca el borde.

Las fotos siguen con el reparto de siempre: la imagen ocupa el 40 % del ancho.

Por eso **clasifica bien cada imagen**: una tabla o un gráfico pegado como imagen es
`screenshot` o `chart`, no `photo`. Si no, sale chico e ilegible.

## Matrices (sin imagen en la galería)

| Familia | Cuándo | Unidad y piezas |
|---|---|---|
| `comparison_matrix` | Filas × columnas (comparativas, criterios) | `header` (cabeceras), `row:N` (1-8). `highlight_column: N` destaca una columna (cabecera blue, celdas blue_pale al 45 %). La tabla se centra en el alto de la zona |
| `priority_matrix` | Matriz 2×2 | `quadrant:N` (4), `axis_x`, `axis_y`, `panel` |

## Antipatrones

- **Card huérfana:** con 4 cards, `rules_cards` y `timeline` salen 3+1 en cualquier
  variante (probado). Para 4 usa `benefits_content` con `four_card_row` (fila de 4),
  `tools_content` (2×2) o `workflow_steps` con `two_by_two_cards` (2×2). Si hace falta la
  cabecera navy de `rules_cards`, reacomoda las cards a 2×2 con código (receta en
  [reparar.md](reparar.md)).
- **Lista en una sola caja:** queda como lista plana. Sepárala (`separar --numeros`) y usa
  `table_of_contents` o `adr_framework`.
- **`keep_layout` como atajo:** solo pone la marca encima y no da el diseño de la familia.
  Es solo para cuando la persona pide conservar su organización.
- **Texto largo en círculos:** los círculos son para una o dos palabras. Si hay frases,
  usa cards.
- **Cards chicas con mucho aire debajo:** agranda el bloque para que ocupe la zona de
  contenido o pasa a una variante con menos columnas.
- **Imagen deformada o pixelada:** recorta para llenar el marco; nunca la estires.
- **Fotos en el lugar de íconos:** una foto en `card:N:icon` sale del tamaño de un ícono.
  Usa `image_text` con `block:N` y `block:N:image`.
- **Cards que repiten los mismos rótulos:** si 4 cards repiten cada una «Clics / Impresiones
  / CTR…», se leen mejor como `comparison_matrix`: una columna por card, una fila por rótulo
  y `highlight_column` en la que importa. Propónselo a la persona. Al juntar los rótulos
  repetidos el texto cambia de forma, así que va solo con su sí y con `consolidate_labels`
  citándolo ([redisenar.md](redisenar.md)).
- **Captura clasificada como foto:** sale al 40 % del ancho e ilegible. Márcala como
  `screenshot`, `chart` o `diagram` para que tome el modo imagen protagonista.
- **Achicar la letra para que entre:** primero parte la slide (`split_parts`). Bajar del
  mínimo solo a pedido de la persona.
