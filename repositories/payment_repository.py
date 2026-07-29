from sqlalchemy import select, delete, update, func
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List
from datetime import datetime

from core.models import Payment


class PaymentRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, payment_id: int) -> Optional[Payment]:
        r = await self.db.execute(select(Payment).where(Payment.id == payment_id))
        return r.scalars().first()

    async def get_by_lesson(self, lesson_id: int) -> Optional[Payment]:
        """Найти платёж per_lesson (списание) для конкретного урока."""
        r = await self.db.execute(
            select(Payment).where(
                Payment.lesson_id == lesson_id,
                Payment.payment_type == "per_lesson",
                Payment.status == "paid",
            )
        )
        return r.scalars().first()

    async def list_by_student(self, student_id: int) -> List[Payment]:
        r = await self.db.execute(
            select(Payment).where(Payment.student_id == student_id).order_by(Payment.created_at.desc())
        )
        return r.scalars().all()

    async def list_by_teacher(self, teacher_id: int) -> List[Payment]:
        """Все платежи учеников данного учителя."""
        from core.models import User, TeacherStudent
        subq = (
            select(User.id)
            .join(TeacherStudent, TeacherStudent.student_id == User.id)
            .where(TeacherStudent.teacher_id == teacher_id)
            .subquery()
        )
        r = await self.db.execute(
            select(Payment).where(Payment.student_id.in_(subq)).order_by(Payment.created_at.desc())
        )
        return r.scalars().all()

    async def create(self, data: dict) -> Payment:
        status = data.get("status", "paid")
        paid_at = data.get("paid_at")
        if paid_at is None and status == "paid":
            paid_at = datetime.utcnow()
        payment = Payment(
            lesson_id=data.get("lesson_id"),
            student_id=data["student_id"],
            payment_type=data["payment_type"],
            amount=data["amount"],
            status=status,
            package_total=data.get("package_total"),
            package_used=0,
            valid_from=data.get("valid_from"),
            valid_until=data.get("valid_until"),
            comment=data.get("comment"),
            paid_at=paid_at,
            created_at=datetime.utcnow(),
        )
        self.db.add(payment)
        await self.db.flush()
        return payment

    async def update_status(self, payment: Payment, status: str) -> Payment:
        payment.status = status
        if status == "paid" and not payment.paid_at:
            payment.paid_at = datetime.utcnow()
        await self.db.flush()
        return payment

    async def update(self, payment: Payment, data: dict) -> Payment:
        """Обновить платёж (все поля кроме id)."""
        for field in ("amount", "package_total", "package_used", "comment",
                       "valid_from", "valid_until", "lesson_id"):
            if field in data and data[field] is not None:
                setattr(payment, field, data[field])
        # status — особая обработка: если меняется на paid, проставляем paid_at
        if "status" in data and data["status"] is not None:
            new_status = data["status"]
            payment.status = new_status
            if new_status == "paid" and not payment.paid_at:
                payment.paid_at = datetime.utcnow()
        # paid_at — можно передать явно
        if "paid_at" in data and data["paid_at"] is not None:
            payment.paid_at = data["paid_at"]
        await self.db.flush()
        return payment

    async def mark_paid(self, payment: Payment) -> Payment:
        return await self.update_status(payment, "paid")

    async def mark_cancelled(self, payment: Payment) -> Payment:
        return await self.update_status(payment, "cancelled")

    async def use_package_lesson(self, student_id: int) -> Optional[Payment]:
        """Списать одно занятие из активного пакета. Возвращает платёж или None."""
        r = await self.db.execute(
            select(Payment).where(
                Payment.student_id == student_id,
                Payment.payment_type == "package",
                Payment.status == "paid",
                Payment.package_total > Payment.package_used,
            ).order_by(Payment.created_at.asc())
        )
        package = r.scalars().first()
        if package:
            package.package_used += 1
            await self.db.flush()
        return package

    async def has_active_subscription(self, student_id: int) -> bool:
        """Есть ли активная месячная подписка."""
        now = datetime.utcnow()
        r = await self.db.execute(
            select(Payment).where(
                Payment.student_id == student_id,
                Payment.payment_type == "monthly",
                Payment.status == "paid",
                Payment.valid_from <= now,
                Payment.valid_until >= now,
            )
        )
        return r.scalars().first() is not None

    async def has_active_package(self, student_id: int) -> bool:
        """Есть ли неизрасходованный пакет занятий."""
        r = await self.db.execute(
            select(Payment).where(
                Payment.student_id == student_id,
                Payment.payment_type == "package",
                Payment.status == "paid",
                Payment.package_total > Payment.package_used,
            )
        )
        return r.scalars().first() is not None

    async def batch_active_covers(self, student_ids: list[int]) -> dict[int, dict]:
        """Для списка студентов вернуть: у кого активный monthly, у кого активный package.
        Возвращает {student_id: {"monthly": True/False, "package": True/False}}."""
        result: dict[int, dict] = {sid: {"monthly": False, "package": False} for sid in student_ids}
        if not student_ids:
            return result

        now = datetime.utcnow()
        # Monthly
        r = await self.db.execute(
            select(Payment.student_id).where(
                Payment.student_id.in_(student_ids),
                Payment.payment_type == "monthly",
                Payment.status == "paid",
                Payment.valid_from <= now,
                Payment.valid_until >= now,
            )
        )
        for (sid,) in r.all():
            result[sid]["monthly"] = True

        # Package
        r = await self.db.execute(
            select(Payment.student_id).where(
                Payment.student_id.in_(student_ids),
                Payment.payment_type == "package",
                Payment.status == "paid",
                Payment.package_total > Payment.package_used,
            )
        )
        for (sid,) in r.all():
            result[sid]["package"] = True

        return result

    async def delete(self, payment: Payment) -> None:
        await self.db.delete(payment)
        await self.db.flush()

    async def stats_for_teacher(self, teacher_id: int, from_date: datetime = None, to_date: datetime = None,
                                 student_id: Optional[int] = None) -> dict:
        """Статистика по платежам для учителя. Опционально фильтруется по student_id."""
        from core.models import User, TeacherStudent

        if student_id:
            # Статистика по конкретному ученику
            base = select(Payment).where(Payment.student_id == student_id)
        else:
            subq = (
                select(User.id)
                .join(TeacherStudent, TeacherStudent.student_id == User.id)
                .where(TeacherStudent.teacher_id == teacher_id)
                .subquery()
            )
            base = select(Payment).where(Payment.student_id.in_(subq))
        if from_date:
            base = base.where(Payment.created_at >= from_date)
        if to_date:
            base = base.where(Payment.created_at <= to_date)

        paid_stmt = base.where(Payment.status == "paid")
        r_paid = await self.db.execute(paid_stmt)
        paid = r_paid.scalars().all()

        total = sum(p.amount for p in paid)
        per_lesson = sum(p.amount for p in paid if p.payment_type == "per_lesson")
        monthly = sum(p.amount for p in paid if p.payment_type == "monthly")
        package = sum(p.amount for p in paid if p.payment_type == "package")

        return {
            "total": total,
            "per_lesson": per_lesson,
            "monthly": monthly,
            "package": package,
            "count": len(paid),
            "pending_count": await self.db.scalar(
                select(func.count()).select_from(base.where(Payment.status == "pending").subquery())
            ) or 0,
        }
