# Plan de mejoras 0.2.0: feedback del deck de cliente

Fecha: 2026-11-23.
Fuente: el feedback sobre el rediseño de un reporte mensual de un cliente, con co-marca NEO +
cliente. Fueron 28 slides, 1 entrega y 6 rondas de corrección.

Meta: si se vuelve a correr ese deck desde el original con la 0.2.0, ninguna de las
correcciones de las 6 rondas debería hacer falta.

Las rutas son relativas a `skills/neo-presentaciones/`.

---

## Lo que muestra el código y el feedback no dice

Al cruzar cada hallazgo con el motor, varias causas son distintas de las que propone el feedback:

1. **La barra de acento ya está bien en el motor; lo que está mal es la guía.** En `image_text`,
   el motor dibuja la barra de 3 pt lógicos (6 pt en el archivo final) y del alto del texto
   (`motor/neo_refactor/composer.py:1649`). Pero `references/marca.md:62` dice que la barra
   «junto al mensaje en image_text» mide 4.5 × 25.5 (9 × 51), y esas son las medidas de *otra*
   barra, la que acompaña al título (`tokens.yaml:253`, `composer.py:2473`). En la ronda 4 se
   acortó la barra justo a 9 × 51: el error salió de la guía.
2. **Viñetas.** En las slides que el motor redibuja, `renderer.py:196` ya escribe Arial «•»,
   pero sin `buClr` ni `buSzPct`, así que la viñeta toma el navy y el tamaño del texto. El
   `buSzPts` del original solo queda en las slides que conservaron su organización
   (`no_cupieron` o `keep_layout`). En esas, `brand_fix.py` no toca las viñetas, ni
   `a:highlight`, ni las fuentes `ea`/`cs`/`sym`.
3. **El patrón del separador no se pone siempre.** Solo aparece cuando el título del
   separador oscuro tiene una sola palabra, y es una regla de marca registrada
   (`tokens.yaml:43`, `single_word_separator.companion_required: true`) que la auditoría
   exige (`audit/policies.py:156`). Quitarlo es un cambio de política (ver D1).
4. **El 40 % de ancho para la imagen en `image_text` es a propósito.** Salió de la revisión del
   2026-09-23 («las imágenes o GIF son grandes») y funciona bien con fotos. El modo «imagen
   protagonista» tiene que aplicarse solo a `screenshot`, `chart` y `diagram`, y dejar las
   fotos como están.
5. **Títulos de tamaños distintos.** `fit_heading` (`composer.py:182`) baja la letra de 21 a
   16 pt lógicos (de 42 a 32) cuando el título no entra en 2 líneas (`tokens.yaml:149`, `min: 16`).
6. **El `FileNotFoundError` no viene de `icon_tint`.** `verificar` lee los dos decks dentro de
   un `TemporaryDirectory` y compara las imágenes después de cerrarlo, cuando la carpeta ya no
   existe (`scripts/neo_skill/inspeccion.py:319`). Solo se nota cuando una imagen cambió de
   bytes, porque es el único caso en que `same_glyph` abre los archivos.
7. **«Todo centrado» choca con una regla de marca escrita.** `ajustes.centrar_bloque`
   (`scripts/neo_skill/ajustes.py:127`) dice: «NO las cifras, las imágenes, las tablas…, que van
   arriba, pegadas al título». La persona pidió lo contrario para matrices y para imagen con
   texto (ver D4).
8. **El separador tiene tres estilos distintos según dónde se mire.** `section.yaml` y
   `slide_families.yaml` dicen Montserrat Black 36; `tokens.yaml:224` y `marca.md` dicen
   ExtraBold 45. El composer usa `tokens.yaml`. Hay que dejar uno solo.

---

## Decisiones antes de empezar

| # | Decisión | Recomendación |
|---|---|---|
| D1 | ¿El separador nuevo pasa a ser la regla NEO para todos los decks? Título en una línea, primera palabra en blanco y el resto en `blue_pale` (hoy el énfasis es `separator_blue` en Black itálica), línea azul de 125 × 4 lógicos (250 × 8) debajo y sin el patrón geométrico | Sí. La persona lo aprobó («ya perfecto»). Implica cambiar `tokens.yaml`, `slide_families.yaml` y la auditoría |
| D2 | Quitar el fondo blanco de las capturas | Hacerlo por defecto en slides claras para `screenshot`, `chart` y `diagram`, con una opción para desactivarlo por slide. Nunca en slides oscuras |
| D3 | Títulos de slide | La letra no se achica nunca: 21 pt lógicos (42) fijos. Si el título no entra en una línea, se propone una versión corta y se aplica solo con aprobación. Si la persona no la aprueba, el título va en dos líneas a 42 |
| D4 | ¿Las tablas, las matrices y el bloque imagen + texto se centran en vertical? | Sí. Se cambia la regla de `centrar_bloque` y la del motor. Las cifras siguen pegadas al título hasta que alguien pida lo contrario |

