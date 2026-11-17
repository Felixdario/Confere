"""Aplicação FastAPI. OpenAPI em `/docs` (e `docs/openapi.json`, versionado e testado)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from arq.connections import ArqRedis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import BlockingConnectionPool
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from curriculo_api import __version__
from curriculo_api.api import (
    rotas_analises,
    rotas_auth,
    rotas_curriculos,
    rotas_privacidade,
    rotas_recrutador,
)
from curriculo_api.api.dependencias import Recursos
from curriculo_api.api.erros import MIDIA_PROBLEMA, TIPO_BASE, instalar
from curriculo_api.api.esquemas import Saude
from curriculo_api.api.middleware import MiddlewareRequisicao
from curriculo_api.config import Settings, obter_settings
from curriculo_api.db.sessao import criar_fabrica, criar_motor
from curriculo_api.limites import Limitador
from curriculo_api.logs import configurar_logs

DESCRICAO = """
API do analisador de currículos: compara um currículo com uma vaga e explica a nota.

- **Sessão** por cookie httpOnly (`curriculo_sessao`). Toda rota que muda estado exige o
  cabeçalho `X-CSRF-Token` igual ao cookie `curriculo_csrf` (pegue em `GET /auth/csrf`).
- **Erros** em `application/problem+json` com `codigo` estável e `detail` em português.
- **Análise** assíncrona: `POST /analises` responde 202 com o id; os eventos chegam por SSE em
  `GET /analises/{id}/eventos` e o resultado em `GET /analises/{id}`.
