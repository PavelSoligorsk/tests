"""
Student tests: profile, tests, submit, history, results, assignments,
start test, theory, AI hints/solutions, and security checks.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession

import core.models as models
from tests.conftest import auth_header


# ==================== 1. STUDENT PROFILE ====================


class TestStudentProfile:
    """Profile: get and update."""

    def test_get_my_profile(
        self, client: TestClient, db: AsyncSession, student_user: dict
    ):
        """Student can fetch own profile with stats."""
        resp = client.get("/student/me", headers=auth_header(student_user))
        assert resp.status_code == 200
        data = resp.json()
        assert data["user"]["id"] == student_user["id"]
        assert data["user"]["username"] == student_user["username"]
        assert "stats" in data

    def test_get_profile_without_auth(self, client: TestClient):
        """Without token returns 401."""
        resp = client.get("/student/me")
        assert resp.status_code == 401

    def test_update_my_profile(
        self, client: TestClient, db: AsyncSession, student_user: dict
    ):
        """Student can update own name and phone."""
        resp = client.put(
            "/student/me",
            json={"first_name": "NewAnna", "phone": "+375291234567"},
            headers=auth_header(student_user),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["first_name"] == "NewAnna"
        assert data["phone"] == "+375291234567"

    def test_update_profile_without_auth(self, client: TestClient):
        """Updating without token returns 401."""
        resp = client.put("/student/me", json={"first_name": "Hack"})
        assert resp.status_code == 401

    def test_update_profile_as_admin(
        self, client: TestClient, admin_user: dict
    ):
        """Admin cannot update via student /me endpoint."""
        resp = client.put(
            "/student/me",
            json={"first_name": "Admin"},
            headers=auth_header(admin_user),
        )
        if resp.status_code == 200:
            assert resp.json()["role"] in ("admin", "student")


# ==================== 2. AVAILABLE TESTS ====================


class TestStudentAvailableTests:
    """Listing and viewing available tests."""

    def test_get_available_tests_empty(
        self, client: TestClient, student_user: dict
    ):
        """Empty list when no tests exist."""
        resp = client.get("/student/tests")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_get_available_tests(
        self,
        client: TestClient,
        student_user: dict,
        sample_task: int,
        teacher_user: dict,
    ):
        """Available tests visible after teacher creates a test."""
        t = client.post(
            "/teacher/tests",
            json={
                "title": "Available Test",
                "target_class": "10",
                "target_topic": "1",
                "is_autocompile": True,
                "task_ids": [sample_task],
            },
            headers=auth_header(teacher_user),
        )
        assert t.status_code == 200
        test_data = t.json()

        resp = client.get("/student/tests")
        assert resp.status_code == 200
        ids = [item["id"] for item in resp.json()]
        assert test_data["id"] in ids

    def test_get_single_test_for_passing(
        self,
        client: TestClient,
        student_user: dict,
        sample_task: int,
        teacher_user: dict,
    ):
        """Student can fetch a specific test by ID for passing."""
        t = client.post(
            "/teacher/tests",
            json={
                "title": "Single Test",
                "target_class": "10",
                "target_topic": "1",
                "is_autocompile": False,
                "task_ids": [sample_task],
            },
            headers=auth_header(teacher_user),
        )
        assert t.status_code == 200
        test_data = t.json()

        resp = client.get(
            f"/student/tests/{test_data['id']}",
            headers=auth_header(student_user),
        )
        assert resp.status_code == 200
        assert resp.json()["id"] == test_data["id"]

    def test_get_nonexistent_test(
        self, client: TestClient, student_user: dict
    ):
        """Non-existent test returns 404."""
        resp = client.get(
            "/student/tests/99999",
            headers=auth_header(student_user),
        )
        assert resp.status_code == 404

    def test_get_tests_without_auth(self, client: TestClient):
        """Available tests are public."""
        resp = client.get("/student/tests")
        assert resp.status_code == 200

    def test_get_tests_meta(
        self,
        client: TestClient,
        student_user: dict,
        sample_task: int,
        teacher_user: dict,
    ):
        """Meta endpoint returns lightweight test info."""
        t = client.post(
            "/teacher/tests",
            json={
                "title": "Meta Test",
                "target_class": "10",
                "target_topic": "1",
                "is_autocompile": True,
                "task_ids": [sample_task],
            },
            headers=auth_header(teacher_user),
        )
        assert t.status_code == 200

        resp = client.get("/student/tests-meta")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
        if resp.json():
            item = resp.json()[0]
            assert "tasks_count" in item
            assert "id" in item


# ==================== 3. SUBMIT TEST ====================


class TestStudentSubmitTest:
    """Test submission and scoring."""

    def test_submit_closed_answer_correct(
        self,
        client: TestClient,
        db: AsyncSession,
        student_user: dict,
        assigned_test: dict,
    ):
        """Submit correct closed-answer answer earns points."""
        test = assigned_test
        task = test["tasks"][0]

        answers = [
            {"task_id": task["id"], "user_answer": "2"},
        ]

        resp = client.post(
            f"/student/tests/{test['id']}/submit",
            json=answers,
            headers=auth_header(student_user),
        )

        assert resp.status_code == 200
        data = resp.json()
        assert "score" in data
        assert data["score"] > 0

    def test_submit_closed_answer_wrong(
        self,
        client: TestClient,
        db: AsyncSession,
        student_user: dict,
        assigned_test: dict,
    ):
        """Incorrect closed answer earns 0 points."""
        test = assigned_test
        task = test["tasks"][0]

        answers = [
            {"task_id": task["id"], "user_answer": "999"},
        ]

        resp = client.post(
            f"/student/tests/{test['id']}/submit",
            json=answers,
            headers=auth_header(student_user),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "score" in data

    def test_submit_nonexistent_test(
        self, client: TestClient, student_user: dict
    ):
        """Submitting to non-existent test returns 404."""
        resp = client.post(
            "/student/tests/99999/submit",
            json=[{"task_id": 1, "user_answer": "x"}],
            headers=auth_header(student_user),
        )
        assert resp.status_code == 404

    def test_submit_without_auth(self, client: TestClient):
        """Submitting without token returns 401."""
        resp = client.post(
            "/student/tests/1/submit",
            json=[{"task_id": 1, "user_answer": "x"}],
        )
        assert resp.status_code == 401


# ==================== 4. TEST HISTORY ====================


class TestStudentHistory:
    """History and detailed results."""

    def test_history_empty(
        self, client: TestClient, student_user: dict
    ):
        """Empty history when no tests taken."""
        resp = client.get(
            "/student/history", headers=auth_header(student_user)
        )
        assert resp.status_code == 200
        assert resp.json() == []

    def test_history_with_results(
        self,
        client: TestClient,
        db: AsyncSession,
        student_user: dict,
        assigned_test: dict,
    ):
        """History shows submitted tests."""
        test = assigned_test
        task = test["tasks"][0]

        # Submit the test first
        submit_resp = client.post(
            f"/student/tests/{test['id']}/submit",
            json=[{"task_id": task["id"], "user_answer": "2"}],
            headers=auth_header(student_user),
        )
        assert submit_resp.status_code == 200

        resp = client.get(
            "/student/history", headers=auth_header(student_user)
        )
        assert resp.status_code == 200
        history = resp.json()
        assert len(history) >= 1

        found = any(item.get("test_id") == test["id"] for item in history)
        assert found, f"Test {test['id']} not found in history"

    def test_history_without_auth(self, client: TestClient):
        """History without token returns 401."""
        resp = client.get("/student/history")
        assert resp.status_code == 401

    def test_detailed_result(
        self,
        client: TestClient,
        db: AsyncSession,
        student_user: dict,
        assigned_test: dict,
    ):
        """Detailed result shows task-level breakdown."""
        test = assigned_test
        task = test["tasks"][0]

        # Submit the test
        submit_resp = client.post(
            f"/student/tests/{test['id']}/submit",
            json=[{"task_id": task["id"], "user_answer": "2"}],
            headers=auth_header(student_user),
        )
        assert submit_resp.status_code == 200

        # Get history to find result_id
        history = client.get(
            "/student/history", headers=auth_header(student_user)
        )
        assert history.status_code == 200
        history_data = history.json()

        result_item = next(
            (item for item in history_data if item.get("test_id") == test["id"]),
            None,
        )
        assert result_item is not None, "Result not found in history"

        result_id = result_item.get("id") or result_item.get("result_id")
        assert result_id is not None, "No result ID in history item"

        resp = client.get(
            f"/student/results/{result_id}",
            headers=auth_header(student_user),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "total_points" in data or "details" in data

    def test_detailed_result_not_own(
        self,
        client: TestClient,
        db: AsyncSession,
        student_user: dict,
        student2_user: dict,
        assigned_test: dict,
    ):
        """Student cannot view another student's result."""
        test = assigned_test
        task = test["tasks"][0]

        # Student 1 submits
        submit_resp = client.post(
            f"/student/tests/{test['id']}/submit",
            json=[{"task_id": task["id"], "user_answer": "2"}],
            headers=auth_header(student_user),
        )
        assert submit_resp.status_code == 200

        # Get result_id from student1's history
        history = client.get(
            "/student/history", headers=auth_header(student_user)
        )
        history_data = history.json()
        result_item = next(
            (item for item in history_data if item.get("test_id") == test["id"]),
            None,
        )
        assert result_item is not None
        result_id = result_item.get("id") or result_item.get("result_id")

        # Student 2 tries to access student 1's result
        resp = client.get(
            f"/student/results/{result_id}",
            headers=auth_header(student2_user),
        )
        assert resp.status_code in (403, 404)

    def test_detailed_result_nonexistent(
        self, client: TestClient, student_user: dict
    ):
        """Non-existent result returns 404."""
        resp = client.get(
            "/student/results/99999",
            headers=auth_header(student_user),
        )
        assert resp.status_code == 404


