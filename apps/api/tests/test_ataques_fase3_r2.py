"""Regressão dos ataques do Validador às regras da rodada 1 (validador-fase3/r2/r2_ataques.py):
negação, aspiração e flexão falsa na ancoragem; invenção só com vocabulário comum no feedback; e o
detector independente da métrica 8."""

from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from curriculo_api.analise.correspondencia import Limiares
from curriculo_api.analise.embeddings import Comparador, EmbutidorFalso
from curriculo_api.analise.feedback import filtrar_feedback
from curriculo_api.analise.niveis import nivel_de
from curriculo_api.analise.pipeline import Analisador, EntradaCurriculo
from curriculo_api.ancoragem import termo_no_texto
from curriculo_api.evals.harness import reescrita_inventa
from curriculo_api.evals.pipeline import entrada_do_caso
from curriculo_api.ia.falso import ProvedorFalso
from curriculo_api.ia.modelos import (
    Competencia,
    CurriculoExtraido,
    DataParcial,
    Experiencia,
    FeedbackIA,
    Idioma,
    LinhaRequisito,
    NivelProficiencia,
    ReescritaIA,
    Requisito,
    TabelaDaNota,
    VagaExtraida,
)
from curriculo_api.taxonomia import Taxonomia
from test_ataques_fase3 import _ProvedorProgramado

REF = date(2026, 11, 1)

# --- (a) ancoragem ----------------------------------------------------------------------------

CV_A = """Analista de Suporte — Empresa Fictícia Ômega — mar/2021 – atual
Atendo chamados e documento processos.
Nunca usei Kubernetes, mas tenho curiosidade.
Sem experiência em AWS até o momento.
Quero aprender Terraform no próximo ano.
Não tenho Python no dia a dia.
Fiz terraplanagem de dados legados e excelente atendimento ao cliente.
Trabalhei no ângulo de projeção de vendas da gestante.
Trabalho com powerpoint e com BI de marketing.
Habilidades: comunicação, organização
Inglês (cursando o nível avançado)
"""
REQS_A: list[tuple[str, NivelProficiencia | None]] = [
    ("Kubernetes", None),
    ("AWS", None),
    ("Terraform", None),
    ("Python", None),
    ("Excel", None),
    ("Angular", None),
    ("Gestão de projetos", None),
    ("Power BI", None),
    ("Inglês", "avancado"),
]
COMPS_A = [
    ("Kubernetes", "Nunca usei Kubernetes, mas tenho curiosidade."),
    ("AWS", "Sem experiência em AWS até o momento."),
    ("Terraform", "Quero aprender Terraform no próximo ano."),
    ("Python", "Não tenho Python no dia a dia."),
    ("Terraform", "Fiz terraplanagem de dados legados"),
    ("Excel", "excelente atendimento ao cliente"),
    ("Angular", "Trabalhei no ângulo de projeção"),
    ("Gestão de projetos", "projeção de vendas da gestante"),
    ("Power BI", "com powerpoint e com BI de marketing"),
]


def _analisar_a(taxonomia: Taxonomia, competencias: list[tuple[str, str]]) -> Any:
    vaga = VagaExtraida(
        titulo="Vaga",
        idioma="pt",
        requisitos=tuple(
            Requisito(descricao=c, tipo="obrigatorio", competencia=c, nivel=n) for c, n in REQS_A
        ),
    )
    exp = Experiencia(
        cargo="Analista de Suporte",
        empresa="Empresa Fictícia Ômega",
        inicio=DataParcial(ano=2021, mes=3),
        trecho="Analista de Suporte — Empresa Fictícia Ômega — mar/2021 – atual",
    )
    cv = CurriculoExtraido(
        experiencias=(exp,),
        competencias=tuple(
            Competencia(nome=n, trecho=t, experiencias=(0,)) for n, t in competencias
        ),
        idiomas=(
            Idioma(idioma="Inglês", nivel="avançado", trecho="Inglês (cursando o nível avançado)"),
        ),
    )
    analisador = Analisador(
        _ProvedorProgramado(cv, vaga),
        taxonomia,
        Comparador(taxonomia, EmbutidorFalso()),
        Limiares(),
        Decimal(1),
    )
    entrada = EntradaCurriculo(
        texto_vaga="Vaga\n" + "\n".join(f"- {c}" for c, _ in REQS_A),
        data_referencia=REF,
        texto_curriculo=CV_A,
    )
    return asyncio.run(analisador.analisar(entrada))


