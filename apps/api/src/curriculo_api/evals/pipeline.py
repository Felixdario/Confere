"""A interface que o harness chama por caso, e o pipeline da fase 1 (só extração + ancoragem).

A fase 3 pluga a análise completa implementando `Pipeline` e preenchendo os campos que hoje vêm
`None` (nota, alertas, reescritas). O harness não muda: cada métrica que depende de um campo `None`
aparece como "pendente".
"""

from __future__ import annotations

from datetime import date
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from curriculo_api.alertas import Alerta
from curriculo_api.ancoragem import ancorar
from curriculo_api.ia.modelos import CurriculoExtraido, RegistroUso, TextoAnonimizado, VagaExtraida
from curriculo_api.ia.provedor import ProvedorIA


class _Modelo(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EntradaAnalise(_Modelo):
    """O que o pipeline recebe. Nunca o gabarito."""

    texto_curriculo: str
    texto_vaga: str
    data_referencia: date


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


class PipelineExtracao:
    """Fase 1: extração do currículo e da vaga e ancoragem literal. Sem anonimização (fase 2),
    sem nota e sem feedback (fase 3)."""

    def __init__(self, provedor: ProvedorIA) -> None:
        self._provedor = provedor

    @property
    def nome(self) -> str:
        return "extracao-fase-1"

    async def analisar(self, entrada: EntradaAnalise) -> ResultadoAnalise:
        # Fase 2: aqui entra a anonimização; por ora o texto vai como está.
        texto = TextoAnonimizado(entrada.texto_curriculo)
        curriculo = await self._provedor.extrair_curriculo(texto)
        vaga = await self._provedor.extrair_vaga(entrada.texto_vaga)
        ancorado = ancorar(curriculo.saida, texto)
        return ResultadoAnalise(
            texto_analisado=texto,
            curriculo_bruto=curriculo.saida,
            curriculo_mantido=ancorado.mantido,
            descartados_por_ancora=len(ancorado.descartados),
            vaga=vaga.saida,
            usos=(*curriculo.usos, *vaga.usos),
        )
