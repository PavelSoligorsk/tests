"""personal boards can be opened by a share link

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
Create Date: 2026-10-22 13:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f7a8b9c0d1e2"
down_revision: Union[str, Sequence[str], None] = "e6f7a8b9c0d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("boards", sa.Column("share_token", sa.String(length=64), nullable=True))
    op.add_column(
        "boards",
        sa.Column("share_access", sa.String(length=8), nullable=False, server_default="off"),
    )
    op.create_index("ix_boards_share_token", "boards", ["share_token"], unique=True)
    op.create_check_constraint(
        "ck_boards_share_access",
        "boards",
        "share_access IN ('off', 'view', 'edit')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_boards_share_access", "boards", type_="check")
    op.drop_index("ix_boards_share_token", table_name="boards")
    op.drop_column("boards", "share_access")
    op.drop_column("boards", "share_token")
