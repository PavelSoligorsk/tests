from sqlalchemy import select, delete, update, and_, or_, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from typing import Optional, List
from datetime import datetime, timedelta

from core.models import Lesson, LessonSchedule, GroupStudent


class LessonRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, lesson_id: int, teacher_id: Optional[int] = None) -> Optional[Lesson]:
        stmt = select(Lesson).options(
            selectinload(Lesson.schedule),
            selectinload(Lesson.rescheduled_from),
            selectinload(Lesson.rescheduled_to),
            selectinload(Lesson.student),
            selectinload(Lesson.group),
            selectinload(Lesson.payments),
        ).where(Lesson.id == lesson_id)
        if teacher_id:
            stmt = stmt.where(Lesson.teacher_id == teacher_id)
        r = await self.db.execute(stmt)
        return r.scalars().first()

    async def calendar(
        self, teacher_id: int, date_from: datetime, date_to: datetime
    ) -> List[Lesson]:
        r = await self.db.execute(
            select(Lesson).options(
                selectinload(Lesson.schedule),
                selectinload(Lesson.student),
                selectinload(Lesson.group),
                selectinload(Lesson.payments),
            ).where(
                Lesson.teacher_id == teacher_id,
                Lesson.scheduled_date >= date_from.replace(hour=0, minute=0, second=0),
                Lesson.scheduled_date <= date_to.replace(hour=23, minute=59, second=59),
            ).order_by(Lesson.scheduled_date.asc())
        )
        return r.scalars().all()

    async def calendar_for_student(
        self, student_id: int, date_from: datetime, date_to: datetime
    ) -> List[Lesson]:
        r = await self.db.execute(
            select(Lesson).options(
                selectinload(Lesson.schedule)
            ).where(
                or_(
                    Lesson.student_id == student_id,
                    Lesson.group_id.in_(
                        select(GroupStudent.group_id).where(GroupStudent.student_id == student_id)
                    )
                ),
                Lesson.scheduled_date >= date_from.replace(hour=0, minute=0, second=0),
                Lesson.scheduled_date <= date_to.replace(hour=23, minute=59, second=59),
            ).order_by(Lesson.scheduled_date.asc())
        )
        return r.scalars().all()

    async def find_conflicting(
        self, teacher_id: int, scheduled_date: datetime, duration_minutes: int,
        exclude_lesson_id: Optional[int] = None,
    ) -> List[Lesson]:
        """Найти занятия учителя, пересекающиеся с указанным слотом."""
        new_start = scheduled_date
        new_end = scheduled_date + timedelta(minutes=duration_minutes)

        # Широкое окно — достаём кандидатов, проверяем пересечение в Python
        window_start = new_start - timedelta(hours=24)
        window_end = new_end + timedelta(hours=24)

        stmt = select(Lesson).where(
            Lesson.teacher_id == teacher_id,
            Lesson.status == "scheduled",
            Lesson.scheduled_date >= window_start,
            Lesson.scheduled_date <= window_end,
        )
        if exclude_lesson_id:
            stmt = stmt.where(Lesson.id != exclude_lesson_id)
        r = await self.db.execute(stmt)
        candidates = r.scalars().all()

        # Python-проверка пересечения
        conflicts: List[Lesson] = []
        for c in candidates:
            c_end = c.scheduled_date + timedelta(minutes=c.duration_minutes)
            if c.scheduled_date < new_end and c_end > new_start:
                conflicts.append(c)
        return conflicts

    async def create(self, data: dict) -> Lesson:
        lesson = Lesson(
            schedule_id=data.get("schedule_id"),
            teacher_id=data["teacher_id"],
            title=data["title"],
            lesson_type=data.get("lesson_type", "individual"),
            student_id=data.get("student_id"),
            group_id=data.get("group_id"),
            scheduled_date=data["scheduled_date"],
            duration_minutes=data.get("duration_minutes", 60),
            status="scheduled",
            teacher_note=data.get("teacher_note"),
            created_at=datetime.utcnow(),
        )
        self.db.add(lesson)
        await self.db.flush()
        return lesson

    async def update_status(self, lesson: Lesson, status: str, **kwargs) -> Lesson:
        lesson.status = status
        for field, value in kwargs.items():
            if value is not None:
                setattr(lesson, field, value)
        await self.db.flush()
        return lesson

    async def update(self, lesson: Lesson, data: dict) -> Lesson:
        """Обновить поля занятия по словарю (только переданные)."""
        for field in ("title", "scheduled_date", "duration_minutes",
                       "teacher_note", "actual_start", "actual_end", "status"):
            if field in data and data[field] is not None:
                setattr(lesson, field, data[field])
        await self.db.flush()
        return lesson

    async def complete(self, lesson: Lesson, actual_end: Optional[datetime] = None) -> Lesson:
        lesson.status = "completed"
        lesson.actual_end = actual_end or datetime.utcnow()
        if not lesson.actual_start:
            lesson.actual_start = lesson.scheduled_date
        await self.db.flush()
        return lesson

    async def cancel(self, lesson: Lesson, note: Optional[str] = None) -> Lesson:
        lesson.status = "cancelled"
        if note:
            lesson.teacher_note = note
        await self.db.flush()
        return lesson

    async def reschedule(self, lesson: Lesson, new_date: datetime,
                          reason: Optional[str] = None) -> tuple[Lesson, Lesson]:
        """Перенести занятие: создаём новое, помечаем старое как перенесённое."""
        new_lesson = Lesson(
            schedule_id=lesson.schedule_id,
            teacher_id=lesson.teacher_id,
            title=lesson.title,
            lesson_type=lesson.lesson_type,
            student_id=lesson.student_id,
            group_id=lesson.group_id,
            scheduled_date=new_date,
            duration_minutes=lesson.duration_minutes,
            status="scheduled",
            rescheduled_from_id=lesson.id,
            teacher_note=reason,
            created_at=datetime.utcnow(),
        )
        self.db.add(new_lesson)
        await self.db.flush()

        lesson.status = "rescheduled"
        lesson.rescheduled_to_id = new_lesson.id
        await self.db.flush()

        return lesson, new_lesson

    async def reschedule_delete_and_create(self, lesson: Lesson, new_date: datetime,
                                            note: str) -> Lesson:
        """Перенести занятие с полным удалением оригинала.
        Удаляет исходное занятие и создаёт новое с указанной заметкой."""
        new_lesson = Lesson(
            schedule_id=lesson.schedule_id,
            teacher_id=lesson.teacher_id,
            title=lesson.title,
            lesson_type=lesson.lesson_type,
            student_id=lesson.student_id,
            group_id=lesson.group_id,
            scheduled_date=new_date,
            duration_minutes=lesson.duration_minutes,
            status="scheduled",
            teacher_note=note,
            created_at=datetime.utcnow(),
        )
        self.db.add(new_lesson)
        await self.db.flush()

        # Удаляем оригинал
        await self.db.delete(lesson)
        await self.db.flush()

        return new_lesson

    async def reschedule_mark_and_create(self, lesson: Lesson, new_date: datetime,
                                          old_note: str, new_note: str) -> Lesson:
        """Перенести занятие: оригинал помечается cancelled с пометкой «куда»,
        создаётся новое с пометкой «откуда»."""
        new_lesson = Lesson(
            schedule_id=lesson.schedule_id,
            teacher_id=lesson.teacher_id,
            title=lesson.title,
            lesson_type=lesson.lesson_type,
            student_id=lesson.student_id,
            group_id=lesson.group_id,
            scheduled_date=new_date,
            duration_minutes=lesson.duration_minutes,
            status="scheduled",
            teacher_note=new_note,
            created_at=datetime.utcnow(),
        )
        self.db.add(new_lesson)
        await self.db.flush()

        # Оригинал: cancelled с пометкой куда перенесено
        lesson.status = "cancelled"
        lesson.teacher_note = old_note
        await self.db.flush()

        return new_lesson

    async def generate_upcoming(
        self, schedule: LessonSchedule, weeks: int = 4
    ) -> List[Lesson]:
        """Сгенерировать занятия из расписания на период вперёд.
        Если указан recur_until, генерирует до этой даты (но не более года вперёд),
        иначе на weeks недель. Пропускает даты с уже существующими занятиями."""
        today = datetime.utcnow().date()
        max_future = today + timedelta(days=365)  # safety ceiling: 1 year

        if schedule.recur_until and isinstance(schedule.recur_until, datetime):
            recur_end = schedule.recur_until.date() if hasattr(schedule.recur_until, 'date') else schedule.recur_until
            if isinstance(recur_end, type(today)):
                if recur_end < today:
                    return []  # истекло
                end_date = min(recur_end, max_future)
            else:
                end_date = today + timedelta(weeks=weeks)
        else:
            end_date = today + timedelta(weeks=weeks)

        hour, minute = map(int, schedule.time_start.split(":"))

        existing = await self._upcoming_dates(schedule.id, today, end_date)

        created: List[Lesson] = []
        current = today
        while current <= end_date:
            dow = current.strftime("%a").lower()[:3]
            if dow in (d.lower()[:3] for d in schedule.days_of_week):
                slot = datetime(current.year, current.month, current.day, hour, minute)
                if current not in existing and slot > datetime.utcnow():
                    lesson = Lesson(
                        schedule_id=schedule.id,
                        teacher_id=schedule.teacher_id,
                        title=schedule.title,
                        lesson_type=schedule.schedule_type,
                        student_id=schedule.student_id,
                        group_id=schedule.group_id,
                        scheduled_date=slot,
                        duration_minutes=schedule.duration_minutes,
                        status="scheduled",
                        created_at=datetime.utcnow(),
                    )
                    self.db.add(lesson)
                    created.append(lesson)
            current += timedelta(days=1)

        if created:
            await self.db.flush()
        return created

    async def _upcoming_dates(self, schedule_id: int, from_date, to_date):
        r = await self.db.execute(
            select(func.date(Lesson.scheduled_date)).where(
                Lesson.schedule_id == schedule_id,
                func.date(Lesson.scheduled_date) >= from_date,
                func.date(Lesson.scheduled_date) <= to_date,
            )
        )
        return {row[0] for row in r.all()}

    async def delete_all_future_lessons(self, schedule_id: int) -> int:
        """Удаляет все будущие (scheduled, дата > сейчас) занятия расписания.
        Возвращает количество удалённых."""
        now = datetime.utcnow()
        r = await self.db.execute(
            select(Lesson).where(
                Lesson.schedule_id == schedule_id,
                Lesson.status == "scheduled",
                Lesson.scheduled_date > now,
            )
        )
        to_delete = list(r.scalars().all())
        for lesson in to_delete:
            await self.db.delete(lesson)
        if to_delete:
            await self.db.flush()
        return len(to_delete)

    async def delete_future_lessons_not_on_days(
        self, schedule_id: int, keep_days: List[str]
    ) -> int:
        """Удалить будущие занятия расписания, которые не попадают на указанные дни недели.
        Возвращает количество удалённых."""
        now = datetime.utcnow()
        keep_prefixes = {d.lower()[:3] for d in keep_days}
        r = await self.db.execute(
            select(Lesson).where(
                Lesson.schedule_id == schedule_id,
                Lesson.status == "scheduled",
                Lesson.scheduled_date > now,
            )
        )
        to_delete: list[Lesson] = []
        for lesson in r.scalars().all():
            dow = lesson.scheduled_date.strftime("%a").lower()[:3]
            if dow not in keep_prefixes:
                to_delete.append(lesson)
        for l in to_delete:
            await self.db.delete(l)
        if to_delete:
            await self.db.flush()
        return len(to_delete)

    async def delete(self, lesson: Lesson) -> None:
        await self.db.delete(lesson)
        await self.db.flush()

    async def get_lessons_by_teacher(
        self, teacher_id: int, date_from: datetime, date_to: datetime
    ) -> List[Lesson]:
        """Занятия учителя в диапазоне дат (алиас для calendar)."""
        return await self.calendar(teacher_id, date_from, date_to)

    async def get_lessons_by_student(
        self, student_id: int, date_from: datetime, date_to: datetime
    ) -> List[Lesson]:
        """Занятия ученика в диапазоне дат (алиас для calendar_for_student)."""
        return await self.calendar_for_student(student_id, date_from, date_to)
