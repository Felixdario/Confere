"""Integridade do dataset de evals: contagem, schema, evidências literais, faixas coerentes com o
ADR 0003 e variantes com o mesmo conteúdo profissional do par-base."""

import json
import re
from collections import Counter
from datetime import date

import pytest

from curriculo_api.evals.dataset import (
    MARCADOR_OCULTO,
    TIPO_PARA_ATRIBUTO,
    Caso,
    Dataset,
    Esperado,
    aplicar_substituicoes,
    espacos_normalizados,
    sem_cabecalho,
    sem_injecao,
    trechos_do_esperado,
)
from curriculo_api.evals.referencia import (
    faixa_de,
    intervalo_em_meses,
    meses_da_uniao,
    meses_relevantes,
    nota_de_referencia,
)
from curriculo_api.taxonomia import Taxonomia

TOTAL_DE_CASOS = 30
CAMPOS_PROFISSIONAIS = (
    "idioma_vaga",
    "titulo_vaga",
    "nivel",
    "anos_minimos",
    "experiencias",
    "competencias",
    "formacao",
    "idiomas",
    "certificacoes",
    "requisitos",
    "anos_relevantes_esperados",
    "nota_referencia",
    "faixa_nota",
    "lacunas",
)
CAMPOS_DO_CURRICULO = ("experiencias", "competencias", "requisitos")
DOMINIOS_RESERVADOS = re.compile(r"@(example\.(com|net|org)|[\w.-]+\.(example|test|invalid))$")
TELEFONE_FICTICIO = re.compile(r"^(\+55 )?\(00\) 9\d{4}-\d{4}$")


def test_composicao_16_base_6_injection_8_contrafactuais(dataset: Dataset) -> None:
    contagem = Counter(c.esperado.tipo for c in dataset.casos)
    assert contagem == {"base": 16, "injection": 6, "contrafactual": 8}
    assert len(dataset.casos) == TOTAL_DE_CASOS


def test_grupos_contrafactuais(dataset: Dataset) -> None:
    grupos = Counter(c.esperado.base for c in dataset.do_tipo("contrafactual"))
    assert grupos == {
        "b03-dados-pleno-vaga-en": 3,
        "b06-contabilidade-pleno": 2,
        "b11-rh-pleno": 2,
        "b01-frontend-senior": 1,
    }


def test_injection_cobre_os_tipos_pedidos(dataset: Dataset) -> None:
    injecoes = [c.esperado.injecao for c in dataset.do_tipo("injection")]
    assert all(i is not None for i in injecoes)
    ocultas = [i for i in injecoes if i and i.oculta]
    assert len(ocultas) == 2
    assert all(i.alerta == "texto_oculto" for i in ocultas)
    assert any(i and i.local == "vaga" for i in injecoes)
    assert sum(1 for i in injecoes if i and not i.oculta) == 4


def test_diversidade_dos_pares_base(dataset: Dataset) -> None:
    base = dataset.do_tipo("base")
    assert sum(c.esperado.idioma_vaga == "en" for c in base) >= 2
    notas = [c.esperado.nota_referencia for c in base]
    assert max(notas) >= 85 and min(notas) <= 40
    assert {c.esperado.nivel for c in base} >= {"junior", "pleno", "senior"}
    fins_sem_mes = [e for c in base for e in c.esperado.experiencias if e.fim and "-" not in e.fim]
    assert fins_sem_mes, "precisa de datas sem mês"


@pytest.fixture(params=range(TOTAL_DE_CASOS), ids=lambda i: f"caso{i:02d}")
def caso(request: pytest.FixtureRequest, dataset: Dataset) -> Caso:
    indice: int = request.param
    return dataset.casos[indice]


def test_todo_trecho_e_evidencia_existem_literalmente(caso: Caso) -> None:
    ausentes = [t for t in trechos_do_esperado(caso.esperado) if t not in caso.curriculo]
    assert not ausentes, f"{caso.id}: trechos fora do currículo: {ausentes}"


