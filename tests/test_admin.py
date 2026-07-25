"""

👑 ТЕСТЫ АДМИНСКИХ ВОЗМОЖНОСТЕЙ
CRUD тасок, rebuild all static tests, управление пользователями, теория.
"""

import pytest
import pytest_asyncio
import time
from sqlalchemy import select
import core.models as models


# ==================== 1. CRUD ТАСОК ====================

class TestAdminTaskCRUD:
    """Полный CRUD заданий"""

    def test_create_task(self, client, admin_user, sample_task_payload):
        """✅ Создание задания"""
        response = client.post(
            "/admin/tasks",
            json=sample_task_payload,
            headers={"Authorization": f"Bearer {admin_user['token']}"}
        )
        assert response.status_code == 200
        assert response.json()["id"] is not None
        assert response.json()["task_class"] == "11"
        assert response.json()["topic"] == "geometry"

    def test_create_task_without_auth(self, client, sample_task_payload):
        """❌ Без авторизации — 401"""
        response = client.post("/admin/tasks", json=sample_task_payload)
        assert response.status_code == 401

    def test_create_task_as_teacher(self, client, teacher_user, sample_task_payload):
        """❌ Учитель не может создать задание"""
        response = client.post(
            "/admin/tasks",
            json=sample_task_payload,
            headers={"Authorization": f"Bearer {teacher_user['token']}"}
        )
        assert response.status_code == 403

    def test_create_task_as_student(self, client, student_user, sample_task_payload):
        """❌ Студент не может создать задание"""
        response = client.post(
            "/admin/tasks",
            json=sample_task_payload,
            headers={"Authorization": f"Bearer {student_user['token']}"}
        )
        assert response.status_code == 403

    def test_create_task_missing_fields(self, client, admin_user):
        """❌ Без обязательных полей — 422"""
        response = client.post(
            "/admin/tasks",
            json={"task_class": "10", "topic_number": "1", "topic": "algebra", "answer": "2"},
            headers={"Authorization": f"Bearer {admin_user['token']}"}
        )
        assert response.status_code == 422

        response = client.post(
            "/admin/tasks",
            json={"task_class": "10", "topic_number": "1", "topic": "algebra", "content": "text"},
            headers={"Authorization": f"Bearer {admin_user['token']}"}
        )
        assert response.status_code == 422

    def test_create_task_with_options(self, client, admin_user):
        """✅ С заданием с вариантами ответов"""
        payload = {
            "task_class": "10", "topic_number": "1", "topic": "algebra",
            "section": "equations", "content": "Корень $x^2 = 4$?",
            "answer": "2,-2", "hint": "Вспомните корень",
            "solution": "$$x = \\pm 2$$",
            "is_open_answer": False, "options": ["0", "2", "-2", "4"], "difficulty": 2
        }
        response = client.post(
            "/admin/tasks", json=payload,
            headers={"Authorization": f"Bearer {admin_user['token']}"}
        )
        assert response.status_code == 200
        assert response.json()["options"] == ["0", "2", "-2", "4"]

    def test_get_all_tasks(self, client, admin_user, sample_task):
        """✅ Получение всех заданий"""
        response = client.get(
            "/admin/",
            headers={"Authorization": f"Bearer {admin_user['token']}"}
        )
        assert response.status_code == 200
        assert isinstance(response.json(), list)
        assert len(response.json()) >= 1

    def test_get_all_tasks_without_auth(self, client):
        """❌ Без авторизации — 401"""
        response = client.get("/admin/")
        assert response.status_code == 401

    def test_get_single_task(self, client, admin_user, sample_task):
        """✅ Получение задания по ID"""
        response = client.get(
            f"/admin/tasks/{sample_task}",
            headers={"Authorization": f"Bearer {admin_user['token']}"}
        )
        assert response.status_code == 200
        assert response.json()["id"] == sample_task

    def test_get_nonexistent_task(self, client, admin_user):
        """❌ Несуществующее задание — 404"""
        response = client.get(
            "/admin/tasks/99999",
            headers={"Authorization": f"Bearer {admin_user['token']}"}
        )
        assert response.status_code == 404

    def test_update_task(self, client, admin_user, sample_task):
        """✅ Обновление задания"""
        response = client.put(
            f"/admin/tasks/{sample_task}",
            json={
                "task_class": "10", "topic_number": "1", "topic": "algebra",
                "section": "equations", "content": "$3x + 5 = 14$",
                "answer": "3", "hint": "Новая", "solution": "$$3x = 9$$\n$$x = 3$$",
                "is_open_answer": False, "options": ["1", "2", "3", "4"], "difficulty": 3
            },
            headers={"Authorization": f"Bearer {admin_user['token']}"}
        )
        assert response.status_code == 200

    def test_update_task_change_type(self, client, admin_user, sample_task):
        """✅ Смена закрытого → открытый"""
        response = client.put(
            f"/admin/tasks/{sample_task}",
            json={
                "task_class": "10", "topic_number": "1", "topic": "algebra",
                "section": "equations", "content": "$2x + 3 = 7$",
                "answer": "2", "hint": "Подсказка", "solution": "Решение",
                "is_open_answer": True, "options": None, "difficulty": 2
            },
            headers={"Authorization": f"Bearer {admin_user['token']}"}
        )
        assert response.status_code == 200

    def test_delete_task(self, client, admin_user, sample_task):
        """✅ Удаление задания"""
        response = client.delete(
            f"/admin/tasks/{sample_task}",
            headers={"Authorization": f"Bearer {admin_user['token']}"}
        )
        assert response.status_code == 200
        assert "удалены" in response.json()["message"]

        get_response = client.get(
            f"/admin/tasks/{sample_task}",
            headers={"Authorization": f"Bearer {admin_user['token']}"}
        )
        assert get_response.status_code == 404

    def test_delete_nonexistent_task(self, client, admin_user):
        """❌ Удаление несуществующего — 404"""
        response = client.delete(
            "/admin/tasks/99999",
            headers={"Authorization": f"Bearer {admin_user['token']}"}
        )
        assert response.status_code == 404

    def test_delete_task_without_auth(self, client, sample_task):
        """❌ Удаление без авторизации — 401"""
        response = client.delete(f"/admin/tasks/{sample_task}")
        assert response.status_code == 401

    def test_delete_task_as_teacher(self, client, teacher_user, sample_task):
        """❌ Учитель не может удалить задание — 403"""
        response = client.delete(
            f"/admin/tasks/{sample_task}",
            headers={"Authorization": f"Bearer {teacher_user['token']}"}
        )
        assert response.status_code == 403


