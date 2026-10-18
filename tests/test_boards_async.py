"""Именная доска учителя: ученики или группа, без расписания."""
from __future__ import annotations

import asyncio
import base64
import json
from datetime import datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from repositories.board_repository import BoardRepository, new_board
from tests.helpers_async import _bearer

MINI_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


class _FakeS3:
    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}
        self.deleted: list[str] = []

    def put_object(self, **kwargs) -> None:
        self.store[kwargs["Key"]] = kwargs["Body"]

    def delete_object(self, **kwargs) -> None:
        self.deleted.append(kwargs["Key"])
        self.store.pop(kwargs["Key"], None)


@pytest.fixture
def r2(monkeypatch: pytest.MonkeyPatch) -> _FakeS3:
    fake = _FakeS3()
    monkeypatch.setattr("services.board_files.client", lambda: fake)
    return fake


def _sticky(object_id: str = "s1") -> dict:
    return {
        "id": object_id,
        "type": "sticky",
        "x": 10, "y": 20, "w": 200, "h": 160, "rotation": 0,
        "props": {"text": "привет", "color": "#fde68a"},
    }


def _put_body(board: dict, objects: list | None = None, revision: int | None = None) -> dict:
    return {
        "id": board["id"],
        "title": board["title"],
        "teacherId": board["teacherId"],
        "groupId": board["groupId"],
        "studentIds": board["studentIds"],
        "revision": board["revision"] if revision is None else revision,
        "createdAt": board["createdAt"],
        "updatedAt": board["updatedAt"],
        "camera": board["camera"],
        "objects": board["objects"] if objects is None else objects,
    }


async def _link(ac: AsyncClient, admin_token: str, teacher_token: str, student_token: str) -> tuple[int, int]:
    users = (await ac.get("/admin/users", headers=_bearer(admin_token))).json()
    teacher_id = next(user["id"] for user in users if user["role"] == "teacher")
    student_id = (await ac.get("/student/me", headers=_bearer(student_token))).json()["user"]["id"]
    link = await ac.post(
        "/admin/assign-student-to-teacher",
        json={"teacher_id": teacher_id, "student_id": student_id},
        headers=_bearer(admin_token),
    )
    assert link.status_code == 200, link.text
    return teacher_id, student_id


