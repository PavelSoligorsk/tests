"""add_recur_until_to_lesson_schedules

Revision ID: e91f4a2b8c3d
Revises: daf3e2c7d136
Create Date: 2026-07-28 17:12:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e91f4a2b8c3d'
down_revision: Union[str, Sequence[str], None] = 'daf3e2c7d136'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('lesson_schedules', sa.Column('recur_until', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('lesson_schedules', 'recur_until')
