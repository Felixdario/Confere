"""Meses de experiência (ADR 0003, "Contagem de meses").

Implementação própria, de propósito separada do oráculo das evals (`evals/referencia.py`): o teste
que compara as duas notas só prova alguma coisa se as contas forem feitas duas vezes.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from curriculo_api.ia.modelos import Experiencia


def mes_de(referencia: date) -> int:
    return referencia.year * 12 + referencia.month - 1


def intervalo(experiencia: Experiencia, referencia: date) -> tuple[int, int]:
    """[início, fim] em índices de mês, fechado. Sem mês: janeiro no início e dezembro no fim.
    Sem fim (emprego atual): até o mês da referência, inclusive. O fim é limitado ao mês da
    referência (rodada 1 da fase 3: "2025–2035" não conta anos que ainda não aconteceram), e um
    início no futuro dá um intervalo vazio (fim < início), que não conta."""
    comeco = experiencia.inicio.indice_inicio()
    if not experiencia.datas_comprovadas:
        return comeco, comeco - 1  # vazio: sem datas comprovadas, não conta anos
    final = mes_de(referencia) if experiencia.fim is None else experiencia.fim.indice_fim()
    return comeco, min(final, mes_de(referencia))


def data_no_futuro(experiencia: Experiencia, referencia: date) -> bool:
    """Início ou fim depois do mês da referência: a tela avisa e o excedente não conta."""
    limite = mes_de(referencia)
    return experiencia.inicio.indice_inicio() > limite or (
        experiencia.fim is not None and experiencia.fim.indice_fim() > limite
    )


def meses_cobertos(intervalos: Iterable[tuple[int, int]]) -> int:
    """Meses da união: sobreposição conta uma vez; jul → ago emendam sem buraco."""
    validos = sorted((a, b) for a, b in intervalos if b >= a)
    total = 0
    atual_inicio: int | None = None
    atual_fim = 0
    for comeco, final in validos:
        if atual_inicio is None:
            atual_inicio, atual_fim = comeco, final
        elif comeco <= atual_fim + 1:
            atual_fim = max(atual_fim, final)
        else:
            total += atual_fim - atual_inicio + 1
            atual_inicio, atual_fim = comeco, final
    if atual_inicio is not None:
        total += atual_fim - atual_inicio + 1
    return total


def sem_mes(experiencia: Experiencia) -> bool:
    return experiencia.inicio.mes is None or (
        experiencia.fim is not None and experiencia.fim.mes is None
    )
