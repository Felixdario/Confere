"""Anonimização: os dados pessoais anotados somem em todos os 30 casos, nenhuma evidência some, os
contrafactuais viram o mesmo texto do par-base e os falsos positivos clássicos não acontecem."""

import logging
import re

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from curriculo_api.evals.dataset import Caso, Dataset, aplicar_substituicoes, trechos_do_esperado
from curriculo_api.evals.pipeline import ingerir_caso
from curriculo_api.ingestao import anonimizar, ingerir_curriculo
from curriculo_api.ingestao.anonimizacao import PARTICULAS, mascarar, palavras_da_taxonomia
from curriculo_api.ingestao.normalizacao import sem_acentos
from curriculo_api.taxonomia import Taxonomia


def _casos(dataset: Dataset) -> list[Caso]:
    return list(dataset.casos)


@pytest.fixture(scope="module")
def anonimizados(dataset: Dataset) -> dict[str, str]:
    return {caso.id: ingerir_caso(caso)[0].anonimizacao.texto for caso in dataset.casos}


def _partes_do_nome(caso: Caso) -> list[str]:
    nome = next(d.valor for d in caso.esperado.dados_pessoais if d.tipo == "nome")
    return [p for p in nome.split() if sem_acentos(p).lower() not in PARTICULAS]


def test_todo_dado_pessoal_anotado_sumiu(dataset: Dataset, anonimizados: dict[str, str]) -> None:
    for caso in dataset.casos:
        texto = anonimizados[caso.id]
        for dado in caso.esperado.dados_pessoais:
            assert dado.valor not in texto, (caso.id, dado.tipo)
        for parte in _partes_do_nome(caso):
            assert not re.search(rf"\b{re.escape(parte)}\b", texto, re.IGNORECASE), (caso.id, parte)


def test_nenhuma_evidencia_do_gabarito_foi_apagada(
    dataset: Dataset, anonimizados: dict[str, str]
) -> None:
    for caso in dataset.casos:
        texto = anonimizados[caso.id]
        perdidos = [t for t in trechos_do_esperado(caso.esperado) if t not in texto]
        assert not perdidos, (caso.id, perdidos)


def test_o_que_foi_removido_cobre_os_tipos_anotados(dataset: Dataset) -> None:
    for caso in dataset.casos:
        anonimizacao = ingerir_caso(caso)[0].anonimizacao
        removidos = {r.tipo for r in anonimizacao.removidos}
        anotados = {d.tipo for d in caso.esperado.dados_pessoais}
        assert anotados <= removidos, (caso.id, anotados - removidos)
        assert anonimizacao.nome_encontrado, caso.id


def test_contrafactuais_viram_o_texto_do_par_base(
    dataset: Dataset, anonimizados: dict[str, str]
) -> None:
    """A garantia de viés por construção: o texto que a IA vê é idêntico (c07: só o cargo)."""
    for caso in dataset.do_tipo("contrafactual"):
        contrafactual = caso.esperado.contrafactual
        assert contrafactual is not None and caso.esperado.base is not None
        esperado = aplicar_substituicoes(
            anonimizados[caso.esperado.base], contrafactual.substituicoes
        )
        assert anonimizados[caso.id] == esperado, caso.id
        if not contrafactual.substituicoes:
            assert anonimizados[caso.id] == anonimizados[caso.esperado.base]


def test_c07_so_difere_no_cargo(dataset: Dataset, anonimizados: dict[str, str]) -> None:
    caso = dataset.por_id()["c07-frontend-cargo-masculino"]
    base = anonimizados["b01-frontend-senior"]
    assert anonimizados[caso.id] != base
    assert caso.esperado.contrafactual is not None
    desfeito = anonimizados[caso.id]
    for s in caso.esperado.contrafactual.substituicoes:
        desfeito = desfeito.replace(s.para, s.de)
    assert desfeito == base


