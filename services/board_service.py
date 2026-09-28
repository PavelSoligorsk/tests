"""Документ доски целиком: ревизия, картинки и шаблоны."""
from __future__ import annotations

import asyncio
import base64
import math
import re
import uuid
from datetime import datetime
from typing import Any, Optional

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
from services.board_events import board_events
from services.board_files import delete_keys, public_src, put_bytes

OBJECT_TYPES = {"sticky", "text", "shape", "arrow", "draw", "image", "geogebra"}
MAX_OBJECTS = 200
MAX_DOCUMENT_BYTES = 8 * 1024 * 1024
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
        self._require_student(student)
        board = await self._board_or_404(board_id)
        if not await self._student_can_access(student.id, board):
            raise BoardServiceError(403, "Нет доступа к этой доске")
        return await self._document(board)

    async def put_for_student(self, student: User, board_id: uuid.UUID, body: dict) -> BoardDocument:
        self._require_student(student)
        board = await self._board_or_404(board_id)
        if not await self._student_can_access(student.id, board):
            raise BoardServiceError(403, "Нет доступа к этой доске")
        return await self._save(board, body)

    async def open_student_events(
        self, student: User, board_id: uuid.UUID
    ) -> tuple[asyncio.Queue, dict[str, Any]]:
        self._require_student(student)

        async def allowed(board: Board) -> bool:
            return await self._student_can_access(student.id, board)

        return await self._open_events(board_id, allowed)

    async def open_teacher_events(
        self, teacher: User, board_id: uuid.UUID
    ) -> tuple[asyncio.Queue, dict[str, Any]]:
        self._require_teacher(teacher)

        async def allowed(board: Board) -> bool:
            return board.teacher_id == teacher.id

        return await self._open_events(board_id, allowed)

    async def _open_events(self, board_id: uuid.UUID, allowed) -> tuple[asyncio.Queue, dict[str, Any]]:
        key = str(board_id)
        queue = board_events.subscribe(key)
        try:
            board = await self._board_or_404(board_id)
            if not await allowed(board):
                raise BoardServiceError(403, "Нет доступа к этой доске")
            return queue, {
                "id": key,
                "revision": board.revision,
                "updatedAt": _iso(board.updated_at),
            }
        except Exception:
            board_events.unsubscribe(key, queue)
            raise

    async def get_for_teacher(self, teacher: User, board_id: uuid.UUID) -> BoardDocument:
        self._require_teacher(teacher)
        board = await self._owned_board(teacher, board_id)
        return await self._document(board)

    async def put_for_teacher(self, teacher: User, board_id: uuid.UUID, body: dict) -> BoardDocument:
        self._require_teacher(teacher)
        board = await self._owned_board(teacher, board_id)
        return await self._save(board, body)

    async def delete_for_teacher(self, teacher: User, board_id: uuid.UUID) -> None:
        self._require_teacher(teacher)
        board = await self._owned_board(teacher, board_id)
        board_key = str(board.id)
        await self._delete_board(board)
        await self.repo.commit()
        board_events.publish(board_key, {"event": "delete", "id": board_key})

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

    async def _save(self, board: Board, body: dict) -> BoardDocument:
        client_revision = body.get("revision")
        if not isinstance(client_revision, int) or isinstance(client_revision, bool):
            raise BoardServiceError(400, "Нужна целочисленная revision")
        if client_revision != board.revision:
            raise BoardServiceError(409, (await self._document(board)).model_dump(by_alias=True))

        title = body.get("title", board.title)
        camera, objects = _validate_scene(body.get("camera"), body.get("objects"))
        await self._fill_templates(objects, board.teacher_id)
        _reject_huge(camera, objects)
        board.title = _clean_board_title(title)
        board.camera = camera
        board.objects = objects
        board.revision = board.revision + 1
        board.updated_at = datetime.utcnow()
        await self.repo.attach_images(board.id, _image_ids(objects))
        await self.repo.commit()
        document = await self._document(board)
        board_events.publish(str(board.id), {
            "event": "update",
            "id": str(board.id),
            "revision": document.revision,
            "updatedAt": document.updated_at,
        })
        return document

    async def _fill_templates(self, objects: list[dict], teacher_id: int) -> None:
        for obj in objects:
            if obj.get("type") != "geogebra":
                continue
            props = obj.get("props") or {}
            template_id = props.get("templateId")
            if not isinstance(template_id, str) or not template_id.strip():
                continue
            current = props.get("ggbBase64")
            if isinstance(current, str) and current.strip():
                continue
            row = await self.repo.get_template(teacher_id, template_id.strip())
            if row is not None:
                props["ggbBase64"] = row.ggb_base64
                obj["props"] = props

    async def _delete_board(self, board: Board) -> None:
        keys = await self.repo.image_keys(board.id)
        await delete_keys(keys)
        await self.repo.delete_board(board)

    async def _document(self, board: Board) -> BoardDocument:
        objects = [dict(obj) for obj in (board.objects or [])]
        file_ids = _image_ids(objects)
        images = await self.repo.images_by_ids(file_ids)
        for obj in objects:
            if obj.get("type") != "image":
                continue
            props = dict(obj.get("props") or {})
            parsed = _parse_uuid(props.get("fileId"))
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
            created_at=_iso(board.created_at),
            updated_at=_iso(board.updated_at),
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
            updated_at=_iso(board.updated_at),
            object_count=len(board.objects or []),
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

    async def _student_can_access(self, student_id: int, board: Board) -> bool:
        if board.group_id is not None:
            return await self.repo.student_in_group(board.group_id, student_id)
        return student_id in await self._member_ids(board.id)

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


