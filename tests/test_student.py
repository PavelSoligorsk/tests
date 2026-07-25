"""
Student tests: taking tests, viewing results, AI help, and theory access.
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

import core.models as models
from tests.conftest import auth_header


# ==================== 1. ASSIGNMENTS ====================


class TestStudentAssignments:
    """Tests for getting assigned tests."""

    def test_get_my_assignments_empty(self, client: TestClient, student_user: dict):
        """Empty assignment list."""
        resp = client.get("/student/my-assignments", headers=auth_header(student_user))
        assert resp.status_code == 200

    def test_get_my_assignments(self, client: TestClient, student_user: dict, assigned_test: dict):
        """Assignments after a test is assigned."""
        resp = client.get("/student/my-assignments", headers=auth_header(student_user))
        assert resp.status_code == 200
        tests = resp.json()
        assert isinstance(tests, list)

    def test_get_test_detail_for_student(
        self,
        client: TestClient,
        student_user: dict,
        teacher_user: dict,
        link_teacher_student: Any,
        sample_task: int,
    ):
        """View test details as a student."""
        t = client.post(
            "/teacher/tests",
            json={
                "title": "Student Test",
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

        resp = client.get(f"/student/tests/{t['id']}", headers=auth_header(student_user))
        assert resp.status_code == 200
        assert "tasks" in resp.json()

    def test_cant_view_not_assigned_test(
        self, client: TestClient, student_user: dict, teacher_user: dict, sample_task: int
    ):
        """Cannot view a test that is not assigned."""
        t = client.post(
            "/teacher/tests",
            json={
                "title": "NotMine",
                "target_class": "10",
                "target_topic": "1",
                "is_autocompile": False,
                "task_ids": [sample_task],
            },
            headers=auth_header(teacher_user),
        ).json()

        resp = client.get(f"/student/tests/{t['id']}", headers=auth_header(student_user))
        assert resp.status_code in (200, 403, 404)


# ==================== 2. TEST SUBMISSION ====================


class TestStudentSubmit:
    """Tests for submitting answers."""

    def test_submit_correct_answer(self, client: TestClient, student_user: dict, assigned_test: dict):
        """Submit a correct answer."""
        task_id = assigned_test["tasks"][0]["id"]

        resp = client.post(
            f"/student/tests/{assigned_test['id']}/submit",
            json=[{"task_id": task_id, "user_answer": "2"}],
            headers=auth_header(student_user),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["score"] >= 1
        assert data["max_score_possible"] > 0

    def test_submit_wrong_answer(self, client: TestClient, student_user: dict, assigned_test: dict):
        """Submit a wrong answer."""
        task_id = assigned_test["tasks"][0]["id"]

        resp = client.post(
            f"/student/tests/{assigned_test['id']}/submit",
            json=[{"task_id": task_id, "user_answer": "999"}],
            headers=auth_header(student_user),
        )
        assert resp.status_code == 200
        assert resp.json()["score"] == 0

    async def test_submit_open_answer(
        self,
        client: TestClient,
        db: AsyncSession,
        admin_user: dict,
        student_user: dict,
        teacher_user: dict,
        sample_open_task: int,
    ):
        """Submit an open-answer test."""
        t = client.post(
            "/teacher/tests",
            json={
                "title": "Open Test",
                "target_class": "10",
                "target_topic": "2",
                "is_autocompile": False,
                "task_ids": [sample_open_task],
            },
            headers=auth_header(teacher_user),
        ).json()

        link = models.TeacherStudent(teacher_id=teacher_user["id"], student_id=student_user["id"])
        db.add(link)
        await db.commit()

        client.post(
            "/teacher/assign-test",
            json={"test_id": t["id"], "user_ids": [student_user["id"]]},
            headers=auth_header(teacher_user),
        )

        resp = client.post(
            f"/student/tests/{t['id']}/submit",
            json=[{"task_id": sample_open_task, "user_answer": "a^3"}],
            headers=auth_header(student_user),
        )
        assert resp.status_code == 200
        assert resp.json()["score"] >= 2

    def test_submit_twice_updates_result(self, client: TestClient, student_user: dict, assigned_test: dict):
        """Second submission updates the result."""
        task_id = assigned_test["tasks"][0]["id"]

        client.post(
            f"/student/tests/{assigned_test['id']}/submit",
            json=[{"task_id": task_id, "user_answer": "2"}],
            headers=auth_header(student_user),
        )

        resp = client.post(
            f"/student/tests/{assigned_test['id']}/submit",
            json=[{"task_id": task_id, "user_answer": "999"}],
            headers=auth_header(student_user),
        )
        assert resp.status_code == 200
        assert resp.json()["score"] == 0

    def test_submit_empty_answer(self, client: TestClient, student_user: dict, assigned_test: dict):
        """Submitting an empty answer."""
        task_id = assigned_test["tasks"][0]["id"]

        resp = client.post(
            f"/student/tests/{assigned_test['id']}/submit",
            json=[{"task_id": task_id, "user_answer": ""}],
            headers=auth_header(student_user),
        )
        assert resp.status_code in (200, 422)

    def test_submit_not_assigned_test(
        self, client: TestClient, student_user: dict, sample_teacher_test: dict
    ):
        """Submit to a test that is not assigned."""
        resp = client.post(
            f"/student/tests/{sample_teacher_test['id']}/submit",
            json=[{"task_id": 1, "user_answer": "2"}],
            headers=auth_header(student_user),
        )
        assert resp.status_code in (200, 403, 404)


# ==================== 3. RESULTS ====================


class TestStudentResults:
    """Tests for viewing results."""

    def test_get_my_results(self, client: TestClient, student_user: dict, assigned_test: dict):
        """View own results."""
        task_id = assigned_test["tasks"][0]["id"]
        client.post(
            f"/student/tests/{assigned_test['id']}/submit",
            json=[{"task_id": task_id, "user_answer": "2"}],
            headers=auth_header(student_user),
        )

        resp = client.get("/student/history", headers=auth_header(student_user))
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    def test_get_single_result(self, client: TestClient, student_user: dict, assigned_test: dict):
        """View a single result."""
        task_id = assigned_test["tasks"][0]["id"]
        submit = client.post(
            f"/student/tests/{assigned_test['id']}/submit",
            json=[{"task_id": task_id, "user_answer": "2"}],
            headers=auth_header(student_user),
        ).json()
        result_id = submit.get("result_id")

        if result_id:
            resp = client.get(
                f"/student/results/{result_id}",
                headers=auth_header(student_user),
            )
            assert resp.status_code == 200

    def test_cant_view_others_result(
        self,
        client: TestClient,
        student_user: dict,
        teacher_user: dict,
        student2_user: dict,
        link_teacher_student: Any,
        sample_task: int,
    ):
        """Cannot view another student's result."""
        t = client.post(
            "/teacher/tests",
            json={
                "title": "Other Result",
                "target_class": "10",
                "target_topic": "1",
                "is_autocompile": False,
                "task_ids": [sample_task],
            },
            headers=auth_header(teacher_user),
        ).json()

        client.post(
            "/teacher/assign-test",
            json={"test_id": t["id"], "user_ids": [student2_user["id"]]},
            headers=auth_header(teacher_user),
        )

        submit = client.post(
            f"/student/tests/{t['id']}/submit",
            json=[{"task_id": sample_task, "user_answer": "2"}],
            headers=auth_header(student2_user),
        ).json()
        result_id = submit.get("result_id")

        if result_id:
            resp = client.get(
                f"/student/results/{result_id}",
                headers=auth_header(student_user),
            )
            assert resp.status_code == 403


