"""add forecast assumption columns

Revision ID: 007
Revises: 006
Create Date: 2026-08-24

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "manual_assumptions",
        sa.Column("date", sa.Date(), nullable=True),
    )
    op.add_column(
        "manual_assumptions",
        sa.Column("category", sa.String(50), nullable=True),
    )
    op.add_column(
        "manual_assumptions",
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
    )
    op.add_column(
        "manual_assumptions",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("manual_assumptions", "deleted_at")
    op.drop_column("manual_assumptions", "updated_at")
    op.drop_column("manual_assumptions", "category")
    op.drop_column("manual_assumptions", "date")
