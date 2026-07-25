"""
Admin tests: CRUD for tasks, task rebuild, user management, and theory management.
"""

import time
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession

import core.models as models
from tests.conftest import auth_header


# ==================== 1. TASK CRUD ====================


class TestAdminTaskCRUD:
    """Full CRUD for admin tasks."""

    def test_create_task(self, client: TestClient, admin_user: dict, sample_task_payload: dict):
        """Create a task as admin."""
        resp = client.post(
            "/admin/tasks",
            json=sample_task_payload,
            headers=auth_header(admin_user),
        )
        assert resp.status_code == 200
        assert resp.json()["id"] is not None
        assert resp.json()["task_class"] == "11"
        assert resp.json()["topic"] == "geometry"

    def test_create_task_without_auth(self, client: TestClient, sample_task_payload: dict):
        """Creating without auth returns 401."""
        resp = client.post("/admin/tasks", json=sample_task_payload)
        assert resp.status_code == 401

    def test_create_task_as_teacher(self, client: TestClient, teacher_user: dict, sample_task_payload: dict):
        """Teacher cannot create a task."""
        resp = client.post(
            "/admin/tasks",
            json=sample_task_payload,
            headers=auth_header(teacher_user),
        )
        assert resp.status_code == 403

    def test_create_task_as_student(self, client: TestClient, student_user: dict, sample_task_payload: dict):
        """Student cannot create a task."""
        resp = client.post(
            "/admin/tasks",
            json=sample_task_payload,
            headers=auth_header(student_user),
        )
        assert resp.status_code == 403

    def test_create_task_missing_answer(self, client: TestClient, admin_user: dict):
        """Missing required field returns 422."""
        resp = client.post(
            "/admin/tasks",
            json={
                "task_class": "10",
                "topic_number": "1",
                "topic": "algebra",
                "content": "text",
            },
            headers=auth_header(admin_user),
        )
        assert resp.status_code == 422

    def test_create_task_with_options(self, client: TestClient, admin_user: dict):
        """Create a task with answer options."""
        resp = client.post(
            "/admin/tasks",
            json={
                "task_class": "10",
                "topic_number": "1",
                "topic": "algebra",
                "section": "equations",
                "content": r"Root of $x^2 = 4$?",
                "answer": "2,-2",
                "hint": "Remember the root",
                "solution": r"$$x = \pm 2$$",
                "is_open_answer": False,
                "options": ["0", "2", "-2", "4"],
                "difficulty": 2,
            },
            headers=auth_header(admin_user),
        )
        assert resp.status_code == 200
        assert resp.json()["options"] == ["0", "2", "-2", "4"]

    def test_get_all_tasks(self, client: TestClient, admin_user: dict, sample_task: int):
        """Get all tasks."""
        resp = client.get("/admin/", headers=auth_header(admin_user))
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
        assert len(resp.json()) >= 1

    def test_get_all_tasks_without_auth(self, client: TestClient):
        """Get all tasks without auth returns 401."""
        resp = client.get("/admin/")
        assert resp.status_code == 401

    def test_get_single_task(self, client: TestClient, admin_user: dict, sample_task: int):
        """Get a task by ID."""
        resp = client.get(f"/admin/tasks/{sample_task}", headers=auth_header(admin_user))
        assert resp.status_code == 200
        assert resp.json()["id"] == sample_task

    def test_get_nonexistent_task(self, client: TestClient, admin_user: dict):
        """Non-existent task returns 404."""
        resp = client.get("/admin/tasks/99999", headers=auth_header(admin_user))
        assert resp.status_code == 404

    def test_update_task(self, client: TestClient, admin_user: dict, sample_task: int):
        """Update an existing task."""
        resp = client.put(
            f"/admin/tasks/{sample_task}",
            json={
                "task_class": "10",
                "topic_number": "1",
                "topic": "algebra",
                "section": "equations",
                "content": r"$3x + 5 = 14$",
                "answer": "3",
                "hint": "New hint",
                "solution": r"$$3x = 9$$\n$$x = 3$$",
                "is_open_answer": False,
                "options": ["1", "2", "3", "4"],
                "difficulty": 3,
            },
            headers=auth_header(admin_user),
        )
        assert resp.status_code == 200

    def test_update_task_change_type(self, client: TestClient, admin_user: dict, sample_task: int):
        """Change from closed to open answer type."""
        resp = client.put(
            f"/admin/tasks/{sample_task}",
            json={
                "task_class": "10",
                "topic_number": "1",
                "topic": "algebra",
                "section": "equations",
                "content": r"$2x + 3 = 7$",
                "answer": "2",
                "hint": "Hint",
                "solution": "Solution",
                "is_open_answer": True,
                "options": None,
                "difficulty": 2,
            },
            headers=auth_header(admin_user),
        )
        assert resp.status_code == 200

    def test_delete_task(self, client: TestClient, admin_user: dict, sample_task: int):
        """Delete a task."""
        resp = client.delete(f"/admin/tasks/{sample_task}", headers=auth_header(admin_user))
        assert resp.status_code == 200
        assert "удалены" in resp.json()["message"]

        get_resp = client.get(f"/admin/tasks/{sample_task}", headers=auth_header(admin_user))
        assert get_resp.status_code == 404

    def test_delete_nonexistent_task(self, client: TestClient, admin_user: dict):
        """Deleting non-existent task returns 404."""
        resp = client.delete("/admin/tasks/99999", headers=auth_header(admin_user))
        assert resp.status_code == 404

    def test_delete_task_without_auth(self, client: TestClient, sample_task: int):
        """Deleting without auth returns 401."""
        resp = client.delete(f"/admin/tasks/{sample_task}")
        assert resp.status_code == 401

    def test_delete_task_as_teacher(self, client: TestClient, teacher_user: dict, sample_task: int):
        """Teacher cannot delete a task."""
        resp = client.delete(f"/admin/tasks/{sample_task}", headers=auth_header(teacher_user))
        assert resp.status_code == 403