---

## Fase 0: bugs (S)

**0.1 `verificar` y `entregar` se caen con `FileNotFoundError`.**
Hacer la comparación dentro del `with tempfile.TemporaryDirectory` en `inspeccion.verificar`.
Prueba: volver a codificar una PNG del candidato y comprobar que `verificar` no se cae.

**0.2 Una imagen tratada no es una imagen faltante.**
Si se le quita el fondo a una captura, cambia su sha. Hoy `verificar` la cuenta como
`imagenes_faltantes` y bloquea la entrega. Propuesta: agregar en `integrity.py`, junto a
`same_glyph`, una función `same_picture`. Dos imágenes cuentan como la misma si tienen la misma
proporción y el RGB de los píxeles opacos coincide con el original en miniatura. Las que pasen
este control se informan como `imagenes_tratadas` y no bloquean. **2.2 necesita esto primero**,
y también cualquier arreglo de imágenes hecho con código.

## Fase 1: la marca por defecto en el motor (M). Evita las rondas 1, 2, 3, 5 y 6

**1.1 Viñetas de marca.**
- `renderer._bullet`: agregar `buClr` en blue (`2D5BFF`) y `buSzPct 100000`.
- `brand_fix`: en las slides que conservan su organización, normalizar las viñetas que ya
  existen. Se quitan `buSzPts` y los `buClr`/`buFont` que no son de la marca, y quedan Arial
  «•», azul, al 100 %. Las numeraciones (`buAutoNum`) conservan su tipo.

**1.2 Limpieza de los runs (`brand_fix`).** En todas las slides:
- Quitar `a:highlight`. La «caja gris» de los rótulos CR venía de ahí.
- Igualar `ea`, `cs` y `sym` al `latin`.

**1.3 Separador (según D1).**
- `tokens.yaml` (estilo dark `title`): la primera palabra en blanco y el resto en
  `blue_pale`, sin itálica. Va en lugar de `title_emphasis_rule` de `slide_families.yaml`.
- Nuevo componente `separator_line`: 125 × 4 pt lógicos, color blue, a unos 14 pt bajo el
  título y alineado a la izquierda. Se dibuja en `composer.py`, en el bloque del separador
  (línea 556 y siguientes).
- El título va en una línea (`max_lines: 1`). Si a 45 no entra, baja hasta el `min: 32` que ya
  existe. Si tampoco entra así, se propone un título corto (3.2).
- Quitar el patrón: `companion_required: false` (`tokens.yaml:43`), sacar la llamada de
  `composer.py:568` y la regla `single_word_separator_empty` de `audit/policies.py:156`.
- Dejar un solo estilo: `section.yaml` y `slide_families.yaml` se alinean con `tokens.yaml`.

**1.4 Títulos fijos (según D3).**
- En el estilo light `title` de `tokens.yaml:149`, `min: 21`. Así `fit_heading` ya no achica,
  y si el título no cabe deja el aviso `heading_too_long`.
- Riesgo: hay layouts que guardan poco alto para el título (`metrics_row`, `matrix`). Hay que
  probarlo con la galería y con el deck de prueba.

**1.5 Matriz centrada en vertical (según D4).**
- `composer._matrix` (línea 2093): medir el alto de la tabla y, si sobra espacio,
  bajarla hasta centrarla entre el encabezado y el pie.
- Si hay alto, las filas crecen hasta unos 35 pt lógicos (70). Si no, se quedan con su alto
  natural.
- `ajustes.centrar_bloque`: deja de saltarse las tablas, y la guía se actualiza.

## Fase 2: imágenes, logos y matriz (L). Evita las rondas 0, 1, 3 y 4

**2.1 Modo «imagen protagonista» en `image_text`.**
- Cuándo: todas las imágenes de la slide tienen `asset_classes` `screenshot`, `chart` o
  `diagram`.
- `image_text.yaml`: nueva geometría
  `protagonist: {text_column: 250, column_gap: 22, align: top, center_block: true}`.
- `composer._image_message` (líneas 1455–1520). Hoy el ancho de la imagen es `width × 0.4`
  y el texto llega hasta el margen derecho. En el modo nuevo:
  - El texto va en una columna fija de 250 lógicos (500 pt), o más angosta si el texto ocupa
    menos.
  - La imagen toma el resto del ancho sin perder su proporción.
  - El bloque imagen + texto se centra en horizontal y en vertical en la zona de contenido.
  - La imagen y el texto se alinean arriba, y la barra de acento mide lo que el texto.
