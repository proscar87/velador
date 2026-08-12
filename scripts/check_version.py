#!/usr/bin/env python3
"""Verifica que la versión diga lo mismo en los cuatro puntos.

Existe porque el drift ya pasó: el tag v0.6.0 entrega un manifest que dice
0.7.0 (dos tags sobre el mismo commit), el CHANGELOG llegó a tener dos
entradas 0.8.0, y hacs.json declaró 2024.6 durante cuatro versiones con
código que necesita 2024.8.

Uso local antes de taggear:   python3 scripts/check_version.py
En CI sobre un tag:           python3 scripts/check_version.py --tag v0.9.2
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

RAIZ = pathlib.Path(__file__).resolve().parent.parent
MANIFEST = RAIZ / "custom_components" / "velador" / "manifest.json"
CHANGELOG = RAIZ / "CHANGELOG.md"
HACS = RAIZ / "hacs.json"

# APIs de core que el código usa, con la versión de HA que las introdujo.
# Si agregas una, ponla aquí: el piso de hacs.json es un contrato.
APIS_DE_CORE = {
    "last_reported": "2024.8",
}


def fallar(problemas: list[str]) -> None:
    for p in problemas:
        print(f"  ✗ {p}")
    print(f"\n{len(problemas)} problema(s) de versionado. Ver CONTRIBUTING.md.")
    sys.exit(1)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", help="tag que se está publicando (ej. v0.9.2)")
    args = ap.parse_args()

    problemas: list[str] = []

    version = json.loads(MANIFEST.read_text())["version"]
    print(f"manifest.json: {version}")

    # 1. El CHANGELOG tiene que traer la entrada, y una sola.
    encabezados = re.findall(r"^## (\S+)", CHANGELOG.read_text(), re.M)
    if version not in encabezados:
        problemas.append(f"CHANGELOG.md no tiene entrada '## {version}'")
    duplicados = {v for v in encabezados if encabezados.count(v) > 1}
    if duplicados:
        problemas.append(f"CHANGELOG.md tiene encabezados duplicados: {sorted(duplicados)}")

    # 2. Si estamos publicando, el tag manda.
    if args.tag:
        esperado = args.tag.lstrip("v")
        print(f"tag: {args.tag}")
        if esperado != version:
            problemas.append(
                f"el tag {args.tag} entrega un manifest que dice {version} "
                f"(un release por versión, un commit por release)"
            )

    # 3. El piso de hacs.json cubre las APIs de core que se usan.
    piso = json.loads(HACS.read_text()).get("homeassistant", "0")
    print(f"hacs.json homeassistant: {piso}")
    codigo = "\n".join(
        p.read_text() for p in (RAIZ / "custom_components" / "velador").glob("*.py")
    )
    for api, minima in APIS_DE_CORE.items():
        if api not in codigo:
            continue
        if tuple(int(x) for x in piso.split(".")[:2]) < tuple(
            int(x) for x in minima.split(".")[:2]
        ):
            problemas.append(
                f"el código usa '{api}' (HA {minima}+) pero hacs.json declara {piso}"
            )

    if problemas:
        fallar(problemas)
    print("\n✓ versionado alineado")


if __name__ == "__main__":
    main()
