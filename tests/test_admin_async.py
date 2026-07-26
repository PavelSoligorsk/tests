"""
Асинхронные тесты админ-панели на httpx.AsyncClient.

Покрывают бизнес-требования:
- Управление пользователями (список, профиль, история, смена роли, удаление)
- CRUD заданий (одиночное + пакетное создание/обновление/удаление)
- Управление разрешёнными email
- Назначение/открепление учеников от учителей
- CRUD теории
- Контроль доступа (не-админ не может выполнять админские действия)
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient


# ═══════════════════════════════════════════════════════════════
# Управление пользователями
# ═══════════════════════════════════════════════════════════════


@pytest.mark.admin
@pytest.mark.asyncio
async def test_admin_get_users(
    async_client: AsyncClient, admin_token: str
) -> None:
    """БТ: Администратор видит список всех пользователей."""
    resp = await async_client.get(
        "/admin/users",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200, resp.text
    users = resp.json()
    assert isinstance(users, list)
    # At least the admin user themselves should be present
    assert len(users) >= 1
    assert all("id" in u and "username" in u and "role" in u for u in users)


@pytest.mark.admin
@pytest.mark.asyncio
async def test_admin_get_user_profile(
    async_client: AsyncClient, admin_token: str, teacher_token: str
) -> None:
    """БТ: Администратор может просмотреть профиль любого пользователя."""
    # Register a user to get its ID
    # teacher_token is already a registered user, let's get teacher's info
    # We need teacher's ID — use /admin/users
    resp_users = await async_client.get(
        "/admin/users",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    users = resp_users.json()
    teacher = next((u for u in users if u["role"] == "teacher"), None)
    assert teacher is not None, "Teacher user should exist"

    resp = await async_client.get(
        f"/admin/users/{teacher['id']}/profile",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "user" in data
    assert data["user"]["id"] == teacher["id"]


@pytest.mark.admin
@pytest.mark.asyncio
async def test_admin_get_user_history(
    async_client: AsyncClient, admin_token: str, teacher_token: str
) -> None:
    """БТ: Администратор может просмотреть историю пользователя."""
    resp_users = await async_client.get(
        "/admin/users",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    users = resp_users.json()
    teacher = next((u for u in users if u["role"] == "teacher"), None)
    assert teacher is not None

    resp = await async_client.get(
        f"/admin/users/{teacher['id']}/history",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200, resp.text
    assert isinstance(resp.json(), list)


@pytest.mark.admin
@pytest.mark.asyncio
async def test_admin_change_user_role(
    async_client: AsyncClient, admin_token: str, teacher_token: str
) -> None:
    """БТ: Администратор может изменить роль пользователя."""
    # Get a student to change their role
    # First, register a student manually
    email = "rolechange@test.com"
    await async_client.post(
        "/admin/allowed-emails", json={"email": email},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    await async_client.post("/register", json={
        "username": email, "password": "RoleTest1!",
        "first_name": "Role", "last_name": "Test",
    })
    login_resp = await async_client.post("/login", data={
        "username": email, "password": "RoleTest1!",
    })
    assert login_resp.status_code == 200

    resp_users = await async_client.get(
        "/admin/users",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    users = resp_users.json()
    student = next((u for u in users if u["username"] == email), None)
    assert student is not None

    # Change role to teacher
    resp = await async_client.patch(
        f"/admin/users/{student['id']}/role",
        json={"new_role": "teacher"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200, resp.text
    assert "изменена" in resp.json()["message"]


@pytest.mark.admin
@pytest.mark.asyncio
async def test_admin_cannot_delete_self(
    async_client: AsyncClient, admin_token: str
) -> None:
    """БТ: Администратор не может удалить сам себя."""
    resp_users = await async_client.get(
        "/admin/users",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    admin = next((u for u in resp_users.json() if u["role"] == "admin"), None)
    assert admin is not None

    resp = await async_client.delete(
        f"/admin/users/{admin['id']}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 400, resp.text


@pytest.mark.admin
@pytest.mark.asyncio
async def test_admin_delete_user(
    async_client: AsyncClient, admin_token: str
) -> None:
    """БТ: Администратор может удалить пользователя."""
    # Create a disposable student
    email = "delete-me@test.com"
    await async_client.post(
        "/admin/allowed-emails", json={"email": email},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    await async_client.post("/register", json={
        "username": email, "password": "DeleteMe1!",
        "first_name": "Del", "last_name": "User",
    })

    resp_users = await async_client.get(
        "/admin/users",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    user_to_delete = next(
        (u for u in resp_users.json() if u["username"] == email), None
    )
    assert user_to_delete is not None

    resp = await async_client.delete(
        f"/admin/users/{user_to_delete['id']}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200, resp.text


# ═══════════════════════════════════════════════════════════════
# CRUD заданий (одиночное)
# ═══════════════════════════════════════════════════════════════


@pytest.mark.admin
@pytest.mark.asyncio
async def test_admin_create_task(
    async_client: AsyncClient, admin_token: str
) -> None:
    """БТ: Администратор может создать задание."""
    resp = await async_client.post(
        "/admin/tasks",
        json={
            "task_class": "10",
            "topic_number": "1",
            "topic": "algebra",
            "section": "equations",
            "content": "Solve: $2x + 3 = 7$",
            "answer": "2",
            "hint": "Move 3 to the right side",
            "solution": "$$2x = 4$$ $$x = 2$$",
            "is_open_answer": False,
            "options": ["1", "2", "3", "4"],
            "difficulty": 2,
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["id"] > 0
    assert data["task_class"] == "10"
    assert data["topic"] == "algebra"


@pytest.mark.admin
@pytest.mark.asyncio
async def test_admin_get_tasks(
    async_client: AsyncClient, admin_token: str
) -> None:
    """БТ: Администратор может получить список всех заданий."""
    # Create a task first
    await async_client.post(
        "/admin/tasks",
        json={
            "task_class": "9",
            "topic_number": "2",
            "topic": "geometry",
            "section": "circles",
            "content": "What is the area of a circle with radius r?",
            "answer": "pi*r^2",
            "is_open_answer": True,
            "difficulty": 1,
            "hint": "Use the formula",
            "solution": "S = πr²",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    resp = await async_client.get(
        "/admin/",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200, resp.text
    tasks = resp.json()
    assert isinstance(tasks, list)
    assert len(tasks) >= 1


@pytest.mark.admin
@pytest.mark.asyncio
async def test_admin_get_single_task(
    async_client: AsyncClient, admin_token: str
) -> None:
    """БТ: Администратор может получить задание по ID."""
    create_resp = await async_client.post(
        "/admin/tasks",
        json={
            "task_class": "11",
            "topic_number": "3",
            "topic": "trigonometry",
            "section": "basics",
            "content": "Find sin(30°)",
            "answer": "0.5",
            "is_open_answer": False,
            "options": ["0", "0.5", "1", "√3/2"],
            "difficulty": 1,
            "hint": "Remember the table",
            "solution": "sin 30° = 0.5",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    task_id = create_resp.json()["id"]

    resp = await async_client.get(
        f"/admin/tasks/{task_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == task_id


@pytest.mark.admin
@pytest.mark.asyncio
async def test_admin_update_task(
    async_client: AsyncClient, admin_token: str
) -> None:
    """БТ: Администратор может обновить задание."""
    create_resp = await async_client.post(
        "/admin/tasks",
        json={
            "task_class": "10", "topic_number": "1",
            "topic": "algebra", "section": "equations",
            "content": "Old content",
            "answer": "old",
            "is_open_answer": True,
            "difficulty": 1,
            "hint": "old hint",
            "solution": "old solution",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    task_id = create_resp.json()["id"]

    resp = await async_client.put(
        f"/admin/tasks/{task_id}",
        json={
            "task_class": "10", "topic_number": "1",
            "topic": "algebra", "section": "equations",
            "content": "Updated content",
            "answer": "new",
            "is_open_answer": True,
            "difficulty": 2,
            "hint": "new hint",
            "solution": "new solution",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["content"] == "Updated content"


@pytest.mark.admin
@pytest.mark.asyncio
async def test_admin_delete_task(
    async_client: AsyncClient, admin_token: str
) -> None:
    """БТ: Администратор может удалить задание."""
    create_resp = await async_client.post(
        "/admin/tasks",
        json={
            "task_class": "5", "topic_number": "1",
            "topic": "math", "section": "basics",
            "content": "To be deleted",
            "answer": "42",
            "is_open_answer": True,
            "difficulty": 1,
            "hint": "Think",
            "solution": "The answer",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    task_id = create_resp.json()["id"]

    resp = await async_client.delete(
        f"/admin/tasks/{task_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200, resp.text
    assert "message" in resp.json()

    # Verify deleted
    get_resp = await async_client.get(
        f"/admin/tasks/{task_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert get_resp.status_code == 404


@pytest.mark.admin
@pytest.mark.asyncio
async def test_admin_get_nonexistent_task(
    async_client: AsyncClient, admin_token: str
) -> None:
    """БТ: Запрос несуществующего задания — ошибка 404."""
    resp = await async_client.get(
        "/admin/tasks/99999",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 404, resp.text


# ═══════════════════════════════════════════════════════════════
# Пакетные операции с заданиями
# ═══════════════════════════════════════════════════════════════


@pytest.mark.admin
@pytest.mark.asyncio
async def test_admin_batch_create_tasks(
    async_client: AsyncClient, admin_token: str
) -> None:
    """БТ: Администратор может создать несколько заданий за один запрос."""
    resp = await async_client.post(
        "/admin/tasks/batch",
        json={
            "tasks": [
                {
                    "task_class": "8", "topic_number": "1",
                    "topic": "algebra", "section": "fractions",
                    "content": "1/2 + 1/3 = ?",
                    "answer": "5/6",
                    "is_open_answer": True,
                    "difficulty": 1,
                    "hint": "Find common denominator",
                    "solution": "1/2 + 1/3 = 3/6 + 2/6 = 5/6",
                },
                {
                    "task_class": "8", "topic_number": "1",
                    "topic": "algebra", "section": "fractions",
                    "content": "3/4 - 1/2 = ?",
                    "answer": "1/4",
                    "is_open_answer": True,
                    "difficulty": 1,
                    "hint": "Convert to common denominator",
                    "solution": "3/4 - 2/4 = 1/4",
                },
            ]
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["total"] == 2
    assert len(data["created"]) == 2


@pytest.mark.admin
@pytest.mark.asyncio
async def test_admin_batch_update_tasks(
    async_client: AsyncClient, admin_token: str
) -> None:
    """БТ: Администратор может обновить несколько заданий за один запрос."""
    # Create 2 tasks
    batch_create = await async_client.post(
        "/admin/tasks/batch",
        json={
            "tasks": [
                {
                    "task_class": "7", "topic_number": "2",
                    "content": "Old Q1", "answer": "A1",
                    "is_open_answer": True, "difficulty": 1,
                    "hint": "H1", "solution": "S1",
                },
                {
                    "task_class": "7", "topic_number": "2",
                    "content": "Old Q2", "answer": "A2",
                    "is_open_answer": True, "difficulty": 1,
                    "hint": "H2", "solution": "S2",
                },
            ]
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    ids = [t["id"] for t in batch_create.json()["created"]]
    assert len(ids) == 2

    resp = await async_client.put(
        "/admin/tasks/batch",
        json={
            "tasks": [
                {"id": ids[0], "content": "Updated Q1", "difficulty": 3},
                {"id": ids[1], "content": "Updated Q2", "difficulty": 3},
            ]
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["total_updated"] == 2


@pytest.mark.admin
@pytest.mark.asyncio
async def test_admin_batch_delete_tasks(
    async_client: AsyncClient, admin_token: str
) -> None:
    """БТ: Администратор может удалить несколько заданий за один запрос."""
    # Create 2 tasks
    batch_create = await async_client.post(
        "/admin/tasks/batch",
        json={
            "tasks": [
                {
                    "task_class": "6", "topic_number": "1",
                    "content": "Delete me 1", "answer": "A",
                    "is_open_answer": True, "difficulty": 1,
                    "hint": "H", "solution": "S",
                },
                {
                    "task_class": "6", "topic_number": "1",
                    "content": "Delete me 2", "answer": "B",
                    "is_open_answer": True, "difficulty": 1,
                    "hint": "H", "solution": "S",
                },
            ]
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    ids = [t["id"] for t in batch_create.json()["created"]]

    resp = await async_client.request(
        "DELETE", "/admin/tasks/batch",
        json={"ids": ids},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["total_deleted"] == 2

    # Verify deleted
    for tid in ids:
        get_resp = await async_client.get(
            f"/admin/tasks/{tid}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert get_resp.status_code == 404


# ═══════════════════════════════════════════════════════════════
# Управление разрешёнными email
# ═══════════════════════════════════════════════════════════════


@pytest.mark.admin
@pytest.mark.asyncio
async def test_admin_allowed_emails_crud(
    async_client: AsyncClient, admin_token: str
) -> None:
    """БТ: Полный цикл CRUD разрешённых email."""
    email = "crud-email@test.com"

    # Add
    add_resp = await async_client.post(
        "/admin/allowed-emails",
        json={"email": email},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert add_resp.status_code == 200, add_resp.text

    # List
    list_resp = await async_client.get(
        "/admin/allowed/emails",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert list_resp.status_code == 200
    emails = list_resp.json()
    assert any(e["email"] == email for e in emails)

    # Delete
    del_resp = await async_client.delete(
        f"/admin/allowed-emails/{email}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert del_resp.status_code == 200, del_resp.text

    # Verify deleted
    list_resp2 = await async_client.get(
        "/admin/allowed/emails",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert not any(e["email"] == email for e in list_resp2.json())


# ═══════════════════════════════════════════════════════════════
# Назначение учеников учителям
# ═══════════════════════════════════════════════════════════════


@pytest.mark.admin
@pytest.mark.asyncio
async def test_admin_assign_student_to_teacher(
    async_client: AsyncClient, admin_token: str, teacher_token: str
) -> None:
    """БТ: Администратор может назначить ученика учителю."""
    # Create a student
    email = "assign-student@test.com"
    await async_client.post(
        "/admin/allowed-emails", json={"email": email},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    await async_client.post("/register", json={
        "username": email, "password": "Assign1!",
        "first_name": "Assign", "last_name": "Student",
    })

    users_resp = await async_client.get(
        "/admin/users",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    users = users_resp.json()
    student = next((u for u in users if u["username"] == email), None)
    teacher = next((u for u in users if u["role"] == "teacher"), None)
    assert student is not None
    assert teacher is not None

    resp = await async_client.post(
        "/admin/assign-student-to-teacher",
        json={"teacher_id": teacher["id"], "student_id": student["id"]},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200, resp.text
    assert "message" in resp.json()


@pytest.mark.admin
@pytest.mark.asyncio
async def test_admin_remove_student_from_teacher(
    async_client: AsyncClient, admin_token: str, teacher_token: str
) -> None:
    """БТ: Администратор может открепить ученика от учителя."""
    # Create student and assign to teacher
    email = "remove-student@test.com"
    await async_client.post(
        "/admin/allowed-emails", json={"email": email},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    await async_client.post("/register", json={
        "username": email, "password": "Remove1!",
        "first_name": "Rem", "last_name": "Student",
    })

    users_resp = await async_client.get(
        "/admin/users",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    users = users_resp.json()
    student = next((u for u in users if u["username"] == email), None)
    teacher = next((u for u in users if u["role"] == "teacher"), None)
    assert student is not None and teacher is not None

    # Assign first
    assign_resp = await async_client.post(
        "/admin/assign-student-to-teacher",
        json={"teacher_id": teacher["id"], "student_id": student["id"]},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert assign_resp.status_code == 200

    # Now remove
    resp = await async_client.delete(
        f"/admin/remove-student-from-teacher/{student['id']}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200, resp.text
    assert "message" in resp.json()


# ═══════════════════════════════════════════════════════════════
# Теория (CRUD)
# ═══════════════════════════════════════════════════════════════


@pytest.mark.admin
@pytest.mark.asyncio
async def test_admin_theory_crud(
    async_client: AsyncClient, admin_token: str
) -> None:
    """БТ: Полный цикл CRUD теории: создать, получить, обновить, удалить."""
    # Create
    create_resp = await async_client.post(
        "/admin/theory",
        json={
            "topic": "algebra",
            "section": "quadratic_equations",
            "content": "A quadratic equation is ax² + bx + c = 0.",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert create_resp.status_code == 200, create_resp.text
    theory = create_resp.json()
    theory_id = theory["id"]
    assert theory["topic"] == "algebra"

    # Get all
    all_resp = await async_client.get(
        "/admin/theory/getall",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert all_resp.status_code == 200
    assert any(t["id"] == theory_id for t in all_resp.json())

    # Get by id
    get_resp = await async_client.get(
        f"/admin/theory/{theory_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == theory_id

    # Update
    update_resp = await async_client.put(
        f"/admin/theory/{theory_id}",
        json={"content": "Updated: ax² + bx + c = 0 where a ≠ 0."},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert update_resp.status_code == 200, update_resp.text
    assert "Updated" in update_resp.json()["content"]

    # Delete
    del_resp = await async_client.delete(
        f"/admin/theory/{theory_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert del_resp.status_code == 200, del_resp.text


# ═══════════════════════════════════════════════════════════════
# Контроль доступа
# ═══════════════════════════════════════════════════════════════


@pytest.mark.admin
@pytest.mark.asyncio
async def test_non_admin_cannot_access_admin_endpoints(
    async_client: AsyncClient, student_token: str
) -> None:
    """БТ: Студент не может получить доступ к админским эндпоинтам — ошибка 403."""
    resp = await async_client.get(
        "/admin/users",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.admin
@pytest.mark.asyncio
async def test_unauthenticated_cannot_access_admin_endpoints(
    async_client: AsyncClient,
) -> None:
    """БТ: Неавторизованный пользователь не может получить доступ к админке — ошибка 401."""
    resp = await async_client.get("/admin/users")
    assert resp.status_code in (401, 403), f"Unexpected: {resp.status_code} {resp.text}"


# ═══════════════════════════════════════════════════════════════
# Детальный результат (get_detailed_result)
# ═══════════════════════════════════════════════════════════════


@pytest.mark.admin
@pytest.mark.asyncio
async def test_admin_get_detailed_result_full_cycle(
    async_client: AsyncClient, admin_token: str, teacher_token: str, student_token: str
) -> None:
    """БТ: Полный цикл — админ создаёт задание → учитель создаёт тест →
    студент проходит → админ получает детальный результат со всеми полями."""
    # 1. Admin creates a task
    create_task_resp = await async_client.post(
        "/admin/tasks",
        json={
            "task_class": "10", "topic_number": "1",
            "topic": "algebra", "section": "equations",
            "content": "Solve: 2x + 3 = 7",
            "answer": "2",
            "is_open_answer": False,
            "options": ["1", "2", "3", "4"],
            "difficulty": 2,
            "hint": "Move 3 to the right side",
            "solution": "2x = 4, x = 2",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert create_task_resp.status_code == 200
    task = create_task_resp.json()

    # 2. Get teacher & student IDs
    users_resp = await async_client.get(
        "/admin/users",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    users = users_resp.json()
    teacher = next((u for u in users if u["role"] == "teacher"), None)
    student = next((u for u in users if u["username"] == "student_async@test.com"), None)
    assert teacher is not None and student is not None

    # 3. Link student to teacher
    link_resp = await async_client.post(
        "/admin/assign-student-to-teacher",
        json={"teacher_id": teacher["id"], "student_id": student["id"]},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert link_resp.status_code == 200

    # 4. Teacher creates test
    test_resp = await async_client.post(
        "/teacher/tests",
        json={
            "title": "Detailed Result Test",
            "target_class": "10",
            "target_topic": "1",
            "task_ids": [task["id"]],
        },
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert test_resp.status_code == 200
    test_data = test_resp.json()

    # 5. Teacher assigns test to student
    assign_resp = await async_client.post(
        "/teacher/assign-test",
        json={"test_id": test_data["id"], "user_ids": [student["id"]]},
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert assign_resp.status_code == 200

    # 6. Student starts the test
    start_resp = await async_client.post(
        f"/student/start-test/{test_data['id']}",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert start_resp.status_code == 200

    # 7. Student submits correct answer
    submit_resp = await async_client.post(
        f"/student/tests/{test_data['id']}/submit",
        json=[{"task_id": task["id"], "user_answer": "2"}],
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert submit_resp.status_code == 200
    submit_data = submit_resp.json()
    assert submit_data["status"] == "success"
    assert submit_data["score"] == 1  # closed answer correct = 1 point

    # 8. Get result_id from student history
    history_resp = await async_client.get(
        "/student/history",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert history_resp.status_code == 200
    history = history_resp.json()
    assert len(history) >= 1
    result_id = history[0]["id"]

    # 9. Admin gets detailed result
    detail_resp = await async_client.get(
        f"/admin/results/{result_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert detail_resp.status_code == 200, detail_resp.text
    detail = detail_resp.json()

    # Verify all fields
    assert detail["test_title"] == "Detailed Result Test"
    assert detail["total_points"] == 1
    assert detail["max_points"] == 1  # closed answer = 1 max
    assert detail["completed_at"] is not None
    assert "difficulty_stats" in detail
    assert "2" in detail["difficulty_stats"]  # difficulty level 2
    assert detail["difficulty_stats"]["2"]["total"] == 1
    assert detail["difficulty_stats"]["2"]["correct"] == 1
    assert "user" in detail
    assert detail["user"]["first_name"] == "Student"
    assert detail["user"]["last_name"] == "Async"
    assert "details" in detail
    assert len(detail["details"]) == 1
    d = detail["details"][0]
    assert d["task_id"] == task["id"]
    assert d["content"] == "Solve: 2x + 3 = 7"
    assert d["options"] == ["1", "2", "3", "4"]
    assert d["correct_answer"] == "2"
    assert d["user_answer"] == "2"
    assert d["is_correct"] is True
    assert d["points_earned"] == 1
    assert d["max_task_points"] == 1
    assert d["solution"] == "2x = 4, x = 2"
    assert d["hint"] == "Move 3 to the right side"
    assert d["difficulty"] == 2


@pytest.mark.admin
@pytest.mark.asyncio
async def test_admin_get_detailed_result_not_found(
    async_client: AsyncClient, admin_token: str
) -> None:
    """БТ: Запрос несуществующего результата — ошибка 404."""
    resp = await async_client.get(
        "/admin/results/99999",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.admin
@pytest.mark.asyncio
async def test_admin_get_detailed_result_with_open_answer(
    async_client: AsyncClient, admin_token: str, teacher_token: str, student_token: str
) -> None:
    """БТ: Детальный результат с открытым ответом — проверка max_task_points=2 и баллов."""
    # 1. Create open-answer task
    task_resp = await async_client.post(
        "/admin/tasks",
        json={
            "task_class": "11", "topic_number": "1",
            "topic": "algebra", "section": "expressions",
            "content": "Simplify: a * a^2",
            "answer": "a^3",
            "is_open_answer": True,
            "difficulty": 1,
            "hint": "Add exponents",
            "solution": "a^(1+2) = a^3",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert task_resp.status_code == 200
    task = task_resp.json()

    # 2. Get teacher & student
    users_resp = await async_client.get(
        "/admin/users", headers={"Authorization": f"Bearer {admin_token}"})
    users = users_resp.json()
    teacher = next((u for u in users if u["role"] == "teacher"), None)
    student = next((u for u in users if u["username"] == "student_async@test.com"), None)

    # Link if not already
    await async_client.post(
        "/admin/assign-student-to-teacher",
        json={"teacher_id": teacher["id"], "student_id": student["id"]},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    # 3. Teacher creates test
    test_resp = await async_client.post(
        "/teacher/tests",
        json={
            "title": "Open Answer Test",
            "target_class": "11", "target_topic": "1",
            "task_ids": [task["id"]],
        },
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert test_resp.status_code == 200
    test_data = test_resp.json()

    # 4. Assign and submit with wrong answer
    await async_client.post(
        "/teacher/assign-test",
        json={"test_id": test_data["id"], "user_ids": [student["id"]]},
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    await async_client.post(
        f"/student/start-test/{test_data['id']}",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    await async_client.post(
        f"/student/tests/{test_data['id']}/submit",
        json=[{"task_id": task["id"], "user_answer": "wrong"}],
        headers={"Authorization": f"Bearer {student_token}"},
    )

    # Get result_id
    history_resp = await async_client.get(
        "/student/history", headers={"Authorization": f"Bearer {student_token}"})
    result_id = history_resp.json()[0]["id"]

    # Admin checks detailed result
    detail_resp = await async_client.get(
        f"/admin/results/{result_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    assert detail["max_points"] == 2  # open answer = 2 max
    assert detail["total_points"] == 0  # wrong answer
    d = detail["details"][0]
    assert d["is_correct"] is False
    assert d["points_earned"] == 0
    assert d["max_task_points"] == 2


# ═══════════════════════════════════════════════════════════════
# Каскадное пересчитывание при update_task
# ═══════════════════════════════════════════════════════════════


@pytest.mark.admin
@pytest.mark.asyncio
async def test_admin_update_task_cascade_recompute(
    async_client: AsyncClient, admin_token: str, teacher_token: str, student_token: str
) -> None:
    """БТ: При изменении ответа задания каскадно пересчитываются
    UserAnswer.is_correct, points_earned и TestResult.total_points."""
    # 1. Create closed-answer task with answer="4"
    task_resp = await async_client.post(
        "/admin/tasks",
        json={
            "task_class": "9", "topic_number": "1",
            "topic": "math", "section": "basics",
            "content": "2 + 2 = ?",
            "answer": "4",
            "is_open_answer": False,
            "options": ["3", "4", "5", "6"],
            "difficulty": 1,
            "hint": "Think simple",
            "solution": "2 + 2 = 4",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert task_resp.status_code == 200
    task = task_resp.json()

    # 2. Get teacher & student, link them
    users_resp = await async_client.get(
        "/admin/users", headers={"Authorization": f"Bearer {admin_token}"})
    users = users_resp.json()
    teacher = next((u for u in users if u["role"] == "teacher"), None)
    student = next((u for u in users if u["username"] == "student_async@test.com"), None)
    await async_client.post(
        "/admin/assign-student-to-teacher",
        json={"teacher_id": teacher["id"], "student_id": student["id"]},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    # 3. Teacher creates test & assigns
    test_resp = await async_client.post(
        "/teacher/tests",
        json={
            "title": "Cascade Test",
            "target_class": "9", "target_topic": "1",
            "task_ids": [task["id"]],
        },
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    test_data = test_resp.json()
    await async_client.post(
        "/teacher/assign-test",
        json={"test_id": test_data["id"], "user_ids": [student["id"]]},
        headers={"Authorization": f"Bearer {teacher_token}"},
    )

    # 4. Student submits answer "4" — correct
    await async_client.post(
        f"/student/start-test/{test_data['id']}",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    await async_client.post(
        f"/student/tests/{test_data['id']}/submit",
        json=[{"task_id": task["id"], "user_answer": "4"}],
        headers={"Authorization": f"Bearer {student_token}"},
    )

    # Verify before update: correct
    history_resp = await async_client.get(
        "/student/history", headers={"Authorization": f"Bearer {student_token}"})
    result_id = history_resp.json()[0]["id"]
    detail_before = await async_client.get(
        f"/admin/results/{result_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert detail_before.status_code == 200
    assert detail_before.json()["total_points"] == 1
    assert detail_before.json()["details"][0]["is_correct"] is True
    assert detail_before.json()["details"][0]["points_earned"] == 1

    # 5. Admin updates task answer from "4" to "5" — cascade recompute
    update_resp = await async_client.put(
        f"/admin/tasks/{task['id']}",
        json={
            "task_class": "9", "topic_number": "1",
            "topic": "math", "section": "basics",
            "content": "2 + 2 = ?",
            "answer": "5",  # Changed!
            "is_open_answer": False,
            "options": ["3", "4", "5", "6"],
            "difficulty": 1,
            "hint": "Think simple",
            "solution": "2 + 2 = 4",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert update_resp.status_code == 200, update_resp.text

    # 6. Verify after update: now wrong
    detail_after = await async_client.get(
        f"/admin/results/{result_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert detail_after.status_code == 200
    d = detail_after.json()
    assert d["total_points"] == 0, f"Expected 0, got {d['total_points']}"
    assert d["details"][0]["is_correct"] is False
    assert d["details"][0]["points_earned"] == 0


# ═══════════════════════════════════════════════════════════════
# Каскадное удаление пользователя
# ═══════════════════════════════════════════════════════════════


@pytest.mark.admin
@pytest.mark.asyncio
async def test_admin_delete_user_cascade(
    async_client: AsyncClient, admin_token: str, teacher_token: str
) -> None:
    """БТ: Удаление пользователя каскадно удаляет результаты, ответы,
    назначения, группы и связи учитель-ученик."""
    # 1. Create a student with connected data
    email = "cascade-delete@test.com"
    await async_client.post(
        "/admin/allowed-emails", json={"email": email},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    await async_client.post("/register", json={
        "username": email, "password": "Cascade1!",
        "first_name": "Cascade", "last_name": "Delete",
    })

    users_resp = await async_client.get(
        "/admin/users", headers={"Authorization": f"Bearer {admin_token}"})
    users = users_resp.json()
    student = next((u for u in users if u["username"] == email), None)
    teacher = next((u for u in users if u["role"] == "teacher"), None)
    assert student is not None and teacher is not None

    # 2. Link student to teacher
    await async_client.post(
        "/admin/assign-student-to-teacher",
        json={"teacher_id": teacher["id"], "student_id": student["id"]},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    # 3. Create task + test + assign + submit (so there are results/answers)
    task_resp = await async_client.post(
        "/admin/tasks",
        json={
            "task_class": "5", "topic_number": "1",
            "topic": "math", "section": "basics",
            "content": "1 + 1 = ?", "answer": "2",
            "is_open_answer": False,
            "options": ["1", "2", "3", "4"],
            "difficulty": 1,
            "hint": "simple", "solution": "1 + 1 = 2",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    task = task_resp.json()
    test_resp = await async_client.post(
        "/teacher/tests",
        json={
            "title": "Cascade Delete Test", "target_class": "5",
            "target_topic": "1", "task_ids": [task["id"]],
        },
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    test_data = test_resp.json()
    await async_client.post(
        "/teacher/assign-test",
        json={"test_id": test_data["id"], "user_ids": [student["id"]]},
        headers={"Authorization": f"Bearer {teacher_token}"},
    )

    # Login as student and submit
    student_login = await async_client.post(
        "/login", data={"username": email, "password": "Cascade1!"})
    student_tok = student_login.json()["access_token"]
    await async_client.post(
        f"/student/start-test/{test_data['id']}",
        headers={"Authorization": f"Bearer {student_tok}"},
    )
    await async_client.post(
        f"/student/tests/{test_data['id']}/submit",
        json=[{"task_id": task["id"], "user_answer": "2"}],
        headers={"Authorization": f"Bearer {student_tok}"},
    )

    # 4. Delete user
    del_resp = await async_client.delete(
        f"/admin/users/{student['id']}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert del_resp.status_code == 200, del_resp.text
    assert "удалены" in del_resp.json()["message"]

    # 5. Verify user gone from /admin/users
    users_after = await async_client.get(
        "/admin/users", headers={"Authorization": f"Bearer {admin_token}"})
    assert not any(u["id"] == student["id"] for u in users_after.json())

    # 6. Verify profile 404
    profile_resp = await async_client.get(
        f"/admin/users/{student['id']}/profile",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert profile_resp.status_code == 404


# ═══════════════════════════════════════════════════════════════
# change_user_role — негативные кейсы
# ═══════════════════════════════════════════════════════════════


@pytest.mark.admin
@pytest.mark.asyncio
async def test_admin_change_role_invalid_role(
    async_client: AsyncClient, admin_token: str, teacher_token: str
) -> None:
    """БТ: Недопустимая роль → ошибка 400."""
    users_resp = await async_client.get(
        "/admin/users", headers={"Authorization": f"Bearer {admin_token}"})
    teacher = next((u for u in users_resp.json() if u["role"] == "teacher"), None)
    assert teacher is not None

    resp = await async_client.patch(
        f"/admin/users/{teacher['id']}/role",
        json={"new_role": "superhero"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 400, resp.text
    assert "Недопустимая роль" in resp.json()["detail"]


@pytest.mark.admin
@pytest.mark.asyncio
async def test_admin_change_role_user_not_found(
    async_client: AsyncClient, admin_token: str
) -> None:
    """БТ: Смена роли несуществующего пользователя → ошибка 404."""
    resp = await async_client.patch(
        "/admin/users/99999/role",
        json={"new_role": "teacher"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.admin
@pytest.mark.asyncio
async def test_admin_cannot_demote_self(
    async_client: AsyncClient, admin_token: str
) -> None:
    """БТ: Админ не может снять роль админа с самого себя → ошибка 400."""
    users_resp = await async_client.get(
        "/admin/users", headers={"Authorization": f"Bearer {admin_token}"})
    admin = next((u for u in users_resp.json() if u["role"] == "admin"), None)
    assert admin is not None

    resp = await async_client.patch(
        f"/admin/users/{admin['id']}/role",
        json={"new_role": "student"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 400, resp.text
    assert "не можете" in resp.json()["detail"].lower()


# ═══════════════════════════════════════════════════════════════
# get_user_profile / delete_user — 404
# ═══════════════════════════════════════════════════════════════


@pytest.mark.admin
@pytest.mark.asyncio
async def test_admin_get_user_profile_not_found(
    async_client: AsyncClient, admin_token: str
) -> None:
    """БТ: Профиль несуществующего пользователя → ошибка 404."""
    resp = await async_client.get(
        "/admin/users/99999/profile",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.admin
@pytest.mark.asyncio
async def test_admin_delete_user_not_found(
    async_client: AsyncClient, admin_token: str
) -> None:
    """БТ: Удаление несуществующего пользователя → ошибка 404."""
    resp = await async_client.delete(
        "/admin/users/99999",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 404, resp.text


# ═══════════════════════════════════════════════════════════════
# delete_task — 404
# ═══════════════════════════════════════════════════════════════


@pytest.mark.admin
@pytest.mark.asyncio
async def test_admin_delete_nonexistent_task(
    async_client: AsyncClient, admin_token: str
) -> None:
    """БТ: Удаление несуществующего задания → ошибка 404."""
    resp = await async_client.delete(
        "/admin/tasks/99999",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 404, resp.text


# ═══════════════════════════════════════════════════════════════
# allowed emails — негативные кейсы
# ═══════════════════════════════════════════════════════════════


@pytest.mark.admin
@pytest.mark.asyncio
async def test_admin_add_allowed_email_empty(
    async_client: AsyncClient, admin_token: str
) -> None:
    """БТ: Пустой email → ошибка 400."""
    resp = await async_client.post(
        "/admin/allowed-emails",
        json={"email": ""},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.admin
@pytest.mark.asyncio
async def test_admin_add_allowed_email_duplicate(
    async_client: AsyncClient, admin_token: str
) -> None:
    """БТ: Дубликат email → ошибка 400."""
    email = "duplicate-email@test.com"
    # First add
    await async_client.post(
        "/admin/allowed-emails",
        json={"email": email},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    # Duplicate
    resp = await async_client.post(
        "/admin/allowed-emails",
        json={"email": email},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 400, resp.text
    assert "уже" in resp.json()["detail"]


@pytest.mark.admin
@pytest.mark.asyncio
async def test_admin_delete_allowed_email_not_found(
    async_client: AsyncClient, admin_token: str
) -> None:
    """БТ: Удаление несуществующего email → ошибка 404."""
    resp = await async_client.delete(
        "/admin/allowed-emails/nonexistent@test.com",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 404, resp.text


# ═══════════════════════════════════════════════════════════════
# assign_student_to_teacher — негативные кейсы
# ═══════════════════════════════════════════════════════════════


@pytest.mark.admin
@pytest.mark.asyncio
async def test_admin_assign_student_teacher_not_found(
    async_client: AsyncClient, admin_token: str, student_token: str
) -> None:
    """БТ: Назначение с несуществующим учителем → ошибка 404."""
    users_resp = await async_client.get(
        "/admin/users", headers={"Authorization": f"Bearer {admin_token}"})
    student = next((u for u in users_resp.json() if u["role"] == "student"), None)
    assert student is not None

    resp = await async_client.post(
        "/admin/assign-student-to-teacher",
        json={"teacher_id": 99999, "student_id": student["id"]},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.admin
@pytest.mark.asyncio
async def test_admin_assign_student_not_found(
    async_client: AsyncClient, admin_token: str, teacher_token: str
) -> None:
    """БТ: Назначение несуществующего ученика → ошибка 404."""
    users_resp = await async_client.get(
        "/admin/users", headers={"Authorization": f"Bearer {admin_token}"})
    teacher = next((u for u in users_resp.json() if u["role"] == "teacher"), None)
    assert teacher is not None

    resp = await async_client.post(
        "/admin/assign-student-to-teacher",
        json={"teacher_id": teacher["id"], "student_id": 99999},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.admin
@pytest.mark.asyncio
async def test_admin_assign_not_student_to_teacher(
    async_client: AsyncClient, admin_token: str, teacher_token: str
) -> None:
    """БТ: Нельзя назначить не-студента (например, другого учителя) учеником → ошибка 404."""
    users_resp = await async_client.get(
        "/admin/users", headers={"Authorization": f"Bearer {admin_token}"})
    teacher = next((u for u in users_resp.json() if u["role"] == "teacher"), None)
    admin = next((u for u in users_resp.json() if u["role"] == "admin"), None)
    assert teacher is not None and admin is not None

    resp = await async_client.post(
        "/admin/assign-student-to-teacher",
        json={"teacher_id": teacher["id"], "student_id": admin["id"]},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 404, resp.text


# ═══════════════════════════════════════════════════════════════
# remove_student_from_teacher — 404
# ═══════════════════════════════════════════════════════════════


@pytest.mark.admin
@pytest.mark.asyncio
async def test_admin_remove_student_link_not_found(
    async_client: AsyncClient, admin_token: str, student_token: str
) -> None:
    """БТ: Удаление несуществующей связи ученик-учитель → ошибка 404."""
    users_resp = await async_client.get(
        "/admin/users", headers={"Authorization": f"Bearer {admin_token}"})
    student = next((u for u in users_resp.json() if u["role"] == "student"), None)
    assert student is not None

    resp = await async_client.delete(
        f"/admin/remove-student-from-teacher/{student['id']}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 404, resp.text


# ═══════════════════════════════════════════════════════════════
# Theory — негативные кейсы
# ═══════════════════════════════════════════════════════════════


@pytest.mark.admin
@pytest.mark.asyncio
async def test_admin_create_theory_duplicate(
    async_client: AsyncClient, admin_token: str
) -> None:
    """БТ: Создание дубликата теории (topic + section) → ошибка 400."""
    payload = {
        "topic": "duplicate_topic",
        "section": "dup_section",
        "content": "Some theory content.",
    }
    # First — OK
    create1 = await async_client.post(
        "/admin/theory", json=payload,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert create1.status_code == 200, create1.text

    # Second — duplicate
    create2 = await async_client.post(
        "/admin/theory", json=payload,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert create2.status_code == 400, create2.text
    assert "уже существует" in create2.json()["detail"]


@pytest.mark.admin
@pytest.mark.asyncio
async def test_admin_get_theory_not_found(
    async_client: AsyncClient, admin_token: str
) -> None:
    """БТ: Получение несуществующей теории → ошибка 404."""
    resp = await async_client.get(
        "/admin/theory/99999",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.admin
@pytest.mark.asyncio
async def test_admin_update_theory_not_found(
    async_client: AsyncClient, admin_token: str
) -> None:
    """БТ: Обновление несуществующей теории → ошибка 400."""
    resp = await async_client.put(
        "/admin/theory/99999",
        json={"content": "New content"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 400, resp.text


@pytest.mark.admin
@pytest.mark.asyncio
async def test_admin_delete_theory_not_found(
    async_client: AsyncClient, admin_token: str
) -> None:
    """БТ: Удаление несуществующей теории → ошибка 404."""
    resp = await async_client.delete(
        "/admin/theory/99999",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 404, resp.text


# ═══════════════════════════════════════════════════════════════
# send_task_to_tg — с моком httpx
# ═══════════════════════════════════════════════════════════════


@pytest.mark.admin
@pytest.mark.asyncio
async def test_admin_send_task_to_tg_success(
    async_client: AsyncClient, admin_token: str, monkeypatch
) -> None:
    """БТ: Отправка задания в Telegram — успех (мок httpx.AsyncClient)."""
    import httpx as httpx_mod
    from unittest.mock import AsyncMock, MagicMock

    # Create a task first
    task_resp = await async_client.post(
        "/admin/tasks",
        json={
            "task_class": "10", "topic_number": "1",
            "topic": "algebra", "section": "equations",
            "content": "Solve: $2x + 3 = 7$",
            "answer": "2",
            "is_open_answer": False,
            "options": ["1", "2", "3", "4"],
            "difficulty": 2,
            "hint": "hint", "solution": "solution",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert task_resp.status_code == 200
    task = task_resp.json()

    # Mock httpx.AsyncClient.post to return success
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = "OK"

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.post.return_value = mock_response

    original_client = httpx_mod.AsyncClient
    httpx_mod.AsyncClient = lambda *args, **kwargs: mock_client

    try:
        resp = await async_client.post(
            f"/admin/tasks/{task['id']}/send-to-tg",
            json={"chat_id": "123456"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200, resp.text
        assert "отправлена" in resp.json()["message"]
    finally:
        httpx_mod.AsyncClient = original_client


@pytest.mark.admin
@pytest.mark.asyncio
async def test_admin_send_task_to_tg_not_found(
    async_client: AsyncClient, admin_token: str
) -> None:
    """БТ: Отправка несуществующего задания в TG → ошибка 404."""
    resp = await async_client.post(
        "/admin/tasks/99999/send-to-tg",
        json={"chat_id": "123456"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 404, resp.text


# ═══════════════════════════════════════════════════════════════
# rebuild_all_static_tests
# ═══════════════════════════════════════════════════════════════


@pytest.mark.admin
@pytest.mark.asyncio
async def test_admin_rebuild_all_static_tests(
    async_client: AsyncClient, admin_token: str, teacher_token: str
) -> None:
    """БТ: Пересборка статических тестов — создаются автотесты по категориям заданий."""
    # 1. Create tasks in different categories
    await async_client.post(
        "/admin/tasks/batch",
        json={
            "tasks": [
                {
                    "task_class": "10", "topic_number": "1",
                    "topic": "algebra", "section": "eq",
                    "content": "x + 1 = 3", "answer": "2",
                    "is_open_answer": True, "difficulty": 1,
                    "hint": "h", "solution": "s",
                },
                {
                    "task_class": "10", "topic_number": "2",
                    "topic": "algebra", "section": "ineq",
                    "content": "x > 3", "answer": "x>3",
                    "is_open_answer": True, "difficulty": 1,
                    "hint": "h", "solution": "s",
                },
                {
                    "task_class": "11", "topic_number": "1",
                    "topic": "trigonometry", "section": "sin",
                    "content": "sin(30) = ?", "answer": "0.5",
                    "is_open_answer": False,
                    "options": ["0", "0.5", "1", "-1"],
                    "difficulty": 1,
                    "hint": "h", "solution": "s",
                },
            ]
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    # 2. Rebuild
    rebuild_resp = await async_client.post(
        "/admin/rebuild-all-static-tests",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert rebuild_resp.status_code == 200, rebuild_resp.text
    data = rebuild_resp.json()
    assert data["status"] == "success"
    assert len(data["updated_test_ids"]) >= 2  # at least 2 categories
    assert "синхронизировано" in data["message"]

    # 3. Verify autocompile tests exist in admin's task list
    tests_resp = await async_client.get(
        "/teacher/tests",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert tests_resp.status_code == 200
    autocompile_tests = [
        t for t in tests_resp.json()
        if t.get("is_autocompile")
    ]
    assert len(autocompile_tests) >= 1


@pytest.mark.admin
@pytest.mark.asyncio
async def test_admin_rebuild_tests_idempotent(
    async_client: AsyncClient, admin_token: str
) -> None:
    """БТ: Повторная пересборка статических тестов не ломается (идемпотентность)."""
    # Create a task
    await async_client.post(
        "/admin/tasks",
        json={
            "task_class": "7", "topic_number": "5",
            "topic": "math", "section": "basics",
            "content": "1+1", "answer": "2",
            "is_open_answer": True, "difficulty": 1,
            "hint": "h", "solution": "s",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    # First rebuild
    r1 = await async_client.post(
        "/admin/rebuild-all-static-tests",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r1.status_code == 200

    # Second rebuild (idempotent)
    r2 = await async_client.post(
        "/admin/rebuild-all-static-tests",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["status"] == "success"


# ═══════════════════════════════════════════════════════════════
# Access control — teacher can't access admin endpoints
# ═══════════════════════════════════════════════════════════════


@pytest.mark.admin
@pytest.mark.asyncio
async def test_teacher_cannot_access_admin_endpoints(
    async_client: AsyncClient, teacher_token: str
) -> None:
    """БТ: Учитель не может получить доступ к админским эндпоинтам — ошибка 403."""
    resp = await async_client.get(
        "/admin/users",
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.admin
@pytest.mark.asyncio
async def test_teacher_cannot_create_task(
    async_client: AsyncClient, teacher_token: str
) -> None:
    """БТ: Учитель не может создавать задания через админку — ошибка 403."""
    resp = await async_client.post(
        "/admin/tasks",
        json={
            "task_class": "10", "topic_number": "1",
            "content": "test", "answer": "x",
            "is_open_answer": True, "difficulty": 1,
            "hint": "h", "solution": "s",
        },
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert resp.status_code == 403, resp.text
# ═══════════════════════════════════════════════════════════════
# AI-классификация заданий
# ═══════════════════════════════════════════════════════════════


@pytest.mark.admin
@pytest.mark.asyncio
async def test_admin_classify_tasks_with_ids(
    async_client: AsyncClient, admin_token: str
) -> None:
    """БТ: Админ запускает AI-классификацию заданий по списку ID.

    Проверяем:
    - Эндпоинт принимает task_ids и возвращает ClassifyTasksResponse.
    - С мокнутым AI все три фазы проходят без ошибок.
    - В ответе есть корректные счётчики processed/difficulty/solved/classified.
    """
    from unittest.mock import AsyncMock, patch

    # Создаём несколько заданий с уже заданными topic/section
    # (для построения topics_structure в сервисе)
    for i in range(3):
        resp = await async_client.post(
            "/admin/tasks",
            json={
                "task_class": "10",
                "topic_number": str(i + 1),
                "topic": "algebra",
                "section": "equations",
                "content": f"Solve: {i + 2}x + {i + 1} = 0",
                "answer": str(round(-(i + 1) / (i + 2), 4)),
                "is_open_answer": False,
                "options": ["-0.5", "0", "0.5", "1"],
                "difficulty": 1,
                "hint": "Isolate x",
                "solution": "x = -b/a",
            },
            headers={"Authorization": f"******"},
        )
        assert resp.status_code == 200, f"Task {i} creation failed: {resp.text}"

    # Мокируем AIService._chat_completion чтобы возвращать предсказуемые ответы.
    async def mock_chat_completion(
        self_: object,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 800,
        json_mode: bool = False,
        enable_thinking: bool = False,
    ) -> str:
        if "difficulty" in system_prompt.lower() or "Rate the difficulty" in user_prompt:
            return '{"difficulty": 3}'
        if "Solve EACH task" in user_prompt or "solve" in system_prompt.lower():
            import re as _re
            items = []
            for tid_str in _re.findall(r"id=(\d+)", user_prompt):
                tid = int(tid_str)
                items.append(f'{{"task_id": {tid}, "answer": "4"}}')
            return "[" + ", ".join(items) + "]"
        if "classifier" in system_prompt.lower() or "Classify this math task" in user_prompt:
            return '{"topic": "algebra", "section": "equations"}'
        return "{}"

    # Создаём НЕклассифицированные задания (без topic/section)
    unclassified_ids: list[int] = []
    for i in range(2):
        resp = await async_client.post(
            "/admin/tasks",
            json={
                "task_class": "11",
                "topic_number": "99",
                "content": f"Unclassified task {i}: 2^{i + 2} = ?",
                "answer": str(2 ** (i + 2)),
                "is_open_answer": True,
                "options": None,
                "difficulty": 1,
                "hint": "Power rule",
                "solution": "2^n",
            },
            headers={"Authorization": f"******"},
        )
        assert resp.status_code == 200, f"Unclassified task {i} failed: {resp.text}"
        unclassified_ids.append(resp.json()["id"])

    with patch(
        "services.ai_service.AIService._chat_completion",
        new_callable=AsyncMock,
        side_effect=mock_chat_completion,
    ):
        resp = await async_client.post(
            "/admin/classify-tasks",
            json={"task_ids": unclassified_ids},
            headers={"Authorization": f"******"},
        )

    assert resp.status_code == 200, f"classify-tasks failed: {resp.text}"
    data = resp.json()
    assert data["total_processed"] == 2
    assert data["difficulty_assigned"] >= 1
    assert data["solved_correctly"] >= 1
    assert data["classified"] >= 1
    assert len(data["log"]) > 0
    assert data["failed"] >= 0


@pytest.mark.admin
@pytest.mark.asyncio
async def test_admin_classify_tasks_unauthorized(
    async_client: AsyncClient,
) -> None:
    """БТ: Не-админ не может запускать AI-классификацию."""
    resp = await async_client.post(
        "/admin/classify-tasks",
        json={"task_ids": [1]},
    )
    assert resp.status_code in (401, 403), resp.text


@pytest.mark.admin
@pytest.mark.asyncio
async def test_admin_classify_tasks_empty_request(
    async_client: AsyncClient, admin_token: str
) -> None:
    """БТ: Передача пустого task_ids должна обработать все неклассифицированные задания
    или вернуть 0 если таких нет."""
    from unittest.mock import AsyncMock, patch

    async def mock_chat(*args: object, **kwargs: object) -> str:
        return "{}"

    with patch(
        "services.ai_service.AIService._chat_completion",
        new_callable=AsyncMock,
        side_effect=mock_chat,
    ):
        resp = await async_client.post(
            "/admin/classify-tasks",
            json={"task_ids": []},
            headers={"Authorization": f"******"},
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "total_processed" in data
    assert "log" in data
