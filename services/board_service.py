"""Документ доски целиком: ревизия, две доски занятия, картинки и шаблоны."""
from __future__ import annotations

import base64
import math
import re
import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import Board, BoardImage, GeogebraTemplate, Lesson, User
from dto_schemas.board import (
    BoardDocument,
    BoardImageUpload,
    BoardMeta,
    Camera,
    GeogebraTemplateDocument,
    GeogebraTemplateMeta,
    StudentLessonBoards,
    TeacherLessonBoards,
)
from repositories.board_repository import BoardRepository, new_board
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
        return [self._meta(board) for board in boards]

    async def create_draft(self, student: User, title: str) -> BoardDocument:
        self._require_student(student)
        clean = (title or "").strip()
        if not clean:
            raise BoardServiceError(400, "Нужно название черновика")
        if len(clean) > 255:
            raise BoardServiceError(400, "Название длиннее 255 символов")
        board = new_board(title=clean, kind="draft", lesson_id=None, owner_id=student.id)
        self.repo.add_board(board)
        await self.repo.commit()
        return await self._document(board)

    async def get_for_student(self, student: User, board_id: uuid.UUID) -> BoardDocument:
        self._require_student(student)
        board = await self._board_or_404(board_id)
        lesson = await self._lesson_of(board)
        if not await self._student_can_read(student.id, board, lesson):
            raise BoardServiceError(403, "Нет доступа к этой доске")
        return await self._document(board)

    async def put_for_student(self, student: User, board_id: uuid.UUID, body: dict) -> BoardDocument:
        self._require_student(student)
        board = await self._board_or_404(board_id)
        lesson = await self._lesson_of(board)
        if not await self._student_can_read(student.id, board, lesson):
            raise BoardServiceError(403, "Нет доступа к этой доске")
        if board.kind not in ("student", "draft") or board.owner_id != student.id:
            raise BoardServiceError(403, "Эту доску можно только читать")
        return await self._save(board, lesson, body, student_id=student.id)

    async def delete_draft(self, student: User, board_id: uuid.UUID) -> None:
        self._require_student(student)
        board = await self._board_or_404(board_id)
        if board.kind != "draft" or board.owner_id != student.id:
            raise BoardServiceError(403, "Удалить можно только свой черновик")
        await self._delete_board(board)
        await self.repo.commit()

    async def open_student_lesson(self, student: User, lesson_id: int) -> StudentLessonBoards:
        self._require_student(student)
        lesson = await self.repo.get_lesson(lesson_id)
        if lesson is None:
            raise BoardServiceError(404, "Занятие не найдено")
        if not await self._student_in_lesson(student.id, lesson):
            raise BoardServiceError(403, "Нет доступа к этому занятию")
        lesson_id = lesson.id
        await self._ensure(lesson)
        boards = await self.repo.list_for_lesson(lesson_id)
        class_board = next((b for b in boards if b.kind == "class"), None)
        mine = next((b for b in boards if b.kind == "student" and b.owner_id == student.id), None)
        if class_board is None or mine is None:
            raise BoardServiceError(404, "Доска занятия не найдена")
        return StudentLessonBoards(
            class_board=await self._document(class_board),
            mine=await self._document(mine),
        )

    async def open_teacher_lesson(self, teacher: User, lesson_id: int) -> TeacherLessonBoards:
        self._require_teacher(teacher)
        lesson = await self._teacher_lesson(teacher, lesson_id)
        await self._ensure(lesson)
        boards = await self.repo.list_for_lesson(lesson_id)
        class_board = next((b for b in boards if b.kind == "class"), None)
        if class_board is None:
            raise BoardServiceError(404, "Доска занятия не найдена")
        notebooks = [self._meta(b) for b in boards if b.kind == "student"]
        notebooks.sort(key=lambda item: item.owner_id or 0)
        return TeacherLessonBoards(
            class_board=await self._document(class_board),
            notebooks=notebooks,
        )

    async def get_for_teacher(self, teacher: User, board_id: uuid.UUID) -> BoardDocument:
        self._require_teacher(teacher)
        board = await self._board_or_404(board_id)
        lesson = await self._lesson_of(board)
        if lesson is None or lesson.teacher_id != teacher.id:
            raise BoardServiceError(403, "Нет доступа к этой доске")
        return await self._document(board)

    async def put_for_teacher(self, teacher: User, board_id: uuid.UUID, body: dict) -> BoardDocument:
        self._require_teacher(teacher)
        board = await self._board_or_404(board_id)
        lesson = await self._lesson_of(board)
        if lesson is None or lesson.teacher_id != teacher.id:
            raise BoardServiceError(403, "Нет доступа к этой доске")
        if board.kind != "class":
            raise BoardServiceError(403, "Тетрадь ученика учитель не перезаписывает")
        return await self._save(board, lesson, body, student_id=None)

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

    async def _save(
        self, board: Board, lesson: Optional[Lesson], body: dict, *, student_id: Optional[int]
    ) -> BoardDocument:
        client_revision = body.get("revision")
        if not isinstance(client_revision, int) or isinstance(client_revision, bool):
            raise BoardServiceError(400, "Нужна целочисленная revision")
        if client_revision != board.revision:
            raise BoardServiceError(409, (await self._document(board)).model_dump(by_alias=True))

        title = body.get("title", board.title)
        if not isinstance(title, str) or not title.strip():
            raise BoardServiceError(400, "Нужно название")
        title = title.strip()
        if len(title) > 255:
            raise BoardServiceError(400, "Название длиннее 255 символов")

        camera, objects = _validate_scene(body.get("camera"), body.get("objects"))
        await self._fill_templates(objects, lesson, student_id if board.kind == "draft" else None)
        _reject_huge(camera, objects)

        board.title = title
        board.camera = camera
        board.objects = objects
        board.revision = board.revision + 1
        board.updated_at = datetime.utcnow()
        await self.repo.attach_images(board.id, _image_ids(objects))
        await self.repo.commit()
        return await self._document(board)

    async def _fill_templates(
        self, objects: list[dict], lesson: Optional[Lesson], draft_owner_id: Optional[int]
    ) -> None:
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
            row = await self._template_for_board(template_id.strip(), lesson, draft_owner_id)
            if row is not None:
                props["ggbBase64"] = row.ggb_base64
                obj["props"] = props

    async def _template_for_board(
        self, template_id: str, lesson: Optional[Lesson], draft_owner_id: Optional[int]
    ) -> Optional[GeogebraTemplate]:
        if lesson is not None:
            return await self.repo.get_template(lesson.teacher_id, template_id)
        if draft_owner_id is None:
            return None
        teacher_ids = await self.repo.teacher_ids_for_student(draft_owner_id)
        return await self.repo.first_template(teacher_ids, template_id)

    async def _ensure(self, lesson: Lesson) -> None:
        await self._create_missing(lesson)
        try:
            await self.repo.commit()
        except IntegrityError:
            await self.repo.rollback()

    async def _create_missing(self, lesson: Lesson) -> None:
        existing = await self.repo.list_for_lesson(lesson.id)
        if not any(board.kind == "class" for board in existing):
            self.repo.add_board(new_board(
                title=lesson.title, kind="class", lesson_id=lesson.id, owner_id=None,
            ))
        owners = {board.owner_id for board in existing if board.kind == "student"}
        if lesson.lesson_type == "group" and lesson.group_id:
            student_ids = await self.repo.group_student_ids(lesson.group_id)
        elif lesson.student_id:
            student_ids = [lesson.student_id]
        else:
            student_ids = []
        for student_id in student_ids:
            if student_id not in owners:
                self.repo.add_board(new_board(
                    title=lesson.title, kind="student", lesson_id=lesson.id, owner_id=student_id,
                ))

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
        return BoardDocument(
            id=str(board.id),
            title=board.title,
            lesson_id=board.lesson_id,
            kind=board.kind,
            owner_id=board.owner_id,
            revision=board.revision,
            created_at=_iso(board.created_at),
            updated_at=_iso(board.updated_at),
            camera=Camera(x=camera["x"], y=camera["y"], zoom=camera["zoom"]),
            objects=objects,
        )

    def _meta(self, board: Board) -> BoardMeta:
        return BoardMeta(
            id=str(board.id),
            title=board.title,
            lesson_id=board.lesson_id,
            kind=board.kind,
            owner_id=board.owner_id,
            updated_at=_iso(board.updated_at),
            object_count=len(board.objects or []),
        )

    async def _board_or_404(self, board_id: uuid.UUID) -> Board:
        board = await self.repo.get_board(board_id)
        if board is None:
            raise BoardServiceError(404, "Доска не найдена")
        return board

    async def _lesson_of(self, board: Board) -> Optional[Lesson]:
        if board.lesson_id is None:
            return None
        return await self.repo.get_lesson(board.lesson_id)

    async def _teacher_lesson(self, teacher: User, lesson_id: int) -> Lesson:
        lesson = await self.repo.get_lesson(lesson_id)
        if lesson is None or lesson.teacher_id != teacher.id:
            raise BoardServiceError(404, "Занятие не найдено")
        return lesson

    async def _student_in_lesson(self, student_id: int, lesson: Lesson) -> bool:
        if lesson.lesson_type == "group" and lesson.group_id:
            return await self.repo.student_in_group(lesson.group_id, student_id)
        return lesson.student_id == student_id

    async def _student_can_read(self, student_id: int, board: Board, lesson: Optional[Lesson]) -> bool:
        if board.kind in ("draft", "student"):
            return board.owner_id == student_id
        if board.kind == "class" and lesson is not None:
            return await self._student_in_lesson(student_id, lesson)
        return False

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


async def purge_lesson_boards(db: AsyncSession, lesson_id: int) -> None:
    """Стереть холсты занятия и их файлы в R2. Вызывается до удаления урока."""
    repo = BoardRepository(db)
    boards = await repo.list_for_lesson(lesson_id)
    for board in boards:
        keys = await repo.image_keys(board.id)
        await delete_keys(keys)
        await repo.delete_board(board)
    if boards:
        await repo.flush()


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
