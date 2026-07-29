"""Асинхронные тесты для расписания: родители, занятия, оплаты."""
from __future__ import annotations

import pytest
from httpx import AsyncClient
from datetime import datetime, timedelta

from tests.helpers_async import _bearer


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════


async def _link_student_to_teacher(ac: AsyncClient, admin_token: str, teacher_id: int, student_id: int) -> None:
    resp = await ac.post(
        "/admin/assign-student-to-teacher",
        json={"teacher_id": teacher_id, "student_id": student_id},
        headers=_bearer(admin_token),
    )
    assert resp.status_code == 200, f"Link failed: {resp.text}"


async def _get_my_id(ac: AsyncClient, token: str) -> int:
    resp = await ac.get("/student/me", headers=_bearer(token))
    return resp.json()["user"]["id"]


async def _get_teacher_id(ac: AsyncClient, admin_token: str) -> int:
    resp = await ac.get("/admin/users", headers=_bearer(admin_token))
    users = resp.json()
    teacher = next((u for u in users if u["role"] == "teacher"), None)
    assert teacher, "No teacher found"
    return teacher["id"]


async def _create_group(ac: AsyncClient, teacher_token: str, name: str) -> dict:
    resp = await ac.post(
        "/teacher/groups/",
        json={"name": name, "description": "Test group"},
        headers=_bearer(teacher_token),
    )
    assert resp.status_code == 200, f"Create group failed: {resp.text}"
    return resp.json()


async def _add_student_to_group(ac: AsyncClient, teacher_token: str, group_id: int, student_id: int) -> None:
    resp = await ac.post(
        f"/teacher/groups/{group_id}/students",
        json={"student_ids": [student_id]},
        headers=_bearer(teacher_token),
    )
    assert resp.status_code == 200, f"Add student to group failed: {resp.text}"


def _next_monday() -> datetime:
    """Ближайший понедельник от текущего момента (UTC)."""
    now = datetime.utcnow()
    days_ahead = 0 - now.weekday()  # Monday=0
    if days_ahead <= 0:
        days_ahead += 7
    return now.replace(hour=14, minute=0, second=0, microsecond=0) + timedelta(days=days_ahead)


