"""Modelos das saídas da IA e do registro de uso (ADR 0001).

São os mesmos modelos enviados como `output_format` ao `messages.parse` na fase 3. Restrições como
`min_length` não vão no schema da API (o SDK as remove); valem aqui, na validação do nosso lado.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Annotated, Literal, NewType, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from pydantic.json_schema import SkipJsonSchema

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
    datas_comprovadas: SkipJsonSchema[bool] = Field(
        default=True,
        description="Marca do código (fora do schema da IA): False quando nem as datas da "
        "extração nem as lidas do trecho são confiáveis; a experiência fica, mas não conta anos.",
    )

    @model_validator(mode="after")
    def _fim_depois_do_inicio(self) -> Self:
        if self.fim is not None and self.fim.indice_fim() < self.inicio.indice_inicio():
            raise ValueError("o fim da experiência vem antes do início")
        return self


class Competencia(_Modelo):
    nome: Texto
    trecho: Trecho
    nivel: str | None = Field(
        default=None,
        description="Nível de proficiência que o próprio currículo declara para esta competência "
        "(por exemplo 'avançado' ou 'intermediário'), como escrito. Nulo se não declara. "
        "Adjetivos sem escala ('sólida', 'forte') não são nível.",
    )
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
    competencia: str | None = Field(
        default=None,
        description="A competência ou o registro profissional que a certificação comprova, com o "
        "nome da taxonomia (por exemplo 'COREN' para 'COREN-BA ativo'). Nulo se nenhum.",
    )
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
NivelProficiencia = Literal["basico", "intermediario", "avancado", "fluente"]
"""Escala de proficiência do ADR 0003 (básico/noções < intermediário < avançado <
fluente/nativo)."""


class Requisito(_Modelo):
    descricao: Texto
    tipo: Literal["obrigatorio", "desejavel"]
    competencia: Texto = Field(description="Nome da competência pedida, como na taxonomia.")
    anos_minimos: int | None = Field(default=None, ge=0, le=50)
    nivel: NivelProficiencia | None = Field(
        default=None,
        description="Nível de proficiência pedido na própria linha do requisito ('Inglês "
        "avançado' → avancado; 'Noções de HTML' → basico). Nulo se não pede nível.",
    )


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
    stop_reason: str | None = None
    fallback: bool = Field(
        default=False, description="Um modelo de reserva do servidor respondeu (ADR 0001)."
    )


@dataclass(frozen=True)
class Resposta[T]:
    """A saída validada de uma etapa e o uso de cada chamada feita para obtê-la (novas tentativas
    inclusive)."""

    saida: T
    usos: tuple[RegistroUso, ...]


StatusRequisito = Literal["atende", "parcial", "nao_atende"]
RegraCorrespondencia = Literal[
    "mesma_competencia",
    "sinonimo_na_taxonomia",
    "relacionada_na_taxonomia",
    "similaridade",
    "sem_evidencia",
]


class LinhaRequisito(_Modelo):
    """Uma linha da tabela da nota: um requisito da vaga e como o código o decidiu (ADR 0003)."""

    descricao: str
    tipo: Literal["obrigatorio", "desejavel"]
    competencia_pedida: str = Field(description="Canônica da taxonomia, ou o termo da vaga.")
    status: StatusRequisito
    valor: str = Field(description="Valor da linha como fração exata: '1', '1/2' ou '0'.")
    regra: RegraCorrespondencia
    competencia_casada: str | None = Field(
        default=None, description="O item do currículo que comprova (como escrito)."
    )
    similaridade: float | None = Field(
        default=None, description="Cosseno do embedding, quando a regra foi por similaridade."
    )
    evidencia: str | None = Field(default=None, description="O trecho ancorado do currículo.")
    anos_pedidos: int | None = None
    anos_comprovados: float | None = None
    nivel_pedido: NivelProficiencia | None = None
    nivel_declarado: NivelProficiencia | None = None
    motivo: str = Field(description="Explicação legível em pt-BR.")


class Parcela(_Modelo):
    """Um componente da nota já renormalizado: as parcelas presentes somam a nota (antes do
    arredondamento)."""

    componente: Literal["obrigatorios", "desejaveis", "senioridade"]
    peso: str = Field(description="Peso original (fração exata: '7/10').")
    valor: str = Field(description="Valor do componente em [0, 1], fração exata.")
    pontos: str = Field(description="100 × peso × valor ÷ soma dos pesos presentes, exato.")
    pontos_exibicao: str = Field(description="Os pontos com uma casa, meio para cima ('52,5').")
    resumo: str = Field(description="Texto da tela: 'obrigatórios 4,5 de 6 → 52,5'.")


class TabelaDaNota(_Modelo):
    """A nota calculada em código (ADR 0003). A IA do feedback recebe esta tabela pronta e não a
    altera; a nota nunca é lida de uma resposta da IA."""

    nota: int = Field(ge=0, le=100)
    linhas: tuple[LinhaRequisito, ...] = ()
    parcelas: tuple[Parcela, ...] = ()
    anos_relevantes: float = Field(default=0, ge=0)
    anos_minimos: int | None = None
    avisos: tuple[str, ...] = ()
    decomposicao: str = Field(default="", description="A linha da tela com as parcelas e a nota.")


class LacunaIA(_Modelo):
    requisito: Texto = Field(description="A descrição do requisito, exatamente como na tabela.")
    comentario: Texto


class ReescritaIA(_Modelo):
    antes: Texto = Field(description="Trecho literal do currículo, copiado sem mudar nada.")
    depois: Texto
    competencias: tuple[str, ...] = Field(
        default=(), description="Todas as competências que o texto 'depois' cita."
    )


class AprenderIA(_Modelo):
    competencia: Texto
    sugestao: Texto


class FeedbackIA(_Modelo):
    """O que o modelo do feedback devolve (saída estruturada). Não tem nota nem status."""

    resumo: Texto = Field(description="Dois ou três parágrafos curtos para a pessoa candidata.")
    lacunas: tuple[LacunaIA, ...] = ()
    palavras_chave_ats: tuple[str, ...] = Field(
        default=(), description="Termos da vaga que um ATS procuraria, como escritos na vaga."
    )
    reescritas: tuple[ReescritaIA, ...] = ()
    o_que_aprender: tuple[AprenderIA, ...] = ()


class Reescrita(_Modelo):
    """Uma reescrita entregue (passou pelo filtro da evidência)."""

    antes: str
    depois: str
    competencias: tuple[str, ...] = Field(
        description="Competências que a reescrita cita (declaradas pela IA e detectadas no texto)."
    )


class ReescritaDescartada(_Modelo):
    motivo: Literal[
        "antes_curto",
        "antes_sem_ancora",
        "competencia_sem_evidencia",
        "termo_fora_do_curriculo",
        "afirmacao_sem_evidencia",
        "nivel_sem_evidencia",
        "toca_lacuna",
    ]
    competencias_sem_evidencia: tuple[str, ...] = ()
    termos_fora_do_curriculo: int = Field(
        default=0, ge=0, description="Quantas palavras ou números do 'depois' o currículo não tem."
    )


class Feedback(_Modelo):
    """O feedback entregue, depois da regra da evidência (ADR 0003, passo 5)."""

    resumo: str
    lacunas: tuple[LacunaIA, ...]
    palavras_chave_ats: tuple[str, ...]
    reescritas: tuple[Reescrita, ...]
    reescritas_descartadas: tuple[ReescritaDescartada, ...]
    o_que_aprender: tuple[AprenderIA, ...]

    @property
    def reescritas_propostas(self) -> int:
        return len(self.reescritas) + len(self.reescritas_descartadas)


class EventoFeedback(_Modelo):
    """Um evento do feedback em streaming (para o SSE da fase 4).

    - `etapa`: começou uma fase (`texto` traz o nome legível);
    - `texto`: um pedaço da resposta do modelo como chegou (um fragmento do JSON da saída
      estruturada, ver ADR 0001);
    - `final`: a saída validada (`feedback`) e o uso de cada chamada (`usos`).
    """

    tipo: Literal["etapa", "texto", "final"]
    texto: str = ""
    feedback: FeedbackIA | None = None
    usos: tuple[RegistroUso, ...] = ()
