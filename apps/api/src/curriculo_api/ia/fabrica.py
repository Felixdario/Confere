"""Escolha do provedor. Ponto de extensão do `ProvedorAnthropic` (fase 3, `ia/anthropic.py`)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from curriculo_api.ia.falso import ProvedorFalso
from curriculo_api.ia.provedor import ProvedorIA, ProvedorIndisponivel

NomeProvedor = Literal["falso", "anthropic"]

MENSAGEM_ANTHROPIC_PENDENTE = (
    "O provedor real (Anthropic) chega na fase 3. Por enquanto, use PROVEDOR=falso."
)


def criar_provedor(nome: NomeProvedor, *, pasta_gravacoes: Path) -> ProvedorIA:
    if nome == "falso":
        return ProvedorFalso(pasta_gravacoes)
    raise ProvedorIndisponivel(MENSAGEM_ANTHROPIC_PENDENTE)
