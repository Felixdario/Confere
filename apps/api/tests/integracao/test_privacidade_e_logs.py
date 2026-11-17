"""Privacidade (o que guardamos, retenção com relógio injetável, cron do worker) e logs sem
conteúdo (caplog nas rotas principais, no worker e num erro 500)."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from apoio import SENHA as SENHA_APOIO
from apoio import (
    cadastrar,
    caso,
    criar_executor,
    esperar_status,
    hc,
    pegar_csrf,
    rodar_worker,
)
from fastapi import FastAPI

from curriculo_api.api.dependencias import Recursos
from curriculo_api.db.modelos import Analise, CurriculoVersao
from curriculo_api.seed import EMAIL, SENHA, semear
from curriculo_api.servicos.privacidade import limpar_vencidos
from curriculo_api.worker import tarefa_limpar_vencidos


async def test_privacidade_vem_da_configuracao(cliente: httpx.AsyncClient) -> None:
    r = (await cliente.get("/privacidade")).json()
    assert r["retencao_dias"] == 30
    assert "30 dias" in r["texto_consentimento"]
    assert r["versao_texto"] == "2026-11-16"
    assert any("mascarado" in i["dado"] for i in r["o_que_guardamos"])
    assert "sem IA" in r["o_que_vai_para_a_ia"]


async def test_retencao_apaga_conteudo_vencido_com_relogio_injetavel(
    cliente: httpx.AsyncClient, recursos: Recursos, pasta_arquivos: Path
) -> None:
    pessoa = await cadastrar(cliente)
    async with rodar_worker(recursos):
        criada = (
            await pessoa.post(
                "/analises",
                data={
                    "texto": caso("b02-backend-pleno-node", "curriculo.md"),
                    "vaga_texto": caso("b02-backend-pleno-node", "vaga.md"),
                },
            )
        ).json()
        await esperar_status(recursos, criada["id"])
    arquivos = list(pasta_arquivos.rglob("*.txt"))
    assert len(arquivos) == 1
    agora = datetime.now(UTC)

    async with recursos.fabrica() as db:  # dia 29: nada vence
        r = await limpar_vencidos(
            db, recursos.redis, recursos.settings, lambda: agora + timedelta(days=29)
        )
    assert r.versoes == 0 and arquivos[0].exists()

    async with recursos.fabrica() as db:  # dia 31: o conteúdo sai, a nota fica
        r = await limpar_vencidos(
            db, recursos.redis, recursos.settings, lambda: agora + timedelta(days=31)
        )
    assert (r.versoes, r.arquivos, r.analises) == (1, 1, 1)
    assert not arquivos[0].exists()
    async with recursos.fabrica() as db:
        analise = await db.get(Analise, uuid.UUID(criada["id"]))
        assert analise is not None
        versao = await db.get(CurriculoVersao, analise.curriculo_versao_id)
        assert versao is not None
        assert versao.texto_anonimizado is None and versao.arquivo is None
        assert versao.removidos == [] and versao.alertas == []
        assert analise.tabela is None and analise.feedback is None and analise.nota is not None
    # A limpeza também apagou as sessões vencidas (a desta pessoa, de 7 dias): entra de novo.
    assert (await pessoa.get("/eu")).status_code == 401
    pessoa.csrf = await pegar_csrf(cliente)
    entrou = await pessoa.post("/auth/login", json={"email": pessoa.email, "senha": SENHA_APOIO})
    assert entrou.status_code == 200
    detalhe = (await pessoa.get(criada["resultado_url"])).json()
    assert detalhe["conteudo_apagado"] is True and detalhe["requisitos"] == []
    assert detalhe["nota"] is not None
    # Rodar de novo não faz nada (idempotente); o cron do worker usa o mesmo código e relógio.
    executor = criar_executor(recursos)
    executor.agora = lambda: agora + timedelta(days=40)
    assert (await tarefa_limpar_vencidos({"executor": executor}))["versoes"] == 0


MARCADORES = ("ZQXMARCADORCV", "ZQXMARCADORVAGA", "zqx.pessoa@example.com", "ZqxSenhaUnica")


async def test_logs_sem_conteudo(
    app: FastAPI, cliente: httpx.AsyncClient, recursos: Recursos, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)

    @app.get("/teste-erro")
    async def _erro() -> None:
        raise RuntimeError(f"falhou lendo {MARCADORES[0]}")

    curriculo = caso("b02-backend-pleno-node", "curriculo.md").replace(
        "## Sobre mim", f"## Sobre mim\n\nProjeto {MARCADORES[0]} com Node e Docker."
    )
    vaga = caso("b02-backend-pleno-node", "vaga.md") + f"\n- {MARCADORES[1]}\n"
    (await cliente.get("/auth/csrf")).json()["csrf"]
    await cliente.post(
        "/auth/cadastro",
        json={
            "email": MARCADORES[2],
            "senha": MARCADORES[3],
            "aceito_consentimento": True,
            "versao_consentimento": "2026-11-16",
        },
        headers=hc(cliente),
    )
    await cliente.post(
        "/auth/login", json={"email": MARCADORES[2], "senha": "errada"}, headers=hc(cliente)
    )
    await cliente.post(
        "/auth/login", json={"email": MARCADORES[2], "senha": MARCADORES[3]}, headers=hc(cliente)
    )
    async with rodar_worker(recursos):
        r = await cliente.post(
            "/analises", data={"texto": curriculo, "vaga_texto": vaga}, headers=hc(cliente)
        )
        assert r.status_code == 202
        analise = r.json()
        await esperar_status(recursos, analise["id"])
    await cliente.get(analise["resultado_url"])
    await cliente.get(analise["eventos_url"])
    await cliente.get(f"/analises/{analise['id']}/relatorio.pdf")
    await cliente.post(
        "/analises", data={"texto": "x", "vaga_texto": vaga}, headers=hc(cliente)
    )  # 422
    erro = await cliente.get("/teste-erro")
    assert erro.status_code == 500
    assert erro.headers["content-type"].startswith("application/problem+json")
    assert MARCADORES[0] not in erro.text
    await cliente.delete("/eu/dados", headers=hc(cliente))

    registros = caplog.text + " ".join(str(vars(r)) for r in caplog.records)
    for marcador in MARCADORES:
        assert marcador not in registros, f"{marcador} vazou nos logs"
    eventos = {r.getMessage() for r in caplog.records}
    assert {"api.requisicao", "api.erro_interno", "analise.concluida"} <= eventos
    interno = next(r for r in caplog.records if r.getMessage() == "api.erro_interno")
    assert interno.__dict__["tipo"] == "RuntimeError"


async def test_seed_idempotente(cliente: httpx.AsyncClient, recursos: Recursos) -> None:
    primeiro = await semear(recursos.settings, recursos.fabrica, recursos.redis)
    segundo = await semear(recursos.settings, recursos.fabrica, recursos.redis)
    assert primeiro.notas == segundo.notas
    assert segundo.notas["historico_v1"] < segundo.notas["historico_v2"]  # type: ignore[operator]
    csrf = (await cliente.get("/auth/csrf")).json()["csrf"]
    r = await cliente.post(
        "/auth/login", json={"email": EMAIL, "senha": SENHA}, headers={"X-CSRF-Token": csrf}
    )
    assert r.status_code == 200
    historico = (await cliente.get("/analises")).json()["itens"]
    assert len(historico) == 4  # b02, i05 e as duas versões (o recrutador fica no processo)
    comparacao = (
        await cliente.get(
            f"/curriculos/{segundo.curriculo_historico}/comparacao",
            params={"vaga": str(segundo.vaga_historico)},
        )
    ).json()
    assert comparacao["frase"].startswith("A nota subiu de")
    processos = (await cliente.get("/processos")).json()
    assert len(processos) == 1 and processos[0]["candidatos"] == 4
    ranking = (await cliente.get(f"/processos/{processos[0]['id']}")).json()["ranking"]
    assert sum(1 for c in ranking if c["decisao"]) == 1
    # O SSE de uma análise do seed fecha com o final (o stream existe ou o banco responde).
    eventos = await cliente.get(f"/analises/{historico[0]['id']}/eventos")
    assert "event: final" in eventos.text
