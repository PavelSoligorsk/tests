"""board object_count and student lookup indexes

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-10-18 22:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e6f7a8b9c0d1"
down_revision: Union[str, Sequence[str], None] = "d5e6f7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "boards",
        sa.Column("object_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.execute(
        "UPDATE boards SET object_count = COALESCE(json_array_length(objects), 0)"
    )
    op.create_index("ix_board_students_student_id", "board_students", ["student_id"])
    op.create_index("ix_group_students_student_id", "group_students", ["student_id"])
    op.create_index("ix_teacher_students_student_id", "teacher_students", ["student_id"])
    op.create_index("ix_boards_teacher_updated", "boards", ["teacher_id", "updated_at"])
    op.drop_index("ix_boards_teacher_id", table_name="boards")


def downgrade() -> None:
    op.create_index("ix_boards_teacher_id", "boards", ["teacher_id"])
    op.drop_index("ix_boards_teacher_updated", table_name="boards")
    op.drop_index("ix_teacher_students_student_id", table_name="teacher_students")
    op.drop_index("ix_group_students_student_id", table_name="group_students")
    op.drop_index("ix_board_students_student_id", table_name="board_students")
    op.drop_column("boards", "object_count")
