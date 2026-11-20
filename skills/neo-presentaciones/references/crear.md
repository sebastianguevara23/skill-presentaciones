# Crear un deck o una plantilla

Crear es rediseñar sin deck de origen: tú escribes el **guion** y, cuando la persona lo
aprueba, el motor lo convierte en slides con los diseños establecidos. Desde ese momento
el guion aprobado es el contenido que no se toca.

## 1. Entender el pedido

- Lo mínimo es el tema y para quién es. Si la persona dejó documentos en la carpeta
  (propuesta, informe, notas), léelos: son la fuente del contenido.
- Pregunta **una sola vez** lo que falte de verdad (cifras, nombres, fechas). Nunca
  inventes datos: si no los tienes, deja el lugar marcado (`[cifra por confirmar]`) y dilo
  al entregar.
- **Plantilla:** es un deck con las familias que la persona va a reutilizar (portada,
  agenda, separador, cards, cifras, equipo, cierre) y texto guía del tipo «Título de la
  sección». Ese texto es contenido pedido: va en el guion como cualquier otro.

## 2. Escribir el guion

Un JSON con este formato (todas las familias creables y su forma están en
`catalogo` → `creables_en_guion`, y su aspecto en [familias.md](familias.md)):

```json
{
  "title": "Adopción de IA en el área comercial",
  "subtitle": "Propuesta para el comité 2027",
  "request": "hazme una presentación corta para el comité sobre cómo adoptar IA en el área comercial",
  "slides": [
    {"family": "section_divider", "title": "Dónde estamos", "subtitle": "Diagnóstico del área comercial"},
    {"family": "three_cards", "title": "Tres pilares de la adopción", "units": [
      {"number": "01", "title": "Datos", "body": "Unificar el CRM y limpiar la base de clientes."},
      {"number": "02", "title": "Herramientas", "body": "Asistentes para propuestas y seguimiento."},
      {"number": "03", "title": "Personas", "body": "Formación por rol y acompañamiento semanal."}]},
    {"family": "key_metrics", "title": "Resultados del piloto", "units": [
      {"number": "38 %", "label": "menos tiempo por propuesta"},
      {"number": "+12", "label": "puntos de satisfacción"}]},
    {"family": "image_text_clients", "title": "Lo que ya funciona",
     "body": "Los equipos piloto redujeron a la mitad el tiempo de armado de propuestas.", "images": 1},
    {"family": "team_grid", "title": "Equipo responsable", "units": [
      {"title": "Ana Pérez", "label": "Líder comercial"}, {"title": "Luis Gómez", "label": "Datos"}]}
  ]
}
```

- Campos de una slide: `family`, `title`, `kicker`, `subtitle`, `body` (familias con cuerpo
  suelto; un salto de línea es un párrafo), `units` (cada una con `number`, `title`, `label`,
  `body` según la familia), `images` (recuadros «Colocar imagen»), `note` y `aside` (solo
  `steps_aside`: la primera línea de cada panel es su título).
- La portada se agrega sola con `title` y `subtitle`. La despedida canónica la pone la
  marca: no escribas un cierre propio.
- Escribe a la medida del layout: títulos de una línea, cuerpos de una o dos líneas. Los
  textos largos no se achican: se parten en otra slide.
- **Ritmo:** no repitas la misma forma más de tres slides seguidas. Alterna cards, cifras,
  filas, imagen y separadores.

## 3. Mostrar el guion y esperar el visto bueno

Muéstraselo a la persona como tabla (slide, familia, título, contenido resumido) **antes**
de generar, aunque el pedido sea claro. Ajusta lo que pida. Después mide si todo cabe:

```bash
uv run "$NEO" crear "Deck - NEO/guion.json" --medir
```

Lo que no cabe sale con su motivo: acorta o parte en el guion.

## 4. Crear, mirar y corregir

```bash
uv run "$NEO" crear "Deck - NEO/guion.json" --out "Deck - NEO/v1.pptx"
uv run "$NEO" mirar "Deck - NEO/v1.pptx" --out "Deck - NEO/vista-v1"
uv run "$NEO" revisar "Deck - NEO/v1.pptx"
```

- Junto a `v1.pptx` queda `v1_origen.pptx`: es el guion hecho PPTX y es el original contra
  el que se verifica.
- Corrige con código lo que no esté a la altura de la galería ([reparar.md](reparar.md)).
- **Imágenes:** si la persona dejó fotos en la carpeta, reemplaza los recuadros «Colocar
  imagen» por ellas (receta en reparar.md). Si no, quedan los recuadros y lo dices al
  entregar.
- **Gráficos:** si hay datos para graficar, agrega un gráfico nativo con la paleta de marca
  (receta en reparar.md). Los datos salen de la persona o de sus documentos, nunca inventados.

## 5. Verificar y entregar

```bash
uv run "$NEO" verificar "Deck - NEO/v1_origen.pptx" "Deck - NEO/v2.pptx" --reporte "Deck - NEO/v1_report.json"
uv run "$NEO" entregar "Deck - NEO/v1_origen.pptx" "Deck - NEO/v2.pptx" --reporte "Deck - NEO/v1_report.json" --out "Deck - NEO/Deck NEO.pptx"
```

Si la persona cambia el texto después de aprobar el guion, actualiza el guion y vuelve a
crear. Si el cambio es chico y lo haces con código, entrega con `--cambios-pedidos` citando
lo que pidió.
