import pytest
from httpx import ASGITransport, AsyncClient

from curriculo_api.config import obter_settings
from curriculo_api.main import app


@pytest.fixture(autouse=True)
def sem_chave(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    obter_settings.cache_clear()


async def test_saude_responde_ok_com_provedor_falso() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://teste") as cliente:
        resposta = await cliente.get("/saude")

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["status"] == "ok"
    assert corpo["provedor_ia"] == "falso"


async def test_openapi_publicado() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://teste") as cliente:
        resposta = await cliente.get("/openapi.json")

    assert resposta.status_code == 200
    assert "/saude" in resposta.json()["paths"]
