"""
👨‍🏫 ТЕСТЫ УЧИТЕЛЯ
CRUD тестов, заданий, групп, студентов, назначения полный цикл.
"""

import pytest
import pytest_asyncio
from sqlalchemy import select
import core.models as models


# ==================== 1. ТЕСТЫ ====================

class TestTeacherTests:
    """CRUD тестов"""

    def test_get_tests_empty(self, client, teacher_user):
        """✅ Пустой список тестов"""
        response = client.get(
            "/teacher/tests",
            headers={"Authorization": f"Bearer {teacher_user['token']}"}
        )
        assert response.status_code == 200
        assert response.json() == []

    def test_create_test(self, client, teacher_user, sample_task):
        """✅ Создание теста"""
        response = client.post(
            "/teacher/tests",
            json={
                "title": "Мой первый тест",
                "target_class": "10",
                "target_topic": "1",
                "is_autocompile": False,
                "task_ids": [sample_task]
            },
            headers={"Authorization": f"Bearer {teacher_user['token']}"}
        )
        assert response.status_code == 200
        assert response.json()["title"] == "Мой первый тест"
        assert "id" in response.json()

    def test_create_test_without_tasks(self, client, teacher_user):
        """✅ Создание теста без заданий"""
        response = client.post(
            "/teacher/tests",
            json={
                "title": "Пустой тест",
                "target_class": "10",
                "target_topic": "1",
                "is_autocompile": False,
                "task_ids": []
            },
            headers={"Authorization": f"Bearer {teacher_user['token']}"}
        )
        assert response.status_code == 200

    def test_create_test_as_student(self, client, student_user):
        """❌ Студент не может создать тест"""
        response = client.post(
            "/teacher/tests",
            json={"title": "hack", "target_class": "10", "target_topic": "1",
                  "is_autocompile": False, "task_ids": []},
            headers={"Authorization": f"Bearer {student_user['token']}"}
        )
        assert response.status_code == 403

    def test_get_my_tests(self, client, teacher_user, sample_task):
        """✅ Получение своих тестов"""
        client.post("/teacher/tests", json={
            "title": "Тест 1", "target_class": "10", "target_topic": "1",
            "is_autocompile": False, "task_ids": [sample_task]
        }, headers={"Authorization": f"Bearer {teacher_user['token']}"})

        response = client.get(
            "/teacher/tests",
            headers={"Authorization": f"Bearer {teacher_user['token']}"}
        )
        assert response.status_code == 200
        assert len(response.json()) == 1

    async def test_cant_see_other_teachers_tests(self, client, db, teacher_user, sample_task):
        """🛡️ Учитель не видит чужие тесты"""
        # Создаём другого учителя
        allowed2 = models.AllowedEmail(email="teacher2@test.com")
        db.add(allowed2)
        await db.commit()

        client.post("/register", json={
            "username": "teacher2@test.com", "password": "Teacher123!",
            "first_name": "Teacher", "last_name": "Two"
        })
        teacher2 = (await db.execute(select(models.User).where(models.User.username == "teacher2@test.com"))).scalars().first()
        teacher2.role = "teacher"
        await db.commit()

        login2 = client.post("/login", data={"username": "teacher2@test.com", "password": "Teacher123!"})
        teacher2_token = login2.json()["access_token"]

        # teacher2 создаёт тест
        client.post("/teacher/tests", json={
            "title": "Тест учителя 2", "target_class": "10", "target_topic": "1",
            "is_autocompile": False, "task_ids": [sample_task]
        }, headers={"Authorization": f"Bearer {teacher2_token}"})

        # Первый учитель видит только свой
        response = client.get(
            "/teacher/tests",
            headers={"Authorization": f"Bearer {teacher_user['token']}"}
        )
        assert len(response.json()) == 0

    def test_update_test(self, client, teacher_user, sample_task):
        """✅ Обновление теста"""
        test = client.post("/teacher/tests", json={
            "title": "Старый", "target_class": "10", "target_topic": "1",
            "is_autocompile": False, "task_ids": [sample_task]
        }, headers={"Authorization": f"Bearer {teacher_user['token']}"}).json()

        response = client.put(
            f"/teacher/tests/{test['id']}",
            json={"title": "Новый", "target_class": "11", "target_topic": "2",
                  "is_autocompile": True, "task_ids": []},
            headers={"Authorization": f"Bearer {teacher_user['token']}"}
        )
        assert response.status_code == 200
        assert response.json()["title"] == "Новый"

    def test_delete_test(self, client, teacher_user, sample_task):
        """✅ Удаление теста"""
        test = client.post("/teacher/tests", json={
            "title": "На удаление", "target_class": "10", "target_topic": "1",
            "is_autocompile": False, "task_ids": [sample_task]
        }, headers={"Authorization": f"Bearer {teacher_user['token']}"}).json()

        response = client.delete(
            f"/teacher/tests/{test['id']}",
            headers={"Authorization": f"Bearer {teacher_user['token']}"}
        )
        assert response.status_code == 200

        get_resp = client.get(
            f"/teacher/tests/{test['id']}",
            headers={"Authorization": f"Bearer {teacher_user['token']}"}
        )
        assert get_resp.status_code == 404

    async def test_cant_delete_others_test(self, client, db, teacher_user, sample_task):
        """🛡️ Нельзя удалить чужой тест"""
        allowed2 = models.AllowedEmail(email="teacher3@test.com")
        db.add(allowed2)
        await db.commit()

        client.post("/register", json={
            "username": "teacher3@test.com", "password": "Teacher123!",
            "first_name": "T3", "last_name": "Test"
        })
        teacher2 = (await db.execute(select(models.User).where(models.User.username == "teacher3@test.com"))).scalars().first()
        teacher2.role = "teacher"
        await db.commit()

        login2 = client.post("/login", data={"username": "teacher3@test.com", "password": "Teacher123!"})
        teacher2_token = login2.json()["access_token"]

        test2 = client.post("/teacher/tests", json={
            "title": "Чужой тест", "target_class": "10", "target_topic": "1",
            "is_autocompile": False, "task_ids": [sample_task]
        }, headers={"Authorization": f"Bearer {teacher2_token}"}).json()

        response = client.delete(
            f"/teacher/tests/{test2['id']}",
            headers={"Authorization": f"Bearer {teacher_user['token']}"}
        )
        assert response.status_code == 403

    def test_get_test_detail(self, client, teacher_user, sample_task):
        """✅ Детали теста"""
        test = client.post("/teacher/tests", json={
            "title": "Детали", "target_class": "10", "target_topic": "1",
            "is_autocompile": False, "task_ids": [sample_task]
        }, headers={"Authorization": f"Bearer {teacher_user['token']}"}).json()

        response = client.get(
            f"/teacher/tests/{test['id']}",
            headers={"Authorization": f"Bearer {teacher_user['token']}"}
        )
        assert response.status_code == 200
        assert response.json()["id"] == test["id"]


