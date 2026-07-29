from sqlalchemy import select, delete, update, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from typing import Optional, List
from datetime import datetime

from core.models import LessonSchedule


class ScheduleRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, schedule_id: int, teacher_id: Optional[int] = None) -> Optional[LessonSchedule]:
        stmt = select(LessonSchedule).options(
            selectinload(LessonSchedule.lessons)
        ).where(LessonSchedule.id == schedule_id)
        if teacher_id:
            stmt = stmt.where(LessonSchedule.teacher_id == teacher_id)
        r = await self.db.execute(stmt)
        return r.scalars().first()

    async def list_by_teacher(self, teacher_id: int, active_only: bool = False) -> List[LessonSchedule]:
        stmt = select(LessonSchedule).options(
            selectinload(LessonSchedule.lessons)
        ).where(LessonSchedule.teacher_id == teacher_id)
        if active_only:
            stmt = stmt.where(LessonSchedule.is_active == True)
        r = await self.db.execute(stmt)
        return r.scalars().all()

    async def list_by_student(self, student_id: int) -> List[LessonSchedule]:
        r = await self.db.execute(
            select(LessonSchedule).where(LessonSchedule.student_id == student_id)
        )
        return r.scalars().all()

    async def list_by_group(self, group_id: int) -> List[LessonSchedule]:
        r = await self.db.execute(
            select(LessonSchedule).where(LessonSchedule.group_id == group_id)
        )
        return r.scalars().all()

    async def create(self, data: dict) -> LessonSchedule:
        schedule = LessonSchedule(
            teacher_id=data["teacher_id"],
            title=data["title"],
            description=data.get("description"),
            schedule_type=data["schedule_type"],
            student_id=data.get("student_id"),
            group_id=data.get("group_id"),
            days_of_week=data["days_of_week"],
            time_start=data["time_start"],
            duration_minutes=data["duration_minutes"],
            price_per_lesson=data.get("price_per_lesson"),
            recur_until=data.get("recur_until"),
            is_active=True,
            created_at=datetime.utcnow(),
        )
        self.db.add(schedule)
        await self.db.flush()
        return schedule

    async def update(self, schedule: LessonSchedule, data: dict) -> LessonSchedule:
        for field in ("title", "description", "days_of_week", "time_start",
                       "duration_minutes", "price_per_lesson", "is_active",
                       "recur_until"):
            if field in data and data[field] is not None:
                setattr(schedule, field, data[field])
        if not schedule.is_active and schedule.stopped_at is None:
            schedule.stopped_at = datetime.utcnow()
        elif schedule.is_active:
            schedule.stopped_at = None
        await self.db.flush()
        return schedule

    async def toggle_active(self, schedule: LessonSchedule, active: bool) -> LessonSchedule:
        schedule.is_active = active
        schedule.stopped_at = datetime.utcnow() if not active else None
        await self.db.flush()
        return schedule

    async def delete(self, schedule: LessonSchedule) -> None:
        await self.db.delete(schedule)
        await self.db.flush()
