"""Flexão mínima de palavras (fase 3, rodada 3): só plural e gênero, nunca prefixo.

"conciliação" = "conciliações", "bancária" = "bancárias", "técnico" = "técnica" = "técnicos";
mas "Excel" ≠ "excelente", "Angular" ≠ "ângulo", "React" ≠ "reactive", "Marketing" ≠ "market".
As palavras chegam sem acento e em caixa baixa.
"""

from __future__ import annotations


def formas(palavra: str) -> frozenset[str]:
    """A palavra e suas variações de plural e gênero (regras do português, mais o "s" do
    inglês)."""
    p = palavra
    saida = {p, p + "s", p + "es"}
    if p.endswith("s") and len(p) > 3:
        saida |= {p[:-1]}
        if p.endswith("es"):
            saida.add(p[:-2])
    for fim_a, fim_b in (("a", "o"), ("o", "a"), ("as", "os"), ("os", "as")):
        if p.endswith(fim_a) and len(p) > len(fim_a) + 2:
            saida.add(p[: -len(fim_a)] + fim_b)
    # -ão → -ões / -ães / -ãos (sem acento: ao → oes, aes, aos) e o caminho inverso.
    if p.endswith("ao"):
        saida |= {p[:-2] + "oes", p[:-2] + "aes", p[:-2] + "aos"}
    for plural in ("oes", "aes", "aos"):
        if p.endswith(plural):
            saida.add(p[: -len(plural)] + "ao")
    # -l → -is (digital/digitais), -m → -ns (imagem/imagens), -r/-z → -res/-zes já cobertos.
    if p.endswith("l"):
        saida.add(p[:-1] + "is")
    if p.endswith("is") and len(p) > 4:
        saida.add(p[:-2] + "l")
    if p.endswith("m"):
        saida.add(p[:-1] + "ns")
    if p.endswith("ns"):
        saida.add(p[:-2] + "m")
    return frozenset(saida)


def mesma_palavra(a: str, b: str) -> bool:
    return a == b or b in formas(a) or a in formas(b)
