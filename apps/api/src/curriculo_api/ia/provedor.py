"""A interface que o pipeline usa para falar com qualquer modelo (ADR 0001, opção B).

Diferença consciente do esboço do ADR: cada extração devolve `Resposta[T]` (saída + registros de
uso) em vez da saída pura. Assim o custo de cada chamada, novas tentativas inclusive, viaja junto
com o resultado, sem estado compartilhado no provedor (registrado em docs/decisoes.md, D-13).

Na fase 3 cada operação ganhou `orcamento` (o teto de custo da análise, verificado antes de cada
chamada) e o feedback ganhou o texto anonimizado, de onde o modelo copia o "antes" das reescritas.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from curriculo_api.ia.modelos import (
    CurriculoExtraido,
    EventoFeedback,
    RegistroUso,
    Resposta,
    TabelaDaNota,
    TextoAnonimizado,
    VagaExtraida,
)

if TYPE_CHECKING:
    from curriculo_api.ia.orcamento import Orcamento


class ErroProvedor(Exception):
    """Falha do provedor com mensagem que pode ir para a tela (sem conteúdo do currículo).

    `usos` traz as chamadas já feitas (e cobradas) antes da falha, para o custo não sumir."""

    codigo = "erro_provedor"
    usos: tuple[RegistroUso, ...] = ()


class GravacaoAusente(ErroProvedor):
    """O provedor falso não tem resposta gravada para esta entrada."""

    codigo = "gravacao_ausente"


class ProvedorIndisponivel(ErroProvedor):
    """O provedor pedido não pode ser criado (por exemplo, sem chave)."""

    codigo = "provedor_indisponivel"


class ErroLimiteDeTaxa(ErroProvedor):
    codigo = "limite_de_taxa"


class ErroServidor(ErroProvedor):
    codigo = "erro_servidor"


class ErroConexao(ErroProvedor):
    codigo = "erro_conexao"


class ErroRequisicao(ErroProvedor):
    codigo = "requisicao_invalida"


class ErroAutenticacao(ErroProvedor):
    codigo = "autenticacao"


class TempoEsgotado(ErroProvedor):
    codigo = "tempo_esgotado"


class Recusa(ErroProvedor):
    codigo = "recusa"


class SaidaInvalida(ErroProvedor):
    codigo = "saida_invalida"


@runtime_checkable
class ProvedorIA(Protocol):
    @property
    def nome(self) -> str:
        """Nome do provedor ("falso" ou "anthropic"), para `/saude` e para as evals."""
        ...

    async def extrair_curriculo(
        self, texto: TextoAnonimizado, *, orcamento: Orcamento | None = None
    ) -> Resposta[CurriculoExtraido]: ...

    async def extrair_vaga(
        self, texto: str, *, orcamento: Orcamento | None = None
    ) -> Resposta[VagaExtraida]: ...

    def escrever_feedback(
        self,
        tabela: TabelaDaNota,
        curriculo: CurriculoExtraido,
        vaga: VagaExtraida,
        texto: TextoAnonimizado,
        *,
        orcamento: Orcamento | None = None,
    ) -> AsyncIterator[EventoFeedback]: ...
