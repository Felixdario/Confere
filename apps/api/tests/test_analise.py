"""Análise em código (fase 3): ancoragem normalizada, correspondência, nota e regra da evidência.

O teste principal compara a nota do pipeline (com o provedor falso) com o oráculo independente
`evals/referencia.py` nos 30 casos; as propriedades da fórmula vão com hypothesis."""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from curriculo_api.analise.correspondencia import Correspondente, Limiares
from curriculo_api.analise.embeddings import Comparador, EmbutidorFalso, EmbutidorFastEmbed
from curriculo_api.analise.erros import VagaSemRequisitos
from curriculo_api.analise.feedback import competencias_citadas, filtrar_feedback
from curriculo_api.analise.nota import calcular_nota, calcular_tabela
from curriculo_api.analise.pipeline import Analisador, EntradaCurriculo
from curriculo_api.ancoragem import ancorar, normalizar_para_ancora, trecho_ancorado
from curriculo_api.evals import referencia
from curriculo_api.evals.dataset import Dataset, Status
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
    ReescritaIA,
    Requisito,
    TabelaDaNota,
    VagaExtraida,
)
from curriculo_api.ia.orcamento import TetoDeCustoExcedido
from curriculo_api.taxonomia import Taxonomia

REFERENCIA = date(2026, 11, 1)
VALOR: dict[Status, Fraction] = {
    "atende": Fraction(1),
    "parcial": Fraction(1, 2),
    "nao_atende": Fraction(0),
}


def _analisador(raiz: Path, taxonomia: Taxonomia, teto: str = "1") -> Analisador:
    return Analisador(
        ProvedorFalso(raiz / "evals" / "gravacoes"),
        taxonomia,
        Comparador(taxonomia, EmbutidorFalso()),
        Limiares(),
        Decimal(teto),
    )


def _entrada(caso: Any, dataset: Dataset) -> EntradaCurriculo:
    e = entrada_do_caso(caso, dataset.config.data_referencia)
    return EntradaCurriculo(
        texto_vaga=e.texto_vaga,
        data_referencia=e.data_referencia,
        texto_curriculo=e.texto_curriculo,
        arquivo_curriculo=e.arquivo_curriculo,
        nome_arquivo=e.nome_arquivo,
    )


# --- o pipeline = o oráculo nos 30 casos ------------------------------------------------------


@pytest.fixture(scope="module")
def resultados(raiz: Path, dataset: Dataset, taxonomia: Taxonomia) -> dict[str, Any]:
    import asyncio

    analisador = _analisador(raiz, taxonomia)

    async def todos() -> dict[str, Any]:
        return {c.id: await analisador.analisar(_entrada(c, dataset)) for c in dataset.casos}

    return asyncio.run(todos())


def test_nota_do_pipeline_igual_ao_oraculo_nos_30_casos(
    dataset: Dataset, resultados: dict[str, Any]
) -> None:
    assert len(resultados) == 30
    for caso in dataset.casos:
        r = resultados[caso.id]
        esperado = caso.esperado
        assert r.tabela.nota == referencia.nota_de_referencia(esperado, REFERENCIA), caso.id
        assert r.tabela.nota == esperado.nota_referencia, caso.id
        assert r.tabela.anos_relevantes == pytest.approx(esperado.anos_relevantes_esperados), (
            caso.id
        )
        status = [linha.status for linha in r.tabela.linhas]
        assert status == [req.status_esperado for req in esperado.requisitos], caso.id
        # Toda evidência mostrada é trecho ancorado do texto que a IA viu.
        for linha in r.tabela.linhas:
            assert (linha.evidencia is None) == (linha.status == "nao_atende"), caso.id
            if linha.evidencia:
                assert trecho_ancorado(linha.evidencia, r.curriculo.texto_para_ia)
            assert linha.motivo


def test_decomposicao_soma_a_nota(resultados: dict[str, Any]) -> None:
    for r in resultados.values():
        tabela: TabelaDaNota = r.tabela
        soma = sum((Fraction(p.pontos) for p in tabela.parcelas), Fraction(0))
        assert referencia.arredondar_meio_para_cima(soma) == tabela.nota
        assert tabela.decomposicao.endswith(f"nota {tabela.nota}")


