"""Rodada 1 da revisão da fase 4: teto diário com reserva atômica, auditoria do recrutador e
retenção das justificativas.

Revisão: 0002
Anterior: 0001
Criada em: 2026-11-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "uso_diario",
        sa.Column(
            "reservado_usd",
            sa.Numeric(precision=12, scale=6),
            server_default="0",
            nullable=False,
            comment="Pior caso das análises aceitas e ainda não terminadas (teto atômico).",
        ),
    )
    op.add_column(
        "analises",
        sa.Column(
            "reserva_usd",
            sa.Numeric(precision=12, scale=6),
            server_default="0",
            nullable=False,
            comment="O que esta análise reservou do teto diário no envio (devolvido ao terminar).",
        ),
    )
    op.drop_constraint(op.f("ck_decisoes_humanas_justificativa"), "decisoes_humanas", type_="check")
    op.alter_column(
        "decisoes_humanas",
        "justificativa",
        existing_type=sa.Text(),
        nullable=True,
        comment="Obrigatória ao decidir; nula depois da retenção (sobre terceiros).",
    )
    op.create_check_constraint(
        op.f("ck_decisoes_humanas_justificativa"),
        "decisoes_humanas",
        "justificativa IS NULL OR length(btrim(justificativa)) > 0",
    )
    op.add_column(
        "decisoes_humanas",
        sa.Column("justificativa_apagada_em", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "auditoria_recrutador",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("usuario_id", sa.UUID(), nullable=False),
        sa.Column("candidato_id", sa.UUID(), nullable=False),
        sa.Column("acao", sa.String(length=20), nullable=False),
        sa.Column(
            "em", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "acao IN ('revelar', 'baixar_arquivo')", name=op.f("ck_auditoria_recrutador_acao")
        ),
        sa.ForeignKeyConstraint(
            ["candidato_id"],
            ["candidatos.id"],
            name=op.f("fk_auditoria_recrutador_candidato_id_candidatos"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["usuario_id"],
            ["usuarios.id"],
            name=op.f("fk_auditoria_recrutador_usuario_id_usuarios"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auditoria_recrutador")),
    )
    op.create_index(
        "ix_auditoria_candidato", "auditoria_recrutador", ["candidato_id", "em"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_auditoria_candidato", table_name="auditoria_recrutador")
    op.drop_table("auditoria_recrutador")
    op.drop_column("decisoes_humanas", "justificativa_apagada_em")
    op.drop_constraint(op.f("ck_decisoes_humanas_justificativa"), "decisoes_humanas", type_="check")
    op.execute("UPDATE decisoes_humanas SET justificativa = '—' WHERE justificativa IS NULL")
    op.alter_column("decisoes_humanas", "justificativa", existing_type=sa.Text(), nullable=False)
    op.create_check_constraint(
        op.f("ck_decisoes_humanas_justificativa"),
        "decisoes_humanas",
        "length(btrim(justificativa)) > 0",
    )
    op.drop_column("analises", "reserva_usd")
    op.drop_column("uso_diario", "reservado_usd")
