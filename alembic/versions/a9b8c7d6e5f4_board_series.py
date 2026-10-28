"""board pages are linked by an explicit series id

Раньше страницы доски собирались на фронте по совпадению аудитории. Миграция
сохраняет эту группировку для старых досок (в пределах учителя), а доска без
учеников и группы становится серией сама по себе.

Revision ID: a9b8c7d6e5f4
Revises: f7a8b9c0d1e2
Create Date: 2026-10-27 22:40:00.000000

"""
from collections import defaultdict
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a9b8c7d6e5f4"
down_revision: Union[str, Sequence[str], None] = "f7a8b9c0d1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


boards = sa.table(
    "boards",
    sa.column("id", sa.Uuid),
    sa.column("teacher_id", sa.Integer),
    sa.column("group_id", sa.Integer),
    sa.column("created_at", sa.DateTime),
    sa.column("series_id", sa.Uuid),
)
board_students = sa.table(
    "board_students",
    sa.column("board_id", sa.Uuid),
    sa.column("student_id", sa.Integer),
)


def upgrade() -> None:
    op.add_column("boards", sa.Column("series_id", sa.Uuid(), nullable=True))
    op.create_index("ix_boards_series_id", "boards", ["series_id"])

    conn = op.get_bind()
    members: dict = defaultdict(list)
    for board_id, student_id in conn.execute(sa.select(board_students.c.board_id, board_students.c.student_id)):
        members[board_id].append(student_id)

    first_of: dict = {}
    rows = conn.execute(
        sa.select(boards.c.id, boards.c.teacher_id, boards.c.group_id)
        .order_by(boards.c.created_at, boards.c.id)
    )
    for board_id, teacher_id, group_id in rows:
        if group_id is not None:
            key = (teacher_id, f"g:{group_id}")
        elif members.get(board_id):
            key = (teacher_id, "s:" + ",".join(str(item) for item in sorted(members[board_id])))
        else:
            key = None
        series = first_of.setdefault(key, board_id) if key else board_id
        conn.execute(sa.update(boards).where(boards.c.id == board_id).values(series_id=series))


def downgrade() -> None:
    op.drop_index("ix_boards_series_id", table_name="boards")
    op.drop_column("boards", "series_id")