def test_cabecalho_vira_marcadores() -> None:
    texto = (
        "# Mariana Couto Ferraz\n\n"
        "E-mail: mariana.ferraz@example.com · Telefone: (00) 90000-0101 · São Paulo – SP\n"
        "Data de nascimento: 22/08/1995 · CPF: 318.742.596-10\n\n## Resumo\n\nFront-end.\n"
    )
    resultado = anonimizar(texto)
    assert resultado.texto == ("# [NOME]\n\n[DADOS_PESSOAIS]\n\n## Resumo\n\nFront-end.\n")
    valores = {(r.tipo, r.valor) for r in resultado.removidos}
    assert ("nome", "Mariana Couto Ferraz") in valores
    assert ("cpf", "318.742.596-10") in valores
    assert ("nascimento", "22/08/1995") in valores


# --- falsos positivos -------------------------------------------------------------------------

CORPO = """\
## Experiência

Analista de Dados — Rua Digital Projetos — mar/2019 – atual
- 5 anos de experiência com Python e SQL.
- Projeto "Rua Viva" de mapeamento urbano.
- Atendimento em São Paulo e em Rosa Velha Comércio.
- Projeto Esperança: painel de indicadores.

## Formação

Bacharelado em Estatística — Universidade Fictícia — 2014 – 2018
"""


def test_falsos_positivos_classicos_nao_acontecem() -> None:
    """ "5 anos de experiência", "Rua" em nome de projeto e datas de emprego ficam."""
    texto = "# Fulana Beltrana Ciclana\n\nfulana@example.com · (00) 90000-0000\n\n" + CORPO
    resultado = anonimizar(texto)
    assert resultado.texto.startswith("# [NOME]\n\n[DADOS_PESSOAIS]\n")
    corpo = resultado.texto[resultado.texto.index("## Experiência") :]
    assert corpo == CORPO


def test_parte_do_nome_colada_a_outro_nome_proprio_fica() -> None:
    """Rodada 2 (ADR 0004): a parte isolada do nome fica quando está colada a outro nome próprio
    ("Rosa Velha Comércio", "Projeto Esperança"); a minúscula também fica."""
    texto = "# Rosa Maria Esperança\n\nrosa@example.com\n\n" + CORPO + "Mantive a esperança.\n"
    resultado = anonimizar(texto)
    corpo = resultado.texto[resultado.texto.index("## Experiência") :]
    assert corpo == CORPO + "Mantive a esperança.\n"


def test_parte_do_nome_isolada_sai_fora_de_nome_proprio() -> None:
    texto = (
        "# Mariana Couto Ferraz\n\n## Resumo\n\n"
        "Ferraz liderou o time. Mariana também.\nTrabalhou na Ferraz Engenharia.\n"
        "Falar com Ferraz, por favor.\nAtenciosamente, Mariana C. Ferraz\n"
    )
    resultado = anonimizar(texto)
    assert "[NOME] liderou o time. [NOME] também." in resultado.texto
    assert "Falar com [NOME], por favor." in resultado.texto
    assert "Ferraz Engenharia" in resultado.texto  # nome de empresa: fica (vazamento aceito)
    assert "Atenciosamente, [NOME]\n" in resultado.texto  # assinatura com inicial


@pytest.mark.parametrize(
    ("nome", "corpo"),
    [
        (
            "Julia Martins",
            "Modelos estatísticos em Julia e Python. Julia é minha linguagem em HPC.",
        ),
        (
            "Paulo Henrique Costa",
            "Analista na filial de São Paulo. Atendi clientes em Paulo Afonso (BA).",
        ),
        ("Rosa Almeida", "Gerente de loja na Rosa Chá por 4 anos. Rosa Chá Moda Praia."),
        ("Ruby Fernandes", "Desenvolvedora Ruby on Rails. Ruby e Elixir em produção."),
        ("Mercedes Ramos", "Mecânica na concessionária Mercedes-Benz. Frota Mercedes."),
        ("Victor Hugo Natal", "Atuei em Natal (RN), em Natal, RN e no hospital de Natal."),
        ("Caio Oracle Souza", "Administrador de banco Oracle há 6 anos."),
        ("Ana Go", "Microsserviços em Go e Kubernetes."),
        ("Diego Santander Rocha", "Analista de crédito no Banco Santander."),
        ("Maria Itaú Lima", "Analista no Itaú Unibanco e depois no Itaú."),
    ],
)
def test_regressao_do_validador_nome_nao_apaga_evidencia(nome: str, corpo: str) -> None:
    """nome_regressao.py da rodada 2: nenhuma competência, cidade ou empresa apagada, e o nome
    do cabeçalho sai."""
    resultado = anonimizar(f"{nome}\nmail@example.com\n\n## Experiência\n{corpo}\n")
    assert resultado.texto.endswith(corpo + "\n")
    assert resultado.texto.startswith("[NOME]\n")


