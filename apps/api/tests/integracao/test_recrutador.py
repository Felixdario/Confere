"""Modo recrutador: limite de 20, visão anonimizada, nenhuma decisão automática, revelar."""

from __future__ import annotations

from collections.abc import Callable

import httpx
from apoio import analise_do_candidato, cadastrar, caso, esperar_status, rodar_worker
from sqlalchemy import func, select

from curriculo_api.api.dependencias import Recursos
from curriculo_api.config import Settings
from curriculo_api.db.modelos import DecisaoHumana
from curriculo_api.main import criar_app

VAGA = caso("b01-frontend-senior", "vaga.md")
TEXTO = caso("b02-backend-pleno-node", "curriculo.md")


async def test_processo_exige_base_legal(cliente: httpx.AsyncClient) -> None:
    pessoa = await cadastrar(cliente)
    r = await pessoa.post("/processos", json={"vaga_texto": VAGA, "declaro_base_legal": False})
    assert r.status_code == 422 and r.json()["codigo"] == "base_legal_obrigatoria"
    r = await pessoa.post("/processos", json={"vaga_texto": VAGA, "declaro_base_legal": True})
    assert r.status_code == 201
    tipos = [c["tipo"] for c in (await pessoa.get("/eu")).json()["consentimentos"]]
    assert "recrutador_base_legal" in tipos


async def test_vigesimo_primeiro_curriculo_e_recusado(
    fazer_settings: Callable[..., Settings], recursos: Recursos
) -> None:
    app = criar_app(fazer_settings(), recursos)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://teste"
    ) as c:
        pessoa = await cadastrar(c)
        processo = (
            await pessoa.post("/processos", json={"vaga_texto": VAGA, "declaro_base_legal": True})
        ).json()
        assert processo["limite_candidatos"] == 20
        rotulos = []
        for _ in range(20):
            r = await pessoa.post(f"/processos/{processo['id']}/candidatos", data={"texto": TEXTO})
            assert r.status_code == 202, r.text
            rotulos.append(r.json()["rotulo"])
        assert rotulos[0] == "Candidato A" and rotulos[-1] == "Candidato T"
        assert len(set(rotulos)) == 20
        r = await pessoa.post(f"/processos/{processo['id']}/candidatos", data={"texto": TEXTO})
        assert r.status_code == 422
        assert r.json()["codigo"] == "limite_candidatos"
        assert r.headers["content-type"].startswith("application/problem+json")
        assert (await pessoa.get(f"/processos/{processo['id']}")).json()["candidatos"] == 20


async def test_nenhuma_decisao_automatica_e_justificativa_obrigatoria(
    cliente: httpx.AsyncClient, recursos: Recursos
) -> None:
    pessoa = await cadastrar(cliente)
    processo = (
        await pessoa.post("/processos", json={"vaga_texto": VAGA, "declaro_base_legal": True})
    ).json()
    pid = processo["id"]
    async with rodar_worker(recursos):
        candidatos = []
        for nome in ("b01-frontend-senior", "b16-administrativo-sem-desejaveis"):
            r = await pessoa.post(
                f"/processos/{pid}/candidatos", data={"texto": caso(nome, "curriculo.md")}
            )
            candidatos.append(r.json())
        for c in candidatos:
            await esperar_status(recursos, await analise_do_candidato(recursos, c["id"]))
    # Análises prontas, inclusive uma com nota baixa: ninguém foi decidido nem descartado.
    ranking = (await pessoa.get(f"/processos/{pid}")).json()
    assert len(ranking["ranking"]) == 2
    assert all(c["decisao"] is None for c in ranking["ranking"])
    assert "não descarta ninguém" in ranking["aviso"]
    for c in candidatos:
        detalhe = (await pessoa.get(f"/processos/{pid}/candidatos/{c['id']}")).json()
        assert detalhe["decisoes"] == []
    async with recursos.fabrica() as db:
        assert (await db.execute(select(func.count()).select_from(DecisaoHumana))).scalar_one() == 0

    url = f"/processos/{pid}/candidatos/{candidatos[1]['id']}/decisoes"
    sem = await pessoa.post(url, json={"decisao": "nao_avancar"})
    assert sem.status_code == 422
    curta = await pessoa.post(
        url, json={"decisao": "nao_avancar", "justificativa": "     não       "}
    )
    assert curta.status_code == 422
    invalida = await pessoa.post(
        url, json={"decisao": "rejeitar", "justificativa": "motivo bem escrito"}
    )
    assert invalida.status_code == 422
    ok = await pessoa.post(
        url, json={"decisao": "nao_avancar", "justificativa": "Sem experiência em front-end."}
    )
    assert ok.status_code == 201
    de_novo = await pessoa.post(
        url, json={"decisao": "pendente", "justificativa": "Rever depois da entrevista."}
    )
    assert de_novo.status_code == 201
    detalhe = (await pessoa.get(f"/processos/{pid}/candidatos/{candidatos[1]['id']}")).json()
    assert [d["decisao"] for d in detalhe["decisoes"]] == ["nao_avancar", "pendente"]  # histórico
    assert detalhe["decisao"]["decisao"] == "pendente"
    async with recursos.fabrica() as db:
        assert (await db.execute(select(func.count()).select_from(DecisaoHumana))).scalar_one() == 2


async def test_visao_anonimizada_e_revelar_registrado(
    cliente: httpx.AsyncClient, recursos: Recursos
) -> None:
    pessoa = await cadastrar(cliente)
    processo = (
        await pessoa.post("/processos", json={"vaga_texto": VAGA, "declaro_base_legal": True})
    ).json()
    pid = processo["id"]
    async with rodar_worker(recursos):
        c = (
            await pessoa.post(
                f"/processos/{pid}/candidatos",
                data={"texto": caso("b01-frontend-senior", "curriculo.md")},
            )
        ).json()
        await esperar_status(recursos, await analise_do_candidato(recursos, c["id"]))
    ranking = await pessoa.get(f"/processos/{pid}")
    detalhe = await pessoa.get(f"/processos/{pid}/candidatos/{c['id']}")
    for resposta in (ranking, detalhe):
        texto = resposta.text
        # Nem nome, nem e-mail, nem caminho do arquivo na visão do recrutador.
        assert "Mariana" not in texto and "@example.com" not in texto and "/arquivo" not in texto
    assert detalhe.json()["identidade_revelada_em"] is None
    url_arquivo = f"/processos/{pid}/candidatos/{c['id']}/arquivo"
    proibido = await pessoa.get(url_arquivo)
    assert proibido.status_code == 403 and proibido.json()["codigo"] == "identidade_nao_revelada"
    revelado = (await pessoa.post(f"/processos/{pid}/candidatos/{c['id']}/revelar")).json()
    assert revelado["identidade_revelada_em"] and revelado["arquivo_url"] == url_arquivo
    arquivo = await pessoa.get(url_arquivo)
    assert arquivo.status_code == 200 and arquivo.content
