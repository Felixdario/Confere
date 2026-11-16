"""Ingestão do currículo (fase 2): tipo real do arquivo, leitura de PDF/DOCX/texto, texto oculto,
instruções para a IA e anonimização. Decisões no ADR 0004."""

from curriculo_api.ingestao.anonimizacao import Anonimizacao, ItemRemovido, anonimizar
from curriculo_api.ingestao.erros import ErroIngestao
from curriculo_api.ingestao.ingerir import (
    CurriculoIngerido,
    VagaIngerida,
    ingerir_curriculo,
    ingerir_vaga,
    ler_arquivo,
    ler_texto_colado,
)
from curriculo_api.ingestao.modelos import DocumentoLido, Limites, TrechoOculto

__all__ = [
    "Anonimizacao",
    "CurriculoIngerido",
    "DocumentoLido",
    "ErroIngestao",
    "ItemRemovido",
    "Limites",
    "TrechoOculto",
    "VagaIngerida",
    "anonimizar",
    "ingerir_curriculo",
    "ingerir_vaga",
    "ler_arquivo",
    "ler_texto_colado",
]
