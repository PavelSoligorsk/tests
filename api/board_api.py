"""Доски: список и создание по HTTP, живые правки по WebSocket, картинки в R2, шаблоны GeoGebra."""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, WebSocket
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.websockets import WebSocketDisconnect

from core import auth
from core.database import get_db, get_session_factory
from core.models import User
from dto_schemas.board import (
    BoardCreate,
    BoardDocument,
    BoardImageUpload,
    BoardMeta,
    GeogebraTemplateDocument,
    GeogebraTemplateMeta,
)
from services.board_room import (
    CLOSE_FORBIDDEN,
    CLOSE_NOT_FOUND,
    CLOSE_UNAUTHORIZED,
    BoardRoom,
    RoomClient,
    board_rooms,
)
from services.board_service import BoardService, BoardServiceError, DbBoardStore

student_board_router = APIRouter(prefix="/student", tags=["Student boards"])
teacher_board_router = APIRouter(prefix="/teacher", tags=["Teacher boards"])
template_router = APIRouter(prefix="/board", tags=["GeoGebra templates"])

log = logging.getLogger(__name__)


def get_board_service(db: AsyncSession = Depends(get_db)) -> BoardService:
    return BoardService(db)


def _error(exc: BoardServiceError):
    if exc.status == 409 and isinstance(exc.detail, dict):
        return JSONResponse(status_code=409, content=exc.detail)
    raise HTTPException(status_code=exc.status, detail=exc.detail)


async def _read_upload(file: UploadFile) -> tuple[bytes, str]:
    return await file.read(), file.filename or ""


def _close_reason(text: str) -> str:
    # В WebSocket причина закрытия — не больше 123 байт.
    encoded = str(text).encode("utf-8")[:123]
    return encoded.decode("utf-8", errors="ignore")


async def _board_socket(
    websocket: WebSocket,
    board_id: uuid.UUID,
    token: Optional[str],
    session_factory: async_sessionmaker[AsyncSession],
    as_teacher: bool,
) -> None:
    await websocket.accept()
    async with session_factory() as db:
        user = await auth.user_from_token(token, db)
        if user is None:
            await websocket.close(code=CLOSE_UNAUTHORIZED, reason="Нужен вход")
            return
        try:
            await BoardService(db).authorize_room(user, board_id, as_teacher)
        except BoardServiceError as exc:
            code = CLOSE_NOT_FOUND if exc.status == 404 else CLOSE_FORBIDDEN
            await websocket.close(code=code, reason=_close_reason(exc.detail))
            return
        name = " ".join(part for part in (user.first_name, user.last_name) if part) or user.username
        client = RoomClient(user_id=user.id, name=name, role=user.role)

    room = await board_rooms.join(str(board_id), client, DbBoardStore(session_factory))
    if room is None:
        await websocket.close(code=CLOSE_NOT_FOUND, reason=_close_reason("Доска не найдена"))
        return
    await _serve(websocket, room, client)


async def _serve(websocket: WebSocket, room: BoardRoom, client: RoomClient) -> None:
    async def read() -> None:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                return
            text = message.get("text")
            if text is None:
                data = message.get("bytes") or b""
                text = data.decode("utf-8", errors="replace")
            await room.handle(client, text)

    async def write() -> None:
        while True:
            text = await client.outbox.get()
            if text is None:
                await websocket.close(code=client.close_code or 1000)
                return
            await websocket.send_text(text)

    tasks = [asyncio.create_task(read()), asyncio.create_task(write())]
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            exc = task.exception()
            if exc is not None and not isinstance(exc, (WebSocketDisconnect, RuntimeError)):
                log.warning("Соединение доски %s оборвалось: %r", room.board_id, exc)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await board_rooms.leave(room, client)


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


@student_board_router.websocket("/boards/{board_id}/ws")
async def student_board_socket(
    websocket: WebSocket,
    board_id: uuid.UUID,
    token: Optional[str] = Query(None),
    session_factory: async_sessionmaker[AsyncSession] = Depends(get_session_factory),
):
    await _board_socket(websocket, board_id, token, session_factory, as_teacher=False)


# ── Учитель ───────────────────────────────────────────────────


@teacher_board_router.get("/boards", response_model=list[BoardMeta])
async def list_teacher_boards(
    current_user: User = Depends(auth.check_teacher),
    service: BoardService = Depends(get_board_service),
):
    try:
        return await service.list_teacher_boards(current_user)
    except BoardServiceError as exc:
        return _error(exc)


@teacher_board_router.post("/boards", response_model=BoardDocument)
async def create_board(
    body: BoardCreate,
    current_user: User = Depends(auth.check_teacher),
    service: BoardService = Depends(get_board_service),
):
    try:
        return await service.create_board(current_user, body.title, body.student_ids, body.group_id)
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


@teacher_board_router.delete("/boards/{board_id}")
async def delete_teacher_board(
    board_id: uuid.UUID,
    current_user: User = Depends(auth.check_teacher),
    service: BoardService = Depends(get_board_service),
):
    try:
        await service.delete_for_teacher(current_user, board_id)
        return {"ok": True}
    except BoardServiceError as exc:
        return _error(exc)


@teacher_board_router.websocket("/boards/{board_id}/ws")
async def teacher_board_socket(
    websocket: WebSocket,
    board_id: uuid.UUID,
    token: Optional[str] = Query(None),
    session_factory: async_sessionmaker[AsyncSession] = Depends(get_session_factory),
):
    await _board_socket(websocket, board_id, token, session_factory, as_teacher=True)


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
