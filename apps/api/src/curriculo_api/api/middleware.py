"""Middleware ASGI: id da requisição, log de acesso sem conteúdo e o 500 controlado.

O erro inesperado é tratado aqui, e não só pelo handler de `Exception` do Starlette, porque lá a
exceção é relançada depois da resposta e o servidor a registra com a mensagem (que pode citar
conteúdo do currículo). Aqui ela termina: o log leva só o tipo e a pilha sem mensagem.
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from curriculo_api.api.erros import MIDIA_PROBLEMA, TIPO_BASE
from curriculo_api.logs import id_requisicao, pilha_sem_mensagem

log = logging.getLogger("curriculo_api.acesso")
_ID_VALIDO = re.compile(r"^[A-Za-z0-9-]{8,64}$")
CABECALHO_ID = "x-request-id"


class MiddlewareRequisicao:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        recebido = dict(scope.get("headers") or []).get(CABECALHO_ID.encode(), b"").decode()
        rid = recebido if _ID_VALIDO.match(recebido) else uuid.uuid4().hex
        token = id_requisicao.set(rid)
        inicio = time.perf_counter()
        status = 500
        iniciou = False

        async def enviar(mensagem: Message) -> None:
            nonlocal status, iniciou
            if mensagem["type"] == "http.response.start":
                iniciou = True
                status = int(mensagem["status"])
                mensagem["headers"] = [
                    *mensagem.get("headers", []),
                    (CABECALHO_ID.encode(), rid.encode()),
                ]
            await send(mensagem)

        try:
            await self.app(scope, receive, enviar)
        except Exception as exc:
            log.error(
                "api.erro_interno",
                extra={"tipo": type(exc).__name__, "pilha": pilha_sem_mensagem(exc)},
            )
            if not iniciou:
                corpo = json.dumps(
                    {
                        "type": TIPO_BASE + "erro_interno",
                        "title": "Erro interno",
                        "status": 500,
                        "detail": "Algo deu errado do nosso lado. Tente de novo em instantes; se "
                        "continuar, avise com o id da requisição.",
                        "codigo": "erro_interno",
                        "instance": scope.get("path", ""),
                        "id_requisicao": rid,
                    },
                    ensure_ascii=False,
                ).encode()
                await enviar(
                    {
                        "type": "http.response.start",
                        "status": 500,
                        "headers": [
                            (b"content-type", MIDIA_PROBLEMA.encode()),
                            (b"content-length", str(len(corpo)).encode()),
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": corpo})
        finally:
            rota = scope.get("route")
            log.info(
                "api.requisicao",
                extra={
                    "metodo": scope.get("method"),
                    # O modelo da rota ("/analises/{analise_id}"), não o caminho com os ids.
                    "rota": getattr(rota, "path", None) or "(sem rota)",
                    "status": status,
                    "duracao_ms": round((time.perf_counter() - inicio) * 1000),
                },
            )
            id_requisicao.reset(token)
