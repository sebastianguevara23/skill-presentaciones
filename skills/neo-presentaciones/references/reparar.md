# Corregir con código

El motor da la primera pasada; lo que falte para llegar a la galería lo corriges tú con
python-pptx. Trabaja siempre sobre una copia: lees `v1.pptx` y guardas `v2.pptx`.

## Método

1. `formas PPTX --slide N`: nombres, cajas en pt, letra y colores de cada forma. Las formas
   del motor tienen nombres estables (`title_2`, `card_4`, `card_text_4`, `metric_value_6`…);
   las `NEO_BRAND_*` son de la marca y no se tocan.
2. Escribe un script corto en la carpeta de trabajo (`Deck - NEO/arreglos/v2.py`) y córrelo
   con las mismas dependencias que la skill:

   ```bash
   uv run --with python-pptx==1.0.2 --with pillow==12.3.0 python "Deck - NEO/arreglos/v2.py"
   ```

3. `mirar --slides N` y `revisar` sobre la versión nueva. Repite hasta que la slide esté a
   la altura de su imagen en la galería.
4. Al final, `verificar` contra el original con el reporte de la pasada del motor.

Un cambio por intención: si mueves cards, muévelas todas juntas para que sigan alineadas.

## Unidades y medidas

- python-pptx usa EMU: **1 pt = 12 700 EMU**. `formas` da los pt del archivo final
  (lienzo de 1440 × 810 pt).
- Zona de contenido en el archivo final: x de 90 a 1350 pt, y de 128 a 692 pt. Debajo del
  título se dejan unos 28 pt de aire.
- Letra mínima en el archivo final: 22 pt. Separación entre cards: 12 pt. Padding de card: 24 pt.

## Funciones probadas (`neo_skill.ajustes`)

Antes de escribir geometría a mano, usa estas funciones. Respetan las reglas de marca
(separación del motor, qué se centra y qué no):

```python
import sys
sys.path.insert(0, "<carpeta de la skill>/scripts")
from neo_skill.ajustes import *

prs = abrir("Deck - NEO/v1.pptx")
s = slide(prs, 3)                 # número de slide como lo dice la persona
rejilla(s, columnas=2)            # 4 cards en 3+1 → 2×2 que llenan la zona
centrar_bloque(s)                 # cards centradas entre el título y el pie
prs.save("Deck - NEO/v2.pptx")
```

| Función | Qué hace |
|---|---|
| `unidades(s)` | Cada card del motor con sus piezas (cabecera, texto, número, ícono) |
| `rejilla(s, columnas)` | Reacomoda las cards en N columnas con la separación que dio el motor |
| `llenar_ancho(s)` | Agranda las cards de cada fila hasta cubrir el ancho de la zona |
| `centrar_bloque(s)` | Centra el contenido entre el título y el pie: cards, tablas, matrices y el bloque imagen + texto. Las cifras no se mueven: van pegadas al título |
| `mover(forma, dx_pt, dy_pt)` | Desplaza una forma en pt |
| `flecha_escuadra(s, desde, hasta)` | Flecha recta en escuadra, con punta, del borde derecho de `desde` hasta cerca de `hasta` (formas o cajas en pt) |
| `traer_al_frente(s, forma)` | Pone una forma tapada encima de las demás |
| `reemplazar_marcador(s, foto)` | Cambia un «Colocar imagen» por la foto, recortada para llenar |
| `quitar_fondo_blanco(s, forma)` | Vuelve transparente el blanco que toca el borde de una captura. Solo en slides claras |
| `borrar_slide(prs, n)` | Elimina una slide (B Corp) |
| `caja_pt(forma)` | x, y, ancho y alto en pt |

Las bases de unidad del motor se llaman `card_N`, `item_N`, `metric_card_N`; sus piezas,
`card_text_N`, `card_header_N`, `item_number_N`… El número es un contador de la slide, no
de la card: para saber qué pieza va con qué card, usa `unidades(s)`.

## Recetas

### Abrir, ubicar y guardar

```python
from pptx import Presentation
from pptx.util import Pt, Emu
from pptx.dml.color import RGBColor

PT = 12700
prs = Presentation("Deck - NEO/v1.pptx")
slide = prs.slides[3 - 1]                      # slide 3
formas = {s.name: s for s in slide.shapes}
titulo = formas["title_2"]
# ... cambios ...
prs.save("Deck - NEO/v2.pptx")
```

### Letra, peso y color

```python
for p in forma.text_frame.paragraphs:
    for r in p.runs:
        r.font.size = Pt(28)
        r.font.name = "Montserrat ExtraBold"      # pesos: Montserrat, Montserrat Medium,
        r.font.color.rgb = RGBColor(0x00, 0x00, 0x33)  # SemiBold, ExtraBold, Black
```

Colores: navy `000033`, blue `2D5BFF`, blue_pale `C5D5F7`, separator_blue `9AAFFE`, blanco.
En fondo claro el texto va en navy o blue.

### Texto que desborda su caja

En este orden: (1) agranda la caja si hay espacio en la zona; (2) reparte el texto en otra
unidad o parte la slide con `split_parts` en el plan; (3) solo si la persona lo pide, baja
la letra (nunca por debajo de 22 pt en el archivo final sin su permiso).

### Traer al frente una forma tapada

`traer_al_frente(s, forma)`. Si `verificar` dice `texto_tapado`, la forma que tapa está
encima: muévela o trae el texto al frente.

### Reemplazar un recuadro «Colocar imagen» por una foto

`reemplazar_marcador(s, "Deck - NEO/fotos/oficina.jpg")`: recorta la foto para llenar el
recuadro sin deformarla y borra el recuadro.

### Quitar el fondo blanco de una captura

