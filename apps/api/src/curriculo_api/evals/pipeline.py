"""A interface que o harness chama por caso e o `PipelineCompleto` (fase 3): ingestão →
anonimização → extração → ancoragem → correspondência → nota → feedback, pelo mesmo `Analisador`
que a API usa.

Cada métrica do harness olha só para o `ResultadoAnalise`; um campo `None` deixa a métrica
correspondente "pendente".
"""

from __future__ import annotations

from datetime import date
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from curriculo_api.alertas import Alerta
from curriculo_api.analise.pipeline import Analisador, EntradaCurriculo
from curriculo_api.evals.dataset import Caso
from curriculo_api.ia.modelos import (
    CurriculoExtraido,
    Feedback,
    Reescrita,
    RegistroUso,
    TabelaDaNota,
    VagaExtraida,
)
from curriculo_api.ingestao import CurriculoIngerido, VagaIngerida, ingerir_curriculo, ingerir_vaga

__all__ = [
    "EntradaAnalise",
    "Pipeline",
    "PipelineCompleto",
    "Reescrita",
    "ResultadoAnalise",
    "entrada_do_caso",
    "ingerir_caso",
]


class _Modelo(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EntradaAnalise(_Modelo):
    """O que o pipeline recebe. Nunca o gabarito."""

    texto_curriculo: str = Field(description="O texto colado (o `curriculo.md` do caso).")
    texto_vaga: str
    data_referencia: date
    arquivo_curriculo: bytes | None = Field(
        default=None, repr=False, description="O PDF/DOCX real; se houver, é ele que se ingere."
    )
    nome_arquivo: str | None = Field(default=None, repr=False)


def entrada_do_caso(caso: Caso, data_referencia: date) -> EntradaAnalise:
    return EntradaAnalise(
        texto_curriculo=caso.curriculo,
        texto_vaga=caso.vaga,
        data_referencia=data_referencia,
        arquivo_curriculo=caso.arquivo.read_bytes() if caso.arquivo else None,
        nome_arquivo=caso.arquivo.name if caso.arquivo else None,
    )


def ingerir_caso(caso: Caso) -> tuple[CurriculoIngerido, VagaIngerida]:
    """O mesmo que o pipeline faz com o caso (sem a data, que a ingestão não usa). `make
    gravacoes` usa esta função: o hash da gravação é o do texto anonimizado."""
    curriculo = ingerir_curriculo(
        texto=caso.curriculo,
        arquivo=caso.arquivo.read_bytes() if caso.arquivo else None,
        nome_arquivo=caso.arquivo.name if caso.arquivo else None,
    )
    return curriculo, ingerir_vaga(caso.vaga)


class ResultadoAnalise(_Modelo):
    """O que o harness mede. `None` = a parte do pipeline que produz isso não rodou."""

    texto_analisado: str = Field(
        description="O texto que a IA viu e contra o qual o trecho é ancorado (anonimizado)."
    )
    curriculo_bruto: CurriculoExtraido = Field(description="O que a IA devolveu, antes do filtro.")
    curriculo_mantido: CurriculoExtraido = Field(description="O que sobrou depois da ancoragem.")
    descartados_por_ancora: int = Field(
        ge=0,
        description="Itens que o filtro de ancoragem descartou (`ResultadoAncoragem.descartados`)."
        " Remoções por outros motivos não entram aqui.",
    )
    descartados_por_injecao: int = Field(
        default=0, ge=0, description="Itens cujo trecho cai numa linha com alerta de injection."
    )
    ligacoes_removidas: int = Field(
        default=0, ge=0, description="Ligações competência → experiência fora da região dela."
    )
    vaga: VagaExtraida
    usos: tuple[RegistroUso, ...] = ()
    nota: int | None = Field(default=None, ge=0, le=100)
    tabela: TabelaDaNota | None = None
    alertas: tuple[Alerta, ...] | None = None
    reescritas_propostas: int | None = Field(default=None, ge=0)
    reescritas_entregues: tuple[Reescrita, ...] | None = None
    feedback: Feedback | None = None
    consultas_embedding: int | None = Field(
        default=None, ge=0, description="Quantas decisões precisaram de embedding (ADR 0002)."
    )


class Pipeline(Protocol):
    @property
    def nome(self) -> str: ...

    async def analisar(self, entrada: EntradaAnalise) -> ResultadoAnalise: ...


class PipelineCompleto:
    """A análise da fase 3, a mesma da API, convertida no formato que o harness mede."""

    def __init__(self, analisador: Analisador) -> None:
        self.analisador = analisador

    @property
    def nome(self) -> str:
        return "completo-fase-3"

    async def analisar(self, entrada: EntradaAnalise) -> ResultadoAnalise:
        r = await self.analisador.analisar(
            EntradaCurriculo(
                texto_vaga=entrada.texto_vaga,
                data_referencia=entrada.data_referencia,
                texto_curriculo=entrada.texto_curriculo,
                arquivo_curriculo=entrada.arquivo_curriculo,
                nome_arquivo=entrada.nome_arquivo,
            )
        )
        return ResultadoAnalise(
            texto_analisado=r.curriculo.texto_para_ia,
            curriculo_bruto=r.curriculo_bruto,
            curriculo_mantido=r.ancoragem.mantido,
            descartados_por_ancora=len(r.ancoragem.descartados),
            descartados_por_injecao=len(r.ancoragem.descartados_por_injecao),
            ligacoes_removidas=r.ancoragem.ligacoes_removidas,
            vaga=r.vaga,
            usos=r.usos,
            nota=r.tabela.nota,
            tabela=r.tabela,
            alertas=(*r.curriculo.alertas, *r.vaga_ingerida.alertas),
            reescritas_propostas=r.feedback.reescritas_propostas,
            reescritas_entregues=r.feedback.reescritas,
            feedback=r.feedback,
            consultas_embedding=r.correspondencia.consultas_embedding,
        )