# ==================== 2. ЗАДАНИЯ (БАНК ЗАДАНИЙ) ====================

class TestTeacherTasks:
    """Тесты банка заданий для учителя"""

    def test_get_all_tasks(self, client, teacher_user, sample_task):
        """✅ Получение всех заданий"""
        response = client.get(
            "/teacher/tasks",
            headers={"Authorization": f"Bearer {teacher_user['token']}"}
        )
        assert response.status_code == 200
        assert len(response.json()) >= 1

    def test_get_tasks_with_filter(self, client, teacher_user, sample_task):
        """✅ Фильтрация заданий по классу"""
        response = client.get(
            "/teacher/tasks?task_class=10",
            headers={"Authorization": f"Bearer {teacher_user['token']}"}
        )
        assert response.status_code == 200

    def test_get_single_task(self, client, teacher_user, sample_task):
        """✅ Получение задания по ID"""
        response = client.get(
            f"/teacher/tasks/{sample_task}",
            headers={"Authorization": f"Bearer {teacher_user['token']}"}
        )
        assert response.status_code == 200

    def test_get_tasks_grouped(self, client, teacher_user, sample_task):
        """✅ Получение сгруппированных заданий"""
        response = client.get(
            "/teacher/tasks-grouped",
            headers={"Authorization": f"Bearer {teacher_user['token']}"}
        )
        assert response.status_code == 200
        assert "grouped" in response.json()
        assert "total_tasks" in response.json()

    def test_get_tasks_meta(self, client, teacher_user, sample_task):
        """✅ Мета-информация о заданиях"""
        response = client.get(
            "/teacher/tasks-meta",
            headers={"Authorization": f"Bearer {teacher_user['token']}"}
        )
        assert response.status_code == 200

    def test_get_tasks_by_class_and_topic(self, client, teacher_user, sample_task):
        """✅ Задания по классу и теме"""
        response = client.get(
            "/teacher/tasks/by-class-topic?task_class=10&topic_number=1",
            headers={"Authorization": f"Bearer {teacher_user['token']}"}
        )
        assert response.status_code == 200


