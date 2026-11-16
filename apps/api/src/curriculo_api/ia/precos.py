"""Tabela de preços versionada e custo de cada chamada a partir do `usage` (ADR 0001).

Fonte: https://platform.claude.com/docs/en/about-claude/pricing (tabela "Model pricing"), lida em
2026-11-16. Preços em US$ por milhão de tokens (MTok). O cache de 5 minutos é o padrão do
`cache_control: {"type": "ephemeral"}`; o de 1 hora só vale quando o `usage` o informa.

O Claude Haiku 5.5 tem dois preços pelo tamanho do prompt: até 100.000 tokens e acima disso. O
tamanho conta todos os tokens de entrada, inclusive leituras e escritas de cache, e cada requisição
é cobrada inteira pela faixa em que cai.

Os modelos de reserva do fallback do servidor (Claude Opus 5 e Claude Opus 4.8) estão na tabela
porque podem responder no lugar do Opus 5.5 e cobram pelo próprio preço.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

VERSAO_PRECOS = "2026-11-16"
FONTE_PRECOS = "https://platform.claude.com/docs/en/about-claude/pricing"
MILHAO = Decimal(1_000_000)


@dataclass(frozen=True)
class Preco:
    entrada: Decimal
    saida: Decimal
    cache_escrita_5m: Decimal
    cache_escrita_1h: Decimal
    cache_leitura: Decimal


@dataclass(frozen=True)
class PrecoModelo:
    padrao: Preco
    acima_de: int | None = None
    """Acima deste número de tokens de prompt, vale `longo` (só o Haiku 5.5)."""
    longo: Preco | None = None

    def para(self, tokens_de_prompt: int) -> Preco:
        if (
            self.acima_de is not None
            and self.longo is not None
            and tokens_de_prompt > self.acima_de
        ):
            return self.longo
        return self.padrao


def _p(entrada: str, escrita_5m: str, escrita_1h: str, leitura: str, saida: str) -> Preco:
    return Preco(
        entrada=Decimal(entrada),
        saida=Decimal(saida),
        cache_escrita_5m=Decimal(escrita_5m),
        cache_escrita_1h=Decimal(escrita_1h),
        cache_leitura=Decimal(leitura),
    )


# Colunas na ordem da página: entrada, escrita 5 min, escrita 1 h, leitura (hits), saída.
PRECOS: dict[str, PrecoModelo] = {
    "claude-haiku-5-5": PrecoModelo(
        padrao=_p("0.10", "0.125", "0.20", "0.01", "0.50"),
        acima_de=100_000,
        longo=_p("0.50", "0.625", "1", "0.05", "2.50"),
    ),
    "claude-sonnet-5-5": PrecoModelo(padrao=_p("2", "2.50", "4", "0.10", "10")),
    "claude-opus-5-5": PrecoModelo(padrao=_p("4", "5", "8", "0.20", "20")),
    "claude-opus-5": PrecoModelo(padrao=_p("5", "6.25", "10", "0.50", "25")),
    "claude-opus-4-8": PrecoModelo(padrao=_p("5", "6.25", "10", "0.50", "25")),
}


class PrecoDesconhecido(LookupError):
    def __init__(self, modelo: str) -> None:
        super().__init__(
            f"o modelo {modelo!r} não está na tabela de preços ({VERSAO_PRECOS}); acrescente-o em "
            "curriculo_api/ia/precos.py, conferido na página oficial, antes de usá-lo"
        )
        self.modelo = modelo


def preco_de(modelo: str) -> PrecoModelo:
    try:
        return PRECOS[modelo]
    except KeyError:
        raise PrecoDesconhecido(modelo) from None


@dataclass(frozen=True)
class Tokens:
    entrada: int = 0
    saida: int = 0
    cache_escrita_5m: int = 0
    cache_escrita_1h: int = 0
    cache_leitura: int = 0

    @property
    def prompt(self) -> int:
        return self.entrada + self.cache_escrita_5m + self.cache_escrita_1h + self.cache_leitura

    @property
    def cache_escrita(self) -> int:
        return self.cache_escrita_5m + self.cache_escrita_1h


def custo(modelo: str, tokens: Tokens) -> Decimal:
    preco = preco_de(modelo).para(tokens.prompt)
    total = (
        tokens.entrada * preco.entrada
        + tokens.saida * preco.saida
        + tokens.cache_escrita_5m * preco.cache_escrita_5m
        + tokens.cache_escrita_1h * preco.cache_escrita_1h
        + tokens.cache_leitura * preco.cache_leitura
    )
    return total / MILHAO


def custo_maximo(modelo: str, tokens_entrada: int, tokens_saida: int) -> Decimal:
    """Teto de uma chamada ainda não feita: toda a entrada pelo preço da escrita em cache (o
    mais caro dos preços de entrada) e a saída inteira (`max_tokens`)."""
    return custo(modelo, Tokens(cache_escrita_5m=tokens_entrada, saida=tokens_saida))
