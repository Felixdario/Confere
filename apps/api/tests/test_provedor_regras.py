"""O provedor por regras (ADR 0006): extração determinística, sempre ancorada, e feedback por
modelos de texto, sem reescritas. E as peças sem rede da fase 4 (OpenAPI em dia, SSE, rótulos,
senhas)."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from curriculo_api.analise.embeddings import EmbutidorFalso
from curriculo_api.analise.fabrica import criar_analisador
from curriculo_api.analise.pipeline import EntradaCurriculo
from curriculo_api.ancoragem import ancorar
from curriculo_api.api.rotas_recrutador import rotulo
from curriculo_api.config import Settings
from curriculo_api.evals.dataset import Dataset
from curriculo_api.eventos import Evento
from curriculo_api.ia.modelos import TextoAnonimizado
from curriculo_api.ia.provedor import ProvedorIA
from curriculo_api.ia.regras import AVISO_MODO_DEMO, ProvedorRegras
from curriculo_api.ingestao import ingerir_curriculo
from curriculo_api.openapi import caminho, texto
from curriculo_api.seguranca import hash_senha, senha_confere
from curriculo_api.taxonomia import Taxonomia

CURRICULO = """# Fulana de Tal

fulana@example.com · (00) 90000-0000

## Experiência

Desenvolvedora Back-end — Empresa Inventada — mar/2021 – atual
- Construí APIs REST em Python com Django e PostgreSQL.
- Nunca usei Kubernetes, quero aprender.

Analista de Sistemas — Outra Empresa — 2018 – 2021
- Rotinas em SQL e relatórios no Excel.

## Formação

Bacharelado em Ciência da Computação — Universidade Fictícia — 2017

## Idiomas

Inglês avançado

## Habilidades

Python, Django, Docker, Git
"""

VAGA = """# Pessoa Desenvolvedora Python Pleno

## Requisitos

- Mínimo de 3 anos de experiência com desenvolvimento
- Python
- Django
- Kubernetes
- Inglês avançado

## Diferenciais

