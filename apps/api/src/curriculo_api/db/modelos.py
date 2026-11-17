"""Tabelas (ADR 0007). Toda tabela com dado de alguém tem `usuario_id` com `ON DELETE CASCADE`:
"apagar meus dados" é um `DELETE` em `usuarios` (ADR 0004), e toda consulta da API filtra por ele.

O que **não** é guardado: o valor original do que a anonimização removeu (só tipo e valor
mascarado), o nome original do arquivo e o texto bruto do currículo no banco (o arquivo enviado
fica no disco, em `PASTA_ARQUIVOS`, até a retenção).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, ClassVar

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

DIMENSAO_VETORES = 384
"""A do `paraphrase-multilingual-MiniLM-L12-v2` (ADR 0002). Os testes usam o embutidor falso com
a mesma dimensão."""

CONVENCAO = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=CONVENCAO)
    type_annotation_map: ClassVar[dict[Any, Any]] = {dict[str, Any]: JSONB, list[Any]: JSONB}


def _uuid() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _agora() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


def _dono() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False
    )


class Usuario(Base):
    __tablename__ = "usuarios"
    __table_args__ = (Index("uq_usuarios_email_minusculo", func.lower(text("email")), unique=True),)

    id: Mapped[uuid.UUID] = _uuid()
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    senha_hash: Mapped[str] = mapped_column(Text, nullable=False)
    criado_em: Mapped[datetime] = _agora()


class Sessao(Base):
    __tablename__ = "sessoes"

    id: Mapped[uuid.UUID] = _uuid()
    usuario_id: Mapped[uuid.UUID] = _dono()
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    criado_em: Mapped[datetime] = _agora()
    expira_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Consentimento(Base):
    __tablename__ = "consentimentos"
    __table_args__ = (
        CheckConstraint("tipo IN ('lgpd_titular', 'recrutador_base_legal')", name="tipo"),
    )

    id: Mapped[uuid.UUID] = _uuid()
    usuario_id: Mapped[uuid.UUID] = _dono()
    tipo: Mapped[str] = mapped_column(String(40), nullable=False)
    versao_texto: Mapped[str] = mapped_column(String(40), nullable=False)
    aceito_em: Mapped[datetime] = _agora()


class Curriculo(Base):
    __tablename__ = "curriculos"
    __table_args__ = (
        CheckConstraint("origem IN ('proprio', 'recrutador')", name="origem"),
        Index("ix_curriculos_usuario", "usuario_id", "criado_em"),
    )

    id: Mapped[uuid.UUID] = _uuid()
    usuario_id: Mapped[uuid.UUID] = _dono()
    origem: Mapped[str] = mapped_column(String(20), nullable=False, default="proprio")
    criado_em: Mapped[datetime] = _agora()

    versoes: Mapped[list[CurriculoVersao]] = relationship(
        back_populates="curriculo", order_by="CurriculoVersao.numero", passive_deletes=True
    )


class CurriculoVersao(Base):
    __tablename__ = "curriculo_versoes"
    __table_args__ = (
        UniqueConstraint("curriculo_id", "numero", name="uq_curriculo_versoes_numero"),
        CheckConstraint("origem IN ('pdf', 'docx', 'texto')", name="origem"),
        Index("ix_curriculo_versoes_expira", "expira_em"),
    )

    id: Mapped[uuid.UUID] = _uuid()
    curriculo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("curriculos.id", ondelete="CASCADE"), nullable=False
    )
    usuario_id: Mapped[uuid.UUID] = _dono()
    numero: Mapped[int] = mapped_column(Integer, nullable=False)
    origem: Mapped[str] = mapped_column(String(10), nullable=False)
    arquivo: Mapped[str | None] = mapped_column(
        Text, comment="Caminho relativo a PASTA_ARQUIVOS (nulo depois da retenção)."
    )
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    tamanho_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    texto_anonimizado: Mapped[str | None] = mapped_column(Text)
    removidos: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, comment="[{tipo, mascarado, ocorrencias}]"
    )
    alertas: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    criado_em: Mapped[datetime] = _agora()
    expira_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    conteudo_apagado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    curriculo: Mapped[Curriculo] = relationship(back_populates="versoes")


class Vaga(Base):
    __tablename__ = "vagas"
    __table_args__ = (UniqueConstraint("usuario_id", "sha256", name="uq_vagas_usuario_sha256"),)

    id: Mapped[uuid.UUID] = _uuid()
    usuario_id: Mapped[uuid.UUID] = _dono()
    titulo: Mapped[str] = mapped_column(String(200), nullable=False)
    texto: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    alertas: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    criado_em: Mapped[datetime] = _agora()


class Analise(Base):
    __tablename__ = "analises"
    __table_args__ = (
        CheckConstraint("status IN ('na_fila', 'processando', 'concluida', 'erro')", name="status"),
        Index("ix_analises_usuario_criado", "usuario_id", "criado_em", "id"),
        Index("ix_analises_versao_vaga", "curriculo_versao_id", "vaga_id"),
    )

    id: Mapped[uuid.UUID] = _uuid()
    usuario_id: Mapped[uuid.UUID] = _dono()
    curriculo_versao_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("curriculo_versoes.id", ondelete="CASCADE"), nullable=False
    )
    vaga_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vagas.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="na_fila")
    etapas: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, comment="[{etapa, texto, em}]"
    )
    nota: Mapped[int | None] = mapped_column(Integer)
    decomposicao: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, comment="{texto, parcelas, anos_relevantes, anos_minimos}"
    )
    tabela: Mapped[list[Any] | None] = mapped_column(
        JSONB, comment="Linhas requisito × evidência (LinhaRequisito)."
    )
    feedback: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    avisos: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    estatisticas: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, comment="Contagens da ancoragem e do filtro (sem conteúdo)."
    )
    custo_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False, default=0)
    reserva_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 6),
        nullable=False,
        default=0,
        server_default="0",
        comment="O que esta análise reservou do teto diário no envio (devolvido ao terminar).",
    )
    provedor: Mapped[str | None] = mapped_column(String(20))
    modelos: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    erro_codigo: Mapped[str | None] = mapped_column(String(60))
    erro_mensagem: Mapped[str | None] = mapped_column(Text)
    criado_em: Mapped[datetime] = _agora()
    iniciado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    concluido_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProcessoRecrutador(Base):
    __tablename__ = "processos_recrutador"

    id: Mapped[uuid.UUID] = _uuid()
    usuario_id: Mapped[uuid.UUID] = _dono()
    vaga_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vagas.id", ondelete="CASCADE"), nullable=False
    )
    titulo: Mapped[str] = mapped_column(String(200), nullable=False)
    criado_em: Mapped[datetime] = _agora()


class Candidato(Base):
    __tablename__ = "candidatos"
    __table_args__ = (UniqueConstraint("processo_id", "rotulo", name="uq_candidatos_rotulo"),)

    id: Mapped[uuid.UUID] = _uuid()
    processo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("processos_recrutador.id", ondelete="CASCADE"),
        nullable=False,
    )
    usuario_id: Mapped[uuid.UUID] = _dono()
    rotulo: Mapped[str] = mapped_column(String(40), nullable=False)
    curriculo_versao_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("curriculo_versoes.id", ondelete="CASCADE"), nullable=False
    )
    analise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("analises.id", ondelete="CASCADE"), nullable=False
    )
    criado_em: Mapped[datetime] = _agora()
    identidade_revelada_em: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="Revelar é ação explícita do recrutador (ADR 0004)."
    )


class DecisaoHumana(Base):
    """Avançar ou não é sempre de uma pessoa (ADR 0004): só `POST .../decisoes` cria linhas, e
    nenhum código do sistema escreve aqui por conta própria. O histórico fica; vale a última."""

    __tablename__ = "decisoes_humanas"
    __table_args__ = (
        CheckConstraint("decisao IN ('avancar', 'nao_avancar', 'pendente')", name="decisao"),
        CheckConstraint(
            "justificativa IS NULL OR length(btrim(justificativa)) > 0", name="justificativa"
        ),
        Index("ix_decisoes_candidato", "candidato_id", "criado_em"),
    )

    id: Mapped[uuid.UUID] = _uuid()
    candidato_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("candidatos.id", ondelete="CASCADE"), nullable=False
    )
    usuario_id: Mapped[uuid.UUID] = _dono()
    decisao: Mapped[str] = mapped_column(String(20), nullable=False)
    justificativa: Mapped[str | None] = mapped_column(
        Text, comment="Obrigatória ao decidir; nula depois da retenção (sobre terceiros)."
    )
    criado_em: Mapped[datetime] = _agora()
    justificativa_apagada_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditoriaRecrutador(Base):
    """Toda saída da visão anonimizada (ADR 0004): revelar e baixar o arquivo original."""

    __tablename__ = "auditoria_recrutador"
    __table_args__ = (
        CheckConstraint("acao IN ('revelar', 'baixar_arquivo')", name="acao"),
        Index("ix_auditoria_candidato", "candidato_id", "em"),
    )

    id: Mapped[uuid.UUID] = _uuid()
    usuario_id: Mapped[uuid.UUID] = _dono()
    candidato_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("candidatos.id", ondelete="CASCADE"), nullable=False
    )
    acao: Mapped[str] = mapped_column(String(20), nullable=False)
    em: Mapped[datetime] = _agora()


class UsoDiario(Base):
    __tablename__ = "uso_diario"

    usuario_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("usuarios.id", ondelete="CASCADE"), primary_key=True
    )
    dia: Mapped[date] = mapped_column(Date, primary_key=True)
    custo_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False, default=0)
    reservado_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 6),
        nullable=False,
        default=0,
        server_default="0",
        comment="Pior caso das análises aceitas e ainda não terminadas (teto atômico).",
    )
    analises: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class VetorTaxonomia(Base):
    """Vetores da taxonomia para o vizinho mais próximo no banco (ADR 0002, fase 4)."""

    __tablename__ = "vetores_taxonomia"
    __table_args__ = (
        UniqueConstraint("modelo", "versao_taxonomia", "termo", name="uq_vetores_taxonomia_termo"),
        Index(
            "ix_vetores_taxonomia_hnsw",
            "vetor",
            postgresql_using="hnsw",
            postgresql_ops={"vetor": "vector_cosine_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    modelo: Mapped[str] = mapped_column(String(200), nullable=False)
    versao_taxonomia: Mapped[int] = mapped_column(Integer, nullable=False)
    termo: Mapped[str] = mapped_column(Text, nullable=False)
    canonica: Mapped[str] = mapped_column(Text, nullable=False)
    vetor: Mapped[Any] = mapped_column(Vector(DIMENSAO_VETORES), nullable=False)