# ==================== 2. REBUILD ALL STATIC TESTS ====================


class TestAdminRebuild:
    """Tests for rebuilding static tests."""

    def test_rebuild_all_static_tests(self, client: TestClient, admin_user: dict):
        """Rebuild all static tests succeeds."""
        resp = client.post(
            "/admin/rebuild-all-static-tests",
            headers=auth_header(admin_user),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "success"

    def test_rebuild_does_not_delete_teacher_tests(
        self, client: TestClient, admin_user: dict, teacher_user: dict, sample_task: int
    ):
        """Rebuild does not delete teacher-created tests."""
        t = client.post(
            "/teacher/tests",
            json={
                "title": "Teacher Test",
                "target_class": "10",
                "target_topic": "1",
                "is_autocompile": False,
                "task_ids": [sample_task],
            },
            headers=auth_header(teacher_user),
        ).json()

        client.post(
            "/admin/rebuild-all-static-tests",
            headers=auth_header(admin_user),
        )

        get_resp = client.get(f"/teacher/tests/{t['id']}", headers=auth_header(teacher_user))
        assert get_resp.status_code == 200
        assert get_resp.json()["id"] == t["id"]

    async def test_rebuild_does_not_delete_ai_tests(
        self, client: TestClient, db: AsyncSession, admin_user: dict, student_user: dict
    ):
        """Rebuild does not delete AI-generated tests."""
        ai_test = models.Test(
            title="AI Test",
            target_class=None,
            target_topic="test",
            is_autocompile=False,
            is_ai_generated=True,
            creator_id=student_user["id"],
            is_active=True,
        )
        db.add(ai_test)
        await db.commit()
        ai_test_id = ai_test.id

        client.post(
            "/admin/rebuild-all-static-tests",
            headers=auth_header(admin_user),
        )

        result = await db.execute(sa_select(models.Test).where(models.Test.id == ai_test_id))
        assert result.scalars().first() is not None, "AI test was deleted!"

    async def test_rebuild_recalculates_answers(
        self,
        client: TestClient,
        db: AsyncSession,
        admin_user: dict,
        teacher_user: dict,
        student_user: dict,
    ):
        """Rebuild recalculates answers after task updates."""
        closed = client.post(
            "/admin/tasks",
            json={
                "task_class": "20",
                "topic_number": "1",
                "topic": "algebra",
                "section": "equations",
                "content": r"$2x + 3 = 7$",
                "answer": "999",
                "hint": "hint",
                "solution": r"$$2x=4$$",
                "is_open_answer": False,
                "options": ["1", "2", "3", "4"],
                "difficulty": 2,
            },
            headers=auth_header(admin_user),
        ).json()["id"]

        open_t = client.post(
            "/admin/tasks",
            json={
                "task_class": "20",
                "topic_number": "1",
                "topic": "algebra",
                "section": "expressions",
                "content": r"$a \cdot a^2$",
                "answer": "wrong",
                "hint": "hint",
                "solution": r"$$a^3$$",
                "is_open_answer": True,
                "options": None,
                "difficulty": 1,
            },
            headers=auth_header(admin_user),
        ).json()["id"]

        db.add(models.TeacherStudent(teacher_id=teacher_user["id"], student_id=student_user["id"]))
        await db.commit()

        t = client.post(
            "/teacher/tests",
            json={
                "title": "Manual Test",
                "target_class": "20",
                "target_topic": "1",
                "is_autocompile": False,
                "task_ids": [closed, open_t],
            },
            headers=auth_header(teacher_user),
        ).json()

        client.post(
            "/teacher/assign-test",
            json={"test_id": t["id"], "user_ids": [student_user["id"]]},
            headers=auth_header(teacher_user),
        )

        submit = client.post(
            f"/student/tests/{t['id']}/submit",
            json=[
                {"task_id": closed, "user_answer": "2"},
                {"task_id": open_t, "user_answer": "10"},
            ],
            headers=auth_header(student_user),
        )
        assert submit.status_code == 200
        assert submit.json()["score"] == 0

        client.put(
            f"/admin/tasks/{closed}",
            json={
                "task_class": "20",
                "topic_number": "1",
                "topic": "algebra",
                "section": "equations",
                "content": r"$2x + 3 = 7$",
                "answer": "2",
                "hint": "hint",
                "solution": r"$$2x=4$$",
                "is_open_answer": False,
                "options": ["1", "2", "3", "4"],
                "difficulty": 2,
            },
            headers=auth_header(admin_user),
        )

        client.put(
            f"/admin/tasks/{open_t}",
            json={
                "task_class": "20",
                "topic_number": "1",
                "topic": "algebra",
                "section": "expressions",
                "content": r"$a \cdot a^2$",
                "answer": "a^3",
                "hint": "hint",
                "solution": r"$$a^3$$",
                "is_open_answer": True,
                "options": None,
                "difficulty": 1,
            },
            headers=auth_header(admin_user),
        )

        rebuild = client.post(
            "/admin/rebuild-all-static-tests",
            headers=auth_header(admin_user),
        )
        assert rebuild.status_code == 200

        db.expire_all()
        last_result = await db.execute(
            sa_select(models.TestResult)
            .where(models.TestResult.test_id == t["id"])
            .order_by(models.TestResult.completed_at.desc())
        )
        last = last_result.scalars().first()

        if last:
            answers = await db.execute(
                sa_select(models.UserAnswer).where(models.UserAnswer.result_id == last.id)
            )
            total = sum(ua.points_earned for ua in answers.scalars().all())
            assert total == 1, f"Expected 1 point, got {total}"


# ==================== 3. USER MANAGEMENT ====================


class TestAdminUsers:
    """Tests for user management."""

    def test_get_all_users(self, client: TestClient, admin_user: dict):
        """Get all users."""
        resp = client.get("/admin/users", headers=auth_header(admin_user))
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
        assert len(resp.json()) >= 1

    async def test_change_user_role(self, client: TestClient, admin_user: dict, db: AsyncSession):
        """Change a user's role."""
        db.add(models.AllowedEmail(email="roleuser@test.com"))
        await db.commit()

        client.post("/register", json={
            "username": "roleuser@test.com",
            "password": "Pass123!",
            "first_name": "Role",
            "last_name": "User",
        })

        result = await db.execute(
            sa_select(models.User).where(models.User.username == "roleuser@test.com")
        )
        user = result.scalars().first()

        resp = client.patch(
            f"/admin/users/{user.id}/role",
            params={"new_role": "teacher"},
            headers=auth_header(admin_user),
        )
        assert resp.status_code == 200
        assert "изменена на teacher" in resp.json()["message"]

        await db.refresh(user)
        assert user.role == "teacher"

    async def test_change_role_invalid(self, client: TestClient, admin_user: dict, db: AsyncSession):
        """Invalid role returns 400."""
        db.add(models.AllowedEmail(email="badrole@test.com"))
        await db.commit()

        client.post("/register", json={
            "username": "badrole@test.com",
            "password": "Pass123!",
            "first_name": "Bad",
            "last_name": "Role",
        })

        result = await db.execute(
            sa_select(models.User).where(models.User.username == "badrole@test.com")
        )
        user = result.scalars().first()

        resp = client.patch(
            f"/admin/users/{user.id}/role",
            params={"new_role": "superadmin"},
            headers=auth_header(admin_user),
        )
        assert resp.status_code == 400

    async def test_delete_user(self, client: TestClient, admin_user: dict, db: AsyncSession):
        """Delete a user."""
        db.add(models.AllowedEmail(email="deluser@test.com"))
        await db.commit()

        client.post("/register", json={
            "username": "deluser@test.com",
            "password": "Pass123!",
            "first_name": "Del",
            "last_name": "User",
        })

        result = await db.execute(
            sa_select(models.User).where(models.User.username == "deluser@test.com")
        )
        user = result.scalars().first()

        resp = client.delete(f"/admin/users/{user.id}", headers=auth_header(admin_user))
        assert resp.status_code == 200

        deleted = await db.execute(sa_select(models.User).where(models.User.id == user.id))
        assert deleted.scalars().first() is None

    def test_cant_delete_last_admin(self, client: TestClient, admin_user: dict):
        """Cannot delete the last admin."""
        resp = client.delete(f"/admin/users/{admin_user['id']}", headers=auth_header(admin_user))
        assert resp.status_code == 400
        assert "Нельзя удалить" in resp.json()["detail"]

    def test_delete_nonexistent_user(self, client: TestClient, admin_user: dict):
        """Deleting non-existent user returns 404."""
        resp = client.delete("/admin/users/99999", headers=auth_header(admin_user))
        assert resp.status_code == 404


# ==================== 4. THEORY MANAGEMENT ====================


class TestAdminTheory:
    """Tests for theory material management."""

    def test_create_theory(self, client: TestClient, admin_user: dict):
        """Create theory material."""
        resp = client.post(
            "/admin/theory",
            json={
                "topic": "algebra",
                "section": "equations",
                "content": "An equation is an equality with an unknown.",
            },
            headers=auth_header(admin_user),
        )
        assert resp.status_code == 200
        assert resp.json()["topic"] == "algebra"

    async def test_create_theory_duplicate(self, client: TestClient, admin_user: dict, db: AsyncSession):
        """Duplicate theory material returns 400."""
        theory = models.Theory(topic="algebra", section="equations", content="Content")
        db.add(theory)
        await db.commit()

        resp = client.post(
            "/admin/theory",
            json={"topic": "algebra", "section": "equations", "content": "Other"},
            headers=auth_header(admin_user),
        )
        assert resp.status_code == 400
        assert "уже существует" in resp.json()["detail"]

    async def test_get_all_theory(self, client: TestClient, admin_user: dict, db: AsyncSession):
        """Get all theory."""
        theory = models.Theory(topic="algebra", section="equations", content="Content")
        db.add(theory)
        await db.commit()

        resp = client.get("/admin/theory/getall", headers=auth_header(admin_user))
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
        assert len(resp.json()) >= 1

    async def test_update_theory(self, client: TestClient, admin_user: dict, db: AsyncSession):
        """Update theory material."""
        theory = models.Theory(topic="algebra", section="equations", content="Old")
        db.add(theory)
        await db.commit()

        resp = client.put(
            f"/admin/theory/{theory.id}",
            json={"topic": "algebra", "section": "equations", "content": "New content"},
            headers=auth_header(admin_user),
        )
        assert resp.status_code == 200
        assert resp.json()["content"] == "New content"

    async def test_delete_theory(self, client: TestClient, admin_user: dict, db: AsyncSession):
        """Delete theory material."""
        theory = models.Theory(topic="algebra", section="equations", content="Content")
        db.add(theory)
        await db.commit()

        resp = client.delete(
            f"/admin/theory/{theory.id}",
            headers=auth_header(admin_user),
        )
        assert resp.status_code == 200
        assert "успешно удалена" in resp.json()["message"]


# ==================== 5. ADDITIONAL CHECKS ====================


class TestAdminAdditional:
    """Additional admin checks."""

    def test_unauthorized_access(self, client: TestClient):
        """Access without token returns 401."""
        endpoints = ["/admin/users", "/admin/", "/admin/tasks/1"]
        for ep in endpoints:
            resp = client.get(ep)
            assert resp.status_code == 401, f"{ep} should return 401"

    def test_invalid_token(self, client: TestClient):
        """Invalid token returns 401."""
        resp = client.get("/admin/users", headers={"Authorization": "Bearer invalid.token.here"})
        assert resp.status_code == 401

    def test_bulk_task_operations(self, client: TestClient, admin_user: dict):
        """Bulk task creation is performant."""
        start = time.time()

        for i in range(5):
            resp = client.post(
                "/admin/tasks",
                json={
                    "task_class": "10",
                    "topic_number": "1",
                    "topic": "algebra",
                    "section": "equations",
                    "content": f"Bulk {i}",
                    "answer": str(i),
                    "hint": "h",
                    "solution": "s",
                    "is_open_answer": False,
                    "options": ["1", "2", "3", "4"],
                    "difficulty": 1,
                },
                headers=auth_header(admin_user),
            )
            assert resp.status_code == 200

        elapsed = time.time() - start
        assert elapsed < 10, f"Too slow: {elapsed:.2f}s"