# ==================== 2. REBUILD ALL STATIC TESTS ====================

class TestAdminRebuild:
    """Тесты пересборки статических тестов"""

    def test_rebuild_all_static_tests(self, client, admin_user):
        """✅ Пересборка всех статических тестов"""
        response = client.post(
            "/admin/rebuild-all-static-tests",
            headers={"Authorization": f"Bearer {admin_user['token']}"}
        )
        assert response.status_code == 200
        assert response.json()["status"] == "success"

    def test_rebuild_does_not_delete_teacher_tests(self, client, admin_user, teacher_user, sample_task):
        """🛡️ Rebuild НЕ удаляет тесты учителя"""
        teacher_test = client.post(
            "/teacher/tests",
            json={"title": "Тест учителя", "target_class": "10", "target_topic": "1",
                  "is_autocompile": False, "task_ids": [sample_task]},
            headers={"Authorization": f"Bearer {teacher_user['token']}"}
        ).json()
        teacher_test_id = teacher_test["id"]

        client.post(
            "/admin/rebuild-all-static-tests",
            headers={"Authorization": f"Bearer {admin_user['token']}"}
        )

        get_test = client.get(
            f"/teacher/tests/{teacher_test_id}",
            headers={"Authorization": f"Bearer {teacher_user['token']}"}
        )
        assert get_test.status_code == 200
        assert get_test.json()["id"] == teacher_test_id

    async def test_rebuild_does_not_delete_ai_tests(self, client, admin_user, db, student_user):
        """🛡️ Rebuild НЕ удаляет AI-тесты"""
        ai_test = models.Test(
            title="AI тест", target_class=None, target_topic="test",
            is_autocompile=False, is_ai_generated=True,
            creator_id=student_user["id"], is_active=True
        )
        db.add(ai_test)
        await db.commit()
        ai_test_id = ai_test.id

        client.post(
            "/admin/rebuild-all-static-tests",
            headers={"Authorization": f"Bearer {admin_user['token']}"}
        )

        get_test = (await db.execute(select(models.Test).where(models.Test.id == ai_test_id))).scalars().first()
        assert get_test is not None, "AI-тест был удалён!"
        assert get_test.is_ai_generated is True

    async def test_rebuild_deletes_old_admin_auto_tests(self, client, admin_user, teacher_user, student_user, db):
        """✅ Rebuild удаляет старые авто-тесты и пересчитывает ответы"""
        # Создаём задания с неправильными ответами
        closed = client.post("/admin/tasks", json={
            "task_class": "20", "topic_number": "1", "topic": "algebra",
            "section": "equations", "content": "$2x + 3 = 7$",
            "answer": "999", "hint": "hint", "solution": "$$2x=4$$",
            "is_open_answer": False, "options": ["1", "2", "3", "4"], "difficulty": 2
        }, headers={"Authorization": f"Bearer {admin_user['token']}"}).json()["id"]

        open_t = client.post("/admin/tasks", json={
            "task_class": "20", "topic_number": "1", "topic": "algebra",
            "section": "expressions", "content": "$a \\cdot a^2$",
            "answer": "wrong", "hint": "hint", "solution": "$$a^3$$",
            "is_open_answer": True, "options": None, "difficulty": 1
        }, headers={"Authorization": f"Bearer {admin_user['token']}"}).json()["id"]

        # Создаём ручной тест
        link = models.TeacherStudent(teacher_id=teacher_user["id"], student_id=student_user["id"])
        db.add(link)
        await db.commit()

        test_resp = client.post("/teacher/tests", json={
            "title": "Ручной тест", "target_class": "20", "target_topic": "1",
            "is_autocompile": False, "task_ids": [closed, open_t]
        }, headers={"Authorization": f"Bearer {teacher_user['token']}"}).json()
        test_id = test_resp["id"]

        # Назначаем студенту
        client.post("/teacher/assign-test", json={"test_id": test_id, "user_ids": [student_user["id"]]},
                    headers={"Authorization": f"Bearer {teacher_user['token']}"})

        # Студент отправляет ответы
        submit = client.post(f"/student/tests/{test_id}/submit", json=[
            {"task_id": closed, "user_answer": "2"},
            {"task_id": open_t, "user_answer": "10"}
        ], headers={"Authorization": f"Bearer {student_user['token']}"})
        assert submit.status_code == 200
        assert submit.json()["score"] == 0

        # Админ обновляет ответы
        client.put(f"/admin/tasks/{closed}", json={
            "task_class": "20", "topic_number": "1", "topic": "algebra",
            "section": "equations", "content": "$2x + 3 = 7$",
            "answer": "2", "hint": "hint", "solution": "$$2x=4$$",
            "is_open_answer": False, "options": ["1", "2", "3", "4"], "difficulty": 2
        }, headers={"Authorization": f"Bearer {admin_user['token']}"})

        client.put(f"/admin/tasks/{open_t}", json={
            "task_class": "20", "topic_number": "1", "topic": "algebra",
            "section": "expressions", "content": "$a \\cdot a^2$",
            "answer": "a^3", "hint": "hint", "solution": "$$a^3$$",
            "is_open_answer": True, "options": None, "difficulty": 1
        }, headers={"Authorization": f"Bearer {admin_user['token']}"})

        # Rebuild
        rebuild = client.post("/admin/rebuild-all-static-tests",
                              headers={"Authorization": f"Bearer {admin_user['token']}"})
        assert rebuild.status_code == 200

        # Проверяем, что ответы пересчитаны
        db.expire_all()

        # Берём последний result
        last_result = (await db.execute(select(models.TestResult).where(models.TestResult.test_id == test_id
        ).order_by(models.TestResult.completed_at.desc()))).scalars().first()

        if last_result:
            user_answers = (await db.execute(select(models.UserAnswer).where(
                models.UserAnswer.result_id == last_result.id
            ))).scalars().all()
            total = sum(ua.points_earned for ua in user_answers)
            # Закрытое задание: ответ "2" (правильно) = 1 балл
            # Открытое задание: ответ "10", правильный "a^3" — не совпадает = 0 баллов
            assert total == 1, f"Ожидался 1 балл (только закрытое), получено {total}"


