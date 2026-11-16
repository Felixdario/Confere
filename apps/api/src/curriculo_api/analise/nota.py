"""A nota de aderência em código (ADR 0003, passo 4). Função pura, conta exata com `Fraction`.

    O = média dos valores dos obrigatórios; D = média dos desejáveis;
    S = min(1, anos relevantes ÷ anos mínimos)  (anos da vaga, ou do nível: 1/3/5)
    nota = round½↑(100 × (0,70·O + 0,20·D + 0,10·S) ÷ soma dos pesos presentes)

Componente ausente sai do numerador e do denominador. As parcelas da tela já vêm renormalizadas,
para que somem a nota. A nota nunca é lida de uma resposta da IA.
"""

from __future__ import annotations

import math
from collections.abc import Collection, Sequence
from datetime import date
from fractions import Fraction
from typing import Literal

from curriculo_api.analise.erros import VagaSemRequisitos
from curriculo_api.analise.formatacao import decimal_br
from curriculo_api.analise.periodos import data_no_futuro, intervalo, meses_cobertos, sem_mes
from curriculo_api.ia.modelos import (
    CurriculoExtraido,
    LinhaRequisito,
    Nivel,
    Parcela,
    TabelaDaNota,
    VagaExtraida,
)
from curriculo_api.taxonomia import Taxonomia, normalizar_termo

PESOS: dict[Literal["obrigatorios", "desejaveis", "senioridade"], Fraction] = {
    "obrigatorios": Fraction(7, 10),
    "desejaveis": Fraction(2, 10),
    "senioridade": Fraction(1, 10),
}
ANOS_DO_NIVEL: dict[Nivel, int] = {"junior": 1, "pleno": 3, "senior": 5}

AVISO_SEM_DESEJAVEIS = "a vaga não lista desejáveis; os pesos foram redistribuídos"
AVISO_SEM_OBRIGATORIOS = "a vaga não lista obrigatórios; os pesos foram redistribuídos"
AVISO_SEM_SENIORIDADE = (
    "a vaga não cita anos nem nível; a senioridade ficou de fora e os pesos foram redistribuídos"
)
AVISO_DATAS_NO_FUTURO = (
    "há experiência com data depois da data da análise: o período no futuro não conta nos anos"
)
AVISO_DATAS_NAO_COMPROVADAS = (
    "há experiência cujas datas o trecho do currículo não comprova: ela não conta nos anos"
)
AVISO_DATAS_SEM_MES = (
    "há datas sem mês nas experiências que contam: contamos janeiro no início e dezembro no fim"
)


def anos_minimos_da_vaga(vaga: VagaExtraida) -> int | None:
    if vaga.anos_minimos is not None:
        return vaga.anos_minimos
    return ANOS_DO_NIVEL[vaga.nivel] if vaga.nivel is not None else None


def arredondar(valor: Fraction) -> int:
    """Meio para cima: 67,5 → 68 e 66,5 → 67 (não o arredondamento bancário do `round`)."""
    return math.floor(valor + Fraction(1, 2))


def experiencias_relevantes(
    curriculo: CurriculoExtraido, chaves: Collection[str], taxonomia: Taxonomia
) -> list[int]:
    """Índices das experiências com uma competência ligada que é (ou é relacionada a) um
    obrigatório atendido ou parcial (ADR 0003, "Anos relevantes comprovados")."""
    relevantes: set[int] = set()
    for competencia in curriculo.competencias:
        canonica = taxonomia.canonica_de(competencia.nome)
        chave = canonica if canonica is not None else normalizar_termo(competencia.nome)
        relacionadas = taxonomia.relacionadas_de(canonica) if canonica is not None else frozenset()
        if chave in chaves or relacionadas & set(chaves):
            relevantes.update(competencia.experiencias)
    return sorted(i for i in relevantes if 0 <= i < len(curriculo.experiencias))


def _media(linhas: Sequence[LinhaRequisito]) -> Fraction:
    return sum((Fraction(linha.valor) for linha in linhas), Fraction(0)) / len(linhas)


