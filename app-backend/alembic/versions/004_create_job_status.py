"""create job status tracking

Revision ID: 004
Revises: 003
Create Date: 2026-08-23

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "job_status",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("client_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_type", sa.String(50), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("requested_by", postgresql.UUID(as_uuid=True)),
        sa.Column("requested_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("result_id", sa.Text()),
        sa.Column("error_message", sa.Text()),
        sa.ForeignKeyConstraint(["client_id"], ["client.id"]),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id"),
    )

    op.create_index("idx_job_status_job_id", "job_status", ["job_id"])
    op.create_index("idx_job_status_client_id_status", "job_status", ["client_id", "status"])


def downgrade() -> None:
    op.drop_index("idx_job_status_client_id_status", "job_status")
    op.drop_index("idx_job_status_job_id", "job_status")
    op.drop_table("job_status")
