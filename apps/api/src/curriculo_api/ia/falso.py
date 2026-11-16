"""Provedor falso: respostas gravadas, escolhidas pelo SHA-256 do texto de entrada (ADR 0001).

As gravações ficam em `evals/gravacoes/<id>.json`, uma por caso das evals, no formato exato que o
provedor real devolveria (`CurriculoExtraido`, `VagaExtraida` e `FeedbackIA`), com o uso zerado.
Servem às evals, aos testes e ao modo demo. São geradas a partir das anotações (e, no feedback, de
`evals/casos/<base>/feedback.yaml`, texto de demonstração) por `curriculo_api.evals.gravacoes`.

O feedback é escolhido pelo mesmo hash do texto anonimizado do currículo e sai em eventos como o
real: `etapa`, pedaços de `texto` (o JSON da saída, em fatias) e `final`.
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field

from curriculo_api.ia.modelos import (
    CurriculoExtraido,
    EventoFeedback,
    FeedbackIA,
    RegistroUso,
    Resposta,
    TabelaDaNota,
    TextoAnonimizado,
    VagaExtraida,
)
from curriculo_api.ia.provedor import GravacaoAusente

if TYPE_CHECKING:
    from curriculo_api.ia.orcamento import Orcamento

VERSAO_GRAVACAO: Literal[2] = 2
TAMANHO_DO_PEDACO = 120


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


class ChamadaFeedback(_Modelo):
    entrada_sha256: str = Field(description="O hash do texto anonimizado do currículo.")
    saida: FeedbackIA
    uso: RegistroUso


class Gravacao(_Modelo):
    versao: Literal[2]
    id: str
    extrair_curriculo: ChamadaCurriculo
    extrair_vaga: ChamadaVaga
    escrever_feedback: ChamadaFeedback


def _registrar[C: (ChamadaCurriculo, ChamadaVaga, ChamadaFeedback)](
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
        self._feedbacks: dict[str, ChamadaFeedback] = {}
        arquivos = sorted(pasta_gravacoes.glob("*.json"))
        if not arquivos:
            raise GravacaoAusente(f"nenhuma gravação em {pasta_gravacoes}")
        for arquivo in arquivos:
            gravacao = Gravacao.model_validate_json(arquivo.read_text(encoding="utf-8"))
            if gravacao.id != arquivo.stem:
                raise ValueError(f"{arquivo.name}: o id {gravacao.id!r} difere do nome do arquivo")
            _registrar(self._curriculos, gravacao.extrair_curriculo, arquivo)
            _registrar(self._vagas, gravacao.extrair_vaga, arquivo)
            _registrar(self._feedbacks, gravacao.escrever_feedback, arquivo)

    @property
    def nome(self) -> str:
        return "falso"

    async def extrair_curriculo(
        self, texto: TextoAnonimizado, *, orcamento: Orcamento | None = None
    ) -> Resposta[CurriculoExtraido]:
        chave = sha256_texto(texto)
        chamada = self._curriculos.get(chave)
        if chamada is None:
            raise GravacaoAusente(f"sem gravação para este currículo (sha256 {chave[:12]}…)")
        return Resposta(saida=chamada.saida, usos=(chamada.uso,))

    async def extrair_vaga(
        self, texto: str, *, orcamento: Orcamento | None = None
    ) -> Resposta[VagaExtraida]:
        chave = sha256_texto(texto)
        chamada = self._vagas.get(chave)
        if chamada is None:
            raise GravacaoAusente(f"sem gravação para esta vaga (sha256 {chave[:12]}…)")
        return Resposta(saida=chamada.saida, usos=(chamada.uso,))

    async def escrever_feedback(
        self,
        tabela: TabelaDaNota,
        curriculo: CurriculoExtraido,
        vaga: VagaExtraida,
        texto: TextoAnonimizado,
        *,
        orcamento: Orcamento | None = None,
    ) -> AsyncIterator[EventoFeedback]:
        chave = sha256_texto(texto)
        chamada = self._feedbacks.get(chave)
        if chamada is None:
            raise GravacaoAusente(f"sem gravação de feedback para este currículo ({chave[:12]}…)")
        yield EventoFeedback(tipo="etapa", texto="escrevendo o feedback")
        corpo = chamada.saida.model_dump_json()
        for inicio in range(0, len(corpo), TAMANHO_DO_PEDACO):
            yield EventoFeedback(tipo="texto", texto=corpo[inicio : inicio + TAMANHO_DO_PEDACO])
        yield EventoFeedback(tipo="final", feedback=chamada.saida, usos=(chamada.uso,))
