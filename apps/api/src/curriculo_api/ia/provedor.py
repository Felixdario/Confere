"""A interface que o pipeline usa para falar com qualquer modelo (ADR 0001, opção B).

Diferença consciente do esboço do ADR: cada extração devolve `Resposta[T]` (saída + registros de
uso) em vez da saída pura. Assim o custo de cada chamada, novas tentativas inclusive, viaja junto
com o resultado, sem estado compartilhado no provedor (registrado em docs/decisoes.md, D-13).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from curriculo_api.ia.modelos import (
    CurriculoExtraido,
    EventoFeedback,
    Resposta,
    TabelaDaNota,
    TextoAnonimizado,
    VagaExtraida,
)


class ErroProvedor(Exception):
    """Falha do provedor com mensagem que pode ir para a tela (sem conteúdo do currículo)."""


class GravacaoAusente(ErroProvedor):
    """O provedor falso não tem resposta gravada para esta entrada."""


class ProvedorIndisponivel(ErroProvedor):
    """O provedor pedido não existe ou ainda não foi implementado."""


@runtime_checkable
class ProvedorIA(Protocol):
    @property
    def nome(self) -> str:
        """Nome do provedor ("falso" ou "anthropic"), para `/saude` e para as evals."""
        ...

    async def extrair_curriculo(self, texto: TextoAnonimizado) -> Resposta[CurriculoExtraido]: ...

    async def extrair_vaga(self, texto: str) -> Resposta[VagaExtraida]: ...

    def escrever_feedback(
        self, tabela: TabelaDaNota, curriculo: CurriculoExtraido, vaga: VagaExtraida
    ) -> AsyncIterator[EventoFeedback]: ...
