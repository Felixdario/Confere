"""Fixtures da integração (`-m integracao`): Postgres e Redis do Compose (ou dos services do CI).

- **Banco isolado por execução**: `curriculo_teste_<aleatório>` é criado no mesmo servidor, as
  migrações do Alembic rodam nele, e ele é apagado no fim. Entre os testes, as tabelas são
  esvaziadas (`TRUNCATE`), menos os vetores da taxonomia.
- **Redis**: toda chave da aplicação usa um prefixo próprio desta execução (`REDIS_PREFIXO`); no
  fim de cada teste, só as chaves com esse prefixo (e as do arq com o id dos jobs dele) saem.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path
from typing import Any

import asyncpg
import httpx
import pytest
from alembic import command
from alembic.config import Config
from apoio import RAIZ, RAIZ_API
from arq import create_pool
from arq.connections import ArqRedis, RedisSettings
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.engine import make_url

from curriculo_api.api.dependencias import Recursos
from curriculo_api.config import Settings
from curriculo_api.db.sessao import criar_fabrica, criar_motor
from curriculo_api.limites import Limitador
from curriculo_api.main import criar_app, nome_da_fila

TABELAS = (
    "auditoria_recrutador",
    "decisoes_humanas",
    "candidatos",
    "processos_recrutador",
    "analises",
    "curriculo_versoes",
    "curriculos",
    "vagas",
    "uso_diario",
    "consentimentos",
    "sessoes",
    "usuarios",
)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    # Tudo nesta pasta é integração (precisa do Compose).
    for item in items:
        if "integracao" in Path(str(item.fspath)).parts:
            item.add_marker(pytest.mark.integracao)


def _dsn_asyncpg(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


@pytest.fixture(scope="session")
def banco_de_teste() -> Iterator[str]:
    base = make_url(Settings().database_url)
    nome = f"curriculo_teste_{uuid.uuid4().hex[:10]}"
    url = base.set(database=nome).render_as_string(hide_password=False)
    admin = _dsn_asyncpg(base.render_as_string(hide_password=False))

    async def executar(sql: str) -> None:
        conexao = await asyncpg.connect(admin)
        try:
            await conexao.execute(sql)
        finally:
            await conexao.close()

    asyncio.run(executar(f'CREATE DATABASE "{nome}"'))
    try:
        config = Config(str(RAIZ_API / "alembic.ini"))
        config.attributes["url"] = url
        command.upgrade(config, "head")
        yield url
    finally:
        asyncio.run(executar(f'DROP DATABASE IF EXISTS "{nome}" WITH (FORCE)'))


@pytest.fixture(scope="session")
def prefixo_redis() -> str:
    return f"teste-{uuid.uuid4().hex[:10]}"


@pytest.fixture
def pasta_arquivos(tmp_path: Path) -> Path:
    pasta = tmp_path / "arquivos"
    pasta.mkdir()
    return pasta


@pytest.fixture
def fazer_settings(
    banco_de_teste: str, prefixo_redis: str, pasta_arquivos: Path
) -> Callable[..., Settings]:
    def fazer(**valores: Any) -> Settings:
        base: dict[str, Any] = {
            "ambiente": "teste",
            "database_url": banco_de_teste,
            "redis_prefixo": prefixo_redis,
            "provedor_ia": "regras",
            "anthropic_api_key": None,
            "pasta_arquivos": pasta_arquivos,
            "pasta_gravacoes": RAIZ / "evals" / "gravacoes",
            "sse_heartbeat_s": 1.0,
            "limite_analises_por_usuario": 200,
            "limite_analises_por_ip": 400,
            "limite_cadastro_por_ip": 200,
            "limite_login_por_ip": 200,
        }
        base.update(valores)
        return Settings(_env_file=None, **base)

    return fazer


@pytest.fixture
def settings(fazer_settings: Callable[..., Settings]) -> Settings:
    return fazer_settings()


async def _limpar_redis(redis: ArqRedis, prefixo: str) -> None:
    for padrao in (f"{prefixo}:*", f"arq:*:{prefixo}:*"):
        chaves = [c async for c in redis.scan_iter(match=padrao, count=500)]
        if chaves:
            await redis.delete(*chaves)


async def _limpar_banco(url: str) -> None:
    motor = criar_motor(url)
    async with motor.begin() as conexao:
        await conexao.execute(text(f"TRUNCATE {', '.join(TABELAS)} CASCADE"))
    await motor.dispose()


@pytest.fixture
async def recursos(settings: Settings) -> AsyncIterator[Recursos]:
    motor = criar_motor(settings.database_url)
    redis = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    rec = Recursos(
        settings=settings,
        motor=motor,
        fabrica=criar_fabrica(motor),
        redis=redis,
        # Relógio parado: os testes de limite não cruzam a virada da janela no meio.
        limitador=Limitador(redis, settings.redis_prefixo, relogio=lambda: 1_800_000_000.0),
        fila=nome_da_fila(settings),
    )
    try:
        yield rec
    finally:
        await rec.fechar_assinante()
        await _limpar_redis(redis, settings.redis_prefixo)
        await redis.aclose()
        await motor.dispose()
        await _limpar_banco(settings.database_url)


@pytest.fixture
def app(recursos: Recursos) -> FastAPI:
    return criar_app(recursos.settings, recursos)


@pytest.fixture
async def novo_cliente(app: FastAPI) -> AsyncIterator[Callable[[], httpx.AsyncClient]]:
    """Um cliente por pessoa (cada um com os próprios cookies), todos na mesma aplicação."""
    criados: list[httpx.AsyncClient] = []

    def fazer() -> httpx.AsyncClient:
        transporte = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        c = httpx.AsyncClient(transport=transporte, base_url="http://teste")
        criados.append(c)
        return c

    yield fazer
    for c in criados:
        await c.aclose()


@pytest.fixture
def cliente(novo_cliente: Callable[[], httpx.AsyncClient]) -> httpx.AsyncClient:
    return novo_cliente()
