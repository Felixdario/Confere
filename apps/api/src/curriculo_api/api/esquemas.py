"""Modelos de entrada e saída da API (o contrato que o OpenAPI publica, ADR 0007)."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from curriculo_api.ia.modelos import AprenderIA, LacunaIA, LinhaRequisito, Parcela, Reescrita

_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")


class _Saida(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- auth ------------------------------------------------------------------------------------


class TokenCsrf(_Saida):
    csrf: str = Field(description="Copie no cabeçalho `X-CSRF-Token` das rotas que mudam estado.")


class Cadastro(BaseModel):
    email: str = Field(max_length=320, examples=["pessoa@example.com"])
    senha: str = Field(min_length=8, max_length=128, examples=["uma senha longa"])
    aceito_consentimento: bool = Field(
        description="Concordância com o texto de `GET /privacidade` (LGPD). Obrigatória."
    )
    versao_consentimento: str = Field(
        description="A `versao_texto` de `GET /privacidade` que a pessoa leu.",
        examples=["2026-11-16"],
    )

    @field_validator("email")
    @classmethod
    def _email(cls, valor: str) -> str:
        valor = valor.strip()
        if not _EMAIL.match(valor):
            raise ValueError("e-mail inválido")
        return valor


class Login(BaseModel):
    email: str = Field(max_length=320, examples=["demo@curriculo.dev"])
    senha: str = Field(max_length=128, examples=["demo1234"])


class ConsentimentoSaida(_Saida):
    tipo: Literal["lgpd_titular", "recrutador_base_legal"]
    versao_texto: str
    aceito_em: datetime


class Eu(_Saida):
    id: uuid.UUID
    email: str
    criado_em: datetime
    consentimentos: list[ConsentimentoSaida]


# --- análises --------------------------------------------------------------------------------

StatusAnalise = Literal["na_fila", "processando", "concluida", "erro"]


class VagaResumo(_Saida):
    id: uuid.UUID
    titulo: str


class CurriculoRef(_Saida):
    id: uuid.UUID
    versao: int = Field(description="Número da versão deste currículo (1, 2, 3…).")
    origem: Literal["pdf", "docx", "texto"]


class AnaliseCriada(_Saida):
    id: uuid.UUID
    status: StatusAnalise
    curriculo: CurriculoRef
    vaga: VagaResumo
    eventos_url: str = Field(examples=["/analises/6f1c…/eventos"])
    resultado_url: str = Field(examples=["/analises/6f1c…"])


class EtapaFeita(_Saida):
    etapa: str = Field(examples=["leitura"])
    texto: str = Field(examples=["lendo o arquivo"])
    em: datetime


class Decomposicao(_Saida):
    texto: str = Field(
        description="A linha da tela, calculada em código (ADR 0003).",
        examples=[
            "obrigatórios 4,5 de 6 → 52,5 · desejáveis 1 de 3 → 6,7 · senioridade 4/5 anos → "
            "8,0 · nota 67"
        ],
    )
    parcelas: list[Parcela]
    anos_relevantes: float
    anos_minimos: int | None


class PalavraChave(_Saida):
    termo: str
    no_curriculo: bool = Field(description="O termo aparece no texto do currículo.")


class Aviso(_Saida):
    tipo: str = Field(
        description="texto_oculto, instrucao_para_ia, pdf_sem_texto, comentario_nao_lido, "
        "formulario_nao_lido, nome_nao_identificado ou calculo.",
        examples=["texto_oculto"],
    )
    origem: Literal["curriculo", "vaga", "calculo"]
    motivo: str | None = None
    trecho: str = Field(default="", description="Trecho já anonimizado.")
    pagina: int | None = None


class Ignorado(_Saida):
    tipo: str = Field(examples=["email"])
    mascarado: str = Field(examples=["m•••@•••.com"])
    ocorrencias: int


class ErroAnaliseSaida(_Saida):
    codigo: str = Field(examples=["vaga_sem_requisitos"])
    mensagem: str


class AnaliseResumo(_Saida):
    id: uuid.UUID
    status: StatusAnalise
    nota: int | None
    criado_em: datetime
    concluido_em: datetime | None
    curriculo: CurriculoRef
    vaga: VagaResumo
    provedor: str | None


class PaginaAnalises(_Saida):
    itens: list[AnaliseResumo]
    proximo_cursor: str | None = Field(
        description="Passe em `cursor` para a próxima página; nulo na última."
    )


class AnaliseDetalhe(_Saida):
    id: uuid.UUID
    status: StatusAnalise
    etapas: list[EtapaFeita]
    criado_em: datetime
    iniciado_em: datetime | None
    concluido_em: datetime | None
    curriculo: CurriculoRef
    vaga: VagaResumo
    modo_demonstracao: bool = Field(description="Análise por regras ou gravações, sem IA.")
    aviso_modo: str | None = Field(
        examples=["Modo demonstração: análise por regras, sem IA."], default=None
    )
    provedor: str | None
    modelos: list[str]
    custo_usd: Decimal
    nota: int | None
    decomposicao: Decomposicao | None
    requisitos: list[LinhaRequisito] = Field(description="Tabela requisito × evidência.")
    resumo: str | None
    lacunas: list[LacunaIA]
    reescritas: list[Reescrita] = Field(description="Antes/depois, só com evidência ancorada.")
    reescritas_descartadas: int
    palavras_chave: list[PalavraChave]
    o_que_aprender: list[AprenderIA]
    avisos: list[Aviso]
    ignorado: list[Ignorado] = Field(
        description="O que a anonimização tirou antes da análise, com o valor mascarado."
    )
    conteudo_apagado: bool = Field(
        description="A retenção já apagou o texto e o arquivo desta versão (ADR 0004)."
    )
    erro: ErroAnaliseSaida | None


# --- currículos e comparação -----------------------------------------------------------------


class VersaoResumo(_Saida):
    versao: int
    origem: Literal["pdf", "docx", "texto"]
    criado_em: datetime
    expira_em: datetime
    conteudo_apagado: bool


class CurriculoDetalhe(_Saida):
    id: uuid.UUID
    criado_em: datetime
    versoes: list[VersaoResumo]


class PontoDaComparacao(_Saida):
    versao: int
    analise_id: uuid.UUID
    nota: int
    criado_em: datetime


class MudancaDeRequisito(_Saida):
    requisito: str
    tipo: Literal["obrigatorio", "desejavel"]
    de: Literal["atende", "parcial", "nao_atende"] | None
    para: Literal["atende", "parcial", "nao_atende"] | None


class Comparacao(_Saida):
    curriculo_id: uuid.UUID
    vaga: VagaResumo
    versoes: list[PontoDaComparacao] = Field(description="Uma análise concluída por versão.")
    de: PontoDaComparacao
    para: PontoDaComparacao
    diferenca: int
    frase: str = Field(examples=["A nota subiu de 58 para 76."])
    mudancas: list[MudancaDeRequisito]


# --- recrutador ------------------------------------------------------------------------------


class NovoProcesso(BaseModel):
    titulo: str | None = Field(default=None, max_length=200)
    vaga_texto: str = Field(min_length=1, max_length=60_000)
    declaro_base_legal: bool = Field(
        description="Quem envia currículos de terceiros declara ter base legal (LGPD) para "
        "tratá-los. Obrigatório."
    )


class ProcessoResumo(_Saida):
    id: uuid.UUID
    titulo: str
    vaga: VagaResumo
    criado_em: datetime
    candidatos: int
    limite_candidatos: int


Decisao = Literal["avancar", "nao_avancar", "pendente"]


class DecisaoSaida(_Saida):
    id: uuid.UUID
    decisao: Decisao
    justificativa: str | None = Field(
        description="Nula depois da retenção (RETENCAO_DIAS): ficam a decisão, quem e quando."
    )
    justificativa_apagada_em: datetime | None = None
    usuario_id: uuid.UUID = Field(description="Quem decidiu.")
    criado_em: datetime


class RequisitoResumo(_Saida):
    descricao: str
    tipo: Literal["obrigatorio", "desejavel"]
    status: Literal["atende", "parcial", "nao_atende"]


class CandidatoRanking(_Saida):
    id: uuid.UUID
    rotulo: str = Field(examples=["Candidato A"])
    posicao: int | None = Field(description="Ordem por nota (empates na ordem de envio).")
    status: StatusAnalise
    nota: int | None
    decomposicao: str | None
    parcelas: list[Parcela]
    requisitos: list[RequisitoResumo]
    explicacao: str | None = Field(
        examples=["Atende 4 de 6 obrigatórios e 1 de 3 desejáveis; senioridade 4 de 5 anos."]
    )
    decisao: DecisaoSaida | None = Field(description="A última decisão humana; nula = nenhuma.")
    eventos_url: str = Field(description="Progresso da análise (SSE), na visão anonimizada.")


class ProcessoDetalhe(ProcessoResumo):
    aviso: str = Field(
        examples=[
            "O sistema ordena e explica; não descarta ninguém. Avançar ou não é decisão sua, "
            "registrada com justificativa."
        ]
    )
    ranking: list[CandidatoRanking]


class CandidatoCriado(_Saida):
    id: uuid.UUID
    rotulo: str
    status: StatusAnalise
    eventos_url: str


class AvisoAnonimo(_Saida):
    """Alerta na visão do recrutador: tipo e motivo, nunca o trecho."""

    tipo: str
    origem: str
    motivo: str | None = None


class RegistroAuditoria(_Saida):
    acao: Literal["revelar", "baixar_arquivo"]
    usuario_id: uuid.UUID
    em: datetime


class CandidatoDetalhe(CandidatoRanking):
    tabela: list[LinhaRequisito]
    lacunas: list[LacunaIA]
    avisos: list[AvisoAnonimo]
    decisoes: list[DecisaoSaida] = Field(description="Histórico, da mais antiga à mais recente.")
    identidade_revelada_em: datetime | None
    auditoria: list[RegistroAuditoria] = Field(
        description="Cada revelação e cada download do arquivo original (quem e quando)."
    )


class NovaDecisao(BaseModel):
    decisao: Decisao
    justificativa: str = Field(
        min_length=10,
        max_length=2000,
        description="Obrigatória: por que esta decisão (fica registrada com quem e quando).",
        examples=["Tem a experiência com SAE e COREN ativo; falta UTI, a avaliar na entrevista."],
    )


class Revelacao(_Saida):
    candidato_id: uuid.UUID
    identidade_revelada_em: datetime
    arquivo_url: str | None = Field(description="O arquivo original, agora liberado.")


# --- privacidade -----------------------------------------------------------------------------


class ItemGuardado(_Saida):
    dado: str
    por_quanto_tempo: str


class Privacidade(_Saida):
    versao_texto: str
    texto_consentimento: str
    retencao_dias: int
    o_que_guardamos: list[ItemGuardado]
    o_que_vai_para_a_ia: str
    o_que_nunca_guardamos: list[str]
    como_apagar: str


class DadosApagados(_Saida):
    mensagem: str
    apagado: dict[str, int] = Field(
        examples=[{"usuarios": 1, "curriculos": 2, "curriculo_versoes": 3, "analises": 3}]
    )
    arquivos: int = Field(description="Arquivos apagados do disco.")
    chaves_redis: int = Field(description="Chaves apagadas do Redis (eventos, fila, limites).")


class Saude(_Saida):
    status: Literal["ok"]
    versao: str
    provedor_ia: Literal["regras", "falso", "anthropic"]
    modo_demonstracao: bool
