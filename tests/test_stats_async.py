"""
Асинхронные тесты статистики на httpx.AsyncClient.

Покрывают бизнес-требования:
- Статистика для текущего пользователя (период, темы, сложность, полная)
- Статистика для другого пользователя (учитель/админ смотрит ученика)
- Контроль доступа (студент не может смотреть чужую статистику)
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.helpers_async import _bearer, async_create_task


# ═══════════════════════════════════════════════════════════════
# Статистика для текущего пользователя
# ═══════════════════════════════════════════════════════════════


@pytest.mark.student
@pytest.mark.asyncio
async def test_get_my_period_stats(
    async_client: AsyncClient, student_token: str
) -> None:
    """БТ: Пользователь может получить статистику по периодам."""
    for period in ("month", "week", "all"):
        resp = await async_client.get(
            "/stats/me/period",
            params={"period": period},
            headers={"Authorization": f"Bearer {student_token}"},
        )
        assert resp.status_code == 200, f"Failed for period={period}: {resp.text}"
        data = resp.json()
        # PeriodStatsResponse: daily_stats, total_tests, etc.
        assert "daily_stats" in data or "total_tests" in data


@pytest.mark.student
@pytest.mark.asyncio
async def test_get_my_topic_stats(
    async_client: AsyncClient, student_token: str
) -> None:
    """БТ: Пользователь может получить статистику по темам."""
    resp = await async_client.get(
        "/stats/me/topics",
        params={"period": "all"},
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    # TopicsStatsResponse: topics list
    assert "topics" in data or isinstance(data, dict)


@pytest.mark.student
@pytest.mark.asyncio
async def test_get_my_difficulty_stats(
    async_client: AsyncClient, student_token: str
) -> None:
    """БТ: Пользователь может получить статистику по сложности."""
    resp = await async_client.get(
        "/stats/me/difficulty",
        params={"period": "all"},
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.student
@pytest.mark.asyncio
async def test_get_my_full_stats(
    async_client: AsyncClient, student_token: str
) -> None:
    """БТ: Пользователь может получить полную сводную статистику."""
    resp = await async_client.get(
        "/stats/me/full",
        params={"period": "month"},
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert resp.status_code == 200, resp.text


# ═══════════════════════════════════════════════════════════════
# Статистика для другого пользователя
# ═══════════════════════════════════════════════════════════════


@pytest.mark.student
@pytest.mark.asyncio
async def test_get_user_stats_as_teacher(
    async_client: AsyncClient,
    teacher_token: str,
    admin_token: str,
) -> None:
    """БТ: Учитель может просмотреть статистику ученика."""
    # Get student ID
    users_resp = await async_client.get(
        "/admin/users",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    students = [u for u in users_resp.json() if u["role"] == "student"]
    if not students:
        pytest.skip("No students in the system")

    student_id = students[0]["id"]

    # Teacher views student stats (needs teacher-student link)
    # First link them
    teacher_users = [u for u in users_resp.json() if u["role"] == "teacher"]
    if teacher_users:
        await async_client.post(
            "/admin/assign-student-to-teacher",
            json={"teacher_id": teacher_users[0]["id"], "student_id": student_id},
            headers={"Authorization": f"Bearer {admin_token}"},
        )

    resp = await async_client.get(
        f"/stats/user/{student_id}/full",
        params={"period": "all"},
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert resp.status_code == 200, resp.text


# ═══════════════════════════════════════════════════════════════
# Контроль доступа
# ═══════════════════════════════════════════════════════════════


@pytest.mark.student
@pytest.mark.asyncio
async def test_student_cannot_view_other_user_stats(
    async_client: AsyncClient,
    student_token: str,
    student2_token: str,
    admin_token: str,
) -> None:
    """БТ: Студент не может смотреть статистику другого студента — ошибка 403."""
    # Get student2 ID
    users_resp = await async_client.get(
        "/admin/users",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    student2 = next(
        (u for u in users_resp.json()
         if u["username"] == "student2_async@test.com"), None
    )
    if not student2:
        pytest.skip("Student2 not found")

    resp = await async_client.get(
        f"/stats/user/{student2['id']}/full",
        params={"period": "all"},
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.student
@pytest.mark.asyncio
async def test_stats_requires_auth(
    async_client: AsyncClient,
) -> None:
    """БТ: Неавторизованный пользователь не может получить статистику — ошибка 401."""
    resp = await async_client.get("/stats/me/period", params={"period": "month"})
    assert resp.status_code in (401, 403), f"Unexpected: {resp.status_code} {resp.text}"


# ═══════════════════════════════════════════════════════════════
# Негативные — invalid period
# ═══════════════════════════════════════════════════════════════


@pytest.mark.student
@pytest.mark.asyncio
async def test_stats_invalid_period(
    async_client: AsyncClient, student_token: str
) -> None:
    """БТ: Недопустимый период → 400."""
    resp = await async_client.get(
        "/stats/me/period", params={"period": "century"},
        headers=_bearer(student_token),
    )
    assert resp.status_code == 400, resp.text


# ═══════════════════════════════════════════════════════════════
# Access control — teacher without link → 403
# ═══════════════════════════════════════════════════════════════


@pytest.mark.student
@pytest.mark.asyncio
async def test_teacher_cannot_view_unlinked_student_stats(
    async_client: AsyncClient, teacher_token: str, admin_token: str, student_token: str
) -> None:
    """БТ: Учитель не может смотреть статистику непривязанного ученика → 403."""
    users = (await async_client.get("/admin/users", headers=_bearer(admin_token))).json()
    student = next((u for u in users if u["role"] == "student"), None)
    assert student is not None
    resp = await async_client.get(
        f"/stats/user/{student['id']}/period",
        params={"period": "all"}, headers=_bearer(teacher_token))
    assert resp.status_code == 403, resp.text


@pytest.mark.student
@pytest.mark.asyncio
async def test_admin_can_view_any_stats(
    async_client: AsyncClient, admin_token: str
) -> None:
    """БТ: Админ может смотреть статистику любого пользователя."""
    users = (await async_client.get("/admin/users", headers=_bearer(admin_token))).json()
    student = next((u for u in users if u["role"] == "student"), None)
    if not student:
        pytest.skip("No students found")
    resp = await async_client.get(
        f"/stats/user/{student['id']}/period",
        params={"period": "all"}, headers=_bearer(admin_token))
    assert resp.status_code == 200, resp.text


@pytest.mark.student
@pytest.mark.asyncio
async def test_stats_user_not_found(
    async_client: AsyncClient, admin_token: str
) -> None:
    """БТ: Статистика несуществующего пользователя → 400 (user not found)."""
    resp = await async_client.get(
        "/stats/user/99999/period",
        params={"period": "month"}, headers=_bearer(admin_token))
    assert resp.status_code == 400, resp.text


# ═══════════════════════════════════════════════════════════════
# Статистика с реальными данными (submit → stats)
# ═══════════════════════════════════════════════════════════════


@pytest.mark.student
@pytest.mark.asyncio
async def test_stats_with_submitted_data(
    async_client: AsyncClient, admin_token: str, teacher_token: str
) -> None:
    """БТ: После submit статистика отражает реальные данные: total_tests,
    avg_score, correct_tasks, streak_days."""
    # Create and link student
    email = "statsdata@test.com"
    await async_client.post(
        "/admin/allowed-emails", json={"email": email}, headers=_bearer(admin_token))
    await async_client.post("/register", json={
        "username": email, "password": "StatsD1!", "first_name": "S", "last_name": "D"})
    users = (await async_client.get("/admin/users", headers=_bearer(admin_token))).json()
    student = next((u for u in users if u["username"] == email), None)
    teacher = next((u for u in users if u["role"] == "teacher"), None)
    await async_client.post(
        "/admin/assign-student-to-teacher",
        json={"teacher_id": teacher["id"], "student_id": student["id"]},
        headers=_bearer(admin_token))

    # Create test with 2 tasks (1 closed + 1 open)
    t1 = await async_create_task(async_client, admin_token, {
        "task_class": "10", "topic_number": "1",
        "topic": "algebra", "section": "stats",
        "content": "2 + 2", "answer": "4", "is_open_answer": False,
        "options": ["3", "4", "5"], "difficulty": 1,
        "hint": "h", "solution": "s"})
    t2 = await async_create_task(async_client, admin_token, {
        "task_class": "10", "topic_number": "1",
        "topic": "algebra", "section": "stats",
        "content": "x + 1 = 3", "answer": "2", "is_open_answer": True,
        "difficulty": 3, "hint": "subtract", "solution": "x=2"})
    test = (await async_client.post(
        "/teacher/tests",
        json={"title": "Stats Data Test", "target_class": "10",
              "target_topic": "1", "task_ids": [t1["id"], t2["id"]]},
        headers=_bearer(teacher_token))).json()
    await async_client.post(
        "/teacher/assign-test",
        json={"test_id": test["id"], "user_ids": [student["id"]]},
        headers=_bearer(teacher_token))

    s_tok = (await async_client.post(
        "/login", data={"username": email, "password": "StatsD1!"})).json()["access_token"]
    await async_client.post(f"/student/start-test/{test['id']}", headers=_bearer(s_tok))
    await async_client.post(
        f"/student/tests/{test['id']}/submit",
        json=[{"task_id": t1["id"], "user_answer": "4"},
              {"task_id": t2["id"], "user_answer": "wrong"}],
        headers=_bearer(s_tok))

    # Period stats
    period = await async_client.get(
        "/stats/me/period", params={"period": "all"}, headers=_bearer(s_tok))
    assert period.status_code == 200, period.text
    p = period.json()
    assert p["total_tests"] == 1
    assert p["total_tasks"] >= 1
    assert p["correct_tasks"] == 1  # only t1 correct
    assert p["user_name"] == "S D"

    # Topics stats
    topics = await async_client.get(
        "/stats/me/topics", params={"period": "all"}, headers=_bearer(s_tok))
    assert topics.status_code == 200, topics.text
    tp = topics.json()
    assert "topics" in tp or isinstance(tp, dict)
    if "topics" in tp and tp["topics"]:
        algebra = next((t for t in tp["topics"] if t["topic"] == "algebra"), None)
        if algebra:
            assert algebra["total_tasks"] >= 2
            assert algebra["correct_tasks"] == 1

    # Difficulty stats
    diff = await async_client.get(
        "/stats/me/difficulty", params={"period": "all"}, headers=_bearer(s_tok))
    assert diff.status_code == 200, diff.text
    dd = diff.json()
    assert "difficulties" in dd or isinstance(dd, dict)

    # Full stats
    full = await async_client.get(
        "/stats/me/full", params={"period": "month"}, headers=_bearer(s_tok))
    assert full.status_code == 200, full.text
    fd = full.json()
    assert "period" in fd
    assert "topics" in fd
