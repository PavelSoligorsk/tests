import asyncio
import json

from services.board_room import CLOSE_TOO_SLOW, OUTBOX_SIZE, BoardRoom, RoomClient


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


def test_slow_viewer_is_not_kicked_by_cursor_flood():
    async def run():
        room = _room()
        drawer = RoomClient(1, "Учитель", "teacher", trusted=True)
        viewer = RoomClient(2, "Ученик", "student")
        await room.join(drawer)
        await room.join(viewer)

        for step in range(OUTBOX_SIZE * 2):
            await room.handle(drawer, json.dumps({"type": "cursor", "x": step, "y": step}))

        assert viewer.close_code is None
        assert viewer.outbox.qsize() <= OUTBOX_SIZE // 2 + 1

        stroke = {
            "id": "s1", "type": "draw", "x": 0, "y": 0, "w": 12, "h": 12, "rotation": 0,
            "props": {"points": [{"x": 0, "y": 0}, {"x": 1, "y": 1}], "color": "#000", "width": 4},
        }
        await room.handle(drawer, json.dumps({"type": "upsert", "opId": 1, "object": stroke}))
        for index in range(OUTBOX_SIZE // 4):
            await room.handle(drawer, json.dumps({
                "type": "patch", "opId": index + 2, "id": "s1", "set": {"x": index},
            }))
        assert viewer.close_code is None

    asyncio.run(run())


def _drain(client: RoomClient) -> list[dict]:
    items = []
    while not client.outbox.empty():
        items.append(json.loads(client.outbox.get_nowait()))
    return items


def _stroke(points):
    return {
        "id": "s1", "type": "draw", "x": 0, "y": 0, "w": 12, "h": 12, "rotation": 0,
        "props": {"points": points, "color": "#000", "width": 4},
    }


def test_finished_stroke_replaces_the_previous_one():
    async def run():
        room = _room()
        drawer = RoomClient(1, "Учитель", "teacher", trusted=True)
        viewer = RoomClient(2, "Ученик", "student")
        await room.join(drawer)
        await room.join(viewer)
        _drain(drawer)
        _drain(viewer)
        first = _stroke([{"x": 0, "y": 0}, {"x": 1, "y": 1}])
        await room.handle(drawer, json.dumps({"type": "upsert", "opId": 1, "object": first}))
        _drain(viewer)

        finished = _stroke([{"x": 0, "y": 0}, {"x": 1, "y": 1}, {"x": 4, "y": 5}])
        await room.handle(drawer, json.dumps({"type": "upsert", "opId": 2, "object": finished}))
        assert room.objects["s1"]["props"]["points"] == finished["props"]["points"]
        op = next(item["op"] for item in _drain(viewer) if item["type"] == "op")
        assert op["object"]["props"]["points"] == finished["props"]["points"]

    asyncio.run(run())


def test_viewer_that_never_reads_ops_is_still_closed():
    async def run():
        room = _room()
        drawer = RoomClient(1, "Учитель", "teacher", trusted=True)
        viewer = RoomClient(2, "Ученик", "student")
        await room.join(drawer)
        await room.join(viewer)
        stroke = {
            "id": "s1", "type": "draw", "x": 0, "y": 0, "w": 12, "h": 12, "rotation": 0,
            "props": {"points": [{"x": 0, "y": 0}], "color": "#000", "width": 4},
        }
        await room.handle(drawer, json.dumps({"type": "upsert", "opId": 0, "object": stroke}))
        for index in range(OUTBOX_SIZE + 5):
            await room.handle(drawer, json.dumps({
                "type": "patch", "opId": index + 1, "id": "s1", "set": {"x": index},
            }))
        assert viewer.close_code == CLOSE_TOO_SLOW

    asyncio.run(run())
