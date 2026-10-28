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
    share_access: Optional[str] = Field(None, alias="shareAccess")
    share_token: Optional[str] = Field(None, alias="shareToken")
    series_id: Optional[str] = Field(None, alias="seriesId")


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
    share_access: Optional[str] = Field(None, alias="shareAccess")
    series_id: Optional[str] = Field(None, alias="seriesId")


class BoardCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    title: str
    student_ids: Optional[list[int]] = Field(None, alias="studentIds")
    group_id: Optional[int] = Field(None, alias="groupId")
    # Новая страница серии: id любой доски этой серии.
    series_id: Optional[str] = Field(None, alias="seriesId")


class BoardShareUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    access: str
    reset_link: bool = Field(False, alias="resetLink")


class BoardShare(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    share_access: str = Field(alias="shareAccess")
    share_token: Optional[str] = Field(None, alias="shareToken")


class SharedBoardDocument(BoardDocument):
    can_edit: bool = Field(alias="canEdit")


class TheoryBoardImport(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    theory_id: int = Field(alias="theoryId")
    title: str
    objects: list[dict[str, Any]]


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
