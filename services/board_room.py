"""Живая доска. Документ открытой доски лежит в памяти процесса, по сети ходят только операции.

Комната живёт, пока подключён хотя бы один участник. В базу она пишет снимок не чаще
раза в FLUSH_SECONDS и обязательно, когда уходит последний участник.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional, Protocol

from services import board_scene as scene

FLUSH_SECONDS = 2.0
OUTBOX_SIZE = 512
MAX_MESSAGE_CHARS = scene.MAX_DOCUMENT_BYTES

CLOSE_UNAUTHORIZED = 4401
CLOSE_FORBIDDEN = 4403
CLOSE_NOT_FOUND = 4404
CLOSE_TOO_SLOW = 4408

META_KEYS = ("id", "title", "teacherId", "groupId", "studentIds", "revision", "createdAt", "updatedAt")

log = logging.getLogger(__name__)


class BoardStore(Protocol):
    async def load(self, board_id: str) -> Optional[dict]: ...

    async def save(self, board_id: str, title: str, camera: dict, objects: list[dict]) -> Optional[int]: ...

    async def image_src(self, board_id: str, file_id: uuid.UUID) -> str: ...


def _encode(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


class RoomClient:
    """Одно подключение. Сообщения копятся в outbox, медленный клиент не тормозит комнату."""

    def __init__(self, user_id: int, name: str, role: str, trusted: bool = False) -> None:
        self.id = uuid.uuid4().hex[:12]
        self.user_id = user_id
        self.name = name
        self.role = role
        # Владелец доски: видит и меняет props.teacherOnly.
        self.trusted = trusted
        self.outbox: asyncio.Queue[Optional[str]] = asyncio.Queue(OUTBOX_SIZE)
        self.close_code: Optional[int] = None

    def peer(self) -> dict[str, Any]:
        return {"clientId": self.id, "userId": self.user_id, "name": self.name, "role": self.role}

    def send(self, text: str, droppable: bool = False) -> None:
        if self.close_code is not None:
            return
        # Курсор устаревает через 50 мс: при отставании клиента его можно пропустить, а не копить.
        if droppable and self.outbox.qsize() >= OUTBOX_SIZE // 2:
            return
        try:
            self.outbox.put_nowait(text)
        except asyncio.QueueFull:
            self.close(CLOSE_TOO_SLOW)

    def close(self, code: int) -> None:
        if self.close_code is not None:
            return
        self.close_code = code
        try:
            self.outbox.put_nowait(None)
        except asyncio.QueueFull:
            while not self.outbox.empty():
                self.outbox.get_nowait()
            self.outbox.put_nowait(None)


@dataclass
class Applied:
    op: dict[str, Any]
    public: bool = True
    object: Optional[dict] = None


class BoardRoom:
    def __init__(self, document: dict, store: BoardStore) -> None:
        self.board_id: str = document["id"]
        self.store = store
        self.meta = {key: document[key] for key in META_KEYS}
        self.camera = dict(document["camera"])
        self.objects: dict[str, dict] = {}
        self.sizes: dict[str, int] = {}
        for obj in document["objects"]:
            self.objects[obj["id"]] = obj
            self.sizes[obj["id"]] = scene.json_size(obj)
        self.total_size = sum(self.sizes.values())
        self.seq = 0
        self.dirty = False
        self.closed = False
        self.clients: dict[str, RoomClient] = {}
        self.lock = asyncio.Lock()
        self._flush_lock = asyncio.Lock()
        self._flush_task: Optional[asyncio.Task] = None
        self._ops = {
            "upsert": self._upsert,
            "patch": self._patch,
            "append_points": self._append_points,
            "delete": self._delete,
            "reorder": self._reorder,
            "title": self._title,
            "camera": self._camera,
        }

    def document(self) -> dict[str, Any]:
        return {**self.meta, "camera": dict(self.camera), "objects": list(self.objects.values())}

    async def join(self, client: RoomClient) -> None:
        async with self.lock:
            if self.closed:
                client.close(CLOSE_NOT_FOUND)
                return
            client.send(self._snapshot(client))
            self._broadcast({"type": "join", "peer": client.peer()})
            self.clients[client.id] = client

    async def leave(self, client: RoomClient) -> bool:
        """True, если в комнате больше никого нет."""
        async with self.lock:
            if self.clients.pop(client.id, None) is not None:
                self._broadcast({"type": "leave", "clientId": client.id})
            return not self.clients

    async def handle(self, client: RoomClient, raw: str) -> None:
        if len(raw) > MAX_MESSAGE_CHARS:
            self._reject(client, None, "Сообщение больше 8 МБ")
            return
        try:
            message = json.loads(raw)
        except ValueError:
            self._reject(client, None, "Сообщение должно быть JSON")
            return
        if not isinstance(message, dict):
            self._reject(client, None, "Сообщение должно быть объектом")
            return
        op_id = message.get("opId")
        if isinstance(op_id, bool) or not isinstance(op_id, (str, int)):
            op_id = None
        kind = message.get("type")
        if kind == "cursor":
            self._cursor(client, message)
            return
        if kind == "sync":
            async with self.lock:
                client.send(self._snapshot(client))
            return
        handler = self._ops.get(kind)
        if handler is None:
            self._reject(client, op_id, f"Неизвестный type: {kind}")
            return
        async with self.lock:
            if self.closed:
                return
            if not client.trusted:
                message = self._guard_private(kind, message)
            try:
                applied = await handler(message)
            except scene.SceneError as exc:
                self._reject(client, op_id, str(exc))
                return
            ack: dict[str, Any] = {"type": "ack", "opId": op_id, "seq": self.seq}
            if applied is not None:
                self.seq += 1
                self.dirty = True
                self.meta["updatedAt"] = scene.iso_time(datetime.utcnow())
                ack["seq"] = self.seq
                if applied.public:
                    self._broadcast(
                        {"type": "op", "seq": self.seq, "clientId": client.id, "op": applied.op},
                        skip=client,
                    )
                if applied.object is not None:
                    ack["object"] = applied.object
                self._schedule_flush()
            client.send(_encode(ack))

    def _guard_private(self, kind: Any, message: dict) -> dict:
        """Ученик не видит props.teacherOnly, поэтому не может ни задать, ни стереть его."""
        private = scene.PRIVATE_PROP
        if kind == "upsert" and isinstance(message.get("object"), dict):
            obj = message["object"]
            props = obj.get("props")
            if not isinstance(props, dict):
                return message
            props = {key: value for key, value in props.items() if key != private}
            current = self.objects.get(obj.get("id")) if isinstance(obj.get("id"), str) else None
            kept = (current or {}).get("props", {}).get(private)
            if kept is not None:
                props[private] = kept
            return {**message, "object": {**obj, "props": props}}
        if kind == "patch" and isinstance(message.get("set"), dict):
            changes = message["set"]
            props = changes.get("props")
            if isinstance(props, dict) and private in props:
                return {**message, "set": {**changes, "props": {k: v for k, v in props.items() if k != private}}}
        return message

    # ── Операции ──────────────────────────────────────────────

    async def _upsert(self, message: dict) -> Applied:
        obj = scene.validate_object(message.get("object"))
        obj, resolved = await self._with_image_src(obj)
        self._put(obj)
        return Applied({"type": "upsert", "object": obj}, object=obj if resolved else None)

    async def _patch(self, message: dict) -> Applied:
        current = self._existing(message.get("id"))
        changes = scene.validate_patch(message.get("set"))
        updated = {**current, **{key: value for key, value in changes.items() if key != "props"}}
        resolved_object = None
        if "props" in changes:
            updated["props"] = {**current["props"], **changes["props"]}
            if "fileId" in changes["props"]:
                updated, resolved = await self._with_image_src(updated)
                if resolved:
                    changes = {**changes, "props": {**changes["props"], "src": updated["props"]["src"]}}
                    resolved_object = updated
            self._put(updated)
        else:
            self._put(updated, size=self.sizes[current["id"]])
        return Applied({"type": "patch", "id": current["id"], "set": changes}, object=resolved_object)

    async def _append_points(self, message: dict) -> Optional[Applied]:
        current = self._existing(message.get("id"))
        if current["type"] != "draw":
            raise scene.SceneError("Точки дописываются только к объекту draw")
        compact = "pts" in message
        points = scene.decode_pts(message.get("pts")) if compact else scene.validate_points(message.get("points"))
        existing = current["props"].get("points")
        if not isinstance(existing, list):
            existing = []
        start = message.get("from")
        if start is not None:
            if isinstance(start, bool) or not isinstance(start, int) or start < 0:
                raise scene.SceneError("from должен быть неотрицательным целым")
            # Повтор после переподключения: уже принятые точки отбрасываются. Дыру не заполнить, ждём полный штрих.
            if start > len(existing):
                return None
            points = points[len(existing) - start:]
            if not points:
                return None
        updated = {**current, "props": {**current["props"], "points": existing + points}}
        self._put(updated, size=self.sizes[current["id"]] + scene.json_size(points))
        if not compact:
            return Applied({"type": "append_points", "id": current["id"], "points": points})
        return Applied({"type": "append_points", "id": current["id"], "from": len(existing), "pts": scene.encode_pts(points)})

    async def _delete(self, message: dict) -> Optional[Applied]:
        ids = message.get("ids")
        if not isinstance(ids, list) or not all(isinstance(item, str) for item in ids):
            raise scene.SceneError("ids должен быть массивом строк")
        removed: list[str] = []
        for object_id in ids:
            if self.objects.pop(object_id, None) is not None:
                self.total_size -= self.sizes.pop(object_id)
                removed.append(object_id)
        if not removed:
            return None
        return Applied({"type": "delete", "ids": removed})

    async def _reorder(self, message: dict) -> Optional[Applied]:
        ids = message.get("ids")
        if (
            not isinstance(ids, list)
            or len(ids) != len(self.objects)
            or len(set(ids)) != len(ids)
            or set(ids) != set(self.objects)
        ):
            raise scene.SceneError("ids должен перечислять все объекты доски ровно по разу")
        if ids == list(self.objects):
            return None
        self.objects = {object_id: self.objects[object_id] for object_id in ids}
        return Applied({"type": "reorder", "ids": ids})

    async def _title(self, message: dict) -> Optional[Applied]:
        title = scene.clean_board_title(message.get("title"))
        if title == self.meta["title"]:
            return None
        self.meta["title"] = title
        return Applied({"type": "title", "title": title})

    async def _camera(self, message: dict) -> Applied:
        self.camera = scene.validate_camera(message.get("camera"))
        return Applied({"type": "camera", "camera": self.camera}, public=False)

    def _existing(self, object_id: Any) -> dict:
        if not isinstance(object_id, str) or object_id not in self.objects:
            raise scene.SceneError(f"Нет объекта {object_id}")
        return self.objects[object_id]

    def _put(self, obj: dict, size: Optional[int] = None) -> None:
        size = scene.json_size(obj) if size is None else size
        previous = self.sizes.get(obj["id"])
        if previous is None and len(self.objects) >= scene.MAX_OBJECTS:
            raise scene.SceneError(f"На доске не больше {scene.MAX_OBJECTS} объектов")
        total = self.total_size - (previous or 0) + size
        if total > scene.MAX_DOCUMENT_BYTES:
            raise scene.SceneError("Документ больше 8 МБ")
        self.objects[obj["id"]] = obj
        self.sizes[obj["id"]] = size
        self.total_size = total

    async def _with_image_src(self, obj: dict) -> tuple[dict, bool]:
        if obj["type"] != "image":
            return obj, False
        file_id = scene.image_file_id(obj)
        src = await self.store.image_src(self.board_id, file_id) if file_id else ""
        return {**obj, "props": {**obj["props"], "src": src}}, True

    # ── Рассылка ──────────────────────────────────────────────

    def _cursor(self, client: RoomClient, message: dict) -> None:
        if client.id not in self.clients:
            return
        try:
            x = scene.finite(message.get("x"), "x")
            y = scene.finite(message.get("y"), "y")
        except scene.SceneError:
            return
        self._broadcast({"type": "cursor", "clientId": client.id, "x": x, "y": y}, skip=client, droppable=True)

    def _snapshot(self, client: RoomClient) -> str:
        board = self.document()
        if not client.trusted:
            board["objects"] = [scene.public_object(obj) for obj in board["objects"]]
        return _encode({
            "type": "snapshot",
            "seq": self.seq,
            "clientId": client.id,
            "board": board,
            "peers": [other.peer() for other in self.clients.values() if other is not client],
        })

    def _reject(self, client: RoomClient, op_id: Any, detail: str) -> None:
        client.send(_encode({"type": "error", "opId": op_id, "detail": detail}))

    def _broadcast(self, payload: dict[str, Any], skip: Optional[RoomClient] = None, droppable: bool = False) -> None:
        text = _encode(payload)
        public_text = text
        op = payload.get("op")
        if payload.get("type") == "op" and isinstance(op, dict) and scene.has_private(op):
            public_text = _encode({**payload, "op": scene.public_op(op)})
        for client in list(self.clients.values()):
            if client is not skip:
                client.send(text if client.trusted else public_text, droppable=droppable)

    # ── Сохранение ────────────────────────────────────────────

    def _schedule_flush(self) -> None:
        if self._flush_task is None or self._flush_task.done():
            self._flush_task = asyncio.create_task(self._flush_later())

    async def _flush_later(self) -> None:
        await asyncio.sleep(FLUSH_SECONDS)
        await self.flush()

    async def flush(self) -> None:
        async with self._flush_lock:
            if not self.dirty or self.closed:
                return
            self.dirty = False
            title = self.meta["title"]
            camera = dict(self.camera)
            objects = list(self.objects.values())
            try:
                revision = await self.store.save(self.board_id, title, camera, objects)
            except asyncio.CancelledError:
                self.dirty = True
                raise
            except Exception:
                self.dirty = True
                log.exception("Не удалось сохранить доску %s", self.board_id)
                return
            if revision is None:
                self.shutdown(CLOSE_NOT_FOUND, {"type": "deleted", "id": self.board_id})
                return
            self.meta["revision"] = revision

    async def finish(self) -> None:
        """Последний участник ушёл: дописать снимок и закрыть комнату."""
        task = self._flush_task
        if task is not None and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        await self.flush()
        self.closed = True

    def shutdown(self, code: int, payload: Optional[dict[str, Any]] = None) -> None:
        self.closed = True
        task = self._flush_task
        if task is not None and not task.done() and task is not asyncio.current_task():
            task.cancel()
        if payload is not None:
            self._broadcast(payload)
        for client in list(self.clients.values()):
            client.close(code)


class BoardRooms:
    def __init__(self) -> None:
        self._rooms: dict[str, BoardRoom] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock(self, board_id: str) -> asyncio.Lock:
        return self._locks.setdefault(board_id, asyncio.Lock())

    def live_document(self, board_id: str) -> Optional[dict[str, Any]]:
        room = self._rooms.get(board_id)
        if room is None or room.closed:
            return None
        return room.document()

    async def join(self, board_id: str, client: RoomClient, store: BoardStore) -> Optional[BoardRoom]:
        async with self._lock(board_id):
            room = self._rooms.get(board_id)
            if room is None or room.closed:
                document = await store.load(board_id)
                if document is None:
                    return None
                room = BoardRoom(document, store)
                self._rooms[board_id] = room
            await room.join(client)
            return room

    async def leave(self, room: BoardRoom, client: RoomClient) -> None:
        async with self._lock(room.board_id):
            if not await room.leave(client):
                return
            if not room.closed:
                await room.finish()
            if self._rooms.get(room.board_id) is room:
                del self._rooms[room.board_id]

    async def close_board(self, board_id: str) -> None:
        async with self._lock(board_id):
            room = self._rooms.pop(board_id, None)
        if room is not None:
            room.shutdown(CLOSE_NOT_FOUND, {"type": "deleted", "id": board_id})

    async def flush_all(self) -> None:
        for room in list(self._rooms.values()):
            await room.flush()


board_rooms = BoardRooms()
