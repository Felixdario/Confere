"""Dependências das rotas: recursos do processo, sessão do banco, usuário da sessão e CSRF."""

from __future__ import annotations

import secrets
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Annotated

from arq.connections import ArqRedis
from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from curriculo_api.api.erros import ErroApi
from curriculo_api.config import Settings
from curriculo_api.db.modelos import Sessao, Usuario
from curriculo_api.eventos import Assinante
from curriculo_api.limites import Limitador
from curriculo_api.seguranca import (
    CABECALHO_CSRF,
    COOKIE_CSRF,
    COOKIE_SESSAO,
    csrf_valido,
    hash_token,
    tokens_iguais,
)

METODOS_QUE_MUDAM = frozenset({"POST", "PUT", "PATCH", "DELETE"})


@dataclass
class Recursos:
    settings: Settings
    motor: AsyncEngine
    fabrica: async_sessionmaker[AsyncSession]
    redis: ArqRedis
    limitador: Limitador
    fila: str
    _compartilhado: dict[str, Assinante] = field(default_factory=dict, repr=False)
    """O assinante do processo; um dicionário para as cópias (`dataclasses.replace`) usarem o
    mesmo."""
    _chave_csrf: bytes = field(default_factory=lambda: secrets.token_bytes(32), repr=False)

    @property
    def chave_csrf(self) -> bytes:
        if self.settings.chave_csrf is not None and self.settings.chave_csrf.get_secret_value():
            return self.settings.chave_csrf.get_secret_value().encode()
        return self._chave_csrf

    async def obter_assinante(self) -> Assinante:
        """O assinante único do processo (criado na primeira conexão SSE)."""
        assinante = self._compartilhado.get("assinante")
        if assinante is None:
            assinante = Assinante(self.redis, self.settings.redis_prefixo)
            self._compartilhado["assinante"] = assinante
        await assinante.iniciar()
        return assinante

    async def fechar_assinante(self) -> None:
        assinante = self._compartilhado.pop("assinante", None)
        if assinante is not None:
            await assinante.fechar()


def obter_recursos(request: Request) -> Recursos:
    recursos: Recursos = request.app.state.recursos
    return recursos


RecursosDep = Annotated[Recursos, Depends(obter_recursos)]


async def obter_db(recursos: RecursosDep) -> AsyncIterator[AsyncSession]:
    async with recursos.fabrica() as sessao:
        yield sessao


Db = Annotated[AsyncSession, Depends(obter_db)]


def ip_do_cliente(request: Request) -> str:
    # Sem proxy reverso nesta fase: o IP da conexão. Atrás de um proxy, configure o uvicorn com
    # --forwarded-allow-ips para o `client.host` já vir certo.
    return request.client.host if request.client else "desconhecido"


async def verificar_csrf(request: Request, recursos: RecursosDep) -> None:
    """Double submit ligado à sessão (ADR 0007): nas rotas que mudam estado, o cabeçalho
    `X-CSRF-Token` precisa ser igual ao cookie `curriculo_csrf` **e** o token precisa ter o HMAC
    da sessão atual (ou da ausência de sessão). Outro site não lê o cookie, então não forja o
    cabeçalho; um token plantado antes do login deixa de valer depois dele; o `SameSite=Lax`
    do cookie de sessão é a segunda camada."""
    if request.method not in METODOS_QUE_MUDAM:
        return
    cabecalho = request.headers.get(CABECALHO_CSRF)
    if not tokens_iguais(cabecalho, request.cookies.get(COOKIE_CSRF)) or not csrf_valido(
        recursos.chave_csrf, cabecalho or "", request.cookies.get(COOKIE_SESSAO)
    ):
        raise ErroApi(
            403,
            "csrf",
            "O token de segurança (CSRF) está ausente ou não confere. Recarregue a página e "
            "tente de novo.",
        )


async def usuario_atual(request: Request, db: Db) -> Usuario:
    token = request.cookies.get(COOKIE_SESSAO)
    if not token:
        raise ErroApi(401, "sem_sessao", "Entre na sua conta para continuar.")
    agora = datetime.now(UTC)
    linha = (
        await db.execute(
            select(Usuario)
            .join(Sessao, Sessao.usuario_id == Usuario.id)
            .where(Sessao.token_hash == hash_token(token), Sessao.expira_em > agora)
        )
    ).scalar_one_or_none()
    if linha is None:
        raise ErroApi(401, "sessao_expirada", "Sua sessão terminou. Entre de novo.")
    request.state.usuario_id = linha.id
    return linha


UsuarioAtual = Annotated[Usuario, Depends(usuario_atual)]