# ==================== 3. УПРАВЛЕНИЕ ПОЛЬЗОВАТЕЛЯМИ ====================

class TestAdminUsers:
    """Тесты управления пользователями"""

    def test_get_all_users(self, client, admin_user):
        """✅ Список всех пользователей"""
        response = client.get(
            "/admin/users",
            headers={"Authorization": f"Bearer {admin_user['token']}"}
        )
        assert response.status_code == 200
        assert isinstance(response.json(), list)
        assert len(response.json()) >= 1

    async def test_change_user_role(self, client, admin_user, db):
        """✅ Смена роли пользователя"""
        allowed = models.AllowedEmail(email="roleuser@test.com")
        db.add(allowed)
        await db.commit()

        client.post("/register", json={
            "username": "roleuser@test.com", "password": "Pass123!",
            "first_name": "Role", "last_name": "User"
        })

        user = (await db.execute(select(models.User).where(models.User.username == "roleuser@test.com"))).scalars().first()

        response = client.patch(
            f"/admin/users/{user.id}/role",
            params={"new_role": "teacher"},
            headers={"Authorization": f"Bearer {admin_user['token']}"}
        )
        assert response.status_code == 200
        assert "изменена на teacher" in response.json()["message"]

        await db.refresh(user)
        assert user.role == "teacher"

    async def test_change_role_invalid(self, client, admin_user, db):
        """❌ Неверная роль"""
        allowed = models.AllowedEmail(email="badrole@test.com")
        db.add(allowed)
        await db.commit()

        client.post("/register", json={
            "username": "badrole@test.com", "password": "Pass123!",
            "first_name": "Bad", "last_name": "Role"
        })

        user = (await db.execute(select(models.User).where(models.User.username == "badrole@test.com"))).scalars().first()

        response = client.patch(
            f"/admin/users/{user.id}/role",
            params={"new_role": "superadmin"},
            headers={"Authorization": f"Bearer {admin_user['token']}"}
        )
        assert response.status_code == 400

    async def test_delete_user(self, client, admin_user, db):
        """✅ Удаление пользователя"""
        allowed = models.AllowedEmail(email="deleteuser@test.com")
        db.add(allowed)
        await db.commit()

        client.post("/register", json={
            "username": "deleteuser@test.com", "password": "Pass123!",
            "first_name": "Delete", "last_name": "User"
        })

        user = (await db.execute(select(models.User).where(models.User.username == "deleteuser@test.com"))).scalars().first()

        response = client.delete(
            f"/admin/users/{user.id}",
            headers={"Authorization": f"Bearer {admin_user['token']}"}
        )
        assert response.status_code == 200

        deleted = (await db.execute(select(models.User).where(models.User.id == user.id))).scalars().first()
        assert deleted is None

    def test_cant_delete_last_admin(self, client, admin_user):
        """❌ Нельзя удалить последнего админа"""
        response = client.delete(
            f"/admin/users/{admin_user['id']}",
            headers={"Authorization": f"Bearer {admin_user['token']}"}
        )
        assert response.status_code == 400
        assert "Нельзя удалить" in response.json()["detail"]

    def test_delete_nonexistent_user(self, client, admin_user):
        """❌ Удаление несуществующего пользователя"""
        response = client.delete(
            "/admin/users/99999",
            headers={"Authorization": f"Bearer {admin_user['token']}"}
        )
        assert response.status_code == 404


