"""Modelos das saídas da IA e do registro de uso (ADR 0001).

São os mesmos modelos enviados como `output_format` ao `messages.parse` na fase 3. Restrições como
`min_length` não vão no schema da API (o SDK as remove); valem aqui, na validação do nosso lado.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Annotated, Literal, NewType, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

TextoAnonimizado = NewType("TextoAnonimizado", str)
"""Texto do currículo depois da anonimização (fase 2). É o que a IA vê e onde se ancora o trecho."""

Trecho = Annotated[str, StringConstraints(min_length=1, pattern=r"\S")]
"""Citação literal do currículo que comprova o item (ADR 0003, ancoragem)."""

Texto = Annotated[str, StringConstraints(min_length=1, pattern=r"\S")]


class _Modelo(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DataParcial(_Modelo):
    """Ano, com mês opcional ("2019" ou "mar/2019")."""

    ano: int = Field(ge=1950, le=2100)
    mes: int | None = Field(default=None, ge=1, le=12)

    def indice_inicio(self) -> int:
        """Índice do mês (ano × 12 + mês − 1). Sem mês, conta janeiro (ADR 0003). Os dois meses
        das pontas contam: jan–dez de um ano são 12 meses."""
        return self.ano * 12 + (self.mes or 1) - 1

    def indice_fim(self) -> int:
        """Índice do mês final. Sem mês, conta dezembro (ADR 0003)."""
        return self.ano * 12 + (self.mes or 12) - 1


class Experiencia(_Modelo):
    cargo: Texto
    empresa: Texto
    inicio: DataParcial
    fim: DataParcial | None = Field(default=None, description="Ausente quando é o emprego atual.")
    trecho: Trecho

    @model_validator(mode="after")
    def _fim_depois_do_inicio(self) -> Self:
        if self.fim is not None and self.fim.indice_fim() < self.inicio.indice_inicio():
            raise ValueError("o fim da experiência vem antes do início")
        return self


class Competencia(_Modelo):
    nome: Texto
    trecho: Trecho
    experiencias: tuple[int, ...] = Field(
        default=(),
        description="Índices (a partir de 0) das experiências deste currículo em que a "
        "competência aparece. Vazio se ela só aparece no resumo, na lista de habilidades ou na "
        "formação. Serve para calcular anos por competência (ADR 0003).",
    )


class Formacao(_Modelo):
    curso: Texto
    instituicao: str | None = None
    conclusao: int | None = Field(default=None, ge=1950, le=2100)
    trecho: Trecho


class Idioma(_Modelo):
    idioma: Texto
    nivel: str | None = None
    trecho: Trecho


class Certificacao(_Modelo):
    nome: Texto
    emissor: str | None = None
    trecho: Trecho


SecaoCurriculo = Literal["experiencias", "competencias", "formacao", "idiomas", "certificacoes"]
SECOES: tuple[SecaoCurriculo, ...] = (
    "experiencias",
    "competencias",
    "formacao",
    "idiomas",
    "certificacoes",
)


class CurriculoExtraido(_Modelo):
    experiencias: tuple[Experiencia, ...] = ()
    competencias: tuple[Competencia, ...] = ()
    formacao: tuple[Formacao, ...] = ()
    idiomas: tuple[Idioma, ...] = ()
    certificacoes: tuple[Certificacao, ...] = ()

    @model_validator(mode="after")
    def _indices_de_experiencia_validos(self) -> Self:
        total = len(self.experiencias)
        for competencia in self.competencias:
            invalidos = [i for i in competencia.experiencias if not 0 <= i < total]
            if invalidos:
                raise ValueError(
                    f"competência {competencia.nome!r} aponta experiência inexistente: {invalidos}"
                )
        return self

    def total_de_itens(self) -> int:
        return sum(len(getattr(self, secao)) for secao in SECOES)

    def trechos(self) -> list[tuple[SecaoCurriculo, str]]:
        """Todos os itens ancoráveis, como (seção, trecho)."""
        return [(secao, item.trecho) for secao in SECOES for item in getattr(self, secao)]


Nivel = Literal["junior", "pleno", "senior"]


class Requisito(_Modelo):
    descricao: Texto
    tipo: Literal["obrigatorio", "desejavel"]
    competencia: Texto = Field(description="Nome da competência pedida, como na taxonomia.")
    anos_minimos: int | None = Field(default=None, ge=0, le=50)


class VagaExtraida(_Modelo):
    titulo: Texto
    idioma: Literal["pt", "en"]
    nivel: Nivel | None = None
    anos_minimos: int | None = Field(default=None, ge=0, le=50)
    requisitos: tuple[Requisito, ...]


Etapa = Literal["extrair_curriculo", "extrair_vaga", "escrever_feedback"]


class RegistroUso(_Modelo):
    """Uma chamada ao provedor (ADR 0001, "Custo por chamada"). Nunca leva conteúdo do currículo."""

    etapa: Etapa
    modelo: str
    tentativa: int = Field(default=1, ge=1)
    duracao_ms: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cache_creation_input_tokens: int = Field(default=0, ge=0)
    cache_read_input_tokens: int = Field(default=0, ge=0)
    custo_usd: Decimal = Field(ge=0)


@dataclass(frozen=True)
class Resposta[T]:
    """A saída validada de uma etapa e o uso de cada chamada feita para obtê-la (novas tentativas
    inclusive)."""

    saida: T
    usos: tuple[RegistroUso, ...]


class TabelaDaNota(_Modelo):
    """Provisória: a fase 3 define as linhas (requisito, regra, valor) e as parcelas."""

    nota: int = Field(ge=0, le=100)


class EventoFeedback(_Modelo):
    """Provisório: um pedaço do feedback em streaming; o último traz o uso (fase 3)."""

    tipo: Literal["texto", "fim"]
    texto: str = ""
    uso: RegistroUso | None = None
