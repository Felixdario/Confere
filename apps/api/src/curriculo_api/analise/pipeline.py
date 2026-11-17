"""A análise completa (ADR 0003): leitura → anonimização → extração → ancoragem →
correspondência → nota → feedback.

`Analisador.eventos` é um iterador assíncrono de `EventoAnalise` para o SSE da fase 4:
- `etapa`: começou uma fase (`etapa` traz o nome estável, `texto` o legível);
- `texto`: um pedaço do feedback como o modelo o escreve;
- `final`: o `ResultadoCompleto`.

A nota vem só da tabela calculada aqui; o feedback a recebe pronta e nunca a muda.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Literal

from curriculo_api.analise.correspondencia import (
    Correspondente,
    Limiares,
    ResultadoCorrespondencia,
)
from curriculo_api.analise.embeddings import Comparador
from curriculo_api.analise.feedback import filtrar_feedback
from curriculo_api.analise.nota import calcular_tabela
from curriculo_api.ancoragem import ResultadoAncoragem, ancorar
from curriculo_api.ia.modelos import (
    CurriculoExtraido,
    Feedback,
    FeedbackIA,
    RegistroUso,
    TabelaDaNota,
    VagaExtraida,
)
from curriculo_api.ia.orcamento import Orcamento
from curriculo_api.ia.provedor import ProvedorIA, SaidaInvalida
from curriculo_api.ingestao import CurriculoIngerido, VagaIngerida, ingerir_vaga
from curriculo_api.ingestao.ingerir import anonimizar_documento, ler_curriculo
from curriculo_api.taxonomia import Taxonomia


def termos_fora_da_taxonomia(
    curriculo: CurriculoExtraido, vaga: VagaExtraida, taxonomia: Taxonomia
) -> list[str]:
    """Os nomes que a correspondência pode mandar para o embedding (ADR 0002)."""
    nomes = [r.competencia for r in vaga.requisitos]
    nomes += [c.nome for c in curriculo.competencias]
    nomes += [i.idioma for i in curriculo.idiomas]
    nomes += [c.nome for c in curriculo.certificacoes]
    return sorted({n for n in nomes if taxonomia.canonica_de(n) is None})


NomeEtapa = Literal[
    "leitura",
    "anonimizacao",
    "extracao",
    "ancoragem",
    "correspondencia",
    "nota",
    "feedback",
]
ROTULOS: dict[NomeEtapa, str] = {
    "leitura": "lendo o arquivo",
    "anonimizacao": "anonimizando os dados pessoais",
    "extracao": "extraindo currículo e vaga",
    "ancoragem": "conferindo cada trecho no texto",
    "correspondencia": "comparando requisitos e evidências",
    "nota": "calculando a nota",
    "feedback": "escrevendo as sugestões",
}
ETAPAS: tuple[NomeEtapa, ...] = tuple(ROTULOS)


@dataclass(frozen=True)
class EntradaCurriculo:
    texto_vaga: str
    data_referencia: date
    texto_curriculo: str | None = None
    arquivo_curriculo: bytes | None = field(default=None, repr=False)
    nome_arquivo: str | None = field(default=None, repr=False)


@dataclass(frozen=True)
class ResultadoCompleto:
    curriculo: CurriculoIngerido
    vaga_ingerida: VagaIngerida
    curriculo_bruto: CurriculoExtraido
    ancoragem: ResultadoAncoragem
    vaga: VagaExtraida
    correspondencia: ResultadoCorrespondencia
    tabela: TabelaDaNota
    feedback: Feedback
    usos: tuple[RegistroUso, ...]

    @property
    def custo_usd(self) -> Decimal:
        return sum((u.custo_usd for u in self.usos), Decimal(0))


@dataclass(frozen=True)
class EventoAnalise:
    tipo: Literal["etapa", "texto", "final"]
    etapa: NomeEtapa | None = None
    texto: str = ""
    resultado: ResultadoCompleto | None = None


class Analisador:
    def __init__(
        self,
        provedor: ProvedorIA,
        taxonomia: Taxonomia,
        comparador: Comparador,
        limiares: Limiares,
        teto_analise_usd: Decimal,
        orcamento_pai: Orcamento | None = None,
    ) -> None:
        self.provedor = provedor
        self._taxonomia = taxonomia
        self._comparador = comparador
        self.limiares = limiares
        self._teto = teto_analise_usd
        self._orcamento_pai = orcamento_pai

    @property
    def comparador(self) -> Comparador:
        return self._comparador

    def _etapa(self, nome: NomeEtapa) -> EventoAnalise:
        return EventoAnalise(tipo="etapa", etapa=nome, texto=ROTULOS[nome])

    async def eventos(self, entrada: EntradaCurriculo) -> AsyncIterator[EventoAnalise]:
        orcamento = Orcamento(self._teto, escopo="analise", pai=self._orcamento_pai)
        usos: list[RegistroUso] = []

        yield self._etapa("leitura")
        # A leitura de PDF e DOCX é CPU (pdfium, zip): fora do laço de eventos, para o worker
        # seguir publicando eventos e respondendo.
        documento = await asyncio.to_thread(
            ler_curriculo,
            texto=entrada.texto_curriculo,
            arquivo=entrada.arquivo_curriculo,
            nome_arquivo=entrada.nome_arquivo,
        )
        vaga_ingerida = ingerir_vaga(entrada.texto_vaga)

        yield self._etapa("anonimizacao")
        curriculo = await asyncio.to_thread(anonimizar_documento, documento)
        texto = curriculo.texto_para_ia

        yield self._etapa("extracao")
        # Em paralelo; se uma falha, a outra é cancelada (TaskGroup), para não seguir gastando.
        try:
            async with asyncio.TaskGroup() as grupo:
                tarefa_cv = grupo.create_task(
                    self.provedor.extrair_curriculo(texto, orcamento=orcamento)
                )
                tarefa_vaga = grupo.create_task(
                    self.provedor.extrair_vaga(vaga_ingerida.texto, orcamento=orcamento)
                )
        except BaseExceptionGroup as erros:
            raise erros.exceptions[0] from None
        extraido, vaga = tarefa_cv.result(), tarefa_vaga.result()
        usos += [*extraido.usos, *vaga.usos]

        yield self._etapa("ancoragem")
        ancorado = ancorar(extraido.saida, texto, self._taxonomia, curriculo.alertas)

        yield self._etapa("correspondencia")
        # Com o banco (fase 4), o vizinho mais próximo na taxonomia vem do pgvector; os termos
        # que podem precisar dele são buscados de uma vez, antes da correspondência (síncrona).
        await self._comparador.preparar(
            termos_fora_da_taxonomia(ancorado.mantido, vaga.saida, self._taxonomia)
        )
        correspondente = Correspondente(
            self._taxonomia, self._comparador, self.limiares, entrada.data_referencia
        )
        correspondencia = correspondente.corresponder(ancorado.mantido, vaga.saida)

        yield self._etapa("nota")
        tabela = calcular_tabela(
            correspondencia.linhas,
            ancorado.mantido,
            vaga.saida,
            correspondencia.chaves_atendidas,
            self._taxonomia,
            entrada.data_referencia,
        )

        yield self._etapa("feedback")
        bruto: FeedbackIA | None = None
        async for evento in self.provedor.escrever_feedback(
            tabela, ancorado.mantido, vaga.saida, texto, orcamento=orcamento
        ):
            if evento.tipo == "texto":
                yield EventoAnalise(tipo="texto", etapa="feedback", texto=evento.texto)
            elif evento.tipo == "final":
                bruto = evento.feedback
                usos += evento.usos
        if bruto is None:
            raise SaidaInvalida("o feedback terminou sem a saída final")
        feedback = filtrar_feedback(
            bruto, tabela, ancorado.mantido, texto, vaga_ingerida.texto, self._taxonomia
        )
        yield EventoAnalise(
            tipo="final",
            resultado=ResultadoCompleto(
                curriculo=curriculo,
                vaga_ingerida=vaga_ingerida,
                curriculo_bruto=extraido.saida,
                ancoragem=ancorado,
                vaga=vaga.saida,
                correspondencia=correspondencia,
                tabela=tabela,
                feedback=feedback,
                usos=tuple(usos),
            ),
        )

    async def analisar(self, entrada: EntradaCurriculo) -> ResultadoCompleto:
        async for evento in self.eventos(entrada):
            if evento.tipo == "final" and evento.resultado is not None:
                return evento.resultado
        raise SaidaInvalida("a análise terminou sem resultado")  # pragma: no cover