def test_negacao_aspiracao_e_flexao_falsa_nao_comprovam(taxonomia: Taxonomia) -> None:
    atacado = _analisar_a(taxonomia, COMPS_A)  # antes da rodada 3: nota 100
    honesto = _analisar_a(taxonomia, [])  # nenhuma competência extraída
    assert atacado.tabela.nota == honesto.tabela.nota
    assert [linha.status for linha in atacado.tabela.linhas] == [
        linha.status for linha in honesto.tabela.linhas
    ]
    status = {linha.competencia_pedida: linha.status for linha in atacado.tabela.linhas}
    assert all(s == "nao_atende" for c, s in status.items() if c != "Inglês")
    assert status["Inglês"] == "parcial"  # cursando o avançado: no máximo intermediário
    negadas = {d.trecho for d in atacado.ancoragem.descartados_por_negacao}
    assert negadas == {t for _, t in COMPS_A[:4]}
    flexoes = {d.trecho for d in atacado.ancoragem.descartados}
    assert flexoes == {t for _, t in COMPS_A[4:]}
    assert {d.motivo for d in atacado.ancoragem.descartados} == {"termo_fora_do_trecho"}


@pytest.mark.parametrize(
    ("termo", "texto", "esperado"),
    [
        ("Contabilidade", "atualizei contatos e contagem", False),
        ("Marketing", "market share do cliente", False),
        ("React", "reactive streams", False),
        ("Excel", "excelente atendimento", False),
        ("Java", "uso JavaScript", False),
        ("Gestão de projetos", "projeção de vendas da gestante", False),
        ("Power BI", "powerpoint e com BI", False),
        ("Conciliação bancária", "pelas conciliações bancárias", True),
        ("Gestão de projetos", "gestão dos projetos da obra", True),
        ("Docker", "docker-compose dos serviços", True),
    ],
)
def test_termo_por_palavra_inteira(termo: str, texto: str, esperado: bool) -> None:
    assert termo_no_texto(termo, texto) is esperado


@pytest.mark.parametrize(
    ("texto", "nivel"),
    [
        ("Inglês (cursando o nível avançado)", "intermediario"),
        ("Inglês básico (cursando o avançado)", "basico"),
        ("Inglês avançado, Espanhol básico", "basico"),
        ("Inglês avançado", "avancado"),
    ],
)
def test_nivel_em_curso_nao_comprova(texto: str, nivel: str) -> None:
    assert nivel_de(texto) == nivel


# --- (b) e (c) feedback e métrica 8 -----------------------------------------------------------

CV_B = """Analista de Dados — Empresa Fictícia Sigma — jan/2020 – atual
Desenvolvo relatórios em Excel básico e consultas SQL para a equipe financeira.
Organizo planilhas de custos e atendo demandas da área comercial.
Inglês básico. Excel avançado em fórmulas.
"""
VAGA_B = "Requisitos: SQL, Excel, Inglês fluente, Liderança de equipes, Gestão de projetos, Python"
ANTES_B = "Desenvolvo relatórios em Excel básico e consultas SQL para a equipe financeira."
INVENTADAS_B = {
    "liderança": "Liderei a equipe financeira e gerenciei projetos com relatórios em Excel e "
    "consultas SQL.",
    "gestão de projetos": "Coordenei projetos e planejei entregas da equipe com Excel e SQL.",
    "nível inflado": "Desenvolvo relatórios em Excel avançado e consultas SQL para a equipe "
    "financeira.",
    "inglês fluente": "Desenvolvo relatórios em Excel e consultas SQL em inglês fluente para a "
    "equipe financeira.",
    "python minúsculo": "Desenvolvo relatórios em Excel e consultas SQL e scripts python para a "
    "equipe financeira.",
    "automação": "Automatizei processos da equipe financeira com relatórios em Excel e consultas "
    "SQL.",
    "resultado vago": "Reduzi prazos e aumentei a qualidade das entregas da equipe financeira com "
    "Excel e SQL.",
    "espanhol": "Desenvolvo relatórios en Excel con aprendizaje automático para la equipe "
    "financeira.",
    "dez anos": "Desenvolvo há dez anos relatórios em Excel e consultas SQL para a equipe "
    "financeira.",
    "migração": "Migrei os relatórios em Excel e consultas SQL da equipe financeira para sistemas "
    "novos.",
    "lidero": "Desenvolvo relatórios em Excel e consultas SQL e lidero a equipe financeira.",
    "power bi": "Desenvolvo dashboards em power bi e consultas SQL para a equipe financeira.",
    "kafka minúsculo": "Desenvolvo relatórios em Excel e consultas SQL com kafka para a equipe "
    "financeira.",
    "Kafka no início": "Kafka e SQL alimentam os relatórios em Excel da equipe financeira.",
    "Snowflake após ponto": "Desenvolvo relatórios em Excel. Snowflake e SQL para a equipe "
    "financeira.",
}
LEGITIMAS_B = {
    "reordenar": "Para a equipe financeira, desenvolvo consultas SQL e relatórios em Excel básico.",
    "juntar frases": "Desenvolvo relatórios em Excel básico e consultas SQL para a equipe "
    "financeira e atendo demandas da área comercial.",
}