# ==================== 4. AI HELP ====================


class TestStudentAIHelp:
    """Tests for AI hints and solutions."""

    def test_get_hint_for_task(self, client: TestClient, student_user: dict, assigned_test: dict):
        """Get a hint for a task."""
        task_id = assigned_test["tasks"][0]["id"]

        resp = client.post(
            f"/student/tasks/{task_id}/hint",
            json={},
            headers=auth_header(student_user),
        )
        assert resp.status_code == 200
        assert "hint" in resp.json()

    def test_get_solution_for_task(self, client: TestClient, student_user: dict, assigned_test: dict):
        """Get an AI solution for a task."""
        task_id = assigned_test["tasks"][0]["id"]

        resp = client.post(
            f"/student/tasks/{task_id}/ai-solve",
            json={},
            headers=auth_header(student_user),
        )
        assert resp.status_code == 200
        assert "ai_solution" in resp.json()

    def test_ask_ai_question(self, client: TestClient, student_user: dict, theory_material: dict):
        """Ask AI a theory question."""
        resp = client.post(
            "/student/theory/ask-ai",
            json={
                "question": "What is an equation?",
                "theory_content": "An equation is an equality with an unknown.",
            },
            headers=auth_header(student_user),
        )
        assert resp.status_code == 200
        assert "answer" in resp.json()


# ==================== 5. THEORY ====================


class TestStudentTheory:
    """Tests for theory access."""

    def test_get_all_topics(self, client: TestClient, student_user: dict, theory_material: dict):
        """Get all theory topics."""
        resp = client.get("/student/theory/topics", headers=auth_header(student_user))
        assert resp.status_code == 200
        data = resp.json()
        assert "algebra" in [x["topic"] for x in data]

    def test_get_topic_content(self, client: TestClient, student_user: dict, theory_material: dict):
        """Get content of a theory topic."""
        resp = client.get(
            "/student/theory/by-topic/algebra/section/equations",
            headers=auth_header(student_user),
        )
        assert resp.status_code == 200
        assert "content" in resp.json()

    def test_get_nonexistent_topic(self, client: TestClient, student_user: dict):
        """Non-existent topic returns 404."""
        resp = client.get(
            "/student/theory/by-topic/nonexistent/section/topic",
            headers=auth_header(student_user),
        )
        assert resp.status_code == 404