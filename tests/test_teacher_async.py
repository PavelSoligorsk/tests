"""
Асинхронные тесты API учителя на httpx.AsyncClient.

Покрывают бизнес-требования:
- Банк заданий (фильтрация, группировка, мета-информация)
- Конструктор тестов (CRUD тестов, просмотр заданий теста)
- Управление учениками (список, профиль, история, результаты)
- Назначение тестов (индивидуальное, групповое, просмотр назначений)
- Управление группами (CRUD, добавление студентов)
- Контроль доступа (студент не может выполнять учительские действия)
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.helpers_async import _bearer, async_create_task


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════


async def _get_teacher_student_id(
    ac: AsyncClient, admin_token: str, teacher_token: str
) -> tuple[int, int]:
    """Create a student assigned to teacher, return (teacher_id, student_id)."""
    email = "teacher-student@test.com"
    await ac.post(
        "/admin/allowed-emails", json={"email": email},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    await ac.post("/register", json={
        "username": email, "password": "TeachSt1!",
        "first_name": "TStudent", "last_name": "Test",
    })

    users_resp = await ac.get(
        "/admin/users",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    users = users_resp.json()
    student = next((u for u in users if u["username"] == email), None)
    teacher = next((u for u in users if u["role"] == "teacher"), None)
    assert student is not None and teacher is not None

    # Link
    link_resp = await ac.post(
        "/admin/assign-student-to-teacher",
        json={"teacher_id": teacher["id"], "student_id": student["id"]},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert link_resp.status_code == 200
    return teacher["id"], student["id"]


# ═══════════════════════════════════════════════════════════════
# Банк заданий
# ═══════════════════════════════════════════════════════════════


@pytest.mark.teacher
@pytest.mark.asyncio
async def test_teacher_get_all_tasks(
    async_client: AsyncClient, teacher_token: str, admin_token: str
) -> None:
    """БТ: Учитель видит все задания в банке."""
    # Ensure at least one task exists
    await async_create_task(async_client, admin_token, {
        "task_class": "10", "topic_number": "1",
        "topic": "algebra", "section": "equations",
        "content": "2x + 5 = 9, find x",
        "answer": "2",
        "is_open_answer": False,
        "options": ["1", "2", "3", "4"],
        "difficulty": 1,
        "hint": "Subtract 5",
        "solution": "2x = 4, x = 2",
    })

    resp = await async_client.get(
        "/teacher/tasks",
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert resp.status_code == 200, resp.text
    tasks = resp.json()
    assert isinstance(tasks, list)
    assert len(tasks) >= 1
    for task in tasks:
        assert "id" in task
        assert "task_class" in task


@pytest.mark.teacher
@pytest.mark.asyncio
async def test_teacher_filter_tasks_by_class(
    async_client: AsyncClient, teacher_token: str, admin_token: str
) -> None:
    """БТ: Учитель может фильтровать задания по классу."""
    # Create tasks in different classes
    await async_create_task(async_client, admin_token, {
        "task_class": "7", "topic_number": "1",
        "content": "Class 7 task", "answer": "7",
        "is_open_answer": True, "difficulty": 1,
        "hint": "hint", "solution": "solution",
    })
    await async_create_task(async_client, admin_token, {
        "task_class": "11", "topic_number": "1",
        "content": "Class 11 task", "answer": "11",
        "is_open_answer": True, "difficulty": 1,
        "hint": "hint", "solution": "solution",
    })

    resp = await async_client.get(
        "/teacher/tasks", params={"task_class": 7},
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert resp.status_code == 200, resp.text
    tasks = resp.json()
    # All returned tasks should have task_class == "7"
    assert all(t["task_class"] == "7" for t in tasks)
    assert len(tasks) >= 1


@pytest.mark.teacher
@pytest.mark.asyncio
async def test_teacher_tasks_grouped(
    async_client: AsyncClient, teacher_token: str, admin_token: str
) -> None:
    """БТ: Учитель может получить задания, сгруппированные по классам и темам."""
    await async_create_task(async_client, admin_token, {
        "task_class": "10", "topic_number": "5",
        "topic": "algebra", "section": "quadratic",
        "content": "Solve x² - 4 = 0",
        "answer": "x = ±2",
        "is_open_answer": True, "difficulty": 2,
        "hint": "Factor", "solution": "(x-2)(x+2)=0",
    })

    resp = await async_client.get(
        "/teacher/tasks-grouped",
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert resp.status_code == 200, resp.text
    # The response should be a structured grouping
    data = resp.json()
    assert data is not None


@pytest.mark.teacher
@pytest.mark.asyncio
async def test_teacher_tasks_meta(
    async_client: AsyncClient, teacher_token: str, admin_token: str
) -> None:
    """БТ: Учитель может получить мета-структуру заданий (без содержимого)."""
    await async_create_task(async_client, admin_token, {
        "task_class": "9", "topic_number": "3",
        "topic": "geometry", "section": "triangles",
        "content": "Pythagorean theorem", "answer": "a²+b²=c²",
        "is_open_answer": True, "difficulty": 1,
        "hint": "hint", "solution": "solution",
    })

    resp = await async_client.get(
        "/teacher/tasks-meta",
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.teacher
@pytest.mark.asyncio
async def test_teacher_get_single_task(
    async_client: AsyncClient, teacher_token: str, admin_token: str
) -> None:
    """БТ: Учитель может получить одно задание по ID."""
    task = await async_create_task(async_client, admin_token, {
        "task_class": "10", "topic_number": "2",
        "topic": "algebra", "section": "expressions",
        "content": "Simplify: a³ / a",
        "answer": "a²",
        "is_open_answer": True, "difficulty": 1,
        "hint": "Subtract exponents", "solution": "a^(3-1) = a²",
    })

    resp = await async_client.get(
        f"/teacher/tasks/{task['id']}",
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == task["id"]


# ═══════════════════════════════════════════════════════════════
# Конструктор тестов
# ═══════════════════════════════════════════════════════════════


@pytest.mark.teacher
@pytest.mark.asyncio
async def test_teacher_create_test(
    async_client: AsyncClient, teacher_token: str, admin_token: str
) -> None:
    """БТ: Учитель может создать тест из заданий."""
    task = await async_create_task(async_client, admin_token, {
        "task_class": "10", "topic_number": "1",
        "topic": "algebra", "section": "equations",
        "content": "3x = 12, find x",
        "answer": "4",
        "is_open_answer": False,
        "options": ["2", "3", "4", "5"],
        "difficulty": 1,
        "hint": "Divide by 3",
        "solution": "x = 4",
    })

    resp = await async_client.post(
        "/teacher/tests",
        json={
            "title": "My First Test",
            "target_class": "10",
            "target_topic": "1",
            "is_autocompile": False,
            "task_ids": [task["id"]],
        },
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["title"] == "My First Test"
    assert data["target_class"] == "10"


@pytest.mark.teacher
@pytest.mark.asyncio
async def test_teacher_get_my_tests(
    async_client: AsyncClient, teacher_token: str, admin_token: str
) -> None:
    """БТ: Учитель видит список своих тестов."""
    task = await async_create_task(async_client, admin_token, {
        "task_class": "10", "topic_number": "1",
        "content": "Test content", "answer": "X",
        "is_open_answer": True, "difficulty": 1,
        "hint": "hint", "solution": "solution",
    })
    await async_client.post(
        "/teacher/tests",
        json={
            "title": "Test List Test",
            "target_class": "10",
            "target_topic": "1",
            "is_autocompile": False,
            "task_ids": [task["id"]],
        },
        headers={"Authorization": f"Bearer {teacher_token}"},
    )

    resp = await async_client.get(
        "/teacher/tests",
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert resp.status_code == 200, resp.text
    tests = resp.json()
    assert isinstance(tests, list)
    assert len(tests) >= 1
    assert all("id" in t and "title" in t for t in tests)


@pytest.mark.teacher
@pytest.mark.asyncio
async def test_teacher_update_test(
    async_client: AsyncClient, teacher_token: str, admin_token: str
) -> None:
    """БТ: Учитель может обновить свой тест."""
    task = await async_create_task(async_client, admin_token, {
        "task_class": "10", "topic_number": "1",
        "content": "Update test task", "answer": "A",
        "is_open_answer": True, "difficulty": 1,
        "hint": "hint", "solution": "solution",
    })
    create_resp = await async_client.post(
        "/teacher/tests",
        json={
            "title": "Old Title",
            "target_class": "10",
            "target_topic": "1",
            "task_ids": [task["id"]],
        },
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    test_id = create_resp.json()["id"]

    resp = await async_client.put(
        f"/teacher/tests/{test_id}",
        json={
            "title": "Updated Title",
            "target_class": "10",
            "target_topic": "1",
            "is_autocompile": False,
            "task_ids": [task["id"]],
        },
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["title"] == "Updated Title"


@pytest.mark.teacher
@pytest.mark.asyncio
async def test_teacher_delete_test(
    async_client: AsyncClient, teacher_token: str, admin_token: str
) -> None:
    """БТ: Учитель может удалить свой тест."""
    task = await async_create_task(async_client, admin_token, {
        "task_class": "10", "topic_number": "1",
        "content": "Delete test task", "answer": "B",
        "is_open_answer": True, "difficulty": 1,
        "hint": "hint", "solution": "solution",
    })
    create_resp = await async_client.post(
        "/teacher/tests",
        json={
            "title": "To Delete",
            "target_class": "10",
            "target_topic": "1",
            "task_ids": [task["id"]],
        },
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    test_id = create_resp.json()["id"]

    resp = await async_client.delete(
        f"/teacher/tests/{test_id}",
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert resp.status_code == 200, resp.text
    assert "message" in resp.json()

    # Verify deleted
    get_resp = await async_client.get(
        f"/teacher/tests/{test_id}",
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert get_resp.status_code in (404, 403)


# ═══════════════════════════════════════════════════════════════
# Управление учениками
# ═══════════════════════════════════════════════════════════════


@pytest.mark.teacher
@pytest.mark.asyncio
async def test_teacher_get_my_students(
    async_client: AsyncClient, teacher_token: str, admin_token: str
) -> None:
    """БТ: Учитель видит список своих учеников."""
    teacher_id, student_id = await _get_teacher_student_id(
        async_client, admin_token, teacher_token
    )

    resp = await async_client.get(
        "/teacher/students",
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    # Response may be a list of UserResponse
    assert isinstance(data, (list, dict))


@pytest.mark.teacher
@pytest.mark.asyncio
async def test_teacher_get_student_profile(
    async_client: AsyncClient, teacher_token: str, admin_token: str
) -> None:
    """БТ: Учитель может просмотреть профиль своего ученика."""
    teacher_id, student_id = await _get_teacher_student_id(
        async_client, admin_token, teacher_token
    )

    resp = await async_client.get(
        f"/teacher/students-profile/{student_id}",
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.teacher
@pytest.mark.asyncio
async def test_teacher_get_student_history(
    async_client: AsyncClient, teacher_token: str, admin_token: str
) -> None:
    """БТ: Учитель может просмотреть историю своего ученика."""
    teacher_id, student_id = await _get_teacher_student_id(
        async_client, admin_token, teacher_token
    )

    resp = await async_client.get(
        f"/teacher/students-history/{student_id}",
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert resp.status_code == 200, resp.text
    assert isinstance(resp.json(), list)


# ═══════════════════════════════════════════════════════════════
# Назначение тестов
# ═══════════════════════════════════════════════════════════════


@pytest.mark.teacher
@pytest.mark.asyncio
async def test_teacher_assign_test_to_student(
    async_client: AsyncClient, teacher_token: str, admin_token: str
) -> None:
    """БТ: Учитель может назначить тест ученику."""
    teacher_id, student_id = await _get_teacher_student_id(
        async_client, admin_token, teacher_token
    )

    task = await async_create_task(async_client, admin_token, {
        "task_class": "10", "topic_number": "1",
        "content": "Assign test Q", "answer": "Answer",
        "is_open_answer": True, "difficulty": 1,
        "hint": "hint", "solution": "solution",
    })

    test_resp = await async_client.post(
        "/teacher/tests",
        json={
            "title": "Assign Test",
            "target_class": "10",
            "target_topic": "1",
            "task_ids": [task["id"]],
        },
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    test_id = test_resp.json()["id"]

    resp = await async_client.post(
        "/teacher/assign-test",
        json={"test_id": test_id, "user_ids": [student_id]},
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    # Should return list of TeacherAssignmentItemResponse
    assert isinstance(data, list)


@pytest.mark.teacher
@pytest.mark.asyncio
async def test_teacher_get_test_assignments(
    async_client: AsyncClient, teacher_token: str, admin_token: str
) -> None:
    """БТ: Учитель может просмотреть назначения теста."""
    teacher_id, student_id = await _get_teacher_student_id(
        async_client, admin_token, teacher_token
    )
    task = await async_create_task(async_client, admin_token, {
        "task_class": "10", "topic_number": "1",
        "content": "Assignment Q", "answer": "A",
        "is_open_answer": True, "difficulty": 1,
        "hint": "hint", "solution": "solution",
    })
    test_resp = await async_client.post(
        "/teacher/tests",
        json={
            "title": "Assignment Info Test",
            "target_class": "10", "target_topic": "1",
            "task_ids": [task["id"]],
        },
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    test_id = test_resp.json()["id"]

    await async_client.post(
        "/teacher/assign-test",
        json={"test_id": test_id, "user_ids": [student_id]},
        headers={"Authorization": f"Bearer {teacher_token}"},
    )

    resp = await async_client.get(
        f"/teacher/test/{test_id}/assignments",
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert resp.status_code == 200, resp.text


# ═══════════════════════════════════════════════════════════════
# Управление группами
# ═══════════════════════════════════════════════════════════════


@pytest.mark.teacher
@pytest.mark.asyncio
async def test_teacher_group_crud(
    async_client: AsyncClient, teacher_token: str, admin_token: str
) -> None:
    """БТ: Полный цикл CRUD групп: создать, получить, обновить, удалить."""
    # Create
    create_resp = await async_client.post(
        "/teacher/groups/",
        json={"name": "Test Group", "description": "A test group"},
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert create_resp.status_code == 200, create_resp.text
    group = create_resp.json()
    group_id = group["id"]
    assert group["name"] == "Test Group"

    # Get all
    list_resp = await async_client.get(
        "/teacher/groups/",
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert list_resp.status_code == 200
    groups = list_resp.json()
    assert any(g["id"] == group_id for g in groups)

    # Update
    update_resp = await async_client.put(
        f"/teacher/groups/{group_id}",
        json={"name": "Renamed Group", "description": "Updated"},
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert update_resp.status_code == 200, update_resp.text

    # Delete
    del_resp = await async_client.delete(
        f"/teacher/groups/{group_id}",
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert del_resp.status_code == 200, del_resp.text
    assert "message" in del_resp.json()


@pytest.mark.teacher
@pytest.mark.asyncio
async def test_teacher_add_students_to_group(
    async_client: AsyncClient, teacher_token: str, admin_token: str
) -> None:
    """БТ: Учитель может добавить учеников в группу."""
    teacher_id, student_id = await _get_teacher_student_id(
        async_client, admin_token, teacher_token
    )

    # Create group
    group_resp = await async_client.post(
        "/teacher/groups/",
        json={"name": "Students Group"},
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    group_id = group_resp.json()["id"]

    # Add student to group
    resp = await async_client.post(
        f"/teacher/groups/{group_id}/students",
        json={"student_ids": [student_id]},
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["added"] == 1


@pytest.mark.teacher
@pytest.mark.asyncio
async def test_teacher_delete_assignment(
    async_client: AsyncClient, teacher_token: str, admin_token: str
) -> None:
    """БТ: Учитель может удалить назначение теста."""
    teacher_id, student_id = await _get_teacher_student_id(
        async_client, admin_token, teacher_token
    )
    task = await async_create_task(async_client, admin_token, {
        "task_class": "10", "topic_number": "1",
        "content": "Delete assignment Q", "answer": "X",
        "is_open_answer": True, "difficulty": 1,
        "hint": "hint", "solution": "solution",
    })
    test_resp = await async_client.post(
        "/teacher/tests",
        json={
            "title": "Delete Assign",
            "target_class": "10", "target_topic": "1",
            "task_ids": [task["id"]],
        },
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    test_id = test_resp.json()["id"]

    assign_resp = await async_client.post(
        "/teacher/assign-test",
        json={"test_id": test_id, "user_ids": [student_id]},
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assignment = assign_resp.json()[0]
    assignment_id = assignment["id"]

    resp = await async_client.delete(
        f"/teacher/assignments/{assignment_id}",
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert resp.status_code == 200, resp.text
    assert "message" in resp.json()


# ═══════════════════════════════════════════════════════════════
# Контроль доступа
# ═══════════════════════════════════════════════════════════════


@pytest.mark.teacher
@pytest.mark.asyncio
async def test_student_cannot_access_teacher_endpoints(
    async_client: AsyncClient, student_token: str
) -> None:
    """БТ: Студент не может получить доступ к эндпоинтам учителя — ошибка 403."""
    resp = await async_client.get(
        "/teacher/tasks",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert resp.status_code == 403, resp.text


# ═══════════════════════════════════════════════════════════════
# get_task_by_id — 404
# ═══════════════════════════════════════════════════════════════


@pytest.mark.teacher
@pytest.mark.asyncio
async def test_teacher_get_task_not_found(
    async_client: AsyncClient, teacher_token: str
) -> None:
    """БТ: Получение несуществующего задания → 404."""
    resp = await async_client.get(
        "/teacher/tasks/99999",
        headers=_bearer(teacher_token),
    )
    assert resp.status_code == 404, resp.text


# ═══════════════════════════════════════════════════════════════
# Test CRUD — негативные кейсы (not found / permission)
# ═══════════════════════════════════════════════════════════════


@pytest.mark.teacher
@pytest.mark.asyncio
async def test_teacher_get_test_not_found(
    async_client: AsyncClient, teacher_token: str
) -> None:
    """БТ: Получение несуществующего теста → 404."""
    resp = await async_client.get(
        "/teacher/tests/99999",
        headers=_bearer(teacher_token),
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.teacher
@pytest.mark.asyncio
async def test_teacher_update_test_not_found(
    async_client: AsyncClient, teacher_token: str, admin_token: str
) -> None:
    """БТ: Обновление несуществующего теста → 404."""
    task = await async_create_task(async_client, admin_token, {
        "task_class": "10", "topic_number": "1",
        "content": "update nf test", "answer": "x",
        "is_open_answer": True, "difficulty": 1,
        "hint": "h", "solution": "s",
    })
    resp = await async_client.put(
        "/teacher/tests/99999",
        json={
            "title": "Updated", "target_class": "10",
            "target_topic": "1", "is_autocompile": False,
            "task_ids": [task["id"]],
        },
        headers=_bearer(teacher_token),
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.teacher
@pytest.mark.asyncio
async def test_teacher_delete_test_not_found(
    async_client: AsyncClient, teacher_token: str
) -> None:
    """БТ: Удаление несуществующего теста → 404."""
    resp = await async_client.delete(
        "/teacher/tests/99999",
        headers=_bearer(teacher_token),
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.teacher
@pytest.mark.asyncio
async def test_teacher_cannot_delete_anothers_test(
    async_client: AsyncClient, admin_token: str, teacher_token: str
) -> None:
    """БТ: Учитель не может удалить чужой тест → 403."""
    task = await async_create_task(async_client, admin_token, {
        "task_class": "10", "topic_number": "1",
        "content": "admin test", "answer": "42",
        "is_open_answer": True, "difficulty": 1,
        "hint": "h", "solution": "s",
    })
    test_resp = await async_client.post(
        "/teacher/tests",
        json={
            "title": "Admins Test", "target_class": "10",
            "target_topic": "1", "task_ids": [task["id"]],
        },
        headers=_bearer(admin_token),
    )
    test_id = test_resp.json()["id"]
    resp = await async_client.delete(
        f"/teacher/tests/{test_id}",
        headers=_bearer(teacher_token),
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.teacher
@pytest.mark.asyncio
async def test_teacher_cannot_get_anothers_test(
    async_client: AsyncClient, admin_token: str, teacher_token: str
) -> None:
    """БТ: Учитель не может просмотреть чужой тест → 403."""
    task = await async_create_task(async_client, admin_token, {
        "task_class": "10", "topic_number": "1",
        "content": "admin only", "answer": "42",
        "is_open_answer": True, "difficulty": 1,
        "hint": "h", "solution": "s",
    })
    test_resp = await async_client.post(
        "/teacher/tests",
        json={
            "title": "Admin Only Test", "target_class": "10",
            "target_topic": "1", "task_ids": [task["id"]],
        },
        headers=_bearer(admin_token),
    )
    test_id = test_resp.json()["id"]
    resp = await async_client.get(
        f"/teacher/tests/{test_id}",
        headers=_bearer(teacher_token),
    )
    assert resp.status_code == 403, resp.text


# ═══════════════════════════════════════════════════════════════
# Student access — PermissionError (не привязан)
# ═══════════════════════════════════════════════════════════════


@pytest.mark.teacher
@pytest.mark.asyncio
async def test_teacher_get_student_profile_not_linked(
    async_client: AsyncClient, teacher_token: str, admin_token: str, student_token: str
) -> None:
    """БТ: Профиль не-привязанного ученика → 403."""
    users = (await async_client.get("/admin/users", headers=_bearer(admin_token))).json()
    student = next((u for u in users if u["role"] == "student"), None)
    assert student is not None
    resp = await async_client.get(
        f"/teacher/students-profile/{student['id']}",
        headers=_bearer(teacher_token),
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.teacher
@pytest.mark.asyncio
async def test_teacher_get_student_history_not_linked(
    async_client: AsyncClient, teacher_token: str, admin_token: str, student_token: str
) -> None:
    """БТ: История не-привязанного ученика → 403."""
    users = (await async_client.get("/admin/users", headers=_bearer(admin_token))).json()
    student = next((u for u in users if u["role"] == "student"), None)
    assert student is not None
    resp = await async_client.get(
        f"/teacher/students-history/{student['id']}",
        headers=_bearer(teacher_token),
    )
    assert resp.status_code == 403, resp.text


# ═══════════════════════════════════════════════════════════════
# Детальный результат (teacher -> get_detailed_result)
# ═══════════════════════════════════════════════════════════════


@pytest.mark.teacher
@pytest.mark.asyncio
async def test_teacher_get_detailed_result_full_cycle(
    async_client: AsyncClient, admin_token: str, teacher_token: str
) -> None:
    """БТ: Полный цикл: учитель создаёт тест → студент проходит →
    учитель смотрит детальный результат с проверкой всех полей."""
    teacher_id, student_id = await _get_teacher_student_id(
        async_client, admin_token, teacher_token)

    task = await async_create_task(async_client, admin_token, {
        "task_class": "10", "topic_number": "1",
        "topic": "algebra", "section": "equations",
        "content": "2 + 2 = ?",
        "answer": "4",
        "is_open_answer": False,
        "options": ["3", "4", "5", "6"],
        "difficulty": 2,
        "hint": "it's simple", "solution": "2+2=4",
    })
    test_resp = await async_client.post(
        "/teacher/tests",
        json={
            "title": "Teacher Result Test", "target_class": "10",
            "target_topic": "1", "task_ids": [task["id"]],
        },
        headers=_bearer(teacher_token),
    )
    test_data = test_resp.json()

    await async_client.post(
        "/teacher/assign-test",
        json={"test_id": test_data["id"], "user_ids": [student_id]},
        headers=_bearer(teacher_token),
    )

    # login as student, start + submit
    email = "teacher-student@test.com"
    s_login = (await async_client.post(
        "/login", data={"username": email, "password": "TeachSt1!"})).json()
    s_tok = s_login["access_token"]
    await async_client.post(
        f"/student/start-test/{test_data['id']}", headers=_bearer(s_tok))
    await async_client.post(
        f"/student/tests/{test_data['id']}/submit",
        json=[{"task_id": task["id"], "user_answer": "4"}],
        headers=_bearer(s_tok),
    )

    hist = (await async_client.get("/student/history", headers=_bearer(s_tok))).json()
    result_id = hist[0]["id"]

    detail = (await async_client.get(
        f"/teacher/results/{result_id}", headers=_bearer(teacher_token))).json()
    assert detail["test_title"] == "Teacher Result Test"
    assert detail["total_points"] == 1
    assert detail["max_points"] == 1
    assert detail["completed_at"] is not None
    assert "user" in detail
    assert detail["user"]["last_name"] == "Test"
    assert "difficulty_stats" in detail
    assert len(detail["details"]) == 1
    assert detail["details"][0]["task_id"] == task["id"]
    assert detail["details"][0]["is_correct"] is True
    assert detail["details"][0]["points_earned"] == 1


@pytest.mark.teacher
@pytest.mark.asyncio
async def test_teacher_get_detailed_result_not_found(
    async_client: AsyncClient, teacher_token: str
) -> None:
    """БТ: Несуществующий результат → 404."""
    resp = await async_client.get(
        "/teacher/results/99999", headers=_bearer(teacher_token))
    assert resp.status_code == 404, resp.text


@pytest.mark.teacher
@pytest.mark.asyncio
async def test_teacher_get_detailed_result_permission_denied(
    async_client: AsyncClient, admin_token: str, teacher_token: str
) -> None:
    """БТ: Учитель не может смотреть результат чужого ученика → 403."""
    # Create student linked to admin, then teacher tries to view
    email = "tperm@test.com"
    await async_client.post(
        "/admin/allowed-emails", json={"email": email},
        headers=_bearer(admin_token))
    await async_client.post("/register", json={
        "username": email, "password": "TPerm1@!", "first_name": "P", "last_name": "D"})

    users = (await async_client.get("/admin/users", headers=_bearer(admin_token))).json()
    student = next((u for u in users if u["username"] == email), None)
    admin_user = next((u for u in users if u["role"] == "admin"), None)
    await async_client.post(
        "/admin/assign-student-to-teacher",
        json={"teacher_id": admin_user["id"], "student_id": student["id"]},
        headers=_bearer(admin_token))

    task = await async_create_task(async_client, admin_token, {
        "task_class": "10", "topic_number": "1",
        "content": "perm", "answer": "ok", "is_open_answer": True,
        "difficulty": 1, "hint": "h", "solution": "s"})
    test = (await async_client.post(
        "/teacher/tests",
        json={"title": "Perm T", "target_class": "10", "target_topic": "1",
              "task_ids": [task["id"]]},
        headers=_bearer(admin_token))).json()
    await async_client.post(
        "/teacher/assign-test",
        json={"test_id": test["id"], "user_ids": [student["id"]]},
        headers=_bearer(admin_token))
    s_tok = (await async_client.post(
        "/login", data={"username": email, "password": "TPerm1@!"})).json()["access_token"]
    await async_client.post(f"/student/start-test/{test['id']}", headers=_bearer(s_tok))
    await async_client.post(
        f"/student/tests/{test['id']}/submit",
        json=[{"task_id": task["id"], "user_answer": "ok"}], headers=_bearer(s_tok))
    hist = (await async_client.get("/student/history", headers=_bearer(s_tok))).json()

    resp = await async_client.get(
        f"/teacher/results/{hist[0]['id']}", headers=_bearer(teacher_token))
    assert resp.status_code == 403, resp.text


# ═══════════════════════════════════════════════════════════════
# assign_test — негативные кейсы
# ═══════════════════════════════════════════════════════════════


@pytest.mark.teacher
@pytest.mark.asyncio
async def test_teacher_assign_test_not_found(
    async_client: AsyncClient, teacher_token: str
) -> None:
    """БТ: Назначение несуществующего теста → 404."""
    resp = await async_client.post(
        "/teacher/assign-test",
        json={"test_id": 99999, "user_ids": [1]},
        headers=_bearer(teacher_token),
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.teacher
@pytest.mark.asyncio
async def test_teacher_assign_test_students_not_found(
    async_client: AsyncClient, admin_token: str, teacher_token: str
) -> None:
    """БТ: Назначение теста несуществующим пользователям → 404."""
    task = await async_create_task(async_client, admin_token, {
        "task_class": "10", "topic_number": "1",
        "content": "assign nfe", "answer": "x",
        "is_open_answer": True, "difficulty": 1,
        "hint": "h", "solution": "s",
    })
    test = (await async_client.post(
        "/teacher/tests",
        json={"title": "AssignNF", "target_class": "10", "target_topic": "1",
              "task_ids": [task["id"]]},
        headers=_bearer(teacher_token))).json()
    resp = await async_client.post(
        "/teacher/assign-test",
        json={"test_id": test["id"], "user_ids": [99999]},
        headers=_bearer(teacher_token),
    )
    assert resp.status_code == 404, resp.text


# ═══════════════════════════════════════════════════════════════
# get_test_assignments — негативные кейсы
# ═══════════════════════════════════════════════════════════════


@pytest.mark.teacher
@pytest.mark.asyncio
async def test_teacher_get_test_assignments_not_found(
    async_client: AsyncClient, teacher_token: str
) -> None:
    """БТ: Назначения несуществующего теста → 404."""
    resp = await async_client.get(
        "/teacher/test/99999/assignments", headers=_bearer(teacher_token))
    assert resp.status_code == 404, resp.text


@pytest.mark.teacher
@pytest.mark.asyncio
async def test_teacher_get_test_assignments_permission_denied(
    async_client: AsyncClient, admin_token: str, teacher_token: str
) -> None:
    """БТ: Чужой тест → нельзя смотреть назначения → 403."""
    task = await async_create_task(async_client, admin_token, {
        "task_class": "10", "topic_number": "1",
        "content": "perm", "answer": "x",
        "is_open_answer": True, "difficulty": 1,
        "hint": "h", "solution": "s",
    })
    test = (await async_client.post(
        "/teacher/tests",
        json={"title": "AdminPermT", "target_class": "10", "target_topic": "1",
              "task_ids": [task["id"]]},
        headers=_bearer(admin_token))).json()
    resp = await async_client.get(
        f"/teacher/test/{test['id']}/assignments", headers=_bearer(teacher_token))
    assert resp.status_code == 403, resp.text


# ═══════════════════════════════════════════════════════════════
# get_student_assignments + негативные
# ═══════════════════════════════════════════════════════════════


@pytest.mark.teacher
@pytest.mark.asyncio
async def test_teacher_get_student_assignments(
    async_client: AsyncClient, admin_token: str, teacher_token: str
) -> None:
    """БТ: Учитель видит назначения своего ученика с max_points и percentage."""
    teacher_id, student_id = await _get_teacher_student_id(
        async_client, admin_token, teacher_token)
    task = await async_create_task(async_client, admin_token, {
        "task_class": "10", "topic_number": "1",
        "content": "SA", "answer": "x",
        "is_open_answer": True, "difficulty": 1,
        "hint": "h", "solution": "s",
    })
    test = (await async_client.post(
        "/teacher/tests",
        json={"title": "StudentAssign", "target_class": "10", "target_topic": "1",
              "task_ids": [task["id"]]},
        headers=_bearer(teacher_token))).json()
    await async_client.post(
        "/teacher/assign-test",
        json={"test_id": test["id"], "user_ids": [student_id]},
        headers=_bearer(teacher_token))
    data = (await async_client.get(
        f"/teacher/student/{student_id}/assignments", headers=_bearer(teacher_token))).json()
    assert isinstance(data, list)
    assert len(data) >= 1
    assert data[0]["test_id"] == test["id"]
    assert "max_points" in data[0]
    assert "student_name" in data[0]


@pytest.mark.teacher
@pytest.mark.asyncio
async def test_teacher_get_student_assignments_student_not_found(
    async_client: AsyncClient, teacher_token: str
) -> None:
    """БТ: Назначения несуществующего студента → 404."""
    resp = await async_client.get(
        "/teacher/student/99999/assignments", headers=_bearer(teacher_token))
    assert resp.status_code == 404, resp.text


@pytest.mark.teacher
@pytest.mark.asyncio
async def test_teacher_get_student_assignments_permission_denied(
    async_client: AsyncClient, teacher_token: str, admin_token: str, student_token: str
) -> None:
    """БТ: Нельзя смотреть назначения чужого студента → 403."""
    users = (await async_client.get("/admin/users", headers=_bearer(admin_token))).json()
    student = next((u for u in users if u["role"] == "student"), None)
    resp = await async_client.get(
        f"/teacher/student/{student['id']}/assignments", headers=_bearer(teacher_token))
    assert resp.status_code == 403, resp.text


# ═══════════════════════════════════════════════════════════════
# delete_assignment — негативные кейсы
# ═══════════════════════════════════════════════════════════════


@pytest.mark.teacher
@pytest.mark.asyncio
async def test_teacher_delete_assignment_not_found(
    async_client: AsyncClient, teacher_token: str
) -> None:
    """БТ: Удаление несуществующего назначения → 404."""
    resp = await async_client.delete(
        "/teacher/assignments/99999", headers=_bearer(teacher_token))
    assert resp.status_code == 404, resp.text


# ═══════════════════════════════════════════════════════════════
# assign_test_to_group — полный цикл + негативные
# ═══════════════════════════════════════════════════════════════


@pytest.mark.teacher
@pytest.mark.asyncio
async def test_teacher_assign_test_to_group_success(
    async_client: AsyncClient, admin_token: str, teacher_token: str
) -> None:
    """БТ: Назначение теста группе — success с verified_count."""
    teacher_id, student_id = await _get_teacher_student_id(
        async_client, admin_token, teacher_token)
    grp = (await async_client.post(
        "/teacher/groups/", json={"name": "G Assign"},
        headers=_bearer(teacher_token))).json()
    await async_client.post(
        f"/teacher/groups/{grp['id']}/students",
        json={"student_ids": [student_id]}, headers=_bearer(teacher_token))
    task = await async_create_task(async_client, admin_token, {
        "task_class": "10", "topic_number": "1",
        "content": "grp Q", "answer": "A",
        "is_open_answer": True, "difficulty": 1, "hint": "h", "solution": "s"})
    test = (await async_client.post(
        "/teacher/tests",
        json={"title": "GrpAssignT", "target_class": "10", "target_topic": "1",
              "task_ids": [task["id"]]},
        headers=_bearer(teacher_token))).json()
    resp = await async_client.post(
        "/teacher/assign-test-to-group",
        json={"group_id": grp["id"], "test_id": test["id"]},
        headers=_bearer(teacher_token))
    assert resp.status_code == 200, resp.text
    d = resp.json()
    assert d["assigned_count"] >= 1
    assert d["group_id"] == grp["id"]
    assert d["test_id"] == test["id"]


@pytest.mark.teacher
@pytest.mark.asyncio
async def test_teacher_assign_test_to_group_not_found(
    async_client: AsyncClient, teacher_token: str
) -> None:
    """БТ: Назначение теста несуществующей группе → 404."""
    resp = await async_client.post(
        "/teacher/assign-test-to-group",
        json={"group_id": 99999, "test_id": 1}, headers=_bearer(teacher_token))
    assert resp.status_code == 404, resp.text


@pytest.mark.teacher
@pytest.mark.asyncio
async def test_teacher_assign_test_to_group_empty(
    async_client: AsyncClient, teacher_token: str
) -> None:
    """БТ: Назначение теста в пустую группу → 404."""
    grp = (await async_client.post(
        "/teacher/groups/", json={"name": "EmptyG"},
        headers=_bearer(teacher_token))).json()
    resp = await async_client.post(
        "/teacher/assign-test-to-group",
        json={"group_id": grp["id"], "test_id": 1}, headers=_bearer(teacher_token))
    assert resp.status_code == 404, resp.text


# ═══════════════════════════════════════════════════════════════
# Groups — негативные кейсы
# ═══════════════════════════════════════════════════════════════


@pytest.mark.teacher
@pytest.mark.asyncio
async def test_teacher_create_group_empty_name(
    async_client: AsyncClient, teacher_token: str
) -> None:
    """БТ: Создание группы с пустым названием → 400."""
    resp = await async_client.post(
        "/teacher/groups/", json={"name": ""}, headers=_bearer(teacher_token))
    assert resp.status_code == 400, resp.text


@pytest.mark.teacher
@pytest.mark.asyncio
async def test_teacher_update_group_not_found(
    async_client: AsyncClient, teacher_token: str
) -> None:
    """БТ: Обновление несуществующей группы → 404."""
    resp = await async_client.put(
        "/teacher/groups/99999", json={"name": "X"}, headers=_bearer(teacher_token))
    assert resp.status_code == 404, resp.text


@pytest.mark.teacher
@pytest.mark.asyncio
async def test_teacher_delete_group_not_found(
    async_client: AsyncClient, teacher_token: str
) -> None:
    """БТ: Удаление несуществующей группы → 404."""
    resp = await async_client.delete(
        "/teacher/groups/99999", headers=_bearer(teacher_token))
    assert resp.status_code == 404, resp.text


@pytest.mark.teacher
@pytest.mark.asyncio
async def test_teacher_add_students_to_group_not_found(
    async_client: AsyncClient, teacher_token: str
) -> None:
    """БТ: Добавление студентов в несуществующую группу → 404."""
    resp = await async_client.post(
        "/teacher/groups/99999/students",
        json={"student_ids": [1]}, headers=_bearer(teacher_token))
    assert resp.status_code == 404, resp.text


# ═══════════════════════════════════════════════════════════════
# Access control — student forbidden (расширенные)
# ═══════════════════════════════════════════════════════════════


@pytest.mark.teacher
@pytest.mark.asyncio
async def test_student_cannot_create_test(
    async_client: AsyncClient, student_token: str
) -> None:
    """БТ: Студент не может создавать тесты → 403."""
    resp = await async_client.post(
        "/teacher/tests",
        json={"title": "Hack", "target_class": "10", "target_topic": "1", "task_ids": []},
        headers=_bearer(student_token),
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.teacher
@pytest.mark.asyncio
async def test_student_cannot_assign_test(
    async_client: AsyncClient, student_token: str
) -> None:
    """БТ: Студент не может назначать тесты → 403."""
    resp = await async_client.post(
        "/teacher/assign-test",
        json={"test_id": 1, "user_ids": [1]}, headers=_bearer(student_token))
    assert resp.status_code == 403, resp.text


@pytest.mark.teacher
@pytest.mark.asyncio
async def test_student_cannot_access_groups(
    async_client: AsyncClient, student_token: str
) -> None:
    """БТ: Студент не может управлять группами → 403."""
    resp = await async_client.get("/teacher/groups/", headers=_bearer(student_token))
    assert resp.status_code == 403, resp.text
