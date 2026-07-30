from sqlalchemy import select, delete, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from typing import Optional, List
from datetime import datetime

from core.models import Parent, User


class ParentRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, parent_id: int) -> Optional[Parent]:
        r = await self.db.execute(
            select(Parent).options(selectinload(Parent.students)).where(Parent.id == parent_id)
        )
        return r.scalars().first()

    async def list_by_teacher(self, teacher_id: int) -> List[Parent]:
        """Родители всех студентов учителя (parent_id is set on students)."""
        from core.models import TeacherStudent
        subq = (
            select(User.parent_id)
            .join(TeacherStudent, TeacherStudent.student_id == User.id)
            .where(
                TeacherStudent.teacher_id == teacher_id,
                User.parent_id.isnot(None)
            )
            .distinct()
            .subquery()
        )
        r = await self.db.execute(
            select(Parent).options(selectinload(Parent.students)).where(Parent.id.in_(subq))
        )
        return r.scalars().all()

    async def search(self, query: str) -> List[Parent]:
        r = await self.db.execute(
            select(Parent).options(selectinload(Parent.students)).where(
                Parent.name.ilike(f"%{query}%") | Parent.phone.ilike(f"%{query}%")
            )
        )
        return r.scalars().all()

    async def create(self, data: dict) -> Parent:
        parent = Parent(
            name=data["name"],
            phone=data.get("phone"),
            tg_username=data.get("tg_username"),
            comment=data.get("comment"),
            created_at=datetime.utcnow(),
        )
        self.db.add(parent)
        await self.db.flush()
        return parent

    async def update(self, parent: Parent, data: dict) -> Parent:
        for field in ("name", "phone", "tg_username", "comment"):
            if field in data and data[field] is not None:
                setattr(parent, field, data[field])
        await self.db.flush()
        return parent

    async def delete(self, parent: Parent) -> None:
        """Удалить родителя; parent_id на студентах занулится (SET NULL)."""
        await self.db.delete(parent)
        await self.db.flush()

    async def link_student(self, parent_id: int, student_id: int) -> bool:
        r = await self.db.execute(select(User).where(User.id == student_id))
        student = r.scalars().first()
        if not student:
            return False
        student.parent_id = parent_id
        await self.db.flush()
        return True

    async def unlink_student(self, student_id: int) -> bool:
        r = await self.db.execute(select(User).where(User.id == student_id))
        student = r.scalars().first()
        if not student:
            return False
        student.parent_id = None
        await self.db.flush()
        return True

    async def get_student_ids(self, parent_id: int) -> list[int]:
        """Возвращает ID студентов родителя (прямой запрос, без backref)."""
        r = await self.db.execute(
            select(User.id).where(User.parent_id == parent_id)
        )
        return [row[0] for row in r.all()]

    async def get_by_student_id(self, student_id: int) -> List[Parent]:
        """Возвращает родителей ученика по его ID (через parent_id на User)."""
        r = await self.db.execute(
            select(Parent)
            .options(selectinload(Parent.students))
            .join(User, User.parent_id == Parent.id)
            .where(User.id == student_id)
        )
        return r.scalars().all()
