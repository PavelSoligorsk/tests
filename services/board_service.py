"""Доски: доступ, создание, удаление, картинки и шаблоны. Правки идут через живую комнату."""
from __future__ import annotations

import base64
import re
import uuid
from datetime import datetime
from typing import Any, Callable, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from core.models import Board, BoardImage, BoardStudent, GeogebraTemplate, User
from dto_schemas.board import (
    BoardDocument,
    BoardImageUpload,
    BoardMeta,
    Camera,
    GeogebraTemplateDocument,
    GeogebraTemplateMeta,
)
from repositories.board_repository import BoardRepository, new_board
from services import board_scene as scene
from services.board_files import delete_keys, public_src, put_bytes
from services.board_room import board_rooms

MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_GGB_BYTES = 8 * 1024 * 1024
TEMPLATE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
APP_NAMES = {"geometry", "graphing"}

EXT_BY_TYPE = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}


class BoardServiceError(Exception):
    def __init__(self, status: int, detail: Any):
        self.status = status
        self.detail = detail


class BoardService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = BoardRepository(db)

    async def list_student_boards(self, student: User) -> list[BoardMeta]:
        self._require_student(student)
        boards = await self.repo.list_for_student(student.id)
        return await self._metas(boards)

    async def list_teacher_boards(self, teacher: User) -> list[BoardMeta]:
        self._require_teacher(teacher)
        boards = await self.repo.list_for_teacher(teacher.id)
        return await self._metas(boards)

    async def create_board(
        self, teacher: User, title: str, student_ids: Optional[list[int]], group_id: Optional[int]
    ) -> BoardDocument:
        self._require_teacher(teacher)
        clean = _clean_board_title(title)
        group_id, members = await self._audience(teacher.id, student_ids, group_id)
        board = new_board(title=clean, teacher_id=teacher.id, group_id=group_id)
        self.repo.add_board(board)
        for student_id in members:
            self.repo.add_member(BoardStudent(board_id=board.id, student_id=student_id))
        await self.repo.commit()
        return await self._document(board)

    async def get_for_student(self, student: User, board_id: uuid.UUID) -> BoardDocument:
        board = await self._student_board(student, board_id)
        return await self._live_or_stored(board)

    async def get_for_teacher(self, teacher: User, board_id: uuid.UUID) -> BoardDocument:
        self._require_teacher(teacher)
        board = await self._owned_board(teacher, board_id)
        return await self._live_or_stored(board)

    async def authorize_room(self, user: User, board_id: uuid.UUID, as_teacher: bool) -> None:
        if as_teacher:
            self._require_teacher(user)
            await self._owned_board(user, board_id)
        else:
            await self._student_board(user, board_id)

    async def load_document(self, board_id: uuid.UUID) -> Optional[BoardDocument]:
        board = await self.repo.get_board(board_id)
        if board is None:
            return None
        return await self._document(board)

    async def delete_for_teacher(self, teacher: User, board_id: uuid.UUID) -> None:
        self._require_teacher(teacher)
        board = await self._owned_board(teacher, board_id)
        board_key = str(board.id)
        keys = await self.repo.image_keys(board.id)
        await self.repo.delete_board(board)
        await self.repo.commit()
        await board_rooms.close_board(board_key)
        await delete_keys(keys)

    async def upload_image(self, user: User, filename: str, data: bytes) -> BoardImageUpload:
        if user.role not in ("student", "teacher", "admin"):
            raise BoardServiceError(403, "Нет доступа")
        if len(data) > MAX_IMAGE_BYTES:
            raise BoardServiceError(400, "Картинка больше 10 МБ")
        content_type = _sniff_image(data)
        if content_type is None:
            raise BoardServiceError(400, "Нужен файл jpeg, png или webp")
        file_id = uuid.uuid4()
        ext = EXT_BY_TYPE[content_type]
        key = f"boards/{file_id}.{ext}"
        name = (filename or f"image.{ext}")[:255]
        await put_bytes(key, data, content_type)
        self.repo.add_image(BoardImage(
            file_id=file_id,
            board_id=None,
            r2_key=key,
            name=name,
            content_type=content_type,
            uploaded_by=user.id,
            created_at=datetime.utcnow(),
        ))
        await self.repo.commit()
        return BoardImageUpload(file_id=str(file_id), name=name, src=public_src(key))

    async def list_templates(self, user: User) -> list[GeogebraTemplateMeta]:
        teacher_ids = await self._template_teacher_ids(user)
        rows = await self.repo.list_templates(teacher_ids)
        return [
            GeogebraTemplateMeta(
                id=row.id,
                title=row.title,
                app_name=row.app_name,
                teacher_id=row.teacher_id,
            )
            for row in rows
        ]

    async def get_template(
        self, user: User, template_id: str, lesson_id: Optional[int]
    ) -> GeogebraTemplateDocument:
        row = await self._pick_template(user, template_id, lesson_id)
        if row is None:
            raise BoardServiceError(404, "Шаблон не найден")
        return GeogebraTemplateDocument(
            id=row.id,
            title=row.title,
            app_name=row.app_name,
            teacher_id=row.teacher_id,
            ggb_base64=row.ggb_base64,
        )

    async def create_template(
        self, teacher: User, template_id: str, title: str, app_name: str, data: bytes, filename: str
    ) -> GeogebraTemplateDocument:
        self._require_teacher(teacher)
        template_id = _clean_template_id(template_id)
        title = _clean_title(title)
        app_name = _clean_app_name(app_name)
        encoded = _encode_ggb(data, filename)
        if await self.repo.get_template(teacher.id, template_id):
            raise BoardServiceError(409, "Шаблон с таким id уже есть")
        row = GeogebraTemplate(
            teacher_id=teacher.id,
            id=template_id,
            title=title,
            app_name=app_name,
            ggb_base64=encoded,
        )
        self.repo.add_template(row)
        await self.repo.commit()
        return GeogebraTemplateDocument(
            id=row.id, title=row.title, app_name=row.app_name,
            teacher_id=row.teacher_id, ggb_base64=row.ggb_base64,
        )

    async def update_template(
        self,
        teacher: User,
        template_id: str,
        title: Optional[str],
        app_name: Optional[str],
        data: Optional[bytes],
        filename: str,
    ) -> GeogebraTemplateDocument:
        self._require_teacher(teacher)
        row = await self.repo.get_template(teacher.id, template_id)
        if row is None:
            raise BoardServiceError(404, "Шаблон не найден")
        if title is None and app_name is None and data is None:
            raise BoardServiceError(400, "Нечего обновлять")
        if title is not None:
            row.title = _clean_title(title)
        if app_name is not None:
            row.app_name = _clean_app_name(app_name)
        if data is not None:
            row.ggb_base64 = _encode_ggb(data, filename)
        await self.repo.commit()
        return GeogebraTemplateDocument(
            id=row.id, title=row.title, app_name=row.app_name,
            teacher_id=row.teacher_id, ggb_base64=row.ggb_base64,
        )

    async def delete_template(self, teacher: User, template_id: str) -> None:
        self._require_teacher(teacher)
        row = await self.repo.get_template(teacher.id, template_id)
        if row is None:
            raise BoardServiceError(404, "Шаблон не найден")
        await self.repo.delete_template(row)
        await self.repo.commit()

    async def _live_or_stored(self, board: Board) -> BoardDocument:
        live = board_rooms.live_document(str(board.id))
        if live is not None:
            return BoardDocument.model_validate(live)
        return await self._document(board)

    async def _document(self, board: Board) -> BoardDocument:
        objects = [dict(obj) for obj in (board.objects or [])]
        images = await self.repo.images_for_board(board.id, scene.image_ids(objects))
        for obj in objects:
            if obj.get("type") != "image":
                continue
            props = dict(obj.get("props") or {})
            parsed = scene.parse_uuid(props.get("fileId"))
            image = images.get(parsed) if parsed else None
            props["src"] = public_src(image.r2_key) if image else ""
            obj["props"] = props
        camera = board.camera or {"x": 0, "y": 0, "zoom": 1}
        student_ids = [] if board.group_id else await self._member_ids(board.id)
        return BoardDocument(
            id=str(board.id),
            title=board.title,
            teacher_id=board.teacher_id,
            group_id=board.group_id,
            student_ids=student_ids,
            revision=board.revision,
            created_at=scene.iso_time(board.created_at),
            updated_at=scene.iso_time(board.updated_at),
            camera=Camera(x=camera["x"], y=camera["y"], zoom=camera["zoom"]),
            objects=objects,
        )

    async def _metas(self, boards: list[Board]) -> list[BoardMeta]:
        direct = [board.id for board in boards if board.group_id is None]
        members = await self.repo.student_ids_map(direct)
        return [self._meta(board, members.get(board.id, [])) for board in boards]

    def _meta(self, board: Board, student_ids: list[int]) -> BoardMeta:
        return BoardMeta(
            id=str(board.id),
            title=board.title,
            teacher_id=board.teacher_id,
            group_id=board.group_id,
            student_ids=[] if board.group_id else student_ids,
            updated_at=scene.iso_time(board.updated_at),
            object_count=board.object_count,
        )

    async def _member_ids(self, board_id: uuid.UUID) -> list[int]:
        found = await self.repo.student_ids_map([board_id])
        return found.get(board_id, [])

    async def _audience(
        self, teacher_id: int, student_ids: Optional[list[int]], group_id: Optional[int]
    ) -> tuple[Optional[int], list[int]]:
        has_students = bool(student_ids)
        has_group = group_id is not None
        if has_students == has_group:
            raise BoardServiceError(400, "Нужны ученики или группа, что-то одно")
        if has_group:
            group = await self.repo.owned_group(group_id, teacher_id)
            if group is None:
                raise BoardServiceError(404, "Группа не найдена")
            return group_id, []
        unique: list[int] = []
        for student_id in student_ids or []:
            if isinstance(student_id, bool) or not isinstance(student_id, int):
                raise BoardServiceError(400, "studentIds — список id учеников")
            if student_id not in unique:
                unique.append(student_id)
        if not await self.repo.owns_students(teacher_id, unique):
            raise BoardServiceError(400, "Ученик не привязан к учителю")
        return None, unique

    async def _student_board(self, student: User, board_id: uuid.UUID) -> Board:
        self._require_student(student)
        board = await self._board_or_404(board_id)
        if board.group_id is not None:
            allowed = await self.repo.student_in_group(board.group_id, student.id)
        else:
            allowed = await self.repo.is_board_member(board.id, student.id)
        if not allowed:
            raise BoardServiceError(403, "Нет доступа к этой доске")
        return board

    async def _owned_board(self, teacher: User, board_id: uuid.UUID) -> Board:
        board = await self._board_or_404(board_id)
        if board.teacher_id != teacher.id:
            raise BoardServiceError(403, "Нет доступа к этой доске")
        return board

    async def _board_or_404(self, board_id: uuid.UUID) -> Board:
        board = await self.repo.get_board(board_id)
        if board is None:
            raise BoardServiceError(404, "Доска не найдена")
        return board

    async def _teacher_lesson(self, teacher: User, lesson_id: int):
        lesson = await self.repo.get_lesson(lesson_id)
        if lesson is None or lesson.teacher_id != teacher.id:
            raise BoardServiceError(404, "Занятие не найдено")
        return lesson

    async def _student_in_lesson(self, student_id: int, lesson) -> bool:
        if lesson.lesson_type == "group" and lesson.group_id:
            return await self.repo.student_in_group(lesson.group_id, student_id)
        return lesson.student_id == student_id

    async def _template_teacher_ids(self, user: User) -> list[int]:
        if user.role in ("teacher", "admin"):
            return [user.id]
        if user.role == "student":
            return await self.repo.teacher_ids_for_student(user.id)
        raise BoardServiceError(403, "Нет доступа")

    async def _pick_template(
        self, user: User, template_id: str, lesson_id: Optional[int]
    ) -> Optional[GeogebraTemplate]:
        if user.role in ("teacher", "admin"):
            if lesson_id is not None:
                lesson = await self._teacher_lesson(user, lesson_id)
                return await self.repo.get_template(lesson.teacher_id, template_id)
            return await self.repo.get_template(user.id, template_id)
        if user.role != "student":
            raise BoardServiceError(403, "Нет доступа")
        if lesson_id is not None:
            lesson = await self.repo.get_lesson(lesson_id)
            if lesson is None:
                raise BoardServiceError(404, "Занятие не найдено")
            if not await self._student_in_lesson(user.id, lesson):
                raise BoardServiceError(403, "Нет доступа к этому занятию")
            return await self.repo.get_template(lesson.teacher_id, template_id)
        teacher_ids = await self.repo.teacher_ids_for_student(user.id)
        return await self.repo.first_template(teacher_ids, template_id)

    def _require_student(self, user: User) -> None:
        if user.role != "student":
            raise BoardServiceError(403, "Нужна роль ученика")

    def _require_teacher(self, user: User) -> None:
        if user.role not in ("teacher", "admin"):
            raise BoardServiceError(403, "Нужна роль учителя")


