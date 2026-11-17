"""Motor e fábrica de sessões. Um motor por processo (API ou worker).

O tipo `vector` vai e volta como texto (`'[0.1,0.2,…]'`, o formato do `pgvector.sqlalchemy`); sem
codec binário registrado no asyncpg, que recusaria o texto que o SQLAlchemy envia nas comparações.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def criar_motor(url: str, **opcoes: Any) -> AsyncEngine:
    return create_async_engine(url, pool_pre_ping=True, **opcoes)


def criar_fabrica(motor: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(motor, expire_on_commit=False)
