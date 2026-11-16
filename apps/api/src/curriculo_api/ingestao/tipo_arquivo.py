"""Tipo real do arquivo por assinatura de bytes (ADR 0004). O `Content-Type` do cliente é ignorado;
a extensão, se vier, precisa bater com o conteúdo (um .pdf que é DOCX é recusado com mensagem
clara, em vez de ser lido em silêncio)."""

from __future__ import annotations

import io
import zipfile
import zlib
from pathlib import PurePath
from typing import Literal

from curriculo_api.ingestao.erros import (
    ArquivoCorrompido,
    ArquivoGrande,
    ArquivoVazio,
    DocxComMacro,
    ExtensaoNaoConfere,
    TextoGrande,
    TipoNaoSuportado,
    ZipSuspeito,
)
from curriculo_api.ingestao.modelos import Limites

TipoArquivo = Literal["pdf", "docx"]

ASSINATURA_PDF = b"%PDF-"
ASSINATURA_ZIP = b"PK\x03\x04"
ASSINATURA_OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # .doc antigo (Word 97–2003)
PARTES_DOCX = ("[Content_Types].xml", "word/document.xml")
_EXTENSOES: dict[str, TipoArquivo] = {"pdf": "pdf", "docx": "docx"}
_BLOCO = 64 * 1024


def _extensao(nome: str | None) -> str | None:
    if not nome:
        return None
    sufixo = PurePath(nome).suffix.lower().lstrip(".")
    return sufixo or None


def detectar_tipo(
    conteudo: bytes, nome: str | None = None, limites: Limites | None = None
) -> TipoArquivo:
    """Devolve "pdf" ou "docx", ou levanta um `ErroIngestao` com a mensagem para a pessoa."""
    limites = limites or Limites()
    if not conteudo or not conteudo.strip():
        raise ArquivoVazio
    if len(conteudo) > limites.tamanho_max_bytes:
        raise ArquivoGrande(limites.tamanho_max_bytes)

    tipo: TipoArquivo
    # A especificação tolera lixo antes do cabeçalho (até 1024 bytes); leitores reais também.
    if ASSINATURA_PDF in conteudo[:1024]:
        tipo = "pdf"
    elif conteudo.startswith(ASSINATURA_ZIP):
        verificar_docx(conteudo, limites)
        tipo = "docx"
    elif conteudo.startswith(ASSINATURA_OLE):
        raise TipoNaoSuportado("Arquivos .doc antigos não são aceitos: salve como .docx no Word.")
    else:
        raise TipoNaoSuportado

    extensao = _extensao(nome)
    if extensao is not None and extensao in _EXTENSOES and _EXTENSOES[extensao] != tipo:
        raise ExtensaoNaoConfere(extensao, tipo)
    if extensao is not None and extensao not in _EXTENSOES:
        raise ExtensaoNaoConfere(extensao, tipo)
    return tipo


def verificar_docx(conteudo: bytes, limites: Limites) -> None:
    """Confere que o zip é um DOCX e que não é uma zip bomb.

    Os tamanhos declarados no zip podem mentir; por isso, além de somá-los, descompacta cada
    entrada em blocos e para assim que o total real passar do limite (custo limitado ao limite).
    """
    try:
        arquivo = zipfile.ZipFile(io.BytesIO(conteudo))
    except (zipfile.BadZipFile, OSError):
        arquivo = None
    if arquivo is None:
        raise ArquivoCorrompido("docx") from None
    with arquivo:
        entradas = arquivo.infolist()
        nomes = {e.filename for e in entradas}
        if not all(parte in nomes for parte in PARTES_DOCX):
            raise TipoNaoSuportado("O arquivo é um ZIP, mas não é um documento do Word (DOCX).")
        if len(entradas) > limites.entradas_zip_max:
            raise ZipSuspeito
        if sum(e.file_size for e in entradas) > limites.descompactado_max_bytes:
            raise ZipSuspeito
        if any(e.flag_bits & 0x1 for e in entradas):
            raise TipoNaoSuportado("O DOCX está protegido por senha: salve uma cópia sem senha.")
        if _tem_macro(arquivo, nomes):
            raise DocxComMacro
        if arquivo.getinfo("word/document.xml").file_size > limites.documento_xml_max_bytes:
            raise TextoGrande(limites.texto_max_caracteres, arquivo=True)
        total = 0
        corrompido = False
        try:
            for entrada in entradas:
                da_entrada = 0
                with arquivo.open(entrada) as fluxo:
                    while bloco := fluxo.read(_BLOCO):
                        total += len(bloco)
                        da_entrada += len(bloco)
                        if total > limites.descompactado_max_bytes:
                            raise ZipSuspeito
                        if (
                            entrada.filename == "word/document.xml"
                            and da_entrada > limites.documento_xml_max_bytes
                        ):
                            raise TextoGrande(limites.texto_max_caracteres, arquivo=True)
        except (zipfile.BadZipFile, OSError, EOFError, NotImplementedError, zlib.error):
            corrompido = True
        if corrompido:
            raise ArquivoCorrompido("docx") from None


def _tem_macro(arquivo: zipfile.ZipFile, nomes: set[str]) -> bool:
    if any(n.lower().endswith("vbaproject.bin") for n in nomes):
        return True
    try:
        tipos = arquivo.read("[Content_Types].xml")[:200_000]
    except (KeyError, zipfile.BadZipFile, OSError, zlib.error):
        return False
    return b"macroEnabled" in tipos