# ==================== 3. ГРУППЫ ====================

class TestTeacherGroups:
    """Полный CRUD групп"""

    def test_create_group(self, client, teacher_user):
        """✅ Создание группы"""
        response = client.post(
            "/teacher/groups/",
            json={"name": "10A", "description": "Лучший класс"},
            headers={"Authorization": f"Bearer {teacher_user['token']}"}
        )
        assert response.status_code == 200
        assert response.json()["name"] == "10A"

    def test_create_group_without_name(self, client, teacher_user):
        """❌ Группа без имени"""
        response = client.post(
            "/teacher/groups/",
            json={"description": "Без имени"},
            headers={"Authorization": f"Bearer {teacher_user['token']}"}
        )
        assert response.status_code == 400

    def test_get_my_groups_empty(self, client, teacher_user):
        """✅ Пустой список групп"""
        response = client.get(
            "/teacher/groups/",
            headers={"Authorization": f"Bearer {teacher_user['token']}"}
        )
        assert response.status_code == 200
        assert response.json() == []

    def test_get_my_groups(self, client, teacher_user):
        """✅ Список групп"""
        client.post("/teacher/groups/", json={"name": "10A"},
                    headers={"Authorization": f"Bearer {teacher_user['token']}"})
        response = client.get("/teacher/groups/",
                              headers={"Authorization": f"Bearer {teacher_user['token']}"})
        assert response.status_code == 200
        assert len(response.json()) == 1
        assert response.json()[0]["name"] == "10A"

    def test_update_group(self, client, teacher_user):
        """✅ Обновление группы"""
        group = client.post("/teacher/groups/", json={"name": "Старое"},
                           headers={"Authorization": f"Bearer {teacher_user['token']}"}).json()

        response = client.put(f"/teacher/groups/{group['id']}",
                             json={"name": "Новое", "description": "Обновлён"},
                             headers={"Authorization": f"Bearer {teacher_user['token']}"})
        assert response.status_code == 200
        assert response.json()["name"] == "Новое"

    def test_delete_group(self, client, teacher_user):
        """✅ Удаление группы"""
        group = client.post("/teacher/groups/", json={"name": "На удаление"},
                           headers={"Authorization": f"Bearer {teacher_user['token']}"}).json()

        response = client.delete(f"/teacher/groups/{group['id']}",
                                headers={"Authorization": f"Bearer {teacher_user['token']}"})
        assert response.status_code == 200

    async def test_cant_see_other_teacher_groups(self, client, db, teacher_user):
        """🛡️ Не видит чужие группы"""
        allowed2 = models.AllowedEmail(email="teachergrp@test.com")
        db.add(allowed2)
        await db.commit()

        client.post("/register", json={
            "username": "teachergrp@test.com", "password": "Teacher123!",
            "first_name": "T", "last_name": "Grp"
        })
        teacher2 = (await db.execute(select(models.User).where(models.User.username == "teachergrp@test.com"))).scalars().first()
        teacher2.role = "teacher"
        await db.commit()

        login2 = client.post("/login", data={"username": "teachergrp@test.com", "password": "Teacher123!"})
        teacher2_token = login2.json()["access_token"]

        client.post("/teacher/groups/", json={"name": "Чужая группа"},
                    headers={"Authorization": f"Bearer {teacher2_token}"})

        response = client.get("/teacher/groups/",
                              headers={"Authorization": f"Bearer {teacher_user['token']}"})
        assert len(response.json()) == 0

    def test_add_students_to_group(self, client, teacher_user, student_user, link_teacher_student):
        """✅ Добавление студентов в группу"""
        group = client.post("/teacher/groups/", json={"name": "Группа"},
                           headers={"Authorization": f"Bearer {teacher_user['token']}"}).json()

        response = client.post(f"/teacher/groups/{group['id']}/students",
                              json={"student_ids": [student_user["id"]]},
                              headers={"Authorization": f"Bearer {teacher_user['token']}"})
        assert response.status_code == 200
        assert response.json()["added"] == 1

    def test_remove_student_from_group(self, client, teacher_user, student_user, link_teacher_student):
        """✅ Удаление студента из группы"""
        group = client.post("/teacher/groups/", json={"name": "Группа2"},
                           headers={"Authorization": f"Bearer {teacher_user['token']}"}).json()
        client.post(f"/teacher/groups/{group['id']}/students",
                   json={"student_ids": [student_user["id"]]},
                   headers={"Authorization": f"Bearer {teacher_user['token']}"})

        response = client.delete(f"/teacher/groups/{group['id']}/students/{student_user['id']}",
                                headers={"Authorization": f"Bearer {teacher_user['token']}"})
        assert response.status_code == 200

    def test_get_group_students(self, client, teacher_user, student_user, link_teacher_student):
        """✅ Список студентов группы"""
        group = client.post("/teacher/groups/", json={"name": "Группа3"},
                           headers={"Authorization": f"Bearer {teacher_user['token']}"}).json()
        client.post(f"/teacher/groups/{group['id']}/students",
                   json={"student_ids": [student_user["id"]]},
                   headers={"Authorization": f"Bearer {teacher_user['token']}"})

        response = client.get(f"/teacher/groups/{group['id']}/students",
                             headers={"Authorization": f"Bearer {teacher_user['token']}"})
        assert response.status_code == 200
        assert len(response.json()) == 1
        assert response.json()[0]["id"] == student_user["id"]


