# Preparar el equipo

La skill necesita dos programas en el equipo de la persona: **uv**, que trae Python y las
librerías solo, y **LibreOffice**, que dibuja las slides para mirarlas. Montserrat la instala
`preparar` sin permisos de administrador.

Pídele permiso a la persona antes de instalar y dile qué vas a instalar y para qué.

## 1. uv

Comprueba con `uv --version`. Si no está:

- **Windows** (PowerShell):

  ```powershell
  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  ```

- **Mac o Linux**:

  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```

Después de instalar, puede hacer falta abrir una terminal nueva (o usar la ruta completa:
`%USERPROFILE%\.local\bin\uv.exe` en Windows, `~/.local/bin/uv` en Mac y Linux).

La primera vez que corras `neo.py`, uv baja Python 3.12 y unas librerías (unos 80 MB). Las
siguientes veces arranca en un par de segundos.

## 2. LibreOffice

`preparar` lo busca también fuera del PATH (en Windows, en `C:\Program Files\LibreOffice`;
en Mac, en `/Applications`). Si no está:

- **Windows:** `winget install --id TheDocumentFoundation.LibreOffice -e`. Si no hay winget,
  la persona lo descarga de libreoffice.org (instalador de Windows).
- **Mac:** `brew install --cask libreoffice`. Sin Homebrew, el `.dmg` de libreoffice.org.
- **Linux:** `sudo apt install -y libreoffice-impress` (o el gestor de su distribución).

## 3. preparar

```bash
uv run "<carpeta de la skill>/scripts/neo.py" preparar
```

`listo: true` quiere decir que LibreOffice dibujó la slide de prueba con Montserrat. Si no:

| Síntoma | Qué hacer |
|---|---|
| `libreoffice: null` | Instalar LibreOffice (paso 2) y volver a correr |
| `montserrat_en_pdf: false` | Cerrar toda ventana de LibreOffice y volver a correr; en Windows, cerrar sesión y entrar de nuevo si sigue igual |
| El render tarda más de 2 minutos o se cuelga | Cerrar LibreOffice (también en segundo plano: `soffice`) y reintentar |
| Error de permisos en la carpeta de fuentes | Correr de nuevo; si persiste, instalar Montserrat a mano desde `assets/fonts/` (doble clic → Instalar) |

## Notas

- Las rutas con espacios van siempre entre comillas.
- `neo.py` guarda su caché en `.neo/`, dentro de la carpeta donde lo corres. Se puede
  borrar cuando quieras.
- En Windows, Claude Code puede usar PowerShell o Git Bash: los comandos de la skill
  funcionan igual en los dos.
