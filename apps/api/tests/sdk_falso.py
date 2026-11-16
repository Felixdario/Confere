"""Um cliente falso que imita o pedaço do `anthropic.AsyncAnthropic` que o `ProvedorAnthropic` usa.

Sem rede: cada chamada consome a próxima resposta roteirizada (uma mensagem, uma exceção do SDK
ou um atraso) e guarda os kwargs recebidos, para os testes conferirem o prompt.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import anthropic
import httpx2 as httpx  # o transporte que o SDK 2.x usa (dependência dele)

REQUISICAO = httpx.Request("POST", "https://api.anthropic.com/v1/messages")


def erro_http(classe: type[anthropic.APIStatusError], status: int) -> anthropic.APIStatusError:
    resposta = httpx.Response(status, request=REQUISICAO, headers={"request-id": "req_teste"})
    return classe("mensagem da API com trecho do currículo", response=resposta, body=None)


def erro_conexao() -> anthropic.APIConnectionError:
    return anthropic.APIConnectionError(request=REQUISICAO)


def erro_timeout() -> anthropic.APITimeoutError:
    return anthropic.APITimeoutError(request=REQUISICAO)


def uso(
    entrada: int = 1000,
    saida: int = 500,
    escrita: int = 0,
    leitura: int = 0,
    iteracoes: list[Any] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        input_tokens=entrada,
        output_tokens=saida,
        cache_creation_input_tokens=escrita,
        cache_read_input_tokens=leitura,
        cache_creation=SimpleNamespace(
            ephemeral_5m_input_tokens=escrita, ephemeral_1h_input_tokens=0
        ),
        iterations=iteracoes,
    )


def mensagem(
    texto: str,
    *,
    modelo: str = "claude-haiku-5-5",
    stop_reason: str = "end_turn",
    usage: SimpleNamespace | None = None,
    categoria: str | None = None,
    blocos_extra: list[Any] | None = None,
) -> SimpleNamespace:
    blocos: list[Any] = [*(blocos_extra or [])]
    if texto:
        blocos.append(SimpleNamespace(type="text", text=texto))
    return SimpleNamespace(
        id="msg_teste",
        model=modelo,
        content=blocos,
        stop_reason=stop_reason,
        stop_details=SimpleNamespace(category=categoria) if stop_reason == "refusal" else None,
        usage=usage or uso(),
        _request_id="req_teste",
    )


@dataclass
class Atraso:
    """Faz a chamada demorar `segundos` (para o tempo limite)."""

    segundos: float
    depois: Any = None


@dataclass
class _Fluxo:
    final: SimpleNamespace
    pedacos: list[str]
    pausa_entre: float = 0.0
    pausa_inicial: float = 0.0

    def __aiter__(self) -> AsyncIterator[Any]:
        return self._eventos()

    async def _eventos(self) -> AsyncIterator[Any]:
        if self.pausa_inicial:
            await asyncio.sleep(self.pausa_inicial)
        yield SimpleNamespace(type="message_start")
        for pedaco in self.pedacos:
            if self.pausa_entre:
                await asyncio.sleep(self.pausa_entre)
            yield SimpleNamespace(
                type="content_block_delta", delta=SimpleNamespace(type="text_delta", text=pedaco)
            )
        yield SimpleNamespace(type="message_stop")

    async def get_final_message(self) -> SimpleNamespace:
        return self.final


@dataclass
class RespostaFluxo:
    """Roteiro de um `messages.stream`: o texto em pedaços e a mensagem final."""

    final: SimpleNamespace
    pedacos: list[str] | None = None
    pausa_entre: float = 0.0
    pausa_inicial: float = 0.0


class _GerenciadorDeFluxo:
    def __init__(self, roteiro: RespostaFluxo | BaseException) -> None:
        self._roteiro = roteiro
        self.saiu = False

    async def __aenter__(self) -> _Fluxo:
        if isinstance(self._roteiro, BaseException):
            raise self._roteiro
        texto = "".join(
            b.text for b in self._roteiro.final.content if getattr(b, "type", None) == "text"
        )
        pedacos = self._roteiro.pedacos
        if pedacos is None:
            pedacos = [texto[i : i + 50] for i in range(0, len(texto), 50)]
        return _Fluxo(
            self._roteiro.final, pedacos, self._roteiro.pausa_entre, self._roteiro.pausa_inicial
        )

    async def __aexit__(self, *_: object) -> None:
        self.saiu = True


@dataclass
class Chamada:
    metodo: str
    kwargs: dict[str, Any]
    opcoes: dict[str, Any]


@dataclass
class ClienteFalso:
    """`respostas`: fila para `messages.create`; `fluxos`: fila para `messages.stream` e
    `beta.messages.stream`. `contagem`: o `input_tokens` do `count_tokens` (ou uma exceção)."""

    respostas: list[Any] = field(default_factory=list)
    fluxos: list[Any] = field(default_factory=list)
    contagem: int | BaseException = 1200
    chamadas: list[Chamada] = field(default_factory=list)
    _opcoes: dict[str, Any] = field(default_factory=dict)

    # --- a superfície do SDK ---------------------------------------------------------------

    def with_options(self, *, timeout: float, max_retries: int) -> ClienteFalso:
        self._opcoes = {"timeout": timeout, "max_retries": max_retries}
        return self

    @property
    def messages(self) -> SimpleNamespace:
        return SimpleNamespace(
            create=self._create, stream=self._stream, count_tokens=self._count_tokens
        )

    @property
    def beta(self) -> SimpleNamespace:
        return SimpleNamespace(messages=SimpleNamespace(stream=self._stream_beta))

    # --- implementação ---------------------------------------------------------------------

    async def _create(self, **kwargs: Any) -> Any:
        self.chamadas.append(Chamada("create", kwargs, dict(self._opcoes)))
        proxima = self.respostas.pop(0)
        if isinstance(proxima, Atraso):
            await asyncio.sleep(proxima.segundos)
            proxima = proxima.depois
        if isinstance(proxima, BaseException):
            raise proxima
        return proxima

    async def _count_tokens(self, **kwargs: Any) -> Any:
        self.chamadas.append(Chamada("count_tokens", kwargs, dict(self._opcoes)))
        if isinstance(self.contagem, BaseException):
            raise self.contagem
        return SimpleNamespace(input_tokens=self.contagem)

    def _stream(self, **kwargs: Any) -> _GerenciadorDeFluxo:
        self.chamadas.append(Chamada("stream", kwargs, dict(self._opcoes)))
        return _GerenciadorDeFluxo(self.fluxos.pop(0))

    def _stream_beta(self, **kwargs: Any) -> _GerenciadorDeFluxo:
        self.chamadas.append(Chamada("beta.stream", kwargs, dict(self._opcoes)))
        return _GerenciadorDeFluxo(self.fluxos.pop(0))

    def das(self, *metodos: str) -> list[Chamada]:
        return [c for c in self.chamadas if c.metodo in metodos]
