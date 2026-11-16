"""Provedor falso: respostas gravadas, escolhidas pelo SHA-256 do texto de entrada (ADR 0001).

As gravações ficam em `evals/gravacoes/<id>.json`, uma por caso das evals, no formato exato que o
provedor real devolveria (`CurriculoExtraido` e `VagaExtraida`), com o uso zerado. Servem às evals,
aos testes e ao modo demo. São geradas a partir das anotações por `curriculo_api.evals.gravacoes`.
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from curriculo_api.ia.modelos import (
    CurriculoExtraido,
    EventoFeedback,
    RegistroUso,
    Resposta,
    TabelaDaNota,
    TextoAnonimizado,
    VagaExtraida,
)
from curriculo_api.ia.provedor import GravacaoAusente

VERSAO_GRAVACAO: Literal[1] = 1


def sha256_texto(texto: str) -> str:
    """Hash da entrada, com quebras de linha normalizadas para `\\n`."""
    return hashlib.sha256(texto.replace("\r\n", "\n").encode("utf-8")).hexdigest()


class _Modelo(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ChamadaCurriculo(_Modelo):
    entrada_sha256: str
    saida: CurriculoExtraido
    uso: RegistroUso


class ChamadaVaga(_Modelo):
    entrada_sha256: str
    saida: VagaExtraida
    uso: RegistroUso


class Gravacao(_Modelo):
    versao: Literal[1]
    id: str
    extrair_curriculo: ChamadaCurriculo
    extrair_vaga: ChamadaVaga
    escrever_feedback: tuple[EventoFeedback, ...] | None = None


def _registrar[C: (ChamadaCurriculo, ChamadaVaga)](
    indice: dict[str, C], chamada: C, origem: Path
) -> None:
    existente = indice.setdefault(chamada.entrada_sha256, chamada)
    if existente.saida != chamada.saida:
        raise ValueError(
            f"gravações conflitantes para a mesma entrada ({chamada.entrada_sha256[:12]}…): "
            f"{origem.name}"
        )


class ProvedorFalso:
    """Determinístico, sem rede e sem chave."""

    def __init__(self, pasta_gravacoes: Path) -> None:
        self._curriculos: dict[str, ChamadaCurriculo] = {}
        self._vagas: dict[str, ChamadaVaga] = {}
        arquivos = sorted(pasta_gravacoes.glob("*.json"))
        if not arquivos:
            raise GravacaoAusente(f"nenhuma gravação em {pasta_gravacoes}")
        for arquivo in arquivos:
            gravacao = Gravacao.model_validate_json(arquivo.read_text(encoding="utf-8"))
            if gravacao.id != arquivo.stem:
                raise ValueError(f"{arquivo.name}: o id {gravacao.id!r} difere do nome do arquivo")
            _registrar(self._curriculos, gravacao.extrair_curriculo, arquivo)
            _registrar(self._vagas, gravacao.extrair_vaga, arquivo)

    @property
    def nome(self) -> str:
        return "falso"

    async def extrair_curriculo(self, texto: TextoAnonimizado) -> Resposta[CurriculoExtraido]:
        chave = sha256_texto(texto)
        chamada = self._curriculos.get(chave)
        if chamada is None:
            raise GravacaoAusente(f"sem gravação para este currículo (sha256 {chave[:12]}…)")
        return Resposta(saida=chamada.saida, usos=(chamada.uso,))

    async def extrair_vaga(self, texto: str) -> Resposta[VagaExtraida]:
        chave = sha256_texto(texto)
        chamada = self._vagas.get(chave)
        if chamada is None:
            raise GravacaoAusente(f"sem gravação para esta vaga (sha256 {chave[:12]}…)")
        return Resposta(saida=chamada.saida, usos=(chamada.uso,))

    async def escrever_feedback(
        self, tabela: TabelaDaNota, curriculo: CurriculoExtraido, vaga: VagaExtraida
    ) -> AsyncIterator[EventoFeedback]:
        raise GravacaoAusente("as gravações de feedback chegam na fase 3")
        yield EventoFeedback(tipo="fim")  # torna a função um gerador assíncrono
