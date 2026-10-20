"""Проверка объектов доски. Без базы и без сети: им пользуются и сервис, и живая комната."""
from __future__ import annotations

import json
import math
import uuid
from datetime import datetime
from typing import Any, Optional

OBJECT_TYPES = {"sticky", "text", "shape", "arrow", "draw", "image", "geogebra", "task"}
# Поле props, которое видит только учитель: ответ и решение задания.
PRIVATE_PROP = "teacherOnly"
GEOMETRY = ("x", "y", "w", "h", "rotation")
MAX_OBJECTS = 10_000
MAX_DOCUMENT_BYTES = 8 * 1024 * 1024
MAX_DEPTH = 32
LASER_FADE_MS = 2000
MAX_LASER_POINTS = 2000


class SceneError(ValueError):
    pass


def clean_board_title(value: Any) -> str:
    if not isinstance(value, str):
        raise SceneError("Нужно название")
    cleaned = value.strip()
    if not cleaned:
        raise SceneError("Нужно название")
    if len(cleaned) > 255:
        raise SceneError("Название длиннее 255 символов")
    return cleaned


def finite(value: Any, label: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise SceneError(f"Поле {label} должно быть конечным числом")
    return value


def validate_camera(camera: Any) -> dict:
    if not isinstance(camera, dict):
        raise SceneError("camera должен быть объектом")
    return {
        "x": finite(camera.get("x"), "camera.x"),
        "y": finite(camera.get("y"), "camera.y"),
        "zoom": finite(camera.get("zoom"), "camera.zoom"),
    }


def validate_object(raw: Any, label: str = "object") -> dict:
    if not isinstance(raw, dict):
        raise SceneError(f"{label} должен быть объектом")
    object_id = raw.get("id")
    object_type = raw.get("type")
    if not isinstance(object_id, str) or not object_id:
        raise SceneError(f"У {label} нужен строковый id")
    if object_type not in OBJECT_TYPES:
        raise SceneError(f"Неизвестный type у {label}")
    props = raw.get("props", {})
    if not isinstance(props, dict):
        raise SceneError(f"{label}.props должен быть объектом")
    assert_finite_tree(props, f"{label}.props")
    clean = {"id": object_id, "type": object_type}
    for key in GEOMETRY:
        clean[key] = finite(raw.get(key), f"{label}.{key}")
    clean["props"] = props
    return clean


def validate_patch(raw: Any) -> dict:
    if not isinstance(raw, dict) or not raw:
        raise SceneError("set должен быть непустым объектом")
    clean: dict[str, Any] = {}
    for key, value in raw.items():
        if key in GEOMETRY:
            clean[key] = finite(value, f"set.{key}")
        elif key == "props":
            if not isinstance(value, dict):
                raise SceneError("set.props должен быть объектом")
            assert_finite_tree(value, "set.props")
            clean["props"] = value
        else:
            raise SceneError(f"Поле {key} нельзя менять через patch")
    return clean


def validate_laser(message: dict) -> dict:
    """Полоска указки. В документ не входит: клиенты сами гасят её за LASER_FADE_MS."""
    raw = message.get("points")
    if not isinstance(raw, list) or len(raw) < 2:
        raise SceneError("У указки нужно хотя бы две точки")
    if len(raw) > MAX_LASER_POINTS:
        raise SceneError(f"У указки не больше {MAX_LASER_POINTS} точек")
    points = []
    for index, point in enumerate(raw):
        if not isinstance(point, dict):
            raise SceneError(f"points[{index}] должен быть объектом")
        points.append({
            "x": finite(point.get("x"), f"points[{index}].x"),
            "y": finite(point.get("y"), f"points[{index}].y"),
        })
    color = message.get("color", "#fde047")
    if not isinstance(color, str) or not color.strip() or len(color) > 32:
        raise SceneError("color указки — короткая строка")
    width = message.get("width", 18)
    width = finite(width, "width")
    if width <= 0 or width > 80:
        raise SceneError("width указки от 0 до 80")
    return {"points": points, "color": color.strip(), "width": width, "fadeMs": LASER_FADE_MS}


def public_object(obj: dict) -> dict:
    props = obj.get("props")
    if not isinstance(props, dict) or PRIVATE_PROP not in props:
        return obj
    return {**obj, "props": {key: value for key, value in props.items() if key != PRIVATE_PROP}}


def public_op(op: dict) -> dict:
    """Операция в том виде, в каком её получает ученик."""
    kind = op.get("type")
    if kind == "upsert" and isinstance(op.get("object"), dict):
        return {**op, "object": public_object(op["object"])}
    if kind == "patch" and isinstance(op.get("set"), dict):
        changes = op["set"]
        props = changes.get("props")
        if isinstance(props, dict) and PRIVATE_PROP in props:
            return {**op, "set": {**changes, "props": {k: v for k, v in props.items() if k != PRIVATE_PROP}}}
    return op


def has_private(op: dict) -> bool:
    return public_op(op) is not op


def assert_finite_tree(value: Any, label: str, depth: int = 0) -> None:
    if depth > MAX_DEPTH:
        raise SceneError(f"Слишком глубокая вложенность в {label}")
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        if not math.isfinite(float(value)):
            raise SceneError(f"Поле {label} должно быть конечным числом")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            assert_finite_tree(item, f"{label}.{key}", depth + 1)
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            assert_finite_tree(item, f"{label}[{index}]", depth + 1)


def iso_time(value: Optional[datetime]) -> str:
    moment = value or datetime.utcnow()
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def json_size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def image_ids(objects: list[dict]) -> list[uuid.UUID]:
    found: list[uuid.UUID] = []
    for obj in objects:
        parsed = image_file_id(obj)
        if parsed is not None:
            found.append(parsed)
    return found


def image_file_id(obj: dict) -> Optional[uuid.UUID]:
    if obj.get("type") != "image":
        return None
    return parse_uuid((obj.get("props") or {}).get("fileId"))


def parse_uuid(value: Any) -> Optional[uuid.UUID]:
    if not isinstance(value, str) or not value:
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None
