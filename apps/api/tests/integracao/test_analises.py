"""Envio, erros em problem+json, limites, teto diário, SSE (reconexão, heartbeat, tempo real),
paginação por cursor, provedor falso e relatório em PDF."""

from __future__ import annotations

import asyncio
import io
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
import pdfplumber
from apoio import (
    bytes_do_caso,
    cadastrar,
    caso,
    enviar_texto,
    esperar_status,
    ler_sse,
    provedor_falso,
    rodar_worker,
    servidor_http,
)
from fastapi import FastAPI
from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from sqlalchemy import select

from curriculo_api.api.dependencias import Recursos
from curriculo_api.config import Settings
from curriculo_api.db.modelos import UsoDiario
from curriculo_api.ia.modelos import (
    CurriculoExtraido,
    EventoFeedback,
    TabelaDaNota,
    TextoAnonimizado,
    VagaExtraida,
)
from curriculo_api.ia.orcamento import Orcamento
from curriculo_api.ia.regras import ProvedorRegras
from curriculo_api.main import criar_app

VAGA = caso("b02-backend-pleno-node", "vaga.md")


def _pdf_escaneado() -> bytes:
    """Um PDF só com um desenho (sem texto selecionável), como um escaneado."""
    saida = io.BytesIO()
    c = canvas.Canvas(saida, pagesize=A4)
    imagem = Image.new("RGB", (400, 560), (230, 230, 230))
    c.drawInlineImage(imagem, 20, 20, width=555, height=800)
    c.showPage()
    c.save()
    return saida.getvalue()


async def test_erros_de_envio_em_problem_json(cliente: httpx.AsyncClient) -> None:
    pessoa = await cadastrar(cliente)

    async def enviar(**kw: Any) -> httpx.Response:
        r = await pessoa.post("/analises", **kw)
        assert r.headers["content-type"].startswith("application/problem+json"), r.text
        return r

    r = await enviar(
        files={"arquivo": ("cv.pdf", _pdf_escaneado(), "application/pdf")},
        data={"vaga_texto": VAGA},
    )
    assert r.status_code == 422 and r.json()["codigo"] == "sem_texto"
    assert "OCR" in r.json()["detail"]
    r = await enviar(
        files={"arquivo": ("cv.pdf", b"isto nao e um pdf" * 10, "application/pdf")},
        data={"vaga_texto": VAGA},
    )
    assert r.status_code == 422 and r.json()["codigo"] == "tipo_nao_suportado"
    pdf = bytes_do_caso("b14-java-para-front-end", "curriculo.pdf")
    r = await enviar(
        files={"arquivo": ("cv.docx", pdf, "application/pdf")}, data={"vaga_texto": VAGA}
    )
    assert r.json()["codigo"] == "extensao_nao_confere"
    r = await enviar(
        files={"arquivo": ("cv.pdf", b"%PDF-" + b"0" * (6 * 1024 * 1024), "application/pdf")},
        data={"vaga_texto": VAGA},
    )
    assert r.status_code == 413 and r.json()["codigo"] == "arquivo_grande"
    r = await enviar(
        data={
            "texto": caso("b02-backend-pleno-node", "curriculo.md"),
            "vaga_texto": "Venha trabalhar conosco! Ótimo ambiente.",
        }
    )
    assert r.status_code == 422 and r.json()["codigo"] == "vaga_sem_requisitos"
    r = await enviar(data={"vaga_texto": VAGA})
    assert r.status_code == 422 and r.json()["codigo"] == "curriculo_ausente"
    r = await enviar(data={"texto": "Python e SQL"})
    assert r.json()["codigo"] == "vaga_ausente"
    # Nada foi gravado com os envios recusados.
    assert (await pessoa.get("/analises")).json()["itens"] == []


async def test_limite_de_analises_por_usuario(
    fazer_settings: Callable[..., Settings], recursos: Recursos
) -> None:
    s = fazer_settings(limite_analises_por_usuario=2)
    app = criar_app(s, replace(recursos, settings=s))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://teste"
    ) as c:
        pessoa = await cadastrar(c)
        for _ in range(2):
            assert (await enviar_texto(pessoa, "b02-backend-pleno-node")).status_code == 202
        r = await enviar_texto(pessoa, "b02-backend-pleno-node")
        assert r.status_code == 429 and r.json()["codigo"] == "limite_de_taxa"
        assert int(r.headers["retry-after"]) > 0


