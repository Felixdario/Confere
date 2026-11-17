"""Eventos de uma análise para o SSE (ADR 0007): estado persistido + aviso por pub/sub.

O worker grava cada evento num **stream** do Redis com id explícito `<n>-0` (n = 1, 2, 3…) e
publica um aviso no canal da análise. Na API, **um único assinante por processo** (`Assinante`,
`PSUBSCRIBE` no padrão dos canais) acorda em memória as conexões SSE daquela análise; cada uma, ao
acordar (ou a cada heartbeat), lê do stream tudo depois do último id enviado. Assim:

- reconexão com `Last-Event-ID: n` continua do evento n + 1, sem perder nem repetir;
- um aviso perdido não perde evento (o stream é a fonte; o aviso só acorda o leitor);
- mil conexões SSE ocupam **uma** conexão Redis de pub/sub, não mil (rodada 1 da revisão: cada
  SSE com o próprio pub/sub esgotava o pool e derrubava o resto da API);
- o stream expira em `EVENTOS_TTL_S` depois do fim; sem stream, o SSE responde com o banco.

"Apagar meus dados" com análise em andamento (rodada 1): `marcar_apagadas` grava uma marca curta
por análise; o `Publicador` confere a marca antes de cada evento e levanta `AnaliseApagada`, e o
worker apaga o que tiver criado.

Os eventos não levam conteúdo do currículo além do que a própria pessoa vai ver na tela (o texto
do feedback em streaming), e nunca vão para os logs.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import uuid
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from redis.asyncio import Redis

log = logging.getLogger("curriculo_api.eventos")

TipoEvento = Literal["etapa", "texto", "final", "erro"]
TERMINAIS: frozenset[str] = frozenset({"final", "erro"})
TTL_MARCA_APAGADA_S = 3600


def chave_stream(prefixo: str, analise_id: uuid.UUID | str) -> str:
    return f"{prefixo}:analise:{analise_id}:eventos"


def chave_canal(prefixo: str, analise_id: uuid.UUID | str) -> str:
    return f"{prefixo}:analise:{analise_id}:canal"


def chave_job(prefixo: str, analise_id: uuid.UUID | str) -> str:
    """Id do job no arq (o arq guarda `arq:job:<id>` e `arq:result:<id>`)."""
    return f"{prefixo}:analise:{analise_id}"


def chave_apagada(prefixo: str, analise_id: uuid.UUID | str) -> str:
    # Resumo do id, não o id: depois de "apagar meus dados" nenhuma chave cita a análise.
    resumo = hashlib.sha256(str(analise_id).encode()).hexdigest()[:32]
    return f"{prefixo}:apagada:{resumo}"


class AnaliseApagada(Exception):
    """A análise foi apagada ("apagar meus dados") enquanto rodava."""


async def marcar_apagadas(redis: Redis, prefixo: str, analises: Iterable[uuid.UUID]) -> None:
    lista = list(analises)
    if not lista:
        return
    async with redis.pipeline(transaction=False) as tubo:
        for analise_id in lista:
            tubo.set(chave_apagada(prefixo, analise_id), "1", ex=TTL_MARCA_APAGADA_S)
        await tubo.execute()


async def foi_apagada(redis: Redis, prefixo: str, analise_id: uuid.UUID | str) -> bool:
    return bool(await redis.exists(chave_apagada(prefixo, analise_id)))


@dataclass(frozen=True)
class Evento:
    id: int
    tipo: TipoEvento
    dados: dict[str, Any]

    def sse(self) -> str:
        corpo = json.dumps(self.dados, ensure_ascii=False)
        return f"id: {self.id}\nevent: {self.tipo}\ndata: {corpo}\n\n"


def _texto(v: Any) -> str:
    return v.decode() if isinstance(v, bytes) else str(v)


def _do_stream(entrada_id: str | bytes, campos: Mapping[Any, Any]) -> Evento:
    normal = {_texto(k): _texto(v) for k, v in campos.items()}
    tipo = normal["tipo"]
    if tipo not in ("etapa", "texto", "final", "erro"):
        tipo = "etapa"
    return Evento(
        id=int(_texto(entrada_id).split("-", 1)[0]),
        tipo=tipo,  # type: ignore[arg-type]
        dados=json.loads(normal["dados"]),
    )


class Publicador:
    """Escreve os eventos de uma análise (no worker)."""

    def __init__(self, redis: Redis, prefixo: str, analise_id: uuid.UUID | str, ttl_s: int) -> None:
        self._redis = redis
        self._prefixo = prefixo
        self._analise_id = analise_id
        self._stream = chave_stream(prefixo, analise_id)
        self._canal = chave_canal(prefixo, analise_id)
        self._ttl = ttl_s
        self._seq: int | None = None

    async def _proximo(self) -> int:
        if self._seq is None:
            # Uma nova tentativa do job continua a numeração (o cliente não vê id repetido).
            ultimo = await self._redis.xrevrange(self._stream, count=1)
            self._seq = int(_do_stream(ultimo[0][0], ultimo[0][1]).id) if ultimo else 0
        self._seq += 1
        return self._seq

    async def publicar(self, tipo: TipoEvento, dados: dict[str, Any]) -> Evento:
        if await foi_apagada(self._redis, self._prefixo, self._analise_id):
            raise AnaliseApagada
        seq = await self._proximo()
        evento = Evento(seq, tipo, dados)
        async with self._redis.pipeline(transaction=True) as tubo:
            tubo.xadd(
                self._stream,
                {"tipo": tipo, "dados": json.dumps(dados, ensure_ascii=False)},
                id=f"{seq}-0",
            )
            tubo.expire(self._stream, self._ttl)
            tubo.publish(self._canal, str(seq))
            await tubo.execute()
        return evento

    async def limpar(self) -> None:
        await self._redis.delete(self._stream, self._canal)


async def ler_depois(
    redis: Redis, prefixo: str, analise_id: uuid.UUID | str, ultimo: int
) -> list[Evento]:
    """Os eventos com id > `ultimo`, em ordem."""
    entradas = await redis.xrange(chave_stream(prefixo, analise_id), min=f"({ultimo}-0", max="+")
    return [_do_stream(i, campos) for i, campos in entradas]


async def ultimo_evento(redis: Redis, prefixo: str, analise_id: uuid.UUID | str) -> Evento | None:
    entradas = await redis.xrevrange(chave_stream(prefixo, analise_id), count=1)
    return _do_stream(entradas[0][0], entradas[0][1]) if entradas else None


class Assinante:
    """Um `PSUBSCRIBE` por processo e o fan-out em memória para as conexões SSE."""

    def __init__(self, redis: Redis, prefixo: str) -> None:
        self._redis = redis
        self._padrao = f"{prefixo}:analise:*:canal"
        self._esperas: dict[str, set[asyncio.Event]] = {}
        self._tarefa: asyncio.Task[None] | None = None
        self._pronto = asyncio.Event()

    @property
    def conexoes(self) -> int:
        return sum(len(s) for s in self._esperas.values())

    async def iniciar(self) -> None:
        if self._tarefa is None or self._tarefa.done():
            self._pronto = asyncio.Event()
            self._tarefa = asyncio.create_task(self._laco())
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._pronto.wait(), timeout=5)

    async def _laco(self) -> None:
        while True:
            pubsub = self._redis.pubsub()
            try:
                await pubsub.psubscribe(self._padrao)
                self._pronto.set()
                while True:
                    mensagem = await pubsub.get_message(ignore_subscribe_messages=True, timeout=5)
                    if mensagem and mensagem.get("type") == "pmessage":
                        for espera in tuple(self._esperas.get(_texto(mensagem["channel"]), ())):
                            espera.set()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # Redis caiu: as conexões seguem pelo heartbeat
                log.warning("eventos.assinante_reconectando", extra={"tipo": type(exc).__name__})
                for esperas in self._esperas.values():
                    for espera in esperas:
                        espera.set()
                await asyncio.sleep(1)
            finally:
                with contextlib.suppress(Exception):
                    await pubsub.aclose()  # type: ignore[no-untyped-call]

    @contextlib.contextmanager
    def assinar(self, canal: str) -> Iterator[asyncio.Event]:
        espera = asyncio.Event()
        self._esperas.setdefault(canal, set()).add(espera)
        try:
            yield espera
        finally:
            esperas = self._esperas.get(canal)
            if esperas is not None:
                esperas.discard(espera)
                if not esperas:
                    del self._esperas[canal]

    async def fechar(self) -> None:
        if self._tarefa is not None:
            self._tarefa.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._tarefa
            self._tarefa = None
