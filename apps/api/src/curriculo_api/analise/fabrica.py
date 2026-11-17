"""Monta o `Analisador` a partir da configuração."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from curriculo_api.analise.correspondencia import Limiares
from curriculo_api.analise.embeddings import Comparador, Embutidor, EmbutidorFastEmbed
from curriculo_api.analise.pipeline import Analisador
from curriculo_api.config import Settings
from curriculo_api.ia.orcamento import Orcamento
from curriculo_api.ia.provedor import ProvedorIA
from curriculo_api.taxonomia import Taxonomia, carregar_taxonomia


def resolver_pasta(pasta: Path) -> Path:
    """Caminho relativo vale a partir da raiz do repositório (onde está `docker-compose.yml`),
    para `make` rodar de `apps/api` e achar o mesmo `data/`."""
    if pasta.is_absolute():
        return pasta
    for base in (Path.cwd(), *Path.cwd().parents):
        if (base / "docker-compose.yml").is_file():
            return base / pasta
    return Path.cwd() / pasta


def criar_analisador(
    provedor: ProvedorIA,
    settings: Settings,
    *,
    taxonomia: Taxonomia | None = None,
    embutidor: Embutidor | None = None,
    orcamento_pai: Orcamento | None = None,
    comparador: Comparador | None = None,
) -> Analisador:
    """`comparador` permite o do pgvector (`vetores_pg.ComparadorPgvector`, no worker)."""
    taxonomia = taxonomia or carregar_taxonomia()
    pasta = resolver_pasta(settings.pasta_modelos)
    embutidor = embutidor or EmbutidorFastEmbed(settings.modelo_embeddings, pasta)
    return Analisador(
        provedor,
        taxonomia,
        comparador or Comparador(taxonomia, embutidor, pasta),
        Limiares(alto=settings.tau_alto, baixo=settings.tau_baixo),
        Decimal(str(settings.teto_custo_analise_usd)),
        orcamento_pai=orcamento_pai,
    )
