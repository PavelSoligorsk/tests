"""boards belong to students or a group, not a lesson

Revision ID: d5e6f7a8b9c0
Revises: c4b0a1d2e3f4
Create Date: 2026-09-28 10:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d5e6f7a8b9c0"
down_revision: Union[str, Sequence[str], None] = "c4b0a1d2e3f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Старые строки были привязаны к занятию. Та модель больше не используется.
    op.execute("DELETE FROM board_images")
    op.execute("DELETE FROM boards")
    op.drop_index("uq_boards_student_per_lesson", table_name="boards")
    op.drop_index("uq_boards_one_class_per_lesson", table_name="boards")
    op.drop_index("ix_boards_owner_id", table_name="boards")
    op.drop_index("ix_boards_lesson_id", table_name="boards")
    op.drop_constraint("ck_boards_kind_owner", "boards", type_="check")
    op.drop_constraint("ck_boards_kind", "boards", type_="check")
    op.drop_constraint("boards_lesson_id_fkey", "boards", type_="foreignkey")
    op.drop_constraint("boards_owner_id_fkey", "boards", type_="foreignkey")
    op.drop_column("boards", "owner_id")
    op.drop_column("boards", "kind")
    op.drop_column("boards", "lesson_id")

    op.add_column("boards", sa.Column("teacher_id", sa.Integer(), nullable=False))
    op.add_column("boards", sa.Column("group_id", sa.Integer(), nullable=True))
    op.create_foreign_key("boards_teacher_id_fkey", "boards", "users", ["teacher_id"], ["id"], ondelete="CASCADE")
    op.create_foreign_key("boards_group_id_fkey", "boards", "groups", ["group_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_boards_teacher_id", "boards", ["teacher_id"])
    op.create_index("ix_boards_group_id", "boards", ["group_id"])

    op.create_table(
        "board_students",
        sa.Column("board_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["board_id"], ["boards.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["student_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("board_id", "student_id"),
    )


def downgrade() -> None:
    op.drop_table("board_students")
    op.drop_index("ix_boards_group_id", table_name="boards")
    op.drop_index("ix_boards_teacher_id", table_name="boards")
    op.drop_constraint("boards_group_id_fkey", "boards", type_="foreignkey")
    op.drop_constraint("boards_teacher_id_fkey", "boards", type_="foreignkey")
    op.drop_column("boards", "group_id")
    op.drop_column("boards", "teacher_id")

    op.add_column("boards", sa.Column("lesson_id", sa.Integer(), nullable=True))
    op.add_column("boards", sa.Column("kind", sa.String(length=20), nullable=False))
    op.add_column("boards", sa.Column("owner_id", sa.Integer(), nullable=True))
    op.create_foreign_key("boards_lesson_id_fkey", "boards", "lessons", ["lesson_id"], ["id"], ondelete="CASCADE")
    op.create_foreign_key("boards_owner_id_fkey", "boards", "users", ["owner_id"], ["id"], ondelete="CASCADE")
    op.create_check_constraint("ck_boards_kind", "boards", "kind IN ('class', 'student', 'draft')")
    op.create_check_constraint(
        "ck_boards_kind_owner",
        "boards",
        "(kind = 'class' AND owner_id IS NULL AND lesson_id IS NOT NULL) OR "
        "(kind = 'student' AND owner_id IS NOT NULL AND lesson_id IS NOT NULL) OR "
        "(kind = 'draft' AND owner_id IS NOT NULL AND lesson_id IS NULL)",
    )
    op.create_index("ix_boards_lesson_id", "boards", ["lesson_id"])
    op.create_index("ix_boards_owner_id", "boards", ["owner_id"])
    op.create_index(
        "uq_boards_one_class_per_lesson",
        "boards",
        ["lesson_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'class'"),
    )
    op.create_index(
        "uq_boards_student_per_lesson",
        "boards",
        ["lesson_id", "owner_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'student'"),
    )
