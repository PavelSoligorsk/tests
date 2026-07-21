"""
🔐 ТЕСТЫ АВТОРИЗАЦИИ
Проверяют регистрацию, логин, защиту от дублей и невалидных данных.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import sys
import os

# Добавляем путь к проекту
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app
from core.database import Base, get_db
import core.models as models


# ==================== НАСТРОЙКА ТЕСТОВОЙ БД ====================

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
def db_session():
    """Сессия БД для прямого доступа"""
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


# ==================== ТЕСТЫ РЕГИСТРАЦИИ ====================

class TestRegistration:
    """Тесты регистрации"""

    def test_register_success(self, client, db_session):
        """✅ Успешная регистрация"""
        # Добавляем email в белый список
        allowed = models.AllowedEmail(email="test@test.com")
        db_session.add(allowed)
        db_session.commit()

        response = client.post("/register", json={
            "username": "test@test.com",
            "password": "Test123!",
            "first_name": "Test",
            "last_name": "User"
        })

        assert response.status_code == 200
        assert "успешно" in response.json()["message"]

        # Проверяем, что пользователь создался в БД
        user = db_session.query(models.User).filter(
            models.User.username == "test@test.com"
        ).first()
        assert user is not None
        assert user.first_name == "Test"
        assert user.last_name == "User"

    def test_register_without_whitelist(self, client):
        """❌ Регистрация без белого списка — запрещена"""
        response = client.post("/register", json={
            "username": "unknown@test.com",
            "password": "Test123!",
            "first_name": "Unknown",
            "last_name": "User"
        })

        assert response.status_code == 403
        assert "запрещена" in response.json()["detail"]

    def test_register_duplicate_email(self, client, db_session):
        """❌ Регистрация с уже существующим email"""
        # Добавляем в белый список
        allowed = models.AllowedEmail(email="duplicate@test.com")
        db_session.add(allowed)
        db_session.commit()

        # Первая регистрация
        client.post("/register", json={
            "username": "duplicate@test.com",
            "password": "Test123!",
            "first_name": "Duplicate",
            "last_name": "User"
        })

        # Вторая регистрация (дубликат)
        response = client.post("/register", json={
            "username": "duplicate@test.com",
            "password": "Test123!",
            "first_name": "Duplicate",
            "last_name": "User"
        })

        assert response.status_code == 400
        assert "уже существует" in response.json()["detail"]

    def test_register_missing_fields(self, client, db_session):
        """❌ Регистрация без обязательных полей"""
        allowed = models.AllowedEmail(email="missing@test.com")
        db_session.add(allowed)
        db_session.commit()

        # Без пароля
        response = client.post("/register", json={
            "username": "missing@test.com",
            "first_name": "Missing",
            "last_name": "User"
        })
        assert response.status_code == 422  # Validation error

        # Без username
        response = client.post("/register", json={
            "password": "Test123!",
            "first_name": "Missing",
            "last_name": "User"
        })
        assert response.status_code == 422

    def test_register_admin_auto_role(self, client, db_session):
        """✅ Админ автоматически получает роль admin"""
        allowed = models.AllowedEmail(email="admin@gmail.com")
        db_session.add(allowed)
        db_session.commit()

        response = client.post("/register", json={
            "username": "admin@gmail.com",
            "password": "Admin123!",
            "first_name": "Admin",
            "last_name": "Test"
        })

        assert response.status_code == 200

        user = db_session.query(models.User).filter(
            models.User.username == "admin@gmail.com"
        ).first()
        assert user.role == "admin"


# ==================== ТЕСТЫ ЛОГИНА ====================

class TestLogin:
    """Тесты логина"""

    @pytest.fixture
    def registered_user(self, client, db_session):
        """Создаёт пользователя для тестов логина"""
        allowed = models.AllowedEmail(email="login@test.com")
        db_session.add(allowed)
        db_session.commit()

        client.post("/register", json={
            "username": "login@test.com",
            "password": "Correct123!",
            "first_name": "Login",
            "last_name": "User"
        })

    def test_login_success(self, client, registered_user):
        """✅ Успешный логин"""
        response = client.post(
            "/login",
            data={"username": "login@test.com", "password": "Correct123!"}
        )

        assert response.status_code == 200
        assert "access_token" in response.json()
        assert response.json()["token_type"] == "bearer"
        assert "username" in response.json()
        assert response.json()["username"] == "login@test.com"

    def test_login_wrong_password(self, client, registered_user):
        """❌ Логин с неверным паролем"""
        response = client.post(
            "/login",
            data={"username": "login@test.com", "password": "Wrong123!"}
        )

        assert response.status_code == 401
        assert "Неверный логин или пароль" in response.json()["detail"]

    def test_login_nonexistent_user(self, client):
        """❌ Логин несуществующего пользователя"""
        response = client.post(
            "/login",
            data={"username": "nonexistent@test.com", "password": "Test123!"}
        )

        assert response.status_code == 401
        assert "Неверный логин или пароль" in response.json()["detail"]

    def test_login_missing_username(self, client):
        """❌ Логин без username"""
        response = client.post(
            "/login",
            data={"password": "Test123!"}
        )
        assert response.status_code == 422  # Validation error

    def test_login_missing_password(self, client, registered_user):
        """❌ Логин без пароля"""
        response = client.post(
            "/login",
            data={"username": "login@test.com"}
        )
        assert response.status_code == 422


# ==================== ТЕСТЫ СБРОСА ПАРОЛЯ ====================

class TestPasswordReset:
    """Тесты сброса пароля"""

    @pytest.fixture
    def registered_user(self, client, db_session):
        allowed = models.AllowedEmail(email="reset@test.com")
        db_session.add(allowed)
        db_session.commit()

        client.post("/register", json={
            "username": "reset@test.com",
            "password": "OldPass123!",
            "first_name": "Reset",
            "last_name": "User"
        })

    def test_forgot_password(self, client, registered_user):
        """✅ Запрос на сброс пароля"""
        response = client.post("/forgot-password", json={
            "email": "reset@test.com"
        })

        assert response.status_code == 200
        assert "инструкция отправлена" in response.json()["message"]

    def test_forgot_password_nonexistent_email(self, client):
        """❌ Сброс для несуществующего email"""
        response = client.post("/forgot-password", json={
            "email": "nonexistent@test.com"
        })

        assert response.status_code == 200  # Всегда 200, чтобы не палить email
        assert "инструкция отправлена" in response.json()["message"]

    def test_forgot_password_missing_email(self, client):
        """❌ Запрос без email"""
        response = client.post("/forgot-password", json={})
        assert response.status_code == 422


# ==================== ТЕСТЫ ЗАЩИТЫ ====================

class TestSecurity:
    """Тесты безопасности"""

    def test_protected_endpoint_without_token(self, client):
        """❌ Доступ к защищённому эндпоинту без токена"""
        response = client.get("/teacher/tests")
        assert response.status_code == 401

    def test_protected_endpoint_with_invalid_token(self, client):
        """❌ Доступ с невалидным токеном"""
        response = client.get(
            "/teacher/tests",
            headers={"Authorization": "Bearer invalid_token"}
        )
        assert response.status_code == 401

    def test_student_cant_access_teacher(self, client, db_session):
        """❌ Студент не может зайти в учительский эндпоинт"""
        # Создаём студента
        allowed = models.AllowedEmail(email="student_security@test.com")
        db_session.add(allowed)
        db_session.commit()

        client.post("/register", json={
            "username": "student_security@test.com",
            "password": "Student123!",
            "first_name": "Student",
            "last_name": "Security"
        })

        # Логинимся
        login = client.post(
            "/login",
            data={"username": "student_security@test.com", "password": "Student123!"}
        )
        token = login.json()["access_token"]

        # Пытаемся зайти в учительский эндпоинт
        response = client.get(
            "/teacher/tests",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 403
        assert "Требуется роль teacher" in response.json()["detail"]

    def test_student_cant_access_admin(self, client, db_session):
        """❌ Студент не может зайти в админский эндпоинт"""
        allowed = models.AllowedEmail(email="student_admin@test.com")
        db_session.add(allowed)
        db_session.commit()

        client.post("/register", json={
            "username": "student_admin@test.com",
            "password": "Student123!",
            "first_name": "Student",
            "last_name": "Admin"
        })

        login = client.post(
            "/login",
            data={"username": "student_admin@test.com", "password": "Student123!"}
        )
        token = login.json()["access_token"]

        response = client.get(
            "/admin/users",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 403