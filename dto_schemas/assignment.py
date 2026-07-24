from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

class TestAssignmentCreate(BaseModel):
    test_id: int
    user_ids: List[int]
    due_date: Optional[datetime] = None

    class Config:
        from_attributes = True

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

    class Config:
        from_attributes = True

class StudentAssignmentResponse(BaseModel):
    assignment_id: int
    test_id: int
    test_title: Optional[str] = None
    assigned_at: datetime
    due_date: Optional[datetime] = None
    is_completed: bool
    total_tasks: int = 0

    class Config:
        from_attributes = True

class TestGroupAssignment(BaseModel):
    test_id: int
    group_id: int
    due_date: Optional[datetime] = None

    class Config:
        from_attributes = True