# ═══════════════════════════════════════════════════════════════
# 1. Parents
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_parent_create(async_client: AsyncClient, teacher_token: str, admin_token: str,
                              student_token: str) -> None:
    """Создание родителя."""
    resp = await async_client.post(
        "/teacher/parents",
        json={"name": "Мария Петрова", "phone": "+79001112233", "tg_username": "@maria_p", "comment": "Мама"},
        headers=_bearer(teacher_token),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["name"] == "Мария Петрова"
    assert data["phone"] == "+79001112233"
    assert data["tg_username"] == "@maria_p"
    assert data["comment"] == "Мама"
    assert data["student_ids"] == []
    assert data["id"] > 0


@pytest.mark.asyncio
async def test_parent_list(async_client: AsyncClient, teacher_token: str, admin_token: str,
                            student_token: str) -> None:
    """Список родителей — родители привязанных студентов."""
    teacher_id = await _get_teacher_id(async_client, admin_token)
    student_id = await _get_my_id(async_client, student_token)
    await _link_student_to_teacher(async_client, admin_token, teacher_id, student_id)

    # Создать родителя и привязать
    resp = await async_client.post(
        "/teacher/parents",
        json={"name": "Олег Сидоров", "phone": "+7999"},
        headers=_bearer(teacher_token),
    )
    parent_id = resp.json()["id"]

    await async_client.post(
        f"/teacher/parents/{parent_id}/link-student/{student_id}",
        headers=_bearer(teacher_token),
    )

    # Список
    resp = await async_client.get("/teacher/parents", headers=_bearer(teacher_token))
    assert resp.status_code == 200
    parents = resp.json()
    assert len(parents) == 1
    assert parents[0]["name"] == "Олег Сидоров"
    assert parents[0]["student_ids"] == [student_id]


@pytest.mark.asyncio
async def test_parent_update(async_client: AsyncClient, teacher_token: str) -> None:
    """Редактирование родителя."""
    resp = await async_client.post(
        "/teacher/parents",
        json={"name": "Анна Козлова"},
        headers=_bearer(teacher_token),
    )
    parent_id = resp.json()["id"]

    resp = await async_client.put(
        f"/teacher/parents/{parent_id}",
        json={"phone": "+79998887766", "comment": "Обновлён"},
        headers=_bearer(teacher_token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Анна Козлова"  # не изменилось
    assert data["phone"] == "+79998887766"
    assert data["comment"] == "Обновлён"


@pytest.mark.asyncio
async def test_parent_update_not_found(async_client: AsyncClient, teacher_token: str) -> None:
    """404 при редактировании несуществующего родителя."""
    resp = await async_client.put(
        "/teacher/parents/99999",
        json={"name": "X"},
        headers=_bearer(teacher_token),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_parent_delete(async_client: AsyncClient, teacher_token: str, admin_token: str,
                              student_token: str) -> None:
    """Удаление родителя — связь со студентом рвётся (SET NULL)."""
    teacher_id = await _get_teacher_id(async_client, admin_token)
    student_id = await _get_my_id(async_client, student_token)
    await _link_student_to_teacher(async_client, admin_token, teacher_id, student_id)

    resp = await async_client.post(
        "/teacher/parents",
        json={"name": "Удаляемый"},
        headers=_bearer(teacher_token),
    )
    parent_id = resp.json()["id"]
    await async_client.post(
        f"/teacher/parents/{parent_id}/link-student/{student_id}",
        headers=_bearer(teacher_token),
    )

    # Проверить что привязан
    resp = await async_client.get(f"/teacher/parents/{parent_id}", headers=_bearer(teacher_token))
    assert resp.json()["student_ids"] == [student_id]

    # Удалить
    resp = await async_client.delete(f"/teacher/parents/{parent_id}", headers=_bearer(teacher_token))
    assert resp.status_code == 200

    # Родитель удалён
    resp = await async_client.get(f"/teacher/parents/{parent_id}", headers=_bearer(teacher_token))
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_parent_link_unlink(async_client: AsyncClient, teacher_token: str, admin_token: str,
                                   student_token: str, student2_token: str) -> None:
    """Привязка и отвязка студентов от родителя."""
    teacher_id = await _get_teacher_id(async_client, admin_token)
    s1 = await _get_my_id(async_client, student_token)
    s2 = await _get_my_id(async_client, student2_token)
    await _link_student_to_teacher(async_client, admin_token, teacher_id, s1)
    await _link_student_to_teacher(async_client, admin_token, teacher_id, s2)

    resp = await async_client.post(
        "/teacher/parents",
        json={"name": "Родитель Двоих"},
        headers=_bearer(teacher_token),
    )
    parent_id = resp.json()["id"]

    # Привязать обоих
    for sid in (s1, s2):
        r = await async_client.post(
            f"/teacher/parents/{parent_id}/link-student/{sid}",
            headers=_bearer(teacher_token),
        )
        assert r.status_code == 200

    resp = await async_client.get(f"/teacher/parents/{parent_id}", headers=_bearer(teacher_token))
    assert sorted(resp.json()["student_ids"]) == sorted([s1, s2])

    # Отвязать s1
    r = await async_client.delete(
        f"/teacher/parents/unlink-student/{s1}",
        headers=_bearer(teacher_token),
    )
    assert r.status_code == 200

    resp = await async_client.get(f"/teacher/parents/{parent_id}", headers=_bearer(teacher_token))
    assert resp.json()["student_ids"] == [s2]


@pytest.mark.asyncio
async def test_parent_link_student_not_found(async_client: AsyncClient, teacher_token: str) -> None:
    """404 при привязке несуществующего студента."""
    resp = await async_client.post(
        "/teacher/parents",
        json={"name": "X"},
        headers=_bearer(teacher_token),
    )
    parent_id = resp.json()["id"]

    resp = await async_client.post(
        f"/teacher/parents/{parent_id}/link-student/99999",
        headers=_bearer(teacher_token),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_parent_access_denied_for_student(async_client: AsyncClient, student_token: str) -> None:
    """Студент не может работать с родителями."""
    resp = await async_client.get("/teacher/parents", headers=_bearer(student_token))
    assert resp.status_code == 403

    resp = await async_client.post(
        "/teacher/parents",
        json={"name": "X"},
        headers=_bearer(student_token),
    )
    assert resp.status_code == 403


# ═══════════════════════════════════════════════════════════════
# 2. Schedules
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_schedule_create_individual(async_client: AsyncClient, teacher_token: str,
                                           admin_token: str, student_token: str) -> None:
    """Создание индивидуального расписания — проверка автогенерации."""
    teacher_id = await _get_teacher_id(async_client, admin_token)
    student_id = await _get_my_id(async_client, student_token)
    await _link_student_to_teacher(async_client, admin_token, teacher_id, student_id)

    resp = await async_client.post(
        "/teacher/schedules",
        json={
            "title": "Английский",
            "schedule_type": "individual",
            "student_id": student_id,
            "days_of_week": ["mon", "wed"],
            "time_start": "15:00",
            "duration_minutes": 60,
            "price_per_lesson": 1200,
        },
        headers=_bearer(teacher_token),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["title"] == "Английский"
    assert data["schedule_type"] == "individual"
    assert data["student_id"] == student_id
    assert data["days_of_week"] == ["mon", "wed"]
    assert data["time_start"] == "15:00"
    assert data["duration_minutes"] == 60
    assert data["price_per_lesson"] == 1200
    assert data["is_active"] is True

    # Проверить что занятия сгенерировались (календарь на 4 недели)
    monday = _next_monday()
    date_from = monday.isoformat()
    date_to = (monday + timedelta(weeks=4)).isoformat()
    cal = await async_client.get(
        f"/teacher/calendar?date_from={date_from}&date_to={date_to}",
        headers=_bearer(teacher_token),
    )
    assert cal.status_code == 200
    days = cal.json()["days"]
    assert len(days) >= 2  # минимум 2 занятия (пн + ср) за 4 недели


@pytest.mark.asyncio
async def test_schedule_create_group(async_client: AsyncClient, teacher_token: str,
                                      admin_token: str, student_token: str) -> None:
    """Создание группового расписания."""
    teacher_id = await _get_teacher_id(async_client, admin_token)
    student_id = await _get_my_id(async_client, student_token)
    await _link_student_to_teacher(async_client, admin_token, teacher_id, student_id)

    group = await _create_group(async_client, teacher_token, "Группа А")
    await _add_student_to_group(async_client, teacher_token, group["id"], student_id)

    resp = await async_client.post(
        "/teacher/schedules",
        json={
            "title": "Групповое занятие",
            "schedule_type": "group",
            "group_id": group["id"],
            "days_of_week": ["fri"],
            "time_start": "18:00",
            "duration_minutes": 90,
        },
        headers=_bearer(teacher_token),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["schedule_type"] == "group"
    assert data["group_id"] == group["id"]


@pytest.mark.asyncio
async def test_schedule_create_missing_field(async_client: AsyncClient, teacher_token: str) -> None:
    """400 если не указан student_id для individual."""
    resp = await async_client.post(
        "/teacher/schedules",
        json={
            "title": "Без ученика",
            "schedule_type": "individual",
            "days_of_week": ["mon"],
            "time_start": "10:00",
            "duration_minutes": 45,
        },
        headers=_bearer(teacher_token),
    )
    assert resp.status_code == 400

    resp = await async_client.post(
        "/teacher/schedules",
        json={
            "title": "Без группы",
            "schedule_type": "group",
            "days_of_week": ["mon"],
            "time_start": "10:00",
            "duration_minutes": 45,
        },
        headers=_bearer(teacher_token),
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_schedule_list(async_client: AsyncClient, teacher_token: str, admin_token: str,
                              student_token: str) -> None:
    """Список расписаний учителя."""
    teacher_id = await _get_teacher_id(async_client, admin_token)
    student_id = await _get_my_id(async_client, student_token)
    await _link_student_to_teacher(async_client, admin_token, teacher_id, student_id)

    await async_client.post(
        "/teacher/schedules",
        json={
            "title": "S1", "schedule_type": "individual", "student_id": student_id,
            "days_of_week": ["mon"], "time_start": "10:00", "duration_minutes": 45,
        },
        headers=_bearer(teacher_token),
    )
    await async_client.post(
        "/teacher/schedules",
        json={
            "title": "S2", "schedule_type": "individual", "student_id": student_id,
            "days_of_week": ["tue"], "time_start": "11:00", "duration_minutes": 45,
        },
        headers=_bearer(teacher_token),
    )

    resp = await async_client.get("/teacher/schedules", headers=_bearer(teacher_token))
    assert resp.status_code == 200
    schedules = resp.json()
    assert len(schedules) == 2
    titles = {s["title"] for s in schedules}
    assert titles == {"S1", "S2"}


@pytest.mark.asyncio
async def test_schedule_get_not_found(async_client: AsyncClient, teacher_token: str) -> None:
    """404 для несуществующего расписания."""
    resp = await async_client.get("/teacher/schedules/99999", headers=_bearer(teacher_token))
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_schedule_update(async_client: AsyncClient, teacher_token: str, admin_token: str,
                                student_token: str) -> None:
    """Редактирование расписания."""
    teacher_id = await _get_teacher_id(async_client, admin_token)
    student_id = await _get_my_id(async_client, student_token)
    await _link_student_to_teacher(async_client, admin_token, teacher_id, student_id)

    resp = await async_client.post(
        "/teacher/schedules",
        json={
            "title": "До обновления", "schedule_type": "individual", "student_id": student_id,
            "days_of_week": ["mon"], "time_start": "12:00", "duration_minutes": 60,
        },
        headers=_bearer(teacher_token),
    )
    sched_id = resp.json()["id"]

    resp = await async_client.put(
        f"/teacher/schedules/{sched_id}",
        json={"title": "После обновления", "days_of_week": ["mon", "thu"], "price_per_lesson": 2000},
        headers=_bearer(teacher_token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "После обновления"
    assert data["days_of_week"] == ["mon", "thu"]
    assert data["price_per_lesson"] == 2000


@pytest.mark.asyncio
async def test_schedule_toggle(async_client: AsyncClient, teacher_token: str, admin_token: str,
                                student_token: str) -> None:
    """Включение/выключение расписания."""
    teacher_id = await _get_teacher_id(async_client, admin_token)
    student_id = await _get_my_id(async_client, student_token)
    await _link_student_to_teacher(async_client, admin_token, teacher_id, student_id)

    resp = await async_client.post(
        "/teacher/schedules",
        json={
            "title": "Toggle", "schedule_type": "individual", "student_id": student_id,
            "days_of_week": ["mon"], "time_start": "09:00", "duration_minutes": 30,
        },
        headers=_bearer(teacher_token),
    )
    sched_id = resp.json()["id"]

    # Выключить
    resp = await async_client.post(
        f"/teacher/schedules/{sched_id}/toggle?active=false",
        headers=_bearer(teacher_token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_active"] is False
    assert data["stopped_at"] is not None

    # Включить обратно
    resp = await async_client.post(
        f"/teacher/schedules/{sched_id}/toggle?active=true",
        headers=_bearer(teacher_token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_active"] is True
    assert data["stopped_at"] is None


@pytest.mark.asyncio
async def test_schedule_delete(async_client: AsyncClient, teacher_token: str, admin_token: str,
                                student_token: str) -> None:
    """Удаление расписания."""
    teacher_id = await _get_teacher_id(async_client, admin_token)
    student_id = await _get_my_id(async_client, student_token)
    await _link_student_to_teacher(async_client, admin_token, teacher_id, student_id)

    resp = await async_client.post(
        "/teacher/schedules",
        json={
            "title": "Удалить", "schedule_type": "individual", "student_id": student_id,
            "days_of_week": ["fri"], "time_start": "17:00", "duration_minutes": 60,
        },
        headers=_bearer(teacher_token),
    )
    sched_id = resp.json()["id"]

    resp = await async_client.delete(f"/teacher/schedules/{sched_id}", headers=_bearer(teacher_token))
    assert resp.status_code == 200

    resp = await async_client.get(f"/teacher/schedules/{sched_id}", headers=_bearer(teacher_token))
    assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════
# 3. Lessons
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_lesson_create_oneoff(async_client: AsyncClient, teacher_token: str, admin_token: str,
                                     student_token: str) -> None:
    """Создание разового занятия (вне расписания)."""
    teacher_id = await _get_teacher_id(async_client, admin_token)
    student_id = await _get_my_id(async_client, student_token)
    await _link_student_to_teacher(async_client, admin_token, teacher_id, student_id)

    slot = _next_monday() + timedelta(days=2)  # среда
    resp = await async_client.post(
        "/teacher/lessons",
        json={
            "title": "Консультация",
            "lesson_type": "individual",
            "student_id": student_id,
            "scheduled_date": slot.isoformat(),
            "duration_minutes": 45,
            "teacher_note": "Повторить тему 3",
        },
        headers=_bearer(teacher_token),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["title"] == "Консультация"
    assert data["student_id"] == student_id
    assert data["status"] == "scheduled"
    assert data["teacher_note"] == "Повторить тему 3"


@pytest.mark.asyncio
async def test_lesson_create_conflict(async_client: AsyncClient, teacher_token: str, admin_token: str,
                                       student_token: str) -> None:
    """409 при конфликте занятий по времени."""
    teacher_id = await _get_teacher_id(async_client, admin_token)
    student_id = await _get_my_id(async_client, student_token)
    await _link_student_to_teacher(async_client, admin_token, teacher_id, student_id)

    slot = _next_monday()

    # Первое занятие
    r1 = await async_client.post(
        "/teacher/lessons",
        json={"title": "Первое", "lesson_type": "individual", "student_id": student_id,
              "scheduled_date": slot.isoformat(), "duration_minutes": 60},
        headers=_bearer(teacher_token),
    )
    assert r1.status_code == 200

    # Второе — пересекается (через 30 мин от начала первого)
    conflict_slot = slot + timedelta(minutes=30)
    r2 = await async_client.post(
        "/teacher/lessons",
        json={"title": "Конфликт", "lesson_type": "individual", "student_id": student_id,
              "scheduled_date": conflict_slot.isoformat(), "duration_minutes": 60},
        headers=_bearer(teacher_token),
    )
    assert r2.status_code == 409, r2.text
    assert "Конфликт" in r2.json()["detail"]


@pytest.mark.asyncio
async def test_lesson_calendar(async_client: AsyncClient, teacher_token: str, admin_token: str,
                                student_token: str) -> None:
    """Календарь — группировка по дням."""
    teacher_id = await _get_teacher_id(async_client, admin_token)
    student_id = await _get_my_id(async_client, student_token)
    await _link_student_to_teacher(async_client, admin_token, teacher_id, student_id)

    mon = _next_monday()
    tue = mon + timedelta(days=1)

    for slot in (mon, tue):
        await async_client.post(
            "/teacher/lessons",
            json={"title": f"Lesson {slot.day}", "lesson_type": "individual",
                  "student_id": student_id, "scheduled_date": slot.isoformat(), "duration_minutes": 60},
            headers=_bearer(teacher_token),
        )

    date_from = mon.isoformat()
    date_to = (tue + timedelta(hours=1)).isoformat()
    resp = await async_client.get(
        f"/teacher/calendar?date_from={date_from}&date_to={date_to}",
        headers=_bearer(teacher_token),
    )
    assert resp.status_code == 200
    days = resp.json()["days"]
    assert len(days) == 2
    assert all(len(d["lessons"]) == 1 for d in days)
    assert days[0]["date"] == mon.strftime("%Y-%m-%d")
    assert days[1]["date"] == tue.strftime("%Y-%m-%d")


@pytest.mark.asyncio
async def test_lesson_complete(async_client: AsyncClient, teacher_token: str, admin_token: str,
                                student_token: str) -> None:
    """Завершение занятия."""
    teacher_id = await _get_teacher_id(async_client, admin_token)
    student_id = await _get_my_id(async_client, student_token)
    await _link_student_to_teacher(async_client, admin_token, teacher_id, student_id)

    slot = _next_monday()
    r = await async_client.post(
        "/teacher/lessons",
        json={"title": "Complete me", "lesson_type": "individual",
              "student_id": student_id, "scheduled_date": slot.isoformat(), "duration_minutes": 60},
        headers=_bearer(teacher_token),
    )
    lesson_id = r.json()["id"]

    resp = await async_client.post(
        f"/teacher/lessons/{lesson_id}/complete",
        headers=_bearer(teacher_token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "completed"
    assert data["actual_end"] is not None
    assert data["actual_start"] is not None


@pytest.mark.asyncio
async def test_lesson_complete_wrong_status(async_client: AsyncClient, teacher_token: str,
                                             admin_token: str, student_token: str) -> None:
    """400 при попытке завершить уже завершённое занятие."""
    teacher_id = await _get_teacher_id(async_client, admin_token)
    student_id = await _get_my_id(async_client, student_token)
    await _link_student_to_teacher(async_client, admin_token, teacher_id, student_id)

    slot = _next_monday()
    r = await async_client.post(
        "/teacher/lessons",
        json={"title": "X", "lesson_type": "individual",
              "student_id": student_id, "scheduled_date": slot.isoformat(), "duration_minutes": 60},
        headers=_bearer(teacher_token),
    )
    lesson_id = r.json()["id"]

    await async_client.post(f"/teacher/lessons/{lesson_id}/complete", headers=_bearer(teacher_token))
    resp = await async_client.post(f"/teacher/lessons/{lesson_id}/complete", headers=_bearer(teacher_token))
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_lesson_cancel(async_client: AsyncClient, teacher_token: str, admin_token: str,
                              student_token: str) -> None:
    """Отмена занятия."""
    teacher_id = await _get_teacher_id(async_client, admin_token)
    student_id = await _get_my_id(async_client, student_token)
    await _link_student_to_teacher(async_client, admin_token, teacher_id, student_id)

    slot = _next_monday()
    r = await async_client.post(
        "/teacher/lessons",
        json={"title": "Cancel me", "lesson_type": "individual",
              "student_id": student_id, "scheduled_date": slot.isoformat(), "duration_minutes": 60},
        headers=_bearer(teacher_token),
    )
    lesson_id = r.json()["id"]

    resp = await async_client.post(
        f"/teacher/lessons/{lesson_id}/cancel?note=Болен",
        headers=_bearer(teacher_token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "cancelled"
    assert data["teacher_note"] == "Болен"


@pytest.mark.asyncio
async def test_lesson_reschedule(async_client: AsyncClient, teacher_token: str, admin_token: str,
                                  student_token: str) -> None:
    """Перенос занятия — оригинал становится cancelled с пометкой, новое — scheduled."""
    teacher_id = await _get_teacher_id(async_client, admin_token)
    student_id = await _get_my_id(async_client, student_token)
    await _link_student_to_teacher(async_client, admin_token, teacher_id, student_id)

    slot = _next_monday()
    r = await async_client.post(
        "/teacher/lessons",
        json={"title": "Перенос", "lesson_type": "individual",
              "student_id": student_id, "scheduled_date": slot.isoformat(), "duration_minutes": 60},
        headers=_bearer(teacher_token),
    )
    old_id = r.json()["id"]

    new_slot = slot + timedelta(days=2)  # среда
    resp = await async_client.post(
        f"/teacher/lessons/{old_id}/reschedule",
        json={"new_date": new_slot.isoformat(), "reason": "Неудобно"},
        headers=_bearer(teacher_token),
    )
    assert resp.status_code == 200, resp.text
    new_lesson = resp.json()
    assert new_lesson["status"] == "scheduled"
    assert new_lesson["scheduled_date"] == new_slot.isoformat()
    assert "Перенесено с" in new_lesson["teacher_note"]
    assert "Причина: Неудобно" in new_lesson["teacher_note"]

    # Старое занятие — cancelled с пометкой «куда»
    r = await async_client.get(f"/teacher/lessons/{old_id}", headers=_bearer(teacher_token))
    assert r.status_code == 200
    old = r.json()
    assert old["status"] == "cancelled"
    assert "Перенесено на" in old["teacher_note"]


@pytest.mark.asyncio
async def test_lesson_reschedule_conflict(async_client: AsyncClient, teacher_token: str,
                                           admin_token: str, student_token: str) -> None:
    """409 при переносе на конфликтующее время."""
    teacher_id = await _get_teacher_id(async_client, admin_token)
    student_id = await _get_my_id(async_client, student_token)
    await _link_student_to_teacher(async_client, admin_token, teacher_id, student_id)

    mon = _next_monday()
    wed = mon + timedelta(days=2)

    # Занятие на среду (препятствие)
    await async_client.post(
        "/teacher/lessons",
        json={"title": "Препятствие", "lesson_type": "individual",
              "student_id": student_id, "scheduled_date": wed.isoformat(), "duration_minutes": 60},
        headers=_bearer(teacher_token),
    )

    # Занятие на понедельник (пытаемся перенести на среду)
    r = await async_client.post(
        "/teacher/lessons",
        json={"title": "Перенос", "lesson_type": "individual",
              "student_id": student_id, "scheduled_date": mon.isoformat(), "duration_minutes": 60},
        headers=_bearer(teacher_token),
    )
    old_id = r.json()["id"]

    resp = await async_client.post(
        f"/teacher/lessons/{old_id}/reschedule",
        json={"new_date": wed.isoformat()},
        headers=_bearer(teacher_token),
    )
    assert resp.status_code == 409
    assert "Конфликт" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_lesson_get_not_found(async_client: AsyncClient, teacher_token: str) -> None:
    """404 для несуществующего занятия."""
    resp = await async_client.get("/teacher/lessons/99999", headers=_bearer(teacher_token))
    assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════
# 4. Payments
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_payment_create_per_lesson(async_client: AsyncClient, teacher_token: str,
                                          admin_token: str, student_token: str) -> None:
    """Создание поурочной оплаты."""
    teacher_id = await _get_teacher_id(async_client, admin_token)
    student_id = await _get_my_id(async_client, student_token)
    await _link_student_to_teacher(async_client, admin_token, teacher_id, student_id)

    resp = await async_client.post(
        "/teacher/payments",
        json={
            "student_id": student_id,
            "payment_type": "per_lesson",
            "amount": 1500,
            "comment": "За 29.07",
        },
        headers=_bearer(teacher_token),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["payment_type"] == "per_lesson"
    assert data["amount"] == 1500
    assert data["status"] == "paid"  # сразу paid (по умолчанию)
    assert data["paid_at"] is not None


@pytest.mark.asyncio
async def test_payment_create_monthly(async_client: AsyncClient, teacher_token: str,
                                       admin_token: str, student_token: str) -> None:
    """Создание месячного абонемента."""
    teacher_id = await _get_teacher_id(async_client, admin_token)
    student_id = await _get_my_id(async_client, student_token)
    await _link_student_to_teacher(async_client, admin_token, teacher_id, student_id)

    now = datetime.utcnow()
    resp = await async_client.post(
        "/teacher/payments",
        json={
            "student_id": student_id,
            "payment_type": "monthly",
            "amount": 12000,
            "valid_from": now.isoformat(),
            "valid_until": (now + timedelta(days=30)).isoformat(),
            "comment": "Август",
        },
        headers=_bearer(teacher_token),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["payment_type"] == "monthly"
    assert data["amount"] == 12000
    assert data["valid_from"] is not None
    assert data["valid_until"] is not None


@pytest.mark.asyncio
async def test_payment_create_package(async_client: AsyncClient, teacher_token: str,
                                       admin_token: str, student_token: str) -> None:
    """Создание пакета занятий."""
    teacher_id = await _get_teacher_id(async_client, admin_token)
    student_id = await _get_my_id(async_client, student_token)
    await _link_student_to_teacher(async_client, admin_token, teacher_id, student_id)

    resp = await async_client.post(
        "/teacher/payments",
        json={
            "student_id": student_id,
            "payment_type": "package",
            "amount": 10000,
            "package_total": 8,
            "comment": "Пакет 8 занятий",
        },
        headers=_bearer(teacher_token),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["payment_type"] == "package"
    assert data["package_total"] == 8
    assert data["package_used"] == 0  # ещё не использовано


@pytest.mark.asyncio
async def test_payment_list(async_client: AsyncClient, teacher_token: str, admin_token: str,
                             student_token: str) -> None:
    """Список оплат — все и фильтр по студенту."""
    teacher_id = await _get_teacher_id(async_client, admin_token)
    student_id = await _get_my_id(async_client, student_token)
    await _link_student_to_teacher(async_client, admin_token, teacher_id, student_id)

    await async_client.post(
        "/teacher/payments",
        json={"student_id": student_id, "payment_type": "per_lesson", "amount": 1000},
        headers=_bearer(teacher_token),
    )
    await async_client.post(
        "/teacher/payments",
        json={"student_id": student_id, "payment_type": "per_lesson", "amount": 2000},
        headers=_bearer(teacher_token),
    )

    # Все
    resp = await async_client.get("/teacher/payments", headers=_bearer(teacher_token))
    assert resp.status_code == 200
    all_payments = resp.json()
    assert len(all_payments) == 2

    # Фильтр по студенту
    resp = await async_client.get(
        f"/teacher/payments?student_id={student_id}",
        headers=_bearer(teacher_token),
    )
    assert resp.status_code == 200
    assert len(resp.json()) == 2


@pytest.mark.asyncio
async def test_payment_mark_paid_and_cancel(async_client: AsyncClient, teacher_token: str,
                                             admin_token: str, student_token: str) -> None:
    """Отметить как оплачено + отменить."""
    teacher_id = await _get_teacher_id(async_client, admin_token)
    student_id = await _get_my_id(async_client, student_token)
    await _link_student_to_teacher(async_client, admin_token, teacher_id, student_id)

    # Создать — по умолчанию paid, сделаем pending через прямой вызов
    # Для теста обойдём: создадим и проверим что можно отменить
    r = await async_client.post(
        "/teacher/payments",
        json={"student_id": student_id, "payment_type": "per_lesson", "amount": 500},
        headers=_bearer(teacher_token),
    )
    payment_id = r.json()["id"]
    assert r.json()["status"] == "paid"

    # Отменить
    resp = await async_client.post(
        f"/teacher/payments/{payment_id}/cancel",
        headers=_bearer(teacher_token),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"

    # Вернуть в paid
    resp = await async_client.post(
        f"/teacher/payments/{payment_id}/paid",
        headers=_bearer(teacher_token),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "paid"


@pytest.mark.asyncio
async def test_payment_stats(async_client: AsyncClient, teacher_token: str, admin_token: str,
                              student_token: str) -> None:
    """Статистика по оплатам."""
    teacher_id = await _get_teacher_id(async_client, admin_token)
    student_id = await _get_my_id(async_client, student_token)
    await _link_student_to_teacher(async_client, admin_token, teacher_id, student_id)

    await async_client.post(
        "/teacher/payments",
        json={"student_id": student_id, "payment_type": "per_lesson", "amount": 1000},
        headers=_bearer(teacher_token),
    )
    await async_client.post(
        "/teacher/payments",
        json={"student_id": student_id, "payment_type": "package", "amount": 8000, "package_total": 8},
        headers=_bearer(teacher_token),
    )

    resp = await async_client.get("/teacher/payments/stats", headers=_bearer(teacher_token))
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 9000
    assert data["per_lesson"] == 1000
    assert data["package"] == 8000
    assert data["count"] == 2
    assert data["pending_count"] == 0


@pytest.mark.asyncio
async def test_payment_not_found(async_client: AsyncClient, teacher_token: str) -> None:
    """404 для несуществующего платежа."""
    resp = await async_client.post("/teacher/payments/99999/paid", headers=_bearer(teacher_token))
    assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════
# 5. Access control
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_schedule_access_denied_for_student(async_client: AsyncClient, student_token: str) -> None:
    """Студент не может работать с расписанием/занятиями/оплатами."""
    for method, url, body in [
        ("get", "/teacher/schedules", None),
        ("post", "/teacher/schedules", {"title": "X", "schedule_type": "individual",
                                         "student_id": 1, "days_of_week": ["mon"],
                                         "time_start": "10:00", "duration_minutes": 45}),
        ("get", "/teacher/lessons/1", None),
        ("post", "/teacher/lessons", {"title": "X", "lesson_type": "individual",
                                       "student_id": 1,
                                       "scheduled_date": "2026-08-01T10:00:00",
                                       "duration_minutes": 60}),
        ("get", "/teacher/payments", None),
        ("post", "/teacher/payments", {"student_id": 1, "payment_type": "per_lesson", "amount": 100}),
    ]:
        if method == "get":
            resp = await async_client.get(url, headers=_bearer(student_token))
        else:
            resp = await async_client.post(url, json=body, headers=_bearer(student_token))
        assert resp.status_code == 403, f"{method} {url} should be 403, got {resp.status_code}: {resp.text}"