- Docker
- Facilitação de guildas de engenharia
"""


def _anonimizado(texto: str) -> TextoAnonimizado:
    return ingerir_curriculo(texto=texto).texto_para_ia


def test_e_um_provedor_ia_sem_custo() -> None:
    provedor = ProvedorRegras()
    assert isinstance(provedor, ProvedorIA)
    assert provedor.nome == "regras"


def test_extrai_curriculo_e_tudo_passa_na_ancoragem(taxonomia: Taxonomia) -> None:
    texto = _anonimizado(CURRICULO)
    extraido = ProvedorRegras(taxonomia).extrair_curriculo_sincrono(texto)
    assert [(e.cargo, e.empresa) for e in extraido.experiencias] == [
        ("Desenvolvedora Back-end", "Empresa Inventada"),
        ("Analista de Sistemas", "Outra Empresa"),
    ]
    assert extraido.experiencias[0].fim is None and extraido.experiencias[0].inicio.mes == 3
    nomes = {taxonomia.chave_de(c.nome) for c in extraido.competencias}
    assert {"Python", "Django", "Docker", "SQL"} <= nomes
    assert [f.curso for f in extraido.formacao] == ["Bacharelado em Ciência da Computação"]
    assert "Ciência da computação" not in nomes  # o nome da graduação não vira competência
    assert [i.idioma for i in extraido.idiomas] == ["Inglês"]
    ancorado = ancorar(extraido, texto, taxonomia)
    # Toda linha citada existe no texto; o "Nunca usei Kubernetes" cai pela negação.
    assert not ancorado.descartados
    assert "Kubernetes" not in {taxonomia.chave_de(c.nome) for c in ancorado.mantido.competencias}
    python = next(c for c in ancorado.mantido.competencias if c.nome == "Python")
    assert python.experiencias == (0,)


def test_extrai_vaga(taxonomia: Taxonomia) -> None:
    vaga = ProvedorRegras(taxonomia).extrair_vaga_sincrono(VAGA)
    assert vaga.titulo == "Pessoa Desenvolvedora Python Pleno"
    assert vaga.nivel == "pleno" and vaga.anos_minimos == 3 and vaga.idioma == "pt"
    por_tipo = {(r.tipo, r.competencia) for r in vaga.requisitos}
    assert ("obrigatorio", "Python") in por_tipo and ("desejavel", "Docker") in por_tipo
    ingles = next(r for r in vaga.requisitos if taxonomia.chave_de(r.competencia) == "Inglês")
    assert ingles.nivel == "avancado"
    livre = next(r for r in vaga.requisitos if "guildas" in r.descricao)
    assert taxonomia.canonica_de(livre.competencia) is None  # vai para o embedding
    assert not any("3 anos" in r.descricao for r in vaga.requisitos)


def test_vaga_sem_titulos_e_vaga_sem_requisitos() -> None:
    provedor = ProvedorRegras()
    assert [
        r.competencia for r in provedor.extrair_vaga_sincrono("- Python\n- SQL").requisitos
    ] == [
        "Python",
        "SQL",
    ]
    assert (
        provedor.extrair_vaga_sincrono("Venha trabalhar conosco! Ótimo ambiente.").requisitos == ()
    )


async def test_analise_completa_por_regras_sem_reescritas(raiz: Path, taxonomia: Taxonomia) -> None:
    settings = Settings(_env_file=None)
    analisador = criar_analisador(
        ProvedorRegras(taxonomia), settings, taxonomia=taxonomia, embutidor=EmbutidorFalso()
    )
    eventos = [
        e
        async for e in analisador.eventos(
            EntradaCurriculo(
                texto_vaga=VAGA, texto_curriculo=CURRICULO, data_referencia=date(2026, 11, 1)
            )
        )
    ]
    final = eventos[-1].resultado
    assert final is not None
    assert final.feedback.reescritas == () and final.feedback.reescritas_descartadas == ()
    assert final.custo_usd == Decimal(0)
    assert "sem IA" in final.feedback.resumo
    lacunas = {linha.requisito for linha in final.feedback.lacunas}
    assert "Kubernetes" in lacunas
    assert any(a.competencia == "Kubernetes" for a in final.feedback.o_que_aprender)
    assert sum(1 for e in eventos if e.tipo == "texto") >= 2
    assert AVISO_MODO_DEMO.startswith("Modo demonstração")


async def test_deterministico_e_igual_nos_contrafactuais(
    dataset: Dataset, taxonomia: Taxonomia
) -> None:
    provedor = ProvedorRegras(taxonomia)
    casos = dataset.por_id()
    base = ingerir_curriculo(texto=casos["b03-dados-pleno-vaga-en"].curriculo).texto_para_ia
    for variante in ("c01-dados-homem-58", "c02-dados-mulher-27", "c08-dados-nome-vietnamita"):
        texto = ingerir_curriculo(texto=casos[variante].curriculo).texto_para_ia
        assert provedor.extrair_curriculo_sincrono(texto) == provedor.extrair_curriculo_sincrono(
            base
        )


def test_openapi_em_dia() -> None:
    """`make openapi` regrava; este teste falha se a API mudou e o arquivo não."""
    assert caminho().read_text("utf-8") == texto(), "rode `make openapi`"
    documento = json.loads(texto())
    assert documento["info"]["title"] == "Analisador de currículos"
    assert {t["name"] for t in documento["tags"]} >= {
        "auth",
        "análises",
        "recrutador",
        "privacidade",
    }
    assert "Problema" in documento["components"]["schemas"]


def test_evento_sse_e_rotulos_e_senha() -> None:
    assert Evento(3, "etapa", {"etapa": "leitura"}).sse() == (
        'id: 3\nevent: etapa\ndata: {"etapa": "leitura"}\n\n'
    )
    assert [rotulo(i) for i in (0, 1, 19, 25, 26)] == [
        "Candidato A",
        "Candidato B",
        "Candidato T",
        "Candidato Z",
        "Candidato AA",
    ]
    h = hash_senha("segredo comprido")
    assert h.startswith("$argon2id$")
    assert senha_confere("segredo comprido", h)
    assert not senha_confere("outra", h) and not senha_confere("x", None)


VAGA_FORMATOS = (
    "Dev Python Pleno\n\n{o}\n- Python\n- FastAPI\n- 1 ano de experiência com análise de dados\n"
    "\n{d}\n- Redis\n- Kubernetes\n"
)


@pytest.mark.parametrize(
    ("obrigatorios", "desejaveis"),
    [
        ("Requisitos", "Diferenciais"),
        ("Requisitos", "Diferenciais:"),
        ("**Requisitos**", "**Desejáveis**"),
        ("Requirements", "Nice to have"),
        ("Qualificações:", "## Diferenciais"),
        ("# Requisitos obrigatórios", "Requisitos desejáveis"),
    ],
)
def test_seis_formatos_de_titulo_de_vaga(obrigatorios: str, desejaveis: str) -> None:
    """Rodada 1 da revisão: título numa linha sozinha, sem ":" nem "#", também vale; e "1 ano de
    experiência com…" é o tempo mínimo da vaga (senioridade), não um requisito a mais."""
    vaga = ProvedorRegras().extrair_vaga_sincrono(
        VAGA_FORMATOS.format(o=obrigatorios, d=desejaveis)
    )
    assert [(r.competencia, r.tipo) for r in vaga.requisitos] == [
        ("Python", "obrigatorio"),
        ("FastAPI", "obrigatorio"),
        ("Redis", "desejavel"),
        ("Kubernetes", "desejavel"),
    ]
    assert vaga.anos_minimos == 1


def test_comentario_parcial_e_concordancia() -> None:
    """Parcial pela mesma competência não diz "próxima de si mesma" (fase 8)."""
    from curriculo_api.ia.modelos import LinhaRequisito
    from curriculo_api.ia.regras import _comentario

    def linha(casada: str | None) -> LinhaRequisito:
        return LinhaRequisito(
            descricao="Inglês avançado",
            tipo="desejavel",
            competencia_pedida="Inglês",
            competencia_casada=casada,
            status="parcial",
            valor="1/2",
            regra="mesma_competencia",
            motivo="nível intermediário",
        )

    assert "próxima" not in _comentario(linha("Inglês"))
    assert "abaixo do tempo ou do nível" in _comentario(linha("Inglês"))
    assert "Vue, que é próxima de Inglês" in _comentario(linha("Vue"))
