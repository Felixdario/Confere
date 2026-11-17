"""Ambiente do Alembic, assíncrono (asyncpg). A URL vem de `x_url` (testes) ou do `DATABASE_URL`."""

from __future__ import annotations

import asyncio

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from curriculo_api.config import obter_settings
from curriculo_api.db.modelos import Base

config = context.config
alvo = Base.metadata


def _url() -> str:
    explicita = context.get_x_argument(as_dictionary=True).get("url")
    if explicita:
        return explicita
    anexada = config.attributes.get("url")
    return str(anexada) if anexada else obter_settings().database_url


def _rodar(conexao: Connection) -> None:
    context.configure(connection=conexao, target_metadata=alvo, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def _online() -> None:
    motor = create_async_engine(_url())
    async with motor.connect() as conexao:
        await conexao.run_sync(_rodar)
    await motor.dispose()


def _offline() -> None:
    context.configure(url=_url(), target_metadata=alvo, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    _offline()
else:
    conexao_externa = config.attributes.get("conexao")
    if conexao_externa is not None:
        _rodar(conexao_externa)
    else:
        asyncio.run(_online())
