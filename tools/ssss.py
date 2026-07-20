
# Создаём все файлы schemas/ автоматически
import os

output_dir = "/schemas"
os.makedirs(output_dir, exist_ok=True)

# === schemas/task.py ===
task_py = '''from pydantic import BaseModel, model_validator
from typing import List, Optional

class TaskBase(BaseModel):
    task_class: str 
    topic_number: str 
    topic: Optional[str] = None
    section: Optional[str] = None
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
    task_class: Optional[str] = None
    topic_number: Optional[str] = None
    topic: Optional[str] = None
    section: Optional[str] = None
    content: Optional[str] = None
    options: Optional[List[str]] = None
    answer: Optional[str] = None
    hint: Optional[str] = None
    solution: Optional[str] = None
    is_open_answer: Optional[bool] = None
    difficulty: Optional[int] = None
'''

# === schemas/answer.py ===
answer_py = '''from pydantic import BaseModel
from typing import Optional

class AnswerSubmitRequest(BaseModel):
    task_id: int
    user_id: int
    answer_text: str
    test_id: Optional[int] = None

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
'''

# === schemas/test.py ===
test_py = '''from pydantic import BaseModel, model_validator
from typing import List, Optional
from datetime import datetime
from schemas.task import TaskResponse
from schemas.answer import AnswerResponse

class TestCreate(BaseModel):
    title: str
    target_class: Optional[str] = None
    target_topic: Optional[str] = None
    is_autocompile: bool = False
    task_ids: Optional[List[int]] = None
    is_active: bool = True

class TestCreateRequest(BaseModel):
    user_id: int
    task_ids: List[int]

class TestResponse(BaseModel):
    id: int
    title: Optional[str] = None
    target_class: Optional[str] = None
    target_topic: Optional[str] = None
    is_active: bool
    is_autocompile: Optional[bool] = True
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
    test_title: Optional[str] = None 

    class Config:
        from_attributes = True

    @model_validator(mode='before')
    @classmethod
    def get_test_title(cls, data):
        if hasattr(data, 'test') and data.test:
            data.test_title = data.test.title or f"Тест №{data.test.id}"
        return data
'''

# === schemas/user.py ===
user_py = '''from pydantic import BaseModel, EmailStr
from typing import Optional

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
    teacher: Optional[TeacherInfo] = None

    class Config:
        from_attributes = True

class UserUpdate(BaseModel):
    first_name: Optional[str]
    last_name: Optional[str]
    phone: Optional[str]
    tg_username: Optional[str]

class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str
    confirm_password: str

class AssignStudentRequest(BaseModel):
    teacher_id: int
    student_id: int
'''

# === schemas/stats.py ===
stats_py = '''from pydantic import BaseModel
from schemas.user import UserResponse

class UserStats(BaseModel):
    total_attempts: int
    avg_score: float

class UserResponseWithStats(BaseModel):
    user: UserResponse
    stats: UserStats
'''

# === schemas/email.py ===
email_py = '''from pydantic import BaseModel
from typing import Optional

class AllowedEmailBase(BaseModel):
    email: str

class AllowedEmailResponse(AllowedEmailBase):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    tg_username: Optional[str] = None
    
    class Config:
        from_attributes = True
'''

# === schemas/image.py ===
image_py = '''from pydantic import BaseModel
from typing import Optional

class ImageUploadResponse(BaseModel):
    url: str
    filename: Optional[str] = None
    size: Optional[int] = None
'''

# === schemas/assignment.py ===
assignment_py = '''from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

class TestAssignmentCreate(BaseModel):
    test_id: int
    user_ids: List[int]
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
    total_points: Optional[int] = None
    result_id: Optional[int] = None

class StudentAssignmentResponse(BaseModel):
    """Для студента - список назначенных тестов"""
    assignment_id: int
    test_id: int
    test_title: Optional[str] = None
    assigned_at: datetime
    due_date: Optional[datetime] = None
    is_completed: bool
    total_tasks: int = 0

class TestGroupAssignment(BaseModel):
    test_id: int
    group_id: int
    due_date: Optional[datetime] = None
'''

# === schemas/theory.py ===
theory_py = '''from pydantic import BaseModel
from typing import Optional

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
'''

# === schemas/ai.py ===
ai_py = '''from pydantic import BaseModel
from typing import Optional

class AITestRequest(BaseModel):
    prompt: str
    task_count: int = 10
    difficulty: Optional[str] = None
'''

# === schemas/__init__.py ===
init_py = '''from schemas.task import TaskBase, TaskResponse, TaskCreate, TaskCreateRequest, TaskUpdateRequest
from schemas.answer import AnswerSubmitRequest, AnswerResponse
from schemas.test import TestCreate, TestCreateRequest, TestResponse, TestResultResponse
from schemas.user import UserRegister, UserResponse, UserUpdate, ForgotPasswordRequest, ResetPasswordRequest, AssignStudentRequest
from schemas.stats import UserStats, UserResponseWithStats
from schemas.email import AllowedEmailBase, AllowedEmailResponse
from schemas.image import ImageUploadResponse
from schemas.assignment import TestAssignmentCreate, TestAssignmentResponse, StudentAssignmentResponse, TestGroupAssignment
from schemas.theory import TheoryBase, TheoryCreate, TheoryUpdate, TheoryResponse
from schemas.ai import AITestRequest

__all__ = [
    "TaskBase", "TaskResponse", "TaskCreate", "TaskCreateRequest", "TaskUpdateRequest",
    "AnswerSubmitRequest", "AnswerResponse",
    "TestCreate", "TestCreateRequest", "TestResponse", "TestResultResponse",
    "UserRegister", "UserResponse", "UserUpdate",
    "ForgotPasswordRequest", "ResetPasswordRequest", "AssignStudentRequest",
    "UserStats", "UserResponseWithStats",
    "AllowedEmailBase", "AllowedEmailResponse",
    "ImageUploadResponse",
    "TestAssignmentCreate", "TestAssignmentResponse", "StudentAssignmentResponse", "TestGroupAssignment",
    "TheoryBase", "TheoryCreate", "TheoryUpdate", "TheoryResponse",
    "AITestRequest",
]
'''

# Записываем все файлы
files = {
    "task.py": task_py,
    "answer.py": answer_py,
    "test.py": test_py,
    "user.py": user_py,
    "stats.py": stats_py,
    "email.py": email_py,
    "image.py": image_py,
    "assignment.py": assignment_py,
    "theory.py": theory_py,
    "ai.py": ai_py,
    "__init__.py": init_py,
}

for filename, content in files.items():
    filepath = os.path.join(output_dir, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"✅ Создан: {filepath}")

print(f"\n📁 Всего файлов: {len(files)}")
print(f"📂 Папка: {output_dir}")
