"""
Common test configuration.

All fixtures, DB setup, and mocks live here.

Supports both:
- Sync TestClient (existing fastapi.testclient)
- Async httpx.AsyncClient with ASGITransport (for async tests)
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Any, AsyncGenerator

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app
from core.database import Base, get_db
import core.models as models
import core.cache

# ==================== DISABLE REDIS ====================

core.cache.REDIS_AVAILABLE = False
core.cache.redis_client = None
core.cache.get_redis = lambda: None

# ==================== IN-MEMORY SQLITE DB ====================

ASYNC_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

async_engine = create_async_engine(
    ASYNC_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

TestingAsyncSessionLocal = async_sessionmaker(
    async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def override_get_db() -> Any:
    async with TestingAsyncSessionLocal() as db:
        try:
            yield db
        finally:
            await db.close()


app.dependency_overrides[get_db] = override_get_db


# ==================== HELPERS ====================


def auth_header(user: dict) -> dict:
    """Return Authorization header with Bearer token."""
    return {"Authorization": f"Bearer {user['token']}"}


async def register_user(
    client: TestClient,
    db: AsyncSession,
    email: str,
    password: str,
    first_name: str,
    last_name: str,
    role: str = "student",
) -> dict[str, Any]:
    """Register a user, log them in, return {token, id, username, ...}."""
    # Add to allowed emails
    db.add(models.AllowedEmail(email=email))
    await db.commit()

    # Register
    client.post("/register", json={
        "username": email,
        "password": password,
        "first_name": first_name,
        "last_name": last_name,
    })

    # Get user from DB
    result = await db.execute(select(models.User).where(models.User.username == email))
    user = result.scalars().first()

    # Set role if not student
    if role != "student" and user.role != role:
        user.role = role
        await db.commit()
        await db.refresh(user)

    # Login to get token
    login_resp = client.post("/login", data={"username": email, "password": password})
    assert login_resp.status_code == 200, f"Login failed for {email}: {login_resp.text}"
    token = login_resp.json()["access_token"]

    return {
        "token": token,
        "id": user.id,
        "username": email,
        "first_name": first_name,
        "last_name": last_name,
        "role": user.role,
    }


def _create_task(client: TestClient, admin_user: dict, task_data: dict) -> int:
    """Helper to create a task and return its ID."""
    resp = client.post(
        "/admin/tasks",
        json=task_data,
        headers=auth_header(admin_user),
    )
    assert resp.status_code == 200, f"Failed to create task: {resp.text}"
    return resp.json()["id"]


# ==================== DB LIFE-CYCLE ====================


@pytest.fixture(autouse=True)
def setup_database() -> None:
    """Create tables before each test, drop after."""

    async def _init() -> None:
        async with async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def _drop() -> None:
        async with async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)

    asyncio.run(_init())
    yield
    asyncio.run(_drop())


@pytest.fixture
def client() -> TestClient:
    """FastAPI test client."""
    return TestClient(app)


@pytest_asyncio.fixture
async def db() -> AsyncSession:
    """Async DB session for direct access."""
    async with TestingAsyncSessionLocal() as db_session:
        yield db_session


# ==================== USER FIXTURES ====================


@pytest_asyncio.fixture
async def admin_user(client: TestClient, db: AsyncSession) -> dict[str, Any]:
    return await register_user(
        client, db, "admin@test.com", "Admin123!", "Admin", "Test", role="admin"
    )


@pytest_asyncio.fixture
async def teacher_user(client: TestClient, db: AsyncSession) -> dict[str, Any]:
    return await register_user(
        client, db, "teacher@test.com", "Teacher123!", "Ivan", "Petrov", role="teacher"
    )


@pytest_asyncio.fixture
async def student_user(client: TestClient, db: AsyncSession) -> dict[str, Any]:
    return await register_user(
        client, db, "student@test.com", "Student123!", "Anna", "Ivanova"
    )


@pytest_asyncio.fixture
async def student2_user(client: TestClient, db: AsyncSession) -> dict[str, Any]:
    return await register_user(
        client, db, "student2@test.com", "Student123!", "Oleg", "Petrov"
    )


# ==================== TASK FIXTURES ====================


@pytest.fixture
def sample_task(client: TestClient, admin_user: dict) -> int:
    """Create a closed-answer task, return its ID."""
    return _create_task(client, admin_user, {
        "task_class": "10",
        "topic_number": "1",
        "topic": "algebra",
        "section": "equations",
        "content": r"Solve: $2x + 3 = 7$",
        "answer": "2",
        "hint": "Move 3 to the right side",
        "solution": r"$$2x = 4$$\n$$x = 2$$",
        "is_open_answer": False,
        "options": ["1", "2", "3", "4"],
        "difficulty": 2,
    })


@pytest.fixture
def sample_task_id(client: TestClient, admin_user: dict) -> int:
    """Create a sample task and return its ID (same as sample_task but with explicit name)."""
    return _create_task(client, admin_user, {
        "task_class": "10",
        "topic_number": "1",
        "topic": "algebra",
        "section": "equations",
        "content": "2 + 2 = ?",
        "options": ["3", "4", "5", "6"],
        "answer": "4",
        "is_open_answer": False,
        "difficulty": 1,
        "hint": "Think simple",
        "solution": "2 + 2 = 4",
    })


@pytest.fixture
def sample_open_task(client: TestClient, admin_user: dict) -> int:
    """Create an open-answer task, return its ID."""
    return _create_task(client, admin_user, {
        "task_class": "10",
        "topic_number": "2",
        "topic": "algebra",
        "section": "expressions",
        "content": r"Simplify: $a \cdot a^2$",
        "answer": "a^3",
        "hint": "Remember the rule for multiplying powers",
        "solution": r"$$a^1 \cdot a^2 = a^{1+2} = a^3$$",
        "is_open_answer": True,
        "options": None,
        "difficulty": 1,
    })


@pytest.fixture
def sample_task_payload() -> dict[str, Any]:
    """Base payload for task creation."""
    return {
        "task_class": "11",
        "topic_number": "3",
        "topic": "geometry",
        "section": "trigonometry",
        "content": r"Find $\sin 30^\circ$",
        "answer": "0.5",
        "hint": "Recall the values table",
        "solution": r"$$\sin 30^\circ = 0.5$$",
        "is_open_answer": False,
        "options": ["0", "0.5", "1", "0.866"],
        "difficulty": 1,
    }


@pytest.fixture
def sample_teacher_test(
    client: TestClient, teacher_user: dict, sample_task: int
) -> dict[str, Any]:
    """Create a teacher's test (not assigned to anyone)."""
    resp = client.post(
        "/teacher/tests",
        json={
            "title": "Teacher Test",
            "target_class": "10",
            "target_topic": "1",
            "is_autocompile": False,
            "task_ids": [sample_task],
        },
        headers=auth_header(teacher_user),
    )
    assert resp.status_code == 200, f"Failed to create teacher test: {resp.text}"
    return resp.json()


