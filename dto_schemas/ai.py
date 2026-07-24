from pydantic import BaseModel, ConfigDict
from typing import Optional

class AITestRequest(BaseModel):
    prompt: str
    task_count: int = 10
    difficulty: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)