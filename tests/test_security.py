"""
🛡️ ТЕСТЫ БЕЗОПАСНОСТИ
SQL-инъекции, XSS, массовые атаки, защита ролей.
"""

import pytest
import pytest_asyncio
from sqlalchemy import select
import core.models as models


class TestSQLInjection:
    """Тесты на SQL-инъекции"""

    @pytest.mark.parametrize("injection", [
        "'; DROP TABLE users; --",
        "' OR '1'='1",
        "'; SELECT * FROM users; --",
        "admin'--",
        "1; DROP TABLE tasks; --",
    ])
    async def test_login_sql_injection(self, client, db, injection):
        """❌ SQL-инъекция в логин"""
        allowed = models.AllowedEmail(email="safe@test.com")
        db.add(allowed)
        await db.commit()

        client.post("/register", json={
            "username": "safe@test.com", "password": "Safe123!",
            "first_name": "Safe", "last_name": "User"
        })

        # Инъекция в username
        response = client.post(
            "/login",
            data={"username": injection, "password": "test"}
        )
        # Должен вернуть 401 (неверный логин/пароль), а не 500
        assert response.status_code == 401

    @pytest.mark.parametrize("injection", [
        "'; DROP TABLE users; --",
        "' OR '1'='1",
        "1 OR 1=1",
        "999 UNION SELECT * FROM users",
    ])
    def test_task_id_sql_injection(self, client, admin_user, injection):
        """❌ SQL-инъекция в ID задания"""
        response = client.get(
            f"/admin/tasks/{injection}",
            headers={"Authorization": f"Bearer {admin_user['token']}"}
        )
        # Должен вернуть 404 или 422, но не 500
        assert response.status_code in [404, 422]

    @pytest.mark.parametrize("injection", [
        "'; DROP TABLE users; --",
        "' OR '1'='1",
    ])
    def test_search_injection(self, client, teacher_user, injection):
        """❌ SQL-инъекция в параметры поиска"""
        response = client.get(
            f"/teacher/tasks?topic={injection}",
            headers={"Authorization": f"Bearer {teacher_user['token']}"}
        )
        assert response.status_code in [200, 400]
        assert response.status_code != 500


class TestXSSTasks:
    """Тесты на XSS через контент заданий"""

    @pytest.mark.parametrize("xss_payload", [
        "<script>alert('XSS')</script>",
        "<img src=x onerror=alert(1)>",
        "javascript:alert('XSS')",
        "{{7*7}}",
        "${7*7}",
    ])
    def test_xss_in_task_content(self, client, admin_user, xss_payload):
        """❌ XSS в контенте задания"""
        response = client.post(
            "/admin/tasks",
            json={
                "task_class": "10", "topic_number": "1", "topic": xss_payload,
                "section": xss_payload, "content": xss_payload,
                "answer": "2", "hint": xss_payload, "solution": xss_payload,
                "is_open_answer": False, "options": ["1", "2", "3", "4"], "difficulty": 1
            },
            headers={"Authorization": f"Bearer {admin_user['token']}"}
        )
        # Создание должно пройти успешно (защита на уровне вывода, не ввода)
        assert response.status_code == 200

        # Проверяем, что данные сохранены как есть (без экранирования в БД)
        task_id = response.json()["id"]

        get_response = client.get(
            f"/admin/tasks/{task_id}",
            headers={"Authorization": f"Bearer {admin_user['token']}"
            }
        )
        assert get_response.status_code == 200
        # XSS payload сохранён (защита должна быть на фронте + Content-Type)
        assert xss_payload in str(get_response.json().values())

    @pytest.mark.parametrize("xss_payload", [
        "<script>alert('XSS')</script>",
        "<img src=x onerror=alert(1)>",
    ])
    def test_xss_in_user_answer(self, client, student_user, assigned_test, xss_payload):
        """❌ XSS в ответе студента"""
        task_id = assigned_test['tasks'][0]['id']

        response = client.post(
            f"/student/tests/{assigned_test['id']}/submit",
            json=[{"task_id": task_id, "user_answer": xss_payload}],
            headers={"Authorization": f"Bearer {student_user['token']}"}
        )
        # Должен принять, но не выполнить
        assert response.status_code == 200


