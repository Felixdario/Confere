"""Correspondência requisito → evidência, em código (ADR 0002 e ADR 0003, passo 3).

Ordem de decisão para cada requisito:
1. A competência pedida vira canônica pela taxonomia (canônica ou sinônimo). Fora dela, pela
   canônica mais parecida no embedding, se o cosseno passar de τ_alto.
2. Um item ancorado do currículo (competência, idioma ou certificação) com a mesma canônica →
   **atende** ("mesma competência" ou "sinônimo na taxonomia"). Item fora da taxonomia cuja canônica
   mais parecida é a pedida, com cosseno ≥ τ_alto, também atende ("similaridade").
3. Uma canônica "relacionada" na taxonomia → **parcial**. Só a taxonomia decide "relacionada"; um
   requisito que só foi reconhecido pelo embedding não ganha parcial por relação.
4. Senão, similaridade direta entre o termo pedido e os itens que a taxonomia não conhece (ou todos,
   se o pedido também está fora dela): ≥ τ_alto atende, entre τ_baixo e τ_alto parcial, senão
   **não atende**. Itens com uma canônica diferente da pedida nunca entram aqui: é o que impede
   "JavaScript" de atender "Java".
5. Um "atende" vira **parcial** se o requisito pede anos e os anos da competência (união das
   experiências ligadas a ela) não alcançam o pedido, ou se pede um nível e o currículo declara um
   nível abaixo. Sem nível declarado, a evidência basta.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from fractions import Fraction
from typing import Literal

from curriculo_api.analise.embeddings import Comparador
from curriculo_api.analise.formatacao import decimal_br
from curriculo_api.analise.niveis import ORDEM, ROTULO, abaixo, nivel_de
from curriculo_api.analise.periodos import intervalo, meses_cobertos
from curriculo_api.ia.modelos import (
    CurriculoExtraido,
    LinhaRequisito,
    NivelProficiencia,
    RegraCorrespondencia,
    Requisito,
    StatusRequisito,
    VagaExtraida,
)
from curriculo_api.taxonomia import Taxonomia, normalizar_termo

VALOR: dict[StatusRequisito, Fraction] = {
    "atende": Fraction(1),
    "parcial": Fraction(1, 2),
    "nao_atende": Fraction(0),
}


@dataclass(frozen=True)
class Limiares:
    alto: float = 0.85
    baixo: float = 0.70

    def __post_init__(self) -> None:
        if not 0 <= self.baixo <= self.alto <= 1:
            raise ValueError("os limiares precisam de 0 ≤ τ_baixo ≤ τ_alto ≤ 1")


@dataclass(frozen=True)
class Evidencia:
    nome: str
    canonica: str | None
    trecho: str
    experiencias: tuple[int, ...]
    nivel: NivelProficiencia | None
    origem: Literal["competencia", "idioma", "certificacao"]

    @property
    def chave(self) -> str:
        return self.canonica if self.canonica is not None else normalizar_termo(self.nome)


@dataclass
class ResultadoCorrespondencia:
    linhas: tuple[LinhaRequisito, ...]
    chaves_atendidas: frozenset[str] = field(default_factory=frozenset)
    """Chaves (canônicas ou termos normalizados) dos obrigatórios atendidos ou parciais e das
    evidências que os atenderam: definem as experiências relevantes da senioridade."""
    consultas_embedding: int = 0


def sufixo_distintivo(a: str, b: str) -> bool:
    """Depois de tirar as palavras em comum, sobra uma sigla ou palavra curta (até 3 caracteres,
    ou com dígito) de um dos lados: "SAP FI" × "SAP MM", "Vendas B2B" × "Vendas B2C", "Excel" ×
    "Excel VBA". Nesses pares o embedding nunca dá "atende" (no máximo parcial): a parte que
    diferencia é justamente a que o embedding mal enxerga."""
    pa = set(re.findall(r"[\w#+]+", normalizar_termo(a)))
    pb = set(re.findall(r"[\w#+]+", normalizar_termo(b)))
    if not pa & pb:
        return False
    sobras = pa ^ pb
    return any(len(p) <= 3 or any(ch.isdigit() for ch in p) for p in sobras)


def evidencias_de(curriculo: CurriculoExtraido, taxonomia: Taxonomia) -> list[Evidencia]:
    itens: list[Evidencia] = [
        Evidencia(
            nome=c.nome,
            canonica=taxonomia.canonica_de(c.nome),
            trecho=c.trecho,
            experiencias=c.experiencias,
            nivel=nivel_de(c.trecho),
            origem="competencia",
        )
        for c in curriculo.competencias
    ]
    itens += [
        Evidencia(
            nome=i.idioma,
            canonica=taxonomia.canonica_de(i.idioma),
            trecho=i.trecho,
            experiencias=(),
            nivel=nivel_de(i.trecho),
            origem="idioma",
        )
        for i in curriculo.idiomas
    ]
    itens += [
        Evidencia(
            nome=c.nome,
            canonica=(taxonomia.canonica_de(c.competencia) if c.competencia else None)
            or taxonomia.canonica_de(c.nome),
            trecho=c.trecho,
            experiencias=(),
            nivel=None,
            origem="certificacao",
        )
        for c in curriculo.certificacoes
    ]
    return itens


def _anos(meses: int) -> str:
    return decimal_br(Fraction(meses, 12), 1, cortar_zero=True)


@dataclass(frozen=True)
class _Decisao:
    status: StatusRequisito
    regra: RegraCorrespondencia
    evidencia: Evidencia | None = None
    similaridade: float | None = None
    motivo: str = ""


class Correspondente:
    def __init__(
        self,
        taxonomia: Taxonomia,
        comparador: Comparador,
        limiares: Limiares,
        data_referencia: date,
    ) -> None:
        self._taxonomia = taxonomia
        self._comparador = comparador
        self._limiares = limiares
        self._referencia = data_referencia

    # --- embeddings -------------------------------------------------------------------------

    def _canonica_por_similaridade(self, termo: str) -> tuple[str, float] | None:
        canonica, termo_tax, sim = self._comparador.canonica_mais_proxima(termo)
        if sim < self._limiares.alto or sufixo_distintivo(termo, termo_tax):
            return None
        return canonica, sim

    # --- decisão ----------------------------------------------------------------------------

    def _decidir(self, requisito: Requisito, itens: Sequence[Evidencia]) -> tuple[_Decisao, str]:
        pedido = requisito.competencia
        canonica = self._taxonomia.canonica_de(pedido)
        sim_pedido: float | None = None
        if canonica is None:
            mapeada = self._canonica_por_similaridade(pedido)
            if mapeada is not None:
                canonica, sim_pedido = mapeada
        chave_pedida = canonica if canonica is not None else normalizar_termo(pedido)
        tau_a = decimal_br(Fraction(self._limiares.alto).limit_denominator(1000), 2)

        if canonica is not None:
            iguais = [i for i in itens if i.canonica == canonica]
            if iguais:
                item = max(iguais, key=lambda i: (i.nivel is not None, i.origem == "competencia"))
                if sim_pedido is not None:
                    motivo = (
                        f"'{pedido}' não está na taxonomia; similaridade {sim_pedido:.2f} com "
                        f"{canonica} (≥ τ_alto {tau_a}), comprovada por '{item.nome}'"
                    )
                    return _Decisao(
                        "atende", "similaridade", item, sim_pedido, motivo
                    ), chave_pedida
                if normalizar_termo(item.nome) == normalizar_termo(canonica):
                    motivo = f"'{item.nome}' no currículo é a competência pedida"
                    return _Decisao("atende", "mesma_competencia", item, None, motivo), chave_pedida
                motivo = f"'{item.nome}' é sinônimo de {canonica} na taxonomia"
                return _Decisao("atende", "sinonimo_na_taxonomia", item, None, motivo), chave_pedida
            for item in itens:
                if item.canonica is not None:
                    continue
                mapeada = self._canonica_por_similaridade(item.nome)
                if mapeada is not None and mapeada[0] == canonica:
                    motivo = (
                        f"'{item.nome}' não está na taxonomia; similaridade {mapeada[1]:.2f} com "
                        f"{canonica} (≥ τ_alto {tau_a})"
                    )
                    return (
                        _Decisao("atende", "similaridade", item, mapeada[1], motivo),
                        chave_pedida,
                    )
            if sim_pedido is None:
                relacionadas = self._taxonomia.relacionadas_de(canonica)
                parecidos = [i for i in itens if i.canonica in relacionadas]
                if parecidos:
                    item = parecidos[0]
                    motivo = (
                        f"'{item.nome}' ({item.canonica}) é relacionada a {canonica} na "
                        "taxonomia: vale parcial"
                    )
                    return (
                        _Decisao("parcial", "relacionada_na_taxonomia", item, None, motivo),
                        chave_pedida,
                    )

        candidatos = [i for i in itens if canonica is None or i.canonica is None]
        if candidatos:
            sims = self._comparador.similaridades(pedido, [i.nome for i in candidatos])
            melhor = max(range(len(candidatos)), key=lambda k: sims[k])
            item, sim = candidatos[melhor], sims[melhor]
            if sim >= self._limiares.alto and not sufixo_distintivo(pedido, item.nome):
                motivo = f"similaridade {sim:.2f} entre '{pedido}' e '{item.nome}' (≥ τ_alto)"
                return _Decisao("atende", "similaridade", item, sim, motivo), chave_pedida
            if sim >= self._limiares.alto:
                motivo = (
                    f"similaridade {sim:.2f} entre '{pedido}' e '{item.nome}', mas os termos "
                    "diferem numa sigla ou palavra curta: vale parcial, nunca atende"
                )
                return _Decisao("parcial", "similaridade", item, sim, motivo), chave_pedida
            if sim >= self._limiares.baixo:
                motivo = (
                    f"similaridade {sim:.2f} entre '{pedido}' e '{item.nome}', entre τ_baixo e "
                    "τ_alto: vale parcial"
                )
                return _Decisao("parcial", "similaridade", item, sim, motivo), chave_pedida
        motivo = f"nenhuma evidência de {canonica or pedido} no currículo"
        return _Decisao("nao_atende", "sem_evidencia", None, None, motivo), chave_pedida

    def _meses_da_competencia(
        self, curriculo: CurriculoExtraido, itens: Sequence[Evidencia], chave: str
    ) -> int:
        indices = {i for item in itens if item.chave == chave for i in item.experiencias}
        return meses_cobertos(
            intervalo(e, self._referencia)
            for k, e in enumerate(curriculo.experiencias)
            if k in indices
        )

    def corresponder(
        self, curriculo: CurriculoExtraido, vaga: VagaExtraida
    ) -> ResultadoCorrespondencia:
        consultas_antes = self._comparador.consultas
        itens = evidencias_de(curriculo, self._taxonomia)
        linhas: list[LinhaRequisito] = []
        chaves: set[str] = set()
        for requisito in vaga.requisitos:
            decisao, chave_pedida = self._decidir(requisito, itens)
            status, motivo = decisao.status, decisao.motivo
            anos_comprovados: float | None = None
            nivel_declarado: NivelProficiencia | None = None
            item = decisao.evidencia
            if status == "atende" and item is not None:
                if requisito.anos_minimos:
                    meses = self._meses_da_competencia(curriculo, itens, item.chave)
                    anos_comprovados = round(meses / 12, 2)
                    if meses < 12 * requisito.anos_minimos:
                        status = "parcial"
                        motivo += (
                            f"; mas só {_anos(meses)} de {requisito.anos_minimos} anos "
                            f"comprovados com {item.nome}: vale parcial"
                        )
                nivel_pedido = requisito.nivel
                if nivel_pedido is not None:
                    declarados = [
                        n for i in itens if i.chave == item.chave and (n := i.nivel) is not None
                    ]
                    if declarados:
                        maior = max(declarados, key=lambda n: ORDEM[n])
                        nivel_declarado = maior
                        if abaixo(maior, nivel_pedido):
                            status = "parcial"
                            motivo += (
                                f"; o currículo declara nível {ROTULO[maior]}, abaixo "
                                f"do pedido ({ROTULO[nivel_pedido]}): vale parcial"
                            )
            if requisito.tipo == "obrigatorio" and status != "nao_atende":
                chaves.add(chave_pedida)
                if item is not None:
                    chaves.add(item.chave)
            linhas.append(
                LinhaRequisito(
                    descricao=requisito.descricao,
                    tipo=requisito.tipo,
                    competencia_pedida=chave_pedida
                    if chave_pedida in self._taxonomia.canonicas
                    else requisito.competencia,
                    status=status,
                    valor=str(VALOR[status]),
                    regra=decisao.regra,
                    competencia_casada=item.nome if item is not None else None,
                    similaridade=round(decisao.similaridade, 4)
                    if decisao.similaridade is not None
                    else None,
                    evidencia=item.trecho if item is not None else None,
                    anos_pedidos=requisito.anos_minimos,
                    anos_comprovados=anos_comprovados,
                    nivel_pedido=requisito.nivel,
                    nivel_declarado=nivel_declarado,
                    motivo=motivo,
                )
            )
        return ResultadoCorrespondencia(
            linhas=tuple(linhas),
            chaves_atendidas=frozenset(chaves),
            consultas_embedding=self._comparador.consultas - consultas_antes,
        )
