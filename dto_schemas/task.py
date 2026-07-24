from pydantic import BaseModel, ConfigDict, Field, model_validator
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

    model_config = ConfigDict(from_attributes=True)

class TaskResponse(TaskBase):
    id: int
    model_config = ConfigDict(from_attributes=True)

class TaskCreate(TaskBase):
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

    model_config = ConfigDict(from_attributes=True)