"""Именная доска учителя: ученики или группа, живые правки через WebSocket."""
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


def _draw(object_id: str = "d1") -> dict:
    return {
        "id": object_id,
        "type": "draw",
        "x": 0, "y": 0, "w": 100, "h": 100, "rotation": 0,
        "props": {"points": [{"x": 0, "y": 0}], "color": "#111", "width": 2},
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


async def _board_for(ac: AsyncClient, teacher_token: str, student_id: int, title: str = "Живая") -> dict:
    created = await ac.post(
        "/teacher/boards",
        json={"title": title, "studentIds": [student_id]},
        headers=_bearer(teacher_token),
    )
    assert created.status_code == 200, created.text
    return created.json()


class _Socket:
    """WebSocket прямо через ASGI, в том же цикле событий, что и тест."""

    def __init__(self, task: asyncio.Task, inbox: asyncio.Queue, outbox: asyncio.Queue) -> None:
        self.task = task
        self.inbox = inbox
        self.outbox = outbox
        self.close_code: int | None = None

    async def send(self, payload: dict) -> None:
        await self.inbox.put({"type": "websocket.receive", "text": json.dumps(payload)})

    async def recv(self) -> dict:
        message = await asyncio.wait_for(self.outbox.get(), timeout=3)
        if message["type"] == "websocket.close":
            self.close_code = message.get("code", 1000)
            await self.inbox.put({"type": "websocket.disconnect", "code": self.close_code})
            return {"type": "__closed__", "code": self.close_code}
        return json.loads(message["text"])

    async def expect(self, kind: str) -> dict:
        while True:
            message = await self.recv()
            if message["type"] == kind:
                return message
            assert message["type"] != "__closed__", f"сокет закрылся, ждали {kind}"

    async def close(self) -> None:
        if self.close_code is None:
            await self.inbox.put({"type": "websocket.disconnect", "code": 1000})
        await asyncio.wait_for(self.task, timeout=3)


async def _connect(path: str, token: str | None) -> _Socket:
    from main import app

    inbox: asyncio.Queue = asyncio.Queue()
    outbox: asyncio.Queue = asyncio.Queue()
    scope = {
        "type": "websocket",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "scheme": "ws",
        "path": path,
        "raw_path": path.encode(),
        "query_string": (f"token={token}" if token else "").encode(),
        "headers": [],
        "server": ("test", 80),
        "client": ("test", 123),
        "root_path": "",
        "subprotocols": [],
    }
    await inbox.put({"type": "websocket.connect"})
    task = asyncio.create_task(app(scope, inbox.get, outbox.put))
    accepted = await asyncio.wait_for(outbox.get(), timeout=3)
    assert accepted["type"] == "websocket.accept", accepted
    return _Socket(task, inbox, outbox)


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

    same = await async_client.get(f"/student/boards/{board['id']}", headers=_bearer(student2_token))
    assert same.status_code == 200
    assert same.json()["id"] == board["id"]

    both = await async_client.post(
        "/teacher/boards",
        json={"title": "И то и то", "studentIds": [student_id], "groupId": 1},
        headers=_bearer(teacher_token),
    )
    assert both.status_code == 400


@pytest.mark.asyncio
async def test_personal_board_opens_by_share_link(
    async_client: AsyncClient, teacher_token: str, student_token: str, admin_token: str
) -> None:
    await _link(async_client, admin_token, teacher_token, student_token)
    created = await async_client.post(
        "/teacher/boards", json={"title": "Черновик"}, headers=_bearer(teacher_token)
    )
    assert created.status_code == 200, created.text
    board = created.json()
    assert board["studentIds"] == []
    assert board["groupId"] is None
    assert board["shareAccess"] == "off"
    assert board["shareToken"] is None

    hidden = await async_client.get(f"/student/boards/{board['id']}", headers=_bearer(student_token))
    assert hidden.status_code == 403

    opened = await async_client.patch(
        f"/teacher/boards/{board['id']}/share",
        json={"access": "edit"},
        headers=_bearer(teacher_token),
    )
    assert opened.status_code == 200, opened.text
    token = opened.json()["shareToken"]
    assert opened.json()["shareAccess"] == "edit"
    assert token

    shared = await async_client.get(f"/board/shared/{token}", headers=_bearer(student_token))
    assert shared.status_code == 200, shared.text
    assert shared.json()["canEdit"] is True
    assert shared.json()["id"] == board["id"]
    assert "shareToken" not in shared.json() or shared.json()["shareToken"] is None

    viewed = await async_client.patch(
        f"/teacher/boards/{board['id']}/share",
        json={"access": "view"},
        headers=_bearer(teacher_token),
    )
    assert viewed.status_code == 200
    assert (await async_client.get(f"/board/shared/{token}", headers=_bearer(student_token))).json()["canEdit"] is False

    reset = await async_client.patch(
        f"/teacher/boards/{board['id']}/share",
        json={"access": "edit", "resetLink": True},
        headers=_bearer(teacher_token),
    )
    assert reset.status_code == 200
    assert reset.json()["shareToken"] != token
    gone = await async_client.get(f"/board/shared/{token}", headers=_bearer(student_token))
    assert gone.status_code == 404

    closed = await async_client.patch(
        f"/teacher/boards/{board['id']}/share",
        json={"access": "off"},
        headers=_bearer(teacher_token),
    )
    assert closed.status_code == 200
    dead = await async_client.get(
        f"/board/shared/{reset.json()['shareToken']}", headers=_bearer(student_token)
    )
    assert dead.status_code == 404


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

    socket = await _connect(f"/student/boards/{board['id']}/ws", student2_token)
    snapshot = await socket.expect("snapshot")
    assert snapshot["board"]["groupId"] == group_id
    await socket.close()


@pytest.mark.asyncio
async def test_ops_reach_the_other_participant(
    async_client: AsyncClient, teacher_token: str, student_token: str, admin_token: str
) -> None:
    _, student_id = await _link(async_client, admin_token, teacher_token, student_token)
    board = await _board_for(async_client, teacher_token, student_id)

    teacher = await _connect(f"/teacher/boards/{board['id']}/ws", teacher_token)
    first = await teacher.expect("snapshot")
    assert first["board"]["objects"] == []
    assert first["peers"] == []

    student = await _connect(f"/student/boards/{board['id']}/ws", student_token)
    snapshot = await student.expect("snapshot")
    assert [peer["clientId"] for peer in snapshot["peers"]] == [first["clientId"]]
    joined = await teacher.expect("join")
    assert joined["peer"]["clientId"] == snapshot["clientId"]
    assert joined["peer"]["role"] == "student"

    await student.send({"type": "upsert", "opId": "a1", "object": _sticky()})
    ack = await student.expect("ack")
    assert ack["opId"] == "a1"
    assert ack["seq"] == 1
    seen = await teacher.expect("op")
    assert seen["seq"] == 1
    assert seen["clientId"] == snapshot["clientId"]
    assert seen["op"] == {"type": "upsert", "object": _sticky()}

    await teacher.send({"type": "patch", "opId": "t1", "id": "s1", "set": {"x": 99, "props": {"text": "ok"}}})
    assert (await teacher.expect("ack"))["seq"] == 2
    moved = await student.expect("op")
    assert moved["op"] == {"type": "patch", "id": "s1", "set": {"x": 99, "props": {"text": "ok"}}}

    stroke = _draw()
    stroke["props"]["points"] = [{"x": 0, "y": 0}, {"x": 5, "y": 6}]
    await teacher.send({"type": "upsert", "opId": "t2", "object": stroke})
    await teacher.expect("ack")
    drawn = await student.expect("op")
    assert drawn["op"]["object"]["props"]["points"] == stroke["props"]["points"]

    await teacher.send({"type": "reorder", "opId": "t3", "ids": ["d1", "s1"]})
    await teacher.expect("ack")
    assert (await student.expect("op"))["op"] == {"type": "reorder", "ids": ["d1", "s1"]}

    await student.send({"type": "title", "opId": "a3", "title": "Новая"})
    await student.expect("ack")
    assert (await teacher.expect("op"))["op"] == {"type": "title", "title": "Новая"}

    await student.send({"type": "patch", "opId": "bad", "id": "nope", "set": {"x": 1}})
    error = await student.expect("error")
    assert error["opId"] == "bad"

    await student.send({"type": "cursor", "x": 1.5, "y": 2})
    cursor = await teacher.expect("cursor")
    assert cursor == {"type": "cursor", "clientId": snapshot["clientId"], "x": 1.5, "y": 2}

    live = await async_client.get(f"/teacher/boards/{board['id']}", headers=_bearer(teacher_token))
    assert live.status_code == 200
    assert [obj["id"] for obj in live.json()["objects"]] == ["d1", "s1"]

    await student.close()
    left = await teacher.expect("leave")
    assert left["clientId"] == snapshot["clientId"]
    await teacher.close()

    stored = await async_client.get(f"/student/boards/{board['id']}", headers=_bearer(student_token))
    assert stored.status_code == 200
    document = stored.json()
    assert document["title"] == "Новая"
    assert document["revision"] >= 2
    assert [obj["id"] for obj in document["objects"]] == ["d1", "s1"]
    assert document["objects"][0]["props"]["points"] == [{"x": 0, "y": 0}, {"x": 5, "y": 6}]
    assert document["objects"][1]["x"] == 99
    assert document["objects"][1]["props"] == {"text": "ok", "color": "#fde68a"}

    listed = await async_client.get("/teacher/boards", headers=_bearer(teacher_token))
    meta = next(item for item in listed.json() if item["id"] == board["id"])
    assert meta["objectCount"] == 2
    assert meta["title"] == "Новая"

    again = await _connect(f"/teacher/boards/{board['id']}/ws", teacher_token)
    reopened = await again.expect("snapshot")
    assert [obj["id"] for obj in reopened["board"]["objects"]] == ["d1", "s1"]
    await again.close()


@pytest.mark.asyncio
async def test_socket_checks_access(
    async_client: AsyncClient, teacher_token: str, student_token: str, student2_token: str, admin_token: str
) -> None:
    _, student_id = await _link(async_client, admin_token, teacher_token, student_token)
    board = await _board_for(async_client, teacher_token, student_id)

    stranger = await _connect(f"/student/boards/{board['id']}/ws", student2_token)
    assert (await stranger.recv())["code"] == 4403
    await stranger.close()

    anonymous = await _connect(f"/student/boards/{board['id']}/ws", None)
    assert (await anonymous.recv())["code"] == 4401
    await anonymous.close()

    missing = await _connect("/teacher/boards/00000000-0000-0000-0000-000000000000/ws", teacher_token)
    assert (await missing.recv())["code"] == 4404
    await missing.close()


@pytest.mark.asyncio
async def test_delete_closes_room_and_removes_images(
    async_client: AsyncClient, teacher_token: str, student_token: str, admin_token: str, r2: _FakeS3
) -> None:
    _, student_id = await _link(async_client, admin_token, teacher_token, student_token)
    board = await _board_for(async_client, teacher_token, student_id, "С картинкой")
    uploaded = await async_client.post(
        "/teacher/boards/images",
        files={"file": ("a.png", MINI_PNG, "image/png")},
        headers=_bearer(teacher_token),
    )
    assert uploaded.status_code == 200, uploaded.text

    student = await _connect(f"/student/boards/{board['id']}/ws", student_token)
    await student.expect("snapshot")
    image = {
        "id": "img1", "type": "image", "x": 0, "y": 0, "w": 10, "h": 10, "rotation": 0,
        "props": {"fileId": uploaded.json()["fileId"], "src": "", "name": "a.png"},
    }
    await student.send({"type": "upsert", "opId": "i1", "object": image})
    ack = await student.expect("ack")
    assert ack["object"]["props"]["src"].endswith(".png")

    deleted = await async_client.delete(f"/teacher/boards/{board['id']}", headers=_bearer(teacher_token))
    assert deleted.status_code == 200, deleted.text
    notice = await student.expect("deleted")
    assert notice["id"] == board["id"]
    assert (await student.recv())["code"] == 4404
    await student.close()

    assert r2.store == {}
    missing = await async_client.get(f"/student/boards/{board['id']}", headers=_bearer(student_token))
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_template_stays_out_of_the_board_document(
    async_client: AsyncClient, teacher_token: str, student_token: str, admin_token: str
) -> None:
    _, student_id = await _link(async_client, admin_token, teacher_token, student_token)
    uploaded = await async_client.post(
        "/teacher/geogebra-templates",
        data={"id": "circle", "title": "Окружность", "appName": "geometry"},
        files={"file": ("circle.ggb", b"AAA", "application/octet-stream")},
        headers=_bearer(teacher_token),
    )
    assert uploaded.status_code == 200, uploaded.text
    board = await _board_for(async_client, teacher_token, student_id, "Чертёж")

    ggb = {
        "id": "g1", "type": "geogebra", "x": 0, "y": 0, "w": 10, "h": 10, "rotation": 0,
        "props": {"appName": "geometry", "ggbBase64": "", "templateId": "circle", "custom": True},
    }
    student = await _connect(f"/student/boards/{board['id']}/ws", student_token)
    await student.expect("snapshot")
    await student.send({"type": "upsert", "opId": "g", "object": ggb})
    ack = await student.expect("ack")
    assert "object" not in ack
    await student.close()

    stored = await async_client.get(f"/student/boards/{board['id']}", headers=_bearer(student_token))
    props = stored.json()["objects"][0]["props"]
    assert props["ggbBase64"] == ""
    assert props["templateId"] == "circle"
    assert props["custom"] is True

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
