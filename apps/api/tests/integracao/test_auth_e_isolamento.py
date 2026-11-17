"""Sessão por cookie, consentimento, limite de login, CSRF em toda rota que muda estado e
isolamento entre usuários em **todas** as rotas com id."""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from dataclasses import replace
from typing import Any

import httpx
from apoio import (
    Pessoa,
    analise_do_candidato,
    cadastrar,
    caso,
    enviar_texto,
    esperar_status,
    hc,
    pegar_csrf,
    rodar_worker,
)
from fastapi import FastAPI

from curriculo_api.api.dependencias import Recursos
from curriculo_api.main import criar_app

CADASTRO = {
    "email": "Alguem@Example.com",
    "senha": "senha comprida 1",
    "aceito_consentimento": True,
    "versao_consentimento": "2026-11-16",
}


async def test_cadastro_exige_consentimento_e_versao(cliente: httpx.AsyncClient) -> None:
    await pegar_csrf(cliente)
    r = await cliente.post(
        "/auth/cadastro", json={**CADASTRO, "aceito_consentimento": False}, headers=hc(cliente)
    )
    assert r.status_code == 422 and r.json()["codigo"] == "consentimento_obrigatorio"
    assert r.headers["content-type"].startswith("application/problem+json")
    r = await cliente.post(
        "/auth/cadastro", json={**CADASTRO, "versao_consentimento": "velha"}, headers=hc(cliente)
    )
    assert r.json()["codigo"] == "consentimento_desatualizado"
    r = await cliente.post("/auth/cadastro", json=CADASTRO, headers=hc(cliente))
    assert r.status_code == 201
    assert r.json()["consentimentos"][0]["versao_texto"] == "2026-11-16"
    # E-mail único sem diferenciar caixa.
    r = await cliente.post(
        "/auth/cadastro", json={**CADASTRO, "email": "alguem@EXAMPLE.com"}, headers=hc(cliente)
    )
    assert r.status_code == 409 and r.json()["codigo"] == "email_em_uso"
    # A validação não ecoa o valor enviado.
    r = await cliente.post(
        "/auth/cadastro", json={**CADASTRO, "email": "sem-arroba"}, headers=hc(cliente)
    )
    assert r.status_code == 422 and "sem-arroba" not in r.text


async def test_cookie_httponly_samesite_e_secure_fora_de_dev(
    cliente: httpx.AsyncClient, recursos: Recursos
) -> None:
    csrf = await pegar_csrf(cliente)
    r = await cliente.post("/auth/cadastro", json=CADASTRO, headers={"X-CSRF-Token": csrf})
    sessao = next(c for c in r.headers.get_list("set-cookie") if c.startswith("curriculo_sessao="))
    assert "HttpOnly" in sessao and "SameSite=lax" in sessao and "Secure" not in sessao

    em_producao = recursos.settings.model_copy(update={"ambiente": "producao"})
    producao = criar_app(em_producao, replace(recursos, settings=em_producao))
    transporte = httpx.ASGITransport(app=producao)
    async with httpx.AsyncClient(transport=transporte, base_url="https://teste") as seguro:
        csrf = await pegar_csrf(seguro)
        r = await seguro.post(
            "/auth/login",
            json={"email": CADASTRO["email"], "senha": CADASTRO["senha"]},
            headers={"X-CSRF-Token": csrf},
        )
        assert r.status_code == 200
        sessao = next(
            c for c in r.headers.get_list("set-cookie") if c.startswith("curriculo_sessao=")
        )
        assert "Secure" in sessao and "HttpOnly" in sessao


async def test_login_logout_e_eu(cliente: httpx.AsyncClient) -> None:
    pessoa = await cadastrar(cliente)
    assert (await pessoa.post("/auth/logout")).status_code == 204
    assert (await pessoa.get("/eu")).status_code == 401
    pessoa.csrf = await pegar_csrf(cliente)  # o logout apagou o cookie CSRF
    errado = await pessoa.post("/auth/login", json={"email": pessoa.email, "senha": "errada!!"})
    assert errado.status_code == 401 and errado.json()["codigo"] == "credenciais_invalidas"
    inexistente = await pessoa.post("/auth/login", json={"email": "x@example.com", "senha": "a"})
    assert inexistente.json()["detail"] == errado.json()["detail"]  # não revela se a conta existe
    certo = await pessoa.post(
        "/auth/login", json={"email": pessoa.email.upper(), "senha": "uma senha longa 123"}
    )
    assert certo.status_code == 200
    assert (await pessoa.get("/eu")).json()["email"] == pessoa.email


