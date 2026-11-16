"""Ancoragem (ADR 0003, passo 2): item da IA sem trecho no texto é descartado.

Fase 1: comparação literal. A fase 3 troca `trecho_ancorado` pela comparação normalizada (espaços,
hífens de quebra de linha, aspas e caixa); o resto do código e as evals não mudam.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from curriculo_api.ia.modelos import CurriculoExtraido, Experiencia, SecaoCurriculo


class _TemTrecho(Protocol):
    @property
    def trecho(self) -> str: ...


def trecho_ancorado(trecho: str, texto: str) -> bool:
    return bool(trecho) and trecho in texto


@dataclass(frozen=True)
class ItemDescartado:
    secao: SecaoCurriculo
    trecho: str


@dataclass(frozen=True)
class ResultadoAncoragem:
    mantido: CurriculoExtraido
    descartados: tuple[ItemDescartado, ...]


def _filtrar[T: _TemTrecho](
    itens: Sequence[T], secao: SecaoCurriculo, texto: str, descartados: list[ItemDescartado]
) -> tuple[T, ...]:
    mantidos: list[T] = []
    for item in itens:
        if trecho_ancorado(item.trecho, texto):
            mantidos.append(item)
        else:
            descartados.append(ItemDescartado(secao=secao, trecho=item.trecho))
    return tuple(mantidos)


def ancorar(curriculo: CurriculoExtraido, texto: str) -> ResultadoAncoragem:
    """Filtra cada seção e renumera os índices de experiência das competências mantidas (uma
    experiência descartada some das ligações)."""
    descartados: list[ItemDescartado] = []
    novo_indice: dict[int, int] = {}
    experiencias: list[Experiencia] = []
    for i, experiencia in enumerate(curriculo.experiencias):
        if trecho_ancorado(experiencia.trecho, texto):
            novo_indice[i] = len(experiencias)
            experiencias.append(experiencia)
        else:
            descartados.append(ItemDescartado(secao="experiencias", trecho=experiencia.trecho))
    competencias = tuple(
        c.model_copy(
            update={
                "experiencias": tuple(novo_indice[i] for i in c.experiencias if i in novo_indice)
            }
        )
        for c in _filtrar(curriculo.competencias, "competencias", texto, descartados)
    )
    mantido = CurriculoExtraido(
        experiencias=tuple(experiencias),
        competencias=competencias,
        formacao=_filtrar(curriculo.formacao, "formacao", texto, descartados),
        idiomas=_filtrar(curriculo.idiomas, "idiomas", texto, descartados),
        certificacoes=_filtrar(curriculo.certificacoes, "certificacoes", texto, descartados),
    )
    return ResultadoAncoragem(mantido=mantido, descartados=tuple(descartados))
