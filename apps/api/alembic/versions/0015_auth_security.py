"""Add revocable sessions and persistent OAuth authorization state.

Revision ID: 0015
Revises: 0014
Create Date: 2026-08-04
"""

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "user_id", sa.String(32), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("secret_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_reason", sa.String(80), nullable=True),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"])
    op.create_table(
        "login_attempts",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("client_ip", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_login_attempts_client_ip", "login_attempts", ["client_ip"])
    op.create_index("ix_login_attempts_created_at", "login_attempts", ["created_at"])
    op.create_table(
        "oauth_authorization_states",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("state_hash", sa.String(64), nullable=False),
        sa.Column(
            "user_id", sa.String(32), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "auth_session_id",
            sa.String(32),
            sa.ForeignKey("auth_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(30), nullable=False),
        sa.Column("code_verifier_encrypted", sa.Text(), nullable=False),
        sa.Column("redirect_uri", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("state_hash", name="uq_oauth_authorization_states_state_hash"),
    )
    op.create_index(
        "ix_oauth_authorization_states_user_id", "oauth_authorization_states", ["user_id"]
    )
    op.create_index(
        "ix_oauth_authorization_states_auth_session_id",
        "oauth_authorization_states",
        ["auth_session_id"],
    )
    op.create_index(
        "ix_oauth_authorization_states_expires_at", "oauth_authorization_states", ["expires_at"]
    )


def downgrade() -> None:
    op.drop_table("oauth_authorization_states")
    op.drop_table("login_attempts")
    op.drop_table("auth_sessions")
