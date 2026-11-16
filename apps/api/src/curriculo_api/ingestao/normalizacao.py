"""Normalizadores de texto da ingestão. Funções puras, testadas com hypothesis.

Dois níveis:
- `normalizar_texto`: o que muda o texto analisado (e, portanto, o que a IA vê e onde se ancora o
  trecho). Só mexe no que a pessoa não enxerga como diferente: quebras de linha, NFC, caracteres de
  largura zero, ligaduras tipográficas, espaços especiais, espaço no fim da linha e linhas em branco
  repetidas.
- `chave_de_casamento`: uma cópia agressiva, só para procurar padrões (detector de injection):
  NFKC, homóglifos latinos, sem acentos, caixa dobrada e espaços colapsados. Nunca vira texto
  analisado.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from collections.abc import Sequence

# Formatação invisível: largura zero, hífen suave, marcas e sobrescritas de direção, seletores.
LARGURA_ZERO = frozenset("­͏؜ᅟᅠ឴឵᠎​‌‍‎‏‪‫‬‭‮⁠⁡⁢⁣⁤⁦⁧⁨⁩ㅤ﻿ﾠ")
_SELETORES_DE_VARIACAO = re.compile("[︀-️]")
_TABELA_LARGURA_ZERO = {ord(c): None for c in LARGURA_ZERO}

LIGADURAS = {
    "ﬀ": "ff",
    "ﬁ": "fi",
    "ﬂ": "fl",
    "ﬃ": "ffi",
    "ﬄ": "ffl",
    "ﬅ": "st",
    "ﬆ": "st",
}
_TABELA_LIGADURAS = {ord(k): v for k, v in LIGADURAS.items()}

# Espaços que o leitor vê como espaço comum.
_ESPACOS = {ord(c): " " for c in "         "}
_ESPACOS |= {ord(c): " " for c in "      　"}
# Separadores de linha e parágrafo Unicode viram quebra comum.
_ESPACOS |= {ord(" "): "\n", ord(" "): "\n", ord("\x0b"): "\n", ord("\x0c"): "\n"}

_CONTROLE = re.compile(r"[\x00-\x08\x0e-\x1f\x7f]")
_ESPACO_FIM_DE_LINHA = re.compile(r"[ \t]+\n")
_LINHAS_EM_BRANCO = re.compile(r"\n{3,}")


def remover_largura_zero(texto: str) -> str:
    return _SELETORES_DE_VARIACAO.sub("", texto.translate(_TABELA_LARGURA_ZERO))


def normalizar_texto(texto: str) -> str:
    """Normalização do texto analisado. Idempotente (propriedade testada)."""
    texto = texto.replace("\r\n", "\n").replace("\r", "\n")
    texto = unicodedata.normalize("NFC", texto)
    texto = remover_largura_zero(texto)
    texto = texto.translate(_TABELA_LIGADURAS).translate(_ESPACOS)
    texto = _CONTROLE.sub("", texto)
    texto = _ESPACO_FIM_DE_LINHA.sub("\n", texto + "\n")
    texto = _LINHAS_EM_BRANCO.sub("\n\n", texto)
    return texto.strip("\n ") + "\n" if texto.strip() else ""


# Hífen de quebra de linha: letra + "-" no fim da linha + letra minúscula no começo da seguinte.
# "desenvol-\nvimento" vira "desenvolvimento". Não junta "- item" (marcador), nem "2019 -\n2022",
# nem linha seguinte em maiúscula ("Front-\nEnd" fica como está).
_HIFEN_DE_QUEBRA = re.compile(r"(?<=[^\W\d_])-\n(?=[a-zà-öø-ÿ])")


def juntar_hifens_de_quebra(texto: str) -> str:
    return _HIFEN_DE_QUEBRA.sub("", texto)


_NUMERO_DE_PAGINA = re.compile(
    r"^\s*(?:(?:p[áa]gina|page|p[áa]g\.?)\s*\d+(?:\s*(?:de|of|/)\s*\d+)?|\d+\s*(?:/|de|of)\s*\d+"
    r"|[-–—]?\s*\d{1,3}\s*[-–—]?)\s*$",
    re.IGNORECASE,
)


_PAGINA = r"(?:(?:p[áa]gina|page|p[áa]g\.?)\s*\d+(?:\s*(?:de|of|/)\s*\d+)?|\d+\s*/\s*\d+)"
_NUMERO_DE_PAGINA_NA_LINHA = re.compile(
    rf"^{_PAGINA}\s*[-–—|·:]?\s*|\s*[-–—|·]?\s*{_PAGINA}$", re.IGNORECASE
)


def _chave_de_linha(linha: str) -> str:
    """A linha com espaços colapsados e o número de página no começo ou no fim (se houver)
    trocado por #. Outros números ficam: "linha 1" e "linha 2" não são a mesma linha."""
    return _NUMERO_DE_PAGINA_NA_LINHA.sub("#", " ".join(linha.split())).casefold()


