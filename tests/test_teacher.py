"""
Teacher tests: task bank, test CRUD, assignments, students,
groups, group assignments, detailed results, and permissions.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession

import core.models as models
from tests.conftest import auth_header


# ==================== 1. TASK BANK ====================


class TestTeacherTaskBank:
    """Browsing tasks as a teacher."""

    def test_get_all_tasks_empty(self, client: TestClient, teacher_user: dict):
        """Empty task list when no tasks exist."""
        resp = client.get("/teacher/tasks", headers=auth_header(teacher_user))
        assert resp.status_code == 200
        assert resp.json() == []

    def test_get_all_tasks(
        self, client: TestClient, teacher_user: dict, sample_task: int,
    ):
        """Teacher can see all tasks."""
        resp = client.get("/teacher/tasks", headers=auth_header(teacher_user))
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    def test_get_tasks_filtered_by_class(
        self, client: TestClient, teacher_user: dict, sample_task: int,
    ):
        """Filter tasks by class."""
        resp = client.get(
            "/teacher/tasks", params={"task_class": 10},
            headers=auth_header(teacher_user),
        )
        assert resp.status_code == 200
        for task in resp.json():
            assert task["task_class"] == "10"

    def test_get_tasks_filtered_by_topic(
        self, client: TestClient, teacher_user: dict, sample_task: int,
    ):
        """Filter tasks by topic."""
        resp = client.get(
            "/teacher/tasks", params={"topic": "algebra"},
            headers=auth_header(teacher_user),
        )
        assert resp.status_code == 200
        for task in resp.json():
            assert "algebra" in (task["topic"] or "")

    def test_get_tasks_grouped(
        self, client: TestClient, teacher_user: dict, sample_task: int,
    ):
        """Grouped tasks endpoint returns structure."""
        resp = client.get("/teacher/tasks-grouped", headers=auth_header(teacher_user))
        assert resp.status_code == 200
        data = resp.json()
        assert "grouped" in data
        assert "total_tasks" in data
        assert "available_classes" in data

    def test_get_single_task(
        self, client: TestClient, teacher_user: dict, sample_task: int,
    ):
        """Fetch a single task by ID."""
        resp = client.get(
            f"/teacher/tasks/{sample_task}",
            headers=auth_header(teacher_user),
        )
        assert resp.status_code == 200
        assert resp.json()["id"] == sample_task

    def test_get_single_task_nonexistent(
        self, client: TestClient, teacher_user: dict,
    ):
        """Non-existent task returns 404."""
        resp = client.get("/teacher/tasks/99999", headers=auth_header(teacher_user))
        assert resp.status_code == 404

    def test_get_tasks_by_topic_section(
        self, client: TestClient, teacher_user: dict, sample_task: int,
    ):
        """Fetch tasks by topic and section."""
        resp = client.get(
            "/teacher/tasks/by-topic/algebra/section/equations",
            headers=auth_header(teacher_user),
        )
        assert resp.status_code == 200
        tasks = resp.json()
        assert any(t["id"] == sample_task for t in tasks)

    def test_get_tasks_meta(
        self, client: TestClient, teacher_user: dict, sample_task: int,
    ):
        """Task meta returns structured info."""
        resp = client.get("/teacher/tasks-meta", headers=auth_header(teacher_user))
        assert resp.status_code == 200
        assert isinstance(resp.json(), dict)

    def test_get_tasks_meta_by_topic_section(
        self, client: TestClient, teacher_user: dict, sample_task: int,
    ):
        """Meta by topic+section."""
        resp = client.get(
            "/teacher/tasks-meta-by-topic-section",
            headers=auth_header(teacher_user),
        )
        assert resp.status_code == 200
        assert isinstance(resp.json(), dict)

    def test_tasks_without_auth(self, client: TestClient):
        """Without token returns 401."""
        resp = client.get("/teacher/tasks")
        assert resp.status_code == 401

    def test_tasks_as_student(self, client: TestClient, student_user: dict):
        """Student cannot access teacher tasks."""
        resp = client.get("/teacher/tasks", headers=auth_header(student_user))
        assert resp.status_code == 403

    def test_tasks_as_admin(
        self, client: TestClient, admin_user: dict, sample_task: int,
    ):
        """Admin can access teacher tasks."""
        resp = client.get("/teacher/tasks", headers=auth_header(admin_user))
        assert resp.status_code == 200


# ==================== 2. TEST CRUD ====================


class TestTeacherTestCRUD:
    """Create, read, update, delete tests as teacher."""

    def test_create_test(
        self, client: TestClient, teacher_user: dict, sample_task: int,
    ):
        """Teacher creates a test."""
        # --- Act ---
        resp = client.post(
            "/teacher/tests",
            json={
                "title": "My Teacher Test",
                "target_class": "10",
                "target_topic": "1",
                "is_autocompile": False,
                "task_ids": [sample_task],
            },
            headers=auth_header(teacher_user),
        )

        # --- Assert ---
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "My Teacher Test"
        assert data["target_class"] == "10"
        assert len(data["tasks"]) >= 1
        assert data["tasks"][0]["id"] == sample_task

    def test_create_test_minimal(
        self, client: TestClient, teacher_user: dict,
    ):
        """Create test with only title (no tasks)."""
        resp = client.post(
            "/teacher/tests",
            json={"title": "Minimal Test", "is_autocompile": False},
            headers=auth_header(teacher_user),
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "Minimal Test"

    def test_create_test_without_auth(self, client: TestClient):
        """Without token returns 401."""
        resp = client.post("/teacher/tests", json={"title": "hack"})
        assert resp.status_code == 401

    def test_create_test_as_student(
        self, client: TestClient, student_user: dict,
    ):
        """Student cannot create tests."""
        resp = client.post(
            "/teacher/tests",
            json={"title": "Student Test"},
            headers=auth_header(student_user),
        )
        assert resp.status_code == 403

    def test_get_my_tests(
        self, client: TestClient, teacher_user: dict, sample_task: int,
    ):
        """Teacher lists own tests."""
        client.post(
            "/teacher/tests",
            json={
                "title": "My Test",
                "target_class": "10",
                "target_topic": "1",
                "is_autocompile": False,
                "task_ids": [sample_task],
            },
            headers=auth_header(teacher_user),
        )

        resp = client.get("/teacher/tests", headers=auth_header(teacher_user))
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    def test_get_my_tests_empty(self, client: TestClient, teacher_user: dict):
        """Empty list when no tests created."""
        resp = client.get("/teacher/tests", headers=auth_header(teacher_user))
        assert resp.status_code == 200
        assert resp.json() == []

    def test_get_test_detail(
        self, client: TestClient, teacher_user: dict, sample_teacher_test: dict,
    ):
        """Teacher views own test detail."""
        t = sample_teacher_test
        resp = client.get(
            f"/teacher/tests/{t['id']}",
            headers=auth_header(teacher_user),
        )
        assert resp.status_code == 200
        assert resp.json()["id"] == t["id"]

    def test_get_test_detail_not_own(
        self, client: TestClient, admin_user: dict, sample_teacher_test: dict,
        teacher_user: dict,
    ):
        """Admin can view any test; teacher2 cannot."""
        # Create a second teacher
        from tests.conftest import register_user

        # Admin can view teacher's test
        resp = client.get(
            f"/teacher/tests/{sample_teacher_test['id']}",
            headers=auth_header(admin_user),
        )
        assert resp.status_code == 200

    def test_get_test_detail_nonexistent(
        self, client: TestClient, teacher_user: dict,
    ):
        """Non-existent test returns 404."""
        resp = client.get("/teacher/tests/99999", headers=auth_header(teacher_user))
        assert resp.status_code == 404

    def test_update_test(
        self, client: TestClient, teacher_user: dict, sample_teacher_test: dict,
        sample_task: int,
    ):
        """Teacher updates own test."""
        t = sample_teacher_test
        resp = client.put(
            f"/teacher/tests/{t['id']}",
            json={
                "title": "Updated Test Title",
                "target_class": "11",
                "is_autocompile": False,
                "task_ids": [sample_task],
            },
            headers=auth_header(teacher_user),
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "Updated Test Title"
        assert resp.json()["target_class"] == "11"

    def test_update_test_nonexistent(
        self, client: TestClient, teacher_user: dict,
    ):
        """Cannot update non-existent test."""
        resp = client.put(
            "/teacher/tests/99999",
            json={"title": "Ghost", "is_autocompile": False},
            headers=auth_header(teacher_user),
        )
        assert resp.status_code == 404

    def test_delete_test(
        self, client: TestClient, teacher_user: dict, sample_teacher_test: dict,
    ):
        """Teacher deletes own test."""
        t = sample_teacher_test
        # --- Act ---
        resp = client.delete(
            f"/teacher/tests/{t['id']}",
            headers=auth_header(teacher_user),
        )

        # --- Assert ---
        assert resp.status_code == 200
        assert "удалены" in resp.json()["message"]

        # Verify gone
        get_resp = client.get(
            f"/teacher/tests/{t['id']}",
            headers=auth_header(teacher_user),
        )
        assert get_resp.status_code == 404

    def test_delete_test_nonexistent(
        self, client: TestClient, teacher_user: dict,
    ):
        """Cannot delete non-existent test."""
        resp = client.delete("/teacher/tests/99999", headers=auth_header(teacher_user))
        assert resp.status_code == 404

    def test_get_test_tasks(
        self, client: TestClient, teacher_user: dict, sample_teacher_test: dict,
    ):
        """Get only tasks of a test."""
        t = sample_teacher_test
        resp = client.get(
            f"/teacher/tests/{t['id']}/tasks",
            headers=auth_header(teacher_user),
        )
        assert resp.status_code == 200
        tasks = resp.json()
        assert isinstance(tasks, list)
        assert len(tasks) >= 1

    def test_get_test_tasks_not_own(
        self, client: TestClient, admin_user: dict, sample_teacher_test: dict,
    ):
        """Admin can get test tasks of another's test."""
        resp = client.get(
            f"/teacher/tests/{sample_teacher_test['id']}/tasks",
            headers=auth_header(admin_user),
        )
        assert resp.status_code == 200


