# Estado

Última actualización: 2026-11-24.

## Por qué existe

El MCP `neo-slide-refactor` no alcanzó la calidad que se logra trabajando en Claude Code con
el motor: pocos trabajos llegaban aprobados al final y la mayoría de las llamadas eran
consultas de estado. La causa: en el MCP el modelo solo clasificaba sobre un motor
congelado y sin un visto bueno perfecto no había entrega. En Claude Code el modelo es el
autor: ve el render, corrige con código y entrega con salvedades.

Esta skill lleva ese segundo modo a cualquier persona de NEO. El MCP queda congelado.

## Decisiones

- **Claude Code primero** (app de escritorio o terminal). claude.ai queda para después,
  si el sandbox puede correr el motor.
- **Una sola puerta dura: el contenido** (`verificar`). Todo lo demás informa.
- **Cada slide va con el diseño establecido de su familia.** `keep_layout` solo a pedido.
  Las listas en una caja se separan (`separar --numeros`) para que tomen su diseño.
- **El motor se copió** (núcleo de `mcp-presentaciones` en `1f569ad`) y evoluciona aquí.
- **Distribución:** `npx skills add` desde este repo público.
- **Repo público** (2026-11-23): los comentarios del motor nombran las referencias de marca
  sin clientes (Taller 1 v7, Referencia v2) y los decks de casos como «deck de cliente» o
  «deck interno».
- **Marca 0.2.0** (2026-11-23, feedback de un deck de cliente):
  - El separador lleva la palabra de acento en blue_pale y la línea corta, sin el patrón
    geométrico.
  - Los títulos de slide no se achican.
  - Las capturas pierden el fondo blanco en las slides claras.
  - Tablas, matrices y el bloque imagen + texto se centran en alto; las cifras siguen pegadas
    al título.

## Versión 0.2.0

Lo que cambió está en `CHANGELOG.md` y el porqué en `plans/mejoras-0.2.0.md`. Prueba
completa: 14 controles de punta a punta más 138 en `tools/pruebas/`, en verde (Linux/WSL).

## Versión 0.1.0

- Herramientas: preparar, leer, catalogo, separar, redisenar, crear, mirar, formas,
  revisar, verificar, entregar.
- Ajustes probados para corregir con código (`neo_skill.ajustes`).
- Galería de 21 familias con texto neutro.
- Prueba de humo de 14 controles en verde (Linux/WSL).

## Pendiente

1. **Probar en Windows y Mac** de un consultor: instalación de uv, LibreOffice y
   Montserrat, y rutas con espacios.
2. **Piloto con 3 personas** que no sean el dueño, con decks que ya pasaron por el MCP,
   para comparar.
3. **Reforzar la verificación por bloque**: hoy compara palabras y cifras por slide; no ve
   dos cifras intercambiadas entre cards de la misma slide.
4. **Variantes que faltan en la galería** (`rows`, `four_card_row`, `two_by_two_cards`) y
   matrices.
5. `rules_cards` y `timeline` con 4 cards salen 3+1 en el motor: corregir el layout para
   que no haga falta `rejilla`.
6. **Títulos que no entran en 2 líneas a 42:** desde la 0.2.0 no se achican, así que la
   slide no cabe y sale con la marca sobre su organización original. Hay que decidir si en
   ese caso extremo se vuelve a achicar con aviso. También falta decidir si el estilo
   `statement` (título de `metrics_row`, 54 y se achica) sigue la misma regla.
7. **Bugs que ya estaban** (los encontraron las pruebas de la 0.2.0):
   - en una slide que conserva su organización, una tabla nativa cuyo marco va como
     `decorative` se borra entera;
   - `entregar` vuelve a optimizar sin las clases de imagen y las capturas pierden los
     300 ppi;
   - «18 %» se parte entre líneas porque no hay espacio duro.
8. **Viñetas heredadas del layout o del master:** no se normalizan; solo las escritas en la
   slide, que es como exporta Google Slides.
9. **Galería:** falta una imagen del modo imagen protagonista y otra de la matriz con
   columna destacada.
10. **Volver a correr el deck de cliente** que originó la 0.2.0 y compararlo con la versión
    aprobada.
