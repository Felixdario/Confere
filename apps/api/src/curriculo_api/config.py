"""Configuração lida do ambiente (e de um `.env`, se existir)."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+asyncpg://curriculo:curriculo@localhost:5434/curriculo"
    redis_url: str = "redis://localhost:6381/0"

    # Sem chave, a API usa o provedor falso (respostas gravadas) — ver ADR 0001.
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

    @property
    def usa_provedor_falso(self) -> bool:
        return self.anthropic_api_key is None or not self.anthropic_api_key.get_secret_value()


@lru_cache
def obter_settings() -> Settings:
    return Settings()
