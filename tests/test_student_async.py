"""
Асинхронные тесты API студента на httpx.AsyncClient.

Покрывают бизнес-требования:
- Профиль студента (получение, обновление)
- Доступные тесты (список, мета, детали)
- Прохождение тестов (отправка ответов)
- История и результаты
- Назначения (просмотр, старт)
- Теория (темы, разделы, по теме+разделу)
- Контроль доступа (чужие результаты недоступны)
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.helpers_async import _bearer, async_create_task, async_create_theory


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════


async def _setup_student_with_assigned_test(
    ac: AsyncClient, admin_token: str, teacher_token: str, student_token: str
) -> dict:
    """Create a linked student with an assigned test. Returns test dict."""
    # Get student ID
    me_resp = await ac.get(
        "/student/me",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    student_id = me_resp.json()["user"]["id"]

    # Get teacher info
    users_resp = await ac.get(
        "/admin/users",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    users = users_resp.json()
    teacher = next((u for u in users if u["role"] == "teacher"), None)
    assert teacher is not None, "No teacher found"

    # Link student to teacher
    await ac.post(
        "/admin/assign-student-to-teacher",
        json={"teacher_id": teacher["id"], "student_id": student_id},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    # Create task
    task = await async_create_task(ac, admin_token, {
        "task_class": "10", "topic_number": "1",
        "topic": "algebra", "section": "equations",
        "content": "2 + 2 = ?",
        "answer": "4",
        "is_open_answer": False,
        "options": ["3", "4", "5", "6"],
        "difficulty": 1,
        "hint": "Think simple",
        "solution": "2 + 2 = 4",
    })

    # Create test
    test_resp = await ac.post(
        "/teacher/tests",
        json={
            "title": "Student Test",
            "target_class": "10",
            "target_topic": "1",
            "task_ids": [task["id"]],
        },
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    test = test_resp.json()

    # Assign test
    await ac.post(
        "/teacher/assign-test",
        json={"test_id": test["id"], "user_ids": [student_id]},
        headers={"Authorization": f"Bearer {teacher_token}"},
    )

    return test


async def _get_teacher_student_id(
    ac: AsyncClient, admin_token: str, teacher_token: str
) -> tuple[int, int]:
    """Create a student assigned to teacher, return (teacher_id, student_id)."""
    email = "teacher-student-ts@test.com"
    await ac.post(
        "/admin/allowed-emails", json={"email": email},
        headers=_bearer(admin_token),
    )
    await ac.post("/register", json={
        "username": email, "password": "TeachSt1!",
        "first_name": "TStudent", "last_name": "Test",
    })
    users = (await ac.get("/admin/users", headers=_bearer(admin_token))).json()
    student = next((u for u in users if u["username"] == email), None)
    teacher = next((u for u in users if u["role"] == "teacher"), None)
    assert student is not None and teacher is not None
    link = await ac.post(
        "/admin/assign-student-to-teacher",
        json={"teacher_id": teacher["id"], "student_id": student["id"]},
        headers=_bearer(admin_token),
    )
    assert link.status_code == 200
    return teacher["id"], student["id"]


# ═══════════════════════════════════════════════════════════════
# Профиль
# ═══════════════════════════════════════════════════════════════


@pytest.mark.student
@pytest.mark.asyncio
async def test_student_get_profile(async_client: AsyncClient, student_token: str) -> None:
    """БТ: Студент может просмотреть свой профиль со статистикой."""
    resp = await async_client.get(
        "/student/me",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "user" in data
    assert data["user"]["username"] == "student_async@test.com"
    assert data["user"]["role"] == "student"
    # Stats fields are nested under 'stats'
    assert "stats" in data
    assert "total_attempts" in data["stats"]
    assert "avg_score" in data["stats"]


@pytest.mark.student
@pytest.mark.asyncio
async def test_student_update_profile(async_client: AsyncClient, student_token: str) -> None:
    """БТ: Студент может обновить свой профиль."""
    resp = await async_client.put(
        "/student/me",
        json={
            "first_name": "UpdatedName",
            "phone": "+1234567890",
        },
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["first_name"] == "UpdatedName"

    # Verify via GET
    me_resp = await async_client.get(
        "/student/me",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert me_resp.json()["user"]["first_name"] == "UpdatedName"


# ═══════════════════════════════════════════════════════════════
# Доступные тесты
# ═══════════════════════════════════════════════════════════════


@pytest.mark.student
@pytest.mark.asyncio
async def test_student_get_available_tests(
    async_client: AsyncClient, student_token: str
) -> None:
    """БТ: Студент видит список всех публичных тестов."""
    resp = await async_client.get(
        "/student/tests",
    )
    assert resp.status_code == 200, resp.text
    assert isinstance(resp.json(), list)


@pytest.mark.student
@pytest.mark.asyncio
async def test_student_get_tests_meta(
    async_client: AsyncClient,
) -> None:
    """БТ: Студент может получить мета-информацию о тестах."""
    resp = await async_client.get("/student/tests-meta")
    assert resp.status_code == 200, resp.text


# ═══════════════════════════════════════════════════════════════
# История и результаты
# ═══════════════════════════════════════════════════════════════


@pytest.mark.student
@pytest.mark.asyncio
async def test_student_get_history(
    async_client: AsyncClient, student_token: str
) -> None:
    """БТ: Студент может просмотреть свою историю тестов."""
    resp = await async_client.get(
        "/student/history",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert resp.status_code == 200, resp.text
    assert isinstance(resp.json(), list)


# ═══════════════════════════════════════════════════════════════
# Назначения
# ═══════════════════════════════════════════════════════════════


@pytest.mark.student
@pytest.mark.asyncio
async def test_student_get_my_assignments(
    async_client: AsyncClient,
    student_token: str,
    admin_token: str,
    teacher_token: str,
) -> None:
    """БТ: Студент видит назначенные ему тесты."""
    await _setup_student_with_assigned_test(
        async_client, admin_token, teacher_token, student_token
    )

    resp = await async_client.get(
        "/student/my-assignments",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    assert "test" in data[0] or "test_id" in data[0]


@pytest.mark.student
@pytest.mark.asyncio
async def test_student_get_my_assignments_meta(
    async_client: AsyncClient,
    student_token: str,
    admin_token: str,
    teacher_token: str,
) -> None:
    """БТ: Студент видит мета-информацию о назначенных тестах."""
    await _setup_student_with_assigned_test(
        async_client, admin_token, teacher_token, student_token
    )

    resp = await async_client.get(
        "/student/my-assignments-meta",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.student
@pytest.mark.asyncio
async def test_student_start_assigned_test(
    async_client: AsyncClient,
    student_token: str,
    admin_token: str,
    teacher_token: str,
) -> None:
    """БТ: Студент может начать назначенный тест."""
    test = await _setup_student_with_assigned_test(
        async_client, admin_token, teacher_token, student_token
    )

    resp = await async_client.post(
        f"/student/start-test/{test['id']}",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert resp.status_code == 200, resp.text


# ═══════════════════════════════════════════════════════════════
# Теория
# ═══════════════════════════════════════════════════════════════


@pytest.mark.student
@pytest.mark.asyncio
async def test_student_get_theory_topics(
    async_client: AsyncClient, student_token: str
) -> None:
    """БТ: Студент видит список всех тем теории."""
    resp = await async_client.get(
        "/student/theory/topics",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.student
@pytest.mark.asyncio
async def test_student_get_theory_sections(
    async_client: AsyncClient, student_token: str, admin_token: str
) -> None:
    """БТ: Студент видит разделы по теме."""
    # Create theory first
    from tests.helpers_async import async_create_theory
    await async_create_theory(async_client, admin_token, {
        "topic": "algebra",
        "section": "equations",
        "content": "An equation is a statement that asserts equality.",
    })

    resp = await async_client.get(
        "/student/theory/sections/algebra",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.student
@pytest.mark.asyncio
async def test_student_get_theory_by_topic(
    async_client: AsyncClient, student_token: str, admin_token: str
) -> None:
    """БТ: Студент может получить теорию по теме."""
    from tests.helpers_async import async_create_theory
    await async_create_theory(async_client, admin_token, {
        "topic": "algebra",
        "section": "equations",
        "content": "Linear equations are of the form ax + b = 0.",
    })

    resp = await async_client.get(
        "/student/theory/by-topic/algebra",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.student
@pytest.mark.asyncio
async def test_student_get_theory_by_topic_section(
    async_client: AsyncClient, student_token: str, admin_token: str
) -> None:
    """БТ: Студент может получить теорию по теме и разделу."""
    from tests.helpers_async import async_create_theory
    await async_create_theory(async_client, admin_token, {
        "topic": "algebra",
        "section": "quadratic",
        "content": "ax² + bx + c = 0, a ≠ 0.",
    })

    resp = await async_client.get(
        "/student/theory/by-topic/algebra/section/quadratic",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert resp.status_code == 200, resp.text


# ═══════════════════════════════════════════════════════════════
# AI-тесты (мета, без реального AI)
# ═══════════════════════════════════════════════════════════════


@pytest.mark.student
@pytest.mark.asyncio
async def test_student_get_ai_tests(
    async_client: AsyncClient, student_token: str
) -> None:
    """БТ: Студент может получить список AI-тестов."""
    resp = await async_client.get(
        "/student/ai-tests",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert resp.status_code == 200, resp.text
    assert isinstance(resp.json(), list)


# ═══════════════════════════════════════════════════════════════
# Контроль доступа
# ═══════════════════════════════════════════════════════════════


@pytest.mark.student
@pytest.mark.asyncio
async def test_student_profile_requires_auth(
    async_client: AsyncClient,
) -> None:
    """БТ: Неавторизованный пользователь не может получить профиль — ошибка 401."""
    resp = await async_client.get("/student/me")
    assert resp.status_code in (401, 403), f"Unexpected: {resp.status_code} {resp.text}"


# ═══════════════════════════════════════════════════════════════
# submit_test — полный цикл + детальный результат
# ═══════════════════════════════════════════════════════════════


@pytest.mark.student
@pytest.mark.asyncio
async def test_student_submit_test_full_cycle(
    async_client: AsyncClient, admin_token: str, teacher_token: str, student_token: str
) -> None:
    """БТ: Полный цикл: создать тест → назначить → старт → submit →
    проверить history и detailed result со всеми полями."""
    test = await _setup_student_with_assigned_test(
        async_client, admin_token, teacher_token, student_token)

    # Start
    start = await async_client.post(
        f"/student/start-test/{test['id']}", headers=_bearer(student_token))
    assert start.status_code == 200

    tasks = start.json()["tasks"]
    task_id = tasks[0]["id"]

    # Submit correct answer
    submit = await async_client.post(
        f"/student/tests/{test['id']}/submit",
        json=[{"task_id": task_id, "user_answer": "4"}],
        headers=_bearer(student_token),
    )
    assert submit.status_code == 200, submit.text
    assert submit.json()["status"] == "success"

    # History
    hist = await async_client.get("/student/history", headers=_bearer(student_token))
    assert hist.status_code == 200
    items = hist.json()
    assert len(items) >= 1
    assert items[0]["test_title"] == "Student Test"

    # Detailed result
    result_id = items[0]["id"]
    detail = await async_client.get(
        f"/student/results/{result_id}", headers=_bearer(student_token))
    assert detail.status_code == 200, detail.text
    d = detail.json()
    assert d["test_title"] == "Student Test"
    assert "total_points" in d
    assert "max_points" in d
    assert "difficulty_stats" in d
    assert len(d["details"]) == 1
    assert d["details"][0]["task_id"] == task_id
    assert d["details"][0]["is_correct"] is True


# ═══════════════════════════════════════════════════════════════
# submit_test — негативные кейсы
# ═══════════════════════════════════════════════════════════════


@pytest.mark.student
@pytest.mark.asyncio
async def test_student_submit_test_not_found(
    async_client: AsyncClient, student_token: str
) -> None:
    """БТ: Submit несуществующего теста → 404."""
    resp = await async_client.post(
        "/student/tests/99999/submit",
        json=[{"task_id": 1, "user_answer": "x"}],
        headers=_bearer(student_token),
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.student
@pytest.mark.asyncio
async def test_student_get_test_for_passing_not_found(
    async_client: AsyncClient, student_token: str
) -> None:
    """БТ: Получение несуществующего теста → 404."""
    resp = await async_client.get("/student/tests/99999", headers=_bearer(student_token))
    assert resp.status_code == 404, resp.text


@pytest.mark.student
@pytest.mark.asyncio
async def test_student_get_detailed_result_not_found(
    async_client: AsyncClient, student_token: str
) -> None:
    """БТ: Несуществующий результат → 404."""
    resp = await async_client.get(
        "/student/results/99999", headers=_bearer(student_token))
    assert resp.status_code == 404, resp.text


# ═══════════════════════════════════════════════════════════════
# start_assigned_test — негативные кейсы
# ═══════════════════════════════════════════════════════════════


@pytest.mark.student
@pytest.mark.asyncio
async def test_student_start_test_not_assigned(
    async_client: AsyncClient, student_token: str, admin_token: str
) -> None:
    """БТ: Старт неназначенного теста → 403."""
    task = await async_create_task(async_client, admin_token, {
        "task_class": "10", "topic_number": "1",
        "content": "q", "answer": "a", "is_open_answer": True,
        "difficulty": 1, "hint": "h", "solution": "s"})
    test = (await async_client.post(
        "/teacher/tests",
        json={"title": "PublicT", "target_class": "10", "target_topic": "1",
              "task_ids": [task["id"]]},
        headers=_bearer(admin_token))).json()
    resp = await async_client.post(
        f"/student/start-test/{test['id']}", headers=_bearer(student_token))
    assert resp.status_code == 403, resp.text


# ═══════════════════════════════════════════════════════════════
# Теория — негативные кейсы
# ═══════════════════════════════════════════════════════════════


@pytest.mark.student
@pytest.mark.asyncio
async def test_student_theory_by_topic_not_found(
    async_client: AsyncClient, student_token: str
) -> None:
    """БТ: Теория по несуществующей теме → 404."""
    resp = await async_client.get(
        "/student/theory/by-topic/nonexistent_xyz",
        headers=_bearer(student_token),
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.student
@pytest.mark.asyncio
async def test_student_theory_sections_not_found(
    async_client: AsyncClient, student_token: str
) -> None:
    """БТ: Разделы по несуществующей теме → 404."""
    resp = await async_client.get(
        "/student/theory/sections/nonexistent_xyz",
        headers=_bearer(student_token),
    )
    assert resp.status_code == 404, resp.text


# ═══════════════════════════════════════════════════════════════
# AI hint + solution — not found
# ═══════════════════════════════════════════════════════════════


@pytest.mark.student
@pytest.mark.asyncio
async def test_student_ai_hint_task_not_found(
    async_client: AsyncClient, student_token: str
) -> None:
    """БТ: AI-подсказка для несуществующего задания → 404."""
    resp = await async_client.post(
        "/student/tasks/99999/hint", headers=_bearer(student_token))
    assert resp.status_code == 404, resp.text


@pytest.mark.student
@pytest.mark.asyncio
async def test_student_ai_solution_task_not_found(
    async_client: AsyncClient, student_token: str
) -> None:
    """БТ: AI-решение для несуществующего задания → 404."""
    resp = await async_client.post(
        "/student/tasks/99999/ai-solve", headers=_bearer(student_token))
    assert resp.status_code == 404, resp.text


# ═══════════════════════════════════════════════════════════════
# AI hint + solution — success (mock AI)
# ═══════════════════════════════════════════════════════════════


@pytest.mark.student
@pytest.mark.asyncio
async def test_student_ai_hint_success(
    async_client: AsyncClient, student_token: str, admin_token: str
) -> None:
    """БТ: AI-подсказка успешно возвращается с context полями."""
    task = await async_create_task(async_client, admin_token, {
        "task_class": "10", "topic_number": "1",
        "topic": "algebra", "section": "equations",
        "content": "2x + 5 = 9, find x",
        "answer": "2", "is_open_answer": False,
        "options": ["1", "2", "3", "4"],
        "difficulty": 2, "hint": "Subtract 5", "solution": "2x=4, x=2",
    })
    # Mock AI
    from unittest.mock import AsyncMock, patch
    with patch("services.ai_service.AIService.get_hint",
               new_callable=AsyncMock) as mock_hint:
        mock_hint.return_value = "Попробуй перенести 5 в правую часть"
        resp = await async_client.post(
            f"/student/tasks/{task['id']}/hint",
            headers=_bearer(student_token))
        assert resp.status_code == 200, resp.text
        d = resp.json()
        assert d["task_id"] == task["id"]
        assert d["hint"] == "Попробуй перенести 5 в правую часть"
        assert "context" in d
        assert d["context"]["task_class"] == "10"


@pytest.mark.student
@pytest.mark.asyncio
async def test_student_ai_solution_success(
    async_client: AsyncClient, student_token: str, admin_token: str
) -> None:
    """БТ: AI-решение успешно возвращается с verified полем."""
    task = await async_create_task(async_client, admin_token, {
        "task_class": "10", "topic_number": "1",
        "topic": "algebra", "section": "equations",
        "content": "2x + 5 = 9, find x",
        "answer": "2", "is_open_answer": False,
        "options": ["1", "2", "3", "4"],
        "difficulty": 2, "hint": "Subtract 5", "solution": "2x=4, x=2",
    })
    from unittest.mock import AsyncMock, patch
    with patch("services.ai_service.AIService.get_solution",
               new_callable=AsyncMock) as mock_sol:
        mock_sol.return_value = "Решение:\n2x + 5 = 9\n2x = 4\nx = 2\n=== ОТВЕТ ===\n2"
        resp = await async_client.post(
            f"/student/tasks/{task['id']}/ai-solve",
            headers=_bearer(student_token))
        assert resp.status_code == 200, resp.text
        d = resp.json()
        assert d["task_id"] == task["id"]
        assert d["success"] is True
        assert d["verified"] is True
        assert d["ai_answer"] == "2"
        assert "context" in d


# ═══════════════════════════════════════════════════════════════
# generate_ai_test — mock AI + edge cases
# ═══════════════════════════════════════════════════════════════


@pytest.mark.student
@pytest.mark.asyncio
async def test_student_generate_ai_test(
    async_client: AsyncClient, student_token: str, admin_token: str
) -> None:
    """БТ: Генерация AI-теста — тест создаётся с AI флагами."""
    # Pre-create some tasks so AI has something to pick from
    await async_create_task(async_client, admin_token, {
        "task_class": "10", "topic_number": "1",
        "topic": "algebra", "section": "equations",
        "content": "x + 1 = 3", "answer": "2", "is_open_answer": True,
        "difficulty": 1, "hint": "h", "solution": "x=2"})
    await async_create_task(async_client, admin_token, {
        "task_class": "10", "topic_number": "1",
        "topic": "algebra", "section": "expressions",
        "content": "2 + 3", "answer": "5", "is_open_answer": False,
        "options": ["4", "5", "6"], "difficulty": 1,
        "hint": "h", "solution": "5"})

    from unittest.mock import AsyncMock, patch
    with patch("services.ai_service.AIService.classify_topics",
               new_callable=AsyncMock) as mock_classify, \
         patch("services.ai_service.AIService.select_tasks",
               new_callable=AsyncMock) as mock_select:
        mock_classify.return_value = [{"name": "algebra", "sections": ["equations"]}]
        mock_select.return_value = []  # let it fallback

        resp = await async_client.post(
            "/student/generate-test",
            json={"prompt": "реши уравнения", "task_count": 3, "difficulty": "easy"},
            headers=_bearer(student_token),
        )
        assert resp.status_code == 200, resp.text
        d = resp.json()
        assert d["is_ai_generated"] is True
        assert "AI" in d["title"]
        assert d["is_active"] is True


@pytest.mark.student
@pytest.mark.asyncio
async def test_student_generate_ai_test_no_tasks(
    async_client: AsyncClient, student_token: str
) -> None:
    """БТ: Генерация AI-теста без доступных заданий — создаётся тест (возможно пустой)."""
    # No tasks exist in DB for this new student scope
    from unittest.mock import AsyncMock, patch
    with patch("services.ai_service.AIService.classify_topics",
               new_callable=AsyncMock) as mock_classify:
        mock_classify.return_value = []  # AI returns nothing, fallback to random
        resp = await async_client.post(
            "/student/generate-test",
            json={"prompt": "что-то редкое", "task_count": 1},
            headers=_bearer(student_token),
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["is_ai_generated"] is True


# ═══════════════════════════════════════════════════════════════
# Полноценные пользовательские сценарии (end-to-end)
# ═══════════════════════════════════════════════════════════════


@pytest.mark.student
@pytest.mark.asyncio
async def test_student_full_journey(
    async_client: AsyncClient, admin_token: str, teacher_token: str
) -> None:
    """БТ: Полный путь студента: регистрация → теория → тест → результат → статистика."""
    # 1. Register
    email = "journey@test.com"
    await async_client.post(
        "/admin/allowed-emails", json={"email": email},
        headers=_bearer(admin_token))
    await async_client.post("/register", json={
        "username": email, "password": "Journey1!",
        "first_name": "Journey", "last_name": "Student"})
    s_login = (await async_client.post(
        "/login", data={"username": email, "password": "Journey1!"})).json()
    s_tok = s_login["access_token"]

    # 2. Get profile
    me = await async_client.get("/student/me", headers=_bearer(s_tok))
    assert me.status_code == 200
    student_id = me.json()["user"]["id"]

    # 3. Theory topics
    topics = await async_client.get("/student/theory/topics", headers=_bearer(s_tok))
    assert topics.status_code == 200

    # 4. Create theory + read it
    await async_create_theory(async_client, admin_token, {
        "topic": "algebra", "section": "journey",
        "content": "Quadratic formula: x = (-b ± √(b²-4ac)) / 2a"})
    theory = await async_client.get(
        "/student/theory/by-topic/algebra", headers=_bearer(s_tok))
    assert theory.status_code == 200

    # 5. Link to teacher
    users = (await async_client.get("/admin/users", headers=_bearer(admin_token))).json()
    teacher = next((u for u in users if u["role"] == "teacher"), None)
    await async_client.post(
        "/admin/assign-student-to-teacher",
        json={"teacher_id": teacher["id"], "student_id": student_id},
        headers=_bearer(admin_token))

    # 6. Teacher creates test and assigns
    task = await async_create_task(async_client, admin_token, {
        "task_class": "10", "topic_number": "1",
        "topic": "algebra", "section": "journey",
        "content": "x² = 4", "answer": "2", "is_open_answer": True,
        "difficulty": 2, "hint": "square root",
        "solution": "x = ±2"})
    test = (await async_client.post(
        "/teacher/tests",
        json={"title": "Journey Test", "target_class": "10", "target_topic": "1",
              "task_ids": [task["id"]]},
        headers=_bearer(teacher_token))).json()
    await async_client.post(
        "/teacher/assign-test",
        json={"test_id": test["id"], "user_ids": [student_id]},
        headers=_bearer(teacher_token))

    # 7. Student takes test
    await async_client.post(f"/student/start-test/{test['id']}", headers=_bearer(s_tok))
    await async_client.post(
        f"/student/tests/{test['id']}/submit",
        json=[{"task_id": task["id"], "user_answer": "2"}],
        headers=_bearer(s_tok))

    # 8. History + detailed result
    hist = (await async_client.get("/student/history", headers=_bearer(s_tok))).json()
    assert len(hist) >= 1
    result_id = hist[0]["id"]
    detail = await async_client.get(
        f"/student/results/{result_id}", headers=_bearer(s_tok))
    assert detail.status_code == 200

    # 9. Stats
    period = await async_client.get(
        "/stats/me/period", params={"period": "all"}, headers=_bearer(s_tok))
    assert period.status_code == 200
    assert period.json()["total_tests"] >= 1

    # 10. Assignments
    assignments = await async_client.get(
        "/student/my-assignments", headers=_bearer(s_tok))
    assert assignments.status_code == 200


@pytest.mark.teacher
@pytest.mark.asyncio
async def test_teacher_full_journey(
    async_client: AsyncClient, admin_token: str, teacher_token: str
) -> None:
    """БТ: Полный путь учителя: задания → тест → группа → назначение → результаты."""
    # 1. Create tasks
    t1 = await async_create_task(async_client, admin_token, {
        "task_class": "10", "topic_number": "1",
        "topic": "algebra", "section": "linear",
        "content": "2x = 4", "answer": "2", "is_open_answer": True,
        "difficulty": 1, "hint": "divide", "solution": "x=2"})
    t2 = await async_create_task(async_client, admin_token, {
        "task_class": "10", "topic_number": "1",
        "topic": "algebra", "section": "linear",
        "content": "3x = 6", "answer": "2", "is_open_answer": True,
        "difficulty": 1, "hint": "divide", "solution": "x=2"})

    # 2. Create test from tasks
    test = (await async_client.post(
        "/teacher/tests",
        json={"title": "Teacher Journey", "target_class": "10",
              "target_topic": "1", "task_ids": [t1["id"], t2["id"]]},
        headers=_bearer(teacher_token))).json()

    # 3. Get a linked student
    teacher_id, student_id = await _get_teacher_student_id(
        async_client, admin_token, teacher_token)

    # 4. Create group and add student
    grp = (await async_client.post(
        "/teacher/groups/", json={"name": "Journey Group"},
        headers=_bearer(teacher_token))).json()
    await async_client.post(
        f"/teacher/groups/{grp['id']}/students",
        json={"student_ids": [student_id]}, headers=_bearer(teacher_token))

    # 5. Assign test to group
    assign_grp = await async_client.post(
        "/teacher/assign-test-to-group",
        json={"group_id": grp["id"], "test_id": test["id"]},
        headers=_bearer(teacher_token))
    assert assign_grp.status_code == 200, assign_grp.text

    # 6. Individual assignment
    assign_ind = await async_client.post(
        "/teacher/assign-test",
        json={"test_id": test["id"], "user_ids": [student_id]},
        headers=_bearer(teacher_token))
    assert assign_ind.status_code == 200

    # 7. Student submits (via student token — use helper student)
    student_email = "teacher-student-ts@test.com"
    s_login = (await async_client.post(
        "/login", data={"username": student_email, "password": "TeachSt1!"})).json()
    s_tok = s_login["access_token"]
    await async_client.post(f"/student/start-test/{test['id']}", headers=_bearer(s_tok))
    await async_client.post(
        f"/student/tests/{test['id']}/submit",
        json=[{"task_id": t1["id"], "user_answer": "2"},
              {"task_id": t2["id"], "user_answer": "2"}],
        headers=_bearer(s_tok))

    # 8. Teacher views results
    hist = (await async_client.get("/student/history", headers=_bearer(s_tok))).json()
    result = await async_client.get(
        f"/teacher/results/{hist[0]['id']}", headers=_bearer(teacher_token))
    assert result.status_code == 200
    d = result.json()
    assert d["test_title"] == "Teacher Journey"
    assert d["total_points"] == 4  # 2 open = 2+2
    assert d["details"][0]["is_correct"] is True

    # 9. Teacher views student profile
    profile = await async_client.get(
        f"/teacher/students-profile/{student_id}", headers=_bearer(teacher_token))
    assert profile.status_code == 200

    # 10. Teacher views student assignments
    assigns = await async_client.get(
        f"/teacher/student/{student_id}/assignments", headers=_bearer(teacher_token))
    assert assigns.status_code == 200


@pytest.mark.admin
@pytest.mark.asyncio
async def test_admin_full_journey(
    async_client: AsyncClient, admin_token: str, teacher_token: str
) -> None:
    """БТ: Полный путь админа: пользователи → задания → теория → пересборка → детальный результат."""
    # 1. Create a student
    email = "admin-journey@test.com"
    await async_client.post(
        "/admin/allowed-emails", json={"email": email},
        headers=_bearer(admin_token))
    await async_client.post("/register", json={
        "username": email, "password": "AdminJ1!", "first_name": "A", "last_name": "J"})

    users = (await async_client.get("/admin/users", headers=_bearer(admin_token))).json()
    student = next((u for u in users if u["username"] == email), None)
    teacher = next((u for u in users if u["role"] == "teacher"), None)

    # 2. Link student to teacher
    await async_client.post(
        "/admin/assign-student-to-teacher",
        json={"teacher_id": teacher["id"], "student_id": student["id"]},
        headers=_bearer(admin_token))

    # 3. Create tasks
    t1 = await async_create_task(async_client, admin_token, {
        "task_class": "10", "topic_number": "1",
        "topic": "algebra", "section": "journey",
        "content": "ax = b", "answer": "b/a", "is_open_answer": True,
        "difficulty": 3, "hint": "divide", "solution": "x=b/a"})
    t2 = await async_create_task(async_client, admin_token, {
        "task_class": "10", "topic_number": "1",
        "topic": "algebra", "section": "journey",
        "content": "y/2 = 5", "answer": "10", "is_open_answer": True,
        "difficulty": 3, "hint": "multiply", "solution": "y=10"})

    # 4. Rebuild autocompile tests
    rebuild = await async_client.post(
        "/admin/rebuild-all-static-tests",
        headers=_bearer(admin_token))
    assert rebuild.status_code == 200, rebuild.text

    # 5. Teacher creates test from tasks and assigns
    test = (await async_client.post(
        "/teacher/tests",
        json={"title": "Admin Journey", "target_class": "10",
              "target_topic": "1", "task_ids": [t1["id"], t2["id"]]},
        headers=_bearer(teacher_token))).json()
    await async_client.post(
        "/teacher/assign-test",
        json={"test_id": test["id"], "user_ids": [student["id"]]},
        headers=_bearer(teacher_token))

    # 6. Student takes test
    s_tok = (await async_client.post(
        "/login", data={"username": email, "password": "AdminJ1!"})).json()["access_token"]
    await async_client.post(f"/student/start-test/{test['id']}", headers=_bearer(s_tok))
    await async_client.post(
        f"/student/tests/{test['id']}/submit",
        json=[{"task_id": t1["id"], "user_answer": "b/a"},
              {"task_id": t2["id"], "user_answer": "10"}],
        headers=_bearer(s_tok))
    hist = (await async_client.get("/student/history", headers=_bearer(s_tok))).json()

    # 7. Admin views detailed result
    detail = await async_client.get(
        f"/admin/results/{hist[0]['id']}", headers=_bearer(admin_token))
    assert detail.status_code == 200, detail.text
    d = detail.json()
    assert d["test_title"] == "Admin Journey"
    assert d["total_points"] == 4  # 2 open = 2+2
    assert len(d["details"]) == 2
    assert d["difficulty_stats"]["3"]["total"] == 2
    assert d["difficulty_stats"]["3"]["correct"] == 2

    # 8. Admin views user profile + history
    profile = await async_client.get(
        f"/admin/users/{student['id']}/profile", headers=_bearer(admin_token))
    assert profile.status_code == 200
    user_hist = await async_client.get(
        f"/admin/users/{student['id']}/history", headers=_bearer(admin_token))
    assert user_hist.status_code == 200

    # 9. Update task answer → verify cascade
    update = await async_client.put(
        f"/admin/tasks/{t1['id']}",
        json={"task_class": "10", "topic_number": "1",
              "topic": "algebra", "section": "journey",
              "content": "ax = b", "answer": "wrong",
              "is_open_answer": True, "difficulty": 3,
              "hint": "divide", "solution": "x=b/a"},
        headers=_bearer(admin_token))
    assert update.status_code == 200, update.text

    detail2 = await async_client.get(
        f"/admin/results/{hist[0]['id']}", headers=_bearer(admin_token))
    assert detail2.json()["details"][0]["is_correct"] is False
    assert detail2.json()["total_points"] == 2  # only t2 correct now
