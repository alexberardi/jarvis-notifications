"""Initial tables: device_tokens and notification_log

Revision ID: 001
Revises:
Create Date: 2026-03-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "device_tokens",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.Integer, nullable=False, index=True),
        sa.Column("household_id", sa.String(255), nullable=False, index=True),
        sa.Column("push_token", sa.String(255), unique=True, nullable=False, index=True),
        sa.Column("device_type", sa.String(20), nullable=False),
        sa.Column("device_name", sa.String(255), nullable=True),
        sa.Column("is_active", sa.Boolean, default=True, nullable=False),
        sa.Column("last_used_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "notification_log",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source_service", sa.String(255), nullable=False, index=True),
        sa.Column("target_type", sa.String(20), nullable=False),
        sa.Column("target_id", sa.String(255), nullable=False, index=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("data", sa.Text, nullable=True),
        sa.Column("category", sa.String(50), nullable=True),
        sa.Column("token_count", sa.Integer, default=0, nullable=False),
        sa.Column("success_count", sa.Integer, default=0, nullable=False),
        sa.Column("failure_count", sa.Integer, default=0, nullable=False),
        sa.Column("delivery_status", sa.String(20), default="pending", nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("notification_log")
    op.drop_table("device_tokens")
