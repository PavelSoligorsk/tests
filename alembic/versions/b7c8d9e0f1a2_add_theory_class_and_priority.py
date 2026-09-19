"""add theory_class and priority to theory

Revision ID: b7c8d9e0f1a2
Revises: a1b2c3d4e5f6
Create Date: 2026-09-19 11:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b7c8d9e0f1a2"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "theory",
        sa.Column("theory_class", sa.Integer(), nullable=False, server_default="5"),
    )
    op.add_column(
        "theory",
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
    )
    op.drop_constraint("unique_topic_section", "theory", type_="unique")
    op.create_unique_constraint(
        "unique_class_topic_section",
        "theory",
        ["theory_class", "topic", "section"],
    )
    op.create_index("ix_theory_theory_class", "theory", ["theory_class"])
    op.create_check_constraint(
        "ck_theory_class_range",
        "theory",
        "theory_class >= 5 AND theory_class <= 11",
    )
    op.alter_column("theory", "theory_class", server_default=None)
    op.alter_column("theory", "priority", server_default=None)


def downgrade() -> None:
    op.drop_constraint("ck_theory_class_range", "theory", type_="check")
    op.drop_constraint("unique_class_topic_section", "theory", type_="unique")
    op.drop_index("ix_theory_theory_class", table_name="theory")
    op.drop_column("theory", "priority")
    op.drop_column("theory", "theory_class")
    op.create_unique_constraint("unique_topic_section", "theory", ["topic", "section"])