- Galería: agregar `image_text_protagonista.jpg`.

**2.2 Capturas sin fondo blanco (según D2; depende de 0.2).**
- Nuevo módulo `motor/neo_refactor/bg_clear.py`. Hace un relleno por inundación desde los
  bordes: lo casi blanco (todos los canales ≥ 245) se vuelve transparente y la imagen se
  guarda en PNG.
- Solo se aplica a `screenshot`, `chart` y `diagram`, en slides claras y en imágenes que
  todavía no tienen transparencia.
- Si el relleno quitaría más del 70 % de la imagen, no se aplica y queda un aviso.
- `optimize.py` ya deja en PNG las imágenes con transparencia.
- Para hacerlo a mano también: `ajustes.quitar_fondo_blanco(s, forma)`.

**2.3 Logo del cliente con fondo propio.**
- `cobrand._dark_variant` (línea 76) pasa a blanco todo lo oscuro y neutro, y así el bloque
  negro del logo del cliente quedó blanco.
- Detectar el fondo o bloque sólido: los píxeles oscuros forman un área llena (densidad mayor
  a 0.6 dentro de su caja y más del 10 % del logo) o el borde del logo es opaco. En esos casos,
  la variante oscura es el mismo logo.
- Agregar un campo de plan para forzarlo a mano: `client_logo_dark: "original" | "invert"`.
- Prueba: un logo sintético con texto amarillo sobre un bloque negro.

**2.4 `leer` ve los logos de la plantilla.**
- `leer` extrae las imágenes de `slideLayouts` y `slideMasters` a `lectura/plantilla/`, con su
  `srcRect` aplicado, y las lista en `lectura.json` bajo `plantilla.imagenes`.
- Marca como candidatas a `client_logo` las que no son de NEO (sha conocido), son chicas y
  están en una esquina.
- `redisenar --logo-cliente RUTA` pasa la imagen directo a `cobrand.prepare`. Ya no hace falta
  meterla a mano en un `preparado.pptx`.

**2.5 Matriz con una columna destacada.**
- Campo de plan `highlight_column: N` en `schemas.py` (`SlideClassification`) y en
  `composer._matrix_table`: cabecera en blue y celdas en `blue_pale` con 45 % de alfa.
- Hay que permitir ese alfa en `audit/policies.py`. Hoy marca como `off_palette_shape`
  cualquier color con tint.
- Pasar de cards a matriz junta los rótulos repetidos («Clics» ×4 queda en un solo rótulo de
  fila), y `verificar` lo contaría como palabras faltantes. Propuesta: un campo de plan
  `consolidate_labels: true` por slide. Con él, una palabra que falta pero sigue apareciendo
  al menos una vez en la misma slide se informa como «consolidada» y no bloquea. Solo vale
  cuando la persona aprobó la matriz.

## Fase 3: revisión y flujo de la skill (M). Evita las rondas 3 y 4 y las vueltas con Google

**3.1 Avisar a tiempo de los títulos de dos líneas.**
- `revisar`: nuevo hallazgo `titulo_dos_lineas`. Se mide con `textmetrics` en Montserrat
  ExtraBold a 42 pt contra el ancho real del título (unos 1150 pt con co-marca).
- `leer`: el mismo cálculo por slide (`titulo_en_una_linea: false`), para que las propuestas
  lleguen en el paso 2, antes de la primera pasada, y no después.

**3.2 Títulos cortos aprobados, sin abrir la verificación.**
- Hoy, cambiar texto obliga a entregar con `--cambios-pedidos`, y eso apaga la verificación de
  *todo* el deck.
- Propuesta: un campo de plan `text_overrides`, por ejemplo
  `{"s3:t1": {"text": "…", "reason": "aprobó el título corto"}}`. El motor lo aplica, el
  reporte lo registra y `verificar` saca de la comparación solo esos ids y los lista como
  cambios pedidos. El resto del deck se sigue verificando.
- `redisenar.md`, paso 2: la tabla de decisiones suma una columna «título corto propuesto».
  El título corto conserva cifras y sujeto, y se avisa cuando agrega o precisa una cifra (por
  ejemplo, «último Q» pasa a «Q4»).

**3.3 Pedidos ambiguos.**
- En la sección «La persona manda» de `SKILL.md`: si un pedido de estilo puede aplicarse a
  varios elementos parecidos («la línea», «el palito», «el recuadro»), primero se muestra una
  miniatura con los candidatos marcados y se pregunta una vez. Recién entonces se aplica en
  todo el deck.