El motor ya lo hace con las imágenes `screenshot`, `chart` y `diagram` en slides claras.
Para una imagen que agregaste o reclasificaste con código, usa
`quitar_fondo_blanco(s, forma)`. Hace un relleno por inundación desde los bordes: el blanco
que toca el borde se vuelve transparente y el blanco de adentro (celdas, rótulos) queda
igual. No lo uses en slides oscuras. `verificar` la reconoce como la misma imagen
(`imagenes_tratadas`).

### Agregar un gráfico nativo con la marca

```python
from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE
datos = CategoryChartData()
datos.categories = ["2024", "2025", "2026"]
datos.add_series("Ventas", (120, 180, 240))     # datos de la persona, nunca inventados
# Ubícalo en espacio libre de la zona de contenido (x 90-1350, y bajo el título hasta 692).
gf = slide.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Emu(90 * PT), Emu(220 * PT),
                            Emu(800 * PT), Emu(480 * PT), datos)
chart = gf.chart
serie = chart.plots[0].series[0]
serie.format.fill.solid(); serie.format.fill.fore_color.rgb = RGBColor(0x2D, 0x5B, 0xFF)
chart.font.name, chart.font.size = "Montserrat", Pt(22)
chart.font.color.rgb = RGBColor(0x00, 0x00, 0x33)
chart.value_axis.major_gridlines.format.line.color.rgb = RGBColor(0xC5, 0xD5, 0xF7)
chart.has_legend = len(chart.plots[0].series) > 1
chart.has_title = False                         # el título va en la slide, no dentro del gráfico
```

Orden de colores de las series: blue, navy, blue_soft (`7E99FE`), separator_blue, blue_pale.

### Embudo o proceso sobre una imagen

Pasa con las capturas de un embudo con rótulos al lado («CR1 12 %»). Las flechas tienen que
ser rectas, en escuadra y cerca de lo que señalan; nada de curvas ni diagonales.

1. Ubica los pasos dentro de la imagen por su color. Por ejemplo, las cajas amarillas:

   ```python
   import io
   from PIL import Image

   def cajas_de_color(forma, rgb, tol=60):
       """Franjas de un color dentro de una imagen, como cajas en pt de la slide.
       No descuenta el recorte (srcRect): úsala en imágenes sin recortar."""
       im = Image.open(io.BytesIO(forma.image.blob)).convert("RGB")
       w, h = im.size
       px = im.load()
       cerca = lambda x, y: sum(abs(a - b) for a, b in zip(px[x, y], rgb)) < tol
       filas = [any(cerca(x, y) for x in range(0, w, 2)) for y in range(h)]
       x0, y0, ancho, alto = caja_pt(forma)
       cajas, inicio = [], None
       for y, hay in enumerate(filas + [False]):
           if hay and inicio is None:
               inicio = y
           elif not hay and inicio is not None:
               xs = [x for yy in range(inicio, y, 2) for x in range(0, w, 2) if cerca(x, yy)]
               cajas.append((x0 + min(xs) / w * ancho, y0 + inicio / h * alto,
                             (max(xs) - min(xs)) / w * ancho, (y - inicio) / h * alto))
               inicio = None
       return cajas

   pasos = cajas_de_color(formas["image_3"], (255, 205, 0))
   ```

2. Une cada paso con el siguiente, o con su rótulo, usando `flecha_escuadra(s, desde, hasta)`.
   Sale del borde derecho de `desde`, dobla en ángulo recto y termina a unos pt del destino.
3. Los rótulos CR van en negrita: el rótulo en navy y el porcentaje en blue. Si «CR1 12 %»
   está en un solo run, pártelo en dos runs con el mismo texto (no cambies palabras).

### Cards que repiten los mismos rótulos → matriz

Hazlo solo con el sí de la persona. Pon `consolidate_labels` con su cita en el plan de esa
slide y vuelve a correr la pasada del motor: así el reporte lo trae y `verificar` acepta que
los rótulos aparezcan una vez. Después reemplaza las cards por una tabla nativa:

```python
from pptx.util import Emu, Pt
from pptx.dml.color import RGBColor
NAVY, BLUE, PALE = RGBColor(0, 0, 0x33), RGBColor(0x2D, 0x5B, 0xFF), RGBColor(0xC5, 0xD5, 0xF7)

columnas = ["", "Google", "Bing", "AI Overview", "ChatGPT"]      # cabeceras, del original
filas = [["Clics", "120", "40", "75", "12"], ...]                 # textos del original
destacada = 3                                                     # «AI Overview»
alto_fila = 70
alto = alto_fila * (len(filas) + 1)
top = 128 + (692 - 128 - alto) / 2                                # centrada en la zona
tabla = s.shapes.add_table(len(filas) + 1, len(columnas), Emu(90 * PT), Emu(int(top * PT)),
                           Emu(1260 * PT), Emu(alto * PT)).table
for c, texto in enumerate(columnas):
    celda = tabla.cell(0, c)
    celda.text = texto
    celda.fill.solid()
    celda.fill.fore_color.rgb = BLUE if c == destacada else NAVY
# cuerpo blanco y la columna destacada en blue_pale al 45 % de alfa (a:alpha val="45000"
# dentro de su a:srgbClr); letra Montserrat de 22 pt o más; bordes blue_pale de 1.2 pt
```

Borra las cards con sus piezas (usa `unidades(s)`) y mira el resultado con `mirar`.

### Borrar una slide (B Corp)

`borrar_slide(prs, n)`. Después, entrega con `--cambios-pedidos "política de marca: la slide B Corp se elimina"`.

## Qué no hacer con código

- Cambiar palabras, cifras u orden del texto (salvo pedido de la persona).
- Mover o borrar las formas `NEO_BRAND_*`.
- Usar colores o letras fuera de la marca.
- Estirar imágenes: siempre recorta para llenar.