def test_sequencia_do_nome_nao_atravessa_linhas() -> None:
    texto = "# Ana Lima\n\n## Resumo\n\nAna\nLima\nPython e SQL.\n" + "Linha comum.\n" * 50
    resultado = anonimizar(texto)
    assert resultado.texto.count("\n") == texto.count("\n")
    assert "Linha comum." in resultado.texto


@pytest.mark.parametrize(
    "topo",
    [
        "Product Owner",
        "Marketing Digital",
        "Tech Lead",
        "Desenvolvedora Front-end Sênior",
        "Python Django",
    ],
)
def test_cargo_no_topo_nao_vira_nome(topo: str) -> None:
    texto = (
        f"{topo}\n\n## Experiência\n\n{topo} — Empresa Fictícia — 2020 – atual\n"
        "- Liderei o roadmap de Marketing Digital com Python.\n"
    )
    resultado = anonimizar(texto)
    assert not resultado.nome_encontrado
    assert resultado.texto == texto


def test_sem_nome_a_ingestao_avisa() -> None:
    from curriculo_api.ingestao import ingerir_curriculo

    ingerido = ingerir_curriculo(texto="Tech Lead\n\n## Resumo\n\nPython.\n")
    assert [a.tipo for a in ingerido.alertas] == ["nome_nao_identificado"]


def test_vazamentos_no_corpo_do_validador() -> None:
    texto = (
        "# Beatriz da Conceição de Souza\n\n"
        "bia.souza@example.com · +351 912 345 678 · Rua das Flores 120 apto 3, Lapa, São Paulo\n\n"
        "## Resumo\n\n"
        "Sou mãe de dois filhos, casada, tenho 45 anos e nasci em 3 de março de 1980. Sra. Souza.\n"
        "Nascida em 3 de março de 1980.\n"
        "Moro na Rua Augusta, 1500, Consolação, 01305-100.\n"
        "CPF 123 456 789 09. Telefone 3456-7890 ramal 22.\n"
        "linkedin.com/in/beatriz-souza-123 e https://bia-souza.dev\n"
        "Apelido: Bia.\n\n"
        "## Experiência\n\n"
        "Desenvolvedora Ruby — Souza & Filhos Ltda — 2015 – 2020\n"
        "- 5 anos de experiência com Ruby on Rails.\n\n"
        "Atenciosamente, Beatriz C. Souza\n"
    )
    resultado = anonimizar(texto)
    for vazado in (
        "Beatriz",
        "Souza",
        "Bia",
        "mãe de",
        "casada",
        "45 anos",
        "1980",
        "Sra",
        "Augusta",
        "Lapa",
        "São Paulo",
        "01305",
        "456 789",
        "3456",
        "linkedin",
        "bia-souza",
    ):
        assert vazado not in resultado.texto, vazado
    assert "5 anos de experiência com Ruby on Rails." in resultado.texto
    assert "Desenvolvedora Ruby — [NOME] & Filhos Ltda — 2015 – 2020" in resultado.texto


@pytest.mark.parametrize(
    "nome",
    [
        "Nguyễn Thị Lan",
        "Thiago Ślusarczyk",
        "Oluwaseun Adeyemi",
        "Muhammad Al-Farouq",
        "Zhang Wei",
        "Seán O'Connor",
        "JORGE BATISTA NUNES",
    ],
)
def test_nomes_fora_do_latin1_e_em_maiusculas(nome: str) -> None:
    partes = nome.split()
    texto = (
        f"{nome}\n\nlan@example.com\n\n## Experiência\n\n"
        f"{partes[-1]} coordenou a equipe. {partes[0]} liderou projetos em Go.\n"
    )
    resultado = anonimizar(texto)
    assert resultado.nome_encontrado
    for parte in partes:
        assert parte not in resultado.texto, parte
    assert "[NOME] coordenou a equipe. [NOME] liderou projetos em Go." in resultado.texto


