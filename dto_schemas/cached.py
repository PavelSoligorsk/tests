from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, RootModel

from dto_schemas.stats import UserResponseWithStats
from dto_schemas.task import TaskResponse
from dto_schemas.test import TestResponse
from dto_schemas.user import UserResponse


class TaskShortResponse(BaseModel):
    id: int
    content: str

    model_config = ConfigDict(from_attributes=True)


class TestSummaryResponse(BaseModel):
    id: int
    title: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class StudentHistoryItemResponse(BaseModel):
    id: int
    test_id: int
    user_id: int
    total_points: int
    completed_at: Optional[datetime] = None
    test_title: str
    test: Optional[TestSummaryResponse] = None

    model_config = ConfigDict(from_attributes=True)


class DifficultyStatResponse(BaseModel):
    total: int
    correct: int

    model_config = ConfigDict(from_attributes=True)


class ResultUserResponse(BaseModel):
    first_name: str
    last_name: str

    model_config = ConfigDict(from_attributes=True)


class DetailedResultDetailResponse(BaseModel):
    task_id: int
    content: str
    options: Optional[list[str]] = None
    correct_answer: str
    user_answer: str
    is_correct: bool
    solution: Optional[str] = None
    difficulty: Optional[int] = None
    points_earned: Optional[int] = None
    max_task_points: Optional[int] = None
    hint: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class DetailedResultResponse(BaseModel):
    test_title: str
    total_points: int
    max_points: int
    completed_at: Optional[datetime] = None
    difficulty_stats: dict[str, DifficultyStatResponse] = Field(default_factory=dict)
    details: list[DetailedResultDetailResponse] = Field(default_factory=list)
    user: Optional[ResultUserResponse] = None

    model_config = ConfigDict(from_attributes=True)


class StudentAssignmentItemResponse(BaseModel):
    assignment_id: int
    test_id: int
    test_title: str
    target_class: Optional[str] = None
    target_topic: Optional[str] = None
    is_autocompile: Optional[bool] = None
    tasks: list[TaskShortResponse] = Field(default_factory=list)
    assigned_at: Optional[datetime] = None
    due_date: Optional[datetime] = None
    is_completed: bool = False
    completed_at: Optional[datetime] = None
    total_tasks: int = 0
    time_left: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class StudentAssignmentMetaItemResponse(BaseModel):
    assignment_id: int
    test_id: int
    test_title: str
    target_class: Optional[str] = None
    target_topic: Optional[str] = None
    is_autocompile: Optional[bool] = None
    tasks_count: int = 0
    due_date: Optional[datetime] = None
    is_completed: bool = False
    assigned_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class StudentAITestItemResponse(BaseModel):
    id: int
    title: Optional[str] = None
    target_class: Optional[str] = None
    target_topic: Optional[str] = None
    is_ai_generated: bool = True
    tasks_count: int = 0
    is_active: bool = True
    is_completed: bool = False
    has_incomplete_attempt: bool = False
    result_id: Optional[int] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class AvailableTestMetaResponse(BaseModel):
    id: int
    title: Optional[str] = None
    target_class: Optional[str] = None
    target_topic: Optional[str] = None
    is_autocompile: bool = False
    is_ai_generated: bool = False
    tasks_count: int = 0
    is_active: bool = True

    model_config = ConfigDict(from_attributes=True)


class TheoryTopicSummaryResponse(BaseModel):
    topic: str
    label: str
    sections_count: int

    model_config = ConfigDict(from_attributes=True)


class TheorySectionSummaryResponse(BaseModel):
    section: str
    theory_id: int

    model_config = ConfigDict(from_attributes=True)


class TeacherGroupStudentResponse(BaseModel):
    id: int
    first_name: str
    last_name: str
    username: str
    tg_username: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class TeacherGroupResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    students_count: int = 0
    created_at: Optional[datetime] = None
    students: list[TeacherGroupStudentResponse] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class TeacherHistoryResultResponse(BaseModel):
    id: int
    total_points: int
    completed_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class TeacherHistoryItemResponse(BaseModel):
    test_title: str
    result: TeacherHistoryResultResponse

    model_config = ConfigDict(from_attributes=True)


