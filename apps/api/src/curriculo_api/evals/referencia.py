"""Cálculo de referência do gabarito: a fórmula do ADR 0003 aplicada aos status ANOTADOS.

É um oráculo independente do código de produção da fase 3: os testes do dataset o usam para provar
que `nota_referencia` e `faixa_nota` de cada caso são coerentes com o ADR. Se a fase 3 calcular
diferente, um dos dois está errado, e o teste aponta qual caso.

A conta é exata (`fractions.Fraction`), com arredondamento meio para cima (ADR 0003).
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from datetime import date
from fractions import Fraction

from curriculo_api.evals.dataset import Esperado, Status
from curriculo_api.ia.modelos import DataParcial, Nivel

PESO_OBRIGATORIOS = Fraction(7, 10)
PESO_DESEJAVEIS = Fraction(2, 10)
PESO_SENIORIDADE = Fraction(1, 10)
VALOR_STATUS: dict[Status, Fraction] = {
    "atende": Fraction(1),
    "parcial": Fraction(1, 2),
    "nao_atende": Fraction(0),
}
ANOS_POR_NIVEL: dict[Nivel, int] = {"junior": 1, "pleno": 3, "senior": 5}
MARGEM_FAIXA = 5


def data_parcial(texto: str) -> DataParcial:
    """`"2019"` ou `"2019-03"` → `DataParcial`."""
    ano, _, mes = texto.partition("-")
    return DataParcial(ano=int(ano), mes=int(mes) if mes else None)


def intervalo_em_meses(inicio: str, fim: str | None, referencia: date) -> tuple[int, int]:
    """Intervalo fechado [início, fim] em índices de mês; os dois meses das pontas contam.

    Sem mês: janeiro no início, dezembro no fim ("2024" = 12 meses). Sem fim (emprego atual): vai
    até o mês da data de referência, inclusive. O fim nunca passa do mês da referência (rodada 1
    da fase 3); um início depois dela dá um intervalo vazio (fim < início), que a união ignora.
    """
    comeco = data_parcial(inicio).indice_inicio()
    mes_referencia = referencia.year * 12 + referencia.month - 1
    final = mes_referencia if fim is None else data_parcial(fim).indice_fim()
    if final < comeco:
        raise ValueError(f"fim antes do início: {inicio} → {fim}")
    return comeco, min(final, mes_referencia)


def meses_da_uniao(intervalos: Iterable[tuple[int, int]]) -> int:
    """Meses cobertos pela união de intervalos fechados: sobreposição conta uma vez, e intervalos
    consecutivos (jul → ago) se emendam sem buraco (ADR 0003)."""
    total = 0
    atual: tuple[int, int] | None = None
    for comeco, final in sorted((a, b) for a, b in intervalos if b >= a):
        if atual is None or comeco > atual[1] + 1:
            if atual is not None:
                total += atual[1] - atual[0] + 1
            atual = (comeco, final)
        else:
            atual = (atual[0], max(atual[1], final))
    if atual is not None:
        total += atual[1] - atual[0] + 1
    return total


def anos_minimos_efetivos(anos_minimos: int | None, nivel: Nivel | None) -> int | None:
    """Anos explícitos da vaga; senão, os do nível (júnior 1, pleno 3, sênior 5); senão, nada."""
    if anos_minimos is not None:
        return anos_minimos
    return ANOS_POR_NIVEL[nivel] if nivel is not None else None


def _media(statuses: Sequence[Status]) -> Fraction:
    return sum((VALOR_STATUS[s] for s in statuses), Fraction(0)) / len(statuses)


def senioridade(meses_relevantes: int, anos_minimos: int) -> Fraction:
    """S = min(1, anos comprovados ÷ anos mínimos)."""
    if anos_minimos == 0:
        return Fraction(1)
    return min(Fraction(1), Fraction(meses_relevantes, 12) / anos_minimos)


def arredondar_meio_para_cima(valor: Fraction) -> int:
    return math.floor(valor + Fraction(1, 2))


def calcular_nota(
    obrigatorios: Sequence[Status],
    desejaveis: Sequence[Status],
    meses_relevantes: int,
    anos_minimos: int | None,
) -> int:
    """A nota do ADR 0003, com renormalização dos componentes ausentes e meio para cima."""
    if not obrigatorios and not desejaveis:
        raise ValueError("a vaga não tem requisitos reconhecíveis")
    numerador = Fraction(0)
    pesos = Fraction(0)
    if obrigatorios:
        numerador += PESO_OBRIGATORIOS * _media(obrigatorios)
        pesos += PESO_OBRIGATORIOS
    if desejaveis:
        numerador += PESO_DESEJAVEIS * _media(desejaveis)
        pesos += PESO_DESEJAVEIS
    if anos_minimos is not None:
        numerador += PESO_SENIORIDADE * senioridade(meses_relevantes, anos_minimos)
        pesos += PESO_SENIORIDADE
    return arredondar_meio_para_cima(100 * numerador / pesos)


def faixa_de(nota: int) -> tuple[int, int]:
    """Nota ± 5, truncada em 0–100 (decisão D-15)."""
    return max(0, nota - MARGEM_FAIXA), min(100, nota + MARGEM_FAIXA)


def meses_relevantes(esperado: Esperado, referencia: date) -> int:
    return meses_da_uniao(
        intervalo_em_meses(e.inicio, e.fim, referencia)
        for e in esperado.experiencias
        if e.relevante
    )


def nota_de_referencia(esperado: Esperado, referencia: date) -> int:
    obrigatorios = [r.status_esperado for r in esperado.requisitos if r.tipo == "obrigatorio"]
    desejaveis = [r.status_esperado for r in esperado.requisitos if r.tipo == "desejavel"]
    return calcular_nota(
        obrigatorios,
        desejaveis,
        meses_relevantes(esperado, referencia),
        anos_minimos_efetivos(esperado.anos_minimos, esperado.nivel),
    )
