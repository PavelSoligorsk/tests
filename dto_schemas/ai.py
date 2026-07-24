from pydantic import BaseModel, ConfigDict
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