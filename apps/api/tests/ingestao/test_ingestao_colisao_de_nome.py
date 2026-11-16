"""Viés por colisão de nome (rodada 2 da fase 2): uma pessoa cujo nome coincide com uma competência,
cidade ou empresa do próprio currículo não pode perder evidência, e o texto que a IA vê não pode
mudar com o nome.

Para cada par-base, o corpo (sem o cabeçalho original) ganha um trecho sintético com Julia, Ruby on
Rails, São Paulo, Natal (RN), Rosa Chá e Banco Santander, e recebe cabeçalhos de várias
identidades: nomes que colidem com o texto (os da lista e a primeira palavra de cada empresa e cada
competência de uma palavra do gabarito) e nomes sem colisão. Afirma-se que (a) todo trecho do
gabarito e do trecho sintético continua no texto anonimizado e (b) o texto anonimizado é o mesmo
para todas as identidades (o cabeçalho tem o mesmo formato, então nem os marcadores mudam).
"""

import pytest

from curriculo_api.evals.dataset import Caso, Dataset, sem_cabecalho, trechos_do_esperado
from curriculo_api.ingestao import anonimizar
from curriculo_api.ingestao.anonimizacao import palavras_da_taxonomia, parece_nome

SINTETICO = [
    "Modelos estatísticos em Julia e Python.",
    "Manutenção de sistema em Ruby on Rails.",
    "Atendimento em São Paulo e em Natal (RN).",
    "Vitrine da Rosa Chá e integração com o Banco Santander.",
    "Frota Mercedes e conta no Itaú Unibanco.",
]
COLISOES_FIXAS = [
    "Julia",
    "Ruby",
    "Paulo",
    "Rosa",
    "Natal",
    "Santander",
    "Mercedes",
    "Victor Hugo",
    "Itaú",
]
SEM_COLISAO = ["Renata Okumura Prado", "Oluwaseun Adeyemi", "Nguyễn Thị Lan", "Kauã dos Santos"]
SOBRENOME = "Okonkwo"


def _corpo(caso: Caso) -> str:
    extra = "\n## Projetos\n\n" + "".join(f"- {linha}\n" for linha in SINTETICO)
    return sem_cabecalho(caso.curriculo).rstrip("\n") + "\n" + extra


def _colisoes(caso: Caso) -> list[str]:
    palavras = {e.empresa.split()[0] for e in caso.esperado.experiencias}
    palavras |= {c.nome for c in caso.esperado.competencias if len(c.nome.split()) == 1}
    palavras = {p for p in palavras if p[:1].isupper() and p.isalpha()}
    nomes = [f"{p} {SOBRENOME}" for p in sorted(palavras) + COLISOES_FIXAS]
    # "Projetos Okonkwo" ou "Logística Okonkwo" não passam por nome (palavra de cargo/área): a
    # anonimização não apaga nada por palpite, e o caso não é uma identidade plausível.
    return [n for n in nomes if parece_nome(n, palavras_da_taxonomia())]


def _texto(nome: str, corpo: str) -> str:
    return f"# {nome}\n\npessoa@example.com · (00) 90000-0000 · Curitiba – PR\n\n{corpo}"


def _bases(dataset: Dataset) -> list[Caso]:
    return dataset.do_tipo("base")


def test_ha_16_pares_base(dataset: Dataset) -> None:
    assert len(_bases(dataset)) == 16


@pytest.mark.parametrize("indice", range(16))
def test_colisao_de_nome_nao_apaga_evidencia_nem_muda_o_texto(
    dataset: Dataset, indice: int
) -> None:
    caso = _bases(dataset)[indice]
    corpo = _corpo(caso)
    referencia = anonimizar(_texto(SEM_COLISAO[0], corpo)).texto
    trechos = [*trechos_do_esperado(caso.esperado), *SINTETICO]
    for nome in [*SEM_COLISAO, *_colisoes(caso)]:
        resultado = anonimizar(_texto(nome, corpo))
        assert resultado.nome_encontrado, (caso.id, nome)
        perdidos = [t for t in trechos if t not in resultado.texto]
        assert not perdidos, (caso.id, nome, perdidos)
        assert resultado.texto == referencia, (caso.id, nome)
