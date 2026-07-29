"""DTO схемы для расписания, занятий, оплаты и родителей."""
from __future__ import annotations

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, ConfigDict


# ═══════════════════════════════════════════════════════════════
# Parent
# ═══════════════════════════════════════════════════════════════


class ParentCreate(BaseModel):
    name: str
    phone: Optional[str] = None
    tg_username: Optional[str] = None
    comment: Optional[str] = None
    student_ids: List[int] = []   # ID учеников, которых сразу привязать


class ParentUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    tg_username: Optional[str] = None
    comment: Optional[str] = None


class ParentResponse(BaseModel):
    id: int
    name: str
    phone: Optional[str] = None
    tg_username: Optional[str] = None
    comment: Optional[str] = None
    student_ids: List[int] = []
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# ═══════════════════════════════════════════════════════════════
# Lesson Schedule
# ═══════════════════════════════════════════════════════════════


class ScheduleCreate(BaseModel):
    title: str
    description: Optional[str] = None
    schedule_type: str = "individual"       # "individual" | "group"
    student_id: Optional[int] = None
    group_id: Optional[int] = None
    days_of_week: List[str]                 # ["mon", "wed", "fri"]
    time_start: str                         # "14:30"
    duration_minutes: int = 60
    price_per_lesson: Optional[int] = None
    recur_until: Optional[datetime] = None  # до какой даты генерировать (NULL = бессрочно)


class ScheduleUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    days_of_week: Optional[List[str]] = None
    time_start: Optional[str] = None
    duration_minutes: Optional[int] = None
    price_per_lesson: Optional[int] = None
    is_active: Optional[bool] = None
    recur_until: Optional[datetime] = None  # можно изменить дату окончания


class ScheduleResponse(BaseModel):
    id: int
    teacher_id: int
    title: str
    description: Optional[str] = None
    schedule_type: str
    student_id: Optional[int] = None
    group_id: Optional[int] = None
    days_of_week: List[str]
    time_start: str
    duration_minutes: int
    price_per_lesson: Optional[int] = None
    is_active: bool
    recur_until: Optional[datetime] = None  # до какой даты повторяется
    created_at: Optional[datetime] = None
    stopped_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# ═══════════════════════════════════════════════════════════════
# Lesson
# ═══════════════════════════════════════════════════════════════


class LessonCreate(BaseModel):
    """Разовое занятие (вне расписания)."""
    title: str
    lesson_type: str = "individual"
    student_id: Optional[int] = None
    group_id: Optional[int] = None
    scheduled_date: datetime
    duration_minutes: int = 60
    teacher_note: Optional[str] = None


class LessonReschedule(BaseModel):
    new_date: datetime
    reason: Optional[str] = None


class LessonUpdate(BaseModel):
    status: Optional[str] = None             # "completed" | "cancelled"
    teacher_note: Optional[str] = None
    actual_start: Optional[datetime] = None
    actual_end: Optional[datetime] = None


class LessonResponse(BaseModel):
    id: int
    schedule_id: Optional[int] = None
    teacher_id: int
    title: str
    lesson_type: str
    student_id: Optional[int] = None
    group_id: Optional[int] = None
    scheduled_date: datetime
    duration_minutes: int
    actual_start: Optional[datetime] = None
    actual_end: Optional[datetime] = None
    status: str
    rescheduled_from_id: Optional[int] = None
    rescheduled_to_id: Optional[int] = None
    teacher_note: Optional[str] = None
    created_at: Optional[datetime] = None

    # ── CALENDAR UI fields ──
    payment_status: Optional[str] = None      # "paid" | "unpaid" | None (no payment record)
    coverage_type: Optional[str] = None       # "per_lesson" | "monthly" | "package" — чем покрыто
    student_name: Optional[str] = None        # "Иван Петров" или None для групповых
    group_name: Optional[str] = None          # "Группа А" или None для индивидуальных
    student_balance: Optional[int] = None     # Текущий баланс ученика в копейках BYN

    model_config = ConfigDict(from_attributes=True)


# ═══════════════════════════════════════════════════════════════
# Payment
# ═══════════════════════════════════════════════════════════════


