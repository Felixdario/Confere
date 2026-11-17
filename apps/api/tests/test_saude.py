from httpx import ASGITransport, AsyncClient

from curriculo_api.config import Settings
from curriculo_api.main import criar_app


def _settings(**valores: object) -> Settings:
    return Settings(_env_file=None, anthropic_api_key=None, **valores)  # type: ignore[arg-type]


async def test_saude_responde_ok_no_modo_demonstracao() -> None:
    # Sem PROVEDOR_IA, o padrão é o de regras (ADR 0006), mesmo sem chave. `/saude` não usa banco.
    app = criar_app(_settings())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://teste") as cliente:
        resposta = await cliente.get("/saude")

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["status"] == "ok"
    assert corpo["provedor_ia"] == "regras"
    assert corpo["modo_demonstracao"] is True
    assert resposta.headers["x-request-id"]


async def test_saude_com_o_provedor_falso() -> None:
    app = criar_app(_settings(provedor_ia="falso"))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://teste") as cliente:
        corpo = (await cliente.get("/saude")).json()
    assert corpo["provedor_ia"] == "falso"


async def test_openapi_publicado() -> None:
    app = criar_app(_settings())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://teste") as cliente:
        resposta = await cliente.get("/openapi.json")

    assert resposta.status_code == 200
    caminhos = resposta.json()["paths"]
    for rota in ("/saude", "/analises", "/analises/{analise_id}/eventos", "/eu/dados"):
        assert rota in caminhos


async def test_rota_inexistente_em_problem_json() -> None:
    app = criar_app(_settings())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://teste") as cliente:
        resposta = await cliente.get("/nao-existe")
    assert resposta.status_code == 404
    assert resposta.headers["content-type"].startswith("application/problem+json")
    assert resposta.json()["codigo"] == "http_404"
