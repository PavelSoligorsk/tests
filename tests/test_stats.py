"""
📊 ТЕСТЫ СТАТИСТИКИ
Личная статистика студента, просмотр учителем/админом,
фильтрация по периодам, защита доступа.
"""

import pytest
import pytest_asyncio
import core.models as models


# ==================== ФИКСТУРЫ ДЛЯ СТАТИСТИКИ ====================

@pytest.fixture
def sample_task2(client, admin_user):
    """Создаёт второе задание (открытый ответ)"""
    response = client.post(
        "/admin/tasks",
        json={
            "task_class": "10", "topic_number": "2",
            "topic": "geometry", "section": "trigonometry",
            "content": "Найдите $\\sin 30^\\circ$",
            "answer": "0.5", "hint": "Таблица значений",
            "solution": "$$\\sin 30^\\circ = 0.5$$",
            "is_open_answer": True, "options": None, "difficulty": 3
        },
        headers={"Authorization": f"Bearer {admin_user['token']}"}
    )
    return response.json()["id"]


@pytest_asyncio.fixture
async def completed_test(client, db, admin_user, teacher_user, student_user, sample_task, sample_task2):
    """Создаёт тест, который студент уже прошёл"""
    link = models.TeacherStudent(teacher_id=teacher_user["id"], student_id=student_user["id"])
    db.add(link)
    await db.commit()

    test_response = client.post(
        "/teacher/tests",
        json={"title": "Тест для статистики", "target_class": "10", "target_topic": "1",
              "is_autocompile": False, "task_ids": [sample_task, sample_task2]},
        headers={"Authorization": f"Bearer {teacher_user['token']}"}
    )
    test = test_response.json()

    client.post(f"/student/tests/{test['id']}/submit",
                json=[{"task_id": sample_task, "user_answer": "2"},      # правильно
                      {"task_id": sample_task2, "user_answer": "wrong"}], # неправильно
                headers={"Authorization": f"Bearer {student_user['token']}"})

    return test


# ==================== 1. ЛИЧНАЯ СТАТИСТИКА СТУДЕНТА ====================

