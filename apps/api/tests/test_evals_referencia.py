"""O cálculo de referência reproduz os exemplos do ADR 0003 e as propriedades que o ADR pede."""

from datetime import date

from hypothesis import given
from hypothesis import strategies as st

from curriculo_api.evals.dataset import Status
from curriculo_api.evals.referencia import (
    calcular_nota,
    faixa_de,
    intervalo_em_meses,
    meses_da_uniao,
)

OBRIGATORIOS_ADR: list[Status] = ["atende", "atende", "atende", "atende", "parcial", "nao_atende"]
DESEJAVEIS_ADR: list[Status] = ["atende", "nao_atende", "nao_atende"]
REF = date(2026, 11, 1)


def test_exemplo_trabalhado_do_adr_da_67() -> None:
    # jan/2019–jun/2021 (30 meses) e jan/2021–dez/2022 (24): união jan/2019–dez/2022 = 48 meses;
    # somar daria 54 (os 6 meses de sobreposição contariam duas vezes).
    primeira = intervalo_em_meses("2019-01", "2021-06", REF)
    segunda = intervalo_em_meses("2021-01", "2022-12", REF)
    assert meses_da_uniao([primeira]) + meses_da_uniao([segunda]) == 54
    meses = meses_da_uniao([primeira, segunda])
    assert meses == 48
    assert calcular_nota(OBRIGATORIOS_ADR, DESEJAVEIS_ADR, meses, 5) == 67


def test_sem_desejaveis_renormaliza_para_76() -> None:
    assert calcular_nota(OBRIGATORIOS_ADR, [], 48, 5) == 76


def test_desejaveis_zerados_nao_sao_ausentes_61() -> None:
    assert calcular_nota(OBRIGATORIOS_ADR, ["nao_atende"] * 3, 48, 5) == 61


def test_sem_anos_e_sem_desejaveis_so_obrigatorios() -> None:
    assert calcular_nota(["atende", "atende", "atende", "nao_atende"], [], 0, None) == 75


def test_arredondamento_meio_para_cima() -> None:
    # O = 0,75 → 52,5; D = 0,5 → 10; S = 2/5 anos → 4 ⇒ 66,5. Meio para cima dá 67; o `round`
    # bancário do Python daria 66.
    obrigatorios: list[Status] = ["atende", "atende", "atende", "nao_atende"]
    assert calcular_nota(obrigatorios, ["parcial"], 24, 5) == 67


def test_sobreposicao_conta_uma_vez_e_consecutivos_se_emendam() -> None:
    # Intervalos fechados: (0, 10) são 11 meses.
    assert meses_da_uniao([(0, 10), (5, 20)]) == 21
    assert meses_da_uniao([(0, 10), (11, 20)]) == 21  # jul → ago: sem buraco
    assert meses_da_uniao([(0, 10), (12, 20)]) == 20  # um mês de buraco
    assert meses_da_uniao([(3, 3)]) == 1
    assert meses_da_uniao([]) == 0


def test_datas_sem_mes_e_atual() -> None:
    assert meses_da_uniao([intervalo_em_meses("2024", "2024", REF)]) == 12
    assert meses_da_uniao([intervalo_em_meses("2012", "2016", REF)]) == 60
    assert meses_da_uniao([intervalo_em_meses("2024-03", None, REF)]) == 33  # mar/2024–nov/2026
    consecutivos = [
        intervalo_em_meses("2020-01", "2022-07", REF),
        intervalo_em_meses("2022-08", "2022-12", REF),
    ]
    assert meses_da_uniao(consecutivos) == 36


def test_faixa_truncada() -> None:
    assert faixa_de(100) == (95, 100)
    assert faixa_de(2) == (0, 7)
    assert faixa_de(50) == (45, 55)


statuses = st.lists(st.sampled_from(["atende", "parcial", "nao_atende"]), max_size=8)


@given(statuses, statuses, st.integers(0, 600), st.one_of(st.none(), st.integers(0, 15)))
def test_nota_entre_0_e_100(
    obrig: list[Status], desej: list[Status], meses: int, anos: int | None
) -> None:
    if not obrig and not desej:
        return
    assert 0 <= calcular_nota(obrig, desej, meses, anos) <= 100


@given(
    st.lists(st.sampled_from(["atende", "parcial", "nao_atende"]), min_size=1, max_size=8),
    statuses,
    st.integers(0, 600),
    st.integers(1, 15),
    st.data(),
)
def test_melhorar_um_requisito_nunca_baixa_a_nota(
    obrig: list[Status], desej: list[Status], meses: int, anos: int, data: st.DataObject
) -> None:
    indice = data.draw(st.integers(0, len(obrig) - 1))
    melhor: dict[Status, Status] = {
        "nao_atende": "parcial",
        "parcial": "atende",
        "atende": "atende",
    }
    melhorado = list(obrig)
    melhorado[indice] = melhor[obrig[indice]]
    assert calcular_nota(melhorado, desej, meses, anos) >= calcular_nota(obrig, desej, meses, anos)


@given(statuses, statuses, st.integers(0, 600), st.integers(1, 15), st.data())
def test_ordem_dos_requisitos_nao_importa(
    obrig: list[Status], desej: list[Status], meses: int, anos: int, data: st.DataObject
) -> None:
    if not obrig and not desej:
        return
    obrig_perm = data.draw(st.permutations(obrig))
    desej_perm = data.draw(st.permutations(desej))
    nota = calcular_nota(obrig, desej, meses, anos)
    assert calcular_nota(obrig_perm, desej_perm, meses, anos) == nota
