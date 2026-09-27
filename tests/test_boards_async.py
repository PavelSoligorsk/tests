"""Доски занятия: документ, ревизия, картинки, шаблоны."""
from __future__ import annotations

import base64
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import TeacherStudent
from main import app
from tests.conftest import register_user
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


def _sticky(object_id: str = "s1", **props) -> dict:
    return {
        "id": object_id,
        "type": "sticky",
        "x": 10,
        "y": 20,
        "w": 200,
        "h": 160,
        "rotation": 0,
        "props": {"text": "привет", "color": "#fde68a", "fontSize": 16, **props},
    }


def _put_body(board: dict, objects: list | None = None, revision: int | None = None) -> dict:
    return {
        "id": board["id"],
        "title": board["title"],
        "lessonId": board["lessonId"],
        "kind": board["kind"],
        "ownerId": board["ownerId"],
        "revision": board["revision"] if revision is None else revision,
        "createdAt": board["createdAt"],
        "updatedAt": board["updatedAt"],
        "camera": board["camera"],
        "objects": board["objects"] if objects is None else objects,
    }


async def _ids(ac: AsyncClient, admin_token: str, teacher_token: str, student_token: str) -> tuple[int, int]:
    users = (await ac.get("/admin/users", headers=_bearer(admin_token))).json()
    teacher_id = next(user["id"] for user in users if user["role"] == "teacher")
    student = (await ac.get("/student/me", headers=_bearer(student_token))).json()
    student_id = student["user"]["id"]
    link = await ac.post(
        "/admin/assign-student-to-teacher",
        json={"teacher_id": teacher_id, "student_id": student_id},
        headers=_bearer(admin_token),
    )
    assert link.status_code == 200, link.text
    return teacher_id, student_id


async def _lesson(ac: AsyncClient, teacher_token: str, student_id: int | None = None, **extra) -> dict:
    slot = datetime.utcnow().replace(microsecond=0) + timedelta(days=3)
    payload = {
        "title": "Урок дробей",
        "lesson_type": "individual",
        "scheduled_date": slot.isoformat(),
        "duration_minutes": 60,
    }
    if student_id is not None:
        payload["student_id"] = student_id
    payload.update(extra)
    resp = await ac.post("/teacher/lessons", json=payload, headers=_bearer(teacher_token))
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_open_lesson_creates_two_boards_once(
    async_client: AsyncClient, teacher_token: str, student_token: str, admin_token: str
) -> None:
    _, student_id = await _ids(async_client, admin_token, teacher_token, student_token)
    lesson = await _lesson(async_client, teacher_token, student_id)

    before = await async_client.get("/student/boards", headers=_bearer(student_token))
    assert before.status_code == 200
    assert before.json() == []

    first = await async_client.get(
        f"/student/lessons/{lesson['id']}/board", headers=_bearer(student_token)
    )
    assert first.status_code == 200, first.text
    opened = first.json()
    assert opened["class"]["kind"] == "class"
    assert opened["class"]["ownerId"] is None
    assert opened["class"]["lessonId"] == lesson["id"]
    assert opened["class"]["revision"] == 1
    assert opened["class"]["objects"] == []
    assert opened["mine"]["kind"] == "student"
    assert opened["mine"]["ownerId"] == student_id
    assert "objects" not in (await async_client.get("/student/boards", headers=_bearer(student_token))).json()[0]
    assert (await async_client.get("/student/boards", headers=_bearer(student_token))).json()[0]["objectCount"] == 0

    second = await async_client.get(
        f"/student/lessons/{lesson['id']}/board", headers=_bearer(student_token)
    )
    assert second.json()["class"]["id"] == opened["class"]["id"]
    assert second.json()["mine"]["id"] == opened["mine"]["id"]


