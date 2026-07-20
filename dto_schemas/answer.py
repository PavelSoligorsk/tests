from pydantic import BaseModel
from typing import Optional

class AnswerSubmitRequest(BaseModel):
    task_id: int
    user_id: int
    test_id: int
    answer_text: str

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