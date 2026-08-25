"""custom auth - replace cognito with password auth and explicit permissions

Revision ID: 008
Revises: 007
Create Date: 2026-08-25

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Update users table - replace cognito fields with password auth
    op.add_column("users", sa.Column("password_hash", sa.String(255), nullable=False, server_default=""))
    op.add_column("users", sa.Column("full_name", sa.String(255)))
    op.add_column("users", sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"))
    op.add_column("users", sa.Column("is_admin", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("users", sa.Column("mfa_enabled", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("users", sa.Column("mfa_secret", sa.String(255)))
    op.add_column("users", sa.Column("last_login_at", sa.DateTime()))
    op.add_column("users", sa.Column("password_changed_at", sa.DateTime(), server_default=sa.text("now()")))
    op.add_column("users", sa.Column("created_by", sa.String(255)))
    op.add_column("users", sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()")))
    op.add_column("users", sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()")))

    # Drop old Cognito columns
    op.drop_column("users", "cognito_sub")
    op.drop_column("users", "role")

    # Create unique constraint on client_id, email
    op.create_unique_constraint(None, "users", ["client_id", "email"])

    # Create indexes
    op.create_index("idx_users_client_email", "users", ["client_id", "email"])
    op.create_index("idx_users_active", "users", ["client_id", "is_active"])

    # Create refresh_tokens table
    op.create_table(
        "refresh_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(255), nullable=False),
        sa.Column("device_hint", sa.String(255)),
        sa.Column("ip_address", sa.String(50)),
        sa.Column("issued_at", sa.DateTime(), server_default=sa.text("now()")),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime()),
        sa.ForeignKeyConstraint(["client_id"], ["client.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("idx_refresh_tokens_user", "refresh_tokens", ["user_id"])
    op.create_index("idx_refresh_tokens_hash", "refresh_tokens", ["token_hash"])

    # Create password_reset_tokens table
    op.create_table(
        "password_reset_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(255), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("idx_password_reset_tokens_user", "password_reset_tokens", ["user_id"])
    op.create_index("idx_password_reset_tokens_hash", "password_reset_tokens", ["token_hash"])

    # Create user_permissions table
    op.create_table(
        "user_permissions",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("client_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("permission", sa.String(100), nullable=False),
        sa.Column("grant_type", sa.String(10), nullable=False),
        sa.Column("granted_by", postgresql.UUID(as_uuid=True)),
        sa.Column("reason", sa.Text()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()")),
        sa.Column("expires_at", sa.DateTime()),
        sa.ForeignKeyConstraint(["client_id"], ["client.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["granted_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_id", "user_id", "permission"),
    )
    op.create_index("idx_user_permissions_lookup", "user_permissions", ["client_id", "user_id"])

    # Create permission_templates table
    op.create_table(
        "permission_templates",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("client_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("permissions", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True)),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["client_id"], ["client.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_id", "name"),
    )


def downgrade() -> None:
    op.drop_table("permission_templates")
    op.drop_table("user_permissions")
    op.drop_table("password_reset_tokens")
    op.drop_table("refresh_tokens")

    # Restore Cognito columns
    op.add_column("users", sa.Column("role", sa.String(50), nullable=False, server_default="Viewer"))
    op.add_column("users", sa.Column("cognito_sub", sa.String(255), unique=True))

    # Drop new columns
    op.drop_index("idx_users_active", table_name="users")
    op.drop_index("idx_users_client_email", table_name="users")
    op.drop_constraint(None, "users", type_="unique")
    op.drop_column("users", "updated_at")
    op.drop_column("users", "created_at")
    op.drop_column("users", "created_by")
    op.drop_column("users", "password_changed_at")
    op.drop_column("users", "last_login_at")
    op.drop_column("users", "mfa_secret")
    op.drop_column("users", "mfa_enabled")
    op.drop_column("users", "is_admin")
    op.drop_column("users", "is_active")
    op.drop_column("users", "full_name")
    op.drop_column("users", "password_hash")
