"""Configuração lida do ambiente (e de um `.env`, se existir)."""

from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_SSL_EXIGIDO = {"require", "verify-ca", "verify-full"}


def normalizar_url_banco(url: str) -> str:
    """Aceita a URL como os provedores a entregam (Neon, Render: `postgresql://...?sslmode=require`).

    O driver é o asyncpg, que não conhece `sslmode` nem `channel_binding` vindos do SQLAlchemy:
    o esquema vira `postgresql+asyncpg` e o SSL exigido vira `ssl=require`, que ele entende.
    """
    partes = urlsplit(url)
    esquema = partes.scheme
    if esquema in {"postgres", "postgresql"}:
        esquema = "postgresql+asyncpg"
    consulta = []
    ssl = None
    for chave, valor in parse_qsl(partes.query, keep_blank_values=True):
        if chave == "sslmode":
            ssl = "require" if valor in _SSL_EXIGIDO else ssl
        elif chave != "channel_binding":
            consulta.append((chave, valor))
    if ssl and not any(chave == "ssl" for chave, _ in consulta):
        consulta.append(("ssl", ssl))
    return urlunsplit((esquema, partes.netloc, partes.path, urlencode(consulta), partes.fragment))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    ambiente: Literal["dev", "teste", "producao"] = Field(
        default="dev", description="Fora de dev/teste o cookie de sessão sai com `Secure`."
    )
    database_url: str = "postgresql+asyncpg://curriculo:curriculo@localhost:5434/curriculo"

    @field_validator("database_url")
    @classmethod
    def _url_para_asyncpg(cls, valor: str) -> str:
        return normalizar_url_banco(valor)

    redis_url: str = "redis://localhost:6381/0"
    redis_prefixo: str = Field(
        default="curriculo",
        description="Prefixo de toda chave do Redis desta aplicação (fila, eventos, limites).",
    )

    # Provedor da análise (ADR 0006): `regras` é o modo demonstração, sem IA e sem custo; `falso`
    # responde só os textos gravados das evals (testes e seed); `anthropic` exige a chave e só
    # roda quando pedido explicitamente (D-46: este portfólio não gasta com a API).
    provedor_ia: Literal["regras", "falso", "anthropic"] = "regras"
    pasta_gravacoes: Path = Path("evals/gravacoes")

    # Sem chave, o provedor real não existe — ver ADR 0001.
    anthropic_api_key: SecretStr | None = None
    claude_modelo_extracao: str = "claude-haiku-5-5"
    claude_modelo_feedback: str = "claude-opus-5-5"
    claude_esforco_extracao: Literal["low", "medium", "high"] = "low"
    claude_esforco_feedback: Literal["low", "medium", "high"] = "medium"

    # Provedor real (ADR 0001). Tempos em segundos; o SDK faz as novas tentativas de rede.
    claude_max_tokens_extracao: int = Field(default=8000, ge=256)
    claude_max_tokens_feedback: int = Field(default=8000, ge=256)
    claude_timeout_extracao_s: float = Field(default=20.0, gt=0)
    claude_timeout_feedback_primeiro_evento_s: float = Field(default=40.0, gt=0)
    claude_timeout_feedback_ocioso_s: float = Field(
        default=40.0, gt=0, description="Tempo máximo sem nenhum evento novo no fluxo."
    )
    claude_max_retries: int = Field(default=2, ge=0, le=5)
    claude_fallback_feedback: bool = Field(
        default=True, description="Fallback do servidor (`fallbacks: default`) no feedback."
    )
    claude_estimar_com_count_tokens: bool = Field(
        default=True, description="Estima a entrada com `count_tokens` antes de chamar."
    )
    claude_timeout_count_tokens_s: float = Field(
        default=5.0, gt=0, description="Limite do `count_tokens` (no máximo 1/4 da etapa)."
    )
    # Heurística conservadora para estimar tokens sem `count_tokens` (não medida; calibrar com o
    # `usage` real da primeira rodada).
    estimativa_caracteres_por_token: float = Field(default=2.5, gt=0)
    teto_custo_analise_usd: float = Field(
        default=0.60, gt=0, description="Interrompe a análise antes de uma chamada que o passaria."
    )

    # Limiares de similaridade da correspondência (ADR 0002/0003), calibrados na fase 3.
    tau_alto: float = Field(default=0.85, ge=0, le=1)
    tau_baixo: float = Field(default=0.70, ge=0, le=1)
    modelo_embeddings: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    pasta_modelos: Path = Path("data/modelos")

    retencao_dias: int = Field(default=30, ge=1)
    teto_custo_diario_usd: float = Field(default=5.0, ge=0)
    pasta_arquivos: Path = Path("data/arquivos")

    # Limites da ingestão (ADR 0004). O DOCX é zip: o limite descompactado barra zip bomb.
    ingestao_tamanho_max_bytes: int = Field(default=5 * 1024 * 1024, ge=1)
    ingestao_paginas_max: int = Field(default=20, ge=1)
    ingestao_descompactado_max_bytes: int = Field(default=30 * 1024 * 1024, ge=1)
    ingestao_entradas_zip_max: int = Field(default=1000, ge=1)
    ingestao_texto_max_caracteres: int = Field(default=60_000, ge=1)
    ingestao_tempo_max_por_pagina_s: float = Field(default=5.0, gt=0)
    ingestao_documento_xml_max_bytes: int = Field(default=5 * 1024 * 1024, ge=1)

    # Sessão e CSRF (ADR 0007).
    sessao_dias: int = Field(default=7, ge=1, le=90)
    versao_consentimento: str = Field(
        default="2026-11-16", description="Versão do texto de consentimento (LGPD) em vigor."
    )
    cors_origens: tuple[str, ...] = ("http://localhost:3010",)

    # Abuso (ADR 0004): janelas fixas no Redis.
    limite_login_por_email: int = Field(default=5, ge=1, description="Tentativas a cada 15 min.")
    limite_login_por_ip: int = Field(default=30, ge=1, description="Tentativas a cada 15 min.")
    limite_cadastro_por_ip: int = Field(default=10, ge=1, description="Cadastros por hora.")
    limite_analises_por_usuario: int = Field(default=30, ge=1, description="Análises por hora.")
    limite_analises_por_ip: int = Field(default=60, ge=1, description="Análises por hora.")
    max_candidatos_por_processo: int = Field(default=20, ge=1, le=100)

    # CSRF ligado à sessão (ADR 0007): HMAC com esta chave. Sem ela, cada processo sorteia uma
    # (os tokens deixam de valer num reinício; com mais de um processo da API, defina a chave).
    chave_csrf: SecretStr | None = None

    # SSE e fila (ADR 0007).
    limite_sse_por_usuario: int = Field(default=5, ge=1, description="Conexões SSE simultâneas.")
    limite_sse_por_ip: int = Field(default=10, ge=1, description="Conexões SSE simultâneas.")
    redis_max_conexoes: int = Field(default=50, ge=4, description="Teto do pool da API.")
    sse_duracao_max_s: float | None = Field(
        default=None, gt=0, description="Teto de uma conexão SSE; padrão TEMPO_MAX_ANALISE_S + 120."
    )
    sse_heartbeat_s: float = Field(default=15.0, gt=0)
    eventos_ttl_s: int = Field(default=24 * 3600, ge=60)
    tempo_max_analise_s: int = Field(default=300, ge=10)

    # Embeddings: `make modelos` baixa o modelo para PASTA_MODELOS; sem ele, o worker não baixa no
    # meio de uma análise (a correspondência fica só na taxonomia, com aviso).
    baixar_modelo_na_analise: bool = False

    @property
    def duracao_max_sse_s(self) -> float:
        return self.sse_duracao_max_s or float(self.tempo_max_analise_s + 120)

    @property
    def usa_provedor_falso(self) -> bool:
        """Sem chave da Anthropic (o provedor real não pode existir)."""
        return self.anthropic_api_key is None or not self.anthropic_api_key.get_secret_value()

    @property
    def cookie_seguro(self) -> bool:
        return self.ambiente not in ("dev", "teste")

    @property
    def modo_demonstracao(self) -> bool:
        return self.provedor_ia != "anthropic"


@lru_cache
def obter_settings() -> Settings:
    return Settings()