async def test_limite_de_login_por_email(cliente: httpx.AsyncClient) -> None:
    pessoa = await cadastrar(cliente)
    for _ in range(5):
        r = await pessoa.post("/auth/login", json={"email": pessoa.email, "senha": "errada"})
        assert r.status_code == 401
    r = await pessoa.post(
        "/auth/login", json={"email": pessoa.email, "senha": "uma senha longa 123"}
    )
    assert r.status_code == 429
    assert r.json()["codigo"] == "limite_de_taxa"
    assert int(r.headers["retry-after"]) > 0


def _rotas(app: FastAPI) -> list[tuple[str, str]]:
    """Todas as rotas publicadas (pelo OpenAPI, que enxerga os routers incluídos)."""
    return sorted(
        (metodo.upper(), caminho)
        for caminho, metodos in app.openapi()["paths"].items()
        for metodo in metodos
    )


async def test_csrf_exigido_em_toda_rota_que_muda_estado(
    app: FastAPI, cliente: httpx.AsyncClient
) -> None:
    pessoa = await cadastrar(cliente)
    mutaveis = [(m, p) for m, p in _rotas(app) if m in ("POST", "DELETE")]
    assert len(mutaveis) >= 9
    falso_id = str(uuid.uuid4())
    for metodo, caminho in mutaveis:
        url = re.sub(r"\{[a-z_]+\}", falso_id, caminho)
        for cabecalho in ({}, {"X-CSRF-Token": "outro-valor"}):
            r = await pessoa.cliente.request(metodo, url, headers=cabecalho, json={})
            assert r.status_code == 403, (metodo, caminho, r.status_code)
            assert r.json()["codigo"] == "csrf"


async def _recursos_de_a(pessoa: Pessoa, recursos: Recursos) -> dict[str, str]:
    analise = (await enviar_texto(pessoa, "b02-backend-pleno-node")).json()
    processo = (
        await pessoa.post(
            "/processos",
            json={
                "vaga_texto": caso("b02-backend-pleno-node", "vaga.md"),
                "declaro_base_legal": True,
            },
        )
    ).json()
    candidato = (
        await pessoa.post(
            f"/processos/{processo['id']}/candidatos",
            data={"texto": caso("b01-frontend-senior", "curriculo.md")},
        )
    ).json()
    await esperar_status(recursos, analise["id"])
    await esperar_status(recursos, await analise_do_candidato(recursos, candidato["id"]))
    return {
        "analise_id": analise["id"],
        "curriculo_id": analise["curriculo"]["id"],
        "vaga_id": analise["vaga"]["id"],
        "processo_id": processo["id"],
        "candidato_id": candidato["id"],
    }


async def test_isolamento_em_todas_as_rotas_com_id(
    app: FastAPI, recursos: Recursos, novo_cliente: Callable[[], httpx.AsyncClient]
) -> None:
    async with rodar_worker(recursos):
        a = await cadastrar(novo_cliente())
        ids = await _recursos_de_a(a, recursos)
    b = await cadastrar(novo_cliente())
    extras: dict[tuple[str, str], dict[str, Any]] = {
        ("GET", "/curriculos/{curriculo_id}/comparacao"): {"params": {"vaga": ids["vaga_id"]}},
        ("POST", "/processos/{processo_id}/candidatos"): {"data": {"texto": "Python e SQL"}},
        ("POST", "/processos/{processo_id}/candidatos/{candidato_id}/decisoes"): {
            "json": {"decisao": "avancar", "justificativa": "tentativa de outra pessoa"}
        },
    }
    com_id = [(m, p) for m, p in _rotas(app) if "{" in p]
    assert len(com_id) >= 11
    for metodo, caminho in com_id:
        url = caminho.format(**ids)
        kw = extras.get((metodo, caminho), {})
        r = await (b.post(url, **kw) if metodo == "POST" else b.get(url, **kw))
        assert r.status_code == 404, (metodo, caminho, r.status_code, r.text)
        # E o dono continua vendo (o 404 é por ser de outra pessoa, não por id errado).
        if metodo == "GET" and not caminho.endswith("/arquivo"):
            dono = await a.get(url, **kw)
            # (a comparação com uma versão só responde 409: existe, mas não há o que comparar)
            assert dono.status_code in (200, 409), (caminho, dono.text)
    # Listas não vazam nada de A.
    assert (await b.get("/analises")).json()["itens"] == []
    assert (await b.get("/curriculos")).json() == []
    assert (await b.get("/processos")).json() == []
    # O envio que referencia ids de A também é recusado.
    r = await b.post("/analises", data={"texto": "Python e SQL", "vaga_id": ids["vaga_id"]})
    assert r.status_code == 404
    r = await b.post(
        "/analises",
        data={
            "texto": "Python e SQL",
            "vaga_texto": "- Python",
            "curriculo_id": ids["curriculo_id"],
        },
    )
    assert r.status_code == 404
