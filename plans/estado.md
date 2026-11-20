# Estado

Última actualización: 2026-11-23.

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