@pytest.fixture
def theory_material(client: TestClient, admin_user: dict) -> dict[str, Any]:
    """Create theory material."""
    resp = client.post(
        "/admin/theory",
        json={
            "topic": "algebra",
            "section": "equations",
            "content": "An equation is a mathematical equality with an unknown.",
        },
        headers=auth_header(admin_user),
    )
    assert resp.status_code == 200, f"Failed to create theory: {resp.text}"
    return resp.json()


# ==================== RELATIONS & ASSIGNMENTS ====================


@pytest_asyncio.fixture
async def link_teacher_student(
    db: AsyncSession, teacher_user: dict, student_user: dict
) -> models.TeacherStudent:
    """Link student to teacher."""
    link = models.TeacherStudent(
        teacher_id=teacher_user["id"], student_id=student_user["id"]
    )
    db.add(link)
    await db.commit()
    return link


@pytest.fixture
def assigned_test(
    client: TestClient,
    teacher_user: dict,
    student_user: dict,
    sample_task: int,
) -> dict[str, Any]:
    """Create and assign a test to the student."""
    # Create test
    test_resp = client.post(
        "/teacher/tests",
        json={
            "title": "Assigned Test",
            "target_class": "10",
            "target_topic": "1",
            "is_autocompile": False,
            "task_ids": [sample_task],
        },
        headers=auth_header(teacher_user),
    )
    assert test_resp.status_code == 200, f"Failed to create test: {test_resp.text}"
    test = test_resp.json()

    # Assign to student
    assign_resp = client.post(
        "/teacher/assign-test",
        json={"test_id": test["id"], "user_ids": [student_user["id"]]},
        headers=auth_header(teacher_user),
    )
    assert assign_resp.status_code == 200, f"Failed to assign test: {assign_resp.text}"

    return test


# ═══════════════════════════════════════════════════════════════
# Async HTTPX Client (for async def tests)
# ═══════════════════════════════════════════════════════════════


@pytest_asyncio.fixture
async def async_client() -> AsyncGenerator[AsyncClient, None]:
    """Async httpx client with ASGITransport — no real HTTP server needed."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _bearer(token: str) -> dict[str, str]:
    """Helper: Bearer auth header dict."""
    return {"Authorization": f"Bearer {token}"}


# ═══════════════════════════════════════════════════════════════
# Pre-registered user tokens (for async tests)
# ═══════════════════════════════════════════════════════════════


@pytest_asyncio.fixture
async def admin_token(
    async_client: AsyncClient, db: AsyncSession
) -> str:
    """Register admin and return token."""
    info = await register_user(
        TestClient(app), db,
        "admin_async@test.com", "Admin123!", "Admin", "Async",
        role="admin",
    )
    return info["token"]


@pytest_asyncio.fixture
async def teacher_token(
    async_client: AsyncClient, db: AsyncSession
) -> str:
    """Register teacher and return token."""
    info = await register_user(
        TestClient(app), db,
        "teacher_async@test.com", "Teacher123!", "Teacher", "Async",
        role="teacher",
    )
    return info["token"]


@pytest_asyncio.fixture
async def student_token(
    async_client: AsyncClient, db: AsyncSession
) -> str:
    """Register student and return token."""
    info = await register_user(
        TestClient(app), db,
        "student_async@test.com", "Student123!", "Student", "Async",
    )
    return info["token"]


@pytest_asyncio.fixture
async def student2_token(
    async_client: AsyncClient, db: AsyncSession
) -> str:
    """Register second student and return token."""
    info = await register_user(
        TestClient(app), db,
        "student2_async@test.com", "Student123!", "Student2", "Async",
    )
    return info["token"]


# ═══════════════════════════════════════════════════════════════
# Async task & theory helpers
# ═══════════════════════════════════════════════════════════════


async def _async_create_task(
    ac: AsyncClient, token: str, task_data: dict
) -> dict[str, Any]:
    """Helper: create a task via async client, return response JSON."""
    resp = await ac.post("/admin/tasks", json=task_data, headers=_bearer(token))
    assert resp.status_code == 200, f"Failed to create task: {resp.text}"
    return resp.json()


async def _async_create_theory(
    ac: AsyncClient, token: str, theory_data: dict
) -> dict[str, Any]:
    """Helper: create theory via async client, return response JSON."""
    resp = await ac.post("/admin/theory", json=theory_data, headers=_bearer(token))
    assert resp.status_code == 200, f"Failed to create theory: {resp.text}"
    return resp.json()