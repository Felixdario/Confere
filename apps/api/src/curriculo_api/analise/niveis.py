"""Níveis de proficiência (ADR 0003, "Requisito com nível").

A escala é básico/noções < intermediário < avançado < fluente/nativo. Adjetivos sem escala
("sólida", "forte", "strong") não são nível: o sistema não infere proficiência que a pessoa não
escreveu.
"""

from __future__ import annotations

import re

from curriculo_api.ia.modelos import NivelProficiencia
from curriculo_api.taxonomia import normalizar_termo

ORDEM: dict[NivelProficiencia, int] = {
    "basico": 1,
    "intermediario": 2,
    "avancado": 3,
    "fluente": 4,
}

_PALAVRAS: dict[str, NivelProficiencia] = {
    "basico": "basico",
    "basica": "basico",
    "basic": "basico",
    "nocoes": "basico",
    "nocao": "basico",
    "elementar": "basico",
    "elementary": "basico",
    "beginner": "basico",
    "iniciante": "basico",
    "intermediario": "intermediario",
    "intermediaria": "intermediario",
    "intermediate": "intermediario",
    "avancado": "avancado",
    "avancada": "avancado",
    "advanced": "avancado",
    "fluente": "fluente",
    "fluent": "fluente",
    "fluencia": "fluente",
    "fluency": "fluente",
    "nativo": "fluente",
    "nativa": "fluente",
    "native": "fluente",
    # Quadro europeu (CEFR), decidido na rodada 1 da fase 3: A1/A2 = usuário básico, B1/B2 =
    # independente (intermediário), C1 = proficiente operacional (avançado), C2 = domínio pleno
    # (fluente).
    "a1": "basico",
    "a2": "basico",
    "b1": "intermediario",
    "b2": "intermediario",
    "c1": "avancado",
    "c2": "fluente",
}


PALAVRAS_DE_NIVEL: frozenset[str] = frozenset(_PALAVRAS)
"""As palavras (sem acento, caixa baixa) que declaram nível, para o filtro do feedback."""

_ASPIRACAO = frozenset(
    [
        "cursando",
        "aprendendo",
        "estudando",
        "rumo",
        "buscando",
        "pretendo",
        "quero",
        "curso",
        "learning",
        "studying",
        "pursuing",
        "toward",
        "towards",
    ]
)
_ABAIXO: dict[NivelProficiencia, NivelProficiencia] = {
    "basico": "basico",
    "intermediario": "basico",
    "avancado": "intermediario",
    "fluente": "avancado",
}


def nivel_de(texto: str | None) -> NivelProficiencia | None:
    """O nível que o texto declara, se houver ("intermediário", "English (advanced)", "Noções de
    HTML", "Inglês C1"). Com mais de um nível no texto ("leitura avançada, conversação básica"),
    vale o **menor**: o sistema não arredonda proficiência para cima. Um nível precedido de
    aspiração ("cursando o nível avançado", "learning toward C1") não vale: conta, no máximo, o
    nível abaixo dele (rodada 3)."""
    if not texto:
        return None
    achados: list[NivelProficiencia] = []
    palavras = re.findall(r"\w+", normalizar_termo(texto))
    for k, palavra in enumerate(palavras):
        nivel = _PALAVRAS.get(palavra)
        if nivel is None:
            continue
        if _ASPIRACAO & set(palavras[max(0, k - 4) : k]):
            # "cursando o nível avançado": o concluído é, no máximo, o nível abaixo.
            nivel = _ABAIXO[nivel]
        achados.append(nivel)
    if not achados:
        return None
    menor: NivelProficiencia = min(achados, key=ORDEM.__getitem__)
    return menor


def abaixo(declarado: NivelProficiencia, pedido: NivelProficiencia) -> bool:
    return ORDEM[declarado] < ORDEM[pedido]


ROTULO: dict[NivelProficiencia, str] = {
    "basico": "básico",
    "intermediario": "intermediário",
    "avancado": "avançado",
    "fluente": "fluente",
}
