---
name: neo-presentaciones
description: Presentaciones con la línea gráfica de NEO Consulting. Úsala cuando se pida rediseñar un PPTX o un Google Slides con la marca NEO («pásalo a la marca», «rediseña este deck», «ponle el estilo de NEO», «arregla estas slides»), o crear una presentación o una plantilla NEO desde un pedido o desde documentos («hazme una presentación sobre…», «arma el deck del taller», «una plantilla para el cliente»). También para retocar slides ya rediseñadas. No es para piezas de redes (neo-redes) ni para interfaces de software (neo-design).
user-invocable: true
---

# neo-presentaciones

Tú diseñas la presentación. El motor de NEO hace la primera pasada con los diseños
establecidos de cada familia de slide; tú miras el resultado, lo corriges con código y lo
entregas. La persona ve cada paso en imágenes y puede pedir cualquier cambio.

## Reglas que no se discuten

1. **El contenido no se toca.** En un rediseño, el texto, las cifras, las imágenes, los
   gráficos y los enlaces del original salen completos. En un deck creado, manda el guion
   que la persona aprobó. Solo cambia el texto si la persona lo pide, y entonces se entrega
   con `--cambios-pedidos` citando su pedido. Nunca inventes texto, cifras ni títulos.
2. **Portada clara y despedida canónica.** Todo deck abre con la portada clara y cierra con
   la despedida de marca, aunque el pedido sea parcial. El motor las pone solas. Si hay una
   slide de B Corp, se elimina (política de marca).
3. **Cada slide va con el diseño establecido de su familia.** Agenda, índice, cards, cifras,
   pasos, equipo, imagen con texto, portada, separador y cierre ya tienen su diseño: míralo
   en [la galería](references/familias.md) y úsalo. `keep_layout` (marca encima de la
   organización original) es solo para cuando la persona pide conservar su distribución;
   no es un atajo cuando algo no encaja.
4. **Marca:** solo Montserrat, solo la paleta NEO, sin emojis, letra de 22 pt como mínimo en
   el archivo final y contraste de al menos 3:1. El detalle está en [marca.md](references/marca.md).
   Si la persona pide romper una regla, hazlo y avísale en una frase que se aparta de la guía.

## Cómo correr las herramientas

Todo pasa por `scripts/neo.py` de esta carpeta (la ruta exacta te la da Claude Code al cargar
la skill). Se corre con `uv`, que instala solo lo que haga falta:

```bash
uv run "<carpeta de la skill>/scripts/neo.py" <comando> ...
```

**La primera vez en cada equipo**, corre `preparar`: revisa LibreOffice, instala Montserrat
para el usuario y prueba un render. Si falta `uv` o LibreOffice, sigue
[entorno.md](references/entorno.md) e instálalos tú (con el permiso de la persona).

Trabaja en la carpeta de la persona: crea al lado del deck una carpeta `<nombre> - NEO/` con
`lectura/`, las versiones (`v1.pptx`, `v2.pptx`…) y la entrega. Todo queda a la vista.

| Comando | Para qué |
|---|---|
| `preparar` | Deja el equipo listo (una vez) |
| `leer DECK --out DIR` | Texto e ids por slide (`lectura.json`) y cuadrículas del original |
| `catalogo [--familia F]` | Familias, layouts, slots y roles que el motor sabe componer |
| `separar DECK --slide N --forma F [--numeros] --out P` | Una lista en una sola caja pasa a una caja por ítem (mismo texto) |
| `redisenar DECK --plan P --out vN.pptx` | Primera pasada del motor con tu plan |
| `crear GUION --out vN.pptx [--medir]` | Deck nuevo desde un guion aprobado |
| `mirar PPTX --out DIR [--antes DECK] [--slides 3,5]` | PNG por slide, cuadrículas y antes/después |
| `formas PPTX --slide N` | Formas de una slide con posición en pt, letra y colores |
| `revisar PPTX` | Hallazgos de calidad y marca, con medida. Informa, no bloquea |
| `verificar ORIGINAL CANDIDATO [--reporte R]` | Contenido completo y visible |
| `entregar ORIGINAL CANDIDATO --out FINAL [--reporte R]` | Verifica, optimiza y deja el informe |

## El trabajo

**Rediseñar un deck:** sigue [redisenar.md](references/redisenar.md).
**Crear un deck o una plantilla:** sigue [crear.md](references/crear.md).

Los dos caminos usan el mismo bucle:

1. **Mirar el punto de partida.** El original (`leer`) o el guion. Muéstrale a la persona
   la cuadrícula del original.
2. **Decidir el diseño de cada slide** con la galería a la vista, y contárselo a la persona
   en una tabla corta: slide, familia y por qué. En pedidos grandes, avanza por lotes de 6 a
   10 slides.
3. **Primera pasada del motor** (`redisenar` o `crear`).
4. **Mirar el resultado** (`mirar --antes`) y correr `revisar`. Mira tú cada imagen: la
   revisión mide, pero el ojo decide.
5. **Corregir con código** lo que no está a la altura de la galería: tamaños, aire,
   alineación, cards huérfanas, contraste. Las recetas están en [reparar.md](references/reparar.md).
   Guarda cada corrección como una versión nueva y vuelve al paso 4.
6. **Verificar** el contenido contra el original (o contra `_origen.pptx` en un deck creado).
   Es lo único que impide entregar.
7. **Entregar** con `entregar`, y al final muéstrale a la persona el antes y después.

## La persona manda

- Cumple lo que pida: «otra organización», «más aire», «el título en azul», «parte esta
  slide», «letra más chica para que entre». Hazlo con el plan o con código. No respondas
  «no se puede». Si algo choca con la marca, ofrece lo más cercano dentro de ella.
- Pregunta solo si el alcance de verdad no se entiende, y una sola vez.
- Si una slide no queda bien después de dos intentos, dilo y propón la alternativa
  (partirla, otra familia o conservar su organización), en vez de entregarla en silencio.

## Al entregar

Dale a la persona:
- La ruta del PPTX final y lo que cambió, en pocas líneas.
- Las salvedades del informe que valga la pena revisar.
- Las imágenes que falte poner (los recuadros «Colocar imagen»).
- Cómo llevarlo a Google Slides ([google.md](references/google.md)).

Si el contenido cambió a pedido suyo, di qué cambió.

## Qué hay en esta carpeta

- `scripts/neo.py` y `scripts/neo_skill/`: las herramientas de la skill.
- `motor/neo_refactor/`: el motor de composición de NEO (familias, marca, verificación).
- `design_knowledge/`: tokens de marca, catálogo de familias y layouts (lo lee el motor).
- `assets/`: Montserrat, logos y fondos de marca, y la galería de familias (`galeria/`).
- `references/`: los flujos, la marca, las familias y las recetas de corrección.