async def test_teto_de_custo_diario(cliente: httpx.AsyncClient, recursos: Recursos) -> None:
    pessoa = await cadastrar(cliente)
    async with rodar_worker(recursos):
        criada = (await enviar_texto(pessoa, "b02-backend-pleno-node")).json()
        await esperar_status(recursos, criada["id"])
    hoje = datetime.now(UTC).date()
    async with recursos.fabrica() as db:
        uso = await db.get(UsoDiario, (uuid.UUID(pessoa.id), hoje))
        assert uso is not None and uso.analises == 1 and uso.custo_usd == 0  # regras: custo 0
        uso.custo_usd = Decimal("5.000001")  # simula um dia de provedor pago no teto (US$ 5)
        await db.commit()
    r = await enviar_texto(pessoa, "b02-backend-pleno-node")
    assert r.status_code == 429 and r.json()["codigo"] == "teto_custo_diario"
    assert int(r.headers["retry-after"]) <= 86400
    r = await pessoa.post("/processos", json={"vaga_texto": VAGA, "declaro_base_legal": True})
    processo = r.json()["id"]
    r = await pessoa.post(
        f"/processos/{processo}/candidatos", data={"texto": "Python e SQL há anos"}
    )
    assert r.status_code == 429 and r.json()["codigo"] == "teto_custo_diario"


async def test_paginacao_por_cursor(cliente: httpx.AsyncClient) -> None:
    pessoa = await cadastrar(cliente)
    ids = [(await enviar_texto(pessoa, "b02-backend-pleno-node")).json()["id"] for _ in range(5)]
    vistos: list[str] = []
    cursor = None
    paginas = 0
    while True:
        params: dict[str, Any] = {"limite": 2}
        if cursor:
            params["cursor"] = cursor
        pagina = (await pessoa.get("/analises", params=params)).json()
        vistos += [i["id"] for i in pagina["itens"]]
        paginas += 1
        cursor = pagina["proximo_cursor"]
        if cursor is None:
            break
    assert paginas == 3
    assert vistos == list(reversed(ids))  # mais recente primeiro, sem repetir nem pular
    r = await pessoa.get("/analises", params={"cursor": "lixo"})
    assert r.status_code == 400 and r.json()["codigo"] == "cursor_invalido"


class ProvedorLento(ProvedorRegras):
    """Segura o feedback até o teste liberar: dá para ler eventos com a análise em andamento."""

    def __init__(self) -> None:
        super().__init__()
        self.liberar = asyncio.Event()

    async def escrever_feedback(
        self,
        tabela: TabelaDaNota,
        curriculo: CurriculoExtraido,
        vaga: VagaExtraida,
        texto: TextoAnonimizado,
        *,
        orcamento: Orcamento | None = None,
    ) -> AsyncIterator[EventoFeedback]:
        await self.liberar.wait()
        async for evento in super().escrever_feedback(tabela, curriculo, vaga, texto):
            yield evento
            await asyncio.sleep(0.01)


async def test_sse_em_tempo_real_e_reconexao_com_last_event_id(
    app: FastAPI, recursos: Recursos
) -> None:
    lento = ProvedorLento()
    async with (
        servidor_http(app) as base,
        httpx.AsyncClient(base_url=base, timeout=30) as http,
        rodar_worker(recursos, lento),
    ):
        pessoa = await cadastrar(http)
        criada = (await enviar_texto(pessoa, "b01-frontend-senior")).json()
        url = criada["eventos_url"]
        # Primeira conexão: lê 3 eventos com a análise ainda parada antes do feedback e cai.
        async with http.stream("GET", url) as fluxo:
            primeiros = await ler_sse(fluxo, ate=3)
        assert [e.id for e in primeiros] == [1, 2, 3]
        assert (await pessoa.get(criada["resultado_url"])).json()["status"] == "processando"
        # Reconecta com Last-Event-ID: continua do 4, sem repetir.
        lento.liberar.set()
        async with http.stream("GET", url, headers={"Last-Event-ID": "3"}) as fluxo:
            resto = await ler_sse(fluxo)
        assert resto[0].id == 4
        ids = [e.id for e in primeiros + resto]
        assert ids == list(range(1, len(ids) + 1))
        assert resto[-1].tipo == "final"
        assert sum(1 for e in resto if e.tipo == "texto") >= 2
        # Depois do fim, `?desde=` também funciona e o fluxo fecha logo.
        async with http.stream("GET", url, params={"desde": len(ids) - 1}) as fluxo:
            ultimo = await ler_sse(fluxo)
        assert [e.tipo for e in ultimo] == ["final"]


