# Marca NEO en presentaciones

Fuente: `design_knowledge/tokens.yaml` (la usa el motor). Si algo de aquí choca con ese
archivo, manda el archivo.

## Escala

El motor compone en un lienzo lógico de **720 × 405 pt** y entrega a **1440 × 810 pt**
(1920 × 1080 px). Todo se escala ×2. Las medidas de esta guía están en la escala lógica y,
entre paréntesis, en el archivo final, que es lo que ves con `formas`.

## Color

| Token | Hex | Uso |
|---|---|---|
| navy | `000033` | Texto principal en fondo claro, cabeceras de card, círculos |
| blue | `2D5BFF` | Énfasis, números, viñetas, bordes de card, enlaces, barras y líneas de acento |
| blue_soft | `7E99FE` | Solo sobre navy o fondos oscuros (sobre blanco no llega al contraste) |
| blue_pale | `C5D5F7` | Texto secundario sobre navy, palabra de acento del separador, fondos de íconos, destacados con alfa |
| separator_blue | `9AAFFE` | Énfasis en fondo oscuro, divisores |
| white / black | `FFFFFF` / `000000` | Texto sobre navy / casos puntuales |

- El texto solo usa estos colores; nada de grises ni colores del original. Los enlaces van
  en blue.
- **Contraste mínimo 3:1.** En fondo claro: navy o blue. En fondo oscuro: blanco,
  blue_pale o separator_blue. `revisar` lo mide (`contraste_bajo`).
- **Para destacar** (una columna, una fila, un dato) se usa un tono claro de la paleta con
  alfa (`blue_pale` al 45 %), no un color nuevo.
- Íconos y SVG editables: la misma paleta. Los íconos de un color salen en blue sobre un
  círculo blue_pale. Los logos conservan sus colores.

## Tipografía

Solo Montserrat. Pesos: Regular (cuerpo), Medium (subtítulos), SemiBold (etiquetas,
kicker), ExtraBold (títulos), Black (cifras y números de card).

| Rol | Letra | Tamaño |
|---|---|---|
| Título de slide | ExtraBold, navy; énfasis en blue | 21 pt (42) en una o dos líneas |
| Título de portada | ExtraBold, énfasis en blue | 45 pt (90) |
| Título en separador oscuro | ExtraBold, sin itálica: la primera palabra en blanco y el resto en blue_pale | 45 pt (90), en una línea; baja hasta 32 (64) para entrar |
| Subtítulo | Medium, navy | 11 pt (22) |
| Número de card | Black, blue | 24 pt (48) |
| Título de card | ExtraBold, navy | 14 pt (28) |
| Cuerpo de card | Regular, navy | 11 pt (22) |
| Cifra | Black, blue | 30 pt (60) |
| Etiqueta de cifra | ExtraBold, navy | 13 pt (26) |
| Cita de fuente | Regular, navy | 8 pt (16), a la derecha en la línea del pie |

- **Mínimo: 11 pt (22 pt en el archivo final).** Solo las citas de fuente bajan a 8 pt. Si
  no entra, se parte la slide; no se achica la letra salvo que la persona lo pida.
- **Los títulos de slide van en una línea a 21 (42).** Si un título no entra, se propone una
  versión corta y se aplica solo con el sí de la persona ([redisenar.md](redisenar.md),
  paso 2). Si no la aprueba, va en dos líneas a 21 (42). Solo si no entra ni en dos líneas el
  motor lo achica, hasta 16 (32), para que la slide conserve su diseño. Es un caso de
  emergencia: `revisar` lo marca con `titulo_achicado` (y el de dos líneas con
  `titulo_dos_lineas`), y hay que proponer el título corto.
- **Viñetas:** Arial «•» en blue, al 100 % del tamaño del texto. Las listas numeradas, con su
  número en blue. El motor las normaliza también en las slides que conservan su organización.
- Alto de línea: 1.2 × el tamaño (como Google Slides). Los textos de una card empiezan a la
  misma altura en todas las cards de la fila.
