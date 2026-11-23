"""Worker da fila (arq, ADR 0007). `make worker` = `arq curriculo_api.worker.WorkerSettings`.

- `executar_analise(analise_id)`: roda a análise e publica os eventos para o SSE.
- `limpar_vencidos` (cron diário, 03:00 UTC): a retenção de `RETENCAO_DIAS` (ADR 0004). O mesmo
  código roda à mão com `make limpar-vencidos`.

O provedor sai de `PROVEDOR_IA` (padrão `regras`, o modo demonstração). Com o banco no ar, o
vizinho mais próximo da taxonomia vem do pgvector.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, ClassVar

from arq import cron, func
from arq.connections import RedisSettings

from curriculo_api.analise.embeddings import (
    Comparador,
    ComparadorSemEmbeddings,
    Embutidor,
    EmbutidorFalso,
    EmbutidorFastEmbed,
    modelo_instalado,
)
from curriculo_api.analise.fabrica import criar_analisador, resolver_pasta
from curriculo_api.analise.pipeline import Analisador
from curriculo_api.analise.vetores_pg import ComparadorPgvector
from curriculo_api.config import Settings, obter_settings
from curriculo_api.db.sessao import criar_fabrica, criar_motor
from curriculo_api.ia.fabrica import criar_provedor
from curriculo_api.logs import configurar_logs
from curriculo_api.servicos.execucao import Executor
from curriculo_api.servicos.privacidade import limpar_vencidos
from curriculo_api.taxonomia import carregar_taxonomia

log = logging.getLogger("curriculo_api.worker")


def montar_analisador(
    settings: Settings, fabrica: Any, embutidor: Embutidor | None = None
) -> Analisador:
    taxonomia = carregar_taxonomia()
    provedor = criar_provedor(
        settings.provedor_ia,
        pasta_gravacoes=resolver_pasta(settings.pasta_gravacoes),
        settings=settings,
    )
    pasta = resolver_pasta(settings.pasta_modelos)
    comparador: Comparador
    if embutidor is None and not (modelo_instalado(pasta) or settings.baixar_modelo_na_analise):
        # Nunca baixa ~220 MB no meio de uma análise: sem `make modelos`, só a taxonomia.
        log.warning(
            "worker.sem_modelo_de_embeddings",
            extra={"pasta": str(pasta), "como_resolver": "make modelos"},
        )
        comparador = ComparadorSemEmbeddings(taxonomia)
        embutidor = EmbutidorFalso()
    else:
        embutidor = embutidor or EmbutidorFastEmbed(settings.modelo_embeddings, pasta)
        comparador = ComparadorPgvector(taxonomia, embutidor, fabrica, pasta)
    return criar_analisador(
        provedor, settings, taxonomia=taxonomia, embutidor=embutidor, comparador=comparador
    )


async def iniciar(ctx: dict[str, Any]) -> None:
    configurar_logs()
    if "executor" in ctx:  # injetado (testes)
        return
    settings = obter_settings()
    motor = criar_motor(settings.database_url)
    fabrica = criar_fabrica(motor)
    ctx["motor"] = motor
    ctx["settings"] = settings
    ctx["fabrica"] = fabrica
    ctx["executor"] = Executor(
        settings, fabrica, ctx["redis"], montar_analisador(settings, fabrica)
    )
    log.info("worker.iniciado", extra={"provedor": settings.provedor_ia})


async def encerrar(ctx: dict[str, Any]) -> None:
    motor = ctx.get("motor")
    if motor is not None:
        await motor.dispose()


async def executar_analise(ctx: dict[str, Any], analise_id: str) -> str:
    executor: Executor = ctx["executor"]
    return await executor.executar(uuid.UUID(analise_id))


async def tarefa_limpar_vencidos(ctx: dict[str, Any]) -> dict[str, int]:
    executor: Executor = ctx["executor"]
    async with executor.fabrica() as db:
        resultado = await limpar_vencidos(db, executor.redis, executor.settings, executor.agora)
    return vars(resultado)


_settings = obter_settings()


class WorkerSettings:
    functions: ClassVar[list[Any]] = [
        # Sem guardar o resultado (keep_result=0): nada do job sobra no Redis depois que termina.
        func(executar_analise, name="executar_analise", max_tries=2, timeout=600, keep_result=0)
    ]
    cron_jobs: ClassVar[list[Any]] = [
        cron(tarefa_limpar_vencidos, hour={3}, minute={0}, run_at_startup=False)
    ]
    on_startup = iniciar
    on_shutdown = encerrar
    redis_settings = RedisSettings.from_dsn(_settings.redis_url)
    queue_name = f"{_settings.redis_prefixo}:fila"
    max_jobs = 4
    keep_result = 0
    poll_delay = _settings.worker_intervalo_s
