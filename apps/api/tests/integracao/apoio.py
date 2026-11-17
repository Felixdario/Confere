"""Ajudantes da integração: worker e servidor reais, sessão de um usuário e leitura de SSE."""

from __future__ import annotations

import asyncio
import contextlib
import json
import signal
import socket
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import uvicorn
from arq import create_pool
from arq.connections import RedisSettings
from arq.worker import Worker, func
from fastapi import FastAPI

from curriculo_api.analise.embeddings import EmbutidorFalso
from curriculo_api.analise.fabrica import criar_analisador
from curriculo_api.analise.vetores_pg import ComparadorPgvector
from curriculo_api.api.dependencias import Recursos
from curriculo_api.db.modelos import Analise, Candidato
from curriculo_api.ia.falso import ProvedorFalso
from curriculo_api.ia.provedor import ProvedorIA
from curriculo_api.ia.regras import ProvedorRegras
from curriculo_api.servicos.execucao import Executor
from curriculo_api.taxonomia import carregar_taxonomia
from curriculo_api.worker import executar_analise

RAIZ_API = Path(__file__).resolve().parents[2]
RAIZ = RAIZ_API.parents[1]
CASOS = RAIZ / "evals" / "casos"
SENHA = "uma senha longa 123"


def caso(nome: str, arquivo: str) -> str:
    return (CASOS / nome / arquivo).read_text("utf-8")


def bytes_do_caso(nome: str, arquivo: str) -> bytes:
    return (CASOS / nome / arquivo).read_bytes()


# --- execução ----------------------------------------------------------------------------------


def criar_executor(recursos: Recursos, provedor: ProvedorIA | None = None) -> Executor:
    taxonomia = carregar_taxonomia()
    embutidor = EmbutidorFalso(dim=384)
    analisador = criar_analisador(
        provedor or ProvedorRegras(taxonomia),
        recursos.settings,
        taxonomia=taxonomia,
        embutidor=embutidor,
        comparador=ComparadorPgvector(taxonomia, embutidor, recursos.fabrica),
    )
    return Executor(recursos.settings, recursos.fabrica, recursos.redis, analisador)


def provedor_falso() -> ProvedorFalso:
    return ProvedorFalso(RAIZ / "evals" / "gravacoes")


@dataclass
class WorkerDeTeste:
    worker: Worker
    tarefa: asyncio.Task[None]
    executor: Executor


@contextlib.asynccontextmanager
async def rodar_worker(
    recursos: Recursos, provedor: ProvedorIA | None = None
) -> AsyncIterator[WorkerDeTeste]:
    """O worker do arq de verdade, consumindo a fila deste teste, no mesmo laço de eventos."""
    executor = criar_executor(recursos, provedor)
    pool = await create_pool(RedisSettings.from_dsn(recursos.settings.redis_url))
    worker = Worker(
        # Como o WorkerSettings de produção: sem guardar resultado no Redis.
        functions=[func(executar_analise, name="executar_analise", max_tries=1, keep_result=0)],
        redis_pool=pool,
        queue_name=recursos.fila,
        ctx={"executor": executor},
        handle_signals=False,
        poll_delay=0.05,
        keep_result=0,
    )
    tarefa: asyncio.Task[None] = asyncio.create_task(worker.main())
    try:
        yield WorkerDeTeste(worker, tarefa, executor)
    finally:
        # O `close()` do arq sem tratador de sinais usa SIGUSR1, que não existe no Windows: para
        # o worker com o tratador de SIGTERM e fecha como se os sinais fossem dele.
        worker.handle_sig(signal.SIGTERM)
        tarefa.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await tarefa
        worker._handle_signals = True
        # As tarefas de job canceladas pelo SIGTERM fazem o gather do close() levantar
        # CancelledError (era a intermitência vista na fase 4): também é esperado aqui.
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await worker.close()


async def esperar_status(
    recursos: Recursos, analise_id: str | uuid.UUID, finais: tuple[str, ...] = ("concluida", "erro")
) -> str:
    for _ in range(600):
        async with recursos.fabrica() as db:
            analise = await db.get(Analise, uuid.UUID(str(analise_id)))
            if analise is not None and analise.status in finais:
                return analise.status
        await asyncio.sleep(0.05)
    raise AssertionError("a análise não terminou a tempo")


def porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        porta: int = s.getsockname()[1]
        return porta