def _clean_board_title(value: Any) -> str:
    if not isinstance(value, str):
        raise BoardServiceError(400, "Нужно название")
    cleaned = value.strip()
    if not cleaned:
        raise BoardServiceError(400, "Нужно название")
    if len(cleaned) > 255:
        raise BoardServiceError(400, "Название длиннее 255 символов")
    return cleaned


def _iso(value: Optional[datetime]) -> str:
    moment = value or datetime.utcnow()
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def _finite(value: Any, label: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise BoardServiceError(400, f"Поле {label} должно быть конечным числом")
    return value


def _validate_scene(camera: Any, objects: Any) -> tuple[dict, list]:
    if not isinstance(camera, dict):
        raise BoardServiceError(400, "camera должен быть объектом")
    clean_camera = {
        "x": _finite(camera.get("x"), "camera.x"),
        "y": _finite(camera.get("y"), "camera.y"),
        "zoom": _finite(camera.get("zoom"), "camera.zoom"),
    }
    if not isinstance(objects, list):
        raise BoardServiceError(400, "objects должен быть массивом")
    if len(objects) > MAX_OBJECTS:
        raise BoardServiceError(400, "На доске не больше 200 объектов")
    clean_objects: list[dict] = []
    for index, raw in enumerate(objects):
        if not isinstance(raw, dict):
            raise BoardServiceError(400, f"Объект {index} должен быть объектом")
        object_id = raw.get("id")
        object_type = raw.get("type")
        if not isinstance(object_id, str) or not object_id:
            raise BoardServiceError(400, f"У объекта {index} нужен строковый id")
        if object_type not in OBJECT_TYPES:
            raise BoardServiceError(400, f"Неизвестный type у объекта {index}")
        props = raw.get("props", {})
        if not isinstance(props, dict):
            raise BoardServiceError(400, f"props объекта {index} должен быть объектом")
        _assert_finite_tree(props, f"objects[{index}].props")
        clean_objects.append({
            "id": object_id,
            "type": object_type,
            "x": _finite(raw.get("x"), f"objects[{index}].x"),
            "y": _finite(raw.get("y"), f"objects[{index}].y"),
            "w": _finite(raw.get("w"), f"objects[{index}].w"),
            "h": _finite(raw.get("h"), f"objects[{index}].h"),
            "rotation": _finite(raw.get("rotation"), f"objects[{index}].rotation"),
            "props": props,
        })
    return clean_camera, clean_objects


def _assert_finite_tree(value: Any, label: str) -> None:
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        if not math.isfinite(float(value)):
            raise BoardServiceError(400, f"Поле {label} должно быть конечным числом")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            _assert_finite_tree(item, f"{label}.{key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _assert_finite_tree(item, f"{label}[{index}]")


def _reject_huge(camera: dict, objects: list) -> None:
    import json
    raw = json.dumps({"camera": camera, "objects": objects}, ensure_ascii=False).encode("utf-8")
    if len(raw) > MAX_DOCUMENT_BYTES:
        raise BoardServiceError(400, "Документ больше 8 МБ")


def _image_ids(objects: list[dict]) -> list[uuid.UUID]:
    found: list[uuid.UUID] = []
    for obj in objects:
        if obj.get("type") != "image":
            continue
        parsed = _parse_uuid((obj.get("props") or {}).get("fileId"))
        if parsed is not None:
            found.append(parsed)
    return found


def _parse_uuid(value: Any) -> Optional[uuid.UUID]:
    if not isinstance(value, str) or not value:
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


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