async def test_sse_heartbeat_enquanto_espera_a_fila(
    fazer_settings: Callable[..., Settings], recursos: Recursos
) -> None:
    s = fazer_settings(sse_heartbeat_s=0.2)
    app = criar_app(s, replace(recursos, settings=s))
    async with servidor_http(app) as base, httpx.AsyncClient(base_url=base, timeout=30) as http:
        pessoa = await cadastrar(http)
        criada = (await enviar_texto(pessoa, "b02-backend-pleno-node")).json()  # sem worker
        comentarios: list[str] = []

        async def ler() -> None:
            async with http.stream("GET", criada["eventos_url"]) as fluxo:
                await ler_sse(fluxo, comentarios=comentarios)

        tarefa = asyncio.create_task(ler())
        for _ in range(100):
            if len(comentarios) >= 2:
                break
            await asyncio.sleep(0.05)
        tarefa.cancel()
        assert comentarios.count(": ping") >= 2
        # Com o worker no ar, o mesmo fluxo termina com o final.
        async with rodar_worker(recursos), http.stream("GET", criada["eventos_url"]) as fluxo:
            eventos = await ler_sse(fluxo)
        assert eventos[-1].tipo == "final"


async def test_sse_de_analise_com_erro_e_sem_stream(
    cliente: httpx.AsyncClient, recursos: Recursos
) -> None:
    pessoa = await cadastrar(cliente)
    async with rodar_worker(recursos, provedor_falso()):
        # O falso não tem gravação para este texto: a análise termina em erro, com mensagem.
        criada = (
            await pessoa.post(
                "/analises", data={"texto": "Python, SQL e Docker em produção.", "vaga_texto": VAGA}
            )
        ).json()
        assert await esperar_status(recursos, criada["id"]) == "erro"
    r = await pessoa.get(criada["eventos_url"])  # termina sozinho no evento de erro
    assert "event: erro" in r.text and "gravacao_ausente" in r.text
    detalhe = (await pessoa.get(criada["resultado_url"])).json()
    assert detalhe["erro"]["codigo"] == "gravacao_ausente"
    # Sem o stream (expirou), o SSE responde pelo estado do banco.
    await recursos.redis.delete(f"{recursos.settings.redis_prefixo}:analise:{criada['id']}:eventos")
    r = await pessoa.get(criada["eventos_url"])
    assert "event: erro" in r.text


async def test_provedor_falso_resultado_rico_com_avisos(
    cliente: httpx.AsyncClient, recursos: Recursos
) -> None:
    pessoa = await cadastrar(cliente)
    async with rodar_worker(recursos, provedor_falso()):
        criada = (
            await pessoa.post(
                "/analises",
                files={
                    "arquivo": (
                        "x.pdf",
                        bytes_do_caso("i05-oculta-en-instrucao", "curriculo.pdf"),
                        "application/pdf",
                    )
                },
                data={"vaga_texto": caso("i05-oculta-en-instrucao", "vaga.md")},
            )
        ).json()
        assert await esperar_status(recursos, criada["id"]) == "concluida"
    r = (await pessoa.get(criada["resultado_url"])).json()
    tipos = {a["tipo"] for a in r["avisos"]}
    assert {"texto_oculto", "instrucao_para_ia"} <= tipos
    assert r["reescritas"] and r["lacunas"] and r["o_que_aprender"]
    assert r["aviso_modo"].startswith("Modo demonstração")
    assert any(not p["no_curriculo"] for p in r["palavras_chave"]) or r["palavras_chave"]

    pdf = await pessoa.get(f"/analises/{criada['id']}/relatorio.pdf")
    assert pdf.headers["content-type"] == "application/pdf"
    with pdfplumber.open(io.BytesIO(pdf.content)) as documento:
        texto = "\n".join(p.extract_text() or "" for p in documento.pages)
    assert f"Nota: {r['nota']} de 100" in texto
    for item in r["ignorado"]:
        assert item["mascarado"] not in texto
    assert "@" not in texto and "[NOME]" not in texto


async def test_uso_diario_soma_por_analise(cliente: httpx.AsyncClient, recursos: Recursos) -> None:
    pessoa = await cadastrar(cliente)
    async with rodar_worker(recursos):
        for _ in range(2):
            criada = (await enviar_texto(pessoa, "b02-backend-pleno-node")).json()
            await esperar_status(recursos, criada["id"])
    async with recursos.fabrica() as db:
        uso = (
            await db.execute(select(UsoDiario).where(UsoDiario.usuario_id == uuid.UUID(pessoa.id)))
        ).scalar_one()
    assert uso.analises == 2
