"""
Statistics tests: personal stats, teacher/admin views, filtering, and data validation.
"""

from typing import Any

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

import core.models as models
from tests.conftest import auth_header


# ==================== FIXTURES ====================


@pytest.fixture
def sample_task2(client: TestClient, admin_user: dict) -> int:
    """Create a second task (open-answer)."""
    resp = client.post(
        "/admin/tasks",
        json={
            "task_class": "10",
            "topic_number": "2",
            "topic": "geometry",
            "section": "trigonometry",
            "content": r"Find $\sin 30^\circ$",
            "answer": "0.5",
            "hint": "Values table",
            "solution": r"$$\sin 30^\circ = 0.5$$",
            "is_open_answer": True,
            "options": None,
            "difficulty": 3,
        },
        headers=auth_header(admin_user),
    )
    return resp.json()["id"]


@pytest_asyncio.fixture
async def completed_test(
    client: TestClient,
    db: AsyncSession,
    admin_user: dict,
    teacher_user: dict,
    student_user: dict,
    sample_task: int,
    sample_task2: int,
) -> dict[str, Any]:
    """Create a test that the student has already completed."""
    link = models.TeacherStudent(teacher_id=teacher_user["id"], student_id=student_user["id"])
    db.add(link)
    await db.commit()

    test_resp = client.post(
        "/teacher/tests",
        json={
            "title": "Stats Test",
            "target_class": "10",
            "target_topic": "1",
            "is_autocompile": False,
            "task_ids": [sample_task, sample_task2],
        },
        headers=auth_header(teacher_user),
    )
    test = test_resp.json()

    client.post(
        f"/student/tests/{test['id']}/submit",
        json=[
            {"task_id": sample_task, "user_answer": "2"},
            {"task_id": sample_task2, "user_answer": "wrong"},
        ],
        headers=auth_header(student_user),
    )

    return test


# ==================== 1. PERSONAL STATS ====================


class TestMyStats:
    """Tests for student's personal statistics."""

    def test_get_my_period_stats_month(self, client: TestClient, student_user: dict, completed_test: dict):
        """Monthly statistics."""
        resp = client.get("/stats/me/period?period=month", headers=auth_header(student_user))
        assert resp.status_code == 200
        data = resp.json()
        assert data["period"] == "month"
        assert data["user_id"] == student_user["id"]
        assert data["total_tests"] >= 1
        assert "avg_score" in data
        assert "daily_stats" in data

    def test_get_my_period_stats_week(self, client: TestClient, student_user: dict, completed_test: dict):
        """Weekly statistics."""
        resp = client.get("/stats/me/period?period=week", headers=auth_header(student_user))
        assert resp.status_code == 200
        assert resp.json()["period"] == "week"

    def test_get_my_period_stats_all(self, client: TestClient, student_user: dict, completed_test: dict):
        """All-time statistics."""
        resp = client.get("/stats/me/period?period=all", headers=auth_header(student_user))
        assert resp.status_code == 200
        assert resp.json()["start_date"] is None

    def test_get_my_topic_stats(self, client: TestClient, student_user: dict, completed_test: dict):
        """Topic statistics."""
        resp = client.get("/stats/me/topics?period=all", headers=auth_header(student_user))
        assert resp.status_code == 200
        data = resp.json()
        assert "topics" in data
        assert "strongest_topic" in data or data.get("strongest_topic") is None
        assert "weakest_topic" in data or data.get("weakest_topic") is None

    def test_get_my_difficulty_stats(self, client: TestClient, student_user: dict, completed_test: dict):
        """Difficulty statistics."""
        resp = client.get("/stats/me/difficulty?period=all", headers=auth_header(student_user))
        assert resp.status_code == 200
        data = resp.json()
        assert "difficulties" in data
        assert isinstance(data["difficulties"], list)

    def test_get_my_full_stats(self, client: TestClient, student_user: dict, completed_test: dict):
        """Full statistics."""
        resp = client.get("/stats/me/full?period=month", headers=auth_header(student_user))
        assert resp.status_code == 200
        data = resp.json()
        assert "period" in data
        assert "topics" in data
        assert "difficulties" in data

    def test_get_my_stats_empty(self, client: TestClient, student2_user: dict):
        """Statistics for a student with no tests."""
        resp = client.get("/stats/me/period?period=all", headers=auth_header(student2_user))
        assert resp.status_code == 200
        assert resp.json()["total_tests"] == 0

    def test_invalid_period(self, client: TestClient, student_user: dict):
        """Invalid period returns 400."""
        resp = client.get("/stats/me/period?period=invalid", headers=auth_header(student_user))
        assert resp.status_code == 400

    def test_my_stats_without_auth(self, client: TestClient):
        """Statistics without auth returns 401."""
        resp = client.get("/stats/me/period")
        assert resp.status_code == 401


# ==================== 2. TEACHER VIEW ====================


