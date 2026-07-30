"""Сервис расписания: занятия, повторения, переносы, оплаты, родители."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional, List

from sqlalchemy.ext.asyncio import AsyncSession

from core.models import User
from repositories.parent_repository import ParentRepository
from repositories.schedule_repository import ScheduleRepository
from repositories.lesson_repository import LessonRepository
from repositories.payment_repository import PaymentRepository
from repositories.group_repository import GroupRepository
from repositories.teacher_student_repository import TeacherStudentRepository
from repositories.user_repository import UserRepository

from dto_schemas.schedule import (
    ParentCreate, ParentUpdate, ParentResponse,
    ScheduleCreate, ScheduleUpdate, ScheduleResponse,
    LessonCreate, LessonReschedule, LessonUpdate, LessonResponse,
    PaymentCreate, PaymentUpdate, PaymentResponse,
    CalendarDayResponse, CalendarResponse,
    TelegramPaymentRequest, TelegramPaymentResponse,
)

logger = logging.getLogger("schedule_service")


class ScheduleService:
    def __init__(self, db: AsyncSession):
        self.parent_repo = ParentRepository(db)
        self.schedule_repo = ScheduleRepository(db)
        self.lesson_repo = LessonRepository(db)
        self.payment_repo = PaymentRepository(db)
        self.group_repo = GroupRepository(db)
        self.ts_repo = TeacherStudentRepository(db)
        self.user_repo = UserRepository(db)
        self.db = db

    # ═══════════════════════════════════════════════════════════
    # Parents
    # ═══════════════════════════════════════════════════════════

    async def create_parent(self, data: ParentCreate) -> ParentResponse:
        parent = await self.parent_repo.create(data.model_dump())
        # Сразу привязываем учеников
        for sid in (data.student_ids or []):
            await self.parent_repo.link_student(parent.id, sid)
        await self.db.commit()
        return await self._parent_to_response(parent)

    async def update_parent(self, parent_id: int, data: ParentUpdate) -> ParentResponse:
        parent = await self.parent_repo.get_by_id(parent_id)
        if not parent:
            raise ValueError("Родитель не найден")
        await self.parent_repo.update(parent, data.model_dump(exclude_unset=True))
        resp = await self._parent_to_response(parent)
        await self.db.commit()
        return resp

    async def get_parent(self, parent_id: int, teacher_id: int) -> ParentResponse:
        parent = await self.parent_repo.get_by_id(parent_id)
        if not parent:
            raise ValueError("Родитель не найден")
        return await self._parent_to_response(parent)

    async def list_parents(self, teacher_id: int) -> List[ParentResponse]:
        parents = await self.parent_repo.list_by_teacher(teacher_id)
        return [await self._parent_to_response(p) for p in parents]

    async def get_parents_by_student(self, student_id: int, teacher_id: int) -> List[ParentResponse]:
        """Возвращает родителей ученика. Проверяет, что ученик привязан к учителю."""
        from repositories.teacher_student_repository import TeacherStudentRepository
        ts_repo = TeacherStudentRepository(self.db)
        belongs = await ts_repo.check_student_belongs_to_teacher(student_id, teacher_id)
        if not belongs:
            raise ValueError("Ученик не найден или не привязан к вам")
        parents = await self.parent_repo.get_by_student_id(student_id)
        return [await self._parent_to_response(p) for p in parents]

    async def link_parent_student(self, parent_id: int, student_id: int) -> bool:
        ok = await self.parent_repo.link_student(parent_id, student_id)
        if ok:
            await self.db.commit()
        return ok

    async def unlink_parent_student(self, student_id: int) -> bool:
        ok = await self.parent_repo.unlink_student(student_id)
        if ok:
            await self.db.commit()
        return ok

    async def delete_parent(self, parent_id: int) -> None:
        parent = await self.parent_repo.get_by_id(parent_id)
        if not parent:
            raise ValueError("Родитель не найден")
        await self.parent_repo.delete(parent)
        await self.db.commit()

    async def _parent_to_response(self, parent) -> ParentResponse:
        # always use direct SQL — async backref unreliable with SQLAlchemy
        student_ids = await self.parent_repo.get_student_ids(parent.id)
        return ParentResponse(
            id=parent.id,
            name=parent.name,
            phone=parent.phone,
            tg_username=parent.tg_username,
            comment=parent.comment,
            student_ids=student_ids,
            created_at=parent.created_at,
        )

    # ═══════════════════════════════════════════════════════════
    # Schedules
    # ═══════════════════════════════════════════════════════════

    async def create_schedule(self, teacher_id: int, data: ScheduleCreate) -> ScheduleResponse:
        if data.schedule_type == "group" and not data.group_id:
            raise ValueError("group_id обязателен для группового расписания")
        if data.schedule_type == "individual" and not data.student_id:
            raise ValueError("student_id обязателен для индивидуального расписания")

        # Если не указан recur_until, по умолчанию — год от сегодня
        recur_until = data.recur_until
        if recur_until is None:
            recur_until = datetime.utcnow() + timedelta(days=365)

        sched = await self.schedule_repo.create({
            **data.model_dump(),
            "recur_until": recur_until,
            "teacher_id": teacher_id,
        })
        await self.db.commit()

        # Генерируем первые 4 недели занятий
        await self.lesson_repo.generate_upcoming(sched, weeks=4)
        await self.db.commit()

        return self._schedule_to_response(sched)

    async def update_schedule(self, schedule_id: int, teacher_id: int,
                               data: ScheduleUpdate) -> ScheduleResponse:
        sched = await self.schedule_repo.get_by_id(schedule_id, teacher_id)
        if not sched:
            raise ValueError("Расписание не найдено")
        data_dict = data.model_dump(exclude_unset=True)
        await self.schedule_repo.update(sched, data_dict)

        # При любом изменении — удаляем все будущие занятия и перегенерируем
        needs_regenerate = any(
            k in data_dict
            for k in ("days_of_week", "time_start", "duration_minutes", "recur_until")
        )
        if needs_regenerate:
            await self.lesson_repo.delete_all_future_lessons(sched.id)
            await self.lesson_repo.generate_upcoming(sched, weeks=4)

        await self.db.commit()
        return self._schedule_to_response(sched)

    async def list_schedules(self, teacher_id: int) -> List[ScheduleResponse]:
        schedules = await self.schedule_repo.list_by_teacher(teacher_id)
        return [self._schedule_to_response(s) for s in schedules]

    async def get_schedule(self, schedule_id: int, teacher_id: int) -> ScheduleResponse:
        sched = await self.schedule_repo.get_by_id(schedule_id, teacher_id)
        if not sched:
            raise ValueError("Расписание не найдено")
        return self._schedule_to_response(sched)

    async def toggle_schedule(self, schedule_id: int, teacher_id: int,
                               active: bool) -> ScheduleResponse:
        sched = await self.schedule_repo.get_by_id(schedule_id, teacher_id)
        if not sched:
            raise ValueError("Расписание не найдено")
        await self.schedule_repo.toggle_active(sched, active)
        await self.db.commit()
        return self._schedule_to_response(sched)

    async def delete_schedule(self, schedule_id: int, teacher_id: int) -> None:
        sched = await self.schedule_repo.get_by_id(schedule_id, teacher_id)
        if not sched:
            raise ValueError("Расписание не найдено")
        await self.schedule_repo.delete(sched)
        await self.db.commit()

    def _schedule_to_response(self, sched) -> ScheduleResponse:
        return ScheduleResponse(
            id=sched.id,
            teacher_id=sched.teacher_id,
            title=sched.title,
            description=sched.description,
            schedule_type=sched.schedule_type,
            student_id=sched.student_id,
            group_id=sched.group_id,
            days_of_week=sched.days_of_week,
            time_start=sched.time_start,
            duration_minutes=sched.duration_minutes,
            price_per_lesson=sched.price_per_lesson,
            is_active=sched.is_active,
            recur_until=sched.recur_until,
            created_at=sched.created_at,
            stopped_at=sched.stopped_at,
        )

    # ═══════════════════════════════════════════════════════════
    # Lessons
    # ═══════════════════════════════════════════════════════════

    async def create_lesson(self, teacher_id: int, data: LessonCreate) -> LessonResponse:
        # Проверка конфликтов
        conflicts = await self.lesson_repo.find_conflicting(
            teacher_id, data.scheduled_date, data.duration_minutes
        )
        if conflicts:
            raise ValueError(
                f"Конфликт с занятием #{conflicts[0].id} "
                f"({conflicts[0].scheduled_date.strftime('%d.%m.%Y %H:%M')})"
            )

        lesson = await self.lesson_repo.create({**data.model_dump(), "teacher_id": teacher_id})
        resp = self._lesson_to_response(lesson)
        await self.db.commit()
        return resp

    async def calendar(self, teacher_id: int, date_from: datetime,
                        date_to: datetime) -> CalendarResponse:
        lessons = await self.lesson_repo.calendar(teacher_id, date_from, date_to)

        days: dict[str, List[LessonResponse]] = {}
        for l in lessons:
            key = l.scheduled_date.strftime("%Y-%m-%d")
            days.setdefault(key, []).append(self._lesson_to_response(l))
        return CalendarResponse(days=[
            CalendarDayResponse(date=k, lessons=v) for k, v in sorted(days.items())
        ])

    async def get_lesson(self, lesson_id: int, teacher_id: int) -> LessonResponse:
        lesson = await self.lesson_repo.get_by_id(lesson_id, teacher_id)
        if not lesson:
            raise ValueError("Занятие не найдено")
        return self._lesson_to_response(lesson)

    async def complete_lesson(self, lesson_id: int, teacher_id: int) -> LessonResponse:
        lesson = await self.lesson_repo.get_by_id(lesson_id, teacher_id)
        if not lesson:
            raise ValueError("Занятие не найдено")
        if lesson.status != "scheduled":
            raise ValueError(f"Нельзя завершить занятие со статусом '{lesson.status}'")
        await self.lesson_repo.complete(lesson)

        # Списываем price_per_lesson с баланса ученика (если есть студент и цена)
        if lesson.student_id and lesson.schedule and lesson.schedule.price_per_lesson:
            price = lesson.schedule.price_per_lesson
            student = await self.db.get(User, lesson.student_id)
            if student:
                student.balance = (student.balance or 0) - price
                # Создаём запись о списании для истории
                await self.payment_repo.create({
                    "lesson_id": lesson.id,
                    "student_id": lesson.student_id,
                    "payment_type": "per_lesson",
                    "amount": price,
                    "comment": f"Списание с баланса за занятие #{lesson.id}",
                    "status": "paid",
                })

        resp = self._lesson_to_response(lesson)
        await self.db.commit()
        return resp

    async def delete_lesson(self, lesson_id: int, teacher_id: int) -> None:
        lesson = await self.lesson_repo.get_by_id(lesson_id, teacher_id)
        if not lesson:
            raise ValueError("Занятие не найдено")
        await self.lesson_repo.delete(lesson)
        await self.db.commit()

    async def update_lesson(self, lesson_id: int, teacher_id: int,
                            data) -> LessonResponse:
        lesson = await self.lesson_repo.get_by_id(lesson_id, teacher_id)
        if not lesson:
            raise ValueError("Занятие не найдено")
        data_dict = data.model_dump(exclude_unset=True)
        old_status = lesson.status

        await self.lesson_repo.update(lesson, data_dict)

        # Возврат денег: completed → scheduled / cancelled
        if "status" in data_dict and old_status == "completed" and data_dict["status"] in ("scheduled", "cancelled"):
            charge = await self.payment_repo.get_by_lesson(lesson.id)
            if charge and lesson.student_id:
                # Возвращаем деньги на баланс
                student = await self.db.get(User, lesson.student_id)
                if student:
                    student.balance = (student.balance or 0) + charge.amount
                # Отменяем платёж-списание
                await self.payment_repo.mark_cancelled(charge)

        await self.db.commit()
        return self._lesson_to_response(lesson)

    async def cancel_lesson(self, lesson_id: int, teacher_id: int,
                             note: Optional[str] = None) -> LessonResponse:
        lesson = await self.lesson_repo.get_by_id(lesson_id, teacher_id)
        if not lesson:
            raise ValueError("Занятие не найдено")
        if lesson.status != "scheduled":
            raise ValueError(f"Нельзя отменить занятие со статусом '{lesson.status}'")
        await self.lesson_repo.cancel(lesson, note)
        resp = self._lesson_to_response(lesson)
        await self.db.commit()
        return resp

    async def reschedule_lesson(self, lesson_id: int, teacher_id: int,
                                 data: LessonReschedule) -> LessonResponse:
        lesson = await self.lesson_repo.get_by_id(lesson_id, teacher_id)
        if not lesson:
            raise ValueError("Занятие не найдено")
        if lesson.status != "scheduled":
            raise ValueError(f"Нельзя перенести занятие со статусом '{lesson.status}'")

        # Проверка конфликтов для новой даты
        conflicts = await self.lesson_repo.find_conflicting(
            teacher_id, data.new_date, lesson.duration_minutes, exclude_lesson_id=lesson.id
        )
        if conflicts:
            raise ValueError(
                f"Конфликт с занятием #{conflicts[0].id} "
                f"({conflicts[0].scheduled_date.strftime('%d.%m.%Y %H:%M')})"
            )

        # Формируем заметки
        old_date_str = lesson.scheduled_date.strftime("%d.%m.%Y %H:%M")
        new_date_str = data.new_date.strftime("%d.%m.%Y %H:%M")

        # На оригинале: «Перенесено на ДД.ММ.ГГГГ ЧЧ:ММ»
        old_note = f"Перенесено на {new_date_str}"

        # На новом: «Перенесено с ДД.ММ.ГГГГ ЧЧ:ММ. Причина: ...»
        new_note_parts = [f"Перенесено с {old_date_str}"]
        if data.reason:
            new_note_parts.append(f"Причина: {data.reason}")
        new_note = ". ".join(new_note_parts)

        # Оригинал → cancelled с пометкой, создаём новое scheduled
        new_lesson = await self.lesson_repo.reschedule_mark_and_create(
            lesson, data.new_date, old_note, new_note
        )
        resp = self._lesson_to_response(new_lesson)
        await self.db.commit()
        return resp

    def _lesson_to_response(self, lesson, covers: dict = None) -> LessonResponse:
        """covers — не используется (оставлен для обратной совместимости)."""

        # payment_status: ищем любой paid платёж для этого урока
        payment_status = None
        coverage_type = None

        try:
            if lesson.payments:
                paid = next((p for p in lesson.payments if p.status == "paid"), None)
                if paid:
                    payment_status = "paid"
                    coverage_type = paid.payment_type
        except Exception:
            pass

        # student_name / group_name
        student_name = None
        group_name = None
        student_balance = None
        try:
            if lesson.student:
                first = lesson.student.first_name or ""
                last = lesson.student.last_name or ""
                student_name = f"{first} {last}".strip() or None
                student_balance = lesson.student.balance
        except Exception:
            pass
        try:
            if lesson.group:
                group_name = lesson.group.name
        except Exception:
            pass

        return LessonResponse(
            id=lesson.id,
            schedule_id=lesson.schedule_id,
            teacher_id=lesson.teacher_id,
            title=lesson.title,
            lesson_type=lesson.lesson_type,
            student_id=lesson.student_id,
            group_id=lesson.group_id,
            scheduled_date=lesson.scheduled_date,
            duration_minutes=lesson.duration_minutes,
            actual_start=lesson.actual_start,
            actual_end=lesson.actual_end,
            status=lesson.status,
            rescheduled_from_id=lesson.rescheduled_from_id,
            rescheduled_to_id=lesson.rescheduled_to_id,
            teacher_note=lesson.teacher_note,
            created_at=lesson.created_at,
            payment_status=payment_status,
            coverage_type=coverage_type,
            student_name=student_name,
            group_name=group_name,
            student_balance=student_balance,
        )

    # ═══════════════════════════════════════════════════════════
    # Payments
    # ═══════════════════════════════════════════════════════════

    async def create_payment(self, teacher_id: int, data: PaymentCreate) -> PaymentResponse:
        # Проверка: студент должен принадлежать учителю
        if not await self.ts_repo.check_student_belongs_to_teacher(data.student_id, teacher_id):
            raise ValueError("Студент не найден или не привязан к учителю")

        is_paid = (data.status or "paid") == "paid"
        is_per_lesson = data.payment_type == "per_lesson"

        payment = await self.payment_repo.create(data.model_dump())

        # Пополнение баланса: per_lesson + paid → зачисляем сумму на баланс
        new_balance = None
        if is_paid and is_per_lesson:
            student = await self.db.get(User, data.student_id)
            if student:
                student.balance = (student.balance or 0) + data.amount
                new_balance = student.balance

        await self.db.commit()
        return self._payment_to_response(payment, new_balance)

    async def list_payments_for_teacher(self, teacher_id: int) -> List[PaymentResponse]:
        payments = await self.payment_repo.list_by_teacher(teacher_id)
        return [self._payment_to_response(p) for p in payments]

    async def list_payments_for_student(self, student_id: int, teacher_id: int) -> List[PaymentResponse]:
        payments = await self.payment_repo.list_by_student(student_id)
        return [self._payment_to_response(p) for p in payments]

    async def update_payment(self, payment_id: int, teacher_id: int,
                              data: PaymentUpdate) -> PaymentResponse:
        payment = await self.payment_repo.get_by_id(payment_id)
        if not payment:
            raise ValueError("Платёж не найден")
        if not await self.ts_repo.check_student_belongs_to_teacher(payment.student_id, teacher_id):
            raise ValueError("Платёж не найден")
        await self.payment_repo.update(payment, data.model_dump(exclude_unset=True))
        await self.db.commit()
        return self._payment_to_response(payment)

    async def delete_payment(self, payment_id: int, teacher_id: int) -> None:
        payment = await self.payment_repo.get_by_id(payment_id)
        if not payment:
            raise ValueError("Платёж не найден")
        if not await self.ts_repo.check_student_belongs_to_teacher(payment.student_id, teacher_id):
            raise ValueError("Платёж не найден")

        # Если удаляем оплаченный per_lesson — списываем с баланса
        if payment.status == "paid" and payment.payment_type == "per_lesson":
            student = await self.db.get(User, payment.student_id)
            if student:
                student.balance = (student.balance or 0) - payment.amount

        await self.payment_repo.delete(payment)
        await self.db.commit()

    async def mark_payment_paid(self, payment_id: int, teacher_id: int) -> PaymentResponse:
        payment = await self.payment_repo.get_by_id(payment_id)
        if not payment:
            raise ValueError("Платёж не найден")
        if not await self.ts_repo.check_student_belongs_to_teacher(payment.student_id, teacher_id):
            raise ValueError("Платёж не найден")
        was_already_paid = payment.status == "paid"
        await self.payment_repo.mark_paid(payment)

        # Пополнение баланса: per_lesson перешёл в paid (только если не был paid раньше)
        new_balance = None
        if not was_already_paid and payment.payment_type == "per_lesson":
            student = await self.db.get(User, payment.student_id)
            if student:
                student.balance = (student.balance or 0) + payment.amount
                new_balance = student.balance

        await self.db.commit()
        return self._payment_to_response(payment, new_balance)

    async def cancel_payment(self, payment_id: int, teacher_id: int) -> PaymentResponse:
        payment = await self.payment_repo.get_by_id(payment_id)
        if not payment:
            raise ValueError("Платёж не найден")
        if not await self.ts_repo.check_student_belongs_to_teacher(payment.student_id, teacher_id):
            raise ValueError("Платёж не найден")
        was_paid = payment.status == "paid"
        is_per_lesson = payment.payment_type == "per_lesson"
        await self.payment_repo.mark_cancelled(payment)

        # Если отменяем оплаченный per_lesson — списываем с баланса
        new_balance = None
        if was_paid and is_per_lesson:
            student = await self.db.get(User, payment.student_id)
            if student:
                student.balance = (student.balance or 0) - payment.amount
                new_balance = student.balance

        await self.db.commit()
        return self._payment_to_response(payment, new_balance)

    async def payment_stats(self, teacher_id: int,
                             from_date: Optional[datetime] = None,
                             to_date: Optional[datetime] = None,
                             student_id: Optional[int] = None) -> dict:
        return await self.payment_repo.stats_for_teacher(teacher_id, from_date, to_date, student_id)

    async def confirm_payment_via_telegram(self, data: TelegramPaymentRequest) -> TelegramPaymentResponse:
        """Подтверждение оплаты, пришедшей через Telegram-бота.

        Учитель в ТГ-боте проверяет чек от родителя, вводит сумму и username ученика.
        ТГ-бот вызывает этот метод.
        """
        clean_teacher = data.teacher_tg_username.lstrip("@")
        clean_student = data.student_tg_username.lstrip("@")

        # 1. Ищем учителя по tg_username — ТОЛЬКО teacher/admin, иначе ошибка
        teacher = await self.user_repo.get_user_by_tg_username_and_roles(
            data.teacher_tg_username, roles=("teacher", "admin")
        )
        if not teacher:
            raise ValueError(f"Пользователь @{clean_teacher} не является учителем")

        # 2. Ищем ученика по tg_username — ТОЛЬКО student
        student = await self.user_repo.get_user_by_tg_username_and_roles(
            data.student_tg_username, roles=("student",)
        )
        if not student:
            raise ValueError(f"Ученик @{clean_student} не найден")

        # 3. Проверяем, что студент привязан к этому учителю
        if not await self.ts_repo.check_student_belongs_to_teacher(student.id, teacher.id):
            raise ValueError(f"Ученик @{data.student_tg_username} не привязан к вам")

        # 4. Создаём платёж (per_lesson по умолчанию, сразу paid)
        payment_data = {
            "student_id": student.id,
            "payment_type": data.payment_type,
            "amount": data.amount,
            "lesson_id": None,
            "package_total": data.package_total,
            "valid_from": data.valid_from,
            "valid_until": data.valid_until,
            "status": "paid",
            "comment": data.comment or f"Оплата через Telegram (подтвердил @{data.teacher_tg_username.lstrip('@')})",
        }
        payment = await self.payment_repo.create(payment_data)

        # 5. Пополняем баланс для per_lesson
        if data.payment_type == "per_lesson":
            student.balance = (student.balance or 0) + data.amount

        await self.db.commit()

        student_name = f"{student.first_name or ''} {student.last_name or ''}".strip() or student.username

        return TelegramPaymentResponse(
            payment_id=payment.id,
            student_id=student.id,
            student_name=student_name,
            amount=data.amount,
            payment_type=data.payment_type,
            status="paid",
            comment=data.comment,
        )

    async def reject_payment_via_telegram(self, data: TelegramPaymentRequest) -> dict:
        """Отклонение платежа, пришедшего через Telegram-бота.

        Просто логирует факт отклонения — баланс не меняется.
        """
        logger.info(
            f"Telegram payment rejected: teacher=@{data.teacher_tg_username}, "
            f"student=@{data.student_tg_username}, amount={data.amount}, "
            f"reason={data.comment}"
        )
        return {
            "ok": True,
            "detail": "Платёж отклонён (баланс не менялся)",
        }

    def _payment_to_response(self, payment, student_balance: int = None) -> PaymentResponse:
        if student_balance is None:
            try:
                if payment.student:
                    student_balance = payment.student.balance
            except Exception:
                pass
        return PaymentResponse(
            id=payment.id,
            lesson_id=payment.lesson_id,
            student_id=payment.student_id,
            payment_type=payment.payment_type,
            amount=payment.amount,
            status=payment.status,
            package_total=payment.package_total,
            package_used=payment.package_used,
            valid_from=payment.valid_from,
            valid_until=payment.valid_until,
            comment=payment.comment,
            paid_at=payment.paid_at,
            created_at=payment.created_at,
            student_balance=student_balance,
        )
