"""
📦 ОБЩИЙ КОНФИГ ТЕСТОВ
Все фикстуры, настройка БД, моки — здесь.
"""

import pytest
import os
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import sys

# Добавляем путь к проекту
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app
from core.database import Base, get_db
import core.models as models

# ==================== ТЕСТОВАЯ БД ====================

SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


# ==================== ФИКСТУРЫ ====================

@pytest.fixture(autouse=True)
def setup_database():
    """Создаёт таблицы перед тестом, удаляет после"""
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    """Тестовый клиент FastAPI"""
    return TestClient(app)


@pytest.fixture
def db():
    """Сессия БД для прямого доступа"""
    db_session = TestingSessionLocal()
    try:
        yield db_session
    finally:
        db_session.close()


def _register_user(client, db, email, password, first_name, last_name, role="student"):
    """Вспомогательная функция для создания пользователя + возврата токена"""
    allowed = models.AllowedEmail(email=email)
    db.add(allowed)
    db.commit()

    client.post("/register", json={
        "username": email,
        "password": password,
        "first_name": first_name,
        "last_name": last_name
    })

    user = db.query(models.User).filter(models.User.username == email).first()
    if role != "student":
        user.role = role
        db.commit()

    login = client.post("/login", data={"username": email, "password": password})
    token = login.json()["access_token"]

    return {
        "token": token,
        "id": user.id,
        "username": email,
        "first_name": first_name,
        "last_name": last_name
    }


@pytest.fixture
def admin_user(client, db):
    """Создаёт и возвращает админа"""
    return _register_user(client, db, "admin@test.com", "Admin123!", "Admin", "Test", role="admin")


@pytest.fixture
def teacher_user(client, db):
    """Создаёт и возвращает учителя"""
    return _register_user(client, db, "teacher@test.com", "Teacher123!", "Ivan", "Petrov", role="teacher")


@pytest.fixture
def student_user(client, db):
    """Создаёт и возвращает студента"""
    return _register_user(client, db, "student@test.com", "Student123!", "Anna", "Ivanova")


@pytest.fixture
def student2_user(client, db):
    """Создаёт и возвращает второго студента"""
    return _register_user(client, db, "student2@test.com", "Student123!", "Oleg", "Petrov")


# ==================== ФИКСТУРЫ ЗАДАНИЙ ====================

@pytest.fixture
def sample_task(client, admin_user):
    """Создаёт тестовое задание с закрытым ответом"""
    response = client.post(
        "/admin/tasks",
        json={
            "task_class": "10",
            "topic_number": "1",
            "topic": "algebra",
            "section": "equations",
            "content": "Решите уравнение $2x + 3 = 7$",
            "answer": "2",
            "hint": "Перенесите 3 в правую часть",
            "solution": "$$2x = 4$$\n$$x = 2$$",
            "is_open_answer": False,
            "options": ["1", "2", "3", "4"],
            "difficulty": 2
        },
        headers={"Authorization": f"Bearer {admin_user['token']}"}
    )
    return response.json()["id"]


@pytest.fixture
def sample_open_task(client, admin_user):
    """Создаёт тестовое задание с открытым ответом"""
    response = client.post(
        "/admin/tasks",
        json={
            "task_class": "10",
            "topic_number": "2",
            "topic": "algebra",
            "section": "expressions",
            "content": "Упростите выражение $a \\cdot a^2$",
            "answer": "a^3",
            "hint": "Вспомните правило умножения степеней",
            "solution": "$$a^1 \\cdot a^2 = a^{1+2} = a^3$$",
            "is_open_answer": True,
            "options": None,
            "difficulty": 1
        },
        headers={"Authorization": f"Bearer {admin_user['token']}"}
    )
    return response.json()["id"]


@pytest.fixture
def sample_task_payload():
    """Базовый payload для создания задания"""
    return {
        "task_class": "11",
        "topic_number": "3",
        "topic": "geometry",
        "section": "trigonometry",
        "content": "Найдите $\\sin 30^\\circ$",
        "answer": "0.5",
        "hint": "Вспомните таблицу значений",
        "solution": "$$\\sin 30^\\circ = 0.5$$",
        "is_open_answer": False,
        "options": ["0", "0.5", "1", "0.866"],
        "difficulty": 1
    }


@pytest.fixture
def sample_teacher_test(client, teacher_user, sample_task):
    """Создаёт тест учителя (для защиты)"""
    response = client.post(
        "/teacher/tests",
        json={
            "title": "Тест учителя",
            "target_class": "10",
            "target_topic": "1",
            "is_autocompile": False,
            "task_ids": [sample_task]
        },
        headers={"Authorization": f"Bearer {teacher_user['token']}"}
    )
    return response.json()


@pytest.fixture
def link_teacher_student(db, teacher_user, student_user):
    """Привязывает студента к учителю"""
    link = models.TeacherStudent(
        teacher_id=teacher_user["id"],
        student_id=student_user["id"]
    )
    db.add(link)
    db.commit()
    return link


@pytest.fixture
def assigned_test(client, db, teacher_user, student_user, link_teacher_student, sample_task):
    """Создаёт и назначает тест студенту"""
    test_response = client.post(
        "/teacher/tests",
        json={
            "title": "Назначенный тест",
            "target_class": "10",
            "target_topic": "1",
            "is_autocompile": False,
            "task_ids": [sample_task]
        },
        headers={"Authorization": f"Bearer {teacher_user['token']}"}
    )
    test = test_response.json()

    client.post(
        "/teacher/assign-test",
        json={
            "test_id": test["id"],
            "user_ids": [student_user["id"]]
        },
        headers={"Authorization": f"Bearer {teacher_user['token']}"}
    )

    return test


@pytest.fixture
def theory_material(client, admin_user):
    """Создаёт теоретический материал"""
    response = client.post(
        "/admin/theory",
        json={
            "topic": "algebra",
            "section": "equations",
            "content": "Уравнение — это математическое равенство с неизвестной."
        },
        headers={"Authorization": f"Bearer {admin_user['token']}"}
    )
    return response.json()
