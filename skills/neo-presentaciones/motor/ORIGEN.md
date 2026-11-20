# Origen del motor

`neo_refactor/` es el núcleo del motor de rediseño de NEO, copiado del repo privado
`mcp-presentaciones` en el commit `1f569ad` (2026-11-20). Solo se trajeron los módulos de
composición, render, marca, verificación y auditoría; el servidor MCP, la nube y Figma
quedaron fuera.

Desde esta copia el motor evoluciona aquí. Si se corrige algo en el motor, se corrige en
este repo, con una prueba en `tools/probar.py` cuando aplique.

Cambios respecto del origen: ninguno en la lógica. La skill llega al motor con su propia
carpeta de trabajo (`--trabajo`, por defecto `./.neo`) y pone LibreOffice en el PATH del
proceso para que el motor lo encuentre en Windows y Mac.