def remover_cabecalhos_e_rodapes(paginas: Sequence[str], bordas: int = 2) -> list[str]:
    """Tira cabeçalho e rodapé repetidos entre páginas e números de página.

    Uma linha entre as `bordas` primeiras ou últimas linhas não vazias de uma página é
    "repetida" se a mesma linha (com o número de página trocado por #) aparece nas bordas de pelo
    menos 2 páginas e de pelo menos metade delas. As ocorrências da primeira página em que ela
    aparece ficam (no cabeçalho costumam estar o nome e o contato, que a anonimização precisa ver);
    as das outras páginas saem. Linhas que são só número de
    página ("Página 2 de 3", "2/3", "- 2 -") saem sempre que estão numa borda.
    """
    linhas_por_pagina = [p.split("\n") for p in paginas]

    def indices_de_borda(linhas: list[str]) -> list[int]:
        cheias = [i for i, linha in enumerate(linhas) if linha.strip()]
        return sorted(set(cheias[:bordas] + cheias[-bordas:]))

    contagem: Counter[str] = Counter()
    for linhas in linhas_por_pagina:
        contagem.update({_chave_de_linha(linhas[i]) for i in indices_de_borda(linhas)})
    minimo = max(2, math.ceil(len(paginas) / 2))
    repetidas = {chave for chave, n in contagem.items() if n >= minimo}

    primeira_pagina: dict[str, int] = {}
    resultado: list[str] = []
    for pagina, linhas in enumerate(linhas_por_pagina):
        remover: set[int] = set()
        for i in indices_de_borda(linhas):
            chave = _chave_de_linha(linhas[i])
            if _NUMERO_DE_PAGINA.match(linhas[i]) or (
                chave in repetidas and primeira_pagina.setdefault(chave, pagina) != pagina
            ):
                remover.add(i)
        resultado.append("\n".join(linha for i, linha in enumerate(linhas) if i not in remover))
    return resultado


# Homóglifos comuns (cirílico, grego, latim de largura total já sai no NFKC) → latim.
HOMOGLIFOS = {
    "а": "a",
    "в": "b",
    "е": "e",
    "ё": "e",
    "к": "k",
    "м": "m",
    "н": "h",
    "о": "o",
    "р": "p",
    "с": "c",
    "т": "t",
    "у": "y",
    "х": "x",
    "і": "i",
    "ї": "i",
    "ј": "j",
    "ѕ": "s",
    "ԁ": "d",
    "ԛ": "q",
    "ԝ": "w",
    "ɡ": "g",
    "ı": "i",
    "ℓ": "l",
    "α": "a",
    "β": "b",
    "ε": "e",
    "η": "n",
    "ι": "i",
    "κ": "k",
    "ν": "v",
    "ο": "o",
    "ρ": "p",
    "τ": "t",
    "υ": "u",
    "χ": "x",
    "ω": "w",
    "А": "A",
    "В": "B",
    "Е": "E",
    "К": "K",
    "М": "M",
    "Н": "H",
    "О": "O",
    "Р": "P",
    "С": "C",
    "Т": "T",
    "У": "Y",
    "Х": "X",
    "І": "I",
    "Ј": "J",
    "Ѕ": "S",
    "Α": "A",
    "Β": "B",
    "Ε": "E",
    "Η": "H",
    "Ι": "I",
    "Κ": "K",
    "Μ": "M",
    "Ν": "N",
    "Ο": "O",
    "Ρ": "P",
    "Τ": "T",
    "Υ": "Y",
    "Χ": "X",
    "Ζ": "Z",
}
_TABELA_HOMOGLIFOS = {ord(k): v for k, v in HOMOGLIFOS.items()}


def sem_acentos(texto: str) -> str:
    decomposto = unicodedata.normalize("NFD", texto)
    return "".join(c for c in decomposto if not unicodedata.combining(c))


def chave_de_casamento(texto: str) -> str:
    """Forma canônica para procurar padrões: sem largura zero, NFKC, homóglifos → latim, sem
    acentos, caixa dobrada, sem ênfase de Markdown (`*`, `_`, `~`, crase), aspas e travessões
    simples e espaços colapsados."""
    texto = remover_largura_zero(texto)
    texto = unicodedata.normalize("NFKC", texto).translate(_TABELA_HOMOGLIFOS)
    texto = sem_acentos(texto).casefold()
    texto = re.sub(r"[*_~`]+", "", texto)
    texto = re.sub(r"[‘’‚‛´]", "'", texto)
    texto = re.sub(r"[“”„‟]", '"', texto)
    texto = re.sub(r"[‐‑‒–—―]", "-", texto)
    return " ".join(texto.split())


def compactar(chave: str) -> str:
    """Só letras e dígitos: pega "i g n o r e" e "ig-no-re". Use só com padrões longos."""
    return re.sub(r"[^0-9a-z]", "", chave)


def dobrar_1a1(texto: str) -> str:
    """Tira acentos e baixa a caixa caractere a caractere, sem mudar o comprimento: os índices do
    resultado valem no original (a anonimização casa no dobrado e substitui no original)."""
    saida = []
    for c in texto:
        base = unicodedata.normalize("NFD", c)[0]
        minuscula = base.lower()
        saida.append(minuscula if len(minuscula) == 1 else base)
    return "".join(saida)
