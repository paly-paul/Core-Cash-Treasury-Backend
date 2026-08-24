"""create fx rates and system config

Revision ID: 003
Revises: 002
Create Date: 2026-08-23

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fx_rates",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("client_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("currency_from", sa.String(3), nullable=False),
        sa.Column("currency_to", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("rate", sa.Numeric(18, 6), nullable=False),
        sa.Column("rate_date", sa.Date(), nullable=False),
        sa.Column("entered_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entered_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["client_id"], ["client.id"]),
        sa.ForeignKeyConstraint(["entered_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_id", "currency_from", "rate_date"),
    )

    op.create_table(
        "system_config",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("client_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("config_key", sa.String(100), nullable=False),
        sa.Column("config_val", sa.Text(), nullable=False),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["client_id"], ["client.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_id", "config_key"),
    )


def downgrade() -> None:
    op.drop_table("system_config")
    op.drop_table("fx_rates")