- Los textos no llevan resaltado (`highlight`) y todas sus variantes de letra (`latin`, `ea`,
  `cs`, `sym`) son la misma Montserrat. El motor lo limpia.

## Barras y líneas

Tienen nombres distintos para no confundirlas. Cuando la persona pide «la línea» o «el
palito» y puede ser más de una, pregúntale cuál con una miniatura antes de cambiar todas.

| Nombre | Dónde | Forma |
|---|---|---|
| **Barra de acento** | A la izquierda del mensaje en `image_text` | Vertical, blue, 3 pt (6) de ancho y del alto del bloque de texto |
| **Barra del título** | A la izquierda del título, en los layouts que la llevan | Vertical, blue, 4.5 × 25.5 pt (9 × 51), con sombra suave |
| **Línea del separador** | Bajo el título del separador oscuro, alineada a su izquierda | Horizontal, blue, 125 × 4 pt (250 × 8) |
| **Divisor** | Entre el encabezado y el cuerpo, en los layouts que lo llevan | Línea blue_pale de 0.75 pt a lo ancho de la zona |

## Componentes

- **Card blanca:** borde blue de 1.5 pt (3) y sin sombra, o sin borde con la sombra `card`.
  Solo esas dos variantes. Padding de 12 pt (24) y separación de 6 pt (12).
- **Radio de las cards:** 3, 5 o 6 pt (6, 10 o 12), o pill. Nunca esquinas rectas en una
  card, ni radios sueltos.
- **Card con cabecera navy:** cabecera navy con título blanco y cuerpo en card blanca.
- **Tablas y matrices:** grilla plana. Cabecera navy, cuerpo blanco, énfasis blue, negativo
  blue_pale, bordes blue_pale de 0.6 pt, sin sombra ni radio. **Columna destacada**
  (`highlight_column`): cabecera blue y celdas blue_pale al 45 % de alfa.
- **Gráficos nativos:** siguen nativos; solo cambia su estilo. Series en este orden:
  blue, navy, blue_soft, separator_blue, blue_pale (en fondo claro). Grilla blue_pale de 0.75 pt.
- **Capturas, gráficos y diagramas en imagen:** en slide clara se les quita el fondo blanco
  que toca el borde, para que no queden como una caja blanca sobre el degradado. Lo hace el
  motor; `image_background: "keep"` en el plan lo evita en una slide. En slide oscura nunca.

## Marco de la slide

- Logo NEO arriba a la izquierda (45, 31.4 pt), frase `neoconsulting.ai` abajo a la
  izquierda. Los pone el motor como formas `NEO_BRAND_*`: no las muevas ni las borres.
- Zona de contenido: x de 45 a 675 pt, y de 64 a 346 pt (en el archivo final: 90–1350 ×
  128–692).
- **Centrado:** el contenido se centra en el espacio libre bajo el encabezado, en alto y en
  ancho, sin aire muerto a un lado. Eso vale también para las tablas, las matrices y el
  bloque imagen + texto. Solo las cifras (`metrics_row`) van arriba, pegadas al título.
- Fondo claro con degradado suave; separadores en fondo oscuro.
- **Portada:** siempre clara. **Despedida:** la última slide es el cierre canónico claro
  con el texto «Logra tus objetivos de negocio utilizando data e inteligencia artificial.»
- **Separador:** fondo oscuro, título en una línea con la primera palabra en blanco y el
  resto en blue_pale, y la línea del separador debajo. Sin patrón geométrico.
- **Co-marca:** con `asset_classes: client_logo` (o `redisenar --logo-cliente`), el logo del
  cliente va junto al de NEO en todas las slides. En las slides oscuras, el texto oscuro del
  logo pasa a blanco; un logo con fondo o bloque sólido propio se usa tal cual.
- Sin emojis. Sin el logo viejo «NEO | 20 años» (asígnalo a `brand` para retirarlo).