**3.4 `marca.md` al día.**
- Glosario con nombres distintos para cada elemento: **barra de acento** (`image_text`,
  vertical, 6 pt × alto del texto), **barra del título** (9 × 51), **línea del separador**
  (250 × 8, horizontal, bajo el título) y **divisor**.
- Además: separador con la palabra en `blue_pale`, viñetas (blue, 100 %, «•»), destacar con
  `blue_pale` y alfa, capturas sin fondo blanco, títulos a 42 pt sin achicar y la nueva regla
  de centrado (D4).

**3.5 `familias.md`.**
- Antipatrón nuevo: cards que repiten los mismos rótulos → `comparison_matrix` con columna
  destacada (2.5).
- Slides de capturas → `image_text` en modo protagonista (2.1).

**3.6 `reparar.md` y `ajustes.py`.**
- Receta de embudo:
  - Ubicar las cajas de color dentro de la imagen.
  - Flechas en escuadra (freeform con punta) del borde derecho de cada paso al siguiente,
    cerca de lo que señalan.
  - Rótulos CR en negrita: navy para el rótulo y blue para el %.
- Helper nuevo: `flecha_escuadra(s, desde, hasta)`.

**3.7 `google.md`.**
- Subir con el conector de Drive (`create_file` convierte el PPTX).
- El conector no puede reemplazar una presentación, así que cada ronda genera un link nuevo.
  Flujo: subir la versión nueva, renombrar la anterior a «(versión anterior)» y mandarla a la
  papelera solo con el sí de la persona. Avisarlo desde la primera subida.
- La vista previa de Drive («Página N / M») no carga Montserrat: hay que abrir el archivo con
  Presentaciones de Google y pedir las capturas desde ahí.

## Fase 4: pruebas, galería y versión (S)

- `tools/probar.py`, controles nuevos:
  - `verificar` con una imagen vuelta a codificar no se cae y la reconoce.
  - Viñetas con `buClr 2D5BFF` y `buSzPct 100000`.
  - Una slide con `keep_layout` queda sin `a:highlight` y con `ea`/`cs`/`sym` igual a `latin`.
  - El separador tiene su línea, no tiene patrón y la palabra va en `blue_pale`.
  - Todos los títulos de slide están a 42 pt.
  - Una slide `image_text` con captura tiene la imagen en más del 50 % del ancho y el bloque
    centrado.
  - La matriz queda centrada en vertical.
  - Un logo con bloque negro conserva el negro en fondo oscuro.
  - `leer` lista el logo del layout.
- `tools/crear-deck-de-prueba.py` suma slides con:
  - una captura;
  - un separador de dos palabras;
  - el logo del cliente en el layout;
  - cards con rótulos repetidos.
- Galería: regenerar `section_divider` e `image_text_clients`, y agregar la de protagonista y
  la de matriz (esta última ya era el pendiente 4 de `plans/estado.md`).
- `CHANGELOG.md` 0.2.0 y `plans/estado.md`.
- **Validación final:** volver a correr el deck de cliente desde el original y compararlo con
  la v7 aprobada.

---

## Orden y dependencias

```
0.1 ─ 0.2 ─ 2.2
1.1 · 1.2 · 1.3 · 1.4 · 1.5   (independientes entre sí)
2.1 ─ galería de protagonista
2.5 ─ 3.5
3.2 necesita el reporte del motor (engine) y verificar
3.4 va al final de las fases 1 y 2 (lleva sus medidas)
```

## Preferencias de la persona

Casi todas pasan a ser comportamiento por defecto:
- Todo centrado: 1.5, 2.1 y D4.
- Títulos de una línea: 1.4, 3.1 y 3.2.
- Separador: 1.3.
- Destacar con `blue_pale`: 2.5.
- Imágenes sin fondo: 2.2.
- Viñetas azules: 1.1.

La única propia de esta persona es que revisa en Google Slides y manda capturas, y eso lo
cubre 3.7.

## Riesgos

- Quitar el fondo: en una captura donde el blanco toca el borde, las celdas blancas conectadas
  también quedan transparentes. En fondo claro no se nota, y en fondo oscuro no se aplica.
- Títulos sin achicar: algunos layouts con poco alto pueden desbordar. Se controla con la
  galería y el deck de prueba antes de publicar.
- `consolidate_labels` y `text_overrides` abren un poco la única puerta dura. Por eso son
  campos explícitos, citan el pedido, quedan en el informe de entrega y valen solo por slide
  o por id.
