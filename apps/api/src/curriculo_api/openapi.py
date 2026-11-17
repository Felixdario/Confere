"""`make openapi`: grava `docs/openapi.json` (versionado; um teste confere que está em dia)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from curriculo_api.evals.dataset import localizar_raiz


def documento() -> dict[str, Any]:
    from curriculo_api.config import Settings
    from curriculo_api.main import criar_app

    # Configuração fixa: o documento não pode depender do .env de quem gera.
    esquema: dict[str, Any] = criar_app(Settings(_env_file=None)).openapi()
    return esquema


def texto() -> str:
    return json.dumps(documento(), ensure_ascii=False, indent=2, sort_keys=False) + "\n"


def caminho() -> Path:
    return localizar_raiz() / "docs" / "openapi.json"


def main() -> int:
    destino = caminho()
    destino.write_text(texto(), encoding="utf-8", newline="\n")
    print(f"OpenAPI gravado em {destino.as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