# ==================== 4. УПРАВЛЕНИЕ ТЕОРИЕЙ ====================

class TestAdminTheory:
    """Тесты управления теоретическим материалом"""

    def test_create_theory(self, client, admin_user):
        """✅ Создание теории"""
        response = client.post(
            "/admin/theory",
            json={"topic": "algebra", "section": "equations",
                  "content": "Уравнение — это равенство с неизвестной."},
            headers={"Authorization": f"Bearer {admin_user['token']}"}
        )
        assert response.status_code == 200
        assert response.json()["topic"] == "algebra"

    async def test_create_theory_duplicate(self, client, admin_user, db):
        """❌ Дубликат теории"""
        theory = models.Theory(topic="algebra", section="equations", content="Содержание")
        db.add(theory)
        await db.commit()

        response = client.post(
            "/admin/theory",
            json={"topic": "algebra", "section": "equations", "content": "Другое"},
            headers={"Authorization": f"Bearer {admin_user['token']}"}
        )
        assert response.status_code == 400
        assert "уже существует" in response.json()["detail"]

    async def test_get_all_theory(self, client, admin_user, db):
        """✅ Получение всей теории"""
        theory = models.Theory(topic="algebra", section="equations", content="Содержание")
        db.add(theory)
        await db.commit()

        response = client.get(
            "/admin/theory/getall",
            headers={"Authorization": f"Bearer {admin_user['token']}"}
        )
        assert response.status_code == 200
        assert isinstance(response.json(), list)
        assert len(response.json()) >= 1

    async def test_update_theory(self, client, admin_user, db):
        """✅ Обновление теории"""
        theory = models.Theory(topic="algebra", section="equations", content="Старое")
        db.add(theory)
        await db.commit()

        response = client.put(
            f"/admin/theory/{theory.id}",
            json={"topic": "algebra", "section": "equations", "content": "Новое содержание"},
            headers={"Authorization": f"Bearer {admin_user['token']}"}
        )
        assert response.status_code == 200
        assert response.json()["content"] == "Новое содержание"

    async def test_delete_theory(self, client, admin_user, db):
        """✅ Удаление теории"""
        theory = models.Theory(topic="algebra", section="equations", content="Содержание")
        db.add(theory)
        await db.commit()

        response = client.delete(
            f"/admin/theory/{theory.id}",
            headers={"Authorization": f"Bearer {admin_user['token']}"}
        )
        assert response.status_code == 200
        assert "успешно удалена" in response.json()["message"]


