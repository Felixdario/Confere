"""Integração com as evals: os arquivos reais dos casos estão em dia e o texto oculto deles não
chega ao texto analisado."""

from pathlib import Path

from curriculo_api.evals import fixtures
from curriculo_api.evals.dataset import Dataset, sem_injecao
from curriculo_api.evals.pipeline import ingerir_caso


def test_arquivos_reais_em_dia(raiz: Path) -> None:
    problemas = fixtures.desatualizadas(raiz)
    assert not problemas, "rode `make fixtures` e `make gravacoes`: " + ", ".join(problemas)


def test_casos_com_arquivo_real(dataset: Dataset) -> None:
    com_arquivo = {c.id: c.arquivo.suffix for c in dataset.casos if c.arquivo is not None}
    assert com_arquivo == {
        "b13-ml-senior-en": ".pdf",
        "b14-java-para-front-end": ".pdf",
        "b16-administrativo-sem-desejaveis": ".docx",
        "i05-oculta-en-instrucao": ".pdf",
        "i06-oculta-palavras-chave": ".pdf",
    }


def test_injecao_oculta_cobre_branco_1pt_e_fora_da_pagina(dataset: Dataset) -> None:
    motivos: set[str] = set()
    for caso in dataset.do_tipo("injection"):
        injecao = caso.esperado.injecao
        assert injecao is not None
        if not injecao.oculta:
            continue
        ingerido = ingerir_caso(caso)[0]
        motivos |= {o.motivo for o in ingerido.documento.ocultos}
        palavras_ocultas = " ".join(o.texto for o in ingerido.documento.ocultos).split()
        assert sorted(palavras_ocultas) == sorted(injecao.trecho.split()), caso.id
        # Nada do trecho oculto chega ao texto analisado (nem à IA, nem à ancoragem).
        assert injecao.trecho not in ingerido.texto_para_ia
        palavras_analisadas = set(ingerido.texto_para_ia.split())
        so_do_oculto = set(injecao.trecho.split()) - set(
            sem_injecao(caso.curriculo, injecao).split()
        )
        assert not so_do_oculto & palavras_analisadas, caso.id
    assert motivos == {"cor_do_fundo", "fonte_minuscula", "fora_da_pagina"}


def test_variante_oculta_e_o_par_base_viram_o_mesmo_texto(dataset: Dataset) -> None:
    """Sem o texto oculto, o PDF do i05 é o do b13 (e o do i06, o do b14)."""
    por_id = dataset.por_id()
    for variante, base in (
        ("i05-oculta-en-instrucao", "b13-ml-senior-en"),
        ("i06-oculta-palavras-chave", "b14-java-para-front-end"),
    ):
        texto_variante = ingerir_caso(por_id[variante])[0].texto_para_ia
        texto_base = ingerir_caso(por_id[base])[0].texto_para_ia
        assert texto_variante == texto_base, variante
