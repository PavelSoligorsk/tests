from pydantic import BaseModel, ConfigDict
from typing import Optional


class TestAnswerSubmission(BaseModel):
    task_id: int
    user_answer: str | int | list[str] | list[int]

    model_config = ConfigDict(from_attributes=True)

class SaveProgressRequest(BaseModel):
    """Ответы для инкрементального сохранения (без финализации теста)."""
    answers: list[TestAnswerSubmission]

    model_config = ConfigDict(from_attributes=True)

class SavedAnswerItem(BaseModel):
    """Ранее сохранённый ответ (для возобновления теста)."""
    task_id: int
    user_answer: str

    model_config = ConfigDict(from_attributes=True)

class SaveProgressResponse(BaseModel):
    """Ответ на сохранение прогресса."""
    status: str
    saved_count: int
    result_id: int
    total_tasks_in_test: int

    model_config = ConfigDict(from_attributes=True)

class AnswerSubmitRequest(BaseModel):
    task_id: int
    user_id: int
    test_id: int
    answer_text: str

    model_config = ConfigDict(from_attributes=True)

class AnswerResponse(BaseModel):
    id: int
    task_id: int
    user_id: int
    test_id: Optional[int]
    points_earned: int
    is_correct: bool
    attempt_number: int

    model_config = ConfigDict(from_attributes=True)