class PaymentCreate(BaseModel):
    student_id: int
    payment_type: str                         # "per_lesson" | "monthly" | "package"
    amount: int
    lesson_id: Optional[int] = None
    package_total: Optional[int] = None       # кол-во занятий в пакете
    valid_from: Optional[datetime] = None      # для monthly
    valid_until: Optional[datetime] = None     # для monthly
    status: Optional[str] = "paid"             # "paid" | "pending"
    comment: Optional[str] = None


class PaymentUpdate(BaseModel):
    status: Optional[str] = None
    paid_at: Optional[datetime] = None
    comment: Optional[str] = None


class PaymentResponse(BaseModel):
    id: int
    lesson_id: Optional[int] = None
    student_id: int
    payment_type: str
    amount: int
    status: str
    package_total: Optional[int] = None
    package_used: Optional[int] = None
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    comment: Optional[str] = None
    paid_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    student_balance: Optional[int] = None  # Баланс ученика после операции

    model_config = ConfigDict(from_attributes=True)


# ═══════════════════════════════════════════════════════════════
# Calendar / aggregated views
# ═══════════════════════════════════════════════════════════════


class CalendarDayResponse(BaseModel):
    date: str                              # "2026-07-28"
    lessons: List[LessonResponse] = []


class CalendarResponse(BaseModel):
    days: List[CalendarDayResponse] = []


# ═══════════════════════════════════════════════════════════════
# Telegram Payment (вызывается из ТГ-бота)
# ═══════════════════════════════════════════════════════════════


class TelegramPaymentRequest(BaseModel):
    """Запрос от ТГ-бота: учитель подтверждает платёж родителя."""
    teacher_tg_username: str   # @username учителя в Telegram
    student_tg_username: str   # @username ученика, за которого платит родитель
    amount: int                # сумма в копейках BYN
    payment_type: str = "per_lesson"  # "per_lesson" | "monthly" | "package"
    package_total: Optional[int] = None   # для пакетов
    valid_from: Optional[datetime] = None   # для monthly
    valid_until: Optional[datetime] = None  # для monthly
    comment: Optional[str] = None  # пояснение


class TelegramPaymentResponse(BaseModel):
    """Ответ для ТГ-бота."""
    payment_id: int
    student_id: int
    student_name: Optional[str] = None
    amount: int
    payment_type: str
    status: str
    comment: Optional[str] = None
    error: Optional[str] = None  # заполняется только при ошибке

    model_config = ConfigDict(from_attributes=True)


# ═══════════════════════════════════════════════════════════════
# Telegram Bot — whoami, parent, student info
# ═══════════════════════════════════════════════════════════════


class TelegramWhoamiResponse(BaseModel):
    """Информация о пользователе по tg_username."""
    found: bool
    role: Optional[str] = None              # "parent" | "teacher" | "student" | None
    name: Optional[str] = None               # Имя (для parent — имя родителя, для teacher/student — из User)
    tg_username: str                         # очищенный @username
    # Для parent — список детей
    children: Optional[List["TelegramStudentBrief"]] = None
    # Для teacher — краткая инфа
    students_count: Optional[int] = None
    # Для student — заглушка
    message: Optional[str] = None


class TelegramStudentBrief(BaseModel):
    """Краткая информация об ученике (для родителя)."""
    id: int
    name: str                                # "Иван Петров"
    tg_username: Optional[str] = None
    balance: int = 0                         # копейки BYN
    teacher_name: Optional[str] = None        # Имя учителя


class TelegramBalanceResponse(BaseModel):
    """Баланс ученика + последние операции."""
    student_id: int
    student_name: str
    balance: int                             # копейки BYN
    currency: str = "BYN"
    last_operations: List["TelegramPaymentBrief"] = []


class TelegramPaymentBrief(BaseModel):
    """Краткая запись платежа."""
    id: int
    type: str                                # "deposit" | "withdrawal"
    amount: int                              # копейки
    payment_type: str                        # "per_lesson" | "monthly" | "package"
    status: str
    comment: Optional[str] = None
    created_at: Optional[datetime] = None
