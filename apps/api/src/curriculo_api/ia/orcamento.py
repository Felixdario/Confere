"""Teto de custo (ADR 0001 e 0004): interrompe ANTES de uma chamada que passaria do teto.

Um `Orcamento` por análise (`TETO_CUSTO_ANALISE_USD`), opcionalmente filho de outro (o teto de uma
execução inteira das evals, `TETO_USD`). `verificar` compara o gasto real já registrado mais o
pior caso da próxima chamada com o limite de cada nível e **reserva** esse pior caso até a chamada
terminar (`liberar`), para que duas chamadas em paralelo (currículo e vaga) não passem juntas do
teto; `registrar` soma o custo real (do `usage`) nos dois níveis.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from typing import Literal

from curriculo_api.ia.modelos import RegistroUso
from curriculo_api.ia.provedor import ErroProvedor

Escopo = Literal["analise", "execucao"]


class TetoDeCustoExcedido(ErroProvedor):
    def __init__(self, escopo: Escopo, limite: Decimal, gasto: Decimal, estimativa: Decimal):
        quem = "desta análise" if escopo == "analise" else "desta execução"
        super().__init__(
            f"teto de custo {quem} atingido: gasto US$ {gasto:.4f} + próxima chamada até "
            f"US$ {estimativa:.4f} passaria de US$ {limite:.2f}; nada foi chamado"
        )
        self.escopo: Escopo = escopo
        self.limite = limite
        self.gasto = gasto
        self.estimativa = estimativa


class Orcamento:
    def __init__(
        self, limite_usd: Decimal, *, escopo: Escopo = "analise", pai: Orcamento | None = None
    ) -> None:
        if limite_usd <= 0:
            raise ValueError("o teto precisa ser positivo")
        self.limite = limite_usd
        self.escopo: Escopo = escopo
        self.pai = pai
        self.gasto = Decimal(0)
        self.reservado = Decimal(0)

    def _checar(self, estimativa: Decimal) -> None:
        if self.pai is not None:
            self.pai._checar(estimativa)
        if self.gasto + self.reservado + estimativa > self.limite:
            raise TetoDeCustoExcedido(
                self.escopo, self.limite, self.gasto + self.reservado, estimativa
            )

    def verificar(self, estimativa: Decimal) -> None:
        """Levanta `TetoDeCustoExcedido` se a chamada pode passar do teto; senão reserva o pior
        caso (em todos os níveis) até `liberar`."""
        self._checar(estimativa)
        self._reservar(estimativa)

    def _reservar(self, valor: Decimal) -> None:
        self.reservado += valor
        if self.pai is not None:
            self.pai._reservar(valor)

    def liberar(self, estimativa: Decimal) -> None:
        self.reservado = max(Decimal(0), self.reservado - estimativa)
        if self.pai is not None:
            self.pai.liberar(estimativa)

    def consumir(self, estimativa: Decimal) -> None:
        """A chamada terminou sem `usage` (tempo esgotado, conexão caída, cancelamento): o
        servidor pode ter cobrado, então o pior caso reservado vira gasto."""
        self.reservado = max(Decimal(0), self.reservado - estimativa)
        self.gasto += estimativa
        if self.pai is not None:
            self.pai.consumir(estimativa)

    def registrar(self, usos: Iterable[RegistroUso]) -> None:
        lista = list(usos)
        self.gasto += sum((u.custo_usd for u in lista), Decimal(0))
        if self.pai is not None:
            self.pai.registrar(lista)
