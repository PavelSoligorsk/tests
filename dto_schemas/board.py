"""Контракт доски: camelCase, как ждёт фронт."""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class Camera(BaseModel):
    x: float
    y: float
    zoom: float


class BoardDocument(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    title: str
    teacher_id: int = Field(alias="teacherId")
    group_id: Optional[int] = Field(None, alias="groupId")
    student_ids: list[int] = Field(default_factory=list, alias="studentIds")
    revision: int
    created_at: str = Field(alias="createdAt")
    updated_at: str = Field(alias="updatedAt")
    camera: Camera
    objects: list[dict[str, Any]]


class BoardMeta(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    title: str
    teacher_id: int = Field(alias="teacherId")
    group_id: Optional[int] = Field(None, alias="groupId")
    student_ids: list[int] = Field(default_factory=list, alias="studentIds")
    created_at: str = Field(alias="createdAt")
    updated_at: str = Field(alias="updatedAt")
    object_count: int = Field(alias="objectCount")


class BoardCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    title: str
    student_ids: Optional[list[int]] = Field(None, alias="studentIds")
    group_id: Optional[int] = Field(None, alias="groupId")


class BoardImageUpload(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    file_id: str = Field(alias="fileId")
    name: str
    src: str


class GeogebraTemplateMeta(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    title: str
    app_name: str = Field(alias="appName")
    teacher_id: int = Field(alias="teacherId")


class GeogebraTemplateDocument(GeogebraTemplateMeta):
    ggb_base64: str = Field(alias="ggbBase64")
