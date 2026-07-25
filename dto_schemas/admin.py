from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

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
    pass


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