# ==================== 4. СТУДЕНТЫ И НАЗНАЧЕНИЯ ====================

class TestTeacherStudents:
    """Тесты управления студентами и назначениями"""

    def test_get_my_students(self, client, teacher_user, link_teacher_student, student_user):
        """✅ Список студентов"""
        response = client.get(
            "/teacher/students",
            headers={"Authorization": f"Bearer {teacher_user['token']}"}
        )
        assert response.status_code == 200
        student_ids = [s["id"] for s in response.json()]
        assert student_user["id"] in student_ids

    def test_student_profile(self, client, teacher_user, link_teacher_student, student_user):
        """✅ Профиль студента"""
        response = client.get(
            f"/teacher/students-profile/{student_user['id']}",
            headers={"Authorization": f"Bearer {teacher_user['token']}"}
        )
        assert response.status_code == 200
        assert response.json()["user"]["id"] == student_user["id"]

    def test_assign_test(self, client, teacher_user, student_user, link_teacher_student, sample_task):
        """✅ Назначение теста студенту"""
        test = client.post("/teacher/tests", json={
            "title": "Назнач", "target_class": "10", "target_topic": "1",
            "is_autocompile": False, "task_ids": [sample_task]
        }, headers={"Authorization": f"Bearer {teacher_user['token']}"}).json()

        response = client.post("/teacher/assign-test", json={
            "test_id": test["id"], "user_ids": [student_user["id"]]
        }, headers={"Authorization": f"Bearer {teacher_user['token']}"})
        assert response.status_code == 200
        assert len(response.json()) == 1

    def test_assign_test_twice(self, client, teacher_user, student_user, link_teacher_student, sample_task):
        """🛡️ Повторное назначение — не дублируется"""
        test = client.post("/teacher/tests", json={
            "title": "Дубль", "target_class": "10", "target_topic": "1",
            "is_autocompile": False, "task_ids": [sample_task]
        }, headers={"Authorization": f"Bearer {teacher_user['token']}"}).json()

        client.post("/teacher/assign-test", json={"test_id": test["id"], "user_ids": [student_user["id"]]},
                    headers={"Authorization": f"Bearer {teacher_user['token']}"})
        response = client.post("/teacher/assign-test", json={"test_id": test["id"], "user_ids": [student_user["id"]]},
                              headers={"Authorization": f"Bearer {teacher_user['token']}"})
        assert len(response.json()) == 1  # по-прежнему одна запись

    def test_assign_test_to_group(self, client, teacher_user, student_user, link_teacher_student, sample_task):
        """✅ Назначение теста всей группе"""
        group = client.post("/teacher/groups/", json={"name": "Группа-тест"},
                           headers={"Authorization": f"Bearer {teacher_user['token']}"}).json()
        client.post(f"/teacher/groups/{group['id']}/students",
                   json={"student_ids": [student_user["id"]]},
                   headers={"Authorization": f"Bearer {teacher_user['token']}"})

        test = client.post("/teacher/tests", json={
            "title": "Для группы", "target_class": "10", "target_topic": "1",
            "is_autocompile": False, "task_ids": [sample_task]
        }, headers={"Authorization": f"Bearer {teacher_user['token']}"}).json()

        response = client.post("/teacher/assign-test-to-group", json={
            "group_id": group["id"], "test_id": test["id"]
        }, headers={"Authorization": f"Bearer {teacher_user['token']}"})
        assert response.status_code == 200
        assert response.json()["assigned_count"] == 1

    def test_get_test_assignments(self, client, teacher_user, student_user, link_teacher_student, sample_task):
        """✅ Назначения для теста"""
        test = client.post("/teacher/tests", json={
            "title": "Проверка", "target_class": "10", "target_topic": "1",
            "is_autocompile": False, "task_ids": [sample_task]
        }, headers={"Authorization": f"Bearer {teacher_user['token']}"}).json()
        client.post("/teacher/assign-test", json={"test_id": test["id"], "user_ids": [student_user["id"]]},
                    headers={"Authorization": f"Bearer {teacher_user['token']}"})

        response = client.get(f"/teacher/test/{test['id']}/assignments",
                             headers={"Authorization": f"Bearer {teacher_user['token']}"})
        assert response.status_code == 200
        assert len(response.json()) >= 1

    def test_get_student_assignments(self, client, teacher_user, student_user, link_teacher_student, sample_task):
        """✅ Назначения студента"""
        test = client.post("/teacher/tests", json={
            "title": "Студент", "target_class": "10", "target_topic": "1",
            "is_autocompile": False, "task_ids": [sample_task]
        }, headers={"Authorization": f"Bearer {teacher_user['token']}"}).json()
        client.post("/teacher/assign-test", json={"test_id": test["id"], "user_ids": [student_user["id"]]},
                    headers={"Authorization": f"Bearer {teacher_user['token']}"})

        response = client.get(f"/teacher/student/{student_user['id']}/assignments",
                             headers={"Authorization": f"Bearer {teacher_user['token']}"})
        assert response.status_code == 200
        assert len(response.json()) >= 1

    def test_delete_assignment(self, client, teacher_user, student_user, link_teacher_student, sample_task):
        """✅ Удаление назначения"""
        test = client.post("/teacher/tests", json={
            "title": "Удалить название", "target_class": "10", "target_topic": "1",
            "is_autocompile": False, "task_ids": [sample_task]
        }, headers={"Authorization": f"Bearer {teacher_user['token']}"}).json()
        resp = client.post("/teacher/assign-test", json={"test_id": test["id"], "user_ids": [student_user["id"]]},
                          headers={"Authorization": f"Bearer {teacher_user['token']}"})
        assignment_id = resp.json()[0]["id"] if isinstance(resp.json(), list) else \
                        resp.json()["id"]

        del_resp = client.delete(f"/teacher/assignments/{assignment_id}",
                                headers={"Authorization": f"Bearer {teacher_user['token']}"})
        assert del_resp.status_code == 200