def calcular_nota(
    obrigatorios: Sequence[Fraction],
    desejaveis: Sequence[Fraction],
    senioridade: Fraction | None,
) -> int:
    """A fórmula pura sobre valores já decididos (cada um em {0, 1/2, 1})."""
    if not obrigatorios and not desejaveis:
        raise VagaSemRequisitos()
    numerador = Fraction(0)
    pesos = Fraction(0)
    if obrigatorios:
        numerador += PESOS["obrigatorios"] * sum(obrigatorios, Fraction(0)) / len(obrigatorios)
        pesos += PESOS["obrigatorios"]
    if desejaveis:
        numerador += PESOS["desejaveis"] * sum(desejaveis, Fraction(0)) / len(desejaveis)
        pesos += PESOS["desejaveis"]
    if senioridade is not None:
        numerador += PESOS["senioridade"] * senioridade
        pesos += PESOS["senioridade"]
    return arredondar(100 * numerador / pesos)


def calcular_tabela(
    linhas: Sequence[LinhaRequisito],
    curriculo: CurriculoExtraido,
    vaga: VagaExtraida,
    chaves_atendidas: Collection[str],
    taxonomia: Taxonomia,
    data_referencia: date,
) -> TabelaDaNota:
    obrigatorios = [linha for linha in linhas if linha.tipo == "obrigatorio"]
    desejaveis = [linha for linha in linhas if linha.tipo == "desejavel"]
    if not obrigatorios and not desejaveis:
        raise VagaSemRequisitos()
    anos_minimos = anos_minimos_da_vaga(vaga)
    relevantes = experiencias_relevantes(curriculo, chaves_atendidas, taxonomia)
    meses = meses_cobertos(
        intervalo(curriculo.experiencias[i], data_referencia) for i in relevantes
    )
    anos = Fraction(meses, 12)

    componentes: list[tuple[Literal["obrigatorios", "desejaveis", "senioridade"], Fraction, str]]
    componentes = []
    avisos: list[str] = []
    if obrigatorios:
        soma = sum((Fraction(linha.valor) for linha in obrigatorios), Fraction(0))
        texto = f"obrigatórios {decimal_br(soma, 1, cortar_zero=True)} de {len(obrigatorios)}"
        componentes.append(("obrigatorios", _media(obrigatorios), texto))
    else:
        avisos.append(AVISO_SEM_OBRIGATORIOS)
    if desejaveis:
        soma = sum((Fraction(linha.valor) for linha in desejaveis), Fraction(0))
        texto = f"desejáveis {decimal_br(soma, 1, cortar_zero=True)} de {len(desejaveis)}"
        componentes.append(("desejaveis", _media(desejaveis), texto))
    else:
        avisos.append(AVISO_SEM_DESEJAVEIS)
    if anos_minimos is not None:
        s = Fraction(1) if anos_minimos == 0 else min(Fraction(1), anos / anos_minimos)
        texto = f"senioridade {decimal_br(anos, 1, cortar_zero=True)}/{anos_minimos} anos"
        componentes.append(("senioridade", s, texto))
    else:
        avisos.append(AVISO_SEM_SENIORIDADE)
    if any(sem_mes(curriculo.experiencias[i]) for i in relevantes):
        avisos.append(AVISO_DATAS_SEM_MES)
    if any(not e.datas_comprovadas for e in curriculo.experiencias):
        avisos.append(AVISO_DATAS_NAO_COMPROVADAS)
    if any(data_no_futuro(e, data_referencia) for e in curriculo.experiencias):
        avisos.append(AVISO_DATAS_NO_FUTURO)

    soma_pesos = sum((PESOS[c] for c, _, _ in componentes), Fraction(0))
    parcelas: list[Parcela] = []
    total = Fraction(0)
    for componente, valor, texto in componentes:
        pontos = 100 * PESOS[componente] * valor / soma_pesos
        total += pontos
        exibicao = decimal_br(pontos, 1)
        parcelas.append(
            Parcela(
                componente=componente,
                peso=str(PESOS[componente]),
                valor=str(valor),
                pontos=str(pontos),
                pontos_exibicao=exibicao,
                resumo=f"{texto} → {exibicao}",
            )
        )
    nota = arredondar(total)
    if nota != calcular_nota(
        [Fraction(linha.valor) for linha in obrigatorios],
        [Fraction(linha.valor) for linha in desejaveis],
        None
        if anos_minimos is None
        else (Fraction(1) if anos_minimos == 0 else min(Fraction(1), anos / anos_minimos)),
    ):
        raise AssertionError("a soma das parcelas difere da fórmula")  # pragma: no cover
    return TabelaDaNota(
        nota=nota,
        linhas=tuple(linhas),
        parcelas=tuple(parcelas),
        anos_relevantes=round(float(anos), 2),
        anos_minimos=anos_minimos,
        avisos=tuple(avisos),
        decomposicao=" · ".join([*(p.resumo for p in parcelas), f"nota {nota}"]),
    )
