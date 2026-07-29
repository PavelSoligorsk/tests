"""API эндпоинты для интеграции с Telegram-ботом.
Вызываются из ТГ-бота для подтверждения оплаты, которую прислал родитель.
"""

from __future__ import annotations

import os
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from services.schedule_service import ScheduleService
from dto_schemas.schedule import TelegramPaymentRequest, TelegramPaymentResponse

router = APIRouter(prefix="/telegram", tags=["Telegram Bot"])

# Ключ, который ТГ-бот передаёт в заголовке X-Telegram-Bot-Key
# Берётся из .env → TELEGRAM_BOT_TOKEN
TG_BOT_API_KEY = os.getenv("TELEGRAM_BOT_TOKEN", "tg-bot-secret-change-me")


def verify_bot_key(x_telegram_bot_key: str = Header(...)) -> str:
    """Проверяет, что запрос пришёл от нашего ТГ-бота."""
    if x_telegram_bot_key != TG_BOT_API_KEY:
        raise HTTPException(status_code=403, detail="Неверный ключ Telegram-бота")
    return x_telegram_bot_key


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
