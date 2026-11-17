"""Ponta a ponta com servidor HTTP, fila e worker reais: cadastro → upload → fila → SSE →
resultado → nova versão → comparação → recrutador → decisão → apagar os dados."""

from __future__ import annotations

import uuid
from pathlib import Path

import httpx
from apoio import (
    Pessoa,
    analise_do_candidato,
    bytes_do_caso,
    cadastrar,
    caso,
    esperar_status,
    ler_sse,
    rodar_worker,
    servidor_http,
)
from fastapi import FastAPI
from sqlalchemy import func, select, text

from curriculo_api.api.dependencias import Recursos
from curriculo_api.db.modelos import DecisaoHumana, VetorTaxonomia
from curriculo_api.seed import versao_reduzida

# A vaga do b01 com um diferencial fora da taxonomia, que vai para o vizinho mais próximo no
# pgvector.
VAGA = caso("b01-frontend-senior", "vaga.md").rstrip() + "\n- Arquitetura de micro-frontends\n"
ETAPAS = [
    "leitura",
    "anonimizacao",
    "extracao",
    "ancoragem",
    "correspondencia",
    "nota",
    "feedback",
]


async def test_fluxo_completo(app: FastAPI, recursos: Recursos, pasta_arquivos: Path) -> None:
    async with (
        servidor_http(app) as base,
        httpx.AsyncClient(base_url=base, timeout=30) as http,
        rodar_worker(recursos),
    ):
        pessoa = await cadastrar(http)
        eu = (await pessoa.get("/eu")).json()
        assert eu["email"] == pessoa.email
        assert eu["consentimentos"][0]["tipo"] == "lgpd_titular"

        # 1. Upload de um PDF real (b14: PDF gerado com reportlab) contra uma vaga colada.
        resposta = await pessoa.post(
            "/analises",
            files={
                "arquivo": (
                    "meu-cv.pdf",
                    bytes_do_caso("b14-java-para-front-end", "curriculo.pdf"),
                    "application/pdf",
                )
            },
            data={"vaga_texto": VAGA},
        )
        assert resposta.status_code == 202, resposta.text
        criada = resposta.json()
        assert criada["status"] == "na_fila"
        assert resposta.headers["content-type"].startswith("application/json")

        # 2. SSE em tempo real até o evento final.
        async with http.stream("GET", criada["eventos_url"]) as fluxo:
            assert fluxo.status_code == 200
            assert fluxo.headers["content-type"].startswith("text/event-stream")
            eventos = await ler_sse(fluxo)
        tipos = [e.tipo for e in eventos]
        assert tipos[-1] == "final"
        assert [e.dados["etapa"] for e in eventos if e.tipo == "etapa"] == ETAPAS
        assert "texto" in tipos
        ids = [e.id for e in eventos]
        assert ids == list(range(1, len(eventos) + 1))  # contínuos, sem buraco

        # 3. Resultado.
        resultado = (await pessoa.get(criada["resultado_url"])).json()
        assert resultado["status"] == "concluida"
        assert resultado["nota"] == eventos[-1].dados["nota"]
        assert resultado["modo_demonstracao"] is True
        assert resultado["aviso_modo"] == "Modo demonstração: análise por regras, sem IA."
        assert resultado["decomposicao"]["texto"].endswith(f"nota {resultado['nota']}")
        assert resultado["requisitos"] and all("status" in r for r in resultado["requisitos"])
        assert any(r["evidencia"] for r in resultado["requisitos"])
        assert resultado["ignorado"], "a anonimização deveria listar o que tirou"
        assert all("•••" in i["mascarado"] or i["tipo"] == "foto" for i in resultado["ignorado"])
        assert "@example.com" not in str(resultado)
        assert resultado["reescritas"] == []  # o modo por regras não reescreve (ADR 0006)
        assert resultado["palavras_chave"]
        # O vizinho mais próximo da taxonomia foi para o pgvector.
        async with recursos.fabrica() as db:
            vetores = (
                await db.execute(select(func.count()).select_from(VetorTaxonomia))
            ).scalar_one()
        assert vetores > 100

        # 4. Duas versões de texto do mesmo currículo contra a mesma vaga: a nota sobe.
        completo = caso("b01-frontend-senior", "curriculo.md")
        vaga = VAGA
        v1 = (
            await pessoa.post(
                "/analises", data={"texto": versao_reduzida(completo), "vaga_texto": vaga}
            )
        ).json()
        await esperar_status(recursos, v1["id"])
        v2 = (
            await pessoa.post(
                "/analises",
                data={
                    "texto": completo,
                    "vaga_id": v1["vaga"]["id"],
                    "curriculo_id": v1["curriculo"]["id"],
                },
            )
        ).json()
        assert v2["curriculo"] == {**v1["curriculo"], "versao": 2}
        assert (
            v2["vaga"]["id"] == v1["vaga"]["id"] == criada["vaga"]["id"]
        )  # mesma vaga, deduplicada
        await esperar_status(recursos, v2["id"])
        comparacao = (
            await pessoa.get(
                f"/curriculos/{v1['curriculo']['id']}/comparacao", params={"vaga": v1["vaga"]["id"]}
            )
        ).json()
        assert comparacao["diferenca"] > 0
        assert comparacao["frase"] == (
            f"A nota subiu de {comparacao['de']['nota']} para {comparacao['para']['nota']}."
        )
        assert comparacao["mudancas"], "algum requisito deveria mudar de status"
        historico = (await pessoa.get("/analises")).json()
        assert {i["id"] for i in historico["itens"]} == {criada["id"], v1["id"], v2["id"]}

        # 5. Recrutador: processo, candidatos, ranking explicado, decisão humana.
        processo = (
            await pessoa.post(
                "/processos",
                json={"vaga_texto": vaga, "declaro_base_legal": True, "titulo": "Front"},
            )
        ).json()
        candidatos = []
        for nome in ("b02-backend-pleno-node", "b01-frontend-senior", "b14-java-para-front-end"):
            r = await pessoa.post(
                f"/processos/{processo['id']}/candidatos",
                data={"texto": caso(nome, "curriculo.md")},
            )
            assert r.status_code == 202, r.text
            candidatos.append(r.json())
        assert [c["rotulo"] for c in candidatos] == ["Candidato A", "Candidato B", "Candidato C"]
        for c in candidatos:
            await esperar_status(recursos, await analise_do_candidato(recursos, c["id"]))
        ranking = (await pessoa.get(f"/processos/{processo['id']}")).json()
        notas = [c["nota"] for c in ranking["ranking"]]
        assert notas == sorted(notas, reverse=True)
        assert ranking["ranking"][0]["rotulo"] == "Candidato B"  # o b01 é o mais aderente
        assert all(c["decisao"] is None for c in ranking["ranking"])
        assert all(c["explicacao"] and c["parcelas"] for c in ranking["ranking"])
        texto_ranking = str(ranking)
        assert "@example.com" not in texto_ranking and "arquivo" not in texto_ranking
        decisao = await pessoa.post(
            f"/processos/{processo['id']}/candidatos/{candidatos[1]['id']}/decisoes",
            json={
                "decisao": "avancar",
                "justificativa": "Experiência com React e Next.js em produção.",
            },
        )
        assert decisao.status_code == 201
        assert decisao.json()["usuario_id"] == pessoa.id
        ranking = (await pessoa.get(f"/processos/{processo['id']}")).json()
        assert ranking["ranking"][0]["decisao"]["decisao"] == "avancar"

        # 6. PDF do relatório.
        pdf = await pessoa.get(f"/analises/{criada['id']}/relatorio.pdf")
        assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")

        # 7. Apagar tudo: banco, disco e Redis ficam sem nada desta pessoa.
        analises = [
            criada["id"],
            v1["id"],
            v2["id"],
            *[await analise_do_candidato(recursos, c["id"]) for c in candidatos],
        ]
        apagado = await pessoa.delete("/eu/dados")
        assert apagado.status_code == 200, apagado.text
        corpo = apagado.json()
        assert corpo["apagado"]["usuarios"] == 1
        assert corpo["apagado"]["analises"] == len(analises)
        assert corpo["arquivos"] == len(analises)
        assert corpo["chaves_redis"] > 0
        await confirmar_nada_sobrou(recursos, pessoa, analises, pasta_arquivos)
        assert (await pessoa.get("/eu")).status_code == 401


async def confirmar_nada_sobrou(
    recursos: Recursos, pessoa: Pessoa, analises: list[str], pasta_arquivos: Path
) -> None:
    async with recursos.fabrica() as db:
        for tabela in (
            "usuarios",
            "sessoes",
            "consentimentos",
            "curriculos",
            "curriculo_versoes",
            "vagas",
            "analises",
            "processos_recrutador",
            "candidatos",
            "decisoes_humanas",
            "uso_diario",
        ):
            coluna = "id" if tabela == "usuarios" else "usuario_id"
            total = (
                await db.execute(
                    text(f"SELECT count(*) FROM {tabela} WHERE {coluna} = :id"),  # noqa: S608
                    {"id": uuid.UUID(pessoa.id)},
                )
            ).scalar_one()
            assert total == 0, f"sobrou algo em {tabela}"
        assert (await db.execute(select(func.count()).select_from(DecisaoHumana))).scalar_one() == 0
    assert not (pasta_arquivos / pessoa.id).exists()
    assert not any(pasta_arquivos.rglob("*.*"))
    restantes = [c async for c in recursos.redis.scan_iter(match="*", count=1000)]
    texto = " ".join(c.decode() if isinstance(c, bytes) else str(c) for c in restantes)
    for analise_id in analises:
        assert analise_id not in texto, "sobrou chave de análise no Redis"
    assert pessoa.id not in texto, "sobrou chave do usuário no Redis"
