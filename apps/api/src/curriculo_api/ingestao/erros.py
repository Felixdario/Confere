"""Erros da ingestão. A mensagem vai para a tela: é em pt-BR, diz o que fazer e nunca cita o
conteúdo do arquivo (nem o nome original dele), para poder ir também para os logs sem vazar dado
pessoal."""

from __future__ import annotations


class ErroIngestao(Exception):
    """Base. `codigo` é estável (a API e o front usam); `mensagem` é para a pessoa."""

    codigo = "erro_ingestao"

    def __init__(self, mensagem: str) -> None:
        super().__init__(mensagem)
        self.mensagem = mensagem


class ArquivoVazio(ErroIngestao):
    codigo = "arquivo_vazio"

    def __init__(self) -> None:
        super().__init__("O arquivo está vazio. Envie o currículo em PDF ou DOCX.")


class ArquivoGrande(ErroIngestao):
    codigo = "arquivo_grande"

    def __init__(self, limite_bytes: int) -> None:
        mb = limite_bytes / (1024 * 1024)
        super().__init__(
            f"O arquivo passa do limite de {mb:.0f} MB. Exporte o currículo de novo, sem imagens "
            "grandes, ou cole o texto."
        )


class TipoNaoSuportado(ErroIngestao):
    codigo = "tipo_nao_suportado"

    def __init__(self, detalhe: str = "") -> None:
        texto = "Formato não suportado: envie o currículo em PDF ou DOCX, ou cole o texto."
        super().__init__(f"{texto} {detalhe}".strip())


class ExtensaoNaoConfere(ErroIngestao):
    codigo = "extensao_nao_confere"

    def __init__(self, extensao: str, tipo_real: str) -> None:
        super().__init__(
            f"O arquivo tem extensão .{extensao}, mas o conteúdo é {tipo_real.upper()}. Renomeie o "
            f"arquivo para .{tipo_real} ou exporte o currículo de novo."
        )


class ArquivoCorrompido(ErroIngestao):
    codigo = "arquivo_corrompido"

    def __init__(self, tipo: str) -> None:
        super().__init__(
            f"Não conseguimos abrir o {tipo.upper()}: o arquivo parece corrompido ou incompleto. "
            "Exporte o currículo de novo."
        )


class ZipSuspeito(ErroIngestao):
    """DOCX que descompacta para muito mais do que o limite (zip bomb) ou tem entradas demais."""

    codigo = "zip_suspeito"

    def __init__(self) -> None:
        super().__init__(
            "O DOCX descompactado é grande demais ou tem partes demais para um currículo. Salve o "
            "documento de novo no Word ou exporte em PDF."
        )


class PdfCriptografado(ErroIngestao):
    codigo = "pdf_criptografado"

    def __init__(self) -> None:
        super().__init__(
            "O PDF está protegido por senha. Exporte o currículo de novo sem senha e envie "
            "outra vez."
        )


class MuitasPaginas(ErroIngestao):
    codigo = "muitas_paginas"

    def __init__(self, paginas: int, limite: int) -> None:
        super().__init__(
            f"O PDF tem {paginas} páginas, e o limite é {limite}. Envie só o currículo, sem anexos."
        )


class SemTexto(ErroIngestao):
    """Não sobrou texto visível: PDF escaneado (só imagem), documento vazio ou só texto oculto."""

    codigo = "sem_texto"

    def __init__(self, mensagem: str) -> None:
        super().__init__(mensagem)


class TextoGrande(ErroIngestao):
    codigo = "texto_grande"

    def __init__(self, limite_caracteres: int, *, arquivo: bool = False) -> None:
        if arquivo:
            mensagem = (
                f"O texto do arquivo passa do limite de {limite_caracteres} caracteres. Envie só o "
                "currículo, sem anexos."
            )
        else:
            mensagem = (
                f"O texto passa do limite de {limite_caracteres} caracteres. Cole só o currículo."
            )
        super().__init__(mensagem)


class PdfPesado(ErroIngestao):
    """Uma página levou mais que o limite de tempo para ser lida e verificada."""

    codigo = "pdf_pesado"

    def __init__(self, pagina: int, limite_s: float) -> None:
        super().__init__(
            f"A página {pagina} do PDF é pesada demais para ler (passou de {limite_s:.0f} s). "
            "Exporte o currículo de novo, com menos texto por página, ou cole o texto."
        )


class DocxComMacro(ErroIngestao):
    codigo = "docx_com_macro"

    def __init__(self) -> None:
        super().__init__(
            "DOCX com macro (.docm) não é aceito. Salve o documento como .docx comum (sem macros) "
            "ou exporte em PDF."
        )