def test_trecho_nao_sai_do_texto_oculto(caso: Caso) -> None:
    ocultos = MARCADOR_OCULTO.findall(caso.curriculo)
    texto_visivel = MARCADOR_OCULTO.sub("", caso.curriculo)
    for trecho in trechos_do_esperado(caso.esperado):
        assert trecho in texto_visivel, f"{caso.id}: {trecho!r} só existe no texto oculto"
    if caso.esperado.injecao and caso.esperado.injecao.oculta:
        assert ocultos == [caso.esperado.injecao.trecho]
    else:
        assert not ocultos


def test_requisitos_estao_na_vaga(caso: Caso) -> None:
    ausentes = [r.descricao for r in caso.esperado.requisitos if r.descricao not in caso.vaga]
    assert not ausentes, f"{caso.id}: requisitos fora da vaga: {ausentes}"


def test_como_escrito_aparece_no_trecho(caso: Caso) -> None:
    for c in caso.esperado.competencias:
        if c.como_escrito is not None:
            assert c.como_escrito.casefold() in c.trecho.casefold(), (caso.id, c)


def test_nota_e_faixa_coerentes_com_o_adr_0003(caso: Caso, dataset: Dataset) -> None:
    esperado = caso.esperado
    referencia = dataset.config.data_referencia
    nota = nota_de_referencia(esperado, referencia)
    assert esperado.nota_referencia == nota, f"{caso.id}: anotado {esperado.nota_referencia}"
    assert tuple(esperado.faixa_nota) == faixa_de(nota)
    assert esperado.faixa_nota[0] <= esperado.nota_referencia <= esperado.faixa_nota[1]
    anos = meses_relevantes(esperado, referencia) / 12
    assert esperado.anos_relevantes_esperados == pytest.approx(anos, abs=0.005)


def test_status_coerente_com_a_taxonomia(caso: Caso, taxonomia: Taxonomia) -> None:
    """atende → a competência tem evidência; parcial → ela ou uma relacionada tem; não atende →
    nem ela nem relacionada (ADR 0003, correspondência)."""
    evidencias = caso.esperado.evidencias_canonicas
    for r in caso.esperado.requisitos:
        tem = r.competencia in evidencias
        tem_relacionada = bool(taxonomia.relacionadas_de(r.competencia) & evidencias)
        if r.status_esperado == "atende":
            assert tem, (caso.id, r.descricao)
        elif r.status_esperado == "parcial":
            assert tem or tem_relacionada, (caso.id, r.descricao)
        else:
            assert not tem and not tem_relacionada, (caso.id, r.descricao)


def test_relevancia_segue_a_regra_do_adr(caso: Caso, taxonomia: Taxonomia) -> None:
    """Experiência relevante = tem competência ligada a ela que atende ou atende em parte (mesma
    canônica ou relacionada) algum obrigatório com status atende/parcial."""
    pedidos = {
        r.competencia
        for r in caso.esperado.requisitos
        if r.tipo == "obrigatorio" and r.status_esperado != "nao_atende"
    }
    for indice, experiencia in enumerate(caso.esperado.experiencias):
        ligadas = {c.canonica for c in caso.esperado.competencias if indice in c.experiencias}
        relevante = any(
            competencia in pedidos or bool(taxonomia.relacionadas_de(competencia) & pedidos)
            for competencia in ligadas
        )
        assert experiencia.relevante == relevante, (caso.id, experiencia.cargo)


def _meses_da_competencia(esperado: Esperado, competencia: str, referencia: date) -> int:
    indices = {
        i for c in esperado.competencias if c.canonica == competencia for i in c.experiencias
    }
    return meses_da_uniao(
        intervalo_em_meses(e.inicio, e.fim, referencia)
        for i, e in enumerate(esperado.experiencias)
        if i in indices
    )


def test_requisito_com_anos_usa_as_experiencias_da_competencia(
    caso: Caso, dataset: Dataset
) -> None:
    for r in caso.esperado.requisitos:
        if r.anos is None or r.competencia not in caso.esperado.competencias_anotadas:
            continue
        meses = _meses_da_competencia(caso.esperado, r.competencia, dataset.config.data_referencia)
        esperado_status = "atende" if meses >= 12 * r.anos else "parcial"
        assert r.status_esperado == esperado_status, (caso.id, r.descricao, meses)


