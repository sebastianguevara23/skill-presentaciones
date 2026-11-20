"""Entorno local: LibreOffice, Montserrat y conversión PPTX → PDF → PNG.

La skill corre en la máquina de la persona (Windows, Mac o Linux). Aquí vive todo lo que
depende del sistema operativo, para que el resto del código no lo sepa.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SKILL = Path(__file__).resolve().parents[2]
FONTS = SKILL / "assets" / "fonts"

_CANDIDATOS = {
    "Windows": [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "LibreOffice" / "program" / "soffice.exe",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "LibreOffice" / "program" / "soffice.exe",
    ],
    "Darwin": [
        Path("/Applications/LibreOffice.app/Contents/MacOS/soffice"),
        Path.home() / "Applications" / "LibreOffice.app" / "Contents" / "MacOS" / "soffice",
    ],
    "Linux": [Path("/usr/bin/soffice"), Path("/usr/lib/libreoffice/program/soffice"),
              Path("/opt/libreoffice/program/soffice"), Path("/snap/bin/libreoffice")],
}

COMO_INSTALAR = {
    "Windows": "winget install --id TheDocumentFoundation.LibreOffice -e  (o descárgalo de libreoffice.org)",
    "Darwin": "brew install --cask libreoffice  (o descarga el .dmg de libreoffice.org)",
    "Linux": "sudo apt install -y libreoffice-impress  (o el gestor de paquetes de tu distribución)",
}


def sistema() -> str:
    return platform.system()


def soffice() -> Path | None:
    """Ruta de LibreOffice, aunque no esté en el PATH (lo normal en Windows y Mac)."""
    for nombre in ("soffice", "libreoffice"):
        ruta = shutil.which(nombre)
        if ruta:
            return Path(ruta)
    for ruta in _CANDIDATOS.get(sistema(), []):
        if ruta.exists():
            return ruta
    return None


def exponer_soffice() -> None:
    """Pone LibreOffice en el PATH del proceso: el motor lo busca con `shutil.which`."""
    ruta = soffice()
    if ruta and not shutil.which("soffice"):
        os.environ["PATH"] = str(ruta.parent) + os.pathsep + os.environ.get("PATH", "")


def _carpeta_fuentes() -> Path:
    so = sistema()
    if so == "Windows":
        return Path(os.environ["LOCALAPPDATA"]) / "Microsoft" / "Windows" / "Fonts"
    if so == "Darwin":
        return Path.home() / "Library" / "Fonts"
    return Path.home() / ".local" / "share" / "fonts" / "neo-montserrat"


def instalar_fuentes() -> dict:
    """Instala Montserrat para el usuario (sin permisos de administrador)."""
    destino = _carpeta_fuentes()
    destino.mkdir(parents=True, exist_ok=True)
    nuevas = 0
    for ttf in sorted(FONTS.glob("*.ttf")):
        final = destino / ttf.name
        if not final.exists():
            shutil.copy2(ttf, final)
            nuevas += 1
        if sistema() == "Windows":
            _registrar_fuente_windows(final)
    if sistema() == "Linux" and shutil.which("fc-cache"):
        subprocess.run(["fc-cache", "-f", str(destino)], capture_output=True, timeout=120)
    return {"carpeta": str(destino), "nuevas": nuevas, "total": len(list(FONTS.glob("*.ttf")))}


def _registrar_fuente_windows(ruta: Path) -> None:
    import winreg  # type: ignore[import-not-found]

    nombre = ruta.stem.replace("-", " ") + " (TrueType)"
    clave = r"Software\Microsoft\Windows NT\CurrentVersion\Fonts"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, clave) as k:
        winreg.SetValueEx(k, nombre, 0, winreg.REG_SZ, str(ruta))


def montserrat_instalada() -> bool | None:
    """None cuando el sistema no tiene cómo preguntarlo (Windows y Mac sin fc-list)."""
    if shutil.which("fc-list"):
        out = subprocess.run(["fc-list", ":family=Montserrat"], capture_output=True, text=True, timeout=60).stdout
        return bool(out.strip())
    carpeta = _carpeta_fuentes()
    return all((carpeta / ttf.name).exists() for ttf in FONTS.glob("*.ttf"))


def a_pdf(pptx: Path, carpeta: Path, timeout: int = 900) -> Path:
    """PPTX → PDF con LibreOffice, con un perfil temporal (evita cuelgues y bloqueos)."""
    ruta = soffice()
    if ruta is None:
        raise RuntimeError("No encuentro LibreOffice. Instálalo: " + COMO_INSTALAR.get(sistema(), "libreoffice.org"))
    carpeta.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="neo-lo-") as perfil:
        cmd = [str(ruta), f"-env:UserInstallation={Path(perfil).as_uri()}", "--headless", "--norestore",
               "--convert-to", "pdf", "--outdir", str(carpeta), str(pptx)]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    pdf = carpeta / (pptx.stem + ".pdf")
    if not pdf.exists():
        raise RuntimeError(f"LibreOffice no generó el PDF ({proc.returncode}): {proc.stderr[-400:]}")
    return pdf


def pdf_a_png(pdf: Path, carpeta: Path, ancho: int = 1280, paginas: list[int] | None = None,
              prefijo: str = "slide") -> list[Path]:
    """Una imagen por página (1-based en `paginas`), con el ancho pedido en píxeles."""
    import pymupdf

    carpeta.mkdir(parents=True, exist_ok=True)
    salida = []
    with pymupdf.open(pdf) as doc:
        for numero in paginas or range(1, doc.page_count + 1):
            if not 1 <= numero <= doc.page_count:
                continue
            pagina = doc[numero - 1]
            zoom = ancho / pagina.rect.width
            png = carpeta / f"{prefijo}-{numero:02d}.png"
            pagina.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False).save(png)
            salida.append(png)
    return salida


def fuentes_del_pdf(pdf: Path) -> list[str]:
    import pymupdf

    with pymupdf.open(pdf) as doc:
        return sorted({f[3].split("+")[-1] for page in doc for f in page.get_fonts()})


def resumen() -> dict:
    ruta = soffice()
    return {
        "sistema": f"{sistema()} {platform.release()} ({platform.machine()})",
        "python": sys.version.split()[0],
        "libreoffice": str(ruta) if ruta else None,
        "como_instalar_libreoffice": None if ruta else COMO_INSTALAR.get(sistema()),
        "montserrat_instalada": montserrat_instalada(),
    }
