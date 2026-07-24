from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict


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