@pytest.mark.asyncio
async def test_revision_conflict_and_permissions(
    async_client: AsyncClient, teacher_token: str, student_token: str, admin_token: str, student2_token: str
) -> None:
    _, student_id = await _ids(async_client, admin_token, teacher_token, student_token)
    lesson = await _lesson(async_client, teacher_token, student_id)
    opened = (
        await async_client.get(f"/student/lessons/{lesson['id']}/board", headers=_bearer(student_token))
    ).json()

    saved = await async_client.put(
        f"/student/boards/{opened['mine']['id']}",
        json=_put_body(opened["mine"], [_sticky()]),
        headers=_bearer(student_token),
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["revision"] == 2
    assert saved.json()["objects"][0]["props"]["text"] == "привет"

    stale = await async_client.put(
        f"/student/boards/{opened['mine']['id']}",
        json=_put_body(opened["mine"], [_sticky("s2")], revision=1),
        headers=_bearer(student_token),
    )
    assert stale.status_code == 409
    assert stale.json()["revision"] == 2
    assert stale.json()["objects"][0]["id"] == "s1"

    forbidden = await async_client.put(
        f"/student/boards/{opened['class']['id']}",
        json=_put_body(opened["class"], [_sticky()]),
        headers=_bearer(student_token),
    )
    assert forbidden.status_code == 403

    removed = await async_client.delete(
        f"/student/boards/{opened['class']['id']}", headers=_bearer(student_token)
    )
    assert removed.status_code == 403

    teacher_write = await async_client.put(
        f"/teacher/boards/{opened['mine']['id']}",
        json=_put_body(saved.json(), [_sticky("no")]),
        headers=_bearer(teacher_token),
    )
    assert teacher_write.status_code == 403

    teacher_class = await async_client.put(
        f"/teacher/boards/{opened['class']['id']}",
        json=_put_body(opened["class"], [_sticky("t1")]),
        headers=_bearer(teacher_token),
    )
    assert teacher_class.status_code == 200, teacher_class.text
    assert teacher_class.json()["revision"] == 2

    stranger = await async_client.get(
        f"/student/lessons/{lesson['id']}/board", headers=_bearer(student2_token)
    )
    assert stranger.status_code == 403

    too_many = _put_body(teacher_class.json(), [_sticky(str(i)) for i in range(201)], revision=2)
    overflow = await async_client.put(
        f"/teacher/boards/{opened['class']['id']}",
        json=too_many,
        headers=_bearer(teacher_token),
    )
    assert overflow.status_code == 400


@pytest.mark.asyncio
async def test_draft_delete_removes_images(
    async_client: AsyncClient, student_token: str, r2: _FakeS3
) -> None:
    created = await async_client.post(
        "/student/boards", json={"title": "Черновик"}, headers=_bearer(student_token)
    )
    assert created.status_code == 200, created.text
    draft = created.json()
    assert draft["kind"] == "draft"
    assert draft["lessonId"] is None
    assert draft["revision"] == 1

    uploaded = await async_client.post(
        "/student/boards/images",
        files={"file": ("чертёж.png", MINI_PNG, "image/png")},
        headers=_bearer(student_token),
    )
    assert uploaded.status_code == 200, uploaded.text
    image = uploaded.json()
    assert image["fileId"]
    assert image["name"] == "чертёж.png"
    assert image["src"].endswith(f"boards/{image['fileId']}.png")
    assert list(r2.store)

    image_object = {
        "id": "img1",
        "type": "image",
        "x": 0, "y": 0, "w": 10, "h": 10, "rotation": 0,
        "props": {"fileId": image["fileId"], "src": "", "name": image["name"], "note": "keep"},
    }
    saved = await async_client.put(
        f"/student/boards/{draft['id']}",
        json=_put_body(draft, [image_object]),
        headers=_bearer(student_token),
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["objects"][0]["props"]["note"] == "keep"
    assert saved.json()["objects"][0]["props"]["src"].endswith(".png")

    deleted = await async_client.delete(f"/student/boards/{draft['id']}", headers=_bearer(student_token))
    assert deleted.status_code == 200, deleted.text
    assert r2.deleted
    assert r2.store == {}

    missing = await async_client.get(f"/student/boards/{draft['id']}", headers=_bearer(student_token))
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_lesson_delete_removes_board_images(
    async_client: AsyncClient, teacher_token: str, student_token: str, admin_token: str, r2: _FakeS3
) -> None:
    _, student_id = await _ids(async_client, admin_token, teacher_token, student_token)
    lesson = await _lesson(async_client, teacher_token, student_id)
    opened = (
        await async_client.get(f"/teacher/lessons/{lesson['id']}/boards", headers=_bearer(teacher_token))
    ).json()
    assert opened["class"]["kind"] == "class"
    assert len(opened["notebooks"]) == 1
    assert "objects" not in opened["notebooks"][0]
    assert opened["notebooks"][0]["ownerId"] == student_id

    uploaded = await async_client.post(
        "/teacher/boards/images",
        files={"file": ("a.png", MINI_PNG, "image/png")},
        headers=_bearer(teacher_token),
    )
    assert uploaded.status_code == 200, uploaded.text
    file_id = uploaded.json()["fileId"]
    image_object = {
        "id": "img1", "type": "image", "x": 1, "y": 1, "w": 2, "h": 2, "rotation": 0,
        "props": {"fileId": file_id, "src": "", "name": "a.png"},
    }
    saved = await async_client.put(
        f"/teacher/boards/{opened['class']['id']}",
        json=_put_body(opened["class"], [image_object]),
        headers=_bearer(teacher_token),
    )
    assert saved.status_code == 200, saved.text

    removed = await async_client.delete(f"/teacher/lessons/{lesson['id']}", headers=_bearer(teacher_token))
    assert removed.status_code == 200, removed.text
    assert r2.store == {}
    gone = await async_client.get(
        f"/student/lessons/{lesson['id']}/board", headers=_bearer(student_token)
    )
    assert gone.status_code == 404


@pytest.mark.asyncio
async def test_group_lesson_one_notebook_each(
    async_client: AsyncClient,
    teacher_token: str,
    student_token: str,
    student2_token: str,
    admin_token: str,
) -> None:
    teacher_id, student_id = await _ids(async_client, admin_token, teacher_token, student_token)
    student2 = (await async_client.get("/student/me", headers=_bearer(student2_token))).json()
    student2_id = student2["user"]["id"]
    link = await async_client.post(
        "/admin/assign-student-to-teacher",
        json={"teacher_id": teacher_id, "student_id": student2_id},
        headers=_bearer(admin_token),
    )
    assert link.status_code == 200, link.text
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

    lesson = await _lesson(
        async_client,
        teacher_token,
        lesson_type="group",
        group_id=group_id,
        title="Групповой",
    )
    teacher_view = await async_client.get(
        f"/teacher/lessons/{lesson['id']}/boards", headers=_bearer(teacher_token)
    )
    assert teacher_view.status_code == 200, teacher_view.text
    owners = {item["ownerId"] for item in teacher_view.json()["notebooks"]}
    assert owners == {student_id, student2_id}

    mine = await async_client.get(
        f"/student/lessons/{lesson['id']}/board", headers=_bearer(student2_token)
    )
    assert mine.status_code == 200, mine.text
    assert mine.json()["mine"]["ownerId"] == student2_id
    assert mine.json()["class"]["id"] == teacher_view.json()["class"]["id"]


@pytest.mark.asyncio
async def test_templates_follow_the_lesson_teacher(
    async_client: AsyncClient,
    teacher_token: str,
    student_token: str,
    admin_token: str,
    db: AsyncSession,
) -> None:
    _, student_id = await _ids(async_client, admin_token, teacher_token, student_token)
    other = await register_user(
        TestClient(app), db, "teacher2_boards@test.com", "Teacher123!", "Второй", "Учитель", role="teacher"
    )
    # /admin/assign-student-to-teacher заменяет учителя, а каталог читает все связи.
    db.add(TeacherStudent(teacher_id=other["id"], student_id=student_id))
    await db.commit()

    async def _upload(token: str, payload: bytes) -> None:
        resp = await async_client.post(
            "/teacher/geogebra-templates",
            data={"id": "circle", "title": "Окружность", "appName": "geometry"},
            files={"file": ("circle.ggb", payload, "application/octet-stream")},
            headers=_bearer(token),
        )
        assert resp.status_code == 200, resp.text

    await _upload(teacher_token, b"AAA")
    await _upload(other["token"], b"BBB")

    catalog = await async_client.get("/board/geogebra-templates", headers=_bearer(student_token))
    assert catalog.status_code == 200, catalog.text
    rows = catalog.json()
    assert len(rows) == 2
    assert {row["id"] for row in rows} == {"circle"}
    assert "ggbBase64" not in rows[0]
    assert len({row["teacherId"] for row in rows}) == 2

    lesson = await _lesson(async_client, teacher_token, student_id)
    lesson_teacher = (
        await async_client.get(f"/teacher/lessons/{lesson['id']}", headers=_bearer(teacher_token))
    ).json()["teacher_id"]
    expected = base64.b64encode(b"AAA").decode("ascii")
    fetched = await async_client.get(
        f"/board/geogebra-templates/circle?lessonId={lesson['id']}",
        headers=_bearer(student_token),
    )
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["ggbBase64"] == expected
    assert fetched.json()["teacherId"] == lesson_teacher

    opened = (
        await async_client.get(f"/student/lessons/{lesson['id']}/board", headers=_bearer(student_token))
    ).json()
    ggb = {
        "id": "g1",
        "type": "geogebra",
        "x": 0, "y": 0, "w": 100, "h": 80, "rotation": 0,
        "props": {"appName": "geometry", "ggbBase64": "", "templateId": "circle", "custom": True},
    }
    saved = await async_client.put(
        f"/student/boards/{opened['mine']['id']}",
        json=_put_body(opened["mine"], [ggb]),
        headers=_bearer(student_token),
    )
    assert saved.status_code == 200, saved.text
    props = saved.json()["objects"][0]["props"]
    assert props["ggbBase64"] == expected
    assert props["custom"] is True

    draft = (
        await async_client.post("/student/boards", json={"title": "Свой"}, headers=_bearer(student_token))
    ).json()
    draft_ggb = {**ggb, "props": {**ggb["props"], "ggbBase64": ""}}
    draft_saved = await async_client.put(
        f"/student/boards/{draft['id']}",
        json=_put_body(draft, [draft_ggb]),
        headers=_bearer(student_token),
    )
    assert draft_saved.status_code == 200, draft_saved.text
    filled = draft_saved.json()["objects"][0]["props"]["ggbBase64"]
    smallest = min(row["teacherId"] for row in rows)
    expected_draft = base64.b64encode(b"AAA" if smallest == lesson_teacher else b"BBB").decode("ascii")
    assert filled == expected_draft
