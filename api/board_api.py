"""Доски: документ целиком, картинки в R2, шаблоны GeoGebra учителя."""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from core import auth
from core.database import get_db
from core.models import User
from dto_schemas.board import (
    BoardDocument,
    BoardImageUpload,
    BoardMeta,
    DraftCreate,
    GeogebraTemplateDocument,
    GeogebraTemplateMeta,
    StudentLessonBoards,
    TeacherLessonBoards,
)
from services.board_service import BoardService, BoardServiceError

student_board_router = APIRouter(prefix="/student", tags=["Student boards"])
teacher_board_router = APIRouter(prefix="/teacher", tags=["Teacher boards"])
template_router = APIRouter(prefix="/board", tags=["GeoGebra templates"])


def get_board_service(db: AsyncSession = Depends(get_db)) -> BoardService:
    return BoardService(db)


def _error(exc: BoardServiceError):
    if exc.status == 409 and isinstance(exc.detail, dict):
        return JSONResponse(status_code=409, content=exc.detail)
    raise HTTPException(status_code=exc.status, detail=exc.detail)


async def _read_upload(file: UploadFile) -> tuple[bytes, str]:
    return await file.read(), file.filename or ""


# ── Ученик ────────────────────────────────────────────────────


@student_board_router.get("/boards", response_model=list[BoardMeta])
async def list_student_boards(
    current_user: User = Depends(auth.get_current_user),
    service: BoardService = Depends(get_board_service),
):
    try:
        return await service.list_student_boards(current_user)
    except BoardServiceError as exc:
        return _error(exc)


@student_board_router.post("/boards", response_model=BoardDocument)
async def create_draft(
    body: DraftCreate,
    current_user: User = Depends(auth.get_current_user),
    service: BoardService = Depends(get_board_service),
):
    try:
        return await service.create_draft(current_user, body.title)
    except BoardServiceError as exc:
        return _error(exc)


@student_board_router.post("/boards/images", response_model=BoardImageUpload)
async def upload_student_image(
    file: UploadFile = File(...),
    current_user: User = Depends(auth.get_current_user),
    service: BoardService = Depends(get_board_service),
):
    data, name = await _read_upload(file)
    try:
        return await service.upload_image(current_user, name, data)
    except BoardServiceError as exc:
        return _error(exc)


@student_board_router.get("/boards/{board_id}", response_model=BoardDocument)
async def get_student_board(
    board_id: uuid.UUID,
    current_user: User = Depends(auth.get_current_user),
    service: BoardService = Depends(get_board_service),
):
    try:
        return await service.get_for_student(current_user, board_id)
    except BoardServiceError as exc:
        return _error(exc)


@student_board_router.put("/boards/{board_id}", response_model=BoardDocument)
async def put_student_board(
    board_id: uuid.UUID,
    body: dict = Body(...),
    current_user: User = Depends(auth.get_current_user),
    service: BoardService = Depends(get_board_service),
):
    try:
        return await service.put_for_student(current_user, board_id, body)
    except BoardServiceError as exc:
        return _error(exc)


@student_board_router.delete("/boards/{board_id}")
async def delete_student_draft(
    board_id: uuid.UUID,
    current_user: User = Depends(auth.get_current_user),
    service: BoardService = Depends(get_board_service),
):
    try:
        await service.delete_draft(current_user, board_id)
        return {"ok": True}
    except BoardServiceError as exc:
        return _error(exc)


@student_board_router.get("/lessons/{lesson_id}/board", response_model=StudentLessonBoards)
async def open_student_lesson_board(
    lesson_id: int,
    current_user: User = Depends(auth.get_current_user),
    service: BoardService = Depends(get_board_service),
):
    try:
        return await service.open_student_lesson(current_user, lesson_id)
    except BoardServiceError as exc:
        return _error(exc)


# ── Учитель ───────────────────────────────────────────────────


@teacher_board_router.get("/lessons/{lesson_id}/boards", response_model=TeacherLessonBoards)
async def open_teacher_lesson_boards(
    lesson_id: int,
    current_user: User = Depends(auth.check_teacher),
    service: BoardService = Depends(get_board_service),
):
    try:
        return await service.open_teacher_lesson(current_user, lesson_id)
    except BoardServiceError as exc:
        return _error(exc)


@teacher_board_router.post("/boards/images", response_model=BoardImageUpload)
async def upload_teacher_image(
    file: UploadFile = File(...),
    current_user: User = Depends(auth.check_teacher),
    service: BoardService = Depends(get_board_service),
):
    data, name = await _read_upload(file)
    try:
        return await service.upload_image(current_user, name, data)
    except BoardServiceError as exc:
        return _error(exc)


@teacher_board_router.get("/boards/{board_id}", response_model=BoardDocument)
async def get_teacher_board(
    board_id: uuid.UUID,
    current_user: User = Depends(auth.check_teacher),
    service: BoardService = Depends(get_board_service),
):
    try:
        return await service.get_for_teacher(current_user, board_id)
    except BoardServiceError as exc:
        return _error(exc)


@teacher_board_router.put("/boards/{board_id}", response_model=BoardDocument)
async def put_teacher_board(
    board_id: uuid.UUID,
    body: dict = Body(...),
    current_user: User = Depends(auth.check_teacher),
    service: BoardService = Depends(get_board_service),
):
    try:
        return await service.put_for_teacher(current_user, board_id, body)
    except BoardServiceError as exc:
        return _error(exc)


@teacher_board_router.post("/geogebra-templates", response_model=GeogebraTemplateDocument)
async def create_geogebra_template(
    id: str = Form(...),
    title: str = Form(...),
    appName: str = Form(...),
    file: UploadFile = File(...),
    current_user: User = Depends(auth.check_teacher),
    service: BoardService = Depends(get_board_service),
):
    data, name = await _read_upload(file)
    try:
        return await service.create_template(current_user, id, title, appName, data, name)
    except BoardServiceError as exc:
        return _error(exc)


@teacher_board_router.put("/geogebra-templates/{template_id}", response_model=GeogebraTemplateDocument)
async def update_geogebra_template(
    template_id: str,
    title: Optional[str] = Form(None),
    appName: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    current_user: User = Depends(auth.check_teacher),
    service: BoardService = Depends(get_board_service),
):
    data, name = (None, "")
    if file is not None:
        data, name = await _read_upload(file)
    try:
        return await service.update_template(current_user, template_id, title, appName, data, name)
    except BoardServiceError as exc:
        return _error(exc)


@teacher_board_router.delete("/geogebra-templates/{template_id}")
async def delete_geogebra_template(
    template_id: str,
    current_user: User = Depends(auth.check_teacher),
    service: BoardService = Depends(get_board_service),
):
    try:
        await service.delete_template(current_user, template_id)
        return {"ok": True}
    except BoardServiceError as exc:
        return _error(exc)


# ── Каталог шаблонов ──────────────────────────────────────────


@template_router.get("/geogebra-templates", response_model=list[GeogebraTemplateMeta])
async def list_geogebra_templates(
    current_user: User = Depends(auth.get_current_user),
    service: BoardService = Depends(get_board_service),
):
    try:
        return await service.list_templates(current_user)
    except BoardServiceError as exc:
        return _error(exc)


@template_router.get("/geogebra-templates/{template_id}", response_model=GeogebraTemplateDocument)
async def get_geogebra_template(
    template_id: str,
    lessonId: Optional[int] = Query(None),
    current_user: User = Depends(auth.get_current_user),
    service: BoardService = Depends(get_board_service),
):
    try:
        return await service.get_template(current_user, template_id, lessonId)
    except BoardServiceError as exc:
        return _error(exc)
