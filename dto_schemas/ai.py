from pydantic import BaseModel, ConfigDict, Field
from typing import Optional


class TheoryQuestionRequest(BaseModel):
    theory_id: Optional[int] = None
    question: str
    theory_content: str = ""

    model_config = ConfigDict(from_attributes=True)


class AITestRequest(BaseModel):
    prompt: str
    task_count: int = 10
    difficulty: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class TeacherAITestRequest(BaseModel):
    """Запрос на генерацию AI-теста учителем."""
    prompt: str
    task_count: int = Field(default=10, ge=1, le=50)
    difficulty: Optional[str] = None
    student_ids: Optional[list[int]] = None
    group_id: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)