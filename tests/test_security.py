"""
Security tests: SQL injection, XSS, mass requests, role-based access, data integrity.
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession

import core.models as models
from tests.conftest import auth_header


class TestSQLInjection:
    """SQL injection tests."""

    @pytest.mark.parametrize("injection", [
        "'; DROP TABLE users; --",
        "' OR '1'='1",
        "'; SELECT * FROM users; --",
        "admin'--",
        "1; DROP TABLE tasks; --",
    ])
    async def test_login_sql_injection(self, client: TestClient, db: AsyncSession, injection: str):
        """SQL injection in login field returns 401, not 500."""
        db.add(models.AllowedEmail(email="safe@test.com"))
        await db.commit()

        client.post("/register", json={
            "username": "safe@test.com",
            "password": "Safe123!",
            "first_name": "Safe",
            "last_name": "User",
        })

        resp = client.post("/login", data={"username": injection, "password": "test"})
        assert resp.status_code == 401

    @pytest.mark.parametrize("injection", [
        "'; DROP TABLE users; --",
        "' OR '1'='1",
        "1 OR 1=1",
        "999 UNION SELECT * FROM users",
    ])
    def test_task_id_sql_injection(self, client: TestClient, admin_user: dict, injection: str):
        """SQL injection in task ID returns 404 or 422, not 500."""
        resp = client.get(
            f"/admin/tasks/{injection}",
            headers=auth_header(admin_user),
        )
        assert resp.status_code in (404, 422)

    @pytest.mark.parametrize("injection", [
        "'; DROP TABLE users; --",
        "' OR '1'='1",
    ])
    def test_search_injection(self, client: TestClient, teacher_user: dict, injection: str):
        """SQL injection in search parameters."""
        resp = client.get(
            f"/teacher/tasks?topic={injection}",
            headers=auth_header(teacher_user),
        )
        assert resp.status_code in (200, 400)
        assert resp.status_code != 500


class TestXSSTasks:
    """XSS tests via task content."""

    @pytest.mark.parametrize("xss_payload", [
        "<script>alert('XSS')</script>",
        "<img src=x onerror=alert(1)>",
        "javascript:alert('XSS')",
        "{{7*7}}",
        "${7*7}",
    ])
    def test_xss_in_task_content(self, client: TestClient, admin_user: dict, xss_payload: str):
        """XSS in task content is stored as-is (protection is at output level)."""
        resp = client.post(
            "/admin/tasks",
            json={
                "task_class": "10",
                "topic_number": "1",
                "topic": xss_payload,
                "section": xss_payload,
                "content": xss_payload,
                "answer": "2",
                "hint": xss_payload,
                "solution": xss_payload,
                "is_open_answer": False,
                "options": ["1", "2", "3", "4"],
                "difficulty": 1,
            },
            headers=auth_header(admin_user),
        )
        assert resp.status_code == 200

        task_id = resp.json()["id"]
        get_resp = client.get(
            f"/admin/tasks/{task_id}",
            headers=auth_header(admin_user),
        )
        assert get_resp.status_code == 200
        assert xss_payload in str(get_resp.json().values())

    @pytest.mark.parametrize("xss_payload", [
        "<script>alert('XSS')</script>",
        "<img src=x onerror=alert(1)>",
    ])
    def test_xss_in_user_answer(
        self, client: TestClient, student_user: dict, assigned_test: dict, xss_payload: str
    ):
        """XSS in student answer is accepted but not executed."""
        task_id = assigned_test["tasks"][0]["id"]

        resp = client.post(
            f"/student/tests/{assigned_test['id']}/submit",
            json=[{"task_id": task_id, "user_answer": xss_payload}],
            headers=auth_header(student_user),
        )
        assert resp.status_code == 200


class TestMassRequests:
    """Load / mass request tests."""

    async def test_rapid_registrations(self, client: TestClient, db: AsyncSession):
        """Multiple rapid registrations succeed."""
        for i in range(5):
            email = f"mass{i}@test.com"
            db.add(models.AllowedEmail(email=email))
            await db.commit()

            resp = client.post("/register", json={
                "username": email,
                "password": f"Pass{i}123!",
                "first_name": f"Mass{i}",
                "last_name": "User",
            })
            assert resp.status_code == 200

    async def test_rapid_login(self, client: TestClient, db: AsyncSession):
        """Multiple rapid logins succeed."""
        db.add(models.AllowedEmail(email="rapid@test.com"))
        await db.commit()

        client.post("/register", json={
            "username": "rapid@test.com",
            "password": "Rapid123!",
            "first_name": "Rapid",
            "last_name": "User",
        })

        for _ in range(5):
            resp = client.post("/login", data={"username": "rapid@test.com", "password": "Rapid123!"})
            assert resp.status_code == 200
            assert "access_token" in resp.json()


class TestRoleBasedAccess:
    """Role-based access control tests."""

    def test_student_access_denied_to_teacher(self, client: TestClient, student_user: dict):
        """Student cannot access teacher endpoints."""
        teacher_endpoints = [
            ("GET", "/teacher/tests"),
            ("POST", "/teacher/tests"),
            ("GET", "/teacher/groups/"),
            ("POST", "/teacher/groups/"),
            ("GET", "/teacher/students"),
            ("POST", "/teacher/assign-test"),
        ]
        for method, url in teacher_endpoints:
            if method == "GET":
                resp = client.get(url, headers=auth_header(student_user))
            else:
                resp = client.post(url, json={}, headers=auth_header(student_user))
            assert resp.status_code == 403, f"{method} {url} should return 403"

    def test_teacher_cannot_access_admin(self, client: TestClient, teacher_user: dict):
        """Teacher cannot access admin endpoints."""
        admin_endpoints = [
            ("GET", "/admin/users"),
            ("POST", "/admin/tasks"),
            ("GET", "/admin/theory/getall"),
        ]
        for method, url in admin_endpoints:
            if method == "GET":
                resp = client.get(url, headers=auth_header(teacher_user))
            else:
                resp = client.post(url, json={}, headers=auth_header(teacher_user))
            assert resp.status_code == 403, f"{method} {url} should return 403"

    def test_teacher_can_access_student_assignments(
        self,
        client: TestClient,
        teacher_user: dict,
        student_user: dict,
        link_teacher_student: Any,
        assigned_test: dict,
    ):
        """Teacher can view own student's assignments."""
        resp = client.get(
            f"/teacher/student/{student_user['id']}/assignments",
            headers=auth_header(teacher_user),
        )
        assert resp.status_code == 200


