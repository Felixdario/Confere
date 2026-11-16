"""Taxonomia de competências (ADR 0002): canônicas, sinônimos e relacionadas.

A correspondência da fase 3 usa `canonica_de` e `relacionadas_de`. As evals usam o mesmo
`normalizar_termo` para mapear as competências extraídas para a canônica (ADR 0005, métrica 3).
"""

from __future__ import annotations

import string
import unicodedata
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

# Pontuação removida das pontas. `#` e `+` ficam, para "C#" e "C++" não virarem "c"; o "." inicial
# fica, para ".NET" não virar "net" (o "." final sai: "Node." = "Node").
_PONTAS_FIM = (
    "".join(c for c in string.punctuation if c not in "#+") + "–—“”‘’«»…·" + string.whitespace
)
_PONTAS_INICIO = _PONTAS_FIM.replace(".", "")


def _passo_de_normalizacao(termo: str) -> str:
    # Compatibilidade antes e depois da caixa: "𝓐" → "A" → "a", "ﬁ" → "fi", "ß" → "ss".
    decomposto = unicodedata.normalize("NFKD", unicodedata.normalize("NFKD", termo).casefold())
    sem_acentos = "".join(c for c in decomposto if not unicodedata.combining(c))
    return " ".join(sem_acentos.split()).lstrip(_PONTAS_INICIO).rstrip(_PONTAS_FIM)


def normalizar_termo(termo: str) -> str:
    """Caixa, acentos, formas de compatibilidade Unicode, espaços repetidos e pontuação nas pontas
    (ADR 0002 e ADR 0005). Idempotente: repete o passo até um ponto fixo."""
    atual = _passo_de_normalizacao(termo)
    for _ in range(8):
        seguinte = _passo_de_normalizacao(atual)
        if seguinte == atual:
            break
        atual = seguinte
    return atual


class EntradaTaxonomia(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    canonica: str = Field(min_length=1)
    categoria: str = Field(min_length=1)
    sinonimos: tuple[str, ...] = ()
    relacionadas: tuple[str, ...] = ()


class ArquivoTaxonomia(BaseModel):
    """O formato de `dados/taxonomia.yaml`, validado na carga."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    versao: int = Field(ge=1)
    competencias: tuple[EntradaTaxonomia, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _validar(self) -> Self:
        donos: dict[str, str] = {}
        canonicas = {e.canonica for e in self.competencias}
        if len(canonicas) != len(self.competencias):
            raise ValueError("há canônicas repetidas")
        erros: list[str] = []
        for entrada in self.competencias:
            for termo in (entrada.canonica, *entrada.sinonimos):
                chave = normalizar_termo(termo)
                if not chave:
                    erros.append(f"{entrada.canonica}: termo vazio após normalizar ({termo!r})")
                    continue
                dono = donos.setdefault(chave, entrada.canonica)
                if dono != entrada.canonica:
                    erros.append(f"{termo!r} aparece em {dono!r} e em {entrada.canonica!r}")
            for relacionada in entrada.relacionadas:
                if relacionada == entrada.canonica:
                    erros.append(f"{entrada.canonica}: relacionada a si mesma")
                elif relacionada not in canonicas:
                    erros.append(f"{entrada.canonica}: relacionada {relacionada!r} não é canônica")
        por_nome = {e.canonica: e for e in self.competencias}
        for entrada in self.competencias:
            for relacionada in entrada.relacionadas:
                outra = por_nome.get(relacionada)
                if outra is not None and entrada.canonica not in outra.relacionadas:
                    erros.append(
                        f"relação não simétrica: {entrada.canonica!r} lista {relacionada!r}, "
                        "mas não o contrário"
                    )
        if erros:
            raise ValueError("taxonomia inválida:\n- " + "\n- ".join(erros))
        return self


class Taxonomia:
    """Consulta à taxonomia já validada."""

    def __init__(self, arquivo: ArquivoTaxonomia) -> None:
        self.arquivo = arquivo
        self._por_termo: dict[str, str] = {}
        self._relacionadas: dict[str, frozenset[str]] = {}
        self._categoria: dict[str, str] = {}
        for entrada in arquivo.competencias:
            for termo in (entrada.canonica, *entrada.sinonimos):
                self._por_termo[normalizar_termo(termo)] = entrada.canonica
            self._relacionadas[entrada.canonica] = frozenset(entrada.relacionadas)
            self._categoria[entrada.canonica] = entrada.categoria

    @property
    def versao(self) -> int:
        return self.arquivo.versao

    @property
    def canonicas(self) -> frozenset[str]:
        return frozenset(self._categoria)

    def canonica_de(self, termo: str) -> str | None:
        """A canônica de um nome ou sinônimo; `None` se o termo não está na taxonomia."""
        return self._por_termo.get(normalizar_termo(termo))

    def chave_de(self, termo: str) -> str:
        """A canônica, se existir; senão a forma normalizada (ADR 0005, métrica 3)."""
        canonica = self.canonica_de(termo)
        return canonica if canonica is not None else normalizar_termo(termo)

    def relacionadas_de(self, canonica: str) -> frozenset[str]:
        return self._relacionadas.get(canonica, frozenset())

    def categoria_de(self, canonica: str) -> str | None:
        return self._categoria.get(canonica)


def ler_taxonomia(caminho: Path) -> Taxonomia:
    dados = yaml.safe_load(caminho.read_text(encoding="utf-8"))
    return Taxonomia(ArquivoTaxonomia.model_validate(dados))


@lru_cache
def carregar_taxonomia() -> Taxonomia:
    """A taxonomia empacotada em `curriculo_api/dados/taxonomia.yaml`."""
    texto = resources.files("curriculo_api").joinpath("dados/taxonomia.yaml").read_text("utf-8")
    return Taxonomia(ArquivoTaxonomia.model_validate(yaml.safe_load(texto)))