MODELO_CONTRAFACTUAL = """{nome}

{email} · (00) 90000-0101 · Curitiba – PR
{extra}

## Resumo profissional

Analista de dados. {primeiro} lidera o time de BI.

## Experiência

Analista de Dados — Mercado Fictício — fev/2023 – atual
- Escrevo consultas SQL. Indicação: falar com {sobrenome} na equipe.
"""

PRIMEIROS = ["Renata", "Jorge", "Lan", "Oluwaseun", "María", "Kauã", "Wei", "Agnieszka", "Fatima"]
SOBRENOMES = [
    "Prado",
    "Nunes",
    "Nguyễn",
    "Adeyemi",
    "Fernández",
    "Santos",
    "Zhang",
    "Ślusarczyk",
    "Haddad",
    "Lima",
]
EXTRAS = [
    "Nascimento: 17/06/1997 · Sexo: feminino",
    "Data de nascimento: 25/01/1968 · Sexo: masculino",
    "Idade: 52 anos · Gênero: masculino",
    "52 anos · Casada",
    "Nascida em 02/02/1960",
    "Homem, 61 anos",
    "Masculino · 34 anos",
    "Sexo: M",
]


@settings(max_examples=150, deadline=None)
@given(
    st.sampled_from(PRIMEIROS),
    st.lists(st.sampled_from(SOBRENOMES), min_size=1, max_size=3, unique=True),
    st.sampled_from(EXTRAS),
)
def test_mesmo_corpo_com_identidades_diferentes_da_o_mesmo_texto(
    primeiro: str, sobrenomes: list[str], extra: str
) -> None:
    def texto(p: str, s: list[str], e: str) -> str:
        nome = " ".join([p, *s])
        return MODELO_CONTRAFACTUAL.format(
            nome=nome,
            email=f"{sem_acentos(p).lower()}@example.com",
            extra=e,
            primeiro=p,
            sobrenome=s[-1],
        )

    referencia = anonimizar(texto("Renata", ["Okumura", "Prado"], EXTRAS[0])).texto
    assert anonimizar(texto(primeiro, sobrenomes, extra)).texto == referencia


@pytest.mark.parametrize(
    "nome",
    [
        "Maria José da Conceição",
        "Ana-Clara D'Ávila dos Santos",
        "Pedro de Alcântara João Carlos Leopoldo Salvador Bibiano Francisco Xavier de Paula",
        "JOÃO PEDRO SILVA NETO",
        "Kauane Silva dos Santos",
    ],
)
def test_nomes_compostos_e_longos(nome: str) -> None:
    texto = f"# {nome}\n\n{nome.lower().split()[0]}@example.com\n\n## Resumo\n\nPython.\n"
    resultado = anonimizar(texto)
    assert resultado.texto == "# [NOME]\n\n[DADOS_PESSOAIS]\n\n## Resumo\n\nPython.\n"


def test_curriculo_em_ingles() -> None:
    texto = (
        "Daniel Okafor Mendes\n"
        "daniel@example.com | +1 (555) 010-0199 | Austin, TX\n"
        "Date of birth: March 3, 1990 | Gender: male | Marital status: married\n"
        "linkedin.com/in/daniel-okafor | github.com/dokafor\n\n"
        "Summary\nBackend developer, 8 years of experience. Daniel led the API team.\n"
    )
    resultado = anonimizar(texto)
    assert resultado.texto.split("\n")[0] == "[NOME]"
    for valor in ("daniel@", "555", "March 3", "male", "married", "linkedin", "github", "Daniel"):
        assert valor not in resultado.texto, valor
    assert "8 years of experience" in resultado.texto
    assert "[NOME] led the API team." in resultado.texto


def test_nome_de_empresa_e_tecnologia_nao_vira_nome() -> None:
    texto = "Desenvolvedora Front-end Sênior\n\n## Resumo\n\nReact e Node na Empresa Fictícia.\n"
    resultado = anonimizar(texto)
    assert not resultado.nome_encontrado
    assert resultado.texto == texto


def test_campo_nome_rotulado() -> None:
    texto = (
        "Currículo\nNome: Joana Prado Lins\nE-mail: joana@example.com\n\n## Resumo\n\n"
        "Joana é analista.\n"
    )
    resultado = anonimizar(texto)
    assert "Joana" not in resultado.texto and "Lins" not in resultado.texto
    assert "[NOME] é analista." in resultado.texto


