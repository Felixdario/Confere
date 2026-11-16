"""`ProvedorAnthropic`: o SDK oficial atrás de `ProvedorIA` (ADR 0001). É o único módulo que fala
com a API.

Decisões (detalhes e motivos no ADR 0001):
- **Saída estruturada sem `messages.parse`.** As extrações usam `messages.create` com
  `output_config.format` = o schema que o próprio SDK gera do modelo Pydantic
  (`anthropic.transform_schema`, o mesmo que `messages.parse(output_format=...)` envia), e a
  validação Pydantic é feita aqui. Motivo: `parse` valida dentro do SDK e, se a validação falha
  (resposta cortada por `max_tokens`, recusa no meio da saída ou uma regra nossa como "fim antes do
  início"), levanta a exceção sem devolver a mensagem: perderíamos o `usage` (o custo da tentativa)
  e o `stop_reason` (a recusa precisa ser checada antes do conteúdo).
- **Feedback em streaming com saída estruturada** (`messages.stream`, no Opus pelo
  `beta.messages.stream` com o fallback do servidor). O texto que chega é o JSON sendo escrito; os
  eventos `texto` o repassam como chegou e o evento `final` traz o `FeedbackIA` validado.
- **1 nova tentativa** quando a saída não valida, com os erros de validação no prompt. Erros de
  rede, 429 e 5xx ficam com as novas tentativas do SDK (`max_retries`).
- **Tempo limite por etapa** com `asyncio.timeout` em volta da chamada (o do SDK vale por tentativa
  HTTP). No feedback: até o primeiro evento e entre eventos.
- **Custo** de cada chamada pelo `usage` (com `usage.iterations` quando há fallback) e pela tabela
  versionada de `precos.py`; o teto da análise é verificado antes de cada chamada.
- **Logs só com metadados** (etapa, modelo, tokens, custo, duração, stop_reason, request id).
  Nunca o currículo, a vaga, a resposta, a mensagem de erro da API nem o erro de validação.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Literal, Protocol

import anthropic
from pydantic import BaseModel, ValidationError

from curriculo_api.ia.modelos import (
    CurriculoExtraido,
    Etapa,
    EventoFeedback,
    FeedbackIA,
    RegistroUso,
    Resposta,
    TabelaDaNota,
    TextoAnonimizado,
    VagaExtraida,
)
from curriculo_api.ia.precos import Tokens, custo, custo_maximo, preco_de
from curriculo_api.ia.prompts import (
    delimitar,
    json_estavel,
    mensagem_do_usuario,
    system_da_etapa,
)
from curriculo_api.ia.provedor import (
    ErroAutenticacao,
    ErroConexao,
    ErroLimiteDeTaxa,
    ErroProvedor,
    ErroRequisicao,
    ErroServidor,
    Recusa,
    SaidaInvalida,
    TempoEsgotado,
)
from curriculo_api.taxonomia import Taxonomia

if TYPE_CHECKING:
    from curriculo_api.config import Settings
    from curriculo_api.ia.orcamento import Orcamento

log = logging.getLogger("curriculo_api.ia.anthropic")

BETA_FALLBACK = "server-side-fallback-2026-07-01"
MODELOS_COM_FALLBACK_DO_SERVIDOR = frozenset({"claude-opus-5-5"})
MODELOS_DE_RESERVA = ("claude-opus-5", "claude-opus-4-8")
"""Os modelos que o `fallbacks: "default"` pode escolher (documentação do fallback do
servidor). O teto reserva o pior caso da cadeia inteira."""
"""Só onde a documentação garante o `fallbacks: "default"`. O Haiku 5.5 não tem fallback do
servidor (com ele, um pedido recusado continua recusado)."""

MENSAGEM_RECUSA = "não foi possível analisar este conteúdo (a IA recusou o pedido)"
TENTATIVAS_DE_VALIDACAO = 2
Esforco = Literal["low", "medium", "high"]

NOME_DA_ETAPA: dict[Etapa, str] = {
    "extrair_curriculo": "a extração do currículo",
    "extrair_vaga": "a extração da vaga",
    "escrever_feedback": "o feedback",
}


class ClienteAnthropic(Protocol):
    """O pedaço do `anthropic.AsyncAnthropic` que usamos (os testes injetam um falso)."""

    @property
    def messages(self) -> Any: ...

    @property
    def beta(self) -> Any: ...

    def with_options(self, *, timeout: float, max_retries: int) -> Any: ...


@dataclass(frozen=True)
class ConfigAnthropic:
    modelo_extracao: str = "claude-haiku-5-5"
    modelo_feedback: str = "claude-opus-5-5"
    esforco_extracao: Esforco = "low"
    esforco_feedback: Esforco = "medium"
    max_tokens_extracao: int = 8000
    max_tokens_feedback: int = 8000
    timeout_extracao_s: float = 20.0
    timeout_feedback_primeiro_evento_s: float = 40.0
    timeout_feedback_ocioso_s: float = 40.0
    max_retries: int = 2
    fallback_feedback: bool = True
    estimar_com_count_tokens: bool = True
    timeout_count_tokens_s: float = 5.0
    caracteres_por_token: float = 2.5

    @classmethod
    def de_settings(cls, settings: Settings) -> ConfigAnthropic:
        return cls(
            modelo_extracao=settings.claude_modelo_extracao,
            modelo_feedback=settings.claude_modelo_feedback,
            esforco_extracao=settings.claude_esforco_extracao,
            esforco_feedback=settings.claude_esforco_feedback,
            max_tokens_extracao=settings.claude_max_tokens_extracao,
            max_tokens_feedback=settings.claude_max_tokens_feedback,
            timeout_extracao_s=settings.claude_timeout_extracao_s,
            timeout_feedback_primeiro_evento_s=settings.claude_timeout_feedback_primeiro_evento_s,
            timeout_feedback_ocioso_s=settings.claude_timeout_feedback_ocioso_s,
            max_retries=settings.claude_max_retries,
            fallback_feedback=settings.claude_fallback_feedback,
            estimar_com_count_tokens=settings.claude_estimar_com_count_tokens,
            timeout_count_tokens_s=settings.claude_timeout_count_tokens_s,
            caracteres_por_token=settings.estimativa_caracteres_por_token,
        )


def schema_de(modelo: type[BaseModel]) -> dict[str, Any]:
    """O `output_config.format` que `messages.parse(output_format=modelo)` enviaria."""
    return {"type": "json_schema", "schema": anthropic.transform_schema(modelo)}


def formatar_erros_de_validacao(erro: ValidationError) -> str:
    """Os erros sem o valor de entrada (só caminho e mensagem), para o prompt da nova tentativa."""
    linhas = []
    for item in erro.errors(include_input=False, include_url=False)[:20]:
        caminho = ".".join(str(p) for p in item["loc"]) or "(raiz)"
        linhas.append(f"- {caminho}: {item['msg']}")
    return "\n".join(linhas)


def _tokens_do_usage(usage: Any) -> Tokens:
    criacao = int(getattr(usage, "cache_creation_input_tokens", None) or 0)
    detalhe = getattr(usage, "cache_creation", None)
    uma_hora = int(getattr(detalhe, "ephemeral_1h_input_tokens", None) or 0) if detalhe else 0
    uma_hora = min(uma_hora, criacao)
    return Tokens(
        entrada=int(getattr(usage, "input_tokens", 0) or 0),
        saida=int(getattr(usage, "output_tokens", 0) or 0),
        cache_escrita_5m=criacao - uma_hora,
        cache_escrita_1h=uma_hora,
        cache_leitura=int(getattr(usage, "cache_read_input_tokens", None) or 0),
    )


def custo_da_resposta(modelo_pedido: str, resposta: Any) -> tuple[Tokens, Decimal, bool]:
    """Tokens somados, custo em US$ e se um modelo de reserva respondeu.

    Com o fallback do servidor, `usage.iterations` é a fonte por tentativa (o `usage` do topo
    cobre só a tentativa que produziu a mensagem): cada entrada `message`/`fallback_message` é
    cobrada pelo preço do próprio modelo."""
    usage = resposta.usage
    iteracoes = [
        it
        for it in (getattr(usage, "iterations", None) or [])
        if getattr(it, "type", None) in ("message", "fallback_message")
    ]
    if not iteracoes:
        tokens = _tokens_do_usage(usage)
        modelo = getattr(resposta, "model", None) or modelo_pedido
        return tokens, custo(modelo, tokens), False
    soma = Tokens()
    total = Decimal(0)
    for it in iteracoes:
        tokens = _tokens_do_usage(it)
        modelo = getattr(it, "model", None) or modelo_pedido
        total += custo(str(modelo), tokens)
        soma = Tokens(
            entrada=soma.entrada + tokens.entrada,
            saida=soma.saida + tokens.saida,
            cache_escrita_5m=soma.cache_escrita_5m + tokens.cache_escrita_5m,
            cache_escrita_1h=soma.cache_escrita_1h + tokens.cache_escrita_1h,
            cache_leitura=soma.cache_leitura + tokens.cache_leitura,
        )
    houve_fallback = any(getattr(it, "type", None) == "fallback_message" for it in iteracoes)
    return soma, total, houve_fallback


def texto_da_resposta(resposta: Any) -> str:
    """Os blocos `text`, em ordem (os de `thinking` e `fallback` ficam de fora). Com fallback no
    meio da saída, o modelo de reserva continua o texto parcial, então a concatenação é a
    resposta inteira."""
    return "".join(b.text for b in resposta.content if getattr(b, "type", None) == "text")


def traduzir_erro(erro: Exception, etapa: Etapa) -> ErroProvedor:
    """Erros do SDK → erros tipados com mensagem clara em pt-BR (sem a mensagem da API, que pode
    citar trechos da requisição)."""
    nome = NOME_DA_ETAPA[etapa]
    if isinstance(erro, anthropic.APITimeoutError):
        return TempoEsgotado(f"a API não respondeu a tempo durante {nome}")
    if isinstance(erro, anthropic.APIConnectionError):
        return ErroConexao(f"sem conexão com a API da Anthropic durante {nome}; confira a rede")
    if isinstance(erro, anthropic.AuthenticationError | anthropic.PermissionDeniedError):
        return ErroAutenticacao(
            f"a API recusou a chave ({erro.status_code}); confira ANTHROPIC_API_KEY e as "
            "permissões da organização"
        )
    if isinstance(erro, anthropic.RateLimitError):
        return ErroLimiteDeTaxa(
            f"limite de requisições da API atingido (429) durante {nome}, mesmo depois das novas "
            "tentativas; espere alguns minutos e tente de novo"
        )
    if isinstance(erro, anthropic.APIStatusError) and erro.status_code >= 500:
        return ErroServidor(
            f"a API da Anthropic está instável ({erro.status_code}) durante {nome}; tente de novo "
            "em alguns minutos"
        )
    if isinstance(erro, anthropic.APIStatusError):
        tipo = f", {erro.type}" if erro.type else ""
        return ErroRequisicao(
            f"a API recusou a requisição durante {nome} ({erro.status_code}{tipo}); é um erro de "
            "configuração ou do código, não do currículo"
        )
    return ErroProvedor(f"falha inesperada do SDK durante {nome} ({type(erro).__name__})")


@dataclass(frozen=True)
class _Chamada:
    etapa: Etapa
    modelo: str
    esforco: Esforco
    max_tokens: int
    system: list[dict[str, Any]]
    blocos: list[str]

    def kwargs(self, erro_anterior: str | None, formato: dict[str, Any]) -> dict[str, Any]:
        return {
            "model": self.modelo,
            "max_tokens": self.max_tokens,
            "system": self.system,
            "messages": mensagem_do_usuario(self.blocos, erro_anterior),
            "output_config": {"effort": self.esforco, "format": formato},
        }


class ProvedorAnthropic:
    def __init__(
        self,
        cliente: ClienteAnthropic,
        taxonomia: Taxonomia,
        config: ConfigAnthropic | None = None,
        relogio: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._cliente = cliente
        self._taxonomia = taxonomia
        self._config = config or ConfigAnthropic()
        self._relogio = relogio
        for modelo in (self._config.modelo_extracao, self._config.modelo_feedback):
            preco_de(modelo)  # falha cedo se o modelo não tem preço na tabela

    @property
    def nome(self) -> str:
        return "anthropic"

    @property
    def config(self) -> ConfigAnthropic:
        return self._config

    # --- custo e uso ------------------------------------------------------------------------

    async def _estimar_entrada(self, kwargs: dict[str, Any], limite_s: float) -> tuple[int, str]:
        """`count_tokens` com tempo limite próprio (uma fração do tempo da etapa); se falhar ou
        demorar, a estimativa pelo tamanho."""
        if self._config.estimar_com_count_tokens:
            try:
                contagem = await asyncio.wait_for(
                    self._cliente.messages.count_tokens(
                        model=kwargs["model"],
                        system=kwargs["system"],
                        messages=kwargs["messages"],
                        output_config=kwargs["output_config"],
                    ),
                    limite_s,
                )
                return int(contagem.input_tokens), "count_tokens"
            except (anthropic.APIError, TimeoutError):
                pass
        caracteres = sum(len(b["text"]) for b in kwargs["system"]) + sum(
            len(c["text"]) for m in kwargs["messages"] for c in m["content"]
        )
        return math.ceil(caracteres / self._config.caracteres_por_token), "tamanho"

    def pior_caso(self, chamada: _Chamada, tokens: int) -> Decimal:
        """Pior caso de uma chamada. Com o fallback do servidor, a tentativa e a do modelo de
        reserva podem ser cobradas: duas vezes o pior caso, ao preço do mais caro da cadeia."""
        if chamada.etapa == "escrever_feedback" and self.usa_fallback_do_servidor():
            cadeia = (chamada.modelo, *MODELOS_DE_RESERVA)
            return 2 * max(custo_maximo(m, tokens, chamada.max_tokens) for m in cadeia)
        return custo_maximo(chamada.modelo, tokens, chamada.max_tokens)

    async def _verificar_orcamento(
        self,
        chamada: _Chamada,
        kwargs: dict[str, Any],
        orcamento: Orcamento | None,
        tempo_da_etapa_s: float,
    ) -> Decimal:
        """Reserva no orçamento o pior caso da chamada (devolvido, para `liberar` ou `consumir`
        depois)."""
        if orcamento is None:
            return Decimal(0)
        limite = min(self._config.timeout_count_tokens_s, tempo_da_etapa_s / 4)
        tokens, metodo = await self._estimar_entrada(kwargs, limite)
        estimativa = self.pior_caso(chamada, tokens)
        log.info(
            "ia.estimativa",
            extra={
                "etapa": chamada.etapa,
                "modelo": chamada.modelo,
                "tokens_entrada": tokens,
                "metodo": metodo,
                "custo_max_usd": str(estimativa),
            },
        )
        orcamento.verificar(estimativa)
        return estimativa

    def _uso(self, chamada: _Chamada, tentativa: int, inicio: float, resposta: Any) -> RegistroUso:
        tokens, valor, houve_fallback = custo_da_resposta(chamada.modelo, resposta)
        uso = RegistroUso(
            etapa=chamada.etapa,
            modelo=str(getattr(resposta, "model", None) or chamada.modelo),
            tentativa=tentativa,
            duracao_ms=max(0, round((self._relogio() - inicio) * 1000)),
            input_tokens=tokens.entrada,
            output_tokens=tokens.saida,
            cache_creation_input_tokens=tokens.cache_escrita,
            cache_read_input_tokens=tokens.cache_leitura,
            custo_usd=valor,
            stop_reason=getattr(resposta, "stop_reason", None),
            fallback=houve_fallback,
        )
        log.info(
            "ia.chamada",
            extra={
                "etapa": uso.etapa,
                "modelo": uso.modelo,
                "tentativa": uso.tentativa,
                "duracao_ms": uso.duracao_ms,
                "input_tokens": uso.input_tokens,
                "output_tokens": uso.output_tokens,
                "cache_creation_input_tokens": uso.cache_creation_input_tokens,
                "cache_read_input_tokens": uso.cache_read_input_tokens,
                "custo_usd": str(uso.custo_usd),
                "stop_reason": uso.stop_reason,
                "fallback": uso.fallback,
                "request_id": getattr(resposta, "_request_id", None),
            },
        )
        return uso

    def _checar_recusa(self, chamada: _Chamada, resposta: Any, usos: Sequence[RegistroUso]) -> None:
        if getattr(resposta, "stop_reason", None) != "refusal":
            return
        detalhes = getattr(resposta, "stop_details", None)
        log.warning(
            "ia.recusa",
            extra={
                "etapa": chamada.etapa,
                "modelo": chamada.modelo,
                "categoria": getattr(detalhes, "category", None),
            },
        )
        raise _com_usos(Recusa(MENSAGEM_RECUSA), usos)

    # --- extrações --------------------------------------------------------------------------

    async def _extrair[T: BaseModel](
        self, chamada: _Chamada, modelo: type[T], orcamento: Orcamento | None
    ) -> Resposta[T]:
        formato = schema_de(modelo)
        usos: list[RegistroUso] = []
        erro_anterior: str | None = None
        cliente = self._cliente.with_options(
            timeout=self._config.timeout_extracao_s, max_retries=self._config.max_retries
        )
        for tentativa in range(1, TENTATIVAS_DE_VALIDACAO + 1):
            kwargs = chamada.kwargs(erro_anterior, formato)
            prazo = asyncio.get_running_loop().time() + self._config.timeout_extracao_s
            reserva = await self._verificar_orcamento(
                chamada, kwargs, orcamento, self._config.timeout_extracao_s
            )
            inicio = self._relogio()
            cobrar_reserva = True  # sem `usage`, o pior caso vira gasto (o servidor pode cobrar)
            try:
                async with asyncio.timeout_at(prazo):
                    resposta = await cliente.messages.create(**kwargs)
                cobrar_reserva = False
            except TimeoutError:
                log.warning("ia.tempo_esgotado", extra={"etapa": chamada.etapa})
                raise _com_usos(
                    TempoEsgotado(
                        f"{NOME_DA_ETAPA[chamada.etapa]} passou de "
                        f"{self._config.timeout_extracao_s:g} s"
                    ),
                    usos,
                ) from None
            except anthropic.APIError as exc:
                cobrar_reserva = not isinstance(exc, anthropic.APIStatusError)
                _log_erro(chamada.etapa, exc)
                raise _com_usos(traduzir_erro(exc, chamada.etapa), usos) from None
            finally:
                _fechar_reserva(orcamento, reserva, cobrar_reserva)
            uso = self._uso(chamada, tentativa, inicio, resposta)
            usos.append(uso)
            if orcamento is not None:
                orcamento.registrar([uso])
            self._checar_recusa(chamada, resposta, usos)
            saida, erro_anterior = validar(modelo, resposta)
            if saida is not None:
                return Resposta(saida=saida, usos=tuple(usos))
            log.warning(
                "ia.saida_invalida",
                extra={
                    "etapa": chamada.etapa,
                    "tentativa": tentativa,
                    "stop_reason": uso.stop_reason,
                },
            )
        raise _com_usos(
            SaidaInvalida(
                f"a resposta da IA para {NOME_DA_ETAPA[chamada.etapa]} não passou na validação "
                f"depois de {TENTATIVAS_DE_VALIDACAO} tentativas"
            ),
            usos,
        )

    async def extrair_curriculo(
        self, texto: TextoAnonimizado, *, orcamento: Orcamento | None = None
    ) -> Resposta[CurriculoExtraido]:
        chamada = _Chamada(
            etapa="extrair_curriculo",
            modelo=self._config.modelo_extracao,
            esforco=self._config.esforco_extracao,
            max_tokens=self._config.max_tokens_extracao,
            system=system_da_etapa("extrair_curriculo", self._taxonomia),
            blocos=[delimitar("curriculo", texto)],
        )
        return await self._extrair(chamada, CurriculoExtraido, orcamento)

    async def extrair_vaga(
        self, texto: str, *, orcamento: Orcamento | None = None
    ) -> Resposta[VagaExtraida]:
        chamada = _Chamada(
            etapa="extrair_vaga",
            modelo=self._config.modelo_extracao,
            esforco=self._config.esforco_extracao,
            max_tokens=self._config.max_tokens_extracao,
            system=system_da_etapa("extrair_vaga", self._taxonomia),
            blocos=[delimitar("vaga", texto)],
        )
        return await self._extrair(chamada, VagaExtraida, orcamento)

    # --- feedback ---------------------------------------------------------------------------

    def _chamada_feedback(
        self,
        tabela: TabelaDaNota,
        curriculo: CurriculoExtraido,
        vaga: VagaExtraida,
        texto: TextoAnonimizado,
    ) -> _Chamada:
        documento = json_estavel(
            {
                "nota": tabela.nota,
                "decomposicao": tabela.decomposicao,
                "avisos": list(tabela.avisos),
                "requisitos": [
                    {
                        "descricao": linha.descricao,
                        "tipo": linha.tipo,
                        "status": linha.status,
                        "competencia_pedida": linha.competencia_pedida,
                        "evidencia": linha.evidencia,
                        "motivo": linha.motivo,
                    }
                    for linha in tabela.linhas
                ],
                "competencias_comprovadas": sorted(
                    {c.nome for c in curriculo.competencias}
                    | {i.idioma for i in curriculo.idiomas}
                    | {c.nome for c in curriculo.certificacoes}
                ),
            }
        )
        resumo_vaga = f"{vaga.titulo}\n" + "\n".join(
            f"- ({r.tipo}) {r.descricao}" for r in vaga.requisitos
        )
        return _Chamada(
            etapa="escrever_feedback",
            modelo=self._config.modelo_feedback,
            esforco=self._config.esforco_feedback,
            max_tokens=self._config.max_tokens_feedback,
            system=system_da_etapa("escrever_feedback", self._taxonomia),
            blocos=[
                delimitar("documento", documento),
                delimitar("curriculo", texto),
                delimitar("vaga", resumo_vaga),
            ],
        )

    def usa_fallback_do_servidor(self) -> bool:
        return (
            self._config.fallback_feedback
            and self._config.modelo_feedback in MODELOS_COM_FALLBACK_DO_SERVIDOR
        )

    def _abrir_fluxo(self, kwargs: dict[str, Any]) -> Any:
        cliente = self._cliente.with_options(
            timeout=self._config.timeout_feedback_primeiro_evento_s,
            max_retries=self._config.max_retries,
        )
        if self.usa_fallback_do_servidor():
            return cliente.beta.messages.stream(
                **kwargs, betas=[BETA_FALLBACK], fallbacks="default"
            )
        return cliente.messages.stream(**kwargs)

    async def escrever_feedback(
        self,
        tabela: TabelaDaNota,
        curriculo: CurriculoExtraido,
        vaga: VagaExtraida,
        texto: TextoAnonimizado,
        *,
        orcamento: Orcamento | None = None,
    ) -> AsyncIterator[EventoFeedback]:
        chamada = self._chamada_feedback(tabela, curriculo, vaga, texto)
        formato = schema_de(FeedbackIA)
        usos: list[RegistroUso] = []
        erro_anterior: str | None = None
        yield EventoFeedback(tipo="etapa", texto="escrevendo o feedback")
        for tentativa in range(1, TENTATIVAS_DE_VALIDACAO + 1):
            if tentativa > 1:
                yield EventoFeedback(tipo="etapa", texto="nova tentativa do feedback")
            kwargs = chamada.kwargs(erro_anterior, formato)
            reserva = await self._verificar_orcamento(
                chamada, kwargs, orcamento, self._config.timeout_feedback_primeiro_evento_s
            )
            inicio = self._relogio()
            final: list[Any] = []
            cobrar_reserva = True
            try:
                async for pedaco in self._fluxo(kwargs, final):
                    yield EventoFeedback(tipo="texto", texto=pedaco)
                cobrar_reserva = not final
            except TimeoutError:
                log.warning("ia.tempo_esgotado", extra={"etapa": chamada.etapa})
                raise _com_usos(
                    TempoEsgotado(
                        "a API ficou mais de "
                        f"{self._config.timeout_feedback_ocioso_s:g} s sem mandar nada durante "
                        "o feedback"
                    ),
                    usos,
                ) from None
            except anthropic.APIError as exc:
                cobrar_reserva = not isinstance(exc, anthropic.APIStatusError)
                _log_erro(chamada.etapa, exc)
                raise _com_usos(traduzir_erro(exc, chamada.etapa), usos) from None
            finally:
                _fechar_reserva(orcamento, reserva, cobrar_reserva)
            resposta = final[0]
            uso = self._uso(chamada, tentativa, inicio, resposta)
            usos.append(uso)
            if orcamento is not None:
                orcamento.registrar([uso])
            self._checar_recusa(chamada, resposta, usos)
            saida, erro_anterior = validar(FeedbackIA, resposta)
            if saida is not None:
                yield EventoFeedback(tipo="final", feedback=saida, usos=tuple(usos))
                return
            log.warning(
                "ia.saida_invalida",
                extra={
                    "etapa": chamada.etapa,
                    "tentativa": tentativa,
                    "stop_reason": uso.stop_reason,
                },
            )
        raise _com_usos(
            SaidaInvalida(
                "a resposta da IA para o feedback não passou na validação depois de "
                f"{TENTATIVAS_DE_VALIDACAO} tentativas"
            ),
            usos,
        )

    async def _fluxo(self, kwargs: dict[str, Any], final: list[Any]) -> AsyncIterator[str]:
        """Abre o fluxo e repassa cada pedaço de texto assim que chega; no fim, põe a mensagem
        final em `final`. O primeiro evento tem `timeout_feedback_primeiro_evento_s`; cada
        seguinte, `timeout_feedback_ocioso_s`."""
        gerenciador = self._abrir_fluxo(kwargs)
        fluxo = await asyncio.wait_for(
            gerenciador.__aenter__(), self._config.timeout_feedback_primeiro_evento_s
        )
        try:
            eventos = aiter(fluxo)
            limite = self._config.timeout_feedback_primeiro_evento_s
            while True:
                try:
                    evento = await asyncio.wait_for(anext(eventos), limite)
                except StopAsyncIteration:
                    break
                limite = self._config.timeout_feedback_ocioso_s
                if (
                    getattr(evento, "type", None) == "content_block_delta"
                    and getattr(evento.delta, "type", None) == "text_delta"
                ):
                    yield str(evento.delta.text)
            final.append(await fluxo.get_final_message())
        finally:
            await gerenciador.__aexit__(None, None, None)


def validar[T: BaseModel](modelo: type[T], resposta: Any) -> tuple[T | None, str | None]:
    """(saída validada, None) ou (None, erros para a nova tentativa)."""
    if getattr(resposta, "stop_reason", None) == "max_tokens":
        return None, (
            "- a resposta foi cortada pelo limite de tokens antes de terminar; seja mais conciso "
            "nos textos e mantenha o JSON completo"
        )
    texto = texto_da_resposta(resposta)
    if not texto.strip():
        return None, "- a resposta veio vazia; devolva o JSON pedido"
    try:
        return modelo.model_validate_json(texto), None
    except ValidationError as exc:
        return None, formatar_erros_de_validacao(exc)


def _fechar_reserva(orcamento: Orcamento | None, reserva: Decimal, cobrar: bool) -> None:
    """Sem `usage` (tempo esgotado, conexão, cancelamento pelo `TaskGroup`), a reserva vira gasto;
    com resposta, ou com erro HTTP da API (que não cobra), ela é só liberada e o gasto real entra
    pelo `registrar`."""
    if orcamento is None:
        return
    if cobrar:
        orcamento.consumir(reserva)
        log.warning("ia.reserva_cobrada", extra={"custo_max_usd": str(reserva)})
    else:
        orcamento.liberar(reserva)


def _com_usos(erro: ErroProvedor, usos: Sequence[RegistroUso]) -> ErroProvedor:
    erro.usos = tuple(usos)
    return erro


def _log_erro(etapa: Etapa, exc: Exception) -> None:
    log.warning(
        "ia.erro",
        extra={
            "etapa": etapa,
            "tipo": type(exc).__name__,
            "status": getattr(exc, "status_code", None),
            "request_id": getattr(exc, "request_id", None),
        },
    )
