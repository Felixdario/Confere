"""Provedores de IA (ADR 0001): a interface `ProvedorIA`, o falso e, na fase 3, o real."""

from curriculo_api.ia.fabrica import NomeProvedor, criar_provedor
from curriculo_api.ia.falso import ProvedorFalso
from curriculo_api.ia.modelos import (
    CurriculoExtraido,
    RegistroUso,
    Resposta,
    TextoAnonimizado,
    VagaExtraida,
)
from curriculo_api.ia.provedor import (
    ErroProvedor,
    GravacaoAusente,
    ProvedorIA,
    ProvedorIndisponivel,
)

__all__ = [
    "CurriculoExtraido",
    "ErroProvedor",
    "GravacaoAusente",
    "NomeProvedor",
    "ProvedorFalso",
    "ProvedorIA",
    "ProvedorIndisponivel",
    "RegistroUso",
    "Resposta",
    "TextoAnonimizado",
    "VagaExtraida",
    "criar_provedor",
]