def test_outros_campos() -> None:
    texto = (
        "Fulano Beltrano Ciclano\n"
        "RG: 12.345.678-9 SSP/SP · CEP 01234-567 · Bairro: Jardim Fictício\n"
        "Nacionalidade: brasileira · Idade: 41 anos · 41 anos · solteiro\n"
        "Portfólio: https://fulanobeltrano.example.com/projetos\n\n"
        "## Resumo\n\nVer também https://empresa.example.com/case (site da empresa).\n"
    )
    resultado = anonimizar(texto)
    for valor in ("12.345.678", "01234-567", "Jardim", "brasileira", "41", "solteiro", "fulanob"):
        assert valor not in resultado.texto, valor
    assert "https://empresa.example.com/case" in resultado.texto  # link sem nome fica


def test_foto_entra_na_lista() -> None:
    resultado = anonimizar("Fulano Beltrano\n\n## Resumo\n\nPython.\n", imagens=2)
    assert [(r.tipo, r.valor) for r in resultado.do_tipo("foto")] == [
        ("foto", "2 imagens descartadas")
    ]


def test_mascaras() -> None:
    assert mascarar("email", "mariana.ferraz@example.com") == "m•••@•••.com"
    assert mascarar("nome", "Mariana Couto") == "M••• C•••"
    assert mascarar("cpf", "318.742.596-10") == "•••10"


def test_repr_nao_mostra_o_valor() -> None:
    resultado = anonimizar("Mariana Couto Ferraz\nmariana@example.com\n\n## Resumo\n\nPython.\n")
    assert "Mariana" not in repr(resultado) and "mariana@" not in repr(resultado.removidos)


# --- padrões (hypothesis) ---------------------------------------------------------------------

CORPO_SIMPLES = "Fulano Beltrano\n\n## Resumo\n\nContato: {}\nPython e SQL.\n"


def _cpf(digitos: list[int], valido: bool) -> str:
    base = digitos[:9]
    for tamanho in (9, 10):
        soma = sum(d * p for d, p in zip(base, range(tamanho + 1, 1, -1), strict=False))
        base.append((soma * 10) % 11 % 10)
    if not valido:
        base[10] = (base[10] + 1) % 10
    return "".join(map(str, base))


@settings(max_examples=200, deadline=None)
@given(
    st.lists(st.integers(0, 9), min_size=9, max_size=9),
    st.booleans(),
    st.sampled_from(
        ["{a}.{b}.{c}-{d}", "{a}{b}{c}{d}", "CPF {a}{b}{c}{d}", "CPF: {a}.{b}.{c} - {d}"]
    ),
)
def test_cpf_com_ou_sem_pontuacao_valido_ou_nao(
    digitos: list[int], valido: bool, formato: str
) -> None:
    cpf = _cpf(digitos, valido)
    escrito = formato.format(a=cpf[:3], b=cpf[3:6], c=cpf[6:9], d=cpf[9:])
    resultado = anonimizar(CORPO_SIMPLES.format(escrito))
    assert cpf[:3] + "." not in resultado.texto and cpf not in resultado.texto
    assert re.sub(r"\D", "", escrito) not in re.sub(r"\D", "", resultado.texto)


@settings(max_examples=200, deadline=None)
@given(
    st.from_regex(r"[1-9]{2}", fullmatch=True),
    st.from_regex(r"9[0-9]{4}", fullmatch=True),
    st.from_regex(r"[0-9]{4}", fullmatch=True),
    st.sampled_from(
        [
            "({ddd}) {p}-{s}",
            "+55 ({ddd}) {p}-{s}",
            "+55 {ddd} {p} {s}",
            "{ddd} {p}-{s}",
            "Tel: {ddd}{p}{s}",
            "Celular: ({ddd}) {p}{s}",
            "({ddd}){p}-{s}",
        ]
    ),
)
def test_telefones(ddd: str, primeira: str, segunda: str, formato: str) -> None:
    escrito = formato.format(ddd=ddd, p=primeira, s=segunda)
    resultado = anonimizar(CORPO_SIMPLES.format(escrito))
    assert primeira not in resultado.texto and segunda not in resultado.texto.replace("SQL", "")