@pytest.mark.asyncio
async def test_teacher_names_a_board_for_students(
    async_client: AsyncClient, teacher_token: str, student_token: str, student2_token: str, admin_token: str
) -> None:
    teacher_id, student_id = await _link(async_client, admin_token, teacher_token, student_token)
    student2_id = (await async_client.get("/student/me", headers=_bearer(student2_token))).json()["user"]["id"]
    linked = await async_client.post(
        "/admin/assign-student-to-teacher",
        json={"teacher_id": teacher_id, "student_id": student2_id},
        headers=_bearer(admin_token),
    )
    assert linked.status_code == 200, linked.text

    created = await async_client.post(
        "/teacher/boards",
        json={"title": "Дроби", "studentIds": [student_id, student2_id]},
        headers=_bearer(teacher_token),
    )
    assert created.status_code == 200, created.text
    board = created.json()
    assert board["title"] == "Дроби"
    assert board["teacherId"] == teacher_id
    assert board["groupId"] is None
    assert board["studentIds"] == [student_id, student2_id]
    assert "lessonId" not in board
    assert board["revision"] == 1
    assert board["objects"] == []

    listed = await async_client.get("/student/boards", headers=_bearer(student_token))
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == board["id"]
    assert listed.json()[0]["objectCount"] == 0
    assert "objects" not in listed.json()[0]

    stranger = await async_client.post(
        "/admin/assign-student-to-teacher",
        json={"teacher_id": teacher_id, "student_id": student2_id},
        headers=_bearer(admin_token),
    )
    assert stranger.status_code == 200
    # Второй ученик всё ещё в studentIds, он видит ту же доску.
    same = await async_client.get(f"/student/boards/{board['id']}", headers=_bearer(student2_token))
    assert same.status_code == 200
    assert same.json()["id"] == board["id"]

    saved = await async_client.put(
        f"/student/boards/{board['id']}",
        json=_put_body(board, [_sticky()]),
        headers=_bearer(student_token),
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["revision"] == 2

    teacher_saved = await async_client.put(
        f"/teacher/boards/{board['id']}",
        json=_put_body(saved.json(), [_sticky("t1")]),
        headers=_bearer(teacher_token),
    )
    assert teacher_saved.status_code == 200, teacher_saved.text
    assert teacher_saved.json()["objects"][0]["id"] == "t1"

    listed_after = await async_client.get("/teacher/boards", headers=_bearer(teacher_token))
    assert listed_after.status_code == 200
    saved_meta = next(item for item in listed_after.json() if item["id"] == board["id"])
    assert saved_meta["objectCount"] == 1
    assert "objects" not in saved_meta

    stale = await async_client.put(
        f"/student/boards/{board['id']}",
        json=_put_body(board, [_sticky("old")], revision=1),
        headers=_bearer(student_token),
    )
    assert stale.status_code == 409
    assert stale.json()["revision"] == 3

    neither = await async_client.post(
        "/teacher/boards", json={"title": "Пусто"}, headers=_bearer(teacher_token)
    )
    assert neither.status_code == 400
    both = await async_client.post(
        "/teacher/boards",
        json={"title": "И то и то", "studentIds": [student_id], "groupId": 1},
        headers=_bearer(teacher_token),
    )
    assert both.status_code == 400


@pytest.mark.asyncio
async def test_group_board_is_one_canvas(
    async_client: AsyncClient, teacher_token: str, student_token: str, student2_token: str, admin_token: str
) -> None:
    teacher_id, student_id = await _link(async_client, admin_token, teacher_token, student_token)
    student2_id = (await async_client.get("/student/me", headers=_bearer(student2_token))).json()["user"]["id"]
    # assign заменяет учителя, поэтому второго ученика привязываем до группы и не трогаем первого повторно.
    # Оба должны быть у этого учителя. create_link удаляет прежнюю связь ученика, не учителя.
    await async_client.post(
        "/admin/assign-student-to-teacher",
        json={"teacher_id": teacher_id, "student_id": student2_id},
        headers=_bearer(admin_token),
    )
    await async_client.post(
        "/admin/assign-student-to-teacher",
        json={"teacher_id": teacher_id, "student_id": student_id},
        headers=_bearer(admin_token),
    )
    group = await async_client.post(
        "/teacher/groups/",
        json={"name": "Группа", "description": ""},
        headers=_bearer(teacher_token),
    )
    assert group.status_code == 200, group.text
    group_id = group.json()["id"]
    added = await async_client.post(
        f"/teacher/groups/{group_id}/students",
        json={"student_ids": [student_id, student2_id]},
        headers=_bearer(teacher_token),
    )
    assert added.status_code == 200, added.text

    created = await async_client.post(
        "/teacher/boards",
        json={"title": "Групповая доска", "groupId": group_id},
        headers=_bearer(teacher_token),
    )
    assert created.status_code == 200, created.text
    board = created.json()
    assert board["groupId"] == group_id
    assert board["studentIds"] == []

    first = await async_client.get("/student/boards", headers=_bearer(student_token))
    second = await async_client.get("/student/boards", headers=_bearer(student2_token))
    assert first.json()[0]["id"] == board["id"]
    assert second.json()[0]["id"] == board["id"]


@pytest.mark.asyncio
async def test_delete_board_removes_images(
    async_client: AsyncClient, teacher_token: str, student_token: str, admin_token: str, r2: _FakeS3
) -> None:
    _, student_id = await _link(async_client, admin_token, teacher_token, student_token)
    created = await async_client.post(
        "/teacher/boards",
        json={"title": "С картинкой", "studentIds": [student_id]},
        headers=_bearer(teacher_token),
    )
    board = created.json()
    uploaded = await async_client.post(
        "/teacher/boards/images",
        files={"file": ("a.png", MINI_PNG, "image/png")},
        headers=_bearer(teacher_token),
    )
    assert uploaded.status_code == 200, uploaded.text
    image = {
        "id": "img1", "type": "image", "x": 0, "y": 0, "w": 10, "h": 10, "rotation": 0,
        "props": {"fileId": uploaded.json()["fileId"], "src": "", "name": "a.png"},
    }
    saved = await async_client.put(
        f"/teacher/boards/{board['id']}",
        json=_put_body(board, [image]),
        headers=_bearer(teacher_token),
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["objects"][0]["props"]["src"].endswith(".png")

    deleted = await async_client.delete(f"/teacher/boards/{board['id']}", headers=_bearer(teacher_token))
    assert deleted.status_code == 200, deleted.text
    assert r2.store == {}
    missing = await async_client.get(f"/student/boards/{board['id']}", headers=_bearer(student_token))
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_template_stays_out_of_the_board_document(
    async_client: AsyncClient, teacher_token: str, student_token: str, admin_token: str
) -> None:
    teacher_id, student_id = await _link(async_client, admin_token, teacher_token, student_token)
    uploaded = await async_client.post(
        "/teacher/geogebra-templates",
        data={"id": "circle", "title": "Окружность", "appName": "geometry"},
        files={"file": ("circle.ggb", b"AAA", "application/octet-stream")},
        headers=_bearer(teacher_token),
    )
    assert uploaded.status_code == 200, uploaded.text
    created = await async_client.post(
        "/teacher/boards",
        json={"title": "Чертёж", "studentIds": [student_id]},
        headers=_bearer(teacher_token),
    )
    board = created.json()
    ggb = {
        "id": "g1", "type": "geogebra", "x": 0, "y": 0, "w": 10, "h": 10, "rotation": 0,
        "props": {"appName": "geometry", "ggbBase64": "", "templateId": "circle", "custom": True},
    }
    saved = await async_client.put(
        f"/student/boards/{board['id']}",
        json=_put_body(board, [ggb]),
        headers=_bearer(student_token),
    )
    assert saved.status_code == 200, saved.text
    props = saved.json()["objects"][0]["props"]
    assert props["ggbBase64"] == ""
    assert props["templateId"] == "circle"
    assert props["custom"] is True
    assert saved.json()["teacherId"] == teacher_id

    catalog = await async_client.get("/board/geogebra-templates", headers=_bearer(student_token))
    assert catalog.status_code == 200, catalog.text
    assert catalog.json()[0]["id"] == "circle"
    assert "ggbBase64" not in catalog.json()[0]

    fetched = await async_client.get(
        "/board/geogebra-templates/circle", headers=_bearer(student_token)
    )
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["ggbBase64"] == base64.b64encode(b"AAA").decode("ascii")


@pytest.mark.asyncio
async def test_document_update_matches_revision(db: AsyncSession, teacher_user: dict) -> None:
    board = new_board(title="Гонка", teacher_id=teacher_user["id"], group_id=None)
    repo = BoardRepository(db)
    repo.add_board(board)
    await repo.commit()

    camera = {"x": 0, "y": 0, "zoom": 1}
    first = await repo.update_document(
        board.id,
        1,
        title="Гонка",
        camera=camera,
        objects=[_sticky()],
        object_count=1,
        updated_at=datetime.utcnow(),
    )
    assert first is not None
    assert first[0] == 2
    await repo.commit()

    stale = await repo.update_document(
        board.id,
        1,
        title="Старое",
        camera=camera,
        objects=[],
        object_count=0,
        updated_at=datetime.utcnow(),
    )
    assert stale is None

    fresh = await repo.get_board(board.id, refresh=True)
    assert fresh is not None
    assert fresh.revision == 2
    assert fresh.object_count == 1
    assert fresh.objects[0]["id"] == "s1"


def _take_sse(buffer: str) -> tuple[str, dict, str] | None:
    if "\n\n" not in buffer:
        return None
    chunk, rest = buffer.split("\n\n", 1)
    if chunk.startswith(":"):
        return _take_sse(rest)
    event = "message"
    data = None
    for line in chunk.split("\n"):
        if line.startswith("event:"):
            event = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            data = line.split(":", 1)[1].strip()
    if data is None:
        return None
    return event, json.loads(data), rest


async def _open_events(path: str, token: str):
    """Читает SSE по мере чанков. httpx в тестах ждёт конец тела и для потока не годится."""
    from main import app

    chunks: asyncio.Queue = asyncio.Queue()
    disconnected = asyncio.Event()
    sent_request = False

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "headers": [(b"authorization", f"Bearer {token}".encode())],
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "server": ("test", 80),
        "client": ("test", 123),
        "root_path": "",
    }

    async def receive():
        nonlocal sent_request
        if not sent_request:
            sent_request = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await disconnected.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        await chunks.put(message)

    task = asyncio.create_task(app(scope, receive, send))
    start = await asyncio.wait_for(chunks.get(), timeout=3)
    assert start["type"] == "http.response.start"
    assert start["status"] == 200
    return task, chunks, disconnected


async def _next_event(chunks: asyncio.Queue, pending: str) -> tuple[str, dict, str]:
    while True:
        parsed = _take_sse(pending)
        if parsed is not None:
            return parsed
        message = await asyncio.wait_for(chunks.get(), timeout=3)
        assert message["type"] == "http.response.body"
        pending += message.get("body", b"").decode()


@pytest.mark.asyncio
async def test_events_push_revision_not_the_document(
    async_client: AsyncClient, teacher_token: str, student_token: str, student2_token: str, admin_token: str
) -> None:
    _, student_id = await _link(async_client, admin_token, teacher_token, student_token)
    created = await async_client.post(
        "/teacher/boards",
        json={"title": "Живая", "studentIds": [student_id]},
        headers=_bearer(teacher_token),
    )
    board = created.json()
    stranger = await async_client.get(
        f"/student/boards/{board['id']}/events",
        headers=_bearer(student2_token),
    )
    assert stranger.status_code == 403

    task, chunks, disconnected = await _open_events(
        f"/student/boards/{board['id']}/events", student_token
    )
    event, payload, pending = await _next_event(chunks, "")
    assert event == "update"
    assert payload["revision"] == 1
    assert "objects" not in payload

    saved = await async_client.put(
        f"/teacher/boards/{board['id']}",
        json=_put_body(board, [_sticky()]),
        headers=_bearer(teacher_token),
    )
    assert saved.status_code == 200, saved.text
    event, payload, pending = await _next_event(chunks, pending)
    assert event == "update"
    assert payload["revision"] == 2
    assert "objects" not in payload

    deleted = await async_client.delete(
        f"/teacher/boards/{board['id']}", headers=_bearer(teacher_token)
    )
    assert deleted.status_code == 200, deleted.text
    event, payload, _pending = await _next_event(chunks, pending)
    assert event == "delete"
    assert payload["id"] == board["id"]

    disconnected.set()
    await asyncio.wait_for(task, timeout=3)
