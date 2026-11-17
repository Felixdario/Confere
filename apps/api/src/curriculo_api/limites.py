"""Limites de taxa em janela fixa no Redis (ADR 0004): `INCR` + `EXPIRE` por chave e janela.

A chave nunca carrega dado pessoal legível: usuário pelo id, e-mail por um resumo SHA-256 e IP como
veio (o IP é apagado sozinho quando a janela expira).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from redis.asyncio import Redis

from curriculo_api.api.erros import ErroApi


@dataclass(frozen=True)
class Limite:
    nome: str
    maximo: int
    janela_s: int


class Limitador:
    def __init__(
        self, redis: Redis, prefixo: str, relogio: Callable[[], float] = time.time
    ) -> None:
        self._redis = redis
        self._prefixo = prefixo
        self._relogio = relogio  # injetável: os testes não podem cruzar a virada da janela

    def chave(self, limite: Limite, quem: str, agora: float | None = None) -> tuple[str, int]:
        instante = int(agora if agora is not None else self._relogio())
        janela = instante // limite.janela_s
        restante = limite.janela_s - instante % limite.janela_s
        return f"{self._prefixo}:limite:{limite.nome}:{quem}:{janela}", restante

    async def consumir(self, limite: Limite, quem: str, mensagem: str) -> None:
        """Conta uma tentativa; passou do máximo, `429` com `Retry-After`."""
        chave, restante = self.chave(limite, quem)
        async with self._redis.pipeline(transaction=True) as tubo:
            tubo.incr(chave)
            tubo.expire(chave, limite.janela_s + 5)
            contagem, _ = await tubo.execute()
        if int(contagem) > limite.maximo:
            raise ErroApi(
                429,
                "limite_de_taxa",
                mensagem,
                cabecalhos={"Retry-After": str(max(1, restante))},
            )

    async def zerar(self, limite: Limite, quem: str) -> None:
        chave, _ = self.chave(limite, quem)
        await self._redis.delete(chave)