def test_b16_renormaliza_e_avisa(resultados: dict[str, Any]) -> None:
    tabela = resultados["b16-administrativo-sem-desejaveis"].tabela
    assert [p.componente for p in tabela.parcelas] == ["obrigatorios"]
    assert any("desejáveis" in a for a in tabela.avisos)
    assert any("anos nem nível" in a for a in tabela.avisos)


def test_filtro_de_reescrita_descarta_as_inventadas(resultados: dict[str, Any]) -> None:
    for caso_id, inventada in (
        ("b02-backend-pleno-node", "Kubernetes"),
        ("b12-engenharia-civil-senior", "Revit"),
        ("b13-ml-senior-en", "PyTorch"),
    ):
        feedback = resultados[caso_id].feedback
        (descartada,) = feedback.reescritas_descartadas
        assert descartada.motivo == "competencia_sem_evidencia"
        assert inventada in descartada.competencias_sem_evidencia
        assert all(inventada not in r.depois for r in feedback.reescritas)
        assert inventada in {a.competencia for a in feedback.o_que_aprender}


def test_nota_nunca_vem_da_ia(resultados: dict[str, Any]) -> None:
    assert "nota" not in FeedbackIA.model_fields
    for r in resultados.values():
        assert not hasattr(r.feedback, "nota")


async def test_eventos_para_o_sse(raiz: Path, dataset: Dataset, taxonomia: Taxonomia) -> None:
    caso = dataset.por_id()["b01-frontend-senior"]
    eventos = [e async for e in _analisador(raiz, taxonomia).eventos(_entrada(caso, dataset))]
    etapas = [e.etapa for e in eventos if e.tipo == "etapa"]
    assert etapas == [
        "leitura",
        "anonimizacao",
        "extracao",
        "ancoragem",
        "correspondencia",
        "nota",
        "feedback",
    ]
    assert any(e.tipo == "texto" for e in eventos)
    assert eventos[-1].tipo == "final" and eventos[-1].resultado is not None


async def test_logs_da_analise_sem_conteudo_do_curriculo(
    raiz: Path, dataset: Dataset, taxonomia: Taxonomia, caplog: pytest.LogCaptureFixture
) -> None:
    caso = dataset.por_id()["b01-frontend-senior"]
    with caplog.at_level(logging.DEBUG):
        await _analisador(raiz, taxonomia).analisar(_entrada(caso, dataset))
    for trecho in ("Tamanduá Violeta", "Mariana", "ReactJS em produção", "mariana.ferraz"):
        assert trecho not in caplog.text
        for registro in caplog.records:
            assert trecho not in str(vars(registro))


async def test_teto_da_analise_bloqueia_com_o_provedor_real_na_frente(
    taxonomia: Taxonomia,
) -> None:
    from curriculo_api.ia.anthropic import ConfigAnthropic, ProvedorAnthropic
    from sdk_falso import ClienteFalso

    cliente = ClienteFalso()
    provedor = ProvedorAnthropic(
        cliente, taxonomia, ConfigAnthropic(estimar_com_count_tokens=False)
    )
    analisador = Analisador(
        provedor, taxonomia, Comparador(taxonomia, EmbutidorFalso()), Limiares(), Decimal("0.001")
    )
    entrada = EntradaCurriculo(
        texto_vaga="Requisitos:\n- Python", data_referencia=REFERENCIA, texto_curriculo="Python."
    )
    with pytest.raises(TetoDeCustoExcedido):
        await analisador.analisar(entrada)
    assert cliente.das("create") == []


# --- propriedades da fórmula (hypothesis) -------------------------------------------------------

status = st.sampled_from(["atende", "parcial", "nao_atende"])
listas = st.lists(status, max_size=8)
anos = st.one_of(st.none(), st.integers(min_value=0, max_value=10))
meses = st.integers(min_value=0, max_value=240)


def _nota(o: list[Status], d: list[Status], m: int, a: int | None) -> int:
    s = None if a is None else referencia.senioridade(m, a)
    return calcular_nota([VALOR[x] for x in o], [VALOR[x] for x in d], s)


@given(listas, listas, meses, anos)
def test_nota_igual_ao_oraculo_e_entre_0_e_100(
    o: list[Status], d: list[Status], m: int, a: int | None
) -> None:
    if not o and not d:
        with pytest.raises(VagaSemRequisitos):
            _nota(o, d, m, a)
        return
    nota = _nota(o, d, m, a)
    assert 0 <= nota <= 100
    assert nota == referencia.calcular_nota(o, d, m, a)


