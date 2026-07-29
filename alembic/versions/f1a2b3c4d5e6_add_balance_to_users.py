"""add_balance_to_users

Revision ID: f1a2b3c4d5e6
Revises: e91f4a2b8c3d
Create Date: 2026-07-28 19:12:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = 'e91f4a2b8c3d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('balance', sa.Integer(), nullable=True, server_default='0'))


def downgrade() -> None:
    op.drop_column('users', 'balance')
