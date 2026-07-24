from pydantic import BaseModel
from typing import Optional

class AITestRequest(BaseModel):
    prompt: str
    task_count: int = 10
    difficulty: Optional[str] = None

    class Config:
        from_attributes = True