# ==================== 5. РЕЗУЛЬТАТЫ ====================

class TestTeacherResults:
    """Тесты просмотра результатов"""

    def test_student_history_empty(self, client, teacher_user, student_user, link_teacher_student):
        """✅ Пустая история студента"""
        response = client.get(
            f"/teacher/students-history/{student_user['id']}",
            headers={"Authorization": f"Bearer {teacher_user['token']}"}
        )
        assert response.status_code == 200
        assert response.json() == []

    def test_student_history_after_submission(self, client, teacher_user, student_user, link_teacher_student, sample_task):
        """✅ История после прохождения теста"""
        test = client.post("/teacher/tests", json={
            "title": "Для истории", "target_class": "10", "target_topic": "1",
            "is_autocompile": False, "task_ids": [sample_task]
        }, headers={"Authorization": f"Bearer {teacher_user['token']}"}).json()

        client.post("/teacher/assign-test", json={"test_id": test["id"], "user_ids": [student_user["id"]]},
                    headers={"Authorization": f"Bearer {teacher_user['token']}"})

        client.post(f"/student/tests/{test['id']}/submit", json=[
            {"task_id": sample_task, "user_answer": "2"}
        ], headers={"Authorization": f"Bearer {student_user['token']}"})

        response = client.get(
            f"/teacher/students-history/{student_user['id']}",
            headers={"Authorization": f"Bearer {teacher_user['token']}"}
        )
        assert response.status_code == 200
        assert len(response.json()) == 1
        assert response.json()[0]["test_title"] == "Для истории"
