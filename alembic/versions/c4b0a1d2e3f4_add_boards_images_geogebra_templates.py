"""add boards, board images, and geogebra templates

Revision ID: c4b0a1d2e3f4
Revises: b7c8d9e0f1a2
Create Date: 2026-09-28 01:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c4b0a1d2e3f4"
down_revision: Union[str, Sequence[str], None] = "b7c8d9e0f1a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "boards",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("lesson_id", sa.Integer(), nullable=True),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("camera", sa.JSON(), nullable=False),
        sa.Column("objects", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["lesson_id"], ["lessons.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.CheckConstraint("kind IN ('class', 'student', 'draft')", name="ck_boards_kind"),
        sa.CheckConstraint(
            "(kind = 'class' AND owner_id IS NULL AND lesson_id IS NOT NULL) OR "
            "(kind = 'student' AND owner_id IS NOT NULL AND lesson_id IS NOT NULL) OR "
            "(kind = 'draft' AND owner_id IS NOT NULL AND lesson_id IS NULL)",
            name="ck_boards_kind_owner",
        ),
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

    op.create_table(
        "board_images",
        sa.Column("file_id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("board_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("r2_key", sa.String(length=512), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=64), nullable=False),
        sa.Column("uploaded_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["board_id"], ["boards.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploaded_by"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_board_images_board_id", "board_images", ["board_id"])

    op.create_table(
        "geogebra_templates",
        sa.Column("teacher_id", sa.Integer(), nullable=False),
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("app_name", sa.String(length=20), nullable=False),
        sa.Column("ggb_base64", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["teacher_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("teacher_id", "id"),
        sa.CheckConstraint("app_name IN ('geometry', 'graphing')", name="ck_ggb_app_name"),
    )


def downgrade() -> None:
    op.drop_table("geogebra_templates")
    op.drop_index("ix_board_images_board_id", table_name="board_images")
    op.drop_table("board_images")
    op.drop_index("uq_boards_student_per_lesson", table_name="boards")
    op.drop_index("uq_boards_one_class_per_lesson", table_name="boards")
    op.drop_index("ix_boards_owner_id", table_name="boards")
    op.drop_index("ix_boards_lesson_id", table_name="boards")
    op.drop_table("boards")
