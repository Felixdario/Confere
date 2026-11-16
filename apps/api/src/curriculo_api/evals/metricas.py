"""Funções puras das métricas do ADR 0005 (testadas com hypothesis)."""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class PrecisaoCobertura:
    acertos: int
    extraidas: int
    anotadas: int

    @property
    def precisao(self) -> float | None:
        """Σ|E ∩ A| ÷ Σ|E|; indefinida (None) se nada foi extraído."""
        return self.acertos / self.extraidas if self.extraidas else None

    @property
    def cobertura(self) -> float | None:
        """Σ|E ∩ A| ÷ Σ|A|; indefinida (None) se nada foi anotado."""
        return self.acertos / self.anotadas if self.anotadas else None


def precisao_cobertura_micro(
    pares: Iterable[tuple[frozenset[str] | set[str], frozenset[str] | set[str]]],
) -> PrecisaoCobertura:
    """Micro-média sobre os pares (E, A): soma interseções e tamanhos antes de dividir."""
    acertos = extraidas = anotadas = 0
    for extraido, anotado in pares:
        acertos += len(extraido & anotado)
        extraidas += len(extraido)
        anotadas += len(anotado)
    return PrecisaoCobertura(acertos=acertos, extraidas=extraidas, anotadas=anotadas)


def percentil_nearest_rank(valores: Sequence[float], percentil: float) -> float | None:
    """Percentil pelo método nearest-rank: o menor valor com pelo menos p % dos dados ≤ ele.

    posto = ⌈p/100 × N⌉ (mínimo 1); resultado = valores ordenados[posto − 1].
    """
    if not 0 < percentil <= 100:
        raise ValueError("percentil deve estar em (0, 100]")
    if not valores:
        return None
    ordenados = sorted(valores)
    posto = max(1, math.ceil(percentil / 100 * len(ordenados)))
    return ordenados[posto - 1]


def p95(valores: Sequence[float]) -> float | None:
    return percentil_nearest_rank(valores, 95)


def razao(numerador: int, denominador: int) -> float | None:
    return numerador / denominador if denominador else None
