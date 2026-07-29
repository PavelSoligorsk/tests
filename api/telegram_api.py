"""API эндпоинты для интеграции с Telegram-ботом.

Методы:
- whoami:        определить роль пользователя по tg_username
- parent-info:   для родителя — список детей
- student-balance: баланс + история операций
- confirm-payment / reject-payment: работа с оплатами
"""

from __future__ import annotations

import os, datetime as _dt
from typing import List
from fastapi import APIRouter, Depends, HTTPException, Header, Query
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.models import Parent, User
from services.schedule_service import ScheduleService
from dto_schemas.schedule import (
    TelegramPaymentRequest,
    TelegramPaymentResponse,
    TelegramWhoamiResponse,
    TelegramStudentBrief,
    TelegramBalanceResponse,
    TelegramPaymentBrief,
)

router = APIRouter(prefix="/telegram", tags=["Telegram Bot"])

# Ключ, который ТГ-бот передаёт в заголовке X-Telegram-Bot-Key
# Берётся из .env → TELEGRAM_BOT_TOKEN
TG_BOT_API_KEY = os.getenv("TELEGRAM_BOT_TOKEN", "tg-bot-secret-change-me")


def verify_bot_key(x_telegram_bot_key: str = Header(...)) -> str:
    """Проверяет, что запрос пришёл от нашего ТГ-бота."""
    if x_telegram_bot_key != TG_BOT_API_KEY:
        raise HTTPException(status_code=403, detail="Неверный ключ Telegram-бота")
    return x_telegram_bot_key


# ═══════════════════════════════════════════════════════════════
# whoami — определение роли пользователя по tg_username
# ═══════════════════════════════════════════════════════════════


@router.get("/whoami/{tg_username}", response_model=TelegramWhoamiResponse)
async def whoami(
    tg_username: str,
    _api_key: str = Depends(verify_bot_key),
    db: AsyncSession = Depends(get_db),
):
    """Определяет, кто этот пользователь: родитель, учитель или ученик.

    Используется при /start в Telegram-боте для маршрутизации.
    """
    from repositories.user_repository import UserRepository
    from repositories.parent_repository import ParentRepository
    from repositories.teacher_student_repository import TeacherStudentRepository

    clean = tg_username.lstrip("@")

    # 1. Ищем родителя (по Parent.tg_username) — без backref, через прямой SQL
    from sqlalchemy import select as sa_select
    parent_repo = ParentRepository(db)
    r = await db.execute(
        sa_select(Parent).where(Parent.tg_username.in_([clean, f"@{clean}"]))
    )
    parent = r.scalars().first()

    if parent:
        # Получаем ID студентов родителя прямым запросом (не через backref)
        student_ids = await parent_repo.get_student_ids(parent.id)
        children: List[TelegramStudentBrief] = []

        if student_ids:
            # Загружаем студентов по ID
            user_repo_temp = UserRepository(db)
            students = await user_repo_temp.get_users_by_ids(student_ids)
            student_map: dict[int, User] = {s.id: s for s in students}

            # Связи с учителями
            ts_repo = TeacherStudentRepository(db)
            links = await ts_repo.get_links_by_student_ids(student_ids)
            student_teacher_map: dict[int, list[int]] = {}
            for link in links:
                student_teacher_map.setdefault(link.student_id, []).append(link.teacher_id)

            # Batch-запрос учителей
            all_teacher_ids = [tid for tids in student_teacher_map.values() for tid in tids]
            teacher_map: dict[int, User] = {}
            if all_teacher_ids:
                teachers = await user_repo_temp.get_teachers_by_ids(all_teacher_ids)
                teacher_map = {t.id: t for t in teachers}

            for sid in student_ids:
                student = student_map.get(sid)
                if not student:
                    continue
                teacher_ids_for_student = student_teacher_map.get(sid, [])
                teacher_name = None
                if teacher_ids_for_student:
                    t = teacher_map.get(teacher_ids_for_student[0])
                    if t:
                        teacher_name = f"{t.first_name or ''} {t.last_name or ''}".strip() or t.username

                children.append(TelegramStudentBrief(
                    id=student.id,
                    name=f"{student.first_name or ''} {student.last_name or ''}".strip() or student.username,
                    tg_username=student.tg_username,
                    balance=student.balance or 0,
                    teacher_name=teacher_name,
                ))

        return TelegramWhoamiResponse(
            found=True,
            role="parent",
            name=parent.name,
            tg_username=clean,
            children=children,
        )

    # 2. Ищем учителя или ученика (по User.tg_username)
    user_repo = UserRepository(db)
    user = await user_repo.get_user_by_tg_username(tg_username)

    if user:
        name = f"{user.first_name or ''} {user.last_name or ''}".strip() or user.username

        if user.role == "teacher":
            ts_repo = TeacherStudentRepository(db)
            students = await ts_repo.get_teacher_students(user.id)
            return TelegramWhoamiResponse(
                found=True,
                role="teacher",
                name=name,
                tg_username=clean,
                students_count=len(students),
            )

        elif user.role == "student":
            return TelegramWhoamiResponse(
                found=True,
                role="student",
                name=name,
                tg_username=clean,
                message="Функционал для учеников скоро появится! 🚀",
            )

        else:
            # admin — не поддерживается через бота
            return TelegramWhoamiResponse(
                found=True,
                role=user.role,
                name=name,
                tg_username=clean,
                message="Администраторы работают через веб-интерфейс.",
            )

    # 3. Не найден
    return TelegramWhoamiResponse(
        found=False,
        tg_username=clean,
    )