def test_lacunas_coerentes_com_os_requisitos(caso: Caso) -> None:
    nao_atendidos = {
        r.competencia for r in caso.esperado.requisitos if r.status_esperado != "atende"
    }
    obrigatorios_faltando = {
        r.competencia
        for r in caso.esperado.requisitos
        if r.tipo == "obrigatorio" and r.status_esperado != "atende"
    }
    lacunas = set(caso.esperado.lacunas)
    assert lacunas <= nao_atendidos, (caso.id, lacunas - nao_atendidos)
    assert obrigatorios_faltando <= lacunas, (caso.id, obrigatorios_faltando - lacunas)


def _cpf_valido(cpf: str) -> bool:
    digitos = [int(d) for d in re.sub(r"\D", "", cpf)]
    if len(digitos) != 11 or len(set(digitos)) == 1:
        return False
    for tamanho in (9, 10):
        soma = sum(d * p for d, p in zip(digitos[:tamanho], range(tamanho + 1, 1, -1), strict=True))
        dv = (soma * 10) % 11 % 10
        if dv != digitos[tamanho]:
            return False
    return True


def test_verificador_de_cpf() -> None:
    assert _cpf_valido("529.982.247-25")
    assert not _cpf_valido("529.982.247-20")


def test_dominios_e_telefones_reservados() -> None:
    assert DOMINIOS_RESERVADOS.search("a@example.com")
    assert DOMINIOS_RESERVADOS.search("a@empresa.example")
    assert not DOMINIOS_RESERVADOS.search("a@exemplo.com.br")
    assert TELEFONE_FICTICIO.match("(00) 90000-0101")
    assert TELEFONE_FICTICIO.match("+55 (00) 90000-0404")
    assert not TELEFONE_FICTICIO.match("(11) 90000-0101")


def test_dados_pessoais_ficticios_e_literais(caso: Caso) -> None:
    tipos = {d.tipo for d in caso.esperado.dados_pessoais}
    assert {"nome", "email", "telefone"} <= tipos, caso.id
    cabecalho = caso.curriculo[: len(caso.curriculo) - len(sem_cabecalho(caso.curriculo))]
    for dado in caso.esperado.dados_pessoais:
        assert dado.valor in cabecalho, f"{caso.id}: {dado.valor!r} fora do cabeçalho"
        if dado.tipo == "email":
            assert DOMINIOS_RESERVADOS.search(dado.valor), dado.valor
        if dado.tipo == "telefone":
            assert TELEFONE_FICTICIO.match(dado.valor), dado.valor
        if dado.tipo == "cpf":
            assert re.fullmatch(r"\d{3}\.\d{3}\.\d{3}-\d{2}", dado.valor), dado.valor
            assert not _cpf_valido(dado.valor), f"{caso.id}: CPF com dígitos válidos"
    nome = next(d.valor for d in caso.esperado.dados_pessoais if d.tipo == "nome")
    assert nome not in sem_cabecalho(caso.curriculo), "o nome só pode estar no cabeçalho"


def test_nenhum_email_ou_telefone_fora_do_reservado(caso: Caso) -> None:
    for texto in (caso.curriculo, caso.vaga):
        for email in re.findall(r"[\w.+-]+@[\w.-]+", texto):
            assert DOMINIOS_RESERVADOS.search(email), (caso.id, email)
        for ddd in re.findall(r"\((\d{2})\) 9", texto):
            assert ddd == "00", (caso.id, ddd)


def test_variantes_de_injection_tem_o_conteudo_do_base(dataset: Dataset) -> None:
    por_id = dataset.por_id()
    for caso in dataset.do_tipo("injection"):
        injecao = caso.esperado.injecao
        assert injecao is not None and caso.esperado.base is not None
        base = por_id[caso.esperado.base]
        assert base.esperado.tipo == "base"
        if injecao.local == "curriculo":
            limpo_cv, limpo_vaga = sem_injecao(caso.curriculo, injecao), caso.vaga
        else:
            limpo_cv, limpo_vaga = caso.curriculo, sem_injecao(caso.vaga, injecao)
        assert espacos_normalizados(limpo_cv) == espacos_normalizados(base.curriculo), caso.id
        assert espacos_normalizados(limpo_vaga) == espacos_normalizados(base.vaga), caso.id
        assert caso.esperado.dados_pessoais == base.esperado.dados_pessoais


