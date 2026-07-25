"""
Teacher tests: CRUD for tests, tasks, groups, students, assignments, and results.
"""

from typing import Any

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession

import core.models as models
from tests.conftest import auth_header


# ==================== 1. TESTS CRUD ====================


class TestTeacherTests:
    """CRUD for teacher-created tests."""

    def test_get_tests_empty(self, client: TestClient, teacher_user: dict):
        """Empty test list."""
        resp = client.get("/teacher/tests", headers=auth_header(teacher_user))
        assert resp.status_code == 200
        assert resp.json() == []

    def test_create_test(self, client: TestClient, teacher_user: dict, sample_task: int):
        """Create a test with a task."""
        resp = client.post(
            "/teacher/tests",
            json={
                "title": "My First Test",
                "target_class": "10",
                "target_topic": "1",
                "is_autocompile": False,
                "task_ids": [sample_task],
            },
            headers=auth_header(teacher_user),
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "My First Test"
        assert "id" in resp.json()

    def test_create_test_without_tasks(self, client: TestClient, teacher_user: dict):
        """Create a test without tasks."""
        resp = client.post(
            "/teacher/tests",
            json={
                "title": "Empty Test",
                "target_class": "10",
                "target_topic": "1",
                "is_autocompile": False,
                "task_ids": [],
            },
            headers=auth_header(teacher_user),
        )
        assert resp.status_code == 200

    def test_create_test_as_student_forbidden(self, client: TestClient, student_user: dict):
        """Student cannot create a test."""
        resp = client.post(
            "/teacher/tests",
            json={
                "title": "hack",
                "target_class": "10",
                "target_topic": "1",
                "is_autocompile": False,
                "task_ids": [],
            },
            headers=auth_header(student_user),
        )
        assert resp.status_code == 403

    def test_get_my_tests(self, client: TestClient, teacher_user: dict, sample_task: int):
        """Teacher sees own tests."""
        client.post(
            "/teacher/tests",
            json={
                "title": "Test 1",
                "target_class": "10",
                "target_topic": "1",
                "is_autocompile": False,
                "task_ids": [sample_task],
            },
            headers=auth_header(teacher_user),
        )
        resp = client.get("/teacher/tests", headers=auth_header(teacher_user))
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    async def test_cant_see_other_teacher_tests(
        self, client: TestClient, db: AsyncSession, teacher_user: dict, sample_task: int
    ):
        """Teacher cannot see another teacher's tests."""
        db.add(models.AllowedEmail(email="t2@test.com"))
        await db.commit()

        client.post("/register", json={
            "username": "t2@test.com",
            "password": "Teacher123!",
            "first_name": "T",
            "last_name": "Two",
        })

        result = await db.execute(
            sa_select(models.User).where(models.User.username == "t2@test.com")
        )
        teacher2 = result.scalars().first()
        teacher2.role = "teacher"
        await db.commit()

        login2 = client.post("/login", data={"username": "t2@test.com", "password": "Teacher123!"})
        t2_token = login2.json()["access_token"]

        client.post(
            "/teacher/tests",
            json={
                "title": "T2 Test",
                "target_class": "10",
                "target_topic": "1",
                "is_autocompile": False,
                "task_ids": [sample_task],
            },
            headers={"Authorization": f"Bearer {t2_token}"},
        )

        resp = client.get("/teacher/tests", headers=auth_header(teacher_user))
        assert len(resp.json()) == 0

    def test_get_test_detail(self, client: TestClient, teacher_user: dict, sample_task: int):
        """Get test details."""
        t = client.post(
            "/teacher/tests",
            json={
                "title": "Detail",
                "target_class": "10",
                "target_topic": "1",
                "is_autocompile": False,
                "task_ids": [sample_task],
            },
            headers=auth_header(teacher_user),
        ).json()

        resp = client.get(f"/teacher/tests/{t['id']}", headers=auth_header(teacher_user))
        assert resp.status_code == 200
        assert resp.json()["id"] == t["id"]

    def test_update_test(self, client: TestClient, teacher_user: dict, sample_task: int):
        """Update an existing test."""
        t = client.post(
            "/teacher/tests",
            json={
                "title": "Old",
                "target_class": "10",
                "target_topic": "1",
                "is_autocompile": False,
                "task_ids": [sample_task],
            },
            headers=auth_header(teacher_user),
        ).json()

        resp = client.put(
            f"/teacher/tests/{t['id']}",
            json={
                "title": "New",
                "target_class": "11",
                "target_topic": "2",
                "is_autocompile": True,
                "task_ids": [],
            },
            headers=auth_header(teacher_user),
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "New"

    def test_delete_test(self, client: TestClient, teacher_user: dict, sample_task: int):
        """Delete a test."""
        t = client.post(
            "/teacher/tests",
            json={
                "title": "ToDelete",
                "target_class": "10",
                "target_topic": "1",
                "is_autocompile": False,
                "task_ids": [sample_task],
            },
            headers=auth_header(teacher_user),
        ).json()

        resp = client.delete(f"/teacher/tests/{t['id']}", headers=auth_header(teacher_user))
        assert resp.status_code == 200

        get_resp = client.get(f"/teacher/tests/{t['id']}", headers=auth_header(teacher_user))
        assert get_resp.status_code == 404

    async def test_cant_delete_others_test(
        self, client: TestClient, db: AsyncSession, teacher_user: dict, sample_task: int
    ):
        """Cannot delete another teacher's test."""
        db.add(models.AllowedEmail(email="t3@test.com"))
        await db.commit()

        client.post("/register", json={
            "username": "t3@test.com",
            "password": "Teacher123!",
            "first_name": "T3",
            "last_name": "Test",
        })

        result = await db.execute(
            sa_select(models.User).where(models.User.username == "t3@test.com")
        )
        teacher2 = result.scalars().first()
        teacher2.role = "teacher"
        await db.commit()

        login2 = client.post("/login", data={"username": "t3@test.com", "password": "Teacher123!"})
        t2_token = login2.json()["access_token"]

        t2 = client.post(
            "/teacher/tests",
            json={
                "title": "Other",
                "target_class": "10",
                "target_topic": "1",
                "is_autocompile": False,
                "task_ids": [sample_task],
            },
            headers={"Authorization": f"Bearer {t2_token}"},
        ).json()

        resp = client.delete(f"/teacher/tests/{t2['id']}", headers=auth_header(teacher_user))
        assert resp.status_code == 403


# ==================== 2. TASKS BANK ====================


class TestTeacherTasks:
    """Tests for the tasks bank accessible to teachers."""

    def test_get_all_tasks(self, client: TestClient, teacher_user: dict, sample_task: int):
        """Get all tasks."""
        resp = client.get("/teacher/tasks", headers=auth_header(teacher_user))
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    def test_get_tasks_filter_by_class(self, client: TestClient, teacher_user: dict, sample_task: int):
        """Filter tasks by class."""
        resp = client.get("/teacher/tasks?task_class=10", headers=auth_header(teacher_user))
        assert resp.status_code == 200

    def test_get_single_task(self, client: TestClient, teacher_user: dict, sample_task: int):
        """Get task by ID."""
        resp = client.get(f"/teacher/tasks/{sample_task}", headers=auth_header(teacher_user))
        assert resp.status_code == 200

    def test_get_tasks_grouped(self, client: TestClient, teacher_user: dict, sample_task: int):
        """Get grouped tasks."""
        resp = client.get("/teacher/tasks-grouped", headers=auth_header(teacher_user))
        assert resp.status_code == 200
        assert "grouped" in resp.json()
        assert "total_tasks" in resp.json()

    def test_get_tasks_meta(self, client: TestClient, teacher_user: dict, sample_task: int):
        """Get tasks metadata."""
        resp = client.get("/teacher/tasks-meta", headers=auth_header(teacher_user))
        assert resp.status_code == 200

    def test_get_tasks_by_class_and_topic(self, client: TestClient, teacher_user: dict, sample_task: int):
        """Get tasks by class and topic."""
        resp = client.get(
            "/teacher/tasks/by-class-topic?task_class=10&topic_number=1",
            headers=auth_header(teacher_user),
        )
        assert resp.status_code == 200


# ==================== 3. GROUPS CRUD ====================


class TestTeacherGroups:
    """Full CRUD for groups."""

    def test_create_group(self, client: TestClient, teacher_user: dict):
        """Create a group."""
        resp = client.post(
            "/teacher/groups/",
            json={"name": "10A", "description": "Best class"},
            headers=auth_header(teacher_user),
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "10A"

    def test_create_group_without_name(self, client: TestClient, teacher_user: dict):
        """Creating a group without a name fails."""
        resp = client.post(
            "/teacher/groups/",
            json={"description": "No name"},
            headers=auth_header(teacher_user),
        )
        assert resp.status_code == 400

    def test_get_my_groups_empty(self, client: TestClient, teacher_user: dict):
        """Empty group list."""
        resp = client.get("/teacher/groups/", headers=auth_header(teacher_user))
        assert resp.status_code == 200
        assert resp.json() == []

    def test_get_my_groups(self, client: TestClient, teacher_user: dict):
        """Get list of groups."""
        client.post(
            "/teacher/groups/",
            json={"name": "10A"},
            headers=auth_header(teacher_user),
        )
        resp = client.get("/teacher/groups/", headers=auth_header(teacher_user))
        assert resp.status_code == 200
        assert len(resp.json()) == 1
        assert resp.json()[0]["name"] == "10A"

    def test_update_group(self, client: TestClient, teacher_user: dict):
        """Update a group."""
        g = client.post(
            "/teacher/groups/",
            json={"name": "Old"},
            headers=auth_header(teacher_user),
        ).json()

        resp = client.put(
            f"/teacher/groups/{g['id']}",
            json={"name": "New", "description": "Updated"},
            headers=auth_header(teacher_user),
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "New"

    def test_delete_group(self, client: TestClient, teacher_user: dict):
        """Delete a group."""
        g = client.post(
            "/teacher/groups/",
            json={"name": "ToDelete"},
            headers=auth_header(teacher_user),
        ).json()

        resp = client.delete(f"/teacher/groups/{g['id']}", headers=auth_header(teacher_user))
        assert resp.status_code == 200

    async def test_cant_see_other_teacher_groups(
        self, client: TestClient, db: AsyncSession, teacher_user: dict
    ):
        """Cannot see another teacher's groups."""
        db.add(models.AllowedEmail(email="tg@test.com"))
        await db.commit()

        client.post("/register", json={
            "username": "tg@test.com",
            "password": "Teacher123!",
            "first_name": "T",
            "last_name": "G",
        })

        result = await db.execute(
            sa_select(models.User).where(models.User.username == "tg@test.com")
        )
        t2 = result.scalars().first()
        t2.role = "teacher"
        await db.commit()

        login2 = client.post("/login", data={"username": "tg@test.com", "password": "Teacher123!"})
        t2_token = login2.json()["access_token"]

        client.post(
            "/teacher/groups/",
            json={"name": "Other group"},
            headers={"Authorization": f"Bearer {t2_token}"},
        )

        resp = client.get("/teacher/groups/", headers=auth_header(teacher_user))
        assert len(resp.json()) == 0

    def test_add_students_to_group(
        self, client: TestClient, teacher_user: dict, student_user: dict, link_teacher_student: Any
    ):
        """Add students to a group."""
        g = client.post(
            "/teacher/groups/",
            json={"name": "Group"},
            headers=auth_header(teacher_user),
        ).json()

        resp = client.post(
            f"/teacher/groups/{g['id']}/students",
            json={"student_ids": [student_user["id"]]},
            headers=auth_header(teacher_user),
        )
        assert resp.status_code == 200
        assert resp.json()["added"] == 1

    def test_remove_student_from_group(
        self, client: TestClient, teacher_user: dict, student_user: dict, link_teacher_student: Any
    ):
        """Remove a student from a group."""
        g = client.post(
            "/teacher/groups/",
            json={"name": "Group2"},
            headers=auth_header(teacher_user),
        ).json()
        client.post(
            f"/teacher/groups/{g['id']}/students",
            json={"student_ids": [student_user["id"]]},
            headers=auth_header(teacher_user),
        )

        resp = client.delete(
            f"/teacher/groups/{g['id']}/students/{student_user['id']}",
            headers=auth_header(teacher_user),
        )
        assert resp.status_code == 200

    def test_get_group_students(
        self, client: TestClient, teacher_user: dict, student_user: dict, link_teacher_student: Any
    ):
        """Get students in a group."""
        g = client.post(
            "/teacher/groups/",
            json={"name": "Group3"},
            headers=auth_header(teacher_user),
        ).json()
        client.post(
            f"/teacher/groups/{g['id']}/students",
            json={"student_ids": [student_user["id"]]},
            headers=auth_header(teacher_user),
        )

        resp = client.get(
            f"/teacher/groups/{g['id']}/students",
            headers=auth_header(teacher_user),
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 1
        assert resp.json()[0]["id"] == student_user["id"]


# ==================== 4. STUDENTS & ASSIGNMENTS ====================


class TestTeacherStudents:
    """Tests for student management and test assignments."""

    def test_get_my_students(
        self, client: TestClient, teacher_user: dict, student_user: dict, link_teacher_student: Any
    ):
        """Get linked students."""
        resp = client.get("/teacher/students", headers=auth_header(teacher_user))
        assert resp.status_code == 200
        student_ids = [s["id"] for s in resp.json()]
        assert student_user["id"] in student_ids

    def test_student_profile(
        self, client: TestClient, teacher_user: dict, student_user: dict, link_teacher_student: Any
    ):
        """View student profile."""
        resp = client.get(
            f"/teacher/students-profile/{student_user['id']}",
            headers=auth_header(teacher_user),
        )
        assert resp.status_code == 200
        assert resp.json()["user"]["id"] == student_user["id"]

    def test_assign_test(
        self,
        client: TestClient,
        teacher_user: dict,
        student_user: dict,
        link_teacher_student: Any,
        sample_task: int,
    ):
        """Assign a test to a student."""
        t = client.post(
            "/teacher/tests",
            json={
                "title": "Assign",
                "target_class": "10",
                "target_topic": "1",
                "is_autocompile": False,
                "task_ids": [sample_task],
            },
            headers=auth_header(teacher_user),
        ).json()

        resp = client.post(
            "/teacher/assign-test",
            json={"test_id": t["id"], "user_ids": [student_user["id"]]},
            headers=auth_header(teacher_user),
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_assign_test_twice_no_duplicate(
        self,
        client: TestClient,
        teacher_user: dict,
        student_user: dict,
        link_teacher_student: Any,
        sample_task: int,
    ):
        """Assigning a test twice does not duplicate."""
        t = client.post(
            "/teacher/tests",
            json={
                "title": "Dup",
                "target_class": "10",
                "target_topic": "1",
                "is_autocompile": False,
                "task_ids": [sample_task],
            },
            headers=auth_header(teacher_user),
        ).json()

        client.post(
            "/teacher/assign-test",
            json={"test_id": t["id"], "user_ids": [student_user["id"]]},
            headers=auth_header(teacher_user),
        )
        resp = client.post(
            "/teacher/assign-test",
            json={"test_id": t["id"], "user_ids": [student_user["id"]]},
            headers=auth_header(teacher_user),
        )
        assert len(resp.json()) == 1

    def test_assign_test_to_group(
        self,
        client: TestClient,
        teacher_user: dict,
        student_user: dict,
        link_teacher_student: Any,
        sample_task: int,
    ):
        """Assign a test to an entire group."""
        g = client.post(
            "/teacher/groups/",
            json={"name": "TestGroup"},
            headers=auth_header(teacher_user),
        ).json()
        client.post(
            f"/teacher/groups/{g['id']}/students",
            json={"student_ids": [student_user["id"]]},
            headers=auth_header(teacher_user),
        )

        t = client.post(
            "/teacher/tests",
            json={
                "title": "ForGroup",
                "target_class": "10",
                "target_topic": "1",
                "is_autocompile": False,
                "task_ids": [sample_task],
            },
            headers=auth_header(teacher_user),
        ).json()

        resp = client.post(
            "/teacher/assign-test-to-group",
            json={"group_id": g["id"], "test_id": t["id"]},
            headers=auth_header(teacher_user),
        )
        assert resp.status_code == 200
        assert resp.json()["assigned_count"] == 1

    def test_get_test_assignments(
        self,
        client: TestClient,
        teacher_user: dict,
        student_user: dict,
        link_teacher_student: Any,
        sample_task: int,
    ):
        """Get assignments for a test."""
        t = client.post(
            "/teacher/tests",
            json={
                "title": "Check",
                "target_class": "10",
                "target_topic": "1",
                "is_autocompile": False,
                "task_ids": [sample_task],
            },
            headers=auth_header(teacher_user),
        ).json()
        client.post(
            "/teacher/assign-test",
            json={"test_id": t["id"], "user_ids": [student_user["id"]]},
            headers=auth_header(teacher_user),
        )

        resp = client.get(
            f"/teacher/test/{t['id']}/assignments",
            headers=auth_header(teacher_user),
        )
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    def test_get_student_assignments(
        self,
        client: TestClient,
        teacher_user: dict,
        student_user: dict,
        link_teacher_student: Any,
        sample_task: int,
    ):
        """Get assignments for a student."""
        t = client.post(
            "/teacher/tests",
            json={
                "title": "Student",
                "target_class": "10",
                "target_topic": "1",
                "is_autocompile": False,
                "task_ids": [sample_task],
            },
            headers=auth_header(teacher_user),
        ).json()
        client.post(
            "/teacher/assign-test",
            json={"test_id": t["id"], "user_ids": [student_user["id"]]},
            headers=auth_header(teacher_user),
        )

        resp = client.get(
            f"/teacher/student/{student_user['id']}/assignments",
            headers=auth_header(teacher_user),
        )
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    def test_delete_assignment(
        self,
        client: TestClient,
        teacher_user: dict,
        student_user: dict,
        link_teacher_student: Any,
        sample_task: int,
    ):
        """Delete an assignment."""
        t = client.post(
            "/teacher/tests",
            json={
                "title": "DelAssign",
                "target_class": "10",
                "target_topic": "1",
                "is_autocompile": False,
                "task_ids": [sample_task],
            },
            headers=auth_header(teacher_user),
        ).json()
        resp = client.post(
            "/teacher/assign-test",
            json={"test_id": t["id"], "user_ids": [student_user["id"]]},
            headers=auth_header(teacher_user),
        )
        assignment_id = resp.json()[0]["id"] if isinstance(resp.json(), list) else resp.json()["id"]

        del_resp = client.delete(
            f"/teacher/assignments/{assignment_id}",
            headers=auth_header(teacher_user),
        )
        assert del_resp.status_code == 200


# ==================== 5. RESULTS ====================


class TestTeacherResults:
    """Tests for viewing student results."""

    def test_student_history_empty(
        self, client: TestClient, teacher_user: dict, student_user: dict, link_teacher_student: Any
    ):
        """Empty student history."""
        resp = client.get(
            f"/teacher/students-history/{student_user['id']}",
            headers=auth_header(teacher_user),
        )
        assert resp.status_code == 200
        assert resp.json() == []

    def test_student_history_after_submission(
        self,
        client: TestClient,
        teacher_user: dict,
        student_user: dict,
        link_teacher_student: Any,
        sample_task: int,
    ):
        """History after test submission."""
        t = client.post(
            "/teacher/tests",
            json={
                "title": "HistoryTest",
                "target_class": "10",
                "target_topic": "1",
                "is_autocompile": False,
                "task_ids": [sample_task],
            },
            headers=auth_header(teacher_user),
        ).json()

        client.post(
            "/teacher/assign-test",
            json={"test_id": t["id"], "user_ids": [student_user["id"]]},
            headers=auth_header(teacher_user),
        )

        client.post(
            f"/student/tests/{t['id']}/submit",
            json=[{"task_id": sample_task, "user_answer": "2"}],
            headers=auth_header(student_user),
        )

        resp = client.get(
            f"/teacher/students-history/{student_user['id']}",
            headers=auth_header(teacher_user),
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 1
        assert resp.json()[0]["test_title"] == "HistoryTest"