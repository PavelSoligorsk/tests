"""Сервис Telegram-бота: бизнес-логика всех команд.

Вынесен из api/telegram_api.py по слоям: API → Service → Repository.
"""

from __future__ import annotations

import os
import secrets
import logging
from datetime import datetime, timedelta
from typing import List, Optional

from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import Parent, User, Lesson, TestAssignment
from dto_schemas.schedule import (
    TelegramWhoamiResponse,
    TelegramStudentBrief,
    TelegramBalanceResponse,
    TelegramPaymentBrief,
    TelegramPaymentStatsResponse,
    TelegramTeacherChatResponse,
    TelegramPaymentResponse,
    TelegramPaymentRequest,
)
from repositories.user_repository import UserRepository
from repositories.parent_repository import ParentRepository
from repositories.teacher_student_repository import TeacherStudentRepository
from repositories.payment_repository import PaymentRepository
from repositories.password_reset_repository import PasswordResetRepository
from repositories.lesson_repository import LessonRepository
from repositories.assignment_repository import AssignmentRepository
from services.notification_service import notification_service

logger = logging.getLogger("telegram_service")


class TelegramService:
    """Бизнес-логика Telegram-бота."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.user_repo = UserRepository(db)
        self.parent_repo = ParentRepository(db)
        self.ts_repo = TeacherStudentRepository(db)
        self.payment_repo = PaymentRepository(db)
        self.reset_repo = PasswordResetRepository(db)
        self.lesson_repo = LessonRepository(db)
        self.assignment_repo = AssignmentRepository(db)

    # ═══════════════════════════════════════════════════════════
    # whoami
    # ═══════════════════════════════════════════════════════════

    async def whoami(self, tg_username: str) -> TelegramWhoamiResponse:
        """Определить роль пользователя по tg_username."""
        clean = tg_username.lstrip("@")

        # 1. Учитель / admin
        teacher = await self.user_repo.get_user_by_tg_username_and_roles(
            clean, roles=("teacher", "admin")
        )
        if teacher:
            name = (
                f"{teacher.first_name or ''} {teacher.last_name or ''}".strip()
                or teacher.username
            )
            if teacher.role == "teacher":
                students = await self.ts_repo.get_teacher_students(teacher.id)
                return TelegramWhoamiResponse(
                    found=True,
                    role="teacher",
                    name=name,
                    tg_username=clean,
                    students_count=len(students),
                )
            else:
                return TelegramWhoamiResponse(
                    found=True,
                    role=teacher.role,
                    name=name,
                    tg_username=clean,
                    message="Администраторы работают через веб-интерфейс.",
                )

        # 2. Ученик
        student = await self.user_repo.get_user_by_tg_username_and_roles(
            clean, roles=("student",)
        )
        if student:
            name = (
                f"{student.first_name or ''} {student.last_name or ''}".strip()
                or student.username
            )
            return TelegramWhoamiResponse(
                found=True,
                role="student",
                name=name,
                tg_username=clean,
                message="Добро пожаловать! Используйте меню для навигации.",
            )

        # 3. Родитель
        r = await self.db.execute(
            sa_select(Parent).where(Parent.tg_username.in_([clean, f"@{clean}"]))
        )
        parent = r.scalars().first()

        if parent:
            student_ids = await self.parent_repo.get_student_ids(parent.id)
            children: List[TelegramStudentBrief] = []

            if student_ids:
                students = await self.user_repo.get_users_by_ids(student_ids)
                student_map: dict[int, User] = {s.id: s for s in students}

                links = await self.ts_repo.get_links_by_student_ids(student_ids)
                student_teacher_map: dict[int, list[int]] = {}
                for link in links:
                    student_teacher_map.setdefault(link.student_id, []).append(
                        link.teacher_id
                    )

                all_tids = [
                    tid for tids in student_teacher_map.values() for tid in tids
                ]
                teacher_map: dict[int, User] = {}
                if all_tids:
                    teachers = await self.user_repo.get_teachers_by_ids(all_tids)
                    teacher_map = {t.id: t for t in teachers}

                for sid in student_ids:
                    student = student_map.get(sid)
                    if not student:
                        continue
                    tids = student_teacher_map.get(sid, [])
                    teacher_name = None
                    if tids:
                        t = teacher_map.get(tids[0])
                        if t:
                            teacher_name = (
                                f"{t.first_name or ''} {t.last_name or ''}".strip()
                                or t.username
                            )

                    children.append(
                        TelegramStudentBrief(
                            id=student.id,
                            name=(
                                f"{student.first_name or ''} {student.last_name or ''}".strip()
                                or student.username
                            ),
                            tg_username=student.tg_username,
                            balance=student.balance or 0,
                            teacher_name=teacher_name,
                        )
                    )

            return TelegramWhoamiResponse(
                found=True,
                role="parent",
                name=parent.name,
                tg_username=clean,
                children=children,
            )

        # 4. Не найден
        return TelegramWhoamiResponse(found=False, tg_username=clean)

    # ═══════════════════════════════════════════════════════════
    # register_chat
    # ═══════════════════════════════════════════════════════════

    async def register_chat(self, tg_username: str, chat_id: int) -> bool:
        """Сохранить tg_chat_id пользователя."""
        user = await self.user_repo.get_user_by_tg_username(tg_username)
        if not user:
            return False
        await self.user_repo.update_chat_id(user.id, chat_id)
        await self.db.commit()
        return True

    # ═══════════════════════════════════════════════════════════
    # forgot_password
    # ═══════════════════════════════════════════════════════════

    async def forgot_password(self, tg_username: str) -> dict:
        """Сгенерировать токен и отправить ссылку в Telegram."""
        clean = tg_username.lstrip("@")
        user = await self.user_repo.get_user_by_tg_username(clean)

        if not user:
            return {"ok": False, "message": "Пользователь с таким Telegram username не найден."}

        chat_id = user.tg_chat_id
        if not chat_id:
            return {
                "ok": False,
                "message": "Сначала нажмите /start в боте, чтобы активировать аккаунт.",
            }

        await self.reset_repo.delete_existing_tokens(user.username)
        token = secrets.token_urlsafe(32)
        await self.reset_repo.create_token(
            email=user.username,
            token=token,
            expires_at=datetime.utcnow() + timedelta(hours=1),
        )
        await self.db.commit()

        frontend_url = os.getenv("FRONTEND_URL", "https://test-front-lac.vercel.app")
        reset_link = f"{frontend_url}/reset-password?token={token}"

        await notification_service.send_message(
            chat_id,
            (
                f"🔑 *Сброс пароля*\n\n"
                f"Для сброса пароля перейдите по ссылке:\n"
                f"{reset_link}\n\n"
                f"Ссылка действительна 1 час."
            ),
        )
        return {"ok": True, "message": "Ссылка для сброса пароля отправлена вам в Telegram."}

    # ═══════════════════════════════════════════════════════════
    # Баланс ученика
    # ═══════════════════════════════════════════════════════════

    async def get_student_balance(self, student_id: int, limit: int = 5) -> dict:
        """Баланс ученика + последние операции."""
        student = await self.user_repo.get_user_by_id(student_id)
        if not student or student.role != "student":
            raise ValueError("Ученик не найден")

        student_name = (
            f"{student.first_name or ''} {student.last_name or ''}".strip()
            or student.username
        )

        all_payments = await self.payment_repo.list_by_student(student_id)
        operations: List[TelegramPaymentBrief] = []
        for p in all_payments:
            if p.lesson_id:
                op_type = "withdrawal"
            else:
                op_type = "deposit"
            operations.append(
                TelegramPaymentBrief(
                    id=p.id,
                    type=op_type,
                    amount=p.amount,
                    payment_type=p.payment_type,
                    status=p.status,
                    comment=p.comment,
                    created_at=p.created_at,
                )
            )

        last_ops = sorted(
            operations,
            key=lambda o: o.created_at or datetime.min,
            reverse=True,
        )[:limit]

        return {
            "student_id": student.id,
            "student_name": student_name,
            "balance": student.balance or 0,
            "last_operations": [
                o.model_dump() for o in last_ops
            ],
        }

    # ═══════════════════════════════════════════════════════════
    # Статистика платежей
    # ═══════════════════════════════════════════════════════════

    async def get_payment_stats(
        self, student_id: int, page: int = 1, page_size: int = 5
    ) -> dict:
        """Статистика оплат ученика."""
        from math import ceil

        student = await self.user_repo.get_user_by_id(student_id)
        if not student or student.role != "student":
            raise ValueError("Ученик не найден")

        student_name = (
            f"{student.first_name or ''} {student.last_name or ''}".strip()
            or student.username
        )

        all_payments = await self.payment_repo.list_by_student(student_id)
        total_deposited = 0
        total_spent = 0
        operations: List[TelegramPaymentBrief] = []

        for p in all_payments:
            if p.status != "paid":
                continue
            if p.lesson_id:
                op_type = "withdrawal"
                total_spent += p.amount
            else:
                op_type = "deposit"
                total_deposited += p.amount
            operations.append(
                TelegramPaymentBrief(
                    id=p.id,
                    type=op_type,
                    amount=p.amount,
                    payment_type=p.payment_type,
                    status=p.status,
                    comment=p.comment,
                    created_at=p.created_at,
                )
            )

        ops_sorted = sorted(
            operations,
            key=lambda o: o.created_at or datetime.min,
            reverse=True,
        )
        total_items = len(ops_sorted)
        total_pages = max(1, ceil(total_items / page_size))
        page = min(page, total_pages)
        start = (page - 1) * page_size
        page_ops = ops_sorted[start : start + page_size]

        return {
            "student_id": student.id,
            "student_name": student_name,
            "balance": student.balance or 0,
            "total_deposited": total_deposited,
            "total_spent": total_spent,
            "payments": [o.model_dump() for o in page_ops],
            "page": page,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_prev": page > 1,
        }

    # ═══════════════════════════════════════════════════════════
    # Подтверждение / отклонение оплаты
    # ═══════════════════════════════════════════════════════════

    async def confirm_payment(self, data: TelegramPaymentRequest) -> dict:
        """Подтвердить оплату (делегирует в ScheduleService)."""
        from services.schedule_service import ScheduleService

        service = ScheduleService(self.db)
        result = await service.confirm_payment_via_telegram(data)
        return result.model_dump() if hasattr(result, "model_dump") else result

    async def reject_payment(self, data: TelegramPaymentRequest) -> dict:
        """Отклонить оплату."""
        from services.schedule_service import ScheduleService

        service = ScheduleService(self.db)
        return await service.reject_payment_via_telegram(data)

    # ═══════════════════════════════════════════════════════════
    # Chat учителя
    # ═══════════════════════════════════════════════════════════

    async def get_teacher_chat(self, student_id: int) -> dict:
        """Получить chat_id учителя ученика."""
        student = await self.user_repo.get_user_by_id(student_id)
        if not student or student.role != "student":
            raise ValueError("Ученик не найден")

        teachers = await self.ts_repo.get_teacher_students_for_student(student_id)
        if not teachers:
            return {"found": False, "student_id": student_id}

        teacher = teachers[0]
        return {
            "student_id": student_id,
            "teacher_tg_username": teacher.tg_username,
            "chat_id": teacher.tg_chat_id,
            "found": teacher.tg_chat_id is not None,
        }

    # ═══════════════════════════════════════════════════════════
    # Расписание (новое)
    # ═══════════════════════════════════════════════════════════

    async def get_schedule(
        self, tg_username: str, period: str = "week"
    ) -> dict:
        """Расписание занятий на неделю или месяц.

        Args:
            tg_username: @username пользователя
            period: "week" или "month"

        Returns:
            {"ok": True, "lessons": [...], "period": "week"}
        """
        clean = tg_username.lstrip("@")
        user = await self.user_repo.get_user_by_tg_username(clean)
        if not user:
            return {"ok": False, "message": "Пользователь не найден"}

        now = datetime.utcnow()
        if period == "week":
            start = now
            end = now + timedelta(days=7)
        elif period == "month":
            start = now
            end = now + timedelta(days=30)
        else:
            start = now
            end = now + timedelta(days=7)

        if user.role == "teacher":
            lessons = await self.lesson_repo.get_lessons_by_teacher(
                user.id, start, end
            )
        elif user.role == "student":
            lessons = await self.lesson_repo.get_lessons_by_student(
                user.id, start, end
            )
        else:
            return {"ok": False, "message": "Расписание доступно только учителям и ученикам"}

        result = []
        for lesson in lessons:
            if lesson.status == "cancelled":
                continue
            status_emoji = {
                "scheduled": "📅",
                "completed": "✅",
                "rescheduled": "🔄",
            }.get(lesson.status, "📅")

            date_str = lesson.scheduled_date.strftime("%d.%m.%Y") if lesson.scheduled_date else "?"
            start_time = lesson.scheduled_date.strftime("%H:%M") if lesson.scheduled_date else "?"
            end_dt = (
                lesson.scheduled_date + timedelta(minutes=lesson.duration_minutes)
                if lesson.scheduled_date
                else None
            )
            end_time = end_dt.strftime("%H:%M") if end_dt else "?"

            result.append({
                "id": lesson.id,
                "title": lesson.title,
                "date": date_str,
                "time": f"{start_time}–{end_time}",
                "status": lesson.status,
                "status_emoji": status_emoji,
                "teacher_note": lesson.teacher_note,
            })

        return {"ok": True, "lessons": result, "period": period}

    # ═══════════════════════════════════════════════════════════
    # Домашние задания (новое)
    # ═══════════════════════════════════════════════════════════

    async def get_my_assignments(self, tg_username: str) -> dict:
        """Назначенные тесты для ученика.

        Args:
            tg_username: @username ученика

        Returns:
            {"ok": True, "assignments": [...]}
        """
        clean = tg_username.lstrip("@")
        user = await self.user_repo.get_user_by_tg_username(clean)
        if not user or user.role != "student":
            return {"ok": False, "message": "Только ученики могут просматривать задания"}

        assignments = await self.assignment_repo.get_by_student_id(user.id)

        result = []
        for a in assignments:
            if a.is_completed:
                continue
            due = ""
            if a.due_date:
                days_left = (a.due_date - datetime.utcnow()).days
                due = f"⏳ {days_left} дн." if days_left > 0 else "⚠️ Просрочено"
            test_title = getattr(a.test, "title", f"Тест #{a.test_id}")

            result.append({
                "id": a.id,
                "test_id": a.test_id,
                "title": test_title,
                "due_date": a.due_date.strftime("%d.%m.%Y") if a.due_date else "Без срока",
                "due": due,
                "status": "completed" if a.is_completed else "pending",
            })

        return {"ok": True, "assignments": result}