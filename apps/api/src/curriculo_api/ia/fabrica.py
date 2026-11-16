"""Escolha do provedor (ADR 0001). O real só existe com `ANTHROPIC_API_KEY` definida."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from curriculo_api.config import Settings, obter_settings
from curriculo_api.ia.falso import ProvedorFalso
from curriculo_api.ia.precos import PrecoDesconhecido
from curriculo_api.ia.provedor import ProvedorIA, ProvedorIndisponivel
from curriculo_api.taxonomia import carregar_taxonomia

NomeProvedor = Literal["falso", "anthropic"]

MENSAGEM_SEM_CHAVE = (
    "ANTHROPIC_API_KEY não está definida, então o provedor real não pode rodar. Defina a chave "
    "no ambiente ou no .env (nunca no git) e rode de novo, ou use PROVEDOR=falso, que funciona "
    "sem rede e sem chave."
)


def criar_provedor(
    nome: NomeProvedor, *, pasta_gravacoes: Path, settings: Settings | None = None
) -> ProvedorIA:
    if nome == "falso":
        return ProvedorFalso(pasta_gravacoes)
    settings = settings or obter_settings()
    if settings.usa_provedor_falso or settings.anthropic_api_key is None:
        raise ProvedorIndisponivel(MENSAGEM_SEM_CHAVE)
    import anthropic

    from curriculo_api.ia.anthropic import ConfigAnthropic, ProvedorAnthropic

    cliente = anthropic.AsyncAnthropic(
        api_key=settings.anthropic_api_key.get_secret_value(),
        max_retries=settings.claude_max_retries,
    )
    try:
        return ProvedorAnthropic(
            cliente, carregar_taxonomia(), ConfigAnthropic.de_settings(settings)
        )
    except PrecoDesconhecido as exc:
        raise ProvedorIndisponivel(str(exc)) from exc
