"""Esquema inicial da fase 4 (ADR 0007): usuários, sessões, consentimentos, currículos e versões,
vagas, análises, modo recrutador, decisões humanas, uso diário e vetores da taxonomia (pgvector).

Revisão: 0001
Anterior: nenhuma
Criada em: 2026-11-16
"""

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # O tipo vector: a imagem pgvector/pgvector traz a extensão, e cada banco precisa criá-la.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "usuarios",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("senha_hash", sa.Text(), nullable=False),
        sa.Column(
            "criado_em", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_usuarios")),
    )
    op.create_index(
        "uq_usuarios_email_minusculo", "usuarios", [sa.literal_column("lower(email)")], unique=True
    )
    op.create_table(
        "vetores_taxonomia",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("modelo", sa.String(length=200), nullable=False),
        sa.Column("versao_taxonomia", sa.Integer(), nullable=False),
        sa.Column("termo", sa.Text(), nullable=False),
        sa.Column("canonica", sa.Text(), nullable=False),
        sa.Column("vetor", pgvector.sqlalchemy.vector.VECTOR(dim=384), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_vetores_taxonomia")),
        sa.UniqueConstraint(
            "modelo", "versao_taxonomia", "termo", name="uq_vetores_taxonomia_termo"
        ),
    )
    op.create_index(
        "ix_vetores_taxonomia_hnsw",
        "vetores_taxonomia",
        ["vetor"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_ops={"vetor": "vector_cosine_ops"},
    )
    op.create_table(
        "consentimentos",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("usuario_id", sa.UUID(), nullable=False),
        sa.Column("tipo", sa.String(length=40), nullable=False),
        sa.Column("versao_texto", sa.String(length=40), nullable=False),
        sa.Column(
            "aceito_em", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "tipo IN ('lgpd_titular', 'recrutador_base_legal')", name=op.f("ck_consentimentos_tipo")
        ),
        sa.ForeignKeyConstraint(
            ["usuario_id"],
            ["usuarios.id"],
            name=op.f("fk_consentimentos_usuario_id_usuarios"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_consentimentos")),
    )
    op.create_table(
        "curriculos",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("usuario_id", sa.UUID(), nullable=False),
        sa.Column("origem", sa.String(length=20), nullable=False),
        sa.Column(
            "criado_em", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "origem IN ('proprio', 'recrutador')", name=op.f("ck_curriculos_origem")
        ),
        sa.ForeignKeyConstraint(
            ["usuario_id"],
            ["usuarios.id"],
            name=op.f("fk_curriculos_usuario_id_usuarios"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_curriculos")),
    )
    op.create_index(
        "ix_curriculos_usuario", "curriculos", ["usuario_id", "criado_em"], unique=False
    )
    op.create_table(
        "sessoes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("usuario_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "criado_em", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("expira_em", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["usuario_id"],
            ["usuarios.id"],
            name=op.f("fk_sessoes_usuario_id_usuarios"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sessoes")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_sessoes_token_hash")),
    )
    op.create_table(
        "uso_diario",
        sa.Column("usuario_id", sa.UUID(), nullable=False),
        sa.Column("dia", sa.Date(), nullable=False),
        sa.Column("custo_usd", sa.Numeric(precision=12, scale=6), nullable=False),
        sa.Column("analises", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["usuario_id"],
            ["usuarios.id"],
            name=op.f("fk_uso_diario_usuario_id_usuarios"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("usuario_id", "dia", name=op.f("pk_uso_diario")),
    )
    op.create_table(
        "vagas",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("usuario_id", sa.UUID(), nullable=False),
        sa.Column("titulo", sa.String(length=200), nullable=False),
        sa.Column("texto", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("alertas", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "criado_em", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["usuario_id"],
            ["usuarios.id"],
            name=op.f("fk_vagas_usuario_id_usuarios"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_vagas")),
        sa.UniqueConstraint("usuario_id", "sha256", name="uq_vagas_usuario_sha256"),
    )
    op.create_table(
        "curriculo_versoes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("curriculo_id", sa.UUID(), nullable=False),
        sa.Column("usuario_id", sa.UUID(), nullable=False),
        sa.Column("numero", sa.Integer(), nullable=False),
        sa.Column("origem", sa.String(length=10), nullable=False),
        sa.Column(
            "arquivo",
            sa.Text(),
            nullable=True,
            comment="Caminho relativo a PASTA_ARQUIVOS (nulo depois da retenção).",
        ),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("tamanho_bytes", sa.Integer(), nullable=False),
        sa.Column("texto_anonimizado", sa.Text(), nullable=True),
        sa.Column(
            "removidos",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="[{tipo, mascarado, ocorrencias}]",
        ),
        sa.Column("alertas", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "criado_em", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("expira_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("conteudo_apagado_em", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "origem IN ('pdf', 'docx', 'texto')", name=op.f("ck_curriculo_versoes_origem")
        ),
        sa.ForeignKeyConstraint(
            ["curriculo_id"],
            ["curriculos.id"],
            name=op.f("fk_curriculo_versoes_curriculo_id_curriculos"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["usuario_id"],
            ["usuarios.id"],
            name=op.f("fk_curriculo_versoes_usuario_id_usuarios"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_curriculo_versoes")),
        sa.UniqueConstraint("curriculo_id", "numero", name="uq_curriculo_versoes_numero"),
    )
    op.create_index("ix_curriculo_versoes_expira", "curriculo_versoes", ["expira_em"], unique=False)
    op.create_table(
        "processos_recrutador",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("usuario_id", sa.UUID(), nullable=False),
        sa.Column("vaga_id", sa.UUID(), nullable=False),
        sa.Column("titulo", sa.String(length=200), nullable=False),
        sa.Column(
            "criado_em", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["usuario_id"],
            ["usuarios.id"],
            name=op.f("fk_processos_recrutador_usuario_id_usuarios"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["vaga_id"],
            ["vagas.id"],
            name=op.f("fk_processos_recrutador_vaga_id_vagas"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_processos_recrutador")),
    )
    op.create_table(
        "analises",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("usuario_id", sa.UUID(), nullable=False),
        sa.Column("curriculo_versao_id", sa.UUID(), nullable=False),
        sa.Column("vaga_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "etapas",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="[{etapa, texto, em}]",
        ),
        sa.Column("nota", sa.Integer(), nullable=True),
        sa.Column(
            "decomposicao",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="{texto, parcelas, anos_relevantes, anos_minimos}",
        ),
        sa.Column(
            "tabela",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="Linhas requisito × evidência (LinhaRequisito).",
        ),
        sa.Column("feedback", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("avisos", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "estatisticas",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="Contagens da ancoragem e do filtro (sem conteúdo).",
        ),
        sa.Column("custo_usd", sa.Numeric(precision=12, scale=6), nullable=False),
        sa.Column("provedor", sa.String(length=20), nullable=True),
        sa.Column("modelos", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("erro_codigo", sa.String(length=60), nullable=True),
        sa.Column("erro_mensagem", sa.Text(), nullable=True),
        sa.Column(
            "criado_em", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("iniciado_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column("concluido_em", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('na_fila', 'processando', 'concluida', 'erro')",
            name=op.f("ck_analises_status"),
        ),
        sa.ForeignKeyConstraint(
            ["curriculo_versao_id"],
            ["curriculo_versoes.id"],
            name=op.f("fk_analises_curriculo_versao_id_curriculo_versoes"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["usuario_id"],
            ["usuarios.id"],
            name=op.f("fk_analises_usuario_id_usuarios"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["vaga_id"], ["vagas.id"], name=op.f("fk_analises_vaga_id_vagas"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_analises")),
    )
    op.create_index(
        "ix_analises_usuario_criado", "analises", ["usuario_id", "criado_em", "id"], unique=False
    )
    op.create_index(
        "ix_analises_versao_vaga", "analises", ["curriculo_versao_id", "vaga_id"], unique=False
    )
    op.create_table(
        "candidatos",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("processo_id", sa.UUID(), nullable=False),
        sa.Column("usuario_id", sa.UUID(), nullable=False),
        sa.Column("rotulo", sa.String(length=40), nullable=False),
        sa.Column("curriculo_versao_id", sa.UUID(), nullable=False),
        sa.Column("analise_id", sa.UUID(), nullable=False),
        sa.Column(
            "criado_em", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "identidade_revelada_em",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Revelar é ação explícita do recrutador (ADR 0004).",
        ),
        sa.ForeignKeyConstraint(
            ["analise_id"],
            ["analises.id"],
            name=op.f("fk_candidatos_analise_id_analises"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["curriculo_versao_id"],
            ["curriculo_versoes.id"],
            name=op.f("fk_candidatos_curriculo_versao_id_curriculo_versoes"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["processo_id"],
            ["processos_recrutador.id"],
            name=op.f("fk_candidatos_processo_id_processos_recrutador"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["usuario_id"],
            ["usuarios.id"],
            name=op.f("fk_candidatos_usuario_id_usuarios"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_candidatos")),
        sa.UniqueConstraint("processo_id", "rotulo", name="uq_candidatos_rotulo"),
    )
    op.create_table(
        "decisoes_humanas",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("candidato_id", sa.UUID(), nullable=False),
        sa.Column("usuario_id", sa.UUID(), nullable=False),
        sa.Column("decisao", sa.String(length=20), nullable=False),
        sa.Column("justificativa", sa.Text(), nullable=False),
        sa.Column(
            "criado_em", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "decisao IN ('avancar', 'nao_avancar', 'pendente')",
            name=op.f("ck_decisoes_humanas_decisao"),
        ),
        sa.CheckConstraint(
            "length(btrim(justificativa)) > 0", name=op.f("ck_decisoes_humanas_justificativa")
        ),
        sa.ForeignKeyConstraint(
            ["candidato_id"],
            ["candidatos.id"],
            name=op.f("fk_decisoes_humanas_candidato_id_candidatos"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["usuario_id"],
            ["usuarios.id"],
            name=op.f("fk_decisoes_humanas_usuario_id_usuarios"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_decisoes_humanas")),
    )
    op.create_index(
        "ix_decisoes_candidato", "decisoes_humanas", ["candidato_id", "criado_em"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_decisoes_candidato", table_name="decisoes_humanas")
    op.drop_table("decisoes_humanas")
    op.drop_table("candidatos")
    op.drop_index("ix_analises_versao_vaga", table_name="analises")
    op.drop_index("ix_analises_usuario_criado", table_name="analises")
    op.drop_table("analises")
    op.drop_table("processos_recrutador")
    op.drop_index("ix_curriculo_versoes_expira", table_name="curriculo_versoes")
    op.drop_table("curriculo_versoes")
    op.drop_table("vagas")
    op.drop_table("uso_diario")
    op.drop_table("sessoes")
    op.drop_index("ix_curriculos_usuario", table_name="curriculos")
    op.drop_table("curriculos")
    op.drop_table("consentimentos")
    op.drop_index(
        "ix_vetores_taxonomia_hnsw",
        table_name="vetores_taxonomia",
        postgresql_using="hnsw",
        postgresql_ops={"vetor": "vector_cosine_ops"},
    )
    op.drop_table("vetores_taxonomia")
    op.drop_index("uq_usuarios_email_minusculo", table_name="usuarios")
    op.drop_table("usuarios")