@given(listas.filter(bool), listas, meses, anos, st.data())
def test_melhorar_um_requisito_nunca_baixa_a_nota(
    o: list[Status], d: list[Status], m: int, a: int | None, data: st.DataObject
) -> None:
    i = data.draw(st.integers(min_value=0, max_value=len(o) - 1))
    melhor: dict[Status, Status] = {
        "nao_atende": "parcial",
        "parcial": "atende",
        "atende": "atende",
    }
    o2 = [*o[:i], melhor[o[i]], *o[i + 1 :]]
    assert _nota(o2, d, m, a) >= _nota(o, d, m, a)


@given(listas.filter(bool), listas, meses, anos, st.randoms())
def test_ordem_dos_requisitos_nao_importa(
    o: list[Status], d: list[Status], m: int, a: int | None, aleatorio: Any
) -> None:
    o2, d2 = list(o), list(d)
    aleatorio.shuffle(o2)
    aleatorio.shuffle(d2)
    assert _nota(o2, d2, m, a) == _nota(o, d, m, a)


@given(listas.filter(bool), meses, st.integers(min_value=1, max_value=10))
def test_renormalizar_equivale_a_escalar_os_pesos(o: list[Status], m: int, a: int) -> None:
    media_o = sum((VALOR[x] for x in o), Fraction(0)) / len(o)
    s = referencia.senioridade(m, a)
    esperado = referencia.arredondar_meio_para_cima(
        100 * (Fraction(7, 10) * media_o + Fraction(1, 10) * s) / Fraction(8, 10)
    )
    assert _nota(o, [], m, a) == esperado


def test_exemplo_trabalhado_do_adr_0003() -> None:
    o = [VALOR[s] for s in ("atende",) * 4] + [Fraction(1, 2), Fraction(0)]
    d = [Fraction(1), Fraction(0), Fraction(0)]
    assert calcular_nota(o, d, Fraction(4, 5)) == 67
    assert calcular_nota(o, [], Fraction(4, 5)) == 76
    assert calcular_nota(o, [Fraction(0)] * 3, Fraction(4, 5)) == 61
    # Meio para cima, não arredondamento bancário: 71,5 → 72 (caso b08 das evals).
    assert referencia.arredondar_meio_para_cima(Fraction(143, 2)) == 72


# --- ancoragem normalizada ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("trecho", "texto"),
    [
        ("desenvolvimento de APIs", "Fiz o desenvol-\nvimento de APIs REST"),
        ("migrei o front-end", "MIGREI   O\nFront-end para TS"),
        ('projeto "Vitrine"', "Liderei o projeto “Vitrine” em 2022"),
        ("d'água", "caixa d’água"),
        ("2019 - 2021", "Analista — 2019 – 2021"),
    ],
)
def test_ancoragem_normaliza_espacos_hifen_aspas_e_caixa(trecho: str, texto: str) -> None:
    assert trecho_ancorado(trecho, texto)


@pytest.mark.parametrize(
    ("trecho", "texto"),
    [
        ("React em produção", "ReactJS em produção"),  # palavra diferente
        ("producao", "produção"),  # acento continua valendo
        ("produção ReactJS", "ReactJS em produção"),  # ordem continua valendo
        ("   ", "qualquer coisa"),
        ("Front-end", "Front-\nEnd"),  # hífen real antes de maiúscula não some
    ],
)
def test_ancoragem_nao_aceita_o_que_nao_e_citacao(trecho: str, texto: str) -> None:
    assert not trecho_ancorado(trecho, texto)


@given(st.text(max_size=60))
def test_normalizacao_da_ancora_e_idempotente(texto: str) -> None:
    uma = normalizar_para_ancora(texto)
    assert normalizar_para_ancora(uma) == uma


def test_sem_ancora_e_descartado_e_contado() -> None:
    texto = "Desenvolvedora — Loja X — 2020 – atual\n- ReactJS em produção"
    bruto = CurriculoExtraido(
        experiencias=(
            Experiencia(
                cargo="Dev",
                empresa="Loja X",
                inicio=DataParcial(ano=2020),
                trecho="Loja X — 2020 – atual",
            ),
        ),
        competencias=(
            Competencia(nome="ReactJS", trecho="reactjs EM produção", experiencias=(0,)),
            Competencia(nome="Kubernetes", trecho="clusters Kubernetes"),
        ),
    )
    resultado = ancorar(bruto, texto)
    assert [c.nome for c in resultado.mantido.competencias] == ["ReactJS"]
    assert [(d.secao, d.trecho) for d in resultado.descartados] == [
        ("competencias", "clusters Kubernetes")
    ]


