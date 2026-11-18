"""board pages belong to a collection row

Страницы одного ученика, одной группы и все личные доски учителя
собираются в строку board_collections. id коллекции — id самой ранней
страницы. Номер страницы идёт по дате создания.

Revision ID: b0c1d2e3f4a5
Revises: a9b8c7d6e5f4
Create Date: 2026-11-19 02:10:00.000000

"""
from collections import defaultdict
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b0c1d2e3f4a5"
down_revision: Union[str, Sequence[str], None] = "a9b8c7d6e5f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


boards = sa.table(
    "boards",
    sa.column("id", sa.Uuid),
    sa.column("teacher_id", sa.Integer),
    sa.column("group_id", sa.Integer),
    sa.column("created_at", sa.DateTime),
    sa.column("series_id", sa.Uuid),
    sa.column("page_number", sa.Integer),
)
board_students = sa.table(
    "board_students",
    sa.column("board_id", sa.Uuid),
    sa.column("student_id", sa.Integer),
)
collections = sa.table(
    "board_collections",
    sa.column("id", sa.Uuid),
    sa.column("teacher_id", sa.Integer),
    sa.column("kind", sa.String),
    sa.column("student_id", sa.Integer),
    sa.column("group_id", sa.Integer),
    sa.column("title", sa.String),
    sa.column("created_at", sa.DateTime),
)


def upgrade() -> None:
    op.create_table(
        "board_collections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("teacher_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=True),
        sa.Column("group_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "(kind = 'student' AND group_id IS NULL AND title IS NULL) OR "
            "(kind = 'group' AND student_id IS NULL AND title IS NULL) OR "
            "(kind = 'personal' AND student_id IS NULL AND group_id IS NULL AND title IS NOT NULL) OR "
            "(kind = 'legacy' AND student_id IS NULL AND group_id IS NULL AND title IS NULL)",
            name="ck_board_collections_shape",
        ),
        sa.ForeignKeyConstraint(["teacher_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["student_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_board_collections_teacher_id", "board_collections", ["teacher_id"])
    op.create_index(
        "uq_board_collections_student",
        "board_collections",
        ["teacher_id", "student_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'student'"),
    )
    op.create_index(
        "uq_board_collections_group",
        "board_collections",
        ["teacher_id", "group_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'group' AND group_id IS NOT NULL"),
    )
    op.add_column("boards", sa.Column("page_number", sa.Integer(), nullable=True, server_default="1"))

    conn = op.get_bind()
    members: dict = defaultdict(list)
    for board_id, student_id in conn.execute(sa.select(board_students.c.board_id, board_students.c.student_id)):
        members[board_id].append(student_id)

    grouped: dict = defaultdict(list)
    rows = conn.execute(
        sa.select(boards.c.id, boards.c.teacher_id, boards.c.group_id, boards.c.created_at)
        .order_by(boards.c.created_at, boards.c.id)
    )
    for board_id, teacher_id, group_id, created_at in rows:
        students = members.get(board_id, [])
        if group_id is not None:
            key = ("group", teacher_id, group_id)
        elif len(students) > 1:
            key = ("legacy", teacher_id, tuple(sorted(students)))
        elif len(students) == 1:
            key = ("student", teacher_id, students[0])
        else:
            key = ("personal", teacher_id)
        grouped[key].append((board_id, teacher_id, group_id, created_at, students))

    for key, pages in grouped.items():
        head_id, teacher_id, group_id, created_at, students = pages[0]
        kind = key[0]
        conn.execute(collections.insert().values(
            id=head_id,
            teacher_id=teacher_id,
            kind=kind,
            student_id=students[0] if kind == "student" else None,
            group_id=group_id if kind == "group" else None,
            title="Черновик" if kind == "personal" else None,
            created_at=created_at,
        ))
        for number, (board_id, *_) in enumerate(pages, start=1):
            conn.execute(
                sa.update(boards)
                .where(boards.c.id == board_id)
                .values(series_id=head_id, page_number=number)
            )

    op.alter_column("boards", "page_number", nullable=False, server_default="1")
    op.alter_column("boards", "series_id", nullable=False)
    op.create_foreign_key(
        "boards_series_id_fkey", "boards", "board_collections", ["series_id"], ["id"], ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("boards_series_id_fkey", "boards", type_="foreignkey")
    op.alter_column("boards", "series_id", nullable=True)
    op.drop_column("boards", "page_number")
    op.drop_index("uq_board_collections_group", table_name="board_collections")
    op.drop_index("uq_board_collections_student", table_name="board_collections")
    op.drop_index("ix_board_collections_teacher_id", table_name="board_collections")
    op.drop_table("board_collections")
