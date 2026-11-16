from typing import Any

import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from curriculo_api.evals.dataset import Dataset
from curriculo_api.taxonomia import ArquivoTaxonomia, Taxonomia, normalizar_termo


def _arquivo(*entradas: dict[str, Any]) -> ArquivoTaxonomia:
    return ArquivoTaxonomia.model_validate({"versao": 1, "competencias": list(entradas)})


@pytest.mark.parametrize(
    ("termo", "canonica"),
    [
        ("ReactJS", "React"),
        ("React.js", "React"),
        ("react js", "React"),
        ("Postgres", "PostgreSQL"),
        ("Node", "Node.js"),
        ("k8s", "Kubernetes"),
        ("MS Excel", "Excel"),
        ("  ms excel. ", "Excel"),
        ("English", "Inglês"),
        ("ingles", "Inglês"),
        ("A/B testing", "Testes A/B"),
        ("Airflow", "Apache Airflow"),
    ],
)
def test_sinonimos_levam_a_canonica(taxonomia: Taxonomia, termo: str, canonica: str) -> None:
    assert taxonomia.canonica_de(termo) == canonica


def test_falso_amigo_java_javascript(taxonomia: Taxonomia) -> None:
    assert taxonomia.canonica_de("Java") == "Java"
    assert taxonomia.canonica_de("JavaScript") == "JavaScript"
    assert "Java" not in taxonomia.relacionadas_de("JavaScript")
    assert "JavaScript" not in taxonomia.relacionadas_de("Java")


def test_relacionadas_do_adr(taxonomia: Taxonomia) -> None:
    assert "Vue.js" in taxonomia.relacionadas_de("React")
    assert "Kubernetes" in taxonomia.relacionadas_de("Docker")


def test_termo_fora_da_taxonomia_vira_forma_normalizada(taxonomia: Taxonomia) -> None:
    assert taxonomia.canonica_de("Kotlin Multiplatform") is None
    assert taxonomia.chave_de("  Kotlin Multiplatform! ") == "kotlin multiplatform"


def test_normalizacao_preserva_cerquilha_mais_e_ponto_inicial() -> None:
    assert normalizar_termo("C#") == "c#"
    assert normalizar_termo("C++") == "c++"
    assert normalizar_termo(".NET") == ".net"
    assert normalizar_termo(".NET") != normalizar_termo("NET")
    assert normalizar_termo("Node.") == "node"
    assert normalizar_termo("“Gestão de Projetos”.") == "gestao de projetos"


def test_produtos_e_partes_nao_sao_sinonimos(taxonomia: Taxonomia) -> None:
    """Revisão da rodada 1: Tasy, TCP/IP e triagem de currículos são canônicas relacionadas, não
    sinônimos; "CD" sozinho não é CI/CD."""
    assert taxonomia.canonica_de("Tasy") == "Tasy"
    assert "Prontuário eletrônico" in taxonomia.relacionadas_de("Tasy")
    assert taxonomia.canonica_de("TCP/IP") == "TCP/IP"
    assert "Redes de computadores" in taxonomia.relacionadas_de("TCP/IP")
    assert taxonomia.canonica_de("triagem de currículos") == "Triagem de currículos"
    assert "Recrutamento e seleção" in taxonomia.relacionadas_de("Triagem de currículos")
    assert taxonomia.canonica_de("CD") is None
    assert taxonomia.canonica_de("CI") is None


@settings(deadline=None)  # a 1ª chamada carrega as tabelas Unicode e passa de 200 ms
@given(st.text())
@example("𝓐")  # letra matemática: compatibilidade vira "A", e a caixa precisa vir depois
@example("ﬁ")  # ligadura
@example("Ⅻ")  # numeral romano
@example("ß")  # casefold vira "ss"
@example("İ")  # casefold gera ponto combinante
def test_normalizacao_idempotente(termo: str) -> None:
    assert normalizar_termo(normalizar_termo(termo)) == normalizar_termo(termo)


@pytest.mark.parametrize(
    ("termo", "esperado"),
    [("𝓐", "a"), ("ﬁ", "fi"), ("Ⅻ", "xii"), ("ß", "ss"), ("Straße", "strasse")],
)
def test_formas_de_compatibilidade(termo: str, esperado: str) -> None:
    assert normalizar_termo(termo) == esperado


def test_sinonimo_em_duas_entradas_e_recusado() -> None:
    with pytest.raises(ValidationError, match="aparece em"):
        _arquivo(
            {"canonica": "React", "categoria": "x", "sinonimos": ["ReactJS"]},
            {"canonica": "Preact", "categoria": "x", "sinonimos": ["reactjs"]},
        )


def test_relacionada_inexistente_e_recusada() -> None:
    with pytest.raises(ValidationError, match="não é canônica"):
        _arquivo({"canonica": "React", "categoria": "x", "relacionadas": ["Svelte"]})


def test_relacao_assimetrica_e_recusada() -> None:
    with pytest.raises(ValidationError, match="não simétrica"):
        _arquivo(
            {"canonica": "React", "categoria": "x", "relacionadas": ["Vue.js"]},
            {"canonica": "Vue.js", "categoria": "x"},
        )


def test_toda_competencia_do_dataset_existe_na_taxonomia(
    dataset: Dataset, taxonomia: Taxonomia
) -> None:
    faltando: set[str] = set()
    for caso in dataset.casos:
        e = caso.esperado
        citadas = {c.canonica for c in e.competencias}
        citadas |= {r.competencia for r in e.requisitos}
        citadas |= {i.idioma for i in e.idiomas}
        citadas |= {c.canonica for c in e.certificacoes if c.canonica is not None}
        citadas |= set(e.lacunas)
        faltando |= citadas - taxonomia.canonicas
    assert not faltando, f"fora da taxonomia: {sorted(faltando)}"


def test_como_escrito_mapeia_para_a_canonica(dataset: Dataset, taxonomia: Taxonomia) -> None:
    erros = [
        f"{caso.id}: {c.nome!r} → {taxonomia.canonica_de(c.nome)!r}, esperado {c.canonica!r}"
        for caso in dataset.casos
        for c in caso.esperado.competencias
        if taxonomia.canonica_de(c.nome) != c.canonica
    ]
    assert not erros, "\n".join(erros)
