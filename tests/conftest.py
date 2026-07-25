"""
Common test configuration.
All fixtures, DB setup, and mocks live here.
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Any

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
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
    db.add(models.AllowedEmail(email=email))
    await db.commit()

    client.post("/register", json={
        "username": email,
        "password": password,
        "first_name": first_name,
        "last_name": last_name,
    })

    result = await db.execute(select(models.User).where(models.User.username == email))
    user = result.scalars().first()

    if role != "student":
        user.role = role
        await db.commit()

    login_resp = client.post("/login", data={"username": email, "password": password})
    token = login_resp.json()["access_token"]

    return {
        "token": token,
        "id": user.id,
        "username": email,
        "first_name": first_name,
        "last_name": last_name,
    }


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
    return await register_user(client, db, "admin@test.com", "Admin123!", "Admin", "Test", role="admin")


@pytest_asyncio.fixture
async def teacher_user(client: TestClient, db: AsyncSession) -> dict[str, Any]:
    return await register_user(client, db, "teacher@test.com", "Teacher123!", "Ivan", "Petrov", role="teacher")


@pytest_asyncio.fixture
async def student_user(client: TestClient, db: AsyncSession) -> dict[str, Any]:
    return await register_user(client, db, "student@test.com", "Student123!", "Anna", "Ivanova")


@pytest_asyncio.fixture
async def student2_user(client: TestClient, db: AsyncSession) -> dict[str, Any]:
    return await register_user(client, db, "student2@test.com", "Student123!", "Oleg", "Petrov")


# ==================== TASK FIXTURES ====================


@pytest.fixture
def sample_task(client: TestClient, admin_user: dict) -> int:
    """Create a closed-answer task, return its ID."""
    resp = client.post(
        "/admin/tasks",
        json={
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
        },
        headers=auth_header(admin_user),
    )
    return resp.json()["id"]


@pytest.fixture
def sample_open_task(client: TestClient, admin_user: dict) -> int:
    """Create an open-answer task, return its ID."""
    resp = client.post(
        "/admin/tasks",
        json={
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
        },
        headers=auth_header(admin_user),
    )
    return resp.json()["id"]


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
def sample_teacher_test(client: TestClient, teacher_user: dict, sample_task: int) -> dict[str, Any]:
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
    return resp.json()


# ==================== RELATIONS & ASSIGNMENTS ====================


@pytest_asyncio.fixture
async def link_teacher_student(
    db: AsyncSession, teacher_user: dict, student_user: dict
) -> models.TeacherStudent:
    """Link student to teacher."""
    link = models.TeacherStudent(teacher_id=teacher_user["id"], student_id=student_user["id"])
    db.add(link)
    await db.commit()
    return link


@pytest_asyncio.fixture
async def assigned_test(
    client: TestClient,
    db: AsyncSession,
    teacher_user: dict,
    student_user: dict,
    link_teacher_student: models.TeacherStudent,
    sample_task: int,
) -> dict[str, Any]:
    """Create and assign a test to the student."""
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
    test = test_resp.json()

    client.post(
        "/teacher/assign-test",
        json={"test_id": test["id"], "user_ids": [student_user["id"]]},
        headers=auth_header(teacher_user),
    )

    return test