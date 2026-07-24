from pydantic import BaseModel, model_validator
from typing import List, Optional
from datetime import datetime
from dto_schemas.task import TaskResponse
from dto_schemas.answer import AnswerResponse

class TestCreate(BaseModel):
    title: str
    target_class: Optional[str] = None
    target_topic: Optional[str] = None
    is_autocompile: bool = False
    task_ids: Optional[List[int]] = None
    is_active: bool = True

    class Config:
        from_attributes = True

class TestCreateRequest(BaseModel):
    user_id: int
    task_ids: List[int]

    class Config:
        from_attributes = True

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