# ═══════════════════════════════════════════════════════════════
# Баланс ученика + история операций
# ═══════════════════════════════════════════════════════════════


@router.get("/student/{student_id}/balance", response_model=TelegramBalanceResponse)
async def get_student_balance_with_history(
    student_id: int,
    limit: int = Query(default=5, ge=0, le=20),
    _api_key: str = Depends(verify_bot_key),
    db: AsyncSession = Depends(get_db),
):
    """Возвращает баланс ученика + последние N операций (пополнения и списания).

    Используется родителем в боте для просмотра баланса ребёнка.
    """
    from repositories.user_repository import UserRepository
    from repositories.payment_repository import PaymentRepository

    user_repo = UserRepository(db)
    student = await user_repo.get_user_by_id(student_id)
    if not student:
        raise HTTPException(status_code=404, detail="Ученик не найден")
    if student.role != "student":
        raise HTTPException(status_code=400, detail="Пользователь не является учеником")

    student_name = f"{student.first_name or ''} {student.last_name or ''}".strip() or student.username

    payment_repo = PaymentRepository(db)
    all_payments = await payment_repo.list_by_student(student_id)

    # Формируем операции: deposit (пополнение) / withdrawal (списание)
    operations: List[TelegramPaymentBrief] = []
    for p in all_payments:
        # Определяем тип операции
        if p.payment_type == "per_lesson":
            # per_lesson с дебетовым статусом "paid" и без lesson_id — это пополнение баланса
            # per_lesson с lesson_id — это списание за урок
            if p.lesson_id:
                op_type = "withdrawal"
            else:
                op_type = "deposit"
        else:
            # monthly / package — всегда deposit
            op_type = "deposit"

        operations.append(TelegramPaymentBrief(
            id=p.id,
            type=op_type,
            amount=p.amount,
            payment_type=p.payment_type,
            status=p.status,
            comment=p.comment,
            created_at=p.created_at,
        ))

    # Последние N операций
    last_ops = sorted(
        operations,
        key=lambda o: o.created_at or _dt.datetime.min,
        reverse=True,
    )[:limit]

    return TelegramBalanceResponse(
        student_id=student.id,
        student_name=student_name,
        balance=student.balance or 0,
        last_operations=last_ops,
    )


# ═══════════════════════════════════════════════════════════════
# Подтверждение / отклонение оплаты (существующие методы)
# ═══════════════════════════════════════════════════════════════


@router.post("/confirm-payment", response_model=TelegramPaymentResponse)
async def confirm_payment_via_telegram(
    data: TelegramPaymentRequest,
    _api_key: str = Depends(verify_bot_key),
    db: AsyncSession = Depends(get_db),
):
    """ТГ-бот вызывает этот метод, когда учитель подтверждает оплату.

    Тело запроса:
        - teacher_tg_username: @username учителя (кто подтверждает)
        - student_tg_username: @username ученика (за кого заплатили)
        - amount: сумма в копейках BYN
        - payment_type: тип оплаты (по умолчанию "per_lesson")
        - comment: пояснение (опционально)

    Создаёт запись Payment со статусом "paid" и пополняет баланс ученика.
    """
    service = ScheduleService(db)
    try:
        return await service.confirm_payment_via_telegram(data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/student-balance/{student_tg_username}")
async def get_student_balance(
    student_tg_username: str,
    _api_key: str = Depends(verify_bot_key),
    db: AsyncSession = Depends(get_db),
):
    """ТГ-бот запрашивает текущий баланс ученика по Telegram username.

    Возвращает:
        - student_id, student_name, balance (копейки BYN)
    """
    from repositories.user_repository import UserRepository

    user_repo = UserRepository(db)
    student = await user_repo.get_user_by_tg_username(student_tg_username)
    if not student:
        raise HTTPException(status_code=404, detail="Ученик не найден")
    if student.role != "student":
        raise HTTPException(status_code=400, detail="Пользователь не является учеником")

    student_name = f"{student.first_name or ''} {student.last_name or ''}".strip() or student.username
    return {
        "student_id": student.id,
        "student_name": student_name,
        "balance": student.balance or 0,
    }


@router.post("/reject-payment")
async def reject_payment_via_telegram(
    data: TelegramPaymentRequest,
    _api_key: str = Depends(verify_bot_key),
    db: AsyncSession = Depends(get_db),
):
    """ТГ-бот вызывает этот метод, когда учитель отклоняет платёж.

    Возвращает статус операции (только для лога, баланс не меняется).
    """
    service = ScheduleService(db)
    try:
        result = await service.reject_payment_via_telegram(data)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
