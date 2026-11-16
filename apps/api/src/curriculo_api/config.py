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

    # Limiares de similaridade da correspondência (ADR 0002/0003), calibrados na fase 3.
    tau_alto: float = Field(default=0.85, ge=0, le=1)
    tau_baixo: float = Field(default=0.70, ge=0, le=1)

    retencao_dias: int = Field(default=30, ge=1)
    teto_custo_diario_usd: float = Field(default=5.0, ge=0)
    pasta_arquivos: Path = Path("data/arquivos")

    @property
    def usa_provedor_falso(self) -> bool:
        return self.anthropic_api_key is None or not self.anthropic_api_key.get_secret_value()


@lru_cache
def obter_settings() -> Settings:
    return Settings()
