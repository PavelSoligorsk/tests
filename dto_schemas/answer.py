from pydantic import BaseModel, ConfigDict
from typing import Optional


class TestAnswerSubmission(BaseModel):
    task_id: int
    user_answer: str | int | list[str] | list[int]

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