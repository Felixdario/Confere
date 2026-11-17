"""Erros em `application/problem+json` (RFC 9457), com mensagens em pt-BR (ADR 0007).

Todo erro tem `codigo` estável (o front usa) e `detail` para a pessoa. Nenhum erro ecoa o que foi
enviado: a validação devolve só o campo e o motivo, nunca o valor.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from curriculo_api.analise.erros import ErroAnalise
from curriculo_api.ingestao.erros import ArquivoGrande, ErroIngestao
from curriculo_api.logs import id_requisicao

TIPO_BASE = "https://curriculo.dev/erros/"
MIDIA_PROBLEMA = "application/problem+json"


class CampoInvalido(BaseModel):
    campo: str = Field(examples=["corpo.email"])
    motivo: str = Field(examples=["valor inválido"])


class Problema(BaseModel):
    """Corpo de todo erro (RFC 9457)."""

    type: str = Field(examples=[TIPO_BASE + "sem_texto"])
    title: str = Field(examples=["O currículo não pode ser lido"])
    status: int = Field(examples=[422])
    detail: str = Field(
        examples=[
            "O PDF não tem texto selecionável (parece escaneado), e o OCR não está disponível "
            "nesta versão. Exporte o currículo do editor de texto como PDF ou cole o texto."
        ]
    )
    codigo: str = Field(examples=["sem_texto"])
    instance: str | None = Field(default=None, examples=["/analises"])
    id_requisicao: str | None = None
    campos: list[CampoInvalido] | None = None


class ErroApi(Exception):
    """Erro com status e mensagem para a tela. `cabecalhos` vai na resposta (`Retry-After`)."""

    def __init__(
        self,
        status: int,
        codigo: str,
        mensagem: str,
        titulo: str | None = None,
        cabecalhos: dict[str, str] | None = None,
    ) -> None:
        super().__init__(mensagem)
        self.status = status
        self.codigo = codigo
        self.mensagem = mensagem
        self.titulo = titulo or TITULOS.get(status, "Erro")
        self.cabecalhos = cabecalhos or {}


TITULOS: dict[int, str] = {
    400: "Requisição inválida",
    401: "Sessão necessária",
    403: "Acesso recusado",
    404: "Não encontrado",
    409: "Conflito",
    413: "Arquivo grande demais",
    415: "Formato não suportado",
    422: "Não foi possível processar",
    429: "Limite atingido",
    500: "Erro interno",
    503: "Serviço indisponível",
}


def nao_encontrado(recurso: str = "recurso") -> ErroApi:
    # O mesmo 404 para "não existe" e "é de outra pessoa": não confirma que o id existe.
    return ErroApi(404, "nao_encontrado", f"{recurso.capitalize()} não encontrado.")


def problema(
    status: int,
    codigo: str,
    detalhe: str,
    request: Request,
    titulo: str | None = None,
    cabecalhos: dict[str, str] | None = None,
    campos: list[CampoInvalido] | None = None,
) -> JSONResponse:
    corpo = Problema(
        type=TIPO_BASE + codigo,
        title=titulo or TITULOS.get(status, "Erro"),
        status=status,
        detail=detalhe,
        codigo=codigo,
        instance=request.url.path,
        id_requisicao=id_requisicao.get(),
        campos=campos,
    )
    return JSONResponse(
        corpo.model_dump(exclude_none=True),
        status_code=status,
        media_type=MIDIA_PROBLEMA,
        headers=cabecalhos,
    )


_MOTIVOS_DE_VALIDACAO = {
    "missing": "campo obrigatório",
    "string_too_short": "texto curto demais",
    "string_too_long": "texto longo demais",
    "value_error": "valor inválido",
    "uuid_parsing": "identificador inválido",
    "literal_error": "valor fora das opções",
    "bool_parsing": "esperado verdadeiro ou falso",
    "int_parsing": "esperado um número inteiro",
}


def _campo(loc: tuple[Any, ...]) -> str:
    traducao = {"body": "corpo", "query": "consulta", "path": "caminho", "header": "cabecalho"}
    return ".".join(traducao.get(str(p), str(p)) for p in loc)


def instalar(app: FastAPI) -> None:
    @app.exception_handler(ErroApi)
    async def _erro_api(request: Request, exc: ErroApi) -> JSONResponse:
        return problema(exc.status, exc.codigo, exc.mensagem, request, exc.titulo, exc.cabecalhos)

    @app.exception_handler(ErroIngestao)
    async def _erro_ingestao(request: Request, exc: ErroIngestao) -> JSONResponse:
        status = 413 if isinstance(exc, ArquivoGrande) else 422
        titulo = "O currículo não pode ser lido" if status == 422 else None
        return problema(status, exc.codigo, exc.mensagem, request, titulo)

    @app.exception_handler(ErroAnalise)
    async def _erro_analise(request: Request, exc: ErroAnalise) -> JSONResponse:
        return problema(422, exc.codigo, exc.mensagem[:1].upper() + exc.mensagem[1:] + ".", request)

    @app.exception_handler(RequestValidationError)
    async def _validacao(request: Request, exc: RequestValidationError) -> JSONResponse:
        campos = [
            CampoInvalido(
                campo=_campo(tuple(e.get("loc", ()))),
                motivo=_MOTIVOS_DE_VALIDACAO.get(str(e.get("type")), "valor inválido"),
            )
            for e in exc.errors()
        ]
        return problema(
            422,
            "validacao",
            "Alguns campos estão faltando ou são inválidos.",
            request,
            "Dados inválidos",
            campos=campos,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        mensagens = {
            404: "Rota não encontrada.",
            405: "Método não permitido nesta rota.",
        }
        return problema(
            exc.status_code,
            "http_" + str(exc.status_code),
            mensagens.get(exc.status_code, "Requisição não atendida."),
            request,
        )

    # O erro inesperado (500) é tratado no `MiddlewareRequisicao`, sem a mensagem nos logs.


RESPOSTAS_DE_ERRO: dict[int | str, dict[str, Any]] = {
    status: {"model": Problema, "content": {MIDIA_PROBLEMA: {}}, "description": titulo}
    for status, titulo in TITULOS.items()
}


def respostas(*status: int) -> dict[int | str, dict[str, Any]]:
    """Os modelos de erro de uma rota, para o OpenAPI."""
    return {s: RESPOSTAS_DE_ERRO[s] for s in status}