@settings(max_examples=200, deadline=None)
@given(
    st.from_regex(r"[a-z][a-z0-9._+-]{0,20}[a-z0-9]", fullmatch=True),
    st.from_regex(r"[a-z][a-z0-9-]{1,15}(\.[a-z]{2,6}){1,2}", fullmatch=True),
)
def test_emails(usuario: str, dominio: str) -> None:
    email = f"{usuario}@{dominio}"
    resultado = anonimizar(CORPO_SIMPLES.format(email))
    assert email not in resultado.texto and "@" not in resultado.texto


def test_datas_de_emprego_e_anos_de_experiencia_ficam() -> None:
    corpo = (
        "Fulano Beltrano\n\n## Experiência\n\nAnalista — Empresa — 03/2019 – 12/2022\n"
        "- 10 anos de experiência em vendas; equipe de 12 pessoas desde 2015.\n"
        "- Pedido nº 2019-2022 entregue em 15/03/2021.\n"
    )
    resultado = anonimizar(corpo)
    assert resultado.texto.split("\n", 1)[1] == corpo.split("\n", 1)[1]


@st.composite
def nome_ficticio(draw: st.DrawFn) -> str:
    silabas = st.sampled_from(["ma", "ri", "an", "lu", "ca", "jo", "re", "ta", "ne", "so", "vi"])
    partes = [
        "".join(draw(st.lists(silabas, min_size=2, max_size=4))).capitalize()
        for _ in range(draw(st.integers(2, 5)))
    ]
    return " ".join(partes)


@settings(max_examples=100, deadline=None)
@given(nome_ficticio(), st.data())
def test_anonimizacao_nao_apaga_competencias_da_taxonomia(
    taxonomia: Taxonomia, nome: str, dados: st.DataObject
) -> None:
    termos = sorted({t for e in taxonomia.arquivo.competencias for t in (e.canonica, *e.sinonimos)})
    escolhidos = dados.draw(st.lists(st.sampled_from(termos), min_size=5, max_size=25, unique=True))
    linhas = "\n".join(f"- Uso de {t} em produção." for t in escolhidos)
    texto = f"# {nome}\n\n{nome.split()[0].lower()}@example.com\n\n## Competências\n\n{linhas}\n"
    resultado = anonimizar(texto)
    for termo in escolhidos:
        assert f"- Uso de {termo} em produção." in resultado.texto, termo
    for parte in nome.split():
        assert parte not in resultado.texto


def test_pessoa_com_nome_de_tecnologia() -> None:
    """Partes do nome que são termo da taxonomia só saem junto com outra parte do nome."""
    assert "oracle" in palavras_da_taxonomia()
    texto = "# Oracle Rocha Lins\n\n## Resumo\n\nOracle Rocha criou APIs em Oracle e Python.\n"
    resultado = anonimizar(texto)
    assert "[NOME] criou APIs em Oracle e Python." in resultado.texto


# --- logs -------------------------------------------------------------------------------------


def test_logs_da_ingestao_nao_tem_dado_pessoal(
    dataset: Dataset, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    for caso in dataset.casos:
        ingerir_caso(caso)
    assert caplog.records, "a ingestão deveria registrar metadados"
    saida = "\n".join(
        [r.getMessage() for r in caplog.records]
        + [str(v) for r in caplog.records for v in r.__dict__.values()]
    )
    for caso in dataset.casos:
        for dado in caso.esperado.dados_pessoais:
            assert dado.valor not in saida, (caso.id, dado.tipo)
        for parte in _partes_do_nome(caso):
            assert parte not in saida, (caso.id, "parte do nome")
        if caso.esperado.injecao is not None:
            assert caso.esperado.injecao.trecho not in saida


def test_logs_sem_conteudo_mesmo_com_marcador_unico(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    marcador = "ZXQ-MARCADOR-UNICO-7731"
    ingerir_curriculo(texto=f"Fulano {marcador}\n\n## Resumo\n\n{marcador} em Python.\n")
    assert all(
        marcador not in r.getMessage() and marcador not in str(r.__dict__) for r in caplog.records
    )
