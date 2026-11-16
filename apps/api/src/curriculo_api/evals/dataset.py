"""Schema e carga do dataset de evals (`evals/casos/<id>/{curriculo.md,vaga.md,esperado.yaml}`).

O schema está documentado em `evals/README.md`.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Annotated, Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from curriculo_api.alertas import TipoAlerta
from curriculo_api.ia.modelos import Nivel

TipoCaso = Literal["base", "injection", "contrafactual"]
Status = Literal["atende", "parcial", "nao_atende"]
TipoDadoPessoal = Literal[
    "nome",
    "email",
    "telefone",
    "cpf",
    "nascimento",
    "idade",
    "genero",
    "estado_civil",
    "endereco",
]
AtributoContrafactual = Literal[
    "nome",
    "genero",
    "idade",
    "estado_civil",
    "email",
    "telefone",
    "cpf",
    "endereco",
    "cargo_flexionado",
]
TIPO_PARA_ATRIBUTO: dict[str, AtributoContrafactual] = {
    "nome": "nome",
    "genero": "genero",
    "nascimento": "idade",
    "idade": "idade",
    "estado_civil": "estado_civil",
    "email": "email",
    "telefone": "telefone",
    "cpf": "cpf",
    "endereco": "endereco",
}

DataTexto = Annotated[str, StringConstraints(pattern=r"^\d{4}(-(0[1-9]|1[0-2]))?$")]
"""`"AAAA"` ou `"AAAA-MM"`."""

Texto = Annotated[str, StringConstraints(min_length=1, pattern=r"\S")]

MARCADOR_OCULTO = re.compile(r"<!-- oculto -->(.*?)<!-- /oculto -->", re.DOTALL)


class _Modelo(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ExperienciaEsperada(_Modelo):
    cargo: Texto
    empresa: Texto
    inicio: DataTexto
    fim: DataTexto | None
    relevante: bool = Field(
        description="Tem competência ancorada que atende ou atende em parte um obrigatório."
    )
    trecho: Texto


class CompetenciaEsperada(_Modelo):
    canonica: Texto
    como_escrito: Texto | None = Field(
        default=None, description="Como aparece no currículo, se difere da canônica."
    )
    trecho: Texto
    experiencias: tuple[int, ...] = Field(
        default=(), description="Índices das experiências em que a competência aparece."
    )

    @property
    def nome(self) -> str:
        return self.como_escrito or self.canonica


class FormacaoEsperada(_Modelo):
    curso: Texto
    instituicao: str | None
    conclusao: int | None
    trecho: Texto


class IdiomaEsperado(_Modelo):
    idioma: Texto = Field(description="Canônica da taxonomia (categoria idioma).")
    nivel: str | None
    trecho: Texto


class CertificacaoEsperada(_Modelo):
    nome: Texto
    canonica: Texto | None = None
    trecho: Texto


class RequisitoEsperado(_Modelo):
    descricao: Texto = Field(description="Texto literal da vaga.")
    tipo: Literal["obrigatorio", "desejavel"]
    competencia: Texto = Field(description="Canônica da taxonomia.")
    anos: int | None = Field(default=None, ge=1)
    status_esperado: Status
    evidencia: Texto | None

    @model_validator(mode="after")
    def _evidencia_coerente(self) -> Self:
        if (self.status_esperado == "nao_atende") != (self.evidencia is None):
            raise ValueError(
                f"{self.descricao!r}: evidência deve ser nula se, e só se, o status é nao_atende"
            )
        return self


class Injecao(_Modelo):
    local: Literal["curriculo", "vaga"]
    oculta: bool
    trecho: Texto = Field(description="O texto injetado, sem os marcadores de oculto.")
    alerta: TipoAlerta = Field(description="Tipo de alerta que a métrica 5 exige.")

    @model_validator(mode="after")
    def _oculta_so_no_curriculo(self) -> Self:
        if self.oculta and self.local != "curriculo":
            raise ValueError("texto oculto só existe no currículo")
        return self


class Substituicao(_Modelo):
    de: Texto
    para: Texto


class Contrafactual(_Modelo):
    muda: tuple[AtributoContrafactual, ...] = Field(
        min_length=1, description="Tudo o que difere do par-base."
    )
    substituicoes: tuple[Substituicao, ...] = Field(
        default=(),
        description="Trocas no corpo do currículo (cargo flexionado em gênero), aplicadas em "
        "ordem sobre o texto do par-base.",
    )

    @model_validator(mode="after")
    def _substituicoes_so_com_cargo_flexionado(self) -> Self:
        if ("cargo_flexionado" in self.muda) != bool(self.substituicoes):
            raise ValueError("`substituicoes` existe se, e só se, `muda` tem cargo_flexionado")
        return self


def aplicar_substituicoes(texto: str, substituicoes: Sequence[Substituicao]) -> str:
    for s in substituicoes:
        texto = texto.replace(s.de, s.para)
    return texto


class DadoPessoal(_Modelo):
    tipo: TipoDadoPessoal
    valor: Texto


class Esperado(_Modelo):
    id: Texto
    tipo: TipoCaso
    base: str | None = None
    descricao: Texto
    idioma_vaga: Literal["pt", "en"]
    titulo_vaga: Texto
    nivel: Nivel | None
    anos_minimos: int | None = Field(ge=0)

    experiencias: tuple[ExperienciaEsperada, ...]
    competencias: tuple[CompetenciaEsperada, ...]
    formacao: tuple[FormacaoEsperada, ...]
    idiomas: tuple[IdiomaEsperado, ...]
    certificacoes: tuple[CertificacaoEsperada, ...]
    requisitos: tuple[RequisitoEsperado, ...] = Field(min_length=1)

    anos_relevantes_esperados: float = Field(ge=0)
    nota_referencia: int = Field(ge=0, le=100)
    faixa_nota: tuple[int, int]
    lacunas: tuple[str, ...]
    alertas_esperados: tuple[TipoAlerta, ...]
    dados_pessoais: tuple[DadoPessoal, ...]

    injecao: Injecao | None = None
    contrafactual: Contrafactual | None = None

    @model_validator(mode="after")
    def _coerencia(self) -> Self:
        minimo, maximo = self.faixa_nota
        if not 0 <= minimo <= maximo <= 100:
            raise ValueError(f"faixa_nota inválida: {self.faixa_nota}")
        if (self.tipo == "base") != (self.base is None):
            raise ValueError("`base` é obrigatório nas variantes e proibido nos pares-base")
        if (self.tipo == "injection") != (self.injecao is not None):
            raise ValueError("`injecao` é obrigatório nas variantes de injection, e só nelas")
        if (self.tipo == "contrafactual") != (self.contrafactual is not None):
            raise ValueError("`contrafactual` é obrigatório nos contrafactuais, e só neles")
        if self.injecao is not None and self.injecao.alerta not in self.alertas_esperados:
            raise ValueError("o alerta da injeção precisa estar em alertas_esperados")
        if self.tipo != "injection" and self.alertas_esperados:
            raise ValueError("só variantes de injection esperam alertas")
        total = len(self.experiencias)
        for c in self.competencias:
            if any(not 0 <= i < total for i in c.experiencias):
                raise ValueError(f"{c.canonica}: índice de experiência inexistente")
        return self

    @property
    def competencias_anotadas(self) -> frozenset[str]:
        """O conjunto A da métrica 3: canônicas das competências (sem idiomas e certificações)."""
        return frozenset(c.canonica for c in self.competencias)

    @property
    def evidencias_canonicas(self) -> frozenset[str]:
        """Tudo o que pode servir de evidência a um requisito: competências, idiomas e
        certificações com canônica."""
        certificacoes = {c.canonica for c in self.certificacoes if c.canonica is not None}
        return self.competencias_anotadas | {i.idioma for i in self.idiomas} | certificacoes


class ConfigDataset(_Modelo):
    versao: int = Field(ge=1)
    data_referencia: date = Field(
        description="Data da análise usada para 'atual' (ADR 0003); fixa, para a nota não mudar "
        "com o calendário."
    )


@dataclass(frozen=True)
class Caso:
    id: str
    pasta: Path
    esperado: Esperado
    curriculo: str
    vaga: str


@dataclass(frozen=True)
class Dataset:
    config: ConfigDataset
    casos: tuple[Caso, ...]

    def por_id(self) -> dict[str, Caso]:
        return {caso.id: caso for caso in self.casos}

    def do_tipo(self, tipo: TipoCaso) -> list[Caso]:
        return [caso for caso in self.casos if caso.esperado.tipo == tipo]


def _ler_texto(caminho: Path) -> str:
    # Modo texto com newline universal: o hash do provedor falso não depende de CRLF.
    return caminho.read_text(encoding="utf-8")


def carregar_caso(pasta: Path) -> Caso:
    dados = yaml.safe_load(_ler_texto(pasta / "esperado.yaml"))
    esperado = Esperado.model_validate(dados)
    if esperado.id != pasta.name:
        raise ValueError(f"{pasta.name}: o id {esperado.id!r} difere do nome da pasta")
    return Caso(
        id=esperado.id,
        pasta=pasta,
        esperado=esperado,
        curriculo=_ler_texto(pasta / "curriculo.md"),
        vaga=_ler_texto(pasta / "vaga.md"),
    )


def carregar_dataset(pasta_evals: Path) -> Dataset:
    """Lê `evals/dataset.yaml` e todos os casos em `evals/casos/`, em ordem de id."""
    config = ConfigDataset.model_validate(yaml.safe_load(_ler_texto(pasta_evals / "dataset.yaml")))
    pastas = sorted(p for p in (pasta_evals / "casos").iterdir() if p.is_dir())
    casos = tuple(carregar_caso(p) for p in pastas)
    ids = {c.id for c in casos}
    for caso in casos:
        base = caso.esperado.base
        if base is not None and base not in ids:
            raise ValueError(f"{caso.id}: base {base!r} não existe")
    return Dataset(config=config, casos=casos)


def localizar_raiz(inicio: Path | None = None) -> Path:
    """A raiz do repositório: a primeira pasta acima que tem `evals/dataset.yaml`."""
    atual = (inicio or Path(__file__)).resolve()
    for pasta in (atual, *atual.parents):
        if (pasta / "evals" / "dataset.yaml").is_file():
            return pasta
    raise FileNotFoundError("não encontrei evals/dataset.yaml acima de " + str(atual))


def sem_cabecalho(curriculo: str) -> str:
    """O currículo a partir da primeira seção (`## `): tira o cabeçalho com os dados pessoais."""
    indice = curriculo.find("\n## ")
    return curriculo if indice < 0 else curriculo[indice + 1 :]


def sem_injecao(texto: str, injecao: Injecao) -> str:
    """O texto com o trecho injetado (e os marcadores de oculto) removido uma vez."""
    alvo = f"<!-- oculto -->{injecao.trecho}<!-- /oculto -->" if injecao.oculta else injecao.trecho
    if texto.count(alvo) != 1:
        raise ValueError("o trecho injetado precisa aparecer exatamente uma vez")
    return texto.replace(alvo, "")


def espacos_normalizados(texto: str) -> str:
    return " ".join(texto.split())


def trechos_do_esperado(esperado: Esperado) -> Sequence[str]:
    """Todo trecho e toda evidência que precisam existir literalmente no currículo."""
    trechos: list[str] = [e.trecho for e in esperado.experiencias]
    trechos += [c.trecho for c in esperado.competencias]
    trechos += [f.trecho for f in esperado.formacao]
    trechos += [i.trecho for i in esperado.idiomas]
    trechos += [c.trecho for c in esperado.certificacoes]
    trechos += [r.evidencia for r in esperado.requisitos if r.evidencia is not None]
    return trechos
