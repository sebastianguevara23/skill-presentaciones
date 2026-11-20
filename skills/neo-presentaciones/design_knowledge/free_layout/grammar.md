# Gramática de composición libre — v1 (F0–F1, 2026-10-02)

Esquema: `schemas.py` (`FreeLayout`, estricto: un campo desconocido se rechaza). Validación:
`free_layout.py` (guardas de marca y que cada rol de contenido quede en exactamente un bloque).

Plan: `plans/composicion-libre.md`. Ejemplos que la gramática debe expresar: `examples/`
(6 layouts del catálogo y 4 slides aprobadas de la referencia Taller 1 v7). En F1 esos ejemplos
pasan a ser fixtures de test.

Solo a pedido explícito de la persona (decisión 3). El modelo describe; el motor mide, dibuja,
compacta o parte, y audita.

## Estructura

```text
free_layout
  mode:    light | dark                       # el fondo y la paleta salen de la marca
  header:  {title_style: title | statement}   # qué lleva sale de los roles: kicker, title,
                                              # subtitle, tags (arriba a la derecha), title_note
                                              # (nota corta a la derecha del título)
  body:    Nodo
  accents: [accent_bar | divider]             # máx. 2, sin contenido
  (el pie es el rol note, como en todos los layouts)

Nodo  := Bloque | Repetición | Fila | Pila
Fila  := row:   [Celda…]          # columnas en una rejilla de 12 dentro del área segura (45–675 pt)
Celda := {span: 1–12, align: top | center | stretch} + Nodo
Pila  := stack: [Nodo…]           # de arriba hacia abajo
Repetición := repeat: {unit, columns: auto | 1–4, order: row | column, max, max_rows, uniform}
              + block: Bloque     # el mismo bloque para cada unidad (card:1…N, item:1…N…)
Bloque := {component, style, tone, icon, numbered, units, params}

En cualquier Nodo: height: auto | fill  ·  optional: true (si no hay contenido, no ocupa lugar)
```

## Bloques

Dos clases. Los **simples** se dibujan por unidad dentro de su celda; los **compuestos** traen su
propio comportamiento adaptativo y se dibujan enteros dentro de la caja que les toca.

| Bloque | Clase | Contenido | Parámetros | Hoy existe en |
|---|---|---|---|---|
| `card` | simple | roles number/title/label/body/note, ícono | `style: outline \| header \| rule`, `icon: auto \| top \| left \| header_right \| none` | three_cards, card_grid |
| `metric_card` | simple | value, label, description | — | metrics_row |
| `item_row` | simple | roles de la unidad | `style: card \| rule` | item_list |
| `step` | simple | roles de la unidad | `numbered: auto \| true` | list_aside |
| `aside` | simple | cajas del grupo, ícono | `tone: dark` | list_aside |
| `banner` | simple | banner | — | three_cards, card_grid |
| `tag` | simple | tag | — | list_aside (`_tags`) |
| `list_title` | simple | list_title | — | list_aside |
| `image_message` | compuesto | imágenes, cuerpo, block:N | `image_ratio`, `image_ratio_fallbacks`, `message` | image_text |
| `quadrant` | compuesto | cuadrantes, ejes | `focus` | quadrant |
| `matrix` | compuesto | encabezados, celdas | — | matrix |
| `worksheet` | compuesto | panel, consignas | `lines` | quadrant (panel) |
| `circles` | compuesto | unidades en círculo | — | circles |

Acentos sin contenido (por iniciativa propia, máximo 2 por slide): `accent_bar`, divisor de
paleta, numeración decorativa (`numbered: true`, decisión 2). Van como `NEO_BRAND`.
Íconos: solo los que trae la slide o los **prestados** que la persona pidió por slide de origen
(decisión 1, F5b). El modelo nunca elige un ícono externo.

## Reglas que el motor aplica (no las decide el modelo)

- `columns: auto` usa la tabla del catálogo (`card_grid.columns_by_count`; item_row: una columna
  hasta `max_rows`, después dos llenadas por columna).
- `uniform: true` (y por omisión en toda repetición): mismo alto para todas las unidades.
- `height: fill` reparte el alto sobrante; `auto` toma lo que mide el contenido.
- Tipografía, colores, radios, rellenos y separaciones salen de `tokens.yaml`; los gutters, de la
  geometría del layout del catálogo más cercano al bloque.
- Desborde: compactación dentro de la marca → excepción autorizada → `split_suggested` por unidades.

## Guardas de marca (validación antes de dibujar)

Componentes solo de esta tabla · tono oscuro solo en `aside` (máx. 1 por slide clara) · máx. 3
tipos de bloque por slide · `span` mínimo: card 3, aside 3, item_row 4, compuestos 6 (worksheet 4, como en Taller 1 v7, slide 22) · nada fuera
del área segura · portada y cierre nunca son libres · reglas de Taller 1 v7 (`convenciones.md`).

## Estado del dibujo (F3, 2026-10-02)

Se dibujan todos los bloques de la tabla salvo `tag` suelto (los tags van en el encabezado), la
card con `style: rule` y `mode: dark`. G1–G5 están resueltos; G6 (íconos prestados) es F5b.

## Resultado de la prueba de expresividad (F0)

Los 10 ejemplos se escriben con la gramática. Lo que **ya dibuja** el composer cubre la mayoría;
lo que falta es poco y concreto:

| # | Falta | Lo pide | Fase |
|---|---|---|---|
| G1 | `header.note`: bloque corto a la derecha del título | Taller 1 v7, slides 13 y 22 | F3 |
| G2 | `icon: header_right`: ícono dentro de la cabecera navy de la card | Taller 1 v7, slide 13 | F3 |
| G3 | `numbered: true`: numeración decorativa cuando el autor no numeró | decisión 2, Taller 1 v7, slide 10 | F3 |
| G4 | `align: top` de una celda más baja que su fila (panel oscuro arriba) | Taller 1 v7, slide 10 | F2 |
| G5 | Bloques compuestos dibujados en una caja arbitraria: hoy `_image_text`, `_quadrant`, `_matrix` y `_circles` suponen el ancho completo (x=45, 630 pt) | image_text, Taller 1 v7, slide 22 | F3 (la tarea más grande) |
| G6 | Íconos prestados de otra slide | decisión 1 | F5b |

Conclusiones:

1. **Repetición, no celdas sueltas.** Seis de los diez ejemplos son «el mismo bloque para cada
   unidad»: sin `repeat` el modelo tendría que escribir una celda por card y no podría expresar
   «columnas automáticas». Es la pieza central de la gramática.
2. **El comportamiento adaptativo no se reescribe con celdas.** La imagen que cede ancho, la
   imagen principal con retrato y la galería de image_text, o los ejes de la matriz, son bloques
   compuestos que reusan el código actual. Por eso G5 es la tarea más grande de F3.
3. **Los layouts fijos pueden pasar a ser presets** de esta gramática (los seis `catalog_*.yaml`),
   pero solo después de que F2 demuestre geometría equivalente. No antes.
4. **Cobertura de las referencias:** las 4 slides de Taller 1 v7 se expresan sin bloques nuevos; solo
   piden G1–G4.
