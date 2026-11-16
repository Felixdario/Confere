"""A interface que o harness chama por caso, e o pipeline da fase 2: ingestão → anonimização →
extração → ancoragem contra o texto anonimizado.

A fase 3 pluga a análise completa implementando `Pipeline` e preenchendo os campos que hoje vêm
`None` (nota, reescritas). O harness não muda: cada métrica que depende de um campo `None`
aparece como "pendente".
"""

from __future__ import annotations

from datetime import date
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from curriculo_api.alertas import Alerta
from curriculo_api.ancoragem import ancorar
from curriculo_api.evals.dataset import Caso
from curriculo_api.ia.modelos import CurriculoExtraido, RegistroUso, VagaExtraida
from curriculo_api.ia.provedor import ProvedorIA
from curriculo_api.ingestao import CurriculoIngerido, VagaIngerida, ingerir_curriculo, ingerir_vaga


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


def ingerir_entrada(entrada: EntradaAnalise) -> tuple[CurriculoIngerido, VagaIngerida]:
    """A parte determinística do pipeline, compartilhada com `make gravacoes` (o hash da gravação
    é o do texto anonimizado, que é o que o provedor recebe)."""
    curriculo = ingerir_curriculo(
        texto=entrada.texto_curriculo,
        arquivo=entrada.arquivo_curriculo,
        nome_arquivo=entrada.nome_arquivo,
    )
    return curriculo, ingerir_vaga(entrada.texto_vaga)


def ingerir_caso(caso: Caso) -> tuple[CurriculoIngerido, VagaIngerida]:
    """O mesmo que o pipeline faz com o caso (sem a data, que a ingestão não usa)."""
    curriculo = ingerir_curriculo(
        texto=caso.curriculo,
        arquivo=caso.arquivo.read_bytes() if caso.arquivo else None,
        nome_arquivo=caso.arquivo.name if caso.arquivo else None,
    )
    return curriculo, ingerir_vaga(caso.vaga)


class Reescrita(_Modelo):
    antes: str
    depois: str
    competencias: tuple[str, ...] = Field(description="Competências que a reescrita cita.")


class ResultadoAnalise(_Modelo):
    """O que o harness mede. `None` = a parte do pipeline que produz isso ainda não existe."""

    texto_analisado: str = Field(
        description="O texto que a IA viu e contra o qual o trecho é ancorado (anonimizado a "
        "partir da fase 2)."
    )
    curriculo_bruto: CurriculoExtraido = Field(description="O que a IA devolveu, antes do filtro.")
    curriculo_mantido: CurriculoExtraido = Field(description="O que sobrou depois da ancoragem.")
    descartados_por_ancora: int = Field(
        ge=0,
        description="Itens que o filtro de ancoragem descartou (`ResultadoAncoragem.descartados`)."
        " Remoções por outros motivos não entram aqui.",
    )
    vaga: VagaExtraida
    usos: tuple[RegistroUso, ...] = ()
    nota: int | None = Field(default=None, ge=0, le=100)
    alertas: tuple[Alerta, ...] | None = None
    reescritas_propostas: int | None = Field(default=None, ge=0)
    reescritas_entregues: tuple[Reescrita, ...] | None = None


class Pipeline(Protocol):
    @property
    def nome(self) -> str: ...

    async def analisar(self, entrada: EntradaAnalise) -> ResultadoAnalise: ...


class PipelineIngestao:
    """Fase 2: ingestão (arquivo ou texto, texto oculto fora, alertas), anonimização, extração do
    currículo e da vaga e ancoragem literal contra o texto anonimizado. Sem nota e sem feedback
    (fase 3)."""

    def __init__(self, provedor: ProvedorIA) -> None:
        self._provedor = provedor

    @property
    def nome(self) -> str:
        return "ingestao-fase-2"

    async def analisar(self, entrada: EntradaAnalise) -> ResultadoAnalise:
        ingerido, vaga_ingerida = ingerir_entrada(entrada)
        texto = ingerido.texto_para_ia
        curriculo = await self._provedor.extrair_curriculo(texto)
        vaga = await self._provedor.extrair_vaga(vaga_ingerida.texto)
        ancorado = ancorar(curriculo.saida, texto)
        return ResultadoAnalise(
            texto_analisado=texto,
            curriculo_bruto=curriculo.saida,
            curriculo_mantido=ancorado.mantido,
            descartados_por_ancora=len(ancorado.descartados),
            vaga=vaga.saida,
            usos=(*curriculo.usos, *vaga.usos),
            alertas=(*ingerido.alertas, *vaga_ingerida.alertas),
        )
