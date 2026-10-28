import asyncio
import json

from services import board_scene as scene
from services.board_room import BoardRoom, RoomClient


class _Store:
    async def load(self, board_id):
        return None

    async def save(self, board_id, title, camera, objects):
        return 1

    async def image_src(self, board_id, file_id):
        return ""


def _room() -> BoardRoom:
    return BoardRoom({
        "id": "b1", "title": "Доска", "teacherId": 1, "groupId": None, "studentIds": [2],
        "revision": 0, "createdAt": "", "updatedAt": "",
        "camera": {"x": 0, "y": 0, "zoom": 1}, "objects": [],
    }, _Store())


def _drain(client: RoomClient) -> list[dict]:
    items = []
    while not client.outbox.empty():
        items.append(json.loads(client.outbox.get_nowait()))
    return items


THEORY = {
    "type": "card",
    "title": "Карточка",
    "blocks": [
        {"type": "text", "content": "Текст"},
        {"type": "html", "html": "<img src=x onerror=alert(1)>"},
    ],
}


def _theory_object(block: dict) -> dict:
    return {
        "id": "th1", "type": "text", "x": 0, "y": 0, "w": 300, "h": 200, "rotation": 0,
        "props": {"format": "theory", "text": "", "theoryBlock": block},
    }


def test_strip_untrusted_markup_drops_html_blocks_and_tags():
    block = {
        "type": "steps",
        "steps": ["Шаг <Html><img src=x onerror=alert(1)></Html> дальше", "Обычный шаг"],
        "blocks": [{"type": "html", "html": "<b>x</b>"}, {"type": "text", "content": "ok"}],
    }
    cleaned = scene.strip_untrusted_markup({"theoryBlock": block, "text": "keep"})
    assert cleaned["text"] == "keep"
    assert cleaned["theoryBlock"]["steps"] == ["Шаг  дальше", "Обычный шаг"]
    assert cleaned["theoryBlock"]["blocks"] == [{"type": "text", "content": "ok"}]


def test_student_cannot_put_raw_html_on_board_but_teacher_can():
    async def run():
        room = _room()
        teacher = RoomClient(1, "Учитель", "teacher", trusted=True)
        student = RoomClient(2, "Ученик", "student")
        await room.join(teacher)
        await room.join(student)
        _drain(teacher)
        _drain(student)

        await room.handle(student, json.dumps({"type": "upsert", "opId": 1, "object": _theory_object(THEORY)}))
        stored = room.objects["th1"]["props"]["theoryBlock"]
        assert [item["type"] for item in stored["blocks"]] == ["text"]
        relayed = next(m for m in _drain(teacher) if m["type"] == "op")["op"]
        assert "onerror" not in json.dumps(relayed)

        await room.handle(student, json.dumps({
            "type": "patch", "opId": 2, "id": "th1", "set": {"props": {"theoryBlock": THEORY}},
        }))
        assert "onerror" not in json.dumps(room.objects["th1"])

        await room.handle(teacher, json.dumps({"type": "upsert", "opId": 3, "object": _theory_object(THEORY)}))
        assert [item["type"] for item in room.objects["th1"]["props"]["theoryBlock"]["blocks"]] == ["text", "html"]

    asyncio.run(run())


def test_ping_gets_pong_even_on_read_only_link():
    async def run():
        room = _room()
        guest = RoomClient(5, "Гость", "student", can_edit=False)
        await room.join(guest)
        _drain(guest)
        await room.handle(guest, json.dumps({"type": "ping", "t": 12.5}))
        await room.handle(guest, json.dumps({"type": "ping", "t": "x"}))
        assert _drain(guest) == [{"type": "pong", "t": 12.5}, {"type": "pong", "t": None}]

    asyncio.run(run())


def test_geomove_is_relayed_to_others_and_validated():
    async def run():
        room = _room()
        teacher = RoomClient(1, "Учитель", "teacher", trusted=True)
        student = RoomClient(2, "Ученик", "student")
        guest = RoomClient(5, "Гость", "student", can_edit=False)
        for client in (teacher, student, guest):
            await room.join(client)
        for client in (teacher, student, guest):
            _drain(client)

        await room.handle(teacher, json.dumps({
            "type": "geomove", "id": "g1", "t": 1000, "moves": [{"n": "A", "v": [1.5, 2]}, {"n": "a", "v": [3]}],
        }))
        relayed = _drain(student)
        assert relayed == [{
            "type": "geomove", "clientId": teacher.id, "id": "g1", "t": 1000,
            "moves": [{"n": "A", "v": [1.5, 2]}, {"n": "a", "v": [3]}],
        }]
        assert _drain(teacher) == []
        assert [m["type"] for m in _drain(guest)] == ["geomove"]
        assert room.objects == {}

        await room.handle(teacher, json.dumps({"type": "geomove", "id": "g1", "moves": [{"n": "A", "v": ["x"]}]}))
        await room.handle(teacher, json.dumps({"type": "geomove", "id": "g1", "moves": []}))
        assert _drain(student) == []

        await room.handle(guest, json.dumps({"type": "geomove", "id": "g1", "moves": [{"n": "A", "v": [0, 0]}]}))
        assert _drain(student) == []
        assert [m["type"] for m in _drain(guest)] == ["error"]

    asyncio.run(run())
