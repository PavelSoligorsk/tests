"""
Auth tests: registration, login, password reset, and security checks.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession

import core.models as models
from tests.conftest import auth_header


class TestRegistration:
    """Registration tests."""

    async def test_register_success(self, client: TestClient, db: AsyncSession):
        """Successful registration when email is in whitelist."""
        db.add(models.AllowedEmail(email="test@test.com"))
        await db.commit()

        resp = client.post("/register", json={
            "username": "test@test.com",
            "password": "Test123!",
            "first_name": "Test",
            "last_name": "User",
        })
        assert resp.status_code == 200

        result = await db.execute(
            sa_select(models.User).where(models.User.username == "test@test.com")
        )
        user = result.scalars().first()
        assert user is not None
        assert user.first_name == "Test"
        assert user.last_name == "User"

    def test_register_without_whitelist(self, client: TestClient):
        """Registration without email in whitelist is forbidden."""
        resp = client.post("/register", json={
            "username": "unknown@test.com",
            "password": "Test123!",
            "first_name": "Unknown",
            "last_name": "User",
        })
        assert resp.status_code == 403
        assert "запрещена" in resp.json()["detail"]

    async def test_register_duplicate_email(self, client: TestClient, db: AsyncSession):
        """Duplicate email registration fails."""
        db.add(models.AllowedEmail(email="dup@test.com"))
        await db.commit()

        client.post("/register", json={
            "username": "dup@test.com",
            "password": "Test123!",
            "first_name": "First",
            "last_name": "User",
        })

        resp = client.post("/register", json={
            "username": "dup@test.com",
            "password": "Test123!",
            "first_name": "Second",
            "last_name": "User",
        })
        assert resp.status_code == 400
        assert "уже существует" in resp.json()["detail"]

    async def test_register_missing_password(self, client: TestClient, db: AsyncSession):
        """Registration without password fails validation."""
        db.add(models.AllowedEmail(email="nopass@test.com"))
        await db.commit()

        resp = client.post("/register", json={
            "username": "nopass@test.com",
            "first_name": "No",
            "last_name": "Pass",
        })
        assert resp.status_code == 422

    def test_register_missing_username(self, client: TestClient):
        """Registration without username fails validation."""
        resp = client.post("/register", json={
            "password": "Test123!",
            "first_name": "No",
            "last_name": "User",
        })
        assert resp.status_code == 422

    async def test_register_admin_auto_role(self, client: TestClient, db: AsyncSession):
        """Gmail addresses automatically get admin role."""
        db.add(models.AllowedEmail(email="admin@gmail.com"))
        await db.commit()

        resp = client.post("/register", json={
            "username": "admin@gmail.com",
            "password": "Admin123!",
            "first_name": "Admin",
            "last_name": "Test",
        })
        assert resp.status_code == 200

        result = await db.execute(
            sa_select(models.User).where(models.User.username == "admin@gmail.com")
        )
        user = result.scalars().first()
        assert user.role == "admin"


class TestLogin:
    """Login tests."""

    @pytest.fixture(autouse=True)
    async def _registered_user(self, client: TestClient, db: AsyncSession):
        """Create a user for login tests."""
        db.add(models.AllowedEmail(email="login@test.com"))
        await db.commit()
        client.post("/register", json={
            "username": "login@test.com",
            "password": "Correct123!",
            "first_name": "Login",
            "last_name": "User",
        })

    def test_login_success(self, client: TestClient):
        """Successful login returns a token."""
        resp = client.post("/login", data={"username": "login@test.com", "password": "Correct123!"})
        assert resp.status_code == 200
        assert "access_token" in resp.json()
        assert resp.json()["token_type"] == "bearer"
        assert resp.json()["username"] == "login@test.com"

    def test_login_wrong_password(self, client: TestClient):
        """Wrong password returns 401."""
        resp = client.post("/login", data={"username": "login@test.com", "password": "Wrong123!"})
        assert resp.status_code == 401
        assert "Неверный логин или пароль" in resp.json()["detail"]

    def test_login_nonexistent_user(self, client: TestClient):
        """Login for non-existent user returns 401."""
        resp = client.post("/login", data={"username": "no@test.com", "password": "Test123!"})
        assert resp.status_code == 401
        assert "Неверный логин или пароль" in resp.json()["detail"]

    def test_login_missing_password(self, client: TestClient):
        """Login without password fails validation."""
        resp = client.post("/login", data={"username": "login@test.com"})
        assert resp.status_code == 422

    def test_login_missing_username(self, client: TestClient):
        """Login without username fails validation."""
        resp = client.post("/login", data={"password": "Test123!"})
        assert resp.status_code == 422


class TestPasswordReset:
    """Password reset tests."""

    @pytest.fixture(autouse=True)
    async def _registered_user(self, client: TestClient, db: AsyncSession):
        """Create a user for reset tests."""
        db.add(models.AllowedEmail(email="reset@test.com"))
        await db.commit()
        client.post("/register", json={
            "username": "reset@test.com",
            "password": "OldPass123!",
            "first_name": "Reset",
            "last_name": "User",
        })

    def test_forgot_password(self, client: TestClient):
        """Forgot password request succeeds."""
        resp = client.post("/forgot-password", json={"email": "reset@test.com"})
        assert resp.status_code == 200
        assert "инструкция отправлена" in resp.json()["message"]

    def test_forgot_password_nonexistent(self, client: TestClient):
        """Forgot password for unknown email returns 200 (no user enumeration)."""
        resp = client.post("/forgot-password", json={"email": "ghost@test.com"})
        assert resp.status_code == 200
        assert "инструкция отправлена" in resp.json()["message"]

    def test_forgot_password_missing_email(self, client: TestClient):
        """Forgot password without email fails validation."""
        resp = client.post("/forgot-password", json={})
        assert resp.status_code == 422


class TestSecurity:
    """Security: protected endpoints and role checks."""

    def test_protected_without_token(self, client: TestClient):
        """Protected endpoint without token returns 401."""
        resp = client.get("/teacher/tests")
        assert resp.status_code == 401

    def test_protected_invalid_token(self, client: TestClient):
        """Invalid token returns 401."""
        resp = client.get("/teacher/tests", headers={"Authorization": "Bearer invalid.token.here"})
        assert resp.status_code == 401

    async def test_student_cant_access_teacher(self, client: TestClient, db: AsyncSession):
        """Student cannot access teacher endpoints."""
        db.add(models.AllowedEmail(email="studsec@test.com"))
        await db.commit()

        client.post("/register", json={
            "username": "studsec@test.com",
            "password": "Student123!",
            "first_name": "Student",
            "last_name": "Security",
        })

        login = client.post("/login", data={"username": "studsec@test.com", "password": "Student123!"})
        token = login.json()["access_token"]

        resp = client.get("/teacher/tests", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 403
        assert "Требуется роль teacher" in resp.json()["detail"]

    async def test_student_cant_access_admin(self, client: TestClient, db: AsyncSession):
        """Student cannot access admin endpoints."""
        db.add(models.AllowedEmail(email="studadm@test.com"))
        await db.commit()

        client.post("/register", json={
            "username": "studadm@test.com",
            "password": "Student123!",
            "first_name": "Student",
            "last_name": "Admin",
        })

        login = client.post("/login", data={"username": "studadm@test.com", "password": "Student123!"})
        token = login.json()["access_token"]

        resp = client.get("/admin/users", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 403