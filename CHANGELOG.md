# Cambios

## 0.2.0 — 2026-11-24

Mejoras que salen de un deck de cliente que necesitó 6 rondas de corrección (plan en
`plans/mejoras-0.2.0.md`).

- **Verificación:** `verificar` ya no se cae cuando una imagen cambia de bytes. Una imagen
  tratada (sin fondo blanco, recomprimida) cuenta como la misma (`imagenes_tratadas`). Hay
  campos de plan nuevos para los textos que la persona aprobó cambiar (`text_overrides`) y
  para los rótulos repetidos que se juntan en una matriz (`consolidate_labels`). Esos cambios
  se informan y el resto de la slide se sigue verificando.
- **Marca por defecto:**
  - Viñetas en azul, al 100 %, con «•».
  - Se quitan el resaltado y las fuentes `ea`/`cs`/`sym` heredadas, también en las slides que
    conservan su organización.
  - Separador nuevo: título en una línea, la primera palabra en blanco y el resto en
    blue_pale, con una línea azul de 250 × 8 debajo y sin el patrón geométrico.
  - Los títulos de slide no se achican.
- **Títulos largos:** `leer` marca los textos que no entran en una línea como título
  (`cabe_como_titulo`), y `revisar` avisa con `titulo_dos_lineas`.
- **Imagen protagonista:** con capturas, gráficos o diagramas, el texto va en una columna de
  500 pt, la imagen toma el resto y el bloque se centra. En slides claras, las capturas
  pierden el fondo blanco (`image_background: "keep"` lo evita).
- **Matriz:** se centra en el alto de la zona, con filas de hasta 70 pt, y una columna se
  puede destacar con `highlight_column` (cabecera blue, celdas blue_pale al 45 %).
- **Logo del cliente:**
  - Un logo con fondo o bloque sólido propio ya no se invierte en las slides oscuras.
  - `leer` lista las imágenes de layouts y masters y marca las candidatas a logo del cliente.
  - Flags nuevos: `redisenar --logo-cliente RUTA` y `--logo-cliente-oscuro`.
- **Ajustes:** `flecha_escuadra` (embudos), `quitar_fondo_blanco`, y `centrar_bloque` ahora
  centra también tablas, matrices y el bloque imagen + texto.
- **Guías:**
  - Glosario de barras y líneas en `marca.md`.
  - Regla para confirmar los pedidos ambiguos con una miniatura.
  - Flujo de títulos cortos aprobados.
  - Recetas de embudo y de cards a matriz.
  - Subir a Google Slides con el conector, cómo versionar, y abrir con Presentaciones de
    Google (la vista previa de Drive no carga Montserrat).
- **Pruebas:** `tools/pruebas/` (verificación, marca, imágenes y matriz, logos: 138
  controles). `tools/probar.py` las corre al final; `--rapido` las salta.

## 0.1.0 — 2026-11-20

Primera versión de prueba.

- Skill `neo-presentaciones` para Claude Code: rediseñar un deck con la marca NEO o crear un
  deck o una plantilla desde un pedido.
- `scripts/neo.py`: preparar, leer, catalogo, separar, redisenar, crear, mirar, formas,
  revisar, verificar y entregar.
- Núcleo del motor de NEO copiado de `mcp-presentaciones` (`1f569ad`).
- Galería de 21 familias, guías de rediseño, creación, marca, familias, corrección con
  código, Google Slides y entorno.
- Prueba de humo `tools/probar.py`.
