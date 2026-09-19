"""add theory_class and priority to theory

Revision ID: b7c8d9e0f1a2
Revises: a1b2c3d4e5f6
Create Date: 2026-09-19 11:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "b7c8d9e0f1a2"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(inspector, table: str, column: str) -> bool:
    return any(c["name"] == column for c in inspector.get_columns(table))


def _has_constraint(inspector, table: str, name: str) -> bool:
    return any(uc["name"] == name for uc in inspector.get_unique_constraints(table))


def _has_index(inspector, table: str, name: str) -> bool:
    return any(ix["name"] == name for ix in inspector.get_indexes(table))


def _has_check(inspector, table: str, name: str) -> bool:
    return any(ck["name"] == name for ck in inspector.get_check_constraints(table))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if not _has_column(inspector, "theory", "theory_class"):
        op.add_column(
            "theory",
            sa.Column("theory_class", sa.Integer(), nullable=False, server_default="5"),
        )
    if not _has_column(inspector, "theory", "priority"):
        op.add_column(
            "theory",
            sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        )

    inspector = inspect(bind)
    for uc in inspector.get_unique_constraints("theory"):
        name = uc["name"]
        cols = set(uc.get("column_names") or [])
        if name == "unique_class_topic_section":
            continue
        if {"topic", "section"} <= cols:
            op.drop_constraint(name, "theory", type_="unique")

    inspector = inspect(bind)
    for ix in inspector.get_indexes("theory"):
        name = ix["name"]
        cols = set(ix.get("column_names") or [])
        if ix.get("unique") and {"topic", "section"} <= cols and name != "unique_class_topic_section":
            op.drop_index(name, table_name="theory")

    inspector = inspect(bind)
    if not _has_constraint(inspector, "theory", "unique_class_topic_section"):
        op.create_unique_constraint(
            "unique_class_topic_section",
            "theory",
            ["theory_class", "topic", "section"],
        )
    if not _has_index(inspector, "theory", "ix_theory_theory_class"):
        op.create_index("ix_theory_theory_class", "theory", ["theory_class"])
    if not _has_check(inspector, "theory", "ck_theory_class_range"):
        op.create_check_constraint(
            "ck_theory_class_range",
            "theory",
            "theory_class >= 5 AND theory_class <= 11",
        )

    op.alter_column("theory", "theory_class", server_default=None)
    op.alter_column("theory", "priority", server_default=None)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if _has_check(inspector, "theory", "ck_theory_class_range"):
        op.drop_constraint("ck_theory_class_range", "theory", type_="check")
    if _has_constraint(inspector, "theory", "unique_class_topic_section"):
        op.drop_constraint("unique_class_topic_section", "theory", type_="unique")
    if _has_index(inspector, "theory", "ix_theory_theory_class"):
        op.drop_index("ix_theory_theory_class", table_name="theory")
    if _has_column(inspector, "theory", "priority"):
        op.drop_column("theory", "priority")
    if _has_column(inspector, "theory", "theory_class"):
        op.drop_column("theory", "theory_class")
    op.create_unique_constraint("unique_topic_section", "theory", ["topic", "section"])
