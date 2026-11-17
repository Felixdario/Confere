"""Execução de uma análise (no worker do arq, ou direto no seed): lê o arquivo do disco, roda o
`Analisador`, publica cada evento para o SSE e grava o resultado e o custo do dia.

Logs: só ids, etapa, duração, custo e o código do erro. A mensagem de uma exceção inesperada não
vai para o log nem para a tela.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from curriculo_api.analise.embeddings import ComparadorSemEmbeddings
from curriculo_api.analise.erros import ErroAnalise
from curriculo_api.analise.pipeline import Analisador, EntradaCurriculo, ResultadoCompleto
from curriculo_api.config import Settings
from curriculo_api.db.modelos import Analise, CurriculoVersao, UsoDiario, Vaga
from curriculo_api.eventos import AnaliseApagada, Publicador, foi_apagada
from curriculo_api.ia.provedor import ErroProvedor
from curriculo_api.ingestao.erros import ErroIngestao
from curriculo_api.logs import pilha_sem_mensagem
from curriculo_api.servicos.envios import acertar_uso, caminho_do_arquivo

log = logging.getLogger("curriculo_api.execucao")

MENSAGEM_INTERNA = "Algo deu errado ao analisar. Tente de novo; se continuar, avise o suporte."
MENSAGEM_TEMPO = "A análise passou do tempo máximo e foi interrompida. Tente de novo."
MENSAGEM_TETO = (
    "O limite diário de custo de análises foi atingido antes desta começar. Tente de novo "
    "depois da meia-noite (UTC)."
)
AVISO_SEM_EMBEDDINGS: dict[str, Any] = {
    "tipo": "calculo",
    "origem": "calculo",
    "motivo": "o modelo de embeddings não está instalado (make modelos): termos fora da "
    "taxonomia não foram comparados por similaridade",
}
MENSAGEM_ARQUIVO_APAGADO = (
    "O arquivo desta versão já foi apagado pela retenção de dados. Envie o currículo de novo."
)


def _agora() -> datetime:
    return datetime.now(UTC)


def serializar_resultado(r: ResultadoCompleto) -> dict[str, Any]:
    """As colunas da análise a partir do resultado (sem nada que não vá para a tela)."""
    tabela = r.tabela
    avisos: list[dict[str, Any]] = [
        {
            k: v
            for k, v in a.model_dump().items()
            if k in ("tipo", "origem", "motivo", "trecho", "pagina")
        }
        for a in (*r.curriculo.alertas, *r.vaga_ingerida.alertas)
    ]
    avisos += [{"tipo": "calculo", "origem": "calculo", "motivo": texto} for texto in tabela.avisos]
    return {
        "nota": tabela.nota,
        "decomposicao": {
            "texto": tabela.decomposicao,
            "parcelas": [p.model_dump() for p in tabela.parcelas],
            "anos_relevantes": tabela.anos_relevantes,
            "anos_minimos": tabela.anos_minimos,
        },
        "tabela": [linha.model_dump() for linha in tabela.linhas],
        "feedback": r.feedback.model_dump(),
        "avisos": avisos,
        "estatisticas": {
            "itens_extraidos": r.curriculo_bruto.total_de_itens(),
            "itens_mantidos": r.ancoragem.mantido.total_de_itens(),
            "descartados": len(r.ancoragem.descartados),
            "descartados_por_injecao": len(r.ancoragem.descartados_por_injecao),
            "descartados_por_negacao": len(r.ancoragem.descartados_por_negacao),
            "ligacoes_removidas": r.ancoragem.ligacoes_removidas,
            "datas_corrigidas": r.ancoragem.datas_corrigidas,
            "datas_nao_comprovadas": r.ancoragem.datas_nao_comprovadas,
            "reescritas_descartadas": len(r.feedback.reescritas_descartadas),
            "consultas_embedding": r.correspondencia.consultas_embedding,
        },
        "custo_usd": r.custo_usd,
        "modelos": sorted({u.modelo for u in r.usos}),
    }


class Executor:
    def __init__(
        self,
        settings: Settings,
        fabrica: async_sessionmaker[AsyncSession],
        redis: Redis,
        analisador: Analisador,
        agora: Callable[[], datetime] = _agora,
    ) -> None:
        self.settings = settings
        self.fabrica = fabrica
        self.redis = redis
        self.analisador = analisador
        self.agora = agora

    async def _registrar_etapa(self, analise_id: uuid.UUID, etapa: str, texto: str) -> None:
        async with self.fabrica() as db:
            analise = await db.get(Analise, analise_id)
            if analise is None:  # "apagar meus dados" no meio da análise
                raise AnaliseApagada
            analise.etapas = [
                *analise.etapas,
                {"etapa": etapa, "texto": texto, "em": self.agora().isoformat()},
            ]
            await db.commit()

    async def _falhar(
        self,
        analise_id: uuid.UUID,
        publicador: Publicador,
        codigo: str,
        mensagem: str,
        custo: Decimal = Decimal(0),
    ) -> None:
        async with self.fabrica() as db:
            analise = await db.get(Analise, analise_id)
            if analise is None:
                raise AnaliseApagada
            analise.status = "erro"
            analise.erro_codigo = codigo
            analise.erro_mensagem = mensagem
            analise.concluido_em = self.agora()
            analise.custo_usd = custo
            # A reserva do teto diário volta; o que já foi gasto fica como custo.
            await acertar_uso(
                db, analise.usuario_id, _dia(analise.criado_em), analise.reserva_usd, custo, False
            )
            await db.commit()
        await publicador.publicar("erro", {"codigo": codigo, "mensagem": mensagem})

    async def executar(self, analise_id: uuid.UUID) -> str:
        """Roda a análise; devolve o status final. Idempotente: análise já terminada não roda.

        Se a análise é apagada no meio ("apagar meus dados"), para na próxima etapa ou evento e
        apaga o que tiver criado no Redis (o stream e o canal), mesmo que algo tenha sido escrito
        entre a conferência e o apagamento."""
        publicador = Publicador(
            self.redis, self.settings.redis_prefixo, analise_id, self.settings.eventos_ttl_s
        )
        try:
            return await self._executar(analise_id, publicador)
        except AnaliseApagada:
            log.info("analise.apagada_durante", extra={"analise_id": str(analise_id)})
            return "apagada"
        finally:
            if await foi_apagada(self.redis, self.settings.redis_prefixo, analise_id):
                await publicador.limpar()

    async def _teto_estourado(self, usuario_id: uuid.UUID, dia: date) -> bool:
        """Nova conferência no worker, antes de chamar o provedor: o custo real do dia já passou
        do teto (outra análise gastou mais que o previsto)?"""
        async with self.fabrica() as db:
            gasto = (
                await db.execute(
                    select(UsoDiario.custo_usd).where(
                        UsoDiario.usuario_id == usuario_id, UsoDiario.dia == dia
                    )
                )
            ).scalar_one_or_none()
        return Decimal(gasto or 0) >= Decimal(str(self.settings.teto_custo_diario_usd))

    async def _executar(self, analise_id: uuid.UUID, publicador: Publicador) -> str:
        inicio = time.perf_counter()
        if await foi_apagada(self.redis, self.settings.redis_prefixo, analise_id):
            raise AnaliseApagada
        async with self.fabrica() as db:
            analise = await db.get(Analise, analise_id)
            if analise is None:
                log.warning("analise.inexistente", extra={"analise_id": str(analise_id)})
                return "inexistente"
            if analise.status in ("concluida", "erro"):
                return analise.status
            versao = await db.get(CurriculoVersao, analise.curriculo_versao_id)
            vaga = await db.get(Vaga, analise.vaga_id)
            if versao is None or vaga is None:  # pragma: no cover — FK em cascata
                return "inexistente"
            analise.status = "processando"
            analise.iniciado_em = self.agora()
            analise.etapas = []
            analise.provedor = self.analisador.provedor.nome
            await db.commit()
            relativo, origem, texto_vaga = versao.arquivo, versao.origem, vaga.texto
            usuario_id = analise.usuario_id
            dia = _dia(analise.criado_em)
            reserva = analise.reserva_usd

        log.info(
            "analise.iniciada",
            extra={"analise_id": str(analise_id), "provedor": self.analisador.provedor.nome},
        )
        if reserva > 0 and await self._teto_estourado(usuario_id, dia):
            await self._falhar(analise_id, publicador, "teto_custo_diario", MENSAGEM_TETO)
            return "erro"
        if relativo is None:
            await self._falhar(analise_id, publicador, "arquivo_apagado", MENSAGEM_ARQUIVO_APAGADO)
            return "erro"
        caminho = caminho_do_arquivo(self.settings, relativo)
        try:
            bruto = await asyncio.to_thread(caminho.read_bytes)
        except FileNotFoundError:
            if not await self._existe(analise_id):
                raise AnaliseApagada from None
            await self._falhar(analise_id, publicador, "arquivo_apagado", MENSAGEM_ARQUIVO_APAGADO)
            return "erro"
        entrada = EntradaCurriculo(
            texto_vaga=texto_vaga,
            data_referencia=self.agora().date(),
            texto_curriculo=bruto.decode("utf-8") if origem == "texto" else None,
            arquivo_curriculo=None if origem == "texto" else bruto,
            nome_arquivo=None if origem == "texto" else f"curriculo.{origem}",
        )

        resultado: ResultadoCompleto | None = None
        try:
            async with asyncio.timeout(self.settings.tempo_max_analise_s):
                async for evento in self.analisador.eventos(entrada):
                    if evento.tipo == "etapa" and evento.etapa is not None:
                        await self._registrar_etapa(analise_id, evento.etapa, evento.texto)
                        await publicador.publicar(
                            "etapa", {"etapa": evento.etapa, "texto": evento.texto}
                        )
                    elif evento.tipo == "texto":
                        await publicador.publicar("texto", {"texto": evento.texto})
                    elif evento.tipo == "final":
                        resultado = evento.resultado
        except AnaliseApagada:
            raise
        except ErroIngestao as exc:
            await self._falhar(analise_id, publicador, exc.codigo, exc.mensagem)
            log.info("analise.erro", extra={"analise_id": str(analise_id), "codigo": exc.codigo})
            return "erro"
        except ErroAnalise as exc:
            mensagem = exc.mensagem[:1].upper() + exc.mensagem[1:] + "."
            await self._falhar(analise_id, publicador, exc.codigo, mensagem)
            log.info("analise.erro", extra={"analise_id": str(analise_id), "codigo": exc.codigo})
            return "erro"
        except ErroProvedor as exc:
            gasto = sum((u.custo_usd for u in exc.usos), Decimal(0))
            await self._falhar(analise_id, publicador, exc.codigo, str(exc), gasto)
            log.info("analise.erro", extra={"analise_id": str(analise_id), "codigo": exc.codigo})
            return "erro"
        except TimeoutError:
            await self._falhar(analise_id, publicador, "tempo_esgotado", MENSAGEM_TEMPO)
            log.info("analise.erro", extra={"analise_id": str(analise_id), "codigo": "tempo"})
            return "erro"
        except Exception as exc:
            log.error(
                "analise.erro_interno",
                extra={
                    "analise_id": str(analise_id),
                    "tipo": type(exc).__name__,
                    "pilha": pilha_sem_mensagem(exc),
                },
            )
            await self._falhar(analise_id, publicador, "erro_interno", MENSAGEM_INTERNA)
            return "erro"

        if resultado is None:  # pragma: no cover — o pipeline sempre termina com `final`
            await self._falhar(analise_id, publicador, "erro_interno", MENSAGEM_INTERNA)
            return "erro"

        colunas = serializar_resultado(resultado)
        if self._sem_embeddings():
            colunas["avisos"] = [*colunas["avisos"], AVISO_SEM_EMBEDDINGS]
        async with self.fabrica() as db:
            analise = await db.get(Analise, analise_id)
            if analise is None:  # apagada durante a análise ("apagar meus dados")
                raise AnaliseApagada
            for chave, valor in colunas.items():
                setattr(analise, chave, valor)
            analise.status = "concluida"
            analise.concluido_em = self.agora()
            await acertar_uso(
                db, usuario_id, dia, analise.reserva_usd, Decimal(colunas["custo_usd"]), True
            )
            await db.commit()
        await publicador.publicar(
            "final", {"status": "concluida", "nota": colunas["nota"], "analise_id": str(analise_id)}
        )
        log.info(
            "analise.concluida",
            extra={
                "analise_id": str(analise_id),
                "duracao_ms": round((time.perf_counter() - inicio) * 1000),
                "custo_usd": str(colunas["custo_usd"]),
            },
        )
        return "concluida"

    def _sem_embeddings(self) -> bool:
        comparador = self.analisador.comparador
        return isinstance(comparador, ComparadorSemEmbeddings) and comparador.pedidos > 0

    async def _existe(self, analise_id: uuid.UUID) -> bool:
        async with self.fabrica() as db:
            return await db.get(Analise, analise_id) is not None


def _dia(instante: datetime) -> date:
    return instante.astimezone(UTC).date()
