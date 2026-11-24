"""Prueba de humo de la skill, de punta a punta, con los ejemplos del repo.

Rediseña `ejemplos/deck-de-prueba.pptx` (con `separar` para la agenda), crea un deck desde
`ejemplos/guion-ejemplo.json`, y en los dos casos mira, revisa, verifica y entrega. Además
comprueba que la verificación atrape una cifra cambiada. Al final corre las pruebas por tema
de `tools/pruebas/` (verificación, marca, imágenes y matriz, logos).

Uso: python3 tools/probar.py [--rapido]   (necesita uv y LibreOffice, como la skill;
--rapido salta las pruebas por tema)
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
NEO = RAIZ / "skills" / "neo-presentaciones" / "scripts" / "neo.py"
EJ = RAIZ / "ejemplos"
fallas: list[str] = []


def neo(*args: str, esperado: int = 0, cwd: Path) -> dict:
    proc = subprocess.run(["uv", "run", "--quiet", str(NEO), *args], capture_output=True, text=True, cwd=cwd)
    if proc.returncode != esperado:
        fallas.append(f"{args[0]}: código {proc.returncode} (esperado {esperado})\n{proc.stdout[-800:]}{proc.stderr[-800:]}")
        return {}
    return json.loads(proc.stdout) if proc.stdout.strip() else {}


def comprobar(condicion: bool, mensaje: str) -> None:
    print(("ok   " if condicion else "FALLA") + " " + mensaje)
    if not condicion:
        fallas.append(mensaje)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="neo-probar-") as tmp:
        t = Path(tmp)
        shutil.copy2(EJ / "deck-de-prueba.pptx", t / "deck.pptx")
        shutil.copy2(EJ / "plan-deck-de-prueba.json", t / "plan.json")
        shutil.copy2(EJ / "guion-ejemplo.json", t / "guion.json")

        prep = neo("preparar", cwd=t)
        comprobar(prep.get("listo") is True, "preparar: LibreOffice y Montserrat listos")

        lectura = neo("leer", "deck.pptx", "--out", "lectura", cwd=t)
        comprobar(lectura.get("slides") == 6 and lectura.get("cuadriculas"), "leer: 6 slides y cuadrícula")

        sep = neo("separar", "deck.pptx", "--slide", "2", "--forma", "TextBox 2", "--numeros", "--out", "preparado.pptx", cwd=t)
        comprobar(sep.get("texto_igual") is True and len(sep.get("cajas_nuevas", [])) == 5, "separar: 5 ítems, mismo texto")

        red = neo("redisenar", "preparado.pptx", "--plan", "plan.json", "--out", "v1.pptx", cwd=t)
        modos = {s["slide"]: s["modo"] for s in red.get("slides", [])}
        comprobar(red.get("ok") and set(modos.values()) == {"redesign"}, f"redisenar: todas con su familia ({modos})")

        vista = neo("mirar", "v1.pptx", "--out", "vista", "--antes", "preparado.pptx", cwd=t)
        comprobar(len(vista.get("antes_despues", [])) == 6, "mirar: 6 antes/después")

        rev = neo("revisar", "v1.pptx", cwd=t)
        comprobar(rev.get("total") == 0, f"revisar: sin hallazgos ({rev.get('por_codigo')})")

        ver = neo("verificar", "preparado.pptx", "v1.pptx", cwd=t)
        comprobar(ver.get("ok") is True and ver.get("modo") == "por_slide", "verificar: contenido completo, por slide")

        ent = neo("entregar", "preparado.pptx", "v1.pptx", "--out", "final.pptx", cwd=t)
        comprobar(ent.get("ok") is True and (t / "final_entrega.json").exists(), "entregar: PPTX final e informe")

        # Una cifra cambiada tiene que impedir la entrega.
        script = ("from pptx import Presentation\n"
                  "p = Presentation('v1.pptx')\n"
                  "for sh in p.slides[3].shapes:\n"
                  "    if sh.has_text_frame and '2,4' in sh.text_frame.text:\n"
                  "        sh.text_frame.paragraphs[0].runs[0].text = '2,8 M'\n"
                  "p.save('malo.pptx')\n")
        subprocess.run(["uv", "run", "--quiet", "--with", "python-pptx==1.0.2", "python", "-c", script], cwd=t, check=True)
        shutil.copy2(t / "v1_report.json", t / "malo_report.json")
        malo = neo("verificar", "preparado.pptx", "malo.pptx", esperado=1, cwd=t)
        comprobar(malo.get("ok") is False and malo.get("slides"), "verificar: atrapa una cifra cambiada")
        neo("entregar", "preparado.pptx", "malo.pptx", "--out", "malo-final.pptx", esperado=1, cwd=t)
        comprobar(not (t / "malo-final.pptx").exists(), "entregar: no entrega con el contenido alterado")

        medir = neo("crear", "guion.json", "--medir", cwd=t)
        comprobar(medir.get("ok") is True, "crear --medir: todo cabe")
        creado = neo("crear", "guion.json", "--out", "creado.pptx", cwd=t)
        comprobar(creado.get("ok") and not creado.get("no_cupieron"), "crear: deck desde el guion")
        ver2 = neo("verificar", "creado_origen.pptx", "creado.pptx", cwd=t)
        comprobar(ver2.get("ok") is True, "verificar: deck creado contra su guion")

        cat = neo("catalogo", cwd=t)
        comprobar(len(cat.get("familias", {})) >= 20, "catalogo: familias del motor")

    # Pruebas por tema (`tools/pruebas/`): cada una arma sus propios decks y sale con 1 si falla.
    if "--rapido" not in sys.argv:
        for prueba in sorted((RAIZ / "tools" / "pruebas").glob("*.py")):
            proc = subprocess.run(["uv", "run", "--quiet", "--with", "python-pptx==1.0.2", "--with", "pillow==12.3.0",
                                   "python", str(prueba)], capture_output=True, text=True, cwd=RAIZ)
            controles = sum(1 for linea in proc.stdout.splitlines() if linea.startswith(("ok", "FALLA")))
            comprobar(proc.returncode == 0, f"pruebas/{prueba.name}: {controles} controles")
            if proc.returncode != 0:
                fallas.append(proc.stdout[-1500:] + proc.stderr[-800:])

    if fallas:
        print("\n" + "\n\n".join(fallas))
        sys.exit(1)
    print("\nTodo bien.")


if __name__ == "__main__":
    main()
