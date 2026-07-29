"""API эндпоинты расписания: занятия, оплаты, родители — только для учителя."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List
from datetime import datetime

from core.models import User
from core import auth
from core.database import get_db
from services.schedule_service import ScheduleService

from dto_schemas.schedule import (
    ParentCreate, ParentUpdate, ParentResponse,
    ScheduleCreate, ScheduleUpdate, ScheduleResponse,
    LessonCreate, LessonReschedule, LessonUpdate, LessonResponse,
    PaymentCreate, PaymentUpdate, PaymentResponse,
    CalendarResponse,
)

router = APIRouter(prefix="/teacher", tags=["Teacher Schedule"])


def get_schedule_service(db: AsyncSession = Depends(get_db)) -> ScheduleService:
    return ScheduleService(db)


def check_teacher(user: User = Depends(auth.get_current_user)):
    if user.role not in ("teacher", "admin"):
        raise HTTPException(status_code=403, detail="Требуется роль teacher или admin")
    return user


# ═══════════════════════════════════════════════════════════
# Parents
# ═══════════════════════════════════════════════════════════

@router.post("/parents", response_model=ParentResponse)
async def create_parent(
    data: ParentCreate,
    current_user: User = Depends(check_teacher),
    service: ScheduleService = Depends(get_schedule_service),
):
    try:
        return await service.create_parent(data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/parents", response_model=List[ParentResponse])
async def list_parents(
    current_user: User = Depends(check_teacher),
    service: ScheduleService = Depends(get_schedule_service),
):
    return await service.list_parents(current_user.id)


@router.get("/parents/{parent_id}", response_model=ParentResponse)
async def get_parent(
    parent_id: int,
    current_user: User = Depends(check_teacher),
    service: ScheduleService = Depends(get_schedule_service),
):
    try:
        return await service.get_parent(parent_id, current_user.id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/parents/{parent_id}", response_model=ParentResponse)
async def update_parent(
    parent_id: int,
    data: ParentUpdate,
    current_user: User = Depends(check_teacher),
    service: ScheduleService = Depends(get_schedule_service),
):
    try:
        return await service.update_parent(parent_id, data)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/parents/{parent_id}")
async def delete_parent(
    parent_id: int,
    current_user: User = Depends(check_teacher),
    service: ScheduleService = Depends(get_schedule_service),
):
    try:
        await service.delete_parent(parent_id)
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/parents/{parent_id}/link-student/{student_id}")
async def link_parent_student(
    parent_id: int,
    student_id: int,
    current_user: User = Depends(check_teacher),
    service: ScheduleService = Depends(get_schedule_service),
):
    ok = await service.link_parent_student(parent_id, student_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Студент не найден")
    return {"ok": True}


@router.delete("/parents/unlink-student/{student_id}")
async def unlink_parent_student(
    student_id: int,
    current_user: User = Depends(check_teacher),
    service: ScheduleService = Depends(get_schedule_service),
):
    ok = await service.unlink_parent_student(student_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Студент не найден")
    return {"ok": True}


# ═══════════════════════════════════════════════════════════
# Schedules
# ═══════════════════════════════════════════════════════════

@router.post("/schedules", response_model=ScheduleResponse)
async def create_schedule(
    data: ScheduleCreate,
    current_user: User = Depends(check_teacher),
    service: ScheduleService = Depends(get_schedule_service),
):
    try:
        return await service.create_schedule(current_user.id, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/schedules", response_model=List[ScheduleResponse])
async def list_schedules(
    current_user: User = Depends(check_teacher),
    service: ScheduleService = Depends(get_schedule_service),
):
    return await service.list_schedules(current_user.id)


@router.get("/schedules/{schedule_id}", response_model=ScheduleResponse)
async def get_schedule(
    schedule_id: int,
    current_user: User = Depends(check_teacher),
    service: ScheduleService = Depends(get_schedule_service),
):
    try:
        return await service.get_schedule(schedule_id, current_user.id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/schedules/{schedule_id}", response_model=ScheduleResponse)
async def update_schedule(
    schedule_id: int,
    data: ScheduleUpdate,
    current_user: User = Depends(check_teacher),
    service: ScheduleService = Depends(get_schedule_service),
):
    try:
        return await service.update_schedule(schedule_id, current_user.id, data)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/schedules/{schedule_id}/toggle", response_model=ScheduleResponse)
async def toggle_schedule(
    schedule_id: int,
    active: bool = Query(..., description="true = включить, false = приостановить"),
    current_user: User = Depends(check_teacher),
    service: ScheduleService = Depends(get_schedule_service),
):
    try:
        return await service.toggle_schedule(schedule_id, current_user.id, active)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/schedules/{schedule_id}")
async def delete_schedule(
    schedule_id: int,
    current_user: User = Depends(check_teacher),
    service: ScheduleService = Depends(get_schedule_service),
):
    try:
        await service.delete_schedule(schedule_id, current_user.id)
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ═══════════════════════════════════════════════════════════
# Lessons
# ═══════════════════════════════════════════════════════════

@router.post("/lessons", response_model=LessonResponse)
async def create_lesson(
    data: LessonCreate,
    current_user: User = Depends(check_teacher),
    service: ScheduleService = Depends(get_schedule_service),
):
    try:
        return await service.create_lesson(current_user.id, data)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.get("/calendar", response_model=CalendarResponse)
async def get_calendar(
    date_from: datetime = Query(..., description="Дата начала (ISO)"),
    date_to: datetime = Query(..., description="Дата окончания (ISO)"),
    current_user: User = Depends(check_teacher),
    service: ScheduleService = Depends(get_schedule_service),
):
    return await service.calendar(current_user.id, date_from, date_to)


@router.get("/lessons/{lesson_id}", response_model=LessonResponse)
async def get_lesson(
    lesson_id: int,
    current_user: User = Depends(check_teacher),
    service: ScheduleService = Depends(get_schedule_service),
):
    try:
        return await service.get_lesson(lesson_id, current_user.id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/lessons/{lesson_id}/complete", response_model=LessonResponse)
async def complete_lesson(
    lesson_id: int,
    current_user: User = Depends(check_teacher),
    service: ScheduleService = Depends(get_schedule_service),
):
    try:
        return await service.complete_lesson(lesson_id, current_user.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/lessons/{lesson_id}/cancel", response_model=LessonResponse)
async def cancel_lesson(
    lesson_id: int,
    note: Optional[str] = Query(None),
    current_user: User = Depends(check_teacher),
    service: ScheduleService = Depends(get_schedule_service),
):
    try:
        return await service.cancel_lesson(lesson_id, current_user.id, note)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/lessons/{lesson_id}/reschedule", response_model=LessonResponse)
async def reschedule_lesson(
    lesson_id: int,
    data: LessonReschedule,
    current_user: User = Depends(check_teacher),
    service: ScheduleService = Depends(get_schedule_service),
):
    try:
        return await service.reschedule_lesson(lesson_id, current_user.id, data)
    except ValueError as e:
        raise HTTPException(status_code=409 if "Конфликт" in str(e) else 400, detail=str(e))


@router.delete("/lessons/{lesson_id}")
async def delete_lesson(
    lesson_id: int,
    current_user: User = Depends(check_teacher),
    service: ScheduleService = Depends(get_schedule_service),
):
    try:
        await service.delete_lesson(lesson_id, current_user.id)
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/lessons/{lesson_id}", response_model=LessonResponse)
async def update_lesson(
    lesson_id: int,
    data: LessonUpdate,
    current_user: User = Depends(check_teacher),
    service: ScheduleService = Depends(get_schedule_service),
):
    try:
        return await service.update_lesson(lesson_id, current_user.id, data)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ═══════════════════════════════════════════════════════════
# Payments
# ═══════════════════════════════════════════════════════════

@router.post("/payments", response_model=PaymentResponse)
async def create_payment(
    data: PaymentCreate,
    current_user: User = Depends(check_teacher),
    service: ScheduleService = Depends(get_schedule_service),
):
    return await service.create_payment(current_user.id, data)


@router.get("/payments", response_model=List[PaymentResponse])
async def list_payments(
    student_id: Optional[int] = Query(None),
    current_user: User = Depends(check_teacher),
    service: ScheduleService = Depends(get_schedule_service),
):
    if student_id:
        return await service.list_payments_for_student(student_id, current_user.id)
    return await service.list_payments_for_teacher(current_user.id)


@router.post("/payments/{payment_id}/paid", response_model=PaymentResponse)
async def mark_payment_paid(
    payment_id: int,
    current_user: User = Depends(check_teacher),
    service: ScheduleService = Depends(get_schedule_service),
):
    try:
        return await service.mark_payment_paid(payment_id, current_user.id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/payments/{payment_id}", response_model=PaymentResponse)
async def update_payment(
    payment_id: int,
    data: PaymentUpdate,
    current_user: User = Depends(check_teacher),
    service: ScheduleService = Depends(get_schedule_service),
):
    try:
        return await service.update_payment(payment_id, current_user.id, data)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/payments/{payment_id}")
async def delete_payment(
    payment_id: int,
    current_user: User = Depends(check_teacher),
    service: ScheduleService = Depends(get_schedule_service),
):
    try:
        await service.delete_payment(payment_id, current_user.id)
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/payments/{payment_id}/cancel", response_model=PaymentResponse)
async def cancel_payment(
    payment_id: int,
    current_user: User = Depends(check_teacher),
    service: ScheduleService = Depends(get_schedule_service),
):
    try:
        return await service.cancel_payment(payment_id, current_user.id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/payments/stats")
async def payment_stats(
    from_date: Optional[datetime] = Query(None),
    to_date: Optional[datetime] = Query(None),
    student_id: Optional[int] = Query(None),
    current_user: User = Depends(check_teacher),
    service: ScheduleService = Depends(get_schedule_service),
):
    return await service.payment_stats(current_user.id, from_date, to_date, student_id)
