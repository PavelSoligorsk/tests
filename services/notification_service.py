"""Сервис отправки уведомлений в Telegram.

Единственное место в системе, которое работает с Telegram Bot API.
Все уведомления проходят через этот сервис.
"""

from __future__ import annotations

import os
import logging
import httpx
from typing import Optional

logger = logging.getLogger("notification_service")

# Bot token из .env
TG_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("BOT_TOKEN") or ""


class NotificationService:
    """Отправка сообщений через Telegram Bot API.

    Все методы статические — сервис не имеет состояния.
    """

    @staticmethod
    def _bot_token() -> str:
        """Токен бота (ленивое чтение, можно обновить через env)."""
        return os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("BOT_TOKEN") or ""

    @staticmethod
    async def send_message(
        chat_id: int,
        text: str,
        *,
        parse_mode: str = "Markdown",
        reply_markup: Optional[dict] = None,
    ) -> bool:
        """Отправить сообщение в Telegram чат.

        Args:
            chat_id: ID чата
            text: Текст сообщения
            parse_mode: "Markdown" или "HTML"
            reply_markup: inline_keyboard (опционально)

        Returns:
            True если отправлено успешно, иначе False.
        """
        bot_token = NotificationService._bot_token()
        if not bot_token:
            logger.error("TELEGRAM_BOT_TOKEN not set")
            return False

        payload: dict = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"https://api.telegram.org/bot{bot_token}/sendMessage",
                    json=payload,
                    timeout=10.0,
                )
            if resp.status_code != 200:
                logger.error(
                    f"Telegram sendMessage failed: {resp.status_code} {resp.text[:200]}"
                )
                return False
            return True
        except Exception as e:
            logger.error(f"Telegram sendMessage exception: {e}")
            return False

    @staticmethod
    async def edit_message(
        chat_id: int,
        message_id: int,
        text: str,
        *,
        parse_mode: str = "Markdown",
        reply_markup: Optional[dict] = None,
    ) -> bool:
        """Отредактировать существующее сообщение в Telegram.

        Args:
            chat_id: ID чата
            message_id: ID сообщения для редактирования
            text: Новый текст
            parse_mode: "Markdown" или "HTML"
            reply_markup: inline_keyboard (опционально)

        Returns:
            True если отредактировано успешно, иначе False.
        """
        bot_token = NotificationService._bot_token()
        if not bot_token:
            logger.error("TELEGRAM_BOT_TOKEN not set")
            return False

        payload: dict = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": parse_mode,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"https://api.telegram.org/bot{bot_token}/editMessageText",
                    json=payload,
                    timeout=10.0,
                )
            if resp.status_code != 200:
                logger.error(
                    f"Telegram editMessageText failed: {resp.status_code} {resp.text[:200]}"
                )
                return False
            return True
        except Exception as e:
            logger.error(f"Telegram editMessageText exception: {e}")
            return False

    async def _notify_user(
        self,
        user_id: int,
        text: str,
        *,
        parse_mode: str = "Markdown",
    ) -> bool:
        """Отправить уведомление пользователю.

        Args:
            user_id: ID пользователя в таблице users
            text: Текст сообщения
            parse_mode: формат

        Returns:
            True если отправлено, иначе False.
        """
        from repositories.user_repository import UserRepository
        from core.database import AsyncSession

        # Создаём сессию вручную (сервис вызывается из разных мест)
        from core.database import SessionLocal
        async with SessionLocal() as db:
            repo = UserRepository(db)
            user = await repo.get_user_by_id(user_id)
            if not user or not user.tg_chat_id:
                logger.warning(f"Cannot notify user {user_id}: no tg_chat_id")
                return False
            return await self.send_message(user.tg_chat_id, text, parse_mode=parse_mode)


# Глобальный экземпляр
notification_service = NotificationService()


# ═══════════════════════════════════════════════════════════════
# Шаблоны уведомлений (template functions)
# ═══════════════════════════════════════════════════════════════


def notify_test_assigned(student_id: int, test_title: str, test_id: int) -> str:
    """Ученику: назначен новый тест."""
    from core.config import settings
    return (
        f"🧪 *Назначен новый тест*\n\n"
        f"📝 {test_title}\n"
        f"🔗 [Пройти тест]({os.getenv('FRONTEND_URL', '')}/test/{test_id})"
    )


def notify_lesson_reminder(lesson_title: str, scheduled_date: str, time_start: str) -> str:
    """Напоминание о занятии за 24 часа."""
    return (
        f"⏰ *Напоминание о занятии*\n\n"
        f"📚 {lesson_title}\n"
        f"📅 {scheduled_date} в {time_start}"
    )


def notify_lesson_rescheduled(
    lesson_title: str, old_date: str, new_date: str, reason: str = ""
) -> str:
    """Занятие перенесено."""
    msg = (
        f"🔄 *Занятие перенесено*\n\n"
        f"📚 {lesson_title}\n"
        f"📅 Было: {old_date}\n"
        f"📅 Стало: {new_date}"
    )
    if reason:
        msg += f"\n📝 Причина: {reason}"
    return msg


def notify_lesson_cancelled(lesson_title: str, scheduled_date: str) -> str:
    """Занятие отменено."""
    return (
        f"❌ *Занятие отменено*\n\n"
        f"📚 {lesson_title}\n"
        f"📅 {scheduled_date}"
    )


def notify_lesson_completed(lesson_title: str, scheduled_date: str) -> str:
    """Занятие проведено."""
    return (
        f"✅ *Занятие проведено*\n\n"
        f"📚 {lesson_title}\n"
        f"📅 {scheduled_date}"
    )


def notify_balance_changed(
    student_name: str, amount: float, new_balance: float, operation: str
) -> str:
    """Баланс пополнен / списан."""
    sign = "🟢" if operation == "deposit" else "🔴"
    op_text = "пополнен" if operation == "deposit" else "списан"
    return (
        f"{sign} *Баланс {op_text}*\n\n"
        f"👤 {student_name}\n"
        f"💵 Сумма: {amount:.2f} BYN\n"
        f"💰 Новый баланс: {new_balance:.2f} BYN"
    )


def notify_payment_confirmed(payment_id: str, amount: float) -> str:
    """Родителю: оплата подтверждена."""
    return (
        f"✅ *Оплата подтверждена!*\n\n"
        f"ID: `{payment_id}`\n"
        f"Сумма: *{amount:.2f} BYN*\n"
        f"Баланс пополнен."
    )


def notify_payment_rejected(payment_id: str, reason: str = "") -> str:
    """Родителю: оплата отклонена."""
    msg = (
        f"❌ *Оплата отклонена*\n\n"
        f"ID: `{payment_id}`"
    )
    if reason:
        msg += f"\nПричина: {reason}"
    return msg


def notify_low_balance(student_name: str, balance: float) -> str:
    """Родителю: баланс ребёнка ниже порога."""
    return (
        f"⚠️ *Низкий баланс*\n\n"
        f"👤 {student_name}\n"
        f"💰 Баланс: {balance:.2f} BYN\n"
        f"Пожалуйста, пополните баланс."
    )


def notify_new_payment_for_teacher(
    payment_id: str, student_tg: str, amount: float
) -> str:
    """Учителю: новый платёж на проверку."""
    return (
        f"💳 *Новый платёж на проверку*\n\n"
        f"ID: `{payment_id}`\n"
        f"👤 Ученик: @{student_tg}\n"
        f"💵 Сумма: *{amount:.2f} BYN*"
    )