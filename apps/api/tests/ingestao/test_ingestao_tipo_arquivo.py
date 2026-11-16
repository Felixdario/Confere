"""Tipo real por assinatura de bytes, extensão que não bate, zip bomb, vazio e limites."""

import io
import time
import zipfile

import pytest

from curriculo_api.evals.fixtures import Linha, Paragrafo, Trecho, docx_de_paragrafos, pdf_de_linhas
from curriculo_api.ingestao import ler_arquivo
from curriculo_api.ingestao.erros import (
    ArquivoCorrompido,
    ArquivoGrande,
    ArquivoVazio,
    DocxComMacro,
    ErroIngestao,
    ExtensaoNaoConfere,
    TextoGrande,
    TipoNaoSuportado,
    ZipSuspeito,
)
from curriculo_api.ingestao.modelos import Limites
from curriculo_api.ingestao.tipo_arquivo import detectar_tipo


@pytest.fixture(scope="module")
def pdf() -> bytes:
    return pdf_de_linhas([[Linha([Trecho("Currículo em PDF com texto.")])]])


@pytest.fixture(scope="module")
def docx() -> bytes:
    return docx_de_paragrafos([Paragrafo("Currículo em DOCX com texto.")])


def test_pdf_e_docx_pela_assinatura(pdf: bytes, docx: bytes) -> None:
    assert detectar_tipo(pdf, "cv.pdf") == "pdf"
    assert detectar_tipo(docx, "cv.docx") == "docx"
    assert detectar_tipo(pdf) == "pdf"  # sem nome também vale
    assert detectar_tipo(docx, "CV.DOCX") == "docx"


def test_lixo_antes_do_cabecalho_do_pdf_e_tolerado(pdf: bytes) -> None:
    assert detectar_tipo(b"\n\n  " + pdf, "cv.pdf") == "pdf"


def test_pdf_renomeado_para_docx(pdf: bytes) -> None:
    with pytest.raises(ExtensaoNaoConfere, match=r"extensão \.docx, mas o conteúdo é PDF"):
        ler_arquivo(pdf, "curriculo.docx")


def test_docx_renomeado_para_pdf(docx: bytes) -> None:
    with pytest.raises(ExtensaoNaoConfere, match=r"extensão \.pdf, mas o conteúdo é DOCX"):
        ler_arquivo(docx, "curriculo.pdf")


def test_extensao_estranha_e_recusada(pdf: bytes) -> None:
    with pytest.raises(ExtensaoNaoConfere, match=r"\.txt"):
        detectar_tipo(pdf, "curriculo.txt")


@pytest.mark.parametrize("conteudo", [b"", b"   \n\t  "])
def test_arquivo_vazio(conteudo: bytes) -> None:
    with pytest.raises(ArquivoVazio, match="vazio"):
        ler_arquivo(conteudo, "cv.pdf")


def test_arquivo_grande(pdf: bytes) -> None:
    with pytest.raises(ArquivoGrande, match="limite de 1 MB"):
        detectar_tipo(pdf + b"0" * (1024 * 1024), "cv.pdf", Limites(tamanho_max_bytes=1024 * 1024))


def test_doc_antigo_tem_mensagem_propria() -> None:
    with pytest.raises(TipoNaoSuportado, match=r"\.doc antigos"):
        detectar_tipo(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 100, "cv.doc")


@pytest.mark.parametrize("conteudo", [b"GIF89a....", b"texto puro qualquer", b"\x89PNG\r\n\x1a\n"])
def test_formato_desconhecido(conteudo: bytes) -> None:
    with pytest.raises(TipoNaoSuportado, match="PDF ou DOCX"):
        detectar_tipo(conteudo)


def _zip(entradas: dict[str, bytes]) -> bytes:
    saida = io.BytesIO()
    with zipfile.ZipFile(saida, "w", zipfile.ZIP_DEFLATED) as z:
        for nome, dados in entradas.items():
            z.writestr(nome, dados)
    return saida.getvalue()


def test_zip_que_nao_e_docx() -> None:
    with pytest.raises(TipoNaoSuportado, match="não é um documento do Word"):
        detectar_tipo(_zip({"leia.txt": b"oi"}), "cv.docx")


def test_zip_bomb_pelo_tamanho_descompactado() -> None:
    bomba = _zip(
        {
            "[Content_Types].xml": b"<x/>",
            "word/document.xml": b"<x/>",
            "word/media/enchimento.bin": b"\0" * (5 * 1024 * 1024),
        }
    )
    assert len(bomba) < 64 * 1024  # comprime ~1000×
    with pytest.raises(ZipSuspeito, match="grande demais"):
        detectar_tipo(bomba, "cv.docx", Limites(descompactado_max_bytes=4 * 1024 * 1024))


