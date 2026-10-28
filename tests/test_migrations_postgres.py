"""Миграции досок на настоящем PostgreSQL (в CI — сервис postgres, локально — TEST_POSTGRES_URL).

Базовой миграции нет: таблицы до досок в проде появились раньше alembic. Поэтому тест повторяет
путь прода — таблицы без досок по моделям, отметка b7c8d9e0f1a2, затем настоящие миграции досок.
"""
from __future__ import annotations

import datetime as dt
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa

PG_URL = os.getenv("TEST_POSTGRES_URL")
ROOT = Path(__file__).resolve().parent.parent
BOARD_TABLES = {"boards", "board_students", "board_images", "geogebra_templates"}
# Эти индексы есть в моделях, но в проде их создала миграция e6f7a8b9c0d1.
LATER_INDEXES = ("ix_group_students_student_id", "ix_teacher_students_student_id")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not PG_URL, reason="TEST_POSTGRES_URL не задан"),
]


def _alembic(*args: str) -> None:
    env = {**os.environ, "DATABASE_URL": PG_URL}
    out = subprocess.run(
        [sys.executable, "-m", "alembic", *args], cwd=ROOT, env=env, capture_output=True, text=True,
    )
    assert out.returncode == 0, out.stdout + out.stderr


def _fill(table: sa.Table, values: dict) -> dict:
    """Значения для обязательных колонок без default — чтобы вставка прошла NOT NULL."""
    row = dict(values)
    for col in table.columns:
        if col.name in row or col.nullable or col.server_default is not None or col.autoincrement is True:
            continue
        try:
            kind = col.type.python_type
        except NotImplementedError:
            kind = dict
        row[col.name] = {int: 0, str: "x", bool: False, float: 0.0, dict: {}, list: [],
                         dt.datetime: dt.datetime(2026, 1, 1), uuid.UUID: uuid.uuid4()}.get(kind)
    return row


@pytest.fixture()
def pg_engine():
    engine = sa.create_engine(PG_URL.replace("postgresql://", "postgresql+psycopg2://", 1))
    with engine.begin() as conn:
        conn.execute(sa.text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    from core.database import Base
    import core.models  # noqa: F401

    Base.metadata.create_all(engine, tables=[t for n, t in Base.metadata.tables.items() if n not in BOARD_TABLES])
    with engine.begin() as conn:
        for name in LATER_INDEXES:
            conn.execute(sa.text(f"DROP INDEX IF EXISTS {name}"))
    engine.dispose()
    _alembic("stamp", "b7c8d9e0f1a2")
    _alembic("upgrade", "f7a8b9c0d1e2")
    yield engine
    engine.dispose()


def _series(engine: sa.Engine, names: dict) -> dict:
    with engine.connect() as conn:
        rows = conn.execute(sa.text("SELECT id, series_id FROM boards")).all()
    return {names[board]: names.get(series) for board, series in rows}


def test_board_series_migration_groups_legacy_boards(pg_engine: sa.Engine) -> None:
    meta = sa.MetaData()
    meta.reflect(pg_engine)
    users, groups, boards, members = (meta.tables[n] for n in ("users", "groups", "boards", "board_students"))
    ids = {f"b{i}": uuid.UUID(int=i) for i in range(1, 11)}
    names = {v: k for k, v in ids.items()}
    base = dt.datetime(2026, 10, 1, 10, 0)
    # (доска, учитель, группа, ученики, минуты от base)
    legacy = [
        ("b1", 1, 1, [], 0),
        ("b2", 1, 1, [], 60),
        ("b10", 1, 1, [], 60),          # то же время, что у b2: порядок по id
        ("b3", 1, None, [3, 4], 30),
        ("b4", 1, None, [4, 3], 120),   # тот же состав в другом порядке
        ("b5", 1, None, [3], 150),
        ("b6", 1, None, [], 180),       # личная доска — серия сама по себе
        ("b7", 1, None, [], 185),
        ("b8", 2, None, [3, 4], -60),   # тот же состав у другого учителя
        ("b9", 2, 2, [], 0),
    ]
    with pg_engine.begin() as conn:
        for uid, role in ((1, "teacher"), (2, "teacher"), (3, "student"), (4, "student")):
            conn.execute(users.insert().values(_fill(users, {"id": uid, "username": f"u{uid}", "hashed_password": "!", "role": role})))
        for gid, teacher in ((1, 1), (2, 2)):
            conn.execute(groups.insert().values(_fill(groups, {"id": gid, "name": f"g{gid}", "teacher_id": teacher})))
        for name, teacher, group, students, minutes in legacy:
            at = base + dt.timedelta(minutes=minutes)
            conn.execute(boards.insert().values(_fill(boards, {
                "id": ids[name], "title": name, "teacher_id": teacher, "group_id": group,
                "created_at": at, "updated_at": at,
            })))
            for student in students:
                conn.execute(members.insert().values(_fill(members, {"board_id": ids[name], "student_id": student})))
    pg_engine.dispose()

    _alembic("upgrade", "head")
    expected = {"b1": "b1", "b2": "b1", "b10": "b1", "b3": "b3", "b4": "b3", "b5": "b5",
                "b6": "b6", "b7": "b7", "b8": "b8", "b9": "b9"}
    assert _series(pg_engine, names) == expected
    with pg_engine.connect() as conn:
        column = conn.execute(sa.text(
            "SELECT data_type, is_nullable FROM information_schema.columns "
            "WHERE table_name = 'boards' AND column_name = 'series_id'"
        )).one()
        assert tuple(column) == ("uuid", "YES")
        assert conn.execute(sa.text("SELECT 1 FROM pg_indexes WHERE indexname = 'ix_boards_series_id'")).scalar() == 1
    pg_engine.dispose()

    _alembic("downgrade", "f7a8b9c0d1e2")
    with pg_engine.connect() as conn:
        assert conn.execute(sa.text(
            "SELECT count(*) FROM information_schema.columns WHERE table_name = 'boards' AND column_name = 'series_id'"
        )).scalar() == 0
        assert conn.execute(sa.text("SELECT count(*) FROM boards")).scalar() == len(legacy)
    pg_engine.dispose()

    _alembic("upgrade", "head")
    assert _series(pg_engine, names) == expected
