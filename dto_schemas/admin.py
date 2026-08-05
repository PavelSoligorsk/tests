from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from dto_schemas.task import TaskBase, TaskResponse


class ChangeUserRoleRequest(BaseModel):
    new_role: str

    model_config = ConfigDict(from_attributes=True)


class SendTaskToTgRequest(BaseModel):
    chat_id: str

    model_config = ConfigDict(from_attributes=True)


class AllowedEmailItemResponse(BaseModel):
    email: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    tg_username: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class RebuildTestsResponse(BaseModel):
    status: str
    message: str
    updated_test_ids: list[int]
    deleted_count: int

    model_config = ConfigDict(from_attributes=True)


class RecomputeAnswersResponse(BaseModel):
    answers_updated: int
    results_updated: int

    model_config = ConfigDict(from_attributes=True)


# ==================== ПАКЕТНЫЕ ОПЕРАЦИИ С ЗАДАНИЯМИ ====================


class BatchTaskCreateItem(TaskBase):
    """Одно задание в пакете для создания"""

    @model_validator(mode='after')
    def validate_options(self):
        if not self.is_open_answer and (not self.options or len(self.options) == 0):
            raise ValueError(f"task_class={self.task_class} topic_number={self.topic_number}: для закрытого задания поле options обязательно.")
        if self.is_open_answer and self.options:
            raise ValueError(f"task_class={self.task_class} topic_number={self.topic_number}: для открытого задания поле options должно быть пустым.")
        if not self.content or not self.content.strip():
            raise ValueError(f"task_class={self.task_class} topic_number={self.topic_number}: поле content обязательно.")
        if not self.answer or not self.answer.strip():
            raise ValueError(f"task_class={self.task_class} topic_number={self.topic_number}: поле answer обязательно.")
        if not self.task_class or not self.task_class.strip():
            raise ValueError("Поле task_class обязательно.")
        if not self.topic_number or not self.topic_number.strip():
            raise ValueError("Поле topic_number обязательно.")
        return self


class BatchTaskCreateRequest(BaseModel):
    """Запрос на пакетное создание заданий"""
    tasks: list[BatchTaskCreateItem] = Field(..., min_length=1, max_length=500)


class BatchTaskCreateResponse(BaseModel):
    """Ответ на пакетное создание заданий"""
    created: list[TaskResponse]
    total: int

    model_config = ConfigDict(from_attributes=True)


class BatchTaskUpdateItem(BaseModel):
    """Одно задание в пакете для обновления"""
    id: int
    task_class: Optional[str] = None
    topic_number: Optional[str] = None
    topic: Optional[str] = None
    section: Optional[str] = None
    content: Optional[str] = None
    options: Optional[list[str]] = None
    answer: Optional[str] = None
    hint: Optional[str] = None
    solution: Optional[str] = None
    is_open_answer: Optional[bool] = None
    difficulty: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode='after')
    def validate_options(self):
        if self.is_open_answer is not None:
            if not self.is_open_answer and self.options is not None and len(self.options) == 0:
                raise ValueError(f"id={self.id}: для закрытого задания options не может быть пустым.")
            if self.is_open_answer and self.options is not None and len(self.options) > 0:
                raise ValueError(f"id={self.id}: для открытого задания options должно быть пустым.")
        if self.difficulty is not None and (self.difficulty < 1 or self.difficulty > 5):
            raise ValueError(f"id={self.id}: difficulty должно быть от 1 до 5.")
        return self


class BatchTaskUpdateRequest(BaseModel):
    """Запрос на пакетное обновление заданий"""
    tasks: list[BatchTaskUpdateItem] = Field(..., min_length=1, max_length=500)


class BatchTaskUpdateResponse(BaseModel):
    """Ответ на пакетное обновление заданий"""
    updated: list[TaskResponse]
    not_found: list[int]
    total_updated: int

    model_config = ConfigDict(from_attributes=True)


class BatchTaskDeleteRequest(BaseModel):
    """Запрос на пакетное удаление заданий"""
    ids: list[int] = Field(..., min_length=1, max_length=500)


class BatchTaskDeleteResponse(BaseModel):
    """Ответ на пакетное удаление заданий"""
    deleted: list[int]
    not_found: list[int]
    total_deleted: int

    model_config = ConfigDict(from_attributes=True)


# ==================== AI-КЛАССИФИКАЦИЯ ЗАДАНИЙ ====================


class ClassifyTasksRequest(BaseModel):
    """Запрос на AI-классификацию заданий"""
    task_ids: list[int] = Field(default=[], description="Список ID заданий. Пустой массив = все задания.")
    include_classified: bool = Field(default=False, description="True — включая уже классифицированные, False — только неклассифицированные")


class ClassifyTasksResponse(BaseModel):
    """Результат AI-классификации (topic/section)"""
    total_processed: int
    classified: int
    failed: int
    log: list[str] = []

    model_config = ConfigDict(from_attributes=True)
