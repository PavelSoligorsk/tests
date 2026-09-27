from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import Board, BoardImage, GeogebraTemplate, GroupStudent, Lesson, TeacherStudent


class BoardRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_lesson(self, lesson_id: int) -> Optional[Lesson]:
        result = await self.db.execute(select(Lesson).where(Lesson.id == lesson_id))
        return result.scalars().first()

    async def get_board(self, board_id: uuid.UUID) -> Optional[Board]:
        result = await self.db.execute(select(Board).where(Board.id == board_id))
        return result.scalars().first()

    async def list_for_lesson(self, lesson_id: int) -> list[Board]:
        result = await self.db.execute(select(Board).where(Board.lesson_id == lesson_id))
        return list(result.scalars().all())

    async def list_for_student(self, student_id: int) -> list[Board]:
        result = await self.db.execute(
            select(Board)
            .where(
                Board.owner_id == student_id,
                Board.kind.in_(("draft", "student")),
            )
            .order_by(Board.updated_at.desc(), Board.created_at.desc())
        )
        return list(result.scalars().all())

    async def group_student_ids(self, group_id: int) -> list[int]:
        result = await self.db.execute(
            select(GroupStudent.student_id).where(GroupStudent.group_id == group_id)
        )
        return [row[0] for row in result.all()]

    async def student_in_group(self, group_id: int, student_id: int) -> bool:
        result = await self.db.execute(
            select(GroupStudent.student_id).where(
                GroupStudent.group_id == group_id,
                GroupStudent.student_id == student_id,
            )
        )
        return result.first() is not None

    async def teacher_ids_for_student(self, student_id: int) -> list[int]:
        result = await self.db.execute(
            select(TeacherStudent.teacher_id)
            .where(TeacherStudent.student_id == student_id)
            .order_by(TeacherStudent.teacher_id.asc())
        )
        return [row[0] for row in result.all()]

    def add_board(self, board: Board) -> None:
        self.db.add(board)

    async def delete_board(self, board: Board) -> None:
        await self.db.execute(delete(BoardImage).where(BoardImage.board_id == board.id))
        await self.db.delete(board)

    async def image_keys(self, board_id: uuid.UUID) -> list[str]:
        result = await self.db.execute(
            select(BoardImage.r2_key).where(BoardImage.board_id == board_id)
        )
        return [row[0] for row in result.all()]

    def add_image(self, image: BoardImage) -> None:
        self.db.add(image)

    async def images_by_ids(self, file_ids: list[uuid.UUID]) -> dict[uuid.UUID, BoardImage]:
        if not file_ids:
            return {}
        result = await self.db.execute(select(BoardImage).where(BoardImage.file_id.in_(file_ids)))
        return {row.file_id: row for row in result.scalars().all()}

    async def attach_images(self, board_id: uuid.UUID, file_ids: list[uuid.UUID]) -> None:
        if not file_ids:
            return
        await self.db.execute(
            update(BoardImage)
            .where(BoardImage.file_id.in_(file_ids), BoardImage.board_id.is_(None))
            .values(board_id=board_id)
        )

    async def get_template(self, teacher_id: int, template_id: str) -> Optional[GeogebraTemplate]:
        result = await self.db.execute(
            select(GeogebraTemplate).where(
                GeogebraTemplate.teacher_id == teacher_id,
                GeogebraTemplate.id == template_id,
            )
        )
        return result.scalars().first()

    async def first_template(self, teacher_ids: list[int], template_id: str) -> Optional[GeogebraTemplate]:
        if not teacher_ids:
            return None
        result = await self.db.execute(
            select(GeogebraTemplate)
            .where(
                GeogebraTemplate.teacher_id.in_(teacher_ids),
                GeogebraTemplate.id == template_id,
            )
            .order_by(GeogebraTemplate.teacher_id.asc())
        )
        return result.scalars().first()

    async def list_templates(self, teacher_ids: list[int]) -> list[GeogebraTemplate]:
        if not teacher_ids:
            return []
        result = await self.db.execute(
            select(GeogebraTemplate)
            .where(GeogebraTemplate.teacher_id.in_(teacher_ids))
            .order_by(GeogebraTemplate.teacher_id.asc(), GeogebraTemplate.id.asc())
        )
        return list(result.scalars().all())

    def add_template(self, template: GeogebraTemplate) -> None:
        self.db.add(template)

    async def delete_template(self, template: GeogebraTemplate) -> None:
        await self.db.delete(template)

    async def flush(self) -> None:
        await self.db.flush()

    async def commit(self) -> None:
        await self.db.commit()

    async def rollback(self) -> None:
        await self.db.rollback()


def empty_camera() -> dict:
    return {"x": 0, "y": 0, "zoom": 1}


def new_board(*, title: str, kind: str, lesson_id: Optional[int], owner_id: Optional[int]) -> Board:
    now = datetime.utcnow()
    return Board(
        id=uuid.uuid4(),
        title=title,
        lesson_id=lesson_id,
        kind=kind,
        owner_id=owner_id,
        revision=1,
        camera=empty_camera(),
        objects=[],
        created_at=now,
        updated_at=now,
    )
