from pydantic import BaseModel, Field, model_validator
from typing import List, Optional
from datetime import datetime

class TaskBase(BaseModel):
    task_class: str 
    topic_number: str 
    topic: Optional[str] = None      # НОВОЕ
    section: Optional[str] = None    # НОВОЕ
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
    task_class: Optional[str] = None  # Было int, исправил на str
    topic_number: Optional[str] = None  # Было int, исправил на str
    topic: Optional[str] = None       # НОВОЕ
    section: Optional[str] = None     # НОВОЕ
    content: Optional[str] = None
    options: Optional[List[str]] = None
    answer: Optional[str] = None
    hint: Optional[str] = None
    solution: Optional[str] = None
    is_open_answer: Optional[bool] = None
    difficulty: Optional[int] = None  # Добавил, чтобы можно было обновлять сложность


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
    target_class: Optional[str] = None
    target_topic: Optional[str] = None
    is_active: bool
    is_autocompile: Optional[bool] = True  # <--- ДОБАВИТЬ
    creator_id: Optional[int] = None 
    tasks: List[TaskResponse] = []
    hint: Optional[str] = None
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

class TestCreate(BaseModel):
    title: str
    target_class: Optional[str] = None
    target_topic: Optional[str] = None
    is_autocompile: bool = False
    task_ids: Optional[List[int]] = None
    is_active: bool = True

class UserRegister(BaseModel):
    username: str
    password: str
    first_name: str
    last_name: str
    phone: Optional[str] = None
    tg_username: Optional[str] = None

class TeacherInfo(BaseModel):
    first_name: str
    last_name: str

class UserResponse(BaseModel):
    id: int
    username: str
    role: str
    first_name: str
    last_name: Optional[str]
    phone: Optional[str]
    tg_username: Optional[str]
    teacher: Optional[TeacherInfo] = None  # ← Только имя и фамилия

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
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    tg_username: Optional[str] = None
    
    class Config:
        from_attributes = True

from pydantic import BaseModel
from typing import Optional

class ImageUploadResponse(BaseModel):
    url: str
    filename: Optional[str] = None
    size: Optional[int] = None

# В dto.py добавьте:

class TestAssignmentCreate(BaseModel):
    test_id: int
    user_ids: List[int]  # Список ID студентов
    due_date: Optional[datetime] = None

class TestAssignmentResponse(BaseModel):
    id: int
    test_id: int
    test_title: str
    user_id: int
    student_name: str
    assigned_at: datetime
    due_date: Optional[datetime] = None
    is_completed: bool = False
    completed_at: Optional[datetime] = None
    total_tasks: int = 0
    total_points: Optional[int] = None      # <-- новое
    result_id: Optional[int] = None         # <-- новое

class StudentAssignmentResponse(BaseModel):
    """Для студента - список назначенных тестов"""
    assignment_id: int
    test_id: int
    test_title: Optional[str] = None
    assigned_at: datetime
    due_date: Optional[datetime] = None
    is_completed: bool
    total_tasks: int = 0

# --- THEORY DTO ---
class TheoryBase(BaseModel):
    topic: str
    section: str
    content: str

class TheoryCreate(TheoryBase):
    pass

class TheoryUpdate(BaseModel):
    topic: Optional[str] = None
    section: Optional[str] = None
    content: Optional[str] = None

class TheoryResponse(TheoryBase):
    id: int
    
    class Config:
        from_attributes = True

class AITestRequest(BaseModel):
    prompt: str
    task_count: int = 10
    difficulty: Optional[str] = None  # ← теперь может быть None

class TestGroupAssignment(BaseModel):
    test_id: int
    group_id: int
    due_date: Optional[datetime] = None