class DbBoardStore:
    """Через него живая комната читает и пишет базу. Каждый вызов — своя короткая сессия."""

    def __init__(self, session_factory: Callable[[], AsyncSession]):
        self._factory = session_factory

    async def load(self, board_id: str) -> Optional[dict]:
        async with self._factory() as db:
            document = await BoardService(db).load_document(uuid.UUID(board_id))
        return document.model_dump(by_alias=True) if document else None

    async def save(self, board_id: str, title: str, camera: dict, objects: list[dict]) -> Optional[int]:
        async with self._factory() as db:
            repo = BoardRepository(db)
            saved = await repo.update_document(
                uuid.UUID(board_id),
                None,
                title=title,
                camera=camera,
                objects=objects,
                object_count=len(objects),
                updated_at=datetime.utcnow(),
            )
            if saved is None:
                return None
            await repo.commit()
            return saved[0]

    async def image_src(self, board_id: str, file_id: uuid.UUID) -> str:
        key = uuid.UUID(board_id)
        async with self._factory() as db:
            repo = BoardRepository(db)
            image = (await repo.images_for_board(key, [file_id])).get(file_id)
            if image is None:
                return ""
            await repo.attach_images(key, [file_id])
            await repo.commit()
            return public_src(image.r2_key)


def _clean_board_title(value: Any) -> str:
    try:
        return scene.clean_board_title(value)
    except scene.SceneError as exc:
        raise BoardServiceError(400, str(exc)) from exc


def _sniff_image(data: bytes) -> Optional[str]:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _clean_template_id(value: str) -> str:
    cleaned = (value or "").strip()
    if TEMPLATE_ID.fullmatch(cleaned) is None:
        raise BoardServiceError(400, "id шаблона: латиница, цифры, дефис, до 64 символов")
    return cleaned


def _clean_title(value: str) -> str:
    cleaned = (value or "").strip()
    if not cleaned or len(cleaned) > 255:
        raise BoardServiceError(400, "Нужно название шаблона короче 256 символов")
    return cleaned


def _clean_app_name(value: str) -> str:
    cleaned = (value or "").strip()
    if cleaned not in APP_NAMES:
        raise BoardServiceError(400, "appName должен быть geometry или graphing")
    return cleaned


def _encode_ggb(data: bytes, filename: str) -> str:
    if filename and not filename.lower().endswith(".ggb"):
        raise BoardServiceError(400, "Нужен файл .ggb")
    if not data:
        raise BoardServiceError(400, "Файл шаблона пустой")
    if len(data) > MAX_GGB_BYTES:
        raise BoardServiceError(400, "Файл шаблона больше 8 МБ")
    return base64.b64encode(data).decode("ascii")
