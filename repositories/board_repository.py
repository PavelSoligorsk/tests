from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from core.models import Board, BoardImage, BoardStudent, GeogebraTemplate, Group, GroupStudent, Lesson, TeacherStudent


class BoardRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_lesson(self, lesson_id: int) -> Optional[Lesson]:
        result = await self.db.execute(select(Lesson).where(Lesson.id == lesson_id))
        return result.scalars().first()

    async def get_by_share_token(self, share_token: str) -> Optional[Board]:
        result = await self.db.execute(select(Board).where(Board.share_token == share_token))
        return result.scalars().first()

    async def get_board(self, board_id: uuid.UUID, *, refresh: bool = False) -> Optional[Board]:
        stmt = select(Board).where(Board.id == board_id)
        if refresh:
            stmt = stmt.execution_options(populate_existing=True)
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def list_for_teacher(self, teacher_id: int) -> list[Board]:
        result = await self.db.execute(
            select(Board)
            .options(load_only(*_BOARD_LIST_COLUMNS))
            .where(Board.teacher_id == teacher_id)
            .order_by(Board.updated_at.desc(), Board.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_for_student(self, student_id: int) -> list[Board]:
        assigned = select(BoardStudent.board_id).where(BoardStudent.student_id == student_id)
        groups = select(GroupStudent.group_id).where(GroupStudent.student_id == student_id)
        result = await self.db.execute(
            select(Board)
            .options(load_only(*_BOARD_LIST_COLUMNS))
            .where(or_(Board.id.in_(assigned), Board.group_id.in_(groups)))
            .order_by(Board.updated_at.desc(), Board.created_at.desc())
        )
        return list(result.scalars().all())

    async def student_ids_map(self, board_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[int]]:
        if not board_ids:
            return {}
        result = await self.db.execute(
            select(BoardStudent.board_id, BoardStudent.student_id)
            .where(BoardStudent.board_id.in_(board_ids))
            .order_by(BoardStudent.student_id.asc())
        )
        found: dict[uuid.UUID, list[int]] = {}
        for board_id, student_id in result.all():
            found.setdefault(board_id, []).append(student_id)
        return found

    async def is_board_member(self, board_id: uuid.UUID, student_id: int) -> bool:
        result = await self.db.execute(
            select(BoardStudent.student_id).where(
                BoardStudent.board_id == board_id,
                BoardStudent.student_id == student_id,
            )
        )
        return result.first() is not None

    async def owns_students(self, teacher_id: int, student_ids: list[int]) -> bool:
        result = await self.db.execute(
            select(TeacherStudent.student_id).where(
                TeacherStudent.teacher_id == teacher_id,
                TeacherStudent.student_id.in_(student_ids),
            )
        )
        return {row[0] for row in result.all()} == set(student_ids)

    async def owned_group(self, group_id: int, teacher_id: int) -> Optional[Group]:
        result = await self.db.execute(
            select(Group).where(Group.id == group_id, Group.teacher_id == teacher_id)
        )
        return result.scalars().first()

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

    def add_member(self, member: BoardStudent) -> None:
        self.db.add(member)

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

    async def images_for_board(
        self, board_id: uuid.UUID, file_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, BoardImage]:
        """Картинки этой доски и ещё ни к одной не привязанные. Чужие не отдаются."""
        if not file_ids:
            return {}
        result = await self.db.execute(
            select(BoardImage).where(
                BoardImage.file_id.in_(file_ids),
                or_(BoardImage.board_id == board_id, BoardImage.board_id.is_(None)),
            )
        )
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
            .options(load_only(
                GeogebraTemplate.teacher_id,
                GeogebraTemplate.id,
                GeogebraTemplate.title,
                GeogebraTemplate.app_name,
            ))
            .where(GeogebraTemplate.teacher_id.in_(teacher_ids))
            .order_by(GeogebraTemplate.teacher_id.asc(), GeogebraTemplate.id.asc())
        )
        return list(result.scalars().all())

    async def update_document(
        self,
        board_id: uuid.UUID,
        expected_revision: Optional[int],
        *,
        title: str,
        camera: dict,
        objects: list,
        object_count: int,
        updated_at: datetime,
    ) -> Optional[tuple[int, datetime]]:
        """Пишет документ. С expected_revision — только если ревизия в базе всё ещё та."""
        conditions = [Board.id == board_id]
        if expected_revision is not None:
            conditions.append(Board.revision == expected_revision)
        result = await self.db.execute(
            update(Board)
            .where(*conditions)
            .values(
                title=title,
                camera=camera,
                objects=objects,
                object_count=object_count,
                revision=Board.revision + 1,
                updated_at=updated_at,
            )
            .returning(Board.revision, Board.updated_at)
            .execution_options(synchronize_session=False)
        )
        row = result.first()
        if row is None:
            return None
        return int(row.revision), row.updated_at

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


_BOARD_LIST_COLUMNS = (
    Board.id,
    Board.teacher_id,
    Board.group_id,
    Board.title,
    Board.object_count,
    Board.created_at,
    Board.updated_at,
    Board.share_access,
    Board.series_id,
)


def empty_camera() -> dict:
    return {"x": 0, "y": 0, "zoom": 1}


def new_board(
    *, title: str, teacher_id: int, group_id: Optional[int], series_id: Optional[uuid.UUID] = None,
) -> Board:
    now = datetime.utcnow()
    board_id = uuid.uuid4()
    return Board(
        id=board_id,
        series_id=series_id or board_id,
        teacher_id=teacher_id,
        group_id=group_id,
        title=title,
        revision=1,
        camera=empty_camera(),
        objects=[],
        object_count=0,
        share_access="off",
        share_token=None,
        created_at=now,
        updated_at=now,
    )
