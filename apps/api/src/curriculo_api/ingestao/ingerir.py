"""Ponto de entrada da ingestão: arquivo ou texto colado → `DocumentoLido` com alertas → texto
anonimizado, que é o que a IA vê e onde se ancora o trecho (ADR 0003 e 0004).

Logs: só metadados (origem, páginas, contagens, duração). Nunca o texto, o trecho, o nome do
arquivo, o valor removido nem a mensagem de exceções de terceiros. O pdfminer, em DEBUG, registra
os operadores do PDF (o texto incluído), então os loggers dele ficam em WARNING.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

from curriculo_api.alertas import Alerta
from curriculo_api.config import obter_settings
from curriculo_api.ia.modelos import TextoAnonimizado
from curriculo_api.ingestao.anonimizacao import Anonimizacao, anonimizar, anonimizar_trecho
from curriculo_api.ingestao.erros import SemTexto, TextoGrande
from curriculo_api.ingestao.injecao import alertas_de_instrucao
from curriculo_api.ingestao.leitor_docx import ler_docx
from curriculo_api.ingestao.leitor_pdf import ler_pdf
from curriculo_api.ingestao.modelos import DESCRICAO_MOTIVO, DocumentoLido, Limites
from curriculo_api.ingestao.normalizacao import normalizar_texto
from curriculo_api.ingestao.tipo_arquivo import detectar_tipo

log = logging.getLogger("curriculo_api.ingestao")

LOGGERS_DE_TERCEIROS = ("pdfminer", "pdfplumber", "docx", "PIL")


def silenciar_logs_de_terceiros() -> None:
    for nome in LOGGERS_DE_TERCEIROS:
        logging.getLogger(nome).setLevel(logging.WARNING)


silenciar_logs_de_terceiros()


def _limites_padrao() -> Limites:
    """Os limites do ambiente (`INGESTAO_*`, ver `config.Settings`)."""
    return Limites.de_settings(obter_settings())


MENSAGEM_SEM_OCR = "o PDF não tem texto selecionável; OCR não está disponível nesta versão"


MENSAGEM_FORMULARIO = (
    "o PDF tem campos de formulário preenchidos; o texto deles não é lido (só o texto da página)"
)
MENSAGEM_COMENTARIOS = (
    "o DOCX tem comentários; eles não fazem parte do currículo entregue e não são lidos"
)
MENSAGEM_SEM_NOME = (
    "não identificamos o nome no topo do currículo; nada foi apagado como nome. Confira se o "
    "nome aparece no texto que vai para a análise"
)


def _sem_mudanca(texto: str) -> str:
    return texto


def _alertas(
    documento: DocumentoLido,
    limpar: Callable[[str], str] = _sem_mudanca,
    texto_visivel: str | None = None,
) -> tuple[Alerta, ...]:
    """Alertas do documento. `limpar` anonimiza cada trecho que vai para o alerta, e
    `texto_visivel` (o texto anonimizado) é onde se procuram as instruções visíveis: um alerta
    nunca carrega dado pessoal."""
    alertas: list[Alerta] = [
        Alerta(
            tipo="texto_oculto",
            origem="curriculo",
            trecho=limpar(oculto.texto),
            motivo=DESCRICAO_MOTIVO[oculto.motivo],
            pagina=oculto.pagina,
        )
        for oculto in documento.ocultos
    ]
    for oculto in documento.ocultos:
        alertas += alertas_de_instrucao(
            limpar(oculto.texto), "curriculo", em_texto_oculto=True, pagina=oculto.pagina
        )
    alertas += alertas_de_instrucao(
        documento.texto if texto_visivel is None else texto_visivel, "curriculo"
    )
    alertas += [
        Alerta(
            tipo="pdf_sem_texto", origem="curriculo", trecho="", motivo=MENSAGEM_SEM_OCR, pagina=p
        )
        for p in documento.paginas_sem_texto
    ]
    if documento.comentarios_nao_lidos:
        alertas.append(
            Alerta(
                tipo="comentario_nao_lido",
                origem="curriculo",
                trecho="",
                motivo=MENSAGEM_COMENTARIOS,
            )
        )
    if documento.campos_de_formulario:
        alertas.append(
            Alerta(
                tipo="formulario_nao_lido",
                origem="curriculo",
                trecho="",
                motivo=MENSAGEM_FORMULARIO,
            )
        )
    return tuple(alertas)


def _exigir_texto(documento: DocumentoLido) -> None:
    if documento.texto.strip():
        return
    if documento.paginas_sem_texto:
        raise SemTexto(
            "O PDF não tem texto selecionável (parece escaneado), e o OCR não está disponível "
            "nesta versão. Exporte o currículo do editor de texto como PDF ou cole o texto."
        )
    if documento.ocultos:
        raise SemTexto(
            "O documento só tem texto oculto (invisível para quem lê). Envie a versão que a "
            "pessoa vê."
        )
    raise SemTexto("O documento não tem texto. Confira o arquivo ou cole o texto do currículo.")


def ler_arquivo(
    conteudo: bytes, nome: str | None = None, limites: Limites | None = None
) -> DocumentoLido:
    """PDF ou DOCX (tipo pela assinatura de bytes). Levanta `ErroIngestao` com mensagem clara."""
    limites = limites or _limites_padrao()
    inicio = time.perf_counter()
    tipo = detectar_tipo(conteudo, nome, limites)
    documento = (
        ler_pdf(conteudo, limites)
        if tipo == "pdf"
        else ler_docx(conteudo, limites, ja_verificado=True)
    )
    documento = documento.model_copy(update={"alertas": _alertas(documento)})
    log.info(
        "ingestao.arquivo",
        extra={
            "origem": tipo,
            "bytes": len(conteudo),
            "paginas": documento.paginas,
            "caracteres": len(documento.texto),
            "ocultos": len(documento.ocultos),
            "imagens": len(documento.imagens),
            "alertas": len(documento.alertas),
            "duracao_ms": round((time.perf_counter() - inicio) * 1000),
        },
    )
    _exigir_texto(documento)
    return documento


def ler_texto_colado(texto: str, limites: Limites | None = None) -> DocumentoLido:
    limites = limites or _limites_padrao()
    if len(texto) > limites.texto_max_caracteres:
        raise TextoGrande(limites.texto_max_caracteres)
    documento = DocumentoLido(origem="texto", texto=normalizar_texto(texto))
    documento = documento.model_copy(update={"alertas": _alertas(documento)})
    _exigir_texto(documento)
    log.info(
        "ingestao.texto",
        extra={"caracteres": len(documento.texto), "alertas": len(documento.alertas)},
    )
    return documento


@dataclass(frozen=True)
class CurriculoIngerido:
    documento: DocumentoLido
    anonimizacao: Anonimizacao
    alertas: tuple[Alerta, ...]
    """Os alertas para a tela, com os trechos já anonimizados."""

    @property
    def texto_para_ia(self) -> TextoAnonimizado:
        return TextoAnonimizado(self.anonimizacao.texto)


def ingerir_curriculo(
    *,
    texto: str | None = None,
    arquivo: bytes | None = None,
    nome_arquivo: str | None = None,
    limites: Limites | None = None,
) -> CurriculoIngerido:
    """Arquivo (se houver) ou texto colado → documento lido → anonimização."""
    if arquivo is not None:
        documento = ler_arquivo(arquivo, nome_arquivo, limites)
    elif texto is not None:
        documento = ler_texto_colado(texto, limites)
    else:
        raise ValueError("passe `texto` ou `arquivo`")
    inicio = time.perf_counter()
    anonimizacao = anonimizar(documento.texto, imagens=len(documento.imagens))
    log.info(
        "ingestao.anonimizacao",
        extra={
            "removidos": sum(r.ocorrencias for r in anonimizacao.removidos),
            "tipos": sorted({r.tipo for r in anonimizacao.removidos}),
            "nome_encontrado": anonimizacao.nome_encontrado,
            "duracao_ms": round((time.perf_counter() - inicio) * 1000),
        },
    )
    nome = anonimizacao.nome
    alertas = list(
        _alertas(documento, lambda trecho: anonimizar_trecho(trecho, nome), anonimizacao.texto)
    )
    if not anonimizacao.nome_encontrado:
        alertas.append(
            Alerta(
                tipo="nome_nao_identificado",
                origem="curriculo",
                trecho="",
                motivo=MENSAGEM_SEM_NOME,
            )
        )
    return CurriculoIngerido(documento=documento, anonimizacao=anonimizacao, alertas=tuple(alertas))


@dataclass(frozen=True)
class VagaIngerida:
    texto: str
    alertas: tuple[Alerta, ...]


def ingerir_vaga(texto: str, limites: Limites | None = None) -> VagaIngerida:
    """A vaga não é anonimizada (não é dado pessoal do candidato), mas passa pela normalização e
    pelo detector de instruções (a injection pode vir na vaga, caso i04)."""
    limites = limites or _limites_padrao()
    if len(texto) > limites.texto_max_caracteres:
        raise TextoGrande(limites.texto_max_caracteres)
    normalizado = normalizar_texto(texto)
    if not normalizado.strip():
        raise SemTexto("A vaga está vazia. Cole o texto da vaga.")
    alertas = tuple(alertas_de_instrucao(normalizado, "vaga"))
    log.info("ingestao.vaga", extra={"caracteres": len(normalizado), "alertas": len(alertas)})
    return VagaIngerida(texto=normalizado, alertas=alertas)
