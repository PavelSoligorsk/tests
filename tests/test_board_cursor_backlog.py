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


def test_teacher_hides_cursors_and_anyone_can_pull_view():
    async def run():
        room = _room()
        teacher = RoomClient(1, "Учитель", "teacher", trusted=True)
        student = RoomClient(2, "Ученик", "student", can_edit=True)
        await room.join(teacher)
        await room.join(student)
        _drain(teacher)
        _drain(student)

        await room.handle(student, json.dumps({"type": "cursors", "enabled": False}))
        assert room.cursors is True
        assert any(item.get("type") == "error" for item in _drain(student))

        await room.handle(teacher, json.dumps({"type": "cursors", "enabled": False}))
        assert room.cursors is False
        assert next(item for item in _drain(student) if item["type"] == "cursors")["enabled"] is False

        await room.handle(student, json.dumps({"type": "pull", "camera": {"x": 10, "y": 20, "zoom": 2}}))
        pulled = next(item for item in _drain(teacher) if item["type"] == "pull")
        assert pulled["camera"] == {"x": 10, "y": 20, "zoom": 2}
        assert room.camera["zoom"] == 1

    asyncio.run(run())


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


def test_geocam_is_broadcast_and_not_stored():
    async def run():
        room = _room()
        drawer = RoomClient(1, "Учитель", "teacher", trusted=True)
        viewer = RoomClient(2, "Ученик", "student")
        await room.join(drawer)
        await room.join(viewer)
        _drain(drawer)
        _drain(viewer)
        await room.handle(drawer, json.dumps({
            "type": "geocam",
            "id": "geo-1",
            "seq": 4,
            "az": 20,
            "el": -15,
            "z": 0.01,
            "c": [1, 2, 3],
        }))
        seen = next(item for item in _drain(viewer) if item["type"] == "geocam")
        assert seen["id"] == "geo-1"
        assert seen["seq"] == 4
        assert seen["z"] == 0.01
        assert room.geocams["geo-1"]["seq"] == 4
        assert room.objects == {}
        assert room.dirty is False
        assert _drain(drawer) == []
        snap = json.loads(room._snapshot(viewer))
        assert snap["geocams"][0]["id"] == "geo-1"

        await room.handle(viewer, json.dumps({
            "type": "geocam",
            "id": "geo-1",
            "seq": 5,
            "az": 40,
            "el": 0,
            "z": 0.02,
            "c": [0, 0, 0],
        }))
        assert _drain(drawer) == []
        assert room.geocams["geo-1"]["seq"] == 4

    asyncio.run(run())


def test_laser_is_broadcast_and_not_stored():
    async def run():
        room = _room()
        drawer = RoomClient(1, "Учитель", "teacher", trusted=True)
        viewer = RoomClient(2, "Ученик", "student")
        await room.join(drawer)
        await room.join(viewer)
        _drain(drawer)
        _drain(viewer)

        await room.handle(drawer, json.dumps({
            "type": "laser",
            "points": [{"x": 1, "y": 2}, {"x": 8, "y": 9}],
        }))
        seen = next(item for item in _drain(viewer) if item["type"] == "laser")
        assert seen["clientId"] == drawer.id
        assert seen["points"] == [{"x": 1, "y": 2}, {"x": 8, "y": 9}]
        assert seen["color"] == "#fde047"
        assert seen["width"] == 18
        assert seen["fadeMs"] == 2000
        assert room.objects == {}
        assert room.dirty is False
        assert _drain(drawer) == []

        await room.handle(drawer, json.dumps({"type": "laser", "opId": "bad", "points": [{"x": 1, "y": 2}]}))
        error = next(item for item in _drain(drawer) if item["type"] == "error")
        assert error["opId"] == "bad"
        assert _drain(viewer) == []

    asyncio.run(run())


def test_view_only_guest_cannot_change_the_board():
    async def run():
        room = _room()
        owner = RoomClient(1, "Учитель", "teacher", trusted=True)
        guest = RoomClient(2, "Гость", "student", can_edit=False)
        await room.join(owner)
        await room.join(guest)
        _drain(owner)
        _drain(guest)
        await room.handle(guest, json.dumps({
            "type": "upsert", "opId": "no", "object": {
                "id": "s1", "type": "sticky", "x": 0, "y": 0, "w": 10, "h": 10, "rotation": 0, "props": {},
            },
        }))
        error = next(item for item in _drain(guest) if item["type"] == "error")
        assert error["detail"] == "Доска только для просмотра"
        assert room.objects == {}
        await room.handle(guest, json.dumps({"type": "cursor", "x": 3, "y": 4}))
        cursor = next(item for item in _drain(owner) if item["type"] == "cursor")
        assert cursor["x"] == 3

    asyncio.run(run())


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


def test_point_and_vertex_names_are_stored():
    async def run():
        room = _room()
        teacher = RoomClient(1, "Учитель", "teacher", trusted=True)
        await room.join(teacher)
        shape = {
            "id": "fig", "type": "shape", "x": 0, "y": 0, "w": 100, "h": 80, "rotation": 0,
            "props": {"shape": "polygon", "fill": "#fff"},
        }
        point = {
            "id": "p1", "type": "point", "x": 120.5, "y": 80.2, "w": 8, "h": 8, "rotation": 0,
            "props": {
                "letter": "A",
                "sub": "1",
                "cross": [{"id": "fig", "edge": 0}, {"id": "seg", "edge": 1}],
            },
        }
        await room.handle(teacher, json.dumps({"type": "upsert", "opId": 1, "object": shape}))
        await room.handle(teacher, json.dumps({"type": "upsert", "opId": 2, "object": point}))
        await room.handle(teacher, json.dumps({
            "type": "patch", "opId": 3, "id": "fig",
            "set": {"props": {
                "names": [{"letter": "B", "sub": "2"}, None, {"letter": "C", "sub": ""}],
                "verts": [[0, 0], [100, 50], [10, 100]],
            }},
        }))
        await room.handle(teacher, json.dumps({
            "type": "patch", "opId": 4, "id": "p1", "set": {"props": {"cross": None}},
        }))

        assert room.objects["p1"]["props"]["letter"] == "A"
        assert room.objects["p1"]["props"]["sub"] == "1"
        assert room.objects["p1"]["props"]["cross"] is None
        assert room.objects["fig"]["props"]["shape"] == "polygon"
        assert room.objects["fig"]["props"]["names"][1] is None
        assert room.objects["fig"]["props"]["names"][2] == {"letter": "C", "sub": ""}
        assert room.objects["fig"]["props"]["verts"] == [[0, 0], [100, 50], [10, 100]]

    asyncio.run(run())
