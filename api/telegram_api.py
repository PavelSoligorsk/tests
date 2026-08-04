"""API эндпоинты для интеграции с Telegram-ботом.

Методы:
- whoami:        определить роль пользователя по tg_username
- Баланс / статистика / платежи
- register-chat: сохранить tg_chat_id
- forgot-password: сброс пароля через Telegram
- schedule:      расписание на неделю/месяц
- my-assignments: домашние задания
"""

from __future__ import annotations

import os, datetime as _dt
from typing import List
from fastapi import APIRouter, Depends, HTTPException, Header, Query
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from core.database import get_db
from core.models import Parent, User
from services.telegram_service import TelegramService
from dto_schemas.schedule import (
    TelegramPaymentRequest,
    TelegramPaymentResponse,
    TelegramWhoamiResponse,
    TelegramBalanceResponse,
    TelegramPaymentStatsResponse,
    TelegramRegisterChatRequest,
    TelegramTeacherChatResponse,
)

router = APIRouter(prefix="/telegram", tags=["Telegram Bot"])

# Ключ для проверки запросов от бота
TG_BOT_API_KEY = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("BOT_TOKEN") or "tg-bot-secret-change-me"


def verify_bot_key(x_telegram_bot_key: str = Header(...)) -> str:
    if x_telegram_bot_key != TG_BOT_API_KEY:
        import logging
        logging.getLogger(__name__).warning(
            f"Key mismatch! Received: ...{x_telegram_bot_key[-8:] if len(x_telegram_bot_key) >= 8 else x_telegram_bot_key}, "
            f"Expected: ...{TG_BOT_API_KEY[-8:] if len(TG_BOT_API_KEY) >= 8 else TG_BOT_API_KEY}"
        )
        raise HTTPException(status_code=403, detail="Неверный ключ Telegram-бота")
    return x_telegram_bot_key


def get_telegram_service(db: AsyncSession = Depends(get_db)) -> TelegramService:
    return TelegramService(db)


# ═══════════════════════════════════════════════════════════════
# whoami
# ═══════════════════════════════════════════════════════════════


@router.get("/whoami/{tg_username}", response_model=TelegramWhoamiResponse)
async def whoami(
    tg_username: str,
    _api_key: str = Depends(verify_bot_key),
    service: TelegramService = Depends(get_telegram_service),
):
    return await service.whoami(tg_username)


# ═══════════════════════════════════════════════════════════════
# Баланс ученика
# ═══════════════════════════════════════════════════════════════


@router.get("/student/{student_id}/balance")
async def get_student_balance_with_history(
    student_id: int,
    limit: int = Query(default=5, ge=0, le=20),
    _api_key: str = Depends(verify_bot_key),
    service: TelegramService = Depends(get_telegram_service),
):
    try:
        return await service.get_student_balance(student_id, limit)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/student/{student_id}/payment-stats")
async def get_payment_stats(
    student_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=5, ge=1, le=20),
    _api_key: str = Depends(verify_bot_key),
    service: TelegramService = Depends(get_telegram_service),
):
    try:
        return await service.get_payment_stats(student_id, page, page_size)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ═══════════════════════════════════════════════════════════════
# Платежи (подтверждение / отклонение)
# ═══════════════════════════════════════════════════════════════


@router.post("/confirm-payment", response_model=TelegramPaymentResponse)
async def confirm_payment_via_telegram(
    data: TelegramPaymentRequest,
    _api_key: str = Depends(verify_bot_key),
    service: TelegramService = Depends(get_telegram_service),
):
    try:
        return await service.confirm_payment(data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/student-balance/{student_tg_username}")
async def get_student_balance(
    student_tg_username: str,
    _api_key: str = Depends(verify_bot_key),
    db: AsyncSession = Depends(get_db),
):
    """ТГ-бот запрашивает текущий баланс ученика по Telegram username."""
    from repositories.user_repository import UserRepository
    user_repo = UserRepository(db)
    student = await user_repo.get_user_by_tg_username_and_roles(
        student_tg_username, roles=("student",)
    )
    if not student:
        raise HTTPException(status_code=404, detail="Ученик не найден")
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
    service: TelegramService = Depends(get_telegram_service),
):
    try:
        return await service.reject_payment(data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ═══════════════════════════════════════════════════════════════
# Chat registration
# ═══════════════════════════════════════════════════════════════


@router.post("/register-chat", response_model=TelegramTeacherChatResponse)
async def register_chat(
    data: TelegramRegisterChatRequest,
    _api_key: str = Depends(verify_bot_key),
    service: TelegramService = Depends(get_telegram_service),
):
    ok = await service.register_chat(data.tg_username, data.chat_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    return TelegramTeacherChatResponse(
        student_id=0,
        teacher_tg_username=data.tg_username,
        chat_id=data.chat_id,
        found=True,
    )


@router.get("/student/{student_id}/teacher-chat", response_model=TelegramTeacherChatResponse)
async def get_teacher_chat(
    student_id: int,
    _api_key: str = Depends(verify_bot_key),
    service: TelegramService = Depends(get_telegram_service),
):
    try:
        result = await service.get_teacher_chat(student_id)
        return TelegramTeacherChatResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ═══════════════════════════════════════════════════════════════
# Восстановление пароля
# ═══════════════════════════════════════════════════════════════


class TelegramForgotPasswordRequest(BaseModel):
    tg_username: str


class TelegramForgotPasswordResponse(BaseModel):
    ok: bool
    message: str


@router.post("/forgot-password", response_model=TelegramForgotPasswordResponse)
async def forgot_password_via_telegram(
    data: TelegramForgotPasswordRequest,
    _api_key: str = Depends(verify_bot_key),
    service: TelegramService = Depends(get_telegram_service),
):
    return await service.forgot_password(data.tg_username)


# ═══════════════════════════════════════════════════════════════
# Расписание (новое)
# ═══════════════════════════════════════════════════════════════


@router.get("/schedule")
async def get_schedule(
    tg_username: str = Query(...),
    period: str = Query(default="week", regex="^(week|month)$"),
    _api_key: str = Depends(verify_bot_key),
    service: TelegramService = Depends(get_telegram_service),
):
    """Расписание занятий на неделю или месяц.

    Query params:
        tg_username: @username пользователя
        period: "week" (7 дней) или "month" (30 дней)
    """
    return await service.get_schedule(tg_username, period)


# ═══════════════════════════════════════════════════════════════
# Домашние задания (новое)
# ═══════════════════════════════════════════════════════════════


@router.get("/my-assignments")
async def get_my_assignments(
    tg_username: str = Query(...),
    _api_key: str = Depends(verify_bot_key),
    service: TelegramService = Depends(get_telegram_service),
):
    """Назначенные тесты для ученика.

    Query params:
        tg_username: @username ученика
    """
    return await service.get_my_assignments(tg_username)