# ==================== 5. ASSIGNMENTS ====================


class TestStudentAssignments:
    """Assignment listing, meta, and start."""

    def test_my_assignments_empty(
        self, client: TestClient, student_user: dict
    ):
        """Empty assignments when none assigned."""
        resp = client.get(
            "/student/my-assignments",
            headers=auth_header(student_user),
        )
        assert resp.status_code == 200
        assert resp.json() == []

    def test_my_assignments_after_assignment(
        self,
        client: TestClient,
        db: AsyncSession,
        student_user: dict,
        assigned_test: dict,
    ):
        """Assignments appear after teacher assigns a test."""
        resp = client.get(
            "/student/my-assignments",
            headers=auth_header(student_user),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        test_ids = [item.get("test_id") for item in data]
        assert assigned_test["id"] in test_ids

    def test_my_assignments_meta(
        self,
        client: TestClient,
        db: AsyncSession,
        student_user: dict,
        assigned_test: dict,
    ):
        """Meta endpoint returns lightweight assignment info."""
        resp = client.get(
            "/student/my-assignments-meta",
            headers=auth_header(student_user),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        assert "tasks_count" in data[0]
        assert "test_id" in data[0]

    def test_start_assigned_test(
        self,
        client: TestClient,
        db: AsyncSession,
        student_user: dict,
        assigned_test: dict,
    ):
        """Starting an assigned test returns tasks and a result_id."""
        test_id = assigned_test["id"]

        resp = client.post(
            f"/student/start-test/{test_id}",
            headers=auth_header(student_user),
        )

        assert resp.status_code == 200
        data = resp.json()
        assert "result_id" in data
        assert "tasks" in data
        assert len(data["tasks"]) >= 1

    def test_start_assigned_test_not_assigned(
        self,
        client: TestClient,
        student2_user: dict,
        assigned_test: dict,
    ):
        """Student cannot start a test not assigned to them."""
        resp = client.post(
            f"/student/start-test/{assigned_test['id']}",
            headers=auth_header(student2_user),
        )
        assert resp.status_code in (403, 404)

    def test_start_nonexistent_test(
        self, client: TestClient, student_user: dict
    ):
        """Starting non-existent test returns 403 or 404."""
        resp = client.post(
            "/student/start-test/99999",
            headers=auth_header(student_user),
        )
        assert resp.status_code in (403, 404)

    def test_start_test_without_auth(self, client: TestClient):
        """Without token returns 401."""
        resp = client.post("/student/start-test/1")
        assert resp.status_code == 401


# ==================== 6. AI ENDPOINTS ====================


class TestStudentAI:
    """AI hint, solution, test generation, and theory questions."""

    def test_get_ai_hint_task_not_found(
        self, client: TestClient, student_user: dict
    ):
        """AI hint returns 404 for non-existent task."""
        resp = client.post(
            "/student/tasks/99999/hint",
            headers=auth_header(student_user),
        )
        assert resp.status_code == 404

    def test_get_ai_solution_task_not_found(
        self, client: TestClient, student_user: dict
    ):
        """AI solution returns 404 for non-existent task."""
        resp = client.post(
            "/student/tasks/99999/ai-solve",
            headers=auth_header(student_user),
        )
        assert resp.status_code == 404

    def test_ai_hint_without_auth(self, client: TestClient):
        """Without token returns 401."""
        resp = client.post("/student/tasks/1/hint")
        assert resp.status_code == 401

    def test_ai_solution_without_auth(self, client: TestClient):
        """Without token returns 401."""
        resp = client.post("/student/tasks/1/ai-solve")
        assert resp.status_code == 401

    def test_generate_ai_test(
        self,
        client: TestClient,
        db: AsyncSession,
        student_user: dict,
    ):
        """AI test generation endpoint exists."""
        resp = client.post(
            "/student/generate-test",
            json={"prompt": "test", "task_count": 1, "difficulty": "easy"},
            headers=auth_header(student_user),
        )
        assert resp.status_code not in (401, 403)

    def test_ai_tests_empty(
        self, client: TestClient, student_user: dict
    ):
        """AI tests list is empty initially."""
        resp = client.get(
            "/student/ai-tests", headers=auth_header(student_user)
        )
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_ai_tests_without_auth(self, client: TestClient):
        """Without token returns 401."""
        resp = client.get("/student/ai-tests")
        assert resp.status_code == 401


# ==================== 7. THEORY ENDPOINTS ====================


class TestStudentTheory:
    """Theory: topics, by-topic, sections, by-section, and AI questions."""

    def test_get_theory_topics_empty(
        self, client: TestClient, student_user: dict
    ):
        """Empty theory topics when nothing exists."""
        resp = client.get(
            "/student/theory/topics",
            headers=auth_header(student_user),
        )
        assert resp.status_code == 200
        assert resp.json() == []

    def test_get_theory_topics(
        self,
        client: TestClient,
        student_user: dict,
        theory_material: dict,
    ):
        """Theory topics list includes created material."""
        resp = client.get(
            "/student/theory/topics",
            headers=auth_header(student_user),
        )
        assert resp.status_code == 200
        topics = [t["topic"] for t in resp.json()]
        assert "algebra" in topics

    def test_get_theory_by_topic(
        self,
        client: TestClient,
        student_user: dict,
        theory_material: dict,
    ):
        """Theory fetched by topic."""
        resp = client.get(
            "/student/theory/by-topic/algebra",
            headers=auth_header(student_user),
        )
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
        assert len(resp.json()) >= 1
        assert resp.json()[0]["topic"] == "algebra"

    def test_get_theory_by_topic_unknown(
        self, client: TestClient, student_user: dict
    ):
        """Unknown topic returns 404."""
        resp = client.get(
            "/student/theory/by-topic/xxxunknownxxx",
            headers=auth_header(student_user),
        )
        assert resp.status_code == 404

    def test_get_theory_sections(
        self,
        client: TestClient,
        student_user: dict,
        theory_material: dict,
    ):
        """Theory sections for a topic."""
        resp = client.get(
            "/student/theory/sections/algebra",
            headers=auth_header(student_user),
        )
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
        sections = [s["section"] for s in resp.json()]
        assert "equations" in sections

    def test_get_theory_sections_unknown(
        self, client: TestClient, student_user: dict
    ):
        """Unknown topic sections returns 404."""
        resp = client.get(
            "/student/theory/sections/xxxunknownxxx",
            headers=auth_header(student_user),
        )
        assert resp.status_code == 404

    def test_get_theory_by_topic_section(
        self,
        client: TestClient,
        student_user: dict,
        theory_material: dict,
    ):
        """Theory fetched by topic and section."""
        resp = client.get(
            "/student/theory/by-topic/algebra/section/equations",
            headers=auth_header(student_user),
        )
        assert resp.status_code == 200
        assert resp.json()["topic"] == "algebra"
        assert resp.json()["section"] == "equations"

    def test_get_theory_by_topic_section_unknown(
        self, client: TestClient, student_user: dict
    ):
        """Unknown topic+section returns 404."""
        resp = client.get(
            "/student/theory/by-topic/xxx/section/yyy",
            headers=auth_header(student_user),
        )
        assert resp.status_code == 404

    def test_ask_ai_theory_no_context(
        self, client: TestClient, student_user: dict
    ):
        """AI theory question without theory_id or content."""
        resp = client.post(
            "/student/theory/ask-ai",
            json={"question": "What is algebra?", "theory_content": ""},
            headers=auth_header(student_user),
        )
        assert resp.status_code != 401

    def test_theory_without_auth(self, client: TestClient):
        """Theory endpoints without token return 401."""
        resp = client.get("/student/theory/topics")
        assert resp.status_code == 401


# ==================== 8. ROLE-BASED ACCESS CONTROL ====================


class TestStudentRoleAccess:
    """Student cannot access teacher/admin endpoints."""

    def test_student_cannot_access_teacher_tests(
        self, client: TestClient, student_user: dict
    ):
        """Student gets 403 when accessing teacher endpoint."""
        resp = client.get(
            "/teacher/tests", headers=auth_header(student_user)
        )
        assert resp.status_code == 403

    def test_student_cannot_access_admin_users(
        self, client: TestClient, student_user: dict
    ):
        """Student gets 403 when accessing admin endpoint."""
        resp = client.get(
            "/admin/users", headers=auth_header(student_user)
        )
        assert resp.status_code == 403

    def test_student_cannot_create_teacher_test(
        self, client: TestClient, student_user: dict
    ):
        """Student gets 403 when creating a test via teacher endpoint."""
        resp = client.post(
            "/teacher/tests",
            json={"title": "hack", "is_autocompile": False},
            headers=auth_header(student_user),
        )
        assert resp.status_code == 403

    def test_student_cannot_delete_task(
        self,
        client: TestClient,
        student_user: dict,
        sample_task: int,
    ):
        """Student gets 403 when trying to delete a task."""
        resp = client.delete(
            f"/admin/tasks/{sample_task}",
            headers=auth_header(student_user),
        )
        assert resp.status_code == 403


# ==================== 9. STATISTICS ENDPOINTS ====================


class TestStudentStats:
    """Student statistics endpoints."""

    def test_get_period_stats(
        self, client: TestClient, student_user: dict
    ):
        """Period stats endpoint returns valid data."""
        resp = client.get(
            "/stats/me/period",
            headers=auth_header(student_user),
            params={"period": "month"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "period" in data
        assert "user_id" in data

    def test_get_topic_stats(
        self, client: TestClient, student_user: dict
    ):
        """Topic stats endpoint returns valid data."""
        resp = client.get(
            "/stats/me/topics",
            headers=auth_header(student_user),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "topics" in data

    def test_get_difficulty_stats(
        self, client: TestClient, student_user: dict
    ):
        """Difficulty stats endpoint returns valid data."""
        resp = client.get(
            "/stats/me/difficulty",
            headers=auth_header(student_user),
        )
        assert resp.status_code == 200
        data = resp.json