def test_contrafactuais_mudam_so_o_declarado(dataset: Dataset) -> None:
    por_id = dataset.por_id()
    for caso in dataset.do_tipo("contrafactual"):
        cf = caso.esperado.contrafactual
        assert cf is not None and caso.esperado.base is not None
        base = por_id[caso.esperado.base]
        assert base.esperado.tipo == "base"
        corpo_base = aplicar_substituicoes(sem_cabecalho(base.curriculo), cf.substituicoes)
        assert sem_cabecalho(caso.curriculo) == corpo_base, caso.id
        if cf.substituicoes:
            assert sem_cabecalho(caso.curriculo) != sem_cabecalho(base.curriculo)
        assert caso.vaga == base.vaga
        meus = {d.tipo: d.valor for d in caso.esperado.dados_pessoais}
        deles = {d.tipo: d.valor for d in base.esperado.dados_pessoais}
        muda = {
            TIPO_PARA_ATRIBUTO[t] for t in meus.keys() | deles.keys() if meus.get(t) != deles.get(t)
        }
        if cf.substituicoes:
            muda |= {"genero", "cargo_flexionado"}
        assert set(cf.muda) == muda, (caso.id, sorted(cf.muda), sorted(muda))
        assert {"nome", "idade"} <= muda, caso.id


def _idade(nascimento: str, referencia: date) -> int:
    dia, mes, ano = (int(x) for x in nascimento.split("/"))
    return referencia.year - ano - ((referencia.month, referencia.day) < (mes, dia))


def test_idades_compativeis_com_o_corpo(dataset: Dataset) -> None:
    """Quem se formou numa graduação tinha pelo menos 20 anos; quem começou a trabalhar, 16."""
    referencia = dataset.config.data_referencia
    for caso in dataset.casos:
        nascimento = next(
            (d.valor for d in caso.esperado.dados_pessoais if d.tipo == "nascimento"), None
        )
        if nascimento is None:
            continue
        ano_nasc = int(nascimento[-4:])
        graduacoes = [
            f.conclusao
            for f in caso.esperado.formacao
            if f.conclusao and f.curso.startswith(("Bacharelado", "Licenciatura", "Tecnologia"))
        ]
        for conclusao in graduacoes:
            assert conclusao - ano_nasc >= 20, (caso.id, conclusao, nascimento)
        for e in caso.esperado.experiencias:
            assert int(e.inicio[:4]) - ano_nasc >= 16, (caso.id, e.cargo)
        assert 18 <= _idade(nascimento, referencia) <= 75, caso.id


def test_contrafactuais_variam_genero_no_grupo(dataset: Dataset) -> None:
    por_id = dataset.por_id()
    contrafactuais = dataset.do_tipo("contrafactual")
    for base_id in {c.esperado.base for c in contrafactuais}:
        assert base_id is not None
        grupo = [por_id[base_id], *(c for c in contrafactuais if c.esperado.base == base_id)]
        generos = {d.valor for c in grupo for d in c.esperado.dados_pessoais if d.tipo == "genero"}
        flexionado = any(
            c.esperado.contrafactual and c.esperado.contrafactual.substituicoes for c in grupo
        )
        assert len(generos) == 2 or flexionado, f"o grupo de {base_id} precisa variar o gênero"


def test_variantes_herdam_o_gabarito_profissional(dataset: Dataset) -> None:
    por_id = dataset.por_id()
    for caso in dataset.casos:
        if caso.esperado.base is None:
            continue
        base = por_id[caso.esperado.base].esperado
        subs = caso.esperado.contrafactual.substituicoes if caso.esperado.contrafactual else ()
        for campo in CAMPOS_PROFISSIONAIS:
            # As trocas de cargo só valem para o que vem do currículo, nunca para a vaga.
            trocas = subs if campo in CAMPOS_DO_CURRICULO else ()
            esperado_json = aplicar_substituicoes(
                json.dumps(base.model_dump(mode="json")[campo], ensure_ascii=False), trocas
            )
            atual = json.dumps(caso.esperado.model_dump(mode="json")[campo], ensure_ascii=False)
            assert atual == esperado_json, (caso.id, campo)