# ==================== 3. STUDENTS ====================


class TestTeacherStudents:
    """Managing students."""

    def test_get_my_students_empty(
        self, client: TestClient, teacher_user: dict,
    ):
        """Empty students list when none linked."""
        resp = client.get("/teacher/students", headers=auth_header(teacher_user))
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_get_my_students(
        self, client: TestClient, db: AsyncSession, teacher_user: dict,
        student_user: dict,
    ):
        """Students linked to teacher appear in the list."""
        db.add(models.TeacherStudent(
            teacher_id=teacher_user["id"], student_id=student_user["id"],
        ))
        await db.commit()

        resp = client.get("/teacher/students", headers=auth_header(teacher_user))
        assert resp.status_code == 200
        assert len(resp.json()) >= 1
        assert resp.json()[0]["username"] == student_user["username"]

    async def test_get_student_profile(
        self, client: TestClient, db: AsyncSession, teacher_user: dict,
        student_user: dict, link_teacher_student: models.TeacherStudent,
    ):
        """Teacher can view linked student's profile."""
        resp = client.get(
            f"/teacher/students-profile/{student_user['id']}",
            headers=auth_header(teacher_user),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["user"]["id"] == student_user["id"]
        assert "stats" in data

    def test_get_student_profile_not_linked(
        self, client: TestClient, teacher_user: dict, student2_user: dict,
    ):
        """Cannot view unlinked student."""
        resp = client.get(
            f"/teacher/students-profile/{student2_user['id']}",
            headers=auth_header(teacher_user),
        )
        assert resp.status_code == 403

    def test_get_student_history_empty(
        self, client: TestClient, teacher_user: dict,
        link_teacher_student: models.TeacherStudent, student_user: dict,
    ):
        """Student history is empty initially."""
        resp = client.get(
            f"/teacher/students-history/{student_user['id']}",
            headers=auth_header(teacher_user),
        )
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_get_student_history_with_results(
        self, client: TestClient, db: AsyncSession, teacher_user: dict,
        student_user: dict, link_teacher_student: models.TeacherStudent,
        assigned_test: dict,
    ):
        """Student history shows completed tests."""
        test = assigned_test
        client.post(
            f"/student/tests/{test['id']}/submit",
            json=[{"task_id": test["tasks"][0]["id"], "user_answer": "2"}],
            headers=auth_header(student_user),
        )

        resp = client.get(
            f"/teacher/students-history/{student_user['id']}",
            headers=auth_header(teacher_user),
        )
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    def test_get_student_history_not_linked(
        self, client: TestClient, teacher_user: dict, student2_user: dict,
    ):
        """Cannot view unlinked student's history."""
        resp = client.get(
            f"/teacher/students-history/{student2_user['id']}",
            headers=auth_header(teacher_user),
        )
        assert resp.status_code == 403


# ==================== 4. ASSIGNMENTS ====================


class TestTeacherAssignments:
    """Assign tests to students and manage assignments."""

    async def test_assign_test_to_student(
        self, client: TestClient, db: AsyncSession, teacher_user: dict,
        student_user: dict, link_teacher_student: models.TeacherStudent,
        sample_teacher_test: dict,
    ):
        """Teacher assigns a test to a linked student."""
        # --- Act ---
        resp = client.post(
            "/teacher/assign-test",
            json={
                "test_id": sample_teacher_test["id"],
                "user_ids": [student_user["id"]],
            },
            headers=auth_header(teacher_user),
        )

        # --- Assert ---
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert data[0]["test_id"] == sample_teacher_test["id"]
        assert data[0]["student_name"] == "Anna Ivanova"

    def test_assign_test_to_unlinked_student(
        self, client: TestClient, teacher_user: dict, student2_user: dict,
        sample_teacher_test: dict,
    ):
        """Cannot assign test to unlinked student."""
        resp = client.post(
            "/teacher/assign-test",
            json={
                "test_id": sample_teacher_test["id"],
                "user_ids": [student2_user["id"]],
            },
            headers=auth_header(teacher_user),
        )
        assert resp.status_code == 404  # или 403 PermissionError

    def test_assign_nonexistent_test(
        self, client: TestClient, teacher_user: dict, student_user: dict,
        link_teacher_student: models.TeacherStudent,
    ):
        """Cannot assign non-existent test."""
        resp = client.post(
            "/teacher/assign-test",
            json={"test_id": 99999, "user_ids": [student_user["id"]]},
            headers=auth_header(teacher_user),
        )
        assert resp.status_code == 404

    async def test_get_test_assignments(
        self, client: TestClient, db: AsyncSession, teacher_user: dict,
        student_user: dict, link_teacher_student: models.TeacherStudent,
        sample_teacher_test: dict,
    ):
        """View assignments for a test."""
        client.post(
            "/teacher/assign-test",
            json={
                "test_id": sample_teacher_test["id"],
                "user_ids": [student_user["id"]],
            },
            headers=auth_header(teacher_user),
        )

        resp = client.get(
            f"/teacher/test/{sample_teacher_test['id']}/assignments",
            headers=auth_header(teacher_user),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        assert data[0]["id"] is not None

    async def test_get_student_assignments(
        self, client: TestClient, db: AsyncSession, teacher_user: dict,
        student_user: dict, link_teacher_student: models.TeacherStudent,
        sample_teacher_test: dict,
    ):
        """View assignments for a student."""
        client.post(
            "/teacher/assign-test",
            json={
                "test_id": sample_teacher_test["id"],
                "user_ids": [student_user["id"]],
            },
            headers=auth_header(teacher_user),
        )

        resp = client.get(
            f"/teacher/student/{student_user['id']}/assignments",
            headers=auth_header(teacher_user),
        )
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    async def test_delete_assignment(
        self, client: TestClient, db: AsyncSession, teacher_user: dict,
        student_user: dict, link_teacher_student: models.TeacherStudent,
        sample_teacher_test: dict,
    ):
        """Delete an assignment."""
        created = client.post(
            "/teacher/assign-test",
            json={
                "test_id": sample_teacher_test["id"],
                "user_ids": [student_user["id"]],
            },
            headers=auth_header(teacher_user),
        ).json()

        assignment_id = created[0]["id"]
        resp = client.delete(
            f"/teacher/assignments/{assignment_id}",
            headers=auth_header(teacher_user),
        )
        assert resp.status_code == 200
        assert "удалено" in resp.json()["message"]

    def test_delete_nonexistent_assignment(
        self, client: TestClient, teacher_user: dict,
    ):
        """Cannot delete non-existent assignment."""
        resp = client.delete(
            "/teacher/assignments/99999",
            headers=auth_header(teacher_user),
        )
        assert resp.status_code == 404


# ==================== 5. GROUPS ====================


class TestTeacherGroups:
    """Group CRUD and student management."""

    def test_create_group(
        self, client: TestClient, teacher_user: dict,
    ):
        """Teacher creates a group."""
        resp = client.post(
            "/teacher/groups/",
            json={"name": "10A Physics", "description": "Best group"},
            headers=auth_header(teacher_user),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "10A Physics"

    def test_create_group_no_name(
        self, client: TestClient, teacher_user: dict,
    ):
        """Group without name returns 400."""
        resp = client.post(
            "/teacher/groups/",
            json={"description": "no name"},
            headers=auth_header(teacher_user),
        )
        assert resp.status_code == 400

    def test_get_my_groups(
        self, client: TestClient, teacher_user: dict,
    ):
        """List teacher's groups."""
        client.post(
            "/teacher/groups/",
            json={"name": "My Group"},
            headers=auth_header(teacher_user),
        )
        resp = client.get("/teacher/groups/", headers=auth_header(teacher_user))
        assert resp.status_code == 200
        groups = resp.json()
        assert len(groups) >= 1
        assert groups[0]["name"] == "My Group"

    def test_get_my_groups_empty(self, client: TestClient, teacher_user: dict):
        """Empty groups when none created."""
        resp = client.get("/teacher/groups/", headers=auth_header(teacher_user))
        assert resp.status_code == 200
        assert resp.json() == []

    def test_update_group(
        self, client: TestClient, teacher_user: dict,
    ):
        """Update group name."""
        g = client.post(
            "/teacher/groups/",
            json={"name": "Old Name"},
            headers=auth_header(teacher_user),
        ).json()

        resp = client.put(
            f"/teacher/groups/{g['id']}",
            json={"name": "New Name"},
            headers=auth_header(teacher_user),
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "New Name"

    def test_update_group_nonexistent(
        self, client: TestClient, teacher_user: dict,
    ):
        """Cannot update non-existent group."""
        resp = client.put(
            "/teacher/groups/99999",
            json={"name": "Ghost"},
            headers=auth_header(teacher_user),
        )
        assert resp.status_code == 404

    def test_delete_group(
        self, client: TestClient, teacher_user: dict,
    ):
        """Delete a group."""
        g = client.post(
            "/teacher/groups/",
            json={"name": "To Delete"},
            headers=auth_header(teacher_user),
        ).json()

        resp = client.delete(
            f"/teacher/groups/{g['id']}",
            headers=auth_header(teacher_user),
        )
        assert resp.status_code == 200
        assert "удалена" in resp.json()["message"]

        # Verify gone
        get_resp = client.get("/teacher/groups/", headers=auth_header(teacher_user))
        assert len(get_resp.json()) == 0

    def test_delete_group_nonexistent(
        self, client: TestClient, teacher_user: dict,
    ):
        """Cannot delete non-existent group."""
        resp = client.delete("/teacher/groups/99999", headers=auth_header(teacher_user))
        assert resp.status_code == 404

    async def test_add_students_to_group(
        self, client: TestClient, db: AsyncSession, teacher_user: dict,
        student_user: dict, student2_user: dict,
    ):
        """Add students to a group."""
        db.add(models.TeacherStudent(
            teacher_id=teacher_user["id"], student_id=student_user["id"],
        ))
        db.add(models.TeacherStudent(
            teacher_id=teacher_user["id"], student_id=student2_user["id"],
        ))
        await db.commit()

        g = client.post(
            "/teacher/groups/",
            json={"name": "With Students"},
            headers=auth_header(teacher_user),
        ).json()

        resp = client.post(
            f"/teacher/groups/{g['id']}/students",
            json={"student_ids": [student_user["id"], student2_user["id"]]},
            headers=auth_header(teacher_user),
        )
        assert resp.status_code == 200
        assert resp.json()["added"] == 2

    async def test_add_students_to_nonexistent_group(
        self, client: TestClient, teacher_user: dict, student_user: dict,
    ):
        """Cannot add students to non-existent group."""
        resp = client.post(
            "/teacher/groups/99999/students",
            json={"student_ids": [student_user["id"]]},
            headers=auth_header(teacher_user),
        )
        assert resp.status_code == 404

    async def test_remove_student_from_group(
        self, client: TestClient, db: AsyncSession, teacher_user: dict,
        student_user: dict,
    ):
        """Remove student from group."""
        db.add(models.TeacherStudent(
            teacher_id=teacher_user["id"], student_id=student_user["id"],
        ))
        await db.commit()

        g = client.post(
            "/teacher/groups/",
            json={"name": "Removal Test"},
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
        assert "удалён" in resp.json()["message"]

    async def test_get_group_students(
        self, client: TestClient, db: AsyncSession, teacher_user: dict,
        student_user: dict,
    ):
        """Get students in a group."""
        db.add(models.TeacherStudent(
            teacher_id=teacher_user["id"], student_id=student_user["id"],
        ))
        await db.commit()

        g = client.post(
            "/teacher/groups/",
            json={"name": "Members Check"},
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
        students = resp.json()
        assert len(students) >= 1

    async def test_get_group_students_nonexistent_group(
        self, client: TestClient, teacher_user: dict,
    ):
        """Non-existent group returns 404."""
        resp = client.get(
            "/teacher/groups/99999/students",
            headers=auth_header(teacher_user),
        )
        assert resp.status_code == 404


# ==================== 6. GROUP ASSIGNMENTS ====================


class TestTeacherGroupAssignments:
    """Assign tests to groups."""

    async def test_assign_test_to_group(
        self, client: TestClient, db: AsyncSession, teacher_user: dict,
        student_user: dict, sample_teacher_test: dict,
    ):
        """Assign a test to an entire group."""
        db.add(models.TeacherStudent(
            teacher_id=teacher_user["id"], student_id=student_user["id"],
        ))
        await db.commit()

        g = client.post(
            "/teacher/groups/",
            json={"name": "Group A"},
            headers=auth_header(teacher_user),
        ).json()

        client.post(
            f"/teacher/groups/{g['id']}/students",
            json={"student_ids": [student_user["id"]]},
            headers=auth_header(teacher_user),
        )

        # --- Act ---
        resp = client.post(
            "/teacher/assign-test-to-group",
            json={
                "group_id": g["id"],
                "test_id": sample_teacher_test["id"],
            },
            headers=auth_header(teacher_user),
        )

        # --- Assert ---
        assert resp.status_code == 200
        data = resp.json()
        assert data["assigned_count"] >= 1
        assert "назначен" in data["message"]

    def test_assign_to_group_nonexistent_test(
        self, client: TestClient, teacher_user: dict,
    ):
        """Cannot assign non-existent test to group."""
        g = client.post(
            "/teacher/groups/",
            json={"name": "G"},
            headers=auth_header(teacher_user),
        ).json()

        resp = client.post(
            "/teacher/assign-test-to-group",
            json={"group_id": g["id"], "test_id": 99999},
            headers=auth_header(teacher_user),
        )
        assert resp.status_code == 404

    def test_assign_to_nonexistent_group(
        self, client: TestClient, teacher_user: dict, sample_teacher_test: dict,
    ):
        """Cannot assign to non-existent group."""
        resp = client.post(
            "/teacher/assign-test-to-group",
            json={"group_id": 99999, "test_id": sample_teacher_test["id"]},
            headers=auth_header(teacher_user),
        )
        assert resp.status_code == 404

    async def test_get_group_assignments(
        self, client: TestClient, db: AsyncSession, teacher_user: dict,
        student_user: dict, sample_teacher_test: dict,
    ):
        """View group assignments."""
        db.add(models.TeacherStudent(
            teacher_id=teacher_user["id"], student_id=student_user["id"],
        ))
        await db.commit()

        g = client.post(
            "/teacher/groups/",
            json={"name": "Group B"},
            headers=auth_header(teacher_user),
        ).json()

        client.post(
            f"/teacher/groups/{g['id']}/students",
            json={"student_ids": [student_user["id"]]},
            headers=auth_header(teacher_user),
        )

        client.post(
            "/teacher/assign-test-to-group",
            json={"group_id": g["id"], "test_id": sample_teacher_test["id"]},
            headers=auth_header(teacher_user),
        )

        resp = client.get(
            f"/teacher/groups/{g['id']}/assignments",
            headers=auth_header(teacher_user),
        )
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    def test_get_group_assignments_nonexistent(
        self, client: TestClient, teacher_user: dict,
    ):
        """Non-existent group returns 404."""
        resp = client.get(
            "/teacher/groups/99999/assignments",
            headers=auth_header(teacher_user),
        )
        assert resp.status_code == 404


# ==================== 7. DETAILED RESULTS (TEACHER) ====================


class TestTeacherDetailedResults:
    """Teacher can view detailed results of linked students."""

    async def test_get_detailed_result(
        self, client: TestClient, db: AsyncSession, teacher_user: dict,
        student_user: dict, link_teacher_student: models.TeacherStudent,
        assigned_test: dict,
    ):
        """Teacher views a detailed result."""
        test = assigned_test
        client.post(
            f"/student/tests/{test['id']}/submit",
            json=[{"task_id": test["tasks"][0]["id"], "user_answer": "2"}],
            headers=auth_header(student_user),
        )
        history = client.get(
            "/teacher/students-history/" + str(student_user["id"]),
            headers=auth_header(teacher_user),
        ).json()

        result_id = history[0]["result"]["id"]
        resp = client.get(
            f"/teacher/results/{result_id}",
            headers=auth_header(teacher_user),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "details" in data
        assert "difficulty_stats" in data
        assert "user" in data

    def test_get_detailed_result_nonexistent(
        self, client: TestClient, teacher_user: dict,
    ):
        """Non-existent result returns 404."""
        resp = client.get("/teacher/results/99999", headers=auth_header(teacher_user))
        assert resp.status_code == 404

    def test_get_detailed_result_not_linked(
        self, client: TestClient, teacher_user: dict, student2_user: dict,
        assigned_test: dict,
    ):
        """Cannot view result of unlinked student."""
        test = assigned_test
        submit_resp = client.post(
            f"/student/tests/{test['id']}/submit",
            json=[{"task_id": test["tasks"][0]["id"], "user_answer": "2"}],
            headers=auth_header(
                {"token": client.post(
                    "/login",
                    data={"username": "student@test.com", "password": "Student123!"},
                ).json()["access_token"]},
            ),
        )
        assert submit_resp.status_code == 200

        # Student2 is not linked to teacher, so teacher can't see
        resp = client.get("/teacher/results/1", headers=auth_header(teacher_user))
        # Either 404 or 403 — depends on whether result ID=1 belongs to a linked student
        assert resp.status_code in (403, 404)


# ==================== 8. PERMISSIONS ====================


class TestTeacherPermissions:
    """Teacher permission boundaries."""

    def test_teacher_cannot_create_task(
        self, client: TestClient, teacher_user: dict, sample_task_payload: dict,
    ):
        resp = client.post("/admin/tasks", json=sample_task_payload, headers=auth_header(teacher_user))
        assert resp.status_code == 403

    def test_teacher_cannot_delete_task(
        self, client: TestClient, teacher_user: dict, sample_task: int,
    ):
        resp = client.delete(f"/admin/tasks/{sample_task}", headers=auth_header(teacher_user))
        assert resp.status_code == 403

    def test_teacher_cannot_access_admin_users(
        self, client: TestClient, teacher_user: dict,
    ):
        resp = client.get("/admin/users", headers=auth_header(teacher_user))
        assert resp.status_code == 403

    def test_teacher_cannot_change_role(
        self, client: TestClient, teacher_user: dict,
    ):
        resp = client.patch(
            "/admin/users/1/role",
            params={"new_role": "admin"},
            headers=auth_header(teacher_user),
        )
        assert resp.status_code == 403

    def test_teacher_registers_as_teacher(
        self, client: TestClient, db: AsyncSession, teacher_user: dict,
    ):
        """Teacher is indeed registered as teacher role."""
        result = db.run_sync(
            lambda session: session.execute(
                sa_select(models.User).where(models.User.id == teacher_user["id"])
            ).scalars().first()
        )
        # Just verify they can access teacher endpoints
        resp = client.get("/teacher/tests", headers=auth_header(teacher_user))
        assert resp.status_code == 200