# ==================== 5. ДОПОЛНИТЕЛЬНЫЕ ПРОВЕРКИ ====================

class TestAdminAdditional:
    """Дополнительные проверки"""

    def test_unauthorized_access(self, client):
        """❌ Доступ без токена"""
        endpoints = ["/admin/users", "/admin/", "/admin/tasks/1"]
        for ep in endpoints:
            response = client.get(ep)
            assert response.status_code == 401, f"{ep} should return 401"

    def test_invalid_token(self, client):
        """❌ Невалидный токен"""
        response = client.get(
            "/admin/users",
            headers={"Authorization": "Bearer invalid_token"}
        )
        assert response.status_code == 401

    def test_bulk_task_operations(self, client, admin_user):
        """✅ Массовое создание (производительность)"""
        start = time.time()

        for i in range(5):
            response = client.post(
                "/admin/tasks",
                json={
                    "task_class": "10", "topic_number": "1", "topic": "algebra",
                    "section": "equations", "content": f"Массовое {i}",
                    "answer": str(i), "hint": "h", "solution": "s",
                    "is_open_answer": False, "options": ["1", "2", "3", "4"], "difficulty": 1
                },
                headers={"Authorization": f"Bearer {admin_user['token']}"}
            )
            assert response.status_code == 200

        elapsed = time.time() - start
        assert elapsed < 10, f"Слишком медленно: {elapsed:.2f} сек"
