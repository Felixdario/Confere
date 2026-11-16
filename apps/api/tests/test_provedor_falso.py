from pathlib import Path

import pytest
from pydantic import SecretStr

from curriculo_api.config import Settings
from curriculo_api.evals.dataset import Dataset
from curriculo_api.evals.gravacoes import desatualizadas, gerar_gravacao, serializar
from curriculo_api.evals.pipeline import ingerir_caso
from curriculo_api.ia import (
    GravacaoAusente,
    ProvedorFalso,
    ProvedorIA,
    ProvedorIndisponivel,
    TextoAnonimizado,
    criar_provedor,
)
from curriculo_api.ia.falso import Gravacao
from curriculo_api.ia.modelos import FeedbackIA, TabelaDaNota


@pytest.fixture(scope="module")
def provedor(raiz: Path) -> ProvedorFalso:
    return ProvedorFalso(raiz / "evals" / "gravacoes")


def test_cumpre_o_protocolo(provedor: ProvedorFalso) -> None:
    alvo: ProvedorIA = provedor
    assert isinstance(alvo, ProvedorIA)
    assert alvo.nome == "falso"


def test_toda_gravacao_valida_contra_o_schema_atual(raiz: Path) -> None:
    arquivos = sorted((raiz / "evals" / "gravacoes").glob("*.json"))
    assert len(arquivos) == 30
    for arquivo in arquivos:
        Gravacao.model_validate_json(arquivo.read_text(encoding="utf-8"))


def test_gravacoes_em_dia_com_as_anotacoes(dataset: Dataset, raiz: Path) -> None:
    problemas = desatualizadas(dataset, raiz / "evals" / "gravacoes")
    assert not problemas, "rode `make gravacoes`: " + ", ".join(problemas)


async def test_responde_pelo_hash_do_texto_anonimizado(
    provedor: ProvedorFalso, dataset: Dataset
) -> None:
    for caso in dataset.casos:
        gravada = gerar_gravacao(caso)
        curriculo, vaga_ingerida = ingerir_caso(caso)
        cv = await provedor.extrair_curriculo(curriculo.texto_para_ia)
        vaga = await provedor.extrair_vaga(vaga_ingerida.texto)
        assert cv.saida == gravada.extrair_curriculo.saida
        assert vaga.saida == gravada.extrair_vaga.saida
        assert all(u.custo_usd == 0 and u.input_tokens == 0 for u in (*cv.usos, *vaga.usos))


async def test_crlf_da_o_mesmo_resultado(provedor: ProvedorFalso, dataset: Dataset) -> None:
    caso = dataset.casos[0]
    texto = ingerir_caso(caso)[0].texto_para_ia
    cv = await provedor.extrair_curriculo(TextoAnonimizado(texto.replace("\n", "\r\n")))
    assert cv.saida == gerar_gravacao(caso).extrair_curriculo.saida


async def test_texto_bruto_com_dados_pessoais_nao_tem_gravacao(
    provedor: ProvedorFalso, dataset: Dataset
) -> None:
    """As gravações são indexadas pelo texto anonimizado: o bruto não tem resposta."""
    with pytest.raises(GravacaoAusente):
        await provedor.extrair_curriculo(TextoAnonimizado(dataset.casos[0].curriculo))


async def test_texto_desconhecido_nao_tem_gravacao(provedor: ProvedorFalso) -> None:
    with pytest.raises(GravacaoAusente, match="sha256"):
        await provedor.extrair_curriculo(TextoAnonimizado("currículo que ninguém gravou"))


async def test_feedback_gravado_sai_em_eventos(provedor: ProvedorFalso, dataset: Dataset) -> None:
    caso = dataset.casos[0]
    gravada = gerar_gravacao(caso)
    texto = ingerir_caso(caso)[0].texto_para_ia
    eventos = [
        e
        async for e in provedor.escrever_feedback(
            TabelaDaNota(nota=50),
            gravada.extrair_curriculo.saida,
            gravada.extrair_vaga.saida,
            texto,
        )
    ]
    assert eventos[0].tipo == "etapa" and eventos[-1].tipo == "final"
    textos = [e.texto for e in eventos if e.tipo == "texto"]
    assert len(textos) > 1  # simula o streaming em pedaços
    final = eventos[-1].feedback
    assert final == gravada.escrever_feedback.saida
    assert FeedbackIA.model_validate_json("".join(textos)) == final


async def test_feedback_sem_gravacao(provedor: ProvedorFalso, dataset: Dataset) -> None:
    gravada = gerar_gravacao(dataset.casos[0])
    eventos = provedor.escrever_feedback(
        TabelaDaNota(nota=50),
        gravada.extrair_curriculo.saida,
        gravada.extrair_vaga.saida,
        TextoAnonimizado("currículo que ninguém gravou"),
    )
    with pytest.raises(GravacaoAusente, match="feedback"):
        await anext(eventos)


def test_gravacoes_conflitantes_sao_recusadas(dataset: Dataset, tmp_path: Path) -> None:
    caso = dataset.casos[0]
    gravacao = gerar_gravacao(caso)
    (tmp_path / f"{caso.id}.json").write_text(serializar(gravacao), encoding="utf-8")
    outra = gravacao.model_copy(update={"id": "copia"})
    vaga = outra.extrair_vaga.saida.model_copy(update={"titulo": "Outra"})
    outra = outra.model_copy(
        update={"extrair_vaga": outra.extrair_vaga.model_copy(update={"saida": vaga})}
    )
    (tmp_path / "copia.json").write_text(serializar(outra), encoding="utf-8")
    with pytest.raises(ValueError, match="conflitantes"):
        ProvedorFalso(tmp_path)


def test_provedor_real_sem_chave_e_indisponivel(tmp_path: Path) -> None:
    for chave in (None, ""):
        settings = Settings(anthropic_api_key=None if chave is None else SecretStr(chave))
        with pytest.raises(ProvedorIndisponivel, match="ANTHROPIC_API_KEY"):
            criar_provedor("anthropic", pasta_gravacoes=tmp_path, settings=settings)