@contextlib.asynccontextmanager
async def servidor_http(app: FastAPI) -> AsyncIterator[str]:
    """O uvicorn de verdade (o `ASGITransport` do httpx entrega a resposta só no fim)."""
    porta = porta_livre()
    config = uvicorn.Config(
        app, host="127.0.0.1", port=porta, log_level="warning", lifespan="off", access_log=False
    )
    servidor = uvicorn.Server(config)
    tarefa = asyncio.create_task(servidor.serve())
    for _ in range(250):
        if servidor.started:
            break
        await asyncio.sleep(0.02)
    try:
        yield f"http://127.0.0.1:{porta}"
    finally:
        servidor.should_exit = True
        await tarefa


# --- sessão ------------------------------------------------------------------------------------


@dataclass
class Pessoa:
    """Uma pessoa com o próprio cliente (e o próprio pote de cookies)."""

    cliente: httpx.AsyncClient
    email: str
    csrf: str
    id: str = ""

    @property
    def cabecalhos(self) -> dict[str, str]:
        return hc(self.cliente, self.csrf)

    async def get(self, url: str, **kw: Any) -> httpx.Response:
        return await self.cliente.get(url, **kw)

    async def post(self, url: str, **kw: Any) -> httpx.Response:
        cabecalhos = {**self.cabecalhos, **kw.pop("headers", {})}
        return await self.cliente.post(url, headers=cabecalhos, **kw)

    async def delete(self, url: str, **kw: Any) -> httpx.Response:
        cabecalhos = {**self.cabecalhos, **kw.pop("headers", {})}
        return await self.cliente.delete(url, headers=cabecalhos, **kw)


def hc(cliente: httpx.AsyncClient, reserva: str = "") -> dict[str, str]:
    """O cabeçalho CSRF com o token do cookie atual (ele muda no login e no logout)."""
    return {"X-CSRF-Token": cliente.cookies.get("curriculo_csrf") or reserva}


async def analise_do_candidato(recursos: Recursos, candidato_id: str) -> str:
    """O id da análise de um candidato (a API não o expõe mais ao recrutador)."""
    async with recursos.fabrica() as db:
        candidato = await db.get(Candidato, uuid.UUID(candidato_id))
        assert candidato is not None
        return str(candidato.analise_id)


async def pegar_csrf(cliente: httpx.AsyncClient) -> str:
    resposta = await cliente.get("/auth/csrf")
    assert resposta.status_code == 200
    csrf: str = resposta.json()["csrf"]
    return csrf


async def cadastrar(cliente: httpx.AsyncClient, email: str | None = None) -> Pessoa:
    email = email or f"pessoa-{uuid.uuid4().hex[:8]}@example.com"
    csrf = await pegar_csrf(cliente)
    resposta = await cliente.post(
        "/auth/cadastro",
        json={
            "email": email,
            "senha": SENHA,
            "aceito_consentimento": True,
            "versao_consentimento": "2026-11-16",
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert resposta.status_code == 201, resposta.text
    return Pessoa(cliente, email, csrf, resposta.json()["id"])


async def enviar_texto(
    pessoa: Pessoa, nome_caso: str, *, curriculo_id: str | None = None, vaga: str | None = None
) -> httpx.Response:
    dados = {
        "texto": caso(nome_caso, "curriculo.md"),
        "vaga_texto": vaga or caso(nome_caso, "vaga.md"),
    }
    if curriculo_id:
        dados["curriculo_id"] = curriculo_id
    return await pessoa.post("/analises", data=dados)


# --- SSE ---------------------------------------------------------------------------------------


@dataclass
class EventoLido:
    id: int | None
    tipo: str
    dados: dict[str, Any]


async def ler_sse(
    resposta: httpx.Response, ate: int | None = None, comentarios: list[str] | None = None
) -> list[EventoLido]:
    """Lê eventos até o fim do fluxo (ou até `ate` eventos)."""
    eventos: list[EventoLido] = []
    atual: dict[str, str] = {}
    async for linha in resposta.aiter_lines():
        if linha.startswith(":"):
            if comentarios is not None:
                comentarios.append(linha)
            continue
        if not linha:
            if "event" in atual:
                eventos.append(
                    EventoLido(
                        int(atual["id"]) if "id" in atual else None,
                        atual["event"],
                        json.loads(atual.get("data", "{}")),
                    )
                )
                if ate is not None and len(eventos) >= ate:
                    return eventos
            atual = {}
            continue
        chave, _, valor = linha.partition(":")
        atual[chave] = valor.lstrip(" ")
    return eventos
