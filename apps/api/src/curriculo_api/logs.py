"""Logs estruturados (JSON, uma linha por evento) com o id da requisição (ADR 0004 e 0007).

Regra: o log leva ids, rota, status, etapa, duração, contagens e custo. **Nunca** texto de
currículo ou de vaga, trecho, nome de arquivo, e-mail, senha, valor removido pela anonimização nem
a mensagem de uma exceção (que pode citar conteúdo): de exceções inesperadas vão só o tipo e os
quadros da pilha (arquivo, linha, função), sem a mensagem e sem variáveis.
"""

from __future__ import annotations

import json
import logging
import traceback
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

id_requisicao: ContextVar[str | None] = ContextVar("id_requisicao", default=None)

_ATRIBUTOS_PADRAO = frozenset(
    vars(logging.LogRecord("", 0, "", 0, "", None, None)).keys() | {"message", "asctime"}
)


class FormatoJson(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        dados: dict[str, Any] = {
            "em": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "nivel": record.levelname,
            "logger": record.name,
            "evento": record.getMessage(),
        }
        rid = id_requisicao.get()
        if rid is not None:
            dados["id_requisicao"] = rid
        for chave, valor in vars(record).items():
            if chave not in _ATRIBUTOS_PADRAO and not chave.startswith("_"):
                dados[chave] = valor
        return json.dumps(dados, ensure_ascii=False, default=str)


def pilha_sem_mensagem(exc: BaseException) -> list[str]:
    """Os quadros da exceção ("arquivo:linha função"), sem a mensagem nem o código-fonte."""
    return [
        f"{q.filename.rsplit('/', 1)[-1].rsplit(chr(92), 1)[-1]}:{q.lineno} {q.name}"
        for q in traceback.extract_tb(exc.__traceback__)
    ][-8:]


def configurar_logs(nivel: int = logging.INFO) -> None:
    """Um handler JSON na raiz (idempotente). O acesso do uvicorn sai pelo nosso middleware, que
    registra a rota sem a query string."""
    raiz = logging.getLogger()
    if not any(isinstance(h.formatter, FormatoJson) for h in raiz.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(FormatoJson())
        raiz.addHandler(handler)
    raiz.setLevel(nivel)
    for nome in ("uvicorn.access",):
        logging.getLogger(nome).disabled = True
    for nome in ("sqlalchemy.engine", "httpx", "httpcore", "arq.worker", "arq.jobs"):
        logging.getLogger(nome).setLevel(logging.WARNING)
