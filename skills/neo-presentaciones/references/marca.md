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
| blue | `2D5BFF` | Énfasis, números, bordes de card, enlaces |
| blue_soft | `7E99FE` | Solo sobre navy o fondos oscuros (sobre blanco no llega al contraste) |
| blue_pale | `C5D5F7` | Texto secundario sobre navy, separadores, fondos de íconos |
| separator_blue | `9AAFFE` | Énfasis en fondo oscuro, divisores |
| white / black | `FFFFFF` / `000000` | Texto sobre navy / casos puntuales |

- El texto solo usa estos colores; nada de grises ni colores del original. Los enlaces van
  en blue.
- **Contraste mínimo 3:1.** En fondo claro: navy o blue. En fondo oscuro: blanco,
  blue_pale o separator_blue. `revisar` lo mide (`contraste_bajo`).
- Íconos y SVG editables: la misma paleta. Los íconos de un color salen en blue sobre un
  círculo blue_pale. Los logos conservan sus colores.

## Tipografía

Solo Montserrat. Pesos: Regular (cuerpo), Medium (subtítulos), SemiBold (etiquetas,
kicker), ExtraBold (títulos), Black (cifras y números de card).

| Rol | Letra | Tamaño |
|---|---|---|
| Título de slide | ExtraBold, navy; énfasis en blue | 21 pt (42) |
| Título de portada | ExtraBold 45 pt (90), énfasis en blue | |
| Título en separador oscuro | ExtraBold, blanco | 45 pt (90) |
| Subtítulo | Medium, navy | 11 pt (22) |
| Número de card | Black, blue | 24 pt (48) |
| Título de card | ExtraBold, navy | 14 pt (28) |
| Cuerpo de card | Regular, navy | 11 pt (22) |
| Cifra | Black, blue | 30 pt (60) |
| Etiqueta de cifra | ExtraBold, navy | 13 pt (26) |
| Cita de fuente | Regular, navy | 8 pt (16), a la derecha en la línea del pie |

- **Mínimo: 11 pt (22 pt en el archivo final).** Solo las citas de fuente bajan a 8 pt. Si
  no entra, se parte la slide; no se achica la letra salvo que la persona lo pida.
- Alto de línea: 1.2 × el tamaño (como Google Slides). Los textos de una card empiezan a la
  misma altura en todas las cards de la fila.

## Componentes

- **Card blanca:** borde blue de 1.5 pt (3) y sin sombra, o sin borde con la sombra `card`.
  Solo esas dos variantes. Padding de 12 pt (24) y separación de 6 pt (12).
- **Radio de las cards:** 3, 5 o 6 pt (6, 10 o 12), o pill. Nunca esquinas rectas en una
  card, ni radios sueltos.
- **Card con cabecera navy:** cabecera navy con título blanco y cuerpo en card blanca.
- **Tablas:** grilla plana. Cabecera navy, cuerpo blanco, énfasis blue, negativo blue_pale,
  bordes blue_pale de 0.6 pt, sin sombra ni radio.
- **Barra de acento:** azul, 4.5 × 25.5 pt (9 × 51), junto al mensaje en `image_text`.
- **Gráficos nativos:** siguen nativos; solo cambia su estilo. Series en este orden:
  blue, navy, blue_soft, separator_blue, blue_pale (en fondo claro). Grilla blue_pale de 0.75 pt.

## Marco de la slide

- Logo NEO arriba a la izquierda (45, 31.4 pt), frase `neoconsulting.ai` abajo a la
  izquierda. Los pone el motor como formas `NEO_BRAND_*`: no las muevas ni las borres.
- Zona de contenido: x de 45 a 675 pt, y de 64 a 346 pt (en el archivo final: 90–1350 ×
  128–692). El contenido se centra en el espacio libre bajo el encabezado.
- Fondo claro con degradado suave; separadores en fondo oscuro.
- **Portada:** siempre clara. **Despedida:** la última slide es el cierre canónico claro
  con el texto «Logra tus objetivos de negocio utilizando data e inteligencia artificial.»
- **Co-marca:** con `asset_classes: client_logo`, el logo del cliente va junto al de NEO en
  todas las slides.
- Sin emojis. Sin el logo viejo «NEO | 20 años» (asígnalo a `brand` para retirarlo).