- **Modo demonstração**: sem chave de IA, a análise é por regras, sem IA e sem custo (ADR 0006).
- **Privacidade**: dados pessoais saem antes da análise; `DELETE /eu/dados` apaga tudo.
"""

TAGS = [
    {"name": "auth", "description": "Cadastro (com consentimento LGPD), login, logout e sessão."},
    {"name": "análises", "description": "Envio, fila, eventos em tempo real, resultado e PDF."},
    {"name": "currículos", "description": "Currículos, versões e comparação contra a mesma vaga."},
    {
        "name": "recrutador",
        "description": "Processo com uma vaga e até 20 currículos: ranking explicado, visão "
        "anonimizada e decisão humana registrada (sem rejeição automática).",
    },
    {"name": "privacidade", "description": "O que guardamos, por quanto tempo, e apagar tudo."},
    {"name": "infra", "description": "Saúde do serviço."},
]

FOLGA_DO_CORPO = 256 * 1024
"""Bytes além do limite do arquivo para os outros campos do formulário multipart."""


class CorpoGrande(Exception):
    pass


class LimiteDeCorpo:
    """Recusa com 413 um corpo maior que o limite, antes de ler (pelo `Content-Length`) ou
    durante a leitura (corpo em pedaços)."""

    def __init__(self, app: ASGIApp, maximo: int) -> None:
        self.app = app
        self.maximo = maximo

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        cabecalhos = dict(scope.get("headers") or [])
        declarado = cabecalhos.get(b"content-length", b"").decode()
        if declarado.isdigit() and int(declarado) > self.maximo:
            await self._recusar(scope, send)
            return
        lidos = 0

        async def receber() -> Message:
            nonlocal lidos
            mensagem = await receive()
            if mensagem["type"] == "http.request":
                lidos += len(mensagem.get("body", b""))
                if lidos > self.maximo:
                    raise CorpoGrande
            return mensagem

        iniciou = False

        async def enviar(mensagem: Message) -> None:
            nonlocal iniciou
            if mensagem["type"] == "http.response.start":
                iniciou = True
            await send(mensagem)

        try:
            await self.app(scope, receber, enviar)
        except CorpoGrande:
            if not iniciou:
                await self._recusar(scope, send)

    async def _recusar(self, scope: Scope, send: Send) -> None:
        mb = (self.maximo - FOLGA_DO_CORPO) / (1024 * 1024)
        corpo = json.dumps(
            {
                "type": TIPO_BASE + "arquivo_grande",
                "title": "Arquivo grande demais",
                "status": 413,
                "detail": f"O envio passa do limite de {mb:.0f} MB. Exporte o currículo de novo, "
                "sem imagens grandes, ou cole o texto.",
                "codigo": "arquivo_grande",
                "instance": scope.get("path", ""),
            },
            ensure_ascii=False,
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", MIDIA_PROBLEMA.encode()),
                    (b"content-length", str(len(corpo)).encode()),
                    (b"connection", b"close"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": corpo})


def nome_da_fila(settings: Settings) -> str:
    return f"{settings.redis_prefixo}:fila"


def criar_redis(settings: Settings) -> ArqRedis:
    """ArqRedis sobre um pool **bloqueante** com teto (REDIS_MAX_CONEXOES): passado o teto, o
    pedido espera uma conexão voltar (até 10 s) em vez de abrir mais."""
    pool = BlockingConnectionPool.from_url(
        settings.redis_url, max_connections=settings.redis_max_conexoes, timeout=10
    )
    return ArqRedis(connection_pool=pool)


async def criar_recursos(settings: Settings) -> Recursos:
    motor = criar_motor(settings.database_url)
    # Pool com teto: o SSE não segura conexões (um assinante pub/sub por processo), e o resto pega
    # e devolve; acima do teto, espera em vez de abrir conexões sem fim.
    redis = criar_redis(settings)
    return Recursos(
        settings=settings,
        motor=motor,
        fabrica=criar_fabrica(motor),
        redis=redis,
        limitador=Limitador(redis, settings.redis_prefixo),
        fila=nome_da_fila(settings),
    )


async def fechar_recursos(recursos: Recursos) -> None:
    await recursos.fechar_assinante()
    await recursos.redis.aclose()
    await recursos.redis.connection_pool.disconnect()
    await recursos.motor.dispose()


def criar_app(settings: Settings | None = None, recursos: Recursos | None = None) -> FastAPI:
    """`recursos` injetados (testes) não são criados nem fechados pelo ciclo de vida."""
    settings = settings or (recursos.settings if recursos else obter_settings())

    @asynccontextmanager
    async def ciclo(app: FastAPI) -> AsyncIterator[None]:
        configurar_logs()
        proprios = getattr(app.state, "recursos", None) is None
        if proprios:
            app.state.recursos = await criar_recursos(settings)
        try:
            yield
        finally:
            if proprios:
                await fechar_recursos(app.state.recursos)
                app.state.recursos = None

    app = FastAPI(
        title="Analisador de currículos",
        version=__version__,
        description=DESCRICAO,
        openapi_tags=TAGS,
        docs_url="/docs",
        lifespan=ciclo,
    )
    app.state.recursos = recursos
    instalar(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origens),
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type", "X-CSRF-Token", "Last-Event-ID", "X-Request-ID"],
        expose_headers=["X-Request-ID", "Retry-After", "X-CSRF-Token"],
    )
    app.add_middleware(LimiteDeCorpo, maximo=settings.ingestao_tamanho_max_bytes + FOLGA_DO_CORPO)
    app.add_middleware(MiddlewareRequisicao)

    app.include_router(rotas_auth.rotas)
    app.include_router(rotas_auth.rotas_eu)
    app.include_router(rotas_analises.rotas)
    app.include_router(rotas_curriculos.rotas)
    app.include_router(rotas_recrutador.rotas)
    app.include_router(rotas_privacidade.rotas)

    @app.get("/saude", tags=["infra"], summary="Saúde do serviço")
    async def saude() -> Saude:
        return Saude(
            status="ok",
            versao=__version__,
            provedor_ia=settings.provedor_ia,
            modo_demonstracao=settings.modo_demonstracao,
        )

    return app


app = criar_app()
