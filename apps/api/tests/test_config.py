"""A URL do banco como os provedores a entregam vira uma URL que o asyncpg aceita."""

import pytest

from curriculo_api.config import Settings, normalizar_url_banco


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        (
            "postgresql://u:s@ep-x.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require",
            "postgresql+asyncpg://u:s@ep-x.us-east-1.aws.neon.tech/neondb?ssl=require",
        ),
        ("postgres://u:s@host:5432/db", "postgresql+asyncpg://u:s@host:5432/db"),
        (
            "postgresql+asyncpg://curriculo:curriculo@localhost:5434/curriculo",
            "postgresql+asyncpg://curriculo:curriculo@localhost:5434/curriculo",
        ),
        ("postgresql://u:s@h/db?sslmode=disable", "postgresql+asyncpg://u:s@h/db"),
        (
            "postgresql://u:s@h/db?sslmode=require&application_name=confere",
            "postgresql+asyncpg://u:s@h/db?application_name=confere&ssl=require",
        ),
    ],
)
def test_normaliza_url_do_banco(entrada: str, esperado: str) -> None:
    assert normalizar_url_banco(entrada) == esperado


def test_settings_aplica_a_normalizacao(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:s@h/db?sslmode=require")
    assert Settings().database_url == "postgresql+asyncpg://u:s@h/db?ssl=require"


def test_intervalo_do_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    assert Settings().worker_intervalo_s == 0.5
    monkeypatch.setenv("WORKER_INTERVALO_S", "2")
    assert Settings().worker_intervalo_s == 2.0
    monkeypatch.setenv("WORKER_INTERVALO_S", "0")
    with pytest.raises(ValueError):
        Settings()
