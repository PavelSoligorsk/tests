"""
Stats tests: period, topics, difficulty, full stats for /me and /user/{id},
plus access-control boundaries (student can't see others, teacher needs link).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

import core.models as models
from tests.conftest import auth_header


VALID_PERIODS = ("week", "month", "3months", "6months", "year", "all")


# ==================== 1. MY PERIOD STATS ====================


class TestMyPeriodStats:
    """GET /stats/me/period"""

    def test_empty_period_stats(
        self, client: TestClient, student_user: dict,
    ):
        """Stats are empty (all zeros) for a student with no results."""
        # --- Act ---
        resp = client.get(
            "/stats/me/period", params={"period": "all"},
            headers=auth_header(student_user),
        )
        # --- Assert ---
        assert resp.status_code == 200
        data = resp.json()
        assert data["period"] == "all"
        assert data["total_tests"] == 0
        assert data["total_tasks"] == 0
        assert data["correct_tasks"] == 0
        assert data["avg_score"] == 0.0
        assert data["streak_days"] == 0
        assert data["daily_stats"] == []

    def test_default_period_month(
        self, client: TestClient, student_user: dict,
    ):
        """Default period is 'month'."""
        resp = client.get(
            "/stats/me/period", headers=auth_header(student_user),
        )
        assert resp.status_code == 200
        assert resp.json()["period"] == "month"

    def test_every_valid_period(
        self, client: TestClient, student_user: dict,
    ):
        """All period values return 200."""
        for period in VALID_PERIODS:
            resp = client.get(
                "/stats/me/period", params={"period": period},
                headers=auth_header(student_user),
            )
            assert resp.status_code == 200, f"period={period} failed"

    def test_bad_period_returns_400(
        self, client: TestClient, student_user: dict,
    ):
        """Invalid period returns 400."""
        resp = client.get(
            "/stats/me/period", params={"period": "century"},
            headers=auth_header(student_user),
        )
        assert resp.status_code == 400

    def test_period_with_results(
        self, client: TestClient, student_user: dict, assigned_test: dict,
    ):
        """Stats after submitting a test have non-zero totals."""
        test = assigned_test
        # Submit one task
        client.post(
            f"/student/tests/{test['id']}/submit",
            json=[{"task_id": test["tasks"][0]["id"], "user_answer": "2"}],
            headers=auth_header(student_user),
        )
        # --- Act ---
        resp = client.get(
            "/stats/me/period", params={"period": "all"},
            headers=auth_header(student_user),
        )
        # --- Assert ---
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_tests"] >= 1
        assert data["total_tasks"] >= 1
        assert len(data["daily_stats"]) >= 1

    def test_period_without_auth(self, client: TestClient):
        """Without token returns 401."""
        resp = client.get("/stats/me/period")
        assert resp.status_code == 401


# ==================== 2. MY TOPICS STATS ====================


class TestMyTopicsStats:
    """GET /stats/me/topics"""

    def test_empty_topics(
        self, client: TestClient, student_user: dict,
    ):
        resp = client.get(
            "/stats/me/topics",
            headers=auth_header(student_user),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["topics"] == []
        assert data["strongest_topic"] is None
        assert data["weakest_topic"] is None

    def test_topics_with_results(
        self, client: TestClient, student_user: dict, assigned_test: dict,
    ):
        """After submitting a test, topic stats become non-empty."""
        test = assigned_test
        client.post(
            f"/student/tests/{test['id']}/submit",
            json=[{"task_id": test["tasks"][0]["id"], "user_answer": "2"}],
            headers=auth_header(student_user),
        )
        resp = client.get(
            "/stats/me/topics", params={"period": "all"},
            headers=auth_header(student_user),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["topics"]) >= 1
        # Each topic has mastery_percent and sections
        for topic in data["topics"]:
            assert "topic" in topic
            assert "mastery_percent" in topic
            assert "sections" in topic

    def test_topics_default_period(
        self, client: TestClient, student_user: dict,
    ):
        """Default period is 'all' for topics."""
        resp = client.get(
            "/stats/me/topics", headers=auth_header(student_user),
        )
        assert resp.status_code == 200
        assert resp.json()["period"] == "all"

    def test_topics_without_auth(self, client: TestClient):
        resp = client.get("/stats/me/topics")
        assert resp.status_code == 401


# ==================== 3. MY DIFFICULTY STATS ====================


class TestMyDifficultyStats:
    """GET /stats/me/difficulty"""

    def test_empty_difficulty(
        self, client: TestClient, student_user: dict,
    ):
        resp = client.get(
            "/stats/me/difficulty",
            headers=auth_header(student_user),
        )
        assert resp.status_code == 200
        assert resp.json()["difficulties"] == []

    def test_difficulty_with_results(
        self, client: TestClient, student_user: dict, assigned_test: dict,
    ):
        """After submitting a test, difficulty stats become non-empty."""
        test = assigned_test
        client.post(
            f"/student/tests/{test['id']}/submit",
            json=[{"task_id": test["tasks"][0]["id"], "user_answer": "2"}],
            headers=auth_header(student_user),
        )
        resp = client.get(
            "/stats/me/difficulty", params={"period": "all"},
            headers=auth_header(student_user),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["difficulties"]) >= 1
        for d in data["difficulties"]:
            assert "difficulty" in d
            assert "mastery_percent" in d

    def test_difficulty_without_auth(self, client: TestClient):
        resp = client.get("/stats/me/difficulty")
        assert resp.status_code == 401


# ==================== 4. FULL STATS ====================


class TestMyFullStats:
    """GET /stats/me/full"""

    def test_empty_full_stats(
        self, client: TestClient, student_user: dict,
    ):
        resp = client.get(
            "/stats/me/full",
            headers=auth_header(student_user),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "period" in data
        assert "topics" in data
        assert "difficulties" in data

    def test_full_with_results(
        self, client: TestClient, student_user: dict, assigned_test: dict,
    ):
        test = assigned_test
        client.post(
            f"/student/tests/{test['id']}/submit",
            json=[{"task_id": test["tasks"][0]["id"], "user_answer": "2"}],
            headers=auth_header(student_user),
        )
        resp = client.get(
            "/stats/me/full", params={"period": "all"},
            headers=auth_header(student_user),
        )
        assert resp.status_code == 200
        # Full stats aggregates all three
        data = resp.json()
        assert data["period"]["total_tests"] >= 1
        assert len(data["topics"]["topics"]) >= 1
        assert len(data["difficulties"]["difficulties"]) >= 1

    def test_full_without_auth(self, client: TestClient):
        resp = client.get("/stats/me/full")
        assert resp.status_code == 401


# ==================== 5. USER STATS (BY ID) — SELF ====================


class TestUserStatsSelf:
    """GET /stats/user/{id}/* — viewing own stats."""

    def test_own_period(
        self, client: TestClient, student_user: dict,
    ):
        resp = client.get(
            f"/stats/user/{student_user['id']}/period",
            headers=auth_header(student_user),
        )
        assert resp.status_code == 200
        assert resp.json()["user_id"] == student_user["id"]

    def test_own_topics(
        self, client: TestClient, student_user: dict,
    ):
        resp = client.get(
            f"/stats/user/{student_user['id']}/topics",
            headers=auth_header(student_user),
        )
        assert resp.status_code == 200

    def test_own_difficulty(
        self, client: TestClient, student_user: dict,
    ):
        resp = client.get(
            f"/stats/user/{student_user['id']}/difficulty",
            headers=auth_header(student_user),
        )
        assert resp.status_code == 200

    def test_own_full(
        self, client: TestClient, student_user: dict,
    ):
        resp = client.get(
            f"/stats/user/{student_user['id']}/full",
            headers=auth_header(student_user),
        )
        assert resp.status_code == 200

    def test_nonexistent_user_400(
        self, client: TestClient, admin_user: dict,
    ):
        """Admin querying non-existent user gets 400 ValueError."""
        resp = client.get(
            "/stats/user/99999/period",
            headers=auth_header(admin_user),
        )
        assert resp.status_code == 400


# ==================== 6. ACCESS CONTROL ====================


class TestStatsAccessControl:
    """Permission boundaries: student sees only self, teacher needs link."""

    def test_student_cannot_see_other_student(
        self, client: TestClient, student_user: dict, student2_user: dict,
    ):
        """Student cannot view another student's stats."""
        resp = client.get(
            f"/stats/user/{student2_user['id']}/period",
            headers=auth_header(student_user),
        )
        assert resp.status_code == 403

    def test_teacher_cannot_see_unlinked_student(
        self, client: TestClient, teacher_user: dict, student_user: dict,
    ):
        """Teacher without link cannot view student's stats."""
        # Make sure there's no link
        resp = client.get(
            f"/stats/user/{student_user['id']}/period",
            headers=auth_header(teacher_user),
        )
        assert resp.status_code == 403

    async def test_teacher_can_see_linked_student(
        self, client: TestClient, db: AsyncSession, teacher_user: dict,
        student_user: dict,
    ):
        """Teacher with link can view student's stats."""
        db.add(models.TeacherStudent(
            teacher_id=teacher_user["id"], student_id=student_user["id"],
        ))
        await db.commit()

        resp = client.get(
            f"/stats/user/{student_user['id']}/period",
            headers=auth_header(teacher_user),
        )
        assert resp.status_code == 200

    async def test_teacher_can_see_linked_topics(
        self, client: TestClient, db: AsyncSession, teacher_user: dict,
        student_user: dict,
    ):
        """Teacher with link can view student's topic stats."""
        db.add(models.TeacherStudent(
            teacher_id=teacher_user["id"], student_id=student_user["id"],
        ))
        await db.commit()

        resp = client.get(
            f"/stats/user/{student_user['id']}/topics",
            headers=auth_header(teacher_user),
        )
        assert resp.status_code == 200

    async def test_teacher_can_see_linked_difficulty(
        self, client: TestClient, db: AsyncSession, teacher_user: dict,
        student_user: dict,
    ):
        db.add(models.TeacherStudent(
            teacher_id=teacher_user["id"], student_id=student_user["id"],
        ))
        await db.commit()

        resp = client.get(
            f"/stats/user/{student_user['id']}/difficulty",
            headers=auth_header(teacher_user),
        )
        assert resp.status_code == 200

    async def test_teacher_can_see_linked_full(
        self, client: TestClient, db: AsyncSession, teacher_user: dict,
        student_user: dict,
    ):
        db.add(models.TeacherStudent(
            teacher_id=teacher_user["id"], student_id=student_user["id"],
        ))
        await db.commit()

        resp = client.get(
            f"/stats/user/{student_user['id']}/full",
            headers=auth_header(teacher_user),
        )
        assert resp.status_code == 200

    def test_admin_can_see_any_student(
        self, client: TestClient, admin_user: dict, student_user: dict,
    ):
        """Admin can view any student's stats."""
        resp = client.get(
            f"/stats/user/{student_user['id']}/period",
            headers=auth_header(admin_user),
        )
        assert resp.status_code == 200

    def test_admin_can_see_any_teacher(
        self, client: TestClient, admin_user: dict, teacher_user: dict,
    ):
        """Admin can view any teacher's stats."""
        resp = client.get(
            f"/stats/user/{teacher_user['id']}/period",
            headers=auth_header(admin_user),
        )
        assert resp.status_code == 200

    def test_stats_without_auth(self, client: TestClient, student_user: dict):
        """All stats endpoints require auth."""
        resp = client.get(f"/stats/user/{student_user['id']}/period")
        assert resp.status_code == 401


# ==================== 7. TEACHER SELF STATS ====================


class TestTeacherSelfStats:
    """Teachers can view their own stats."""

    def test_teacher_own_period(
        self, client: TestClient, teacher_user: dict,
    ):
        resp = client.get("/stats/me/period", headers=auth_header(teacher_user))
        assert resp.status_code == 200
        assert resp.json()["user_id"] == teacher_user["id"]

    def test_teacher_own_topics(
        self, client: TestClient, teacher_user: dict,
    ):
        resp = client.get("/stats/me/topics", headers=auth_header(teacher_user))
        assert resp.status_code == 200

    def test_teacher_own_difficulty(
        self, client: TestClient, teacher_user: dict,
    ):
        resp = client.get("/stats/me/difficulty", headers=auth_header(teacher_user))
        assert resp.status_code == 200

    def test_teacher_own_full(
        self, client: TestClient, teacher_user: dict,
    ):
        resp = client.get("/stats/me/full", headers=auth_header(teacher_user))
        assert resp.status_code == 200