class TeacherAssignmentItemResponse(BaseModel):
    id: int
    test_id: int
    test_title: str
    user_id: int
    student_name: str
    student_username: Optional[str] = None
    assigned_at: datetime
    due_date: Optional[datetime] = None
    is_completed: bool = False
    completed_at: Optional[datetime] = None
    total_tasks: int = 0
    total_points: Optional[int] = None
    max_points: Optional[int] = None
    percentage: Optional[float] = None
    result_id: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


class TaskGroupedResponse(BaseModel):
    grouped: dict[str, dict[str, list[TaskResponse]]]
    total_tasks: int
    available_classes: list[str]

    model_config = ConfigDict(from_attributes=True)


class TaskClassTopicMetaResponse(RootModel[dict[str, dict[str, int]]]):
    model_config = ConfigDict(from_attributes=True)


class TopicSectionMetaResponse(RootModel[dict[str, dict[str, int]]]):
    model_config = ConfigDict(from_attributes=True)


class TeacherTaskMetaByTopicSectionResponse(RootModel[dict[str, dict[str, int]]]):
    model_config = ConfigDict(from_attributes=True)


class TeacherTaskMetaResponse(RootModel[dict[str, dict[str, int]]]):
    model_config = ConfigDict(from_attributes=True)


class TeacherTaskSectionResponse(BaseModel):
    section: str
    theory_id: int

    model_config = ConfigDict(from_attributes=True)


class TeacherTasksByClassTopicResponse(RootModel[list[TaskResponse]]):
    model_config = ConfigDict(from_attributes=True)


class TeacherStudentProfileResponse(UserResponseWithStats):
    model_config = ConfigDict(from_attributes=True)


class TestCacheResponse(TestResponse):
    model_config = ConfigDict(from_attributes=True)


class UserCacheResponse(UserResponse):
    model_config = ConfigDict(from_attributes=True)


# ============ TEACHER-SPECIFIC ============

class GroupAssignResponse(BaseModel):
    message: str
    assigned_count: int
    group_id: int
    test_id: int

    model_config = ConfigDict(from_attributes=True)


class AddStudentsToGroupResponse(BaseModel):
    message: str
    added: int

    model_config = ConfigDict(from_attributes=True)


class TeacherTaskDetailResponse(BaseModel):
    id: int
    content: str
    options: Optional[list[str]] = None
    answer: str
    hint: Optional[str] = None
    solution: Optional[str] = None
    is_open_answer: bool = False
    difficulty: Optional[int] = None
    topic: Optional[str] = None
    section: Optional[str] = None
    topic_number: Optional[str] = None
    task_class: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


# ============ STUDENT-SPECIFIC ============

class StartTestTaskItem(BaseModel):
    id: int
    content: str
    options: Optional[list[str]] = None
    is_open_answer: bool = False
    difficulty: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


class StartAssignedTestResponse(BaseModel):
    result_id: int
    test_title: str
    tasks: list[StartTestTaskItem] = Field(default_factory=list)
    time_limit: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class SubmitTestResponse(BaseModel):
    status: str
    score: int
    max_score_possible: int

    model_config = ConfigDict(from_attributes=True)


class AIHintContext(BaseModel):
    task_class: Optional[str] = None
    topic_number: Optional[str] = None
    difficulty: Optional[int] = None
    topic_mastery_percent: Optional[float] = None

    model_config = ConfigDict(from_attributes=True)


class AIHintResponse(BaseModel):
    task_id: int
    hint: str
    context: AIHintContext

    model_config = ConfigDict(from_attributes=True)


class AISolutionContext(BaseModel):
    task_class: Optional[str] = None
    topic_number: Optional[str] = None
    difficulty: Optional[int] = None
    topic_mastery_percent: Optional[float] = None

    model_config = ConfigDict(from_attributes=True)


class AISolutionResponse(BaseModel):
    task_id: int
    success: bool
    verified: bool = False
    message: str = ""
    ai_solution: str = ""
    ai_answer: str = ""
    correct_answer: str = ""
    context: AISolutionContext = Field(default_factory=AISolutionContext)

    model_config = ConfigDict(from_attributes=True)


class AITheoryContext(BaseModel):
    topic: str = ""
    section: str = ""

    model_config = ConfigDict(from_attributes=True)


class AITheoryResponse(BaseModel):
    success: bool
    question: str
    answer: str
    context: AITheoryContext

    model_config = ConfigDict(from_attributes=True)