class TestMassRequests:
    """Тесты на массовые/нагрузочные запросы"""

    async def test_rapid_registrations(self, client, db):
        """✅ Множественная регистрация"""
        for i in range(5):
            email = f"mass{i}@test.com"
            allowed = models.AllowedEmail(email=email)
            db.add(allowed)
            await db.commit()

            response = client.post("/register", json={
                "username": email, "password": f"Pass{i}123!",
                "first_name": f"Mass{i}", "last_name": "User"
            })
            assert response.status_code == 200

    async def test_rapid_login(self, client, db):
        """✅ Множественный логин"""
        allowed = models.AllowedEmail(email="rapid@test.com")
        db.add(allowed)
        await db.commit()

        client.post("/register", json={
            "username": "rapid@test.com", "password": "Rapid123!",
            "first_name": "Rapid", "last_name": "User"
        })

        for _ in range(5):
            response = client.post(
                "/login",
                data={"username": "rapid@test.com", "password": "Rapid123!"}
            )
            assert response.status_code == 200
            assert "access_token" in response.json()


class TestRoleBasedAccess:
    """Тесты ролевого доступа"""

    def test_student_access_denied(self, client, student_user):
        """❌ Студент не может использовать teacher эндпоинты"""
        teacher_endpoints = [
            ("GET", "/teacher/tests"),
            ("POST", "/teacher/tests"),
            ("GET", "/teacher/groups/"),
            ("POST", "/teacher/groups/"),
            ("GET", "/teacher/students"),
            ("POST", "/teacher/assign-test"),
        ]
        for method, url in teacher_endpoints:
            if method == "GET":
                response = client.get(url, headers={"Authorization": f"Bearer {student_user['token']}"})
            else:
                response = client.post(url, json={}, headers={"Authorization": f"Bearer {student_user['token']}"})
            assert response.status_code == 403, f"{method} {url} should return 403"

    def test_teacher_cannot_access_admin(self, client, teacher_user):
        """❌ Учитель не может использовать admin эндпоинты"""
        admin_endpoints = [
            ("GET", "/admin/users"),
            ("POST", "/admin/tasks"),
            ("GET", "/admin/theory/getall"),
        ]
        for method, url in admin_endpoints:
            if method == "GET":
                response = client.get(url, headers={"Authorization": f"Bearer {teacher_user['token']}"})
            else:
                response = client.post(url, json={}, headers={"Authorization": f"Bearer {teacher_user['token']}"})
            assert response.status_code == 403, f"{method} {url} should return 403"

    def test_teacher_can_access_student_assigned_test(self, client, teacher_user, student_user,
                                                       link_teacher_student, assigned_test):
        """✅ Учитель может просматривать назначения своих студентов"""
        response = client.get(
            f"/teacher/student/{student_user['id']}/assignments",
            headers={"Authorization": f"Bearer {teacher_user['token']}"}
        )
        assert response.status_code == 200


class TestDataIntegrity:
    """Тесты целостности данных"""

    async def test_cascade_delete_teacher(self, client, db, admin_user, teacher_user, student_user,
                                     link_teacher_student, sample_task):
        """✅ При удалении учителя удаляются его группы и тесты"""
        # Создаём группу
        group = client.post("/teacher/groups/", json={"name": "Моя группа"},
                           headers={"Authorization": f"Bearer {teacher_user['token']}"}).json()

        # Создаём тест
        test = client.post("/teacher/tests", json={
            "title": "Мой тест", "target_class": "10", "target_topic": "1",
            "is_autocompile": False, "task_ids": [sample_task]
        }, headers={"Authorization": f"Bearer {teacher_user['token']}"}).json()

        group_id = group["id"]
        test_id = test["id"]

        # Удаляем учителя
        client.delete(
            f"/admin/users/{teacher_user['id']}",
            headers={"Authorization": f"Bearer {admin_user['token']}"}
        )

        # Проверяем, что группа и тест удалены
        assert (await db.execute(select(models.Group).where(models.Group.id == group_id))).scalars().first() is None
        assert (await db.execute(select(models.Test).where(models.Test.id == test_id))).scalars().first() is None

    async def test_cascade_delete_student(self, client, db, admin_user, teacher_user, student_user,
                                     link_teacher_student, assigned_test):
        """✅ При удалении студента удаляются его результаты"""
        student_id = student_user["id"]

        client.delete(
            f"/admin/users/{student_id}",
            headers={"Authorization": f"Bearer {admin_user['token']}"}
        )

        # Проверяем, что результаты удалены
        results = (await db.execute(select(models.TestResult).where(models.TestResult.user_id == student_id))).scalars().all()
        assert len(results) == 0

        # Проверяем, что назначения удалены
        assignments = (await db.execute(select(models.TestAssignment).where(
            models.TestAssignment.user_id == student_id
        ))).scalars().all()
        assert len(assignments) == 0