class TestTeacherViewStats:
    """Tests for teacher viewing student stats."""

    def test_teacher_can_view_linked_student(
        self, client: TestClient, teacher_user: dict, student_user: dict, completed_test: dict
    ):
        """Teacher can see linked student's stats."""
        resp = client.get(
            f"/stats/user/{student_user['id']}/period?period=all",
            headers=auth_header(teacher_user),
        )
        assert resp.status_code == 200
        assert resp.json()["user_id"] == student_user["id"]

    def test_teacher_cannot_view_foreign_student(
        self, client: TestClient, teacher_user: dict, student2_user: dict
    ):
        """Teacher cannot see unlinked student's stats."""
        resp = client.get(
            f"/stats/user/{student2_user['id']}/period?period=all",
            headers=auth_header(teacher_user),
        )
        assert resp.status_code == 403

    def test_teacher_view_student_topics(
        self, client: TestClient, teacher_user: dict, student_user: dict, completed_test: dict
    ):
        """Teacher sees student's topic stats."""
        resp = client.get(
            f"/stats/user/{student_user['id']}/topics?period=all",
            headers=auth_header(teacher_user),
        )
        assert resp.status_code == 200
        assert "topics" in resp.json()

    def test_teacher_view_student_difficulty(
        self, client: TestClient, teacher_user: dict, student_user: dict, completed_test: dict
    ):
        """Teacher sees student's difficulty stats."""
        resp = client.get(
            f"/stats/user/{student_user['id']}/difficulty?period=all",
            headers=auth_header(teacher_user),
        )
        assert resp.status_code == 200
        assert "difficulties" in resp.json()

    def test_teacher_view_student_full(
        self, client: TestClient, teacher_user: dict, student_user: dict, completed_test: dict
    ):
        """Teacher sees full student stats."""
        resp = client.get(
            f"/stats/user/{student_user['id']}/full?period=month",
            headers=auth_header(teacher_user),
        )
        assert resp.status_code == 200
        assert "period" in resp.json()
        assert "topics" in resp.json()
        assert "difficulties" in resp.json()


# ==================== 3. ADMIN VIEW ====================


class TestAdminViewStats:
    """Tests for admin viewing any student's stats."""

    def test_admin_can_view_any_student(
        self, client: TestClient, admin_user: dict, student_user: dict, completed_test: dict
    ):
        """Admin can see any student's stats."""
        resp = client.get(
            f"/stats/user/{student_user['id']}/period?period=all",
            headers=auth_header(admin_user),
        )
        assert resp.status_code == 200

    def test_admin_can_view_any_student_topics(
        self, client: TestClient, admin_user: dict, student_user: dict, completed_test: dict
    ):
        """Admin sees topic stats for any student."""
        resp = client.get(
            f"/stats/user/{student_user['id']}/topics?period=all",
            headers=auth_header(admin_user),
        )
        assert resp.status_code == 200

    def test_admin_can_view_any_student_full(
        self, client: TestClient, admin_user: dict, student_user: dict, completed_test: dict
    ):
        """Admin sees full stats for any student."""
        resp = client.get(
            f"/stats/user/{student_user['id']}/full?period=all",
            headers=auth_header(admin_user),
        )
        assert resp.status_code == 200


# ==================== 4. DATA VALIDATION ====================


class TestStatsDataValidation:
    """Verify correctness of statistics data."""

    def test_stats_after_single_submission(
        self, client: TestClient, student_user: dict, completed_test: dict
    ):
        """Single completed test produces correct data."""
        resp = client.get("/stats/me/period?period=all", headers=auth_header(student_user))
        data = resp.json()
        assert data["total_tests"] == 1
        assert data["total_tasks"] == 2
        assert data["correct_tasks"] == 1

    def test_stats_after_multiple_submissions(
        self, client: TestClient, student_user: dict, completed_test: dict
    ):
        """Multiple attempts are aggregated."""
        client.post(
            f"/student/tests/{completed_test['id']}/submit",
            json=[
                {"task_id": completed_test["tasks"][0]["id"], "user_answer": "2"},
                {"task_id": completed_test["tasks"][1]["id"], "user_answer": "0.5"},
            ],
            headers=auth_header(student_user),
        )

        resp = client.get("/stats/me/period?period=all", headers=auth_header(student_user))
        data = resp.json()
        assert data["total_tests"] == 2
        assert data["total_tasks"] == 2

    def test_daily_stats_present(self, client: TestClient, student_user: dict, completed_test: dict):
        """Daily stats are present."""
        resp = client.get("/stats/me/period?period=week", headers=auth_header(student_user))
        data = resp.json()
        assert "daily_stats" in data
        assert len(data["daily_stats"]) >= 1

    def test_streak_after_submission(self, client: TestClient, student_user: dict, completed_test: dict):
        """Streak days after completing a test."""
        resp = client.get("/stats/me/period?period=week", headers=auth_header(student_user))
        data = resp.json()
        assert "streak_days" in data
        assert data["streak_days"] >= 0

    def test_scores_in_range(self, client: TestClient, student_user: dict, completed_test: dict):
        """Scores are within [0, 100]."""
        resp = client.get("/stats/me/period?period=all", headers=auth_header(student_user))
        data = resp.json()
        assert 0 <= data["avg_score"] <= 100
        assert 0 <= data["best_score"] <= 100
        assert 0 <= data["worst_score"] <= 100
        assert data["best_score"] >= data["worst_score"]


# ==================== 5. SECURITY ====================


class TestStatsSecurity:
    """Security tests for statistics."""

    def test_student_cannot_view_other_student(
        self, client: TestClient, student_user: dict, student2_user: dict, completed_test: dict
    ):
        """Student cannot view another student's stats."""
        resp = client.get(
            f"/stats/user/{student2_user['id']}/period?period=all",
            headers=auth_header(student_user),
        )
        assert resp.status_code == 403

    def test_teacher_cannot_view_nonexistent_student(self, client: TestClient, teacher_user: dict):
        """Teacher cannot view non-existent student."""
        resp = client.get(
            "/stats/user/99999/period?period=all",
            headers=auth_header(teacher_user),
        )
        assert resp.status_code == 403

    def test_stats_without_auth(self, client: TestClient, student_user: dict):
        """All stats endpoints require auth."""
        endpoints = [
            "/stats/me/period",
            "/stats/me/topics",
            "/stats/me/difficulty",
            f"/stats/user/{student_user['id']}/period",
        ]
        for ep in endpoints:
            resp = client.get(ep)
            assert resp.status_code == 401, f"{ep} should return 401"