class TestDataIntegrity:
    """Data integrity tests (cascading deletes)."""

    async def test_cascade_delete_teacher(
        self,
        client: TestClient,
        db: AsyncSession,
        admin_user: dict,
        teacher_user: dict,
        student_user: dict,
        link_teacher_student: Any,
        sample_task: int,
    ):
        """Deleting a teacher cascades to groups and tests."""
        g = client.post(
            "/teacher/groups/",
            json={"name": "My Group"},
            headers=auth_header(teacher_user),
        ).json()

        t = client.post(
            "/teacher/tests",
            json={
                "title": "My Test",
                "target_class": "10",
                "target_topic": "1",
                "is_autocompile": False,
                "task_ids": [sample_task],
            },
            headers=auth_header(teacher_user),
        ).json()

        group_id = g["id"]
        test_id = t["id"]

        client.delete(
            f"/admin/users/{teacher_user['id']}",
            headers=auth_header(admin_user),
        )

        group_result = await db.execute(sa_select(models.Group).where(models.Group.id == group_id))
        assert group_result.scalars().first() is None

        test_result = await db.execute(sa_select(models.Test).where(models.Test.id == test_id))
        assert test_result.scalars().first() is None

    async def test_cascade_delete_student(
        self,
        client: TestClient,
        db: AsyncSession,
        admin_user: dict,
        teacher_user: dict,
        student_user: dict,
        link_teacher_student: Any,
        assigned_test: dict,
    ):
        """Deleting a student cascades to results and assignments."""
        student_id = student_user["id"]

        client.delete(
            f"/admin/users/{student_id}",
            headers=auth_header(admin_user),
        )

        results = await db.execute(
            sa_select(models.TestResult).where(models.TestResult.user_id == student_id)
        )
        assert len(results.scalars().all()) == 0

        assignments = await db.execute(
            sa_select(models.TestAssignment).where(models.TestAssignment.user_id == student_id)
        )
        assert len(assignments.scalars().all()) == 0