def _cv_b() -> CurriculoExtraido:
    return CurriculoExtraido(
        competencias=(
            Competencia(nome="SQL", trecho="consultas SQL para a equipe"),
            Competencia(nome="Excel", trecho="relatórios em Excel básico"),
        ),
        idiomas=(Idioma(idioma="Inglês", nivel="básico", trecho="Inglês básico."),),
    )


def _tabela_b() -> TabelaDaNota:
    return TabelaDaNota(
        nota=40,
        linhas=tuple(
            LinhaRequisito(
                descricao=c,
                tipo="obrigatorio",
                competencia_pedida=c,
                status="nao_atende",
                valor="0",
                regra="sem_evidencia",
                motivo="x",
            )
            for c in ("Liderança de equipes", "Gestão de projetos", "Python")
        ),
    )


def test_filtro_nao_entrega_invencao_so_com_vocabulario_comum(taxonomia: Taxonomia) -> None:
    todas = {**INVENTADAS_B, **LEGITIMAS_B}
    bruto = FeedbackIA(
        resumo="ok", reescritas=tuple(ReescritaIA(antes=ANTES_B, depois=d) for d in todas.values())
    )
    fb = filtrar_feedback(bruto, _tabela_b(), _cv_b(), CV_B, VAGA_B, taxonomia)
    entregues = {r.depois for r in fb.reescritas}
    assert not entregues & set(INVENTADAS_B.values())  # antes da rodada 3: 7 entregues
    assert entregues == set(LEGITIMAS_B.values())


@pytest.mark.parametrize("nome", sorted(INVENTADAS_B))
def test_detector_da_metrica_8_pega_cada_invencao(taxonomia: Taxonomia, nome: str) -> None:
    comprovadas = frozenset({"SQL", "Excel", "Inglês"})
    assert reescrita_inventa(INVENTADAS_B[nome], CV_B, comprovadas, taxonomia, ANTES_B)


@pytest.mark.parametrize("nome", sorted(LEGITIMAS_B))
def test_detector_da_metrica_8_aceita_as_legitimas(taxonomia: Taxonomia, nome: str) -> None:
    comprovadas = frozenset({"SQL", "Excel", "Inglês"})
    assert not reescrita_inventa(LEGITIMAS_B[nome], CV_B, comprovadas, taxonomia, ANTES_B)


# --- (4) i02: o falso cita o trecho injetado ---------------------------------------------------


async def test_i02_cita_a_injecao_e_a_ancoragem_descarta(
    raiz: Path, dataset: Any, taxonomia: Taxonomia
) -> None:
    analisador = Analisador(
        ProvedorFalso(raiz / "evals" / "gravacoes"),
        taxonomia,
        Comparador(taxonomia, EmbutidorFalso()),
        Limiares(),
        Decimal(1),
    )
    notas = {}
    for caso_id in ("i02-visivel-en-system", "b02-backend-pleno-node"):
        e = entrada_do_caso(dataset.por_id()[caso_id], dataset.config.data_referencia)
        r = await analisador.analisar(
            EntradaCurriculo(
                texto_vaga=e.texto_vaga,
                data_referencia=e.data_referencia,
                texto_curriculo=e.texto_curriculo,
            )
        )
        notas[caso_id] = r.tabela.nota
        if caso_id.startswith("i02"):
            nomes = {c.nome for c in r.curriculo_bruto.competencias if "SYSTEM" in c.trecho}
            assert nomes == {"AWS", "TypeScript"}
            assert len(r.ancoragem.descartados_por_injecao) == 2
    assert notas["i02-visivel-en-system"] == notas["b02-backend-pleno-node"]
