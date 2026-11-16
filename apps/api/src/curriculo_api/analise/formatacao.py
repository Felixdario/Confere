"""Números para a tela, em pt-BR, com arredondamento meio para cima (ADR 0003)."""

from __future__ import annotations

import math
from fractions import Fraction


def meio_para_cima(valor: Fraction, casas: int = 0) -> Fraction:
    escala = Fraction(10) ** casas
    return Fraction(math.floor(valor * escala + Fraction(1, 2))) / escala


def decimal_br(valor: Fraction, casas: int = 1, *, cortar_zero: bool = False) -> str:
    """`Fraction(105, 2)` → "52,5"; com `cortar_zero`, "4,0" vira "4"."""
    arredondado = meio_para_cima(valor, casas)
    inteiro = math.floor(arredondado)
    resto = arredondado - inteiro
    if casas == 0 or (cortar_zero and resto == 0):
        return str(inteiro)
    digitos = str(round(resto * 10**casas)).rjust(casas, "0")
    return f"{inteiro},{digitos}"


def fracao_texto(valor: Fraction) -> str:
    return str(valor)
