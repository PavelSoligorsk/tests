from pydantic import BaseModel, Field, model_validator
from typing import List, Optional
from datetime import datetime

class TaskBase(BaseModel):
    # Изменяем на str
    task_class: str 
    topic_number: str 
    content: str
    options: Optional[List[str]] = None
    answer: str
    hint: Optional[str] = None
    solution: Optional[str] = None
    is_open_answer: bool = True
    difficulty: Optional[int] = None

class TaskResponse(TaskBase):
    id: int
    class Config:
        from_attributes = True


class TaskCreate(TaskBase):
    """Схема для создания задания (то, что присылает админ)"""
    pass

class TaskCreateRequest(TaskBase):
    @model_validator(mode='after')
    def validate_options(self):
        if not self.is_open_answer and (not self.options or len(self.options) == 0):
            raise ValueError("Если задание с выбором ответа, поле options обязательно.")
        return self

class TaskUpdateRequest(BaseModel):
    task_class: Optional[int] = Field(None, ge=1, le=11)
    topic_number: Optional[int] = None
    content: Optional[str] = None
    options: Optional[List[str]] = None
    answer: Optional[str] = None
    hint: Optional[str] = None
    solution: Optional[str] = None
    is_open_answer: Optional[bool] = None


from pydantic import BaseModel
from typing import Optional

class AnswerSubmitRequest(BaseModel):
    task_id: int
    user_id: int
    test_id: int
    answer_text: str
    test_id: Optional[int] = None  # Теперь можно передать ID теста

class AnswerResponse(BaseModel):
    id: int
    task_id: int
    user_id: int
    test_id: Optional[int]
    points_earned: int
    is_correct: bool
    attempt_number: int

    class Config:
        from_attributes = True

class TestCreateRequest(BaseModel):
    user_id: int
    task_ids: List[int] # Список ID заданий, которые войдут в тест

class TestResponse(BaseModel):
    id: int
    title: Optional[str] = None
    target_class: Optional[str] = None # Изменено на str
    target_topic: Optional[str] = None # Изменено на str
    is_active: bool
    # Используем Optional, так как этих полей может не быть в объекте модели Test
    creator_id: Optional[int] = None 
    tasks: List[TaskResponse] = []
    hint: Optional[str] = None  # <--- Добавляем это поле
    
    # Эти поля вызывали ошибку, так как их нет в модели Test напрямую
    # Если они нужны для чего-то другого, оставляем их Optional
    total_score: Optional[int] = 0 
    answers: List[AnswerResponse] = [] 

    class Config:
        from_attributes = True

class TestResultResponse(BaseModel):
    id: int
    test_id: int
    total_points: int
    completed_at: datetime
    
    # Мы можем достать название через связь с моделью Test
    test_title: Optional[str] = None 

    class Config:
        from_attributes = True

    # Валидатор, чтобы вытащить title из связанной модели Test
    @model_validator(mode='before')
    @classmethod
    def get_test_title(cls, data):
        if hasattr(data, 'test') and data.test:
            data.test_title = data.test.title or f"Тест №{data.test.id}"
        return data

class UserRegister(BaseModel):
    username: str
    password: str
    first_name: str
    last_name: str
    phone: Optional[str] = None
    tg_username: Optional[str] = None

class UserResponse(BaseModel):
    id: int
    username: str
    role: str
    first_name: str
    last_name: Optional[str]
    phone: Optional[str]
    tg_username: Optional[str]

    class Config:
        from_attributes = True

# Схема для вложенной статистики
class UserStats(BaseModel):
    total_attempts: int
    avg_score: float
    # Можно добавить список последних активностей, если нужно
    # last_activity: List[dict] 

# Итоговая схема, которую требует эндпоинт
class UserResponseWithStats(BaseModel):
    user: UserResponse
    stats: UserStats

class TestCreateRequest(BaseModel):
    task_ids: list[int]

class UserUpdate(BaseModel):
    first_name: Optional[str]
    last_name: Optional[str]
    phone: Optional[str]
    tg_username: Optional[str]

from pydantic import EmailStr

from pydantic import BaseModel, EmailStr

class AllowedEmailBase(BaseModel):
    email: str

class AllowedEmailResponse(AllowedEmailBase):
    class Config:
        from_attributes = True

from pydantic import BaseModel
from typing import Optional

class ImageUploadResponse(BaseModel):
    url: str
    filename: Optional[str] = None
    size: Optional[int] = None