import math

import pytest
from hypothesis import given
from hypothesis import strategies as st

from curriculo_api.evals.metricas import (
    p95,
    percentil_nearest_rank,
    precisao_cobertura_micro,
)


def test_micro_media_soma_antes_de_dividir() -> None:
    pares = [
        ({"a", "b", "x"}, {"a", "b"}),  # 2 acertos, 3 extraídas, 2 anotadas
        ({"c"}, {"c", "d", "e", "f"}),  # 1 acerto, 1 extraída, 4 anotadas
    ]
    pc = precisao_cobertura_micro(pares)
    assert (pc.acertos, pc.extraidas, pc.anotadas) == (3, 4, 6)
    assert pc.precisao == pytest.approx(0.75)
    assert pc.cobertura == pytest.approx(0.5)
    # A macro-média daria precisão (2/3 + 1)/2 ≈ 0,83 e cobertura (1 + 1/4)/2 = 0,625.


def test_micro_media_vazia_e_indefinida() -> None:
    pc = precisao_cobertura_micro([])
    assert pc.precisao is None and pc.cobertura is None


conjuntos = st.frozensets(st.sampled_from("abcdefghij"))


@given(st.lists(st.tuples(conjuntos, conjuntos), max_size=10))
def test_micro_media_entre_0_e_1(pares: list[tuple[frozenset[str], frozenset[str]]]) -> None:
    pc = precisao_cobertura_micro(pares)
    for valor in (pc.precisao, pc.cobertura):
        assert valor is None or 0 <= valor <= 1


@given(st.lists(conjuntos.filter(bool), min_size=1, max_size=10))
def test_extracao_identica_ao_gabarito_da_1(anotados: list[frozenset[str]]) -> None:
    pc = precisao_cobertura_micro((a, a) for a in anotados)
    assert pc.precisao == 1.0 and pc.cobertura == 1.0


@pytest.mark.parametrize(
    ("valores", "esperado"),
    [
        ([1.0], 1.0),
        ([3.0, 1.0, 2.0], 3.0),  # ⌈0,95 × 3⌉ = 3
        (list(range(1, 21)), 19),  # ⌈0,95 × 20⌉ = 19
        (list(range(1, 101)), 95),
        (list(range(1, 102)), 96),  # ⌈0,95 × 101⌉ = 96
    ],
)
def test_p95_nearest_rank(valores: list[float], esperado: float) -> None:
    assert p95(valores) == esperado


def test_p95_vazio() -> None:
    assert p95([]) is None


def test_percentil_fora_do_intervalo() -> None:
    with pytest.raises(ValueError):
        percentil_nearest_rank([1.0], 0)


@given(
    st.lists(st.floats(0, 1e4, allow_nan=False), min_size=1, max_size=200),
    st.floats(0.1, 100),
)
def test_nearest_rank_e_o_menor_valor_que_cobre_p(valores: list[float], p: float) -> None:
    resultado = percentil_nearest_rank(valores, p)
    assert resultado in valores
    necessarios = max(1, math.ceil(p / 100 * len(valores)))
    assert sum(v <= resultado for v in valores) >= necessarios
    menores = [v for v in valores if v < resultado]
    assert len(menores) < necessarios
