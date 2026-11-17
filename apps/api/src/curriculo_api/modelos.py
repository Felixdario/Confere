"""`make modelos`: baixa uma vez o modelo de embeddings (`MODELO_EMBEDDINGS`, ~220 MB) para
`PASTA_MODELOS` (padrão `data/modelos`, fora do git). O worker não baixa no meio de uma análise:
sem o modelo, a correspondência fica só na taxonomia e a análise avisa (ADR 0002 e 0007)."""

from __future__ import annotations

import sys

from curriculo_api.analise.embeddings import EmbutidorFastEmbed, modelo_instalado
from curriculo_api.analise.fabrica import resolver_pasta
from curriculo_api.config import obter_settings


def main() -> int:
    settings = obter_settings()
    pasta = resolver_pasta(settings.pasta_modelos)
    if modelo_instalado(pasta):
        print(f"O modelo já está em {pasta.as_posix()}.")
        return 0
    print(f"Baixando {settings.modelo_embeddings} para {pasta.as_posix()} (uma vez só)…")
    EmbutidorFastEmbed(settings.modelo_embeddings, pasta).embutir(["teste"])
    print("Pronto." if modelo_instalado(pasta) else "O download terminou, mas o ONNX não apareceu.")
    return 0 if modelo_instalado(pasta) else 1


if __name__ == "__main__":
    sys.exit(main())