# --- correspondência ---------------------------------------------------------------------------


def _curriculo(*competencias: Competencia, idiomas: tuple[Idioma, ...] = ()) -> CurriculoExtraido:
    return CurriculoExtraido(
        experiencias=(
            Experiencia(
                cargo="Dev",
                empresa="A",
                inicio=DataParcial(ano=2024, mes=1),
                fim=DataParcial(ano=2024, mes=12),
                trecho="Dev — A",
            ),
            Experiencia(
                cargo="Dev",
                empresa="B",
                inicio=DataParcial(ano=2024, mes=7),
                fim=DataParcial(ano=2025, mes=6),
                trecho="Dev — B",
            ),
        ),
        competencias=competencias,
        idiomas=idiomas,
    )


def _vaga(*requisitos: Requisito) -> VagaExtraida:
    return VagaExtraida(titulo="Vaga", idioma="pt", requisitos=requisitos)


def _req(competencia: str, **kw: Any) -> Requisito:
    return Requisito(descricao=competencia, tipo="obrigatorio", competencia=competencia, **kw)


def _correspondente(
    taxonomia: Taxonomia, pares: dict[tuple[str, str], float] | None = None
) -> Correspondente:
    return Correspondente(
        taxonomia, Comparador(taxonomia, EmbutidorFalso(pares)), Limiares(0.85, 0.70), REFERENCIA
    )


def test_sinonimo_relacionada_e_falso_amigo(taxonomia: Taxonomia) -> None:
    curriculo = _curriculo(
        Competencia(nome="ReactJS", trecho="ReactJS"),
        Competencia(nome="Vue.js", trecho="Vue.js"),
        Competencia(nome="Java", trecho="Java"),
    )
    linhas = (
        _correspondente(taxonomia)
        .corresponder(curriculo, _vaga(_req("React"), _req("Angular"), _req("JavaScript")))
        .linhas
    )
    react, angular, javascript = linhas
    assert (react.status, react.regra, react.competencia_casada) == (
        "atende",
        "sinonimo_na_taxonomia",
        "ReactJS",
    )
    assert "sinônimo de React" in react.motivo and react.evidencia == "ReactJS"
    assert (angular.status, angular.regra) == ("parcial", "relacionada_na_taxonomia")
    assert (javascript.status, javascript.regra) == ("nao_atende", "sem_evidencia")


def test_embeddings_com_os_limiares(taxonomia: Taxonomia) -> None:
    pares = {
        ("Termo pedido A", "Coisa escrita A"): 0.91,
        ("Termo pedido B", "Coisa escrita B"): 0.75,
        ("Termo pedido C", "Coisa escrita C"): 0.40,
    }
    curriculo = _curriculo(
        *(Competencia(nome=f"Coisa escrita {x}", trecho=f"Coisa escrita {x}") for x in "ABC")
    )
    vaga = _vaga(*(_req(f"Termo pedido {x}") for x in "ABC"))
    resultado = _correspondente(taxonomia, pares).corresponder(curriculo, vaga)
    a, b, c = resultado.linhas
    assert (a.status, a.regra, a.similaridade) == ("atende", "similaridade", 0.91)
    assert (b.status, b.regra, b.similaridade) == ("parcial", "similaridade", 0.75)
    assert c.status == "nao_atende"
    assert "0,85" in a.motivo or "τ_alto" in a.motivo
    assert resultado.consultas_embedding > 0


def test_anos_por_competencia_pela_uniao_e_nivel_declarado(taxonomia: Taxonomia) -> None:
    curriculo = _curriculo(
        Competencia(nome="Python", trecho="Python", experiencias=(0, 1)),
        idiomas=(Idioma(idioma="Inglês", nivel="intermediário", trecho="Inglês intermediário"),),
    )
    vaga = _vaga(
        _req("Python", anos_minimos=2),
        _req("Python", anos_minimos=1),
        _req("Inglês", nivel="avancado"),
        _req("Inglês", nivel="basico"),
    )
    dois, um, avancado, basico = _correspondente(taxonomia).corresponder(curriculo, vaga).linhas
    # jan/2024–dez/2024 ∪ jul/2024–jun/2025 = 18 meses (a sobreposição conta uma vez).
    assert (dois.status, dois.anos_comprovados) == ("parcial", 1.5)
    assert "1,5 de 2 anos" in dois.motivo
    assert um.status == "atende"
    assert (avancado.status, avancado.nivel_declarado) == ("parcial", "intermediario")
    assert "abaixo do pedido" in avancado.motivo
    assert basico.status == "atende"


