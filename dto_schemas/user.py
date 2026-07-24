from pydantic import BaseModel, EmailStr, ConfigDict
from typing import Optional
import pydantic

# Определяем версию Pydantic
PYDANTIC_V2 = pydantic.__version__.startswith('2.')

# ============ БАЗОВЫЙ КЛАСС ДЛЯ ORM ============

if PYDANTIC_V2:
    class ORMBaseModel(BaseModel):
        """Базовый класс для Pydantic V2"""
        model_config = ConfigDict(from_attributes=True)
else:
    class ORMBaseModel(BaseModel):
        """Базовый класс для Pydantic V1"""
        class Config:
            orm_mode = True  # В V1 используется orm_mode


# ============ АУТЕНТИФИКАЦИЯ ============

class UserRegister(BaseModel):
    username: str
    password: str
    first_name: str
    last_name: str
    phone: Optional[str] = None
    tg_username: Optional[str] = None

    if PYDANTIC_V2:
        model_config = ConfigDict(from_attributes=True)
    else:
        class Config:
            from_attributes = True


class UserLogin(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ============ ПОЛЬЗОВАТЕЛИ ============

class TeacherInfo(ORMBaseModel):
    first_name: str
    last_name: str


class UserResponse(ORMBaseModel):
    id: int
    username: str
    role: str
    first_name: str
    last_name: Optional[str] = None
    phone: Optional[str] = None
    tg_username: Optional[str] = None
    teacher: Optional[TeacherInfo] = None


class UserUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    tg_username: Optional[str] = None

    if PYDANTIC_V2:
        model_config = ConfigDict(from_attributes=True)
    else:
        class Config:
            from_attributes = True


# ============ ВОССТАНОВЛЕНИЕ ПАРОЛЯ ============

class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str
    confirm_password: str


# ============ НАЗНАЧЕНИЯ ============

class AssignStudentRequest(BaseModel):
    teacher_id: int
    student_id: int


class StudentAssignmentResponse(ORMBaseModel):
    id: int
    student_id: int
    teacher_id: int
    assigned_at: Optional[str] = None
    student: Optional[UserResponse] = None
    teacher: Optional[UserResponse] = None


# ============ СТАТИСТИКА ============

class UserStats(BaseModel):
    total_tests: int = 0
    average_score: float = 0.0
    completed_tests: int = 0
    in_progress_tests: int = 0
    total_points: int = 0


class UserResponseWithStats(ORMBaseModel):
    user: UserResponse
    total_tests: int = 0
    average_score: float = 0.0
    completed_tests: int = 0
    in_progress_tests: int = 0
    total_points: int = 0


# ============ ТЕСТЫ ============

class TestResponse(ORMBaseModel):
    id: int
    title: str
    target_class: Optional[str] = None
    target_topic: Optional[str] = None
    is_autocompile: bool = False
    created_by: int
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class TestCreate(BaseModel):
    title: str
    target_class: Optional[str] = None
    target_topic: Optional[str] = None
    is_autocompile: bool = False
    task_ids: Optional[list[int]] = None


# ============ ЗАДАНИЯ ============

class TaskResponse(ORMBaseModel):
    id: int
    question: str
    answer: str
    task_class: str
    topic: str
    topic_number: str
    section: Optional[str] = None
    difficulty: int = 1
    points: int = 1
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


# ============ AI ============

class AITestRequest(BaseModel):
    prompt: str
    task_count: int = 5
    difficulty: int = 1


# ============ НАЗНАЧЕНИЯ ТЕСТОВ ============

class TestAssignmentCreate(BaseModel):
    test_id: int
    user_ids: list[int]
    due_date: Optional[str] = None


class TestGroupAssignment(BaseModel):
    group_id: int
    test_id: int
    due_date: Optional[str] = None


# ============ ГРУППЫ ============

class GroupResponse(ORMBaseModel):
    id: int
    name: str
    description: Optional[str] = None
    teacher_id: int
    created_at: Optional[str] = None
    student_count: int = 0


class GroupCreate(BaseModel):
    name: str
    description: Optional[str] = None


class GroupUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


# ============ УНИВЕРСАЛЬНЫЙ ОТВЕТ ============

class ApiResponse(BaseModel):
    success: bool
    message: Optional[str] = None
    data: Optional[dict] = None


# ============ ХЕЛПЕРЫ ДЛЯ РАБОТЫ ============

def to_orm(data, model_class):
    """
    Преобразует SQLAlchemy объект в Pydantic модель
    """
    if PYDANTIC_V2:
        return model_class.model_validate(data)
    else:
        return model_class.from_orm(data)


def to_dict(obj):
    """
    Преобразует SQLAlchemy объект в словарь
    """
    if hasattr(obj, '__table__'):
        from datetime import datetime, date
        from decimal import Decimal
        from uuid import UUID
        
        result = {}
        for column in obj.__table__.columns:
            value = getattr(obj, column.name)
            if isinstance(value, (datetime, date)):
                result[column.name] = value.isoformat()
            elif isinstance(value, Decimal):
                result[column.name] = float(value)
            elif isinstance(value, UUID):
                result[column.name] = str(value)
            else:
                result[column.name] = value
        return result
    return obj


def to_list_dict(objects):
    """Преобразует список SQLAlchemy объектов в список словарей"""
    return [to_dict(obj) for obj in objects]


# ============ ЕСЛИ У ТЕБЯ PYDANTIC V1 ============

# Раскомментируй это, если используешь Pydantic V1
# class Config:
#     orm_mode = True
#     from_attributes = True  # В V1 тоже работает, но orm_mode предпочтительнее