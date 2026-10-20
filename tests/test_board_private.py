import asyncio
import json

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


TASK = {
    "id": "t1", "type": "task", "x": 0, "y": 0, "w": 400, "h": 200, "rotation": 0,
    "props": {"content": "2+2", "teacherOnly": {"answer": "4", "solution": "сложить"}},
}


def test_student_never_receives_teacher_only_props():
    async def run():
        room = _room()
        teacher = RoomClient(1, "Учитель", "teacher", trusted=True)
        student = RoomClient(2, "Ученик", "student")
        await room.join(teacher)
        await room.join(student)
        _drain(teacher)
        _drain(student)

        await room.handle(teacher, json.dumps({"type": "upsert", "opId": 1, "object": TASK}))
        op = next(m for m in _drain(student) if m["type"] == "op")["op"]
        assert op["object"]["props"] == {"content": "2+2"}

        await room.handle(teacher, json.dumps({
            "type": "patch", "opId": 2, "id": "t1", "set": {"props": {"teacherOnly": {"answer": "5"}}},
        }))
        patch = next(m for m in _drain(student) if m["type"] == "op")["op"]
        assert "teacherOnly" not in patch["set"]["props"]

        late = RoomClient(3, "Ученик 2", "student")
        await room.join(late)
        snapshot = next(m for m in _drain(late) if m["type"] == "snapshot")
        assert "teacherOnly" not in snapshot["board"]["objects"][0]["props"]

        moved = {**TASK, "x": 50, "props": {"content": "2+2"}}
        await room.handle(student, json.dumps({"type": "upsert", "opId": 3, "object": moved}))
        assert room.objects["t1"]["props"]["teacherOnly"] == {"answer": "5"}
        assert room.objects["t1"]["x"] == 50

        forged = {**TASK, "props": {"content": "2+2", "teacherOnly": {"answer": "взлом"}}}
        await room.handle(student, json.dumps({"type": "upsert", "opId": 4, "object": forged}))
        assert room.objects["t1"]["props"]["teacherOnly"] == {"answer": "5"}

        teacher_view = next(m for m in _drain(teacher) if m["type"] == "op")["op"]
        assert teacher_view["object"]["props"]["teacherOnly"] == {"answer": "5"}

    asyncio.run(run())