def test_vaga_sem_requisitos_da_erro_claro(taxonomia: Taxonomia) -> None:
    with pytest.raises(VagaSemRequisitos, match="requisitos reconhecíveis"):
        calcular_tabela((), _curriculo(), _vaga(), frozenset(), taxonomia, REFERENCIA)


def test_vetores_da_taxonomia_ficam_em_cache_em_disco(taxonomia: Taxonomia, tmp_path: Path) -> None:
    chamadas: list[int] = []

    class ModeloFalso:
        def embed(self, termos: list[str]) -> Any:
            chamadas.append(len(termos))
            for termo in termos:
                yield np.ones(8, dtype=np.float32) * (len(termo) % 5 + 1)

    def fabrica(_nome: str, _pasta: str) -> ModeloFalso:
        return ModeloFalso()

    for _ in range(2):
        embutidor = EmbutidorFastEmbed("modelo-teste", tmp_path, fabrica=fabrica)
        Comparador(taxonomia, embutidor, tmp_path).canonica_mais_proxima("termo novo")
    termos_da_taxonomia = chamadas[0]
    assert termos_da_taxonomia > 100
    assert chamadas[1:] == [1, 1]  # na 2ª vez, só o termo consultado; a taxonomia vem do disco
    assert list((tmp_path / "vetores").glob("taxonomia-*.npz"))


# --- regra da evidência no feedback ------------------------------------------------------------


def test_filtro_da_evidencia(taxonomia: Taxonomia) -> None:
    texto = "- Desenvolvo APIs em Python.\n- Testes com Jest."
    curriculo = _curriculo(
        Competencia(nome="Python", trecho="APIs em Python"),
        Competencia(nome="Jest", trecho="Testes com Jest"),
    )
    tabela = TabelaDaNota(
        nota=50,
        linhas=(
            LinhaRequisito(
                descricao="Kubernetes em produção",
                tipo="obrigatorio",
                competencia_pedida="Kubernetes",
                status="nao_atende",
                valor="0",
                regra="sem_evidencia",
                motivo="nenhuma evidência de Kubernetes no currículo",
            ),
        ),
    )
    bruto = FeedbackIA(
        resumo="ok",
        palavras_chave_ats=("Python", "Rust", "python"),
        reescritas=(
            ReescritaIA(
                antes="Desenvolvo APIs em Python.",
                depois="Desenvolvo APIs em Python com testes em Jest.",
                competencias=("Python", "Jest"),
            ),
            ReescritaIA(  # declara só Python, mas o texto cita Kubernetes: o código detecta
                antes="Desenvolvo APIs em Python.",
                depois="Desenvolvo APIs em Python e opero clusters Kubernetes.",
                competencias=("Python",),
            ),
            ReescritaIA(
                antes="Liderei uma equipe de 30 pessoas.", depois="Liderei.", competencias=()
            ),
        ),
    )
    feedback = filtrar_feedback(bruto, tabela, curriculo, texto, "Python e Go", taxonomia)
    assert [r.depois for r in feedback.reescritas] == [
        "Desenvolvo APIs em Python com testes em Jest."
    ]
    motivos = [d.motivo for d in feedback.reescritas_descartadas]
    assert motivos == ["competencia_sem_evidencia", "antes_sem_ancora"]
    assert feedback.reescritas_descartadas[0].competencias_sem_evidencia == ("Kubernetes",)
    assert [a.competencia for a in feedback.o_que_aprender] == ["Kubernetes"]
    assert feedback.palavras_chave_ats == ("Python",)
    assert feedback.reescritas_propostas == 3


def test_competencias_citadas_respeita_termo_curto(taxonomia: Taxonomia) -> None:
    assert "Go" in competencias_citadas("Serviços em Go e Python", taxonomia)
    assert "Go" not in competencias_citadas("vamos go embora", taxonomia)
    assert "JavaScript" not in competencias_citadas("Backend em Java", taxonomia)