def test_zip_bomb_com_tamanho_declarado_mentiroso() -> None:
    """O cabeçalho diz 10 bytes; a descompactação real conta e para no limite."""
    bomba = bytearray(
        _zip(
            {
                "[Content_Types].xml": b"<x/>",
                "word/document.xml": b"<x/>",
                "word/media/a.bin": b"\0" * (3 * 1024 * 1024),
            }
        )
    )
    with zipfile.ZipFile(io.BytesIO(bytes(bomba))) as z:
        info = z.getinfo("word/media/a.bin")
    # Reescreve o tamanho descompactado no diretório central e no cabeçalho local.
    tamanho = (3 * 1024 * 1024).to_bytes(4, "little")
    mentira = (10).to_bytes(4, "little")
    conteudo = bytes(bomba).replace(tamanho, mentira)
    assert info.file_size == 3 * 1024 * 1024
    with pytest.raises((ZipSuspeito, ArquivoCorrompido)):
        detectar_tipo(conteudo, "cv.docx", Limites(descompactado_max_bytes=1024 * 1024))


def test_zip_com_entradas_demais() -> None:
    entradas = {"[Content_Types].xml": b"<x/>", "word/document.xml": b"<x/>"}
    entradas |= {f"word/parte{i}.xml": b"<x/>" for i in range(30)}
    with pytest.raises(ZipSuspeito):
        detectar_tipo(_zip(entradas), "cv.docx", Limites(entradas_zip_max=20))


def test_docx_corrompido() -> None:
    with pytest.raises(ArquivoCorrompido, match="DOCX"):
        detectar_tipo(b"PK\x03\x04" + b"\x00" * 200, "cv.docx")


def test_mensagens_nao_citam_o_nome_do_arquivo(pdf: bytes) -> None:
    nome = "Mariana_Couto_Ferraz_CPF_318.docx"
    with pytest.raises(ErroIngestao) as erro:
        ler_arquivo(pdf, nome)
    assert "Mariana" not in erro.value.mensagem and "318" not in erro.value.mensagem
    assert erro.value.codigo == "extensao_nao_confere"


# --- rodada 1 do Validador ---------------------------------------------------------------------


def _reempacotar(
    docx: bytes, mudar: dict[str, bytes], extra: dict[str, bytes] | None = None
) -> bytes:
    entrada = zipfile.ZipFile(io.BytesIO(docx))
    saida = io.BytesIO()
    with zipfile.ZipFile(saida, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for info in entrada.infolist():
            z.writestr(info.filename, mudar.get(info.filename, entrada.read(info.filename)))
        for nome, dados in (extra or {}).items():
            z.writestr(nome, dados)
    return saida.getvalue()


def test_docm_renomeado_tem_mensagem_propria(docx: bytes) -> None:
    tipos = (
        zipfile.ZipFile(io.BytesIO(docx))
        .read("[Content_Types].xml")
        .replace(b"wordprocessingml.document.main+xml", b"ms-word.document.macroEnabled.main+xml")
    )
    conteudo = _reempacotar(
        docx,
        {"[Content_Types].xml": tipos},
        {"word/vbaProject.bin": b"\xd0\xcf\x11\xe0" + b"\0" * 64},
    )
    with pytest.raises(DocxComMacro, match=r"DOCX com macro \(\.docm\) não é aceito"):
        ler_arquivo(conteudo, "cv.docx")


def test_document_xml_gigante_e_recusado_sem_ler(docx: bytes) -> None:
    """O DOCX de 25 MB de XML do Validador levava 127 s; agora sai pelo limite do document.xml."""
    original = zipfile.ZipFile(io.BytesIO(docx)).read("word/document.xml")
    corpo = b"<w:p><w:r><w:t>Python SQL</w:t></w:r></w:p>" * 200_000
    conteudo = _reempacotar(
        docx, {"word/document.xml": original.replace(b"<w:body>", b"<w:body>" + corpo, 1)}
    )
    inicio = time.perf_counter()
    with pytest.raises(TextoGrande):
        ler_arquivo(conteudo, "cv.docx", Limites(documento_xml_max_bytes=1024 * 1024))
    assert time.perf_counter() - inicio < 2


def test_texto_do_docx_acima_do_teto_e_recusado() -> None:
    conteudo = docx_de_paragrafos([Paragrafo("Python e SQL em produção. " * 40)] * 20)
    with pytest.raises(TextoGrande, match="limite de 5000 caracteres"):
        ler_arquivo(conteudo, "cv.docx", Limites(texto_max_caracteres=5000))


def test_texto_do_pdf_acima_do_teto_e_recusado() -> None:
    linhas = [[Linha([Trecho("Python e SQL em produção, " * 3)]) for _ in range(40)]] * 3
    with pytest.raises(TextoGrande):
        ler_arquivo(pdf_de_linhas(linhas), "cv.pdf", Limites(texto_max_caracteres=2000))


@pytest.mark.parametrize(
    "conteudo",
    [
        b"%PDF-1.7\n1 0 obj << /Segredo (Mariana Couto Ferraz 318.742.596-10) >> endobj",
        b"PK\x03\x04Mariana Couto Ferraz 318.742.596-10" + b"\x00" * 50,
    ],
)
def test_erro_publico_nao_carrega_conteudo(conteudo: bytes) -> None:
    with pytest.raises(ErroIngestao) as erro:
        ler_arquivo(conteudo)
    publico = str(erro.value) + repr(erro.value) + str(erro.value.__cause__ or "")
    assert "Mariana" not in publico and "318" not in publico
    assert erro.value.__cause__ is None