class TestMyStats:
    """Тесты личной статистики студента"""

    def test_get_my_period_stats(self, client, student_user, completed_test):
        """✅ Статистика за месяц"""
        response = client.get(
            "/stats/me/period?period=month",
            headers={"Authorization": f"Bearer {student_user['token']}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["period"] == "month"
        assert data["user_id"] == student_user["id"]
        assert data["total_tests"] >= 1
        assert "avg_score" in data
        assert "daily_stats" in data

    def test_get_my_period_stats_week(self, client, student_user, completed_test):
        """✅ Статистика за неделю"""
        response = client.get(
            "/stats/me/period?period=week",
            headers={"Authorization": f"Bearer {student_user['token']}"}
        )
        assert response.status_code == 200
        assert response.json()["period"] == "week"

    def test_get_my_period_stats_all(self, client, student_user, completed_test):
        """✅ Статистика за всё время"""
        response = client.get(
            "/stats/me/period?period=all",
            headers={"Authorization": f"Bearer {student_user['token']}"}
        )
        assert response.status_code == 200
        assert response.json()["start_date"] is None

    def test_get_my_topic_stats(self, client, student_user, completed_test):
        """✅ Статистика по темам"""
        response = client.get(
            "/stats/me/topics?period=all",
            headers={"Authorization": f"Bearer {student_user['token']}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "topics" in data
        assert "strongest_topic" in data or data.get("strongest_topic") is None
        assert "weakest_topic" in data or data.get("weakest_topic") is None

    def test_get_my_difficulty_stats(self, client, student_user, completed_test):
        """✅ Статистика по сложности"""
        response = client.get(
            "/stats/me/difficulty?period=all",
            headers={"Authorization": f"Bearer {student_user['token']}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "difficulties" in data
        assert isinstance(data["difficulties"], list)

    def test_get_my_full_stats(self, client, student_user, completed_test):
        """✅ Полная статистика"""
        response = client.get(
            "/stats/me/full?period=month",
            headers={"Authorization": f"Bearer {student_user['token']}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "period" in data
        assert "topics" in data
        assert "difficulties" in data

    def test_get_my_stats_empty(self, client, student2_user):
        """✅ Статистика для студента без тестов"""
        response = client.get(
            "/stats/me/period?period=all",
            headers={"Authorization": f"Bearer {student2_user['token']}"}
        )
        assert response.status_code == 200
        assert response.json()["total_tests"] == 0

    def test_invalid_period(self, client, student_user):
        """❌ Неверный период"""
        response = client.get(
            "/stats/me/period?period=invalid",
            headers={"Authorization": f"Bearer {student_user['token']}"}
        )
        assert response.status_code == 400

    def test_my_stats_without_auth(self, client):
        """❌ Статистика без авторизации"""
        response = client.get("/stats/me/period")
        assert response.status_code == 401


# ==================== 2. СТАТИСТИКА ДЛЯ УЧИТЕЛЯ ====================

class TestTeacherViewStats:
    """Тесты просмотра статистики учеников учителем"""

    def test_teacher_can_view_linked_student(self, client, teacher_user, student_user, completed_test):
        """✅ Учитель видит статистику своего ученика"""
        response = client.get(
            f"/stats/user/{student_user['id']}/period?period=all",
            headers={"Authorization": f"Bearer {teacher_user['token']}"}
        )
        assert response.status_code == 200
        assert response.json()["user_id"] == student_user["id"]

    def test_teacher_cannot_view_foreign_student(self, client, teacher_user, student2_user, db):
        """❌ Учитель не видит статистику чужого ученика"""
        response = client.get(
            f"/stats/user/{student2_user['id']}/period?period=all",
            headers={"Authorization": f"Bearer {teacher_user['token']}"}
        )
        assert response.status_code == 403

    def test_teacher_view_student_topics(self, client, teacher_user, student_user, completed_test):
        """✅ Учитель видит статистику по темам ученика"""
        response = client.get(
            f"/stats/user/{student_user['id']}/topics?period=all",
            headers={"Authorization": f"Bearer {teacher_user['token']}"}
        )
        assert response.status_code == 200
        assert "topics" in response.json()

    def test_teacher_view_student_difficulty(self, client, teacher_user, student_user, completed_test):
        """✅ Учитель видит статистику по сложности ученика"""
        response = client.get(
            f"/stats/user/{student_user['id']}/difficulty?period=all",
            headers={"Authorization": f"Bearer {teacher_user['token']}"}
        )
        assert response.status_code == 200
        assert "difficulties" in response.json()

    def test_teacher_view_student_full(self, client, teacher_user, student_user, completed_test):
        """✅ Учитель видит полную статистику ученика"""
        response = client.get(
            f"/stats/user/{student_user['id']}/full?period=month",
            headers={"Authorization": f"Bearer {teacher_user['token']}"}
        )
        assert response.status_code == 200
        assert "period" in response.json()
        assert "topics" in response.json()
        assert "difficulties" in response.json()


# ==================== 3. СТАТИСТИКА ДЛЯ АДМИНА ====================

class TestAdminViewStats:
    """Тесты просмотра статистики админом"""

    def test_admin_can_view_any_student(self, client, admin_user, student_user, completed_test):
        """✅ Админ видит статистику любого студента"""
        response = client.get(
            f"/stats/user/{student_user['id']}/period?period=all",
            headers={"Authorization": f"Bearer {admin_user['token']}"}
        )
        assert response.status_code == 200

    def test_admin_can_view_any_student_topics(self, client, admin_user, student_user, completed_test):
        """✅ Админ видит статистику по темам любого студента"""
        response = client.get(
            f"/stats/user/{student_user['id']}/topics?period=all",
            headers={"Authorization": f"Bearer {admin_user['token']}"}
        )
        assert response.status_code == 200

    def test_admin_can_view_any_student_full(self, client, admin_user, student_user, completed_test):
        """✅ Админ видит полную статистику любого студента"""
        response = client.get(
            f"/stats/user/{student_user['id']}/full?period=all",
            headers={"Authorization": f"Bearer {admin_user['token']}"}
        )
        assert response.status_code == 200


# ==================== 4. ПРОВЕРКА ДАННЫХ ====================

class TestStatsDataValidation:
    """Проверка корректности данных статистики"""

    def test_stats_after_single_submission(self, client, student_user, completed_test):
        """✅ Один пройденный тест — корректные данные"""
        response = client.get(
            "/stats/me/period?period=all",
            headers={"Authorization": f"Bearer {student_user['token']}"}
        )
        data = response.json()
        assert data["total_tests"] == 1
        assert data["total_tasks"] == 2
        assert data["correct_tasks"] == 1

    def test_stats_after_multiple_submissions(self, client, student_user, completed_test):
        """✅ Несколько попыток — данные агрегируются"""
        client.post(f"/student/tests/{completed_test['id']}/submit",
                    json=[{"task_id": completed_test["tasks"][0]["id"], "user_answer": "2"},
                          {"task_id": completed_test["tasks"][1]["id"], "user_answer": "0.5"}],
                    headers={"Authorization": f"Bearer {student_user['token']}"})

        response = client.get(
            "/stats/me/period?period=all",
            headers={"Authorization": f"Bearer {student_user['token']}"}
        )
        data = response.json()
        assert data["total_tests"] == 2
        assert data["total_tasks"] == 2

    def test_daily_stats_present(self, client, student_user, completed_test):
        """✅ Дневная статистика присутствует"""
        response = client.get(
            "/stats/me/period?period=week",
            headers={"Authorization": f"Bearer {student_user['token']}"}
        )
        data = response.json()
        assert "daily_stats" in data
        assert len(data["daily_stats"]) >= 1

    def test_streak_after_submission(self, client, student_user, completed_test):
        """✅ Серия дней после прохождения теста"""
        response = client.get(
            "/stats/me/period?period=week",
            headers={"Authorization": f"Bearer {student_user['token']}"}
        )
        data = response.json()
        assert "streak_days" in data
        assert data["streak_days"] >= 0

    def test_scores_in_range(self, client, student_user, completed_test):
        """✅ Баллы в допустимом диапазоне"""
        response = client.get(
            "/stats/me/period?period=all",
            headers={"Authorization": f"Bearer {student_user['token']}"}
        )
        data = response.json()
        assert 0 <= data["avg_score"] <= 100
        assert 0 <= data["best_score"] <= 100
        assert 0 <= data["worst_score"] <= 100
        assert data["best_score"] >= data["worst_score"]


# ==================== 5. ЗАЩИТА ДОСТУПА ====================

class TestStatsSecurity:
    """Тесты безопасности статистики"""

    def test_student_cannot_view_other_student(self, client, student_user, student2_user, completed_test):
        """❌ Студент не может смотреть статистику другого студента"""
        response = client.get(
            f"/stats/user/{student2_user['id']}/period?period=all",
            headers={"Authorization": f"Bearer {student_user['token']}"}
        )
        assert response.status_code == 403

    def test_teacher_cannot_view_nonexistent_student(self, client, teacher_user):
        """❌ Учитель не может смотреть несуществующего студента"""
        response = client.get(
            "/stats/user/99999/period?period=all",
            headers={"Authorization": f"Bearer {teacher_user['token']}"}
        )
        assert response.status_code == 403

    def test_stats_without_auth(self, client, student_user):
        """❌ Статистика без авторизации"""
        endpoints = [
            "/stats/me/period",
            "/stats/me/topics",
            "/stats/me/difficulty",
            f"/stats/user/{student_user['id']}/period",
        ]
        for ep in endpoints:
            response = client.get(ep)
            assert response.status_code == 401, f"{ep} should return 401"
