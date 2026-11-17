"""O fluxo SSE de uma análise (ADR 0007), usado por `/analises/{id}/eventos` e pela rota de
candidato do modo recrutador.

Rodada 1 da revisão da fase 4:
- **um assinante pub/sub por processo** (`eventos.Assinante`): a conexão SSE espera num
  `asyncio.Event` em memória, não numa conexão Redis própria;
- **limite de conexões simultâneas** por usuário e por IP (`LIMITE_SSE_POR_USUARIO`,
  `LIMITE_SSE_POR_IP`), contadas no Redis com validade de segurança; excesso → `429`;
- **sempre fecha**: se o último evento do stream é terminal e o cliente já o tem (`Last-Event-ID`
  igual ou maior, o que o `EventSource` manda ao reconectar), o evento terminal é **reenviado** com
  o mesmo id e o fluxo fecha (o front trata `final`/`erro` repetido como idempotente); o status do
  banco é conferido a cada heartbeat; e a conexão tem duração máxima (`SSE_DURACAO_MAX_S`, padrão
  `TEMPO_MAX_ANALISE_S` + 120 s), depois da qual fecha com o comentário `: reconecte`;
- `Last-Event-ID` e `desde` só aceitam `^[0-9]{1,18}$`; o resto é `400`.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
import time
import uuid
from collections.abc import AsyncIterator

from fastapi import Request
from fastapi.responses import StreamingResponse

from curriculo_api.api.dependencias import Recursos, ip_do_cliente
from curriculo_api.api.erros import ErroApi
from curriculo_api.db.modelos import Analise
from curriculo_api.eventos import TERMINAIS, Evento, chave_canal, ler_depois, ultimo_evento

_ID_DE_EVENTO = re.compile(r"^[0-9]{1,18}$")
CONFIRMACOES_DO_BANCO = 2
"""Quantas voltas seguidas o banco diz "terminou" sem o evento terminal no stream antes de o SSE
responder pelo banco (o worker grava o banco e publica o final logo depois)."""


def ler_id_de_evento(valor: str | None, nome: str) -> int | None:
    if valor is None or not valor.strip():
        return None
    if not _ID_DE_EVENTO.match(valor.strip()):
        raise ErroApi(
            400, "id_de_evento_invalido", f"{nome} precisa ser um número inteiro de 0 a 18 dígitos."
        )
    return int(valor.strip())


def _chaves_de_contagem(recursos: Recursos, usuario_id: uuid.UUID, ip: str) -> tuple[str, str]:
    p = recursos.settings.redis_prefixo
    return f"{p}:sse:usuario:{usuario_id}", f"{p}:sse:ip:{ip}"


async def _reservar_conexao(recursos: Recursos, usuario_id: uuid.UUID, ip: str) -> tuple[str, str]:
    s = recursos.settings
    chave_usuario, chave_ip = _chaves_de_contagem(recursos, usuario_id, ip)
    validade = int(s.duracao_max_sse_s) + 60  # se um processo morrer, a contagem some sozinha
    async with recursos.redis.pipeline(transaction=True) as tubo:
        tubo.incr(chave_usuario)
        tubo.expire(chave_usuario, validade)
        tubo.incr(chave_ip)
        tubo.expire(chave_ip, validade)
        n_usuario, _, n_ip, _ = await tubo.execute()
    if int(n_usuario) > s.limite_sse_por_usuario or int(n_ip) > s.limite_sse_por_ip:
        await _liberar_conexao(recursos, chave_usuario, chave_ip)
        raise ErroApi(
            429,
            "limite_de_conexoes",
            "Há conexões de acompanhamento demais abertas ao mesmo tempo. Feche outras abas e "
            "tente de novo.",
            cabecalhos={"Retry-After": "5"},
        )
    return chave_usuario, chave_ip


async def _liberar_conexao(recursos: Recursos, *chaves: str) -> None:
    async with recursos.redis.pipeline(transaction=True) as tubo:
        for chave in chaves:
            tubo.decr(chave)
        await tubo.execute()


async def _do_banco(recursos: Recursos, analise_id: uuid.UUID, proximo: int) -> Evento | None:
    """O evento terminal a partir do banco, se a análise terminou (ou sumiu: erro)."""
    async with recursos.fabrica() as db:
        analise = await db.get(Analise, analise_id)
    if analise is None:
        return Evento(proximo, "erro", {"codigo": "nao_encontrado", "mensagem": "Análise apagada."})
    if analise.status == "concluida":
        dados = {"status": "concluida", "nota": analise.nota, "analise_id": str(analise_id)}
        return Evento(proximo, "final", dados)
    if analise.status == "erro":
        return Evento(
            proximo, "erro", {"codigo": analise.erro_codigo, "mensagem": analise.erro_mensagem}
        )
    return None


async def fluxo_de_eventos(
    recursos: Recursos,
    analise_id: uuid.UUID,
    ultimo: int,
    request: Request,
    chaves: tuple[str, ...] = (),
    so_etapas: bool = False,
) -> AsyncIterator[str]:
    redis = recursos.redis
    s = recursos.settings
    prefixo = s.redis_prefixo
    fim = time.monotonic() + s.duracao_max_sse_s
    terminado_no_banco = 0
    try:
        assinante = await recursos.obter_assinante()
        with assinante.assinar(chave_canal(prefixo, analise_id)) as acordar:
            yield "retry: 3000\n\n"
            while True:
                acordar.clear()
                novos = await ler_depois(redis, prefixo, analise_id, ultimo)
                for evento in novos:
                    ultimo = evento.id
                    if so_etapas and evento.tipo == "texto":
                        continue
                    yield evento.sse()
                    if evento.tipo in TERMINAIS:
                        return
                if not novos:
                    derradeiro = await ultimo_evento(redis, prefixo, analise_id)
                    if derradeiro is not None and derradeiro.tipo in TERMINAIS:
                        # O cliente já tem o terminal (ou pediu além dele): reenvia e fecha.
                        yield derradeiro.sse()
                        return
                    banco = await _do_banco(recursos, analise_id, ultimo + 1)
                    if banco is not None:
                        terminado_no_banco += 1
                        if derradeiro is None or terminado_no_banco >= CONFIRMACOES_DO_BANCO:
                            yield banco.sse()
                            return
                    else:
                        terminado_no_banco = 0
                if time.monotonic() >= fim:
                    yield ": tempo máximo desta conexão; reconecte com Last-Event-ID\n\n"
                    return
                if await request.is_disconnected():
                    return
                espera = min(s.sse_heartbeat_s, max(0.0, fim - time.monotonic()))
                try:
                    await asyncio.wait_for(acordar.wait(), timeout=espera)
                except TimeoutError:
                    yield ": ping\n\n"
    finally:
        if chaves:
            # Mesmo com a tarefa cancelada (cliente caiu), a vaga da conexão volta.
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.shield(_liberar_conexao(recursos, *chaves))


async def abrir_sse(
    recursos: Recursos,
    request: Request,
    usuario_id: uuid.UUID,
    analise_id: uuid.UUID,
    last_event_id: str | None,
    desde: str | None,
    so_etapas: bool = False,
) -> StreamingResponse:
    ultimo = ler_id_de_evento(last_event_id, "Last-Event-ID")
    if ultimo is None:
        ultimo = ler_id_de_evento(desde, "desde") or 0
    chaves = await _reservar_conexao(recursos, usuario_id, ip_do_cliente(request))
    return StreamingResponse(
        fluxo_de_eventos(recursos, analise_id, ultimo, request, chaves, so_etapas),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
