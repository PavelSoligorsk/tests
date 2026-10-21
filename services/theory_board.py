"""Раскладка теории на объекты доски. Вид объекта зависит от блока текста."""
from __future__ import annotations

import math
import re

from services.geogebra_builder import geogebra_builder

PLACEHOLDER = re.compile(r"\{\{geogebra:(\d+)\}\}")
FORMULA = re.compile(r"\$\$([\s\S]+?)\$\$")
HEADING = re.compile(r"^(#{1,3})\s+(.+?)\s*$")

GAP = 28
X = 48

BLOCK_STYLE = {
    "heading": {"w": 820, "fontSize": 32, "min_h": 72, "line_px": 40, "max_h": 160},
    "paragraph": {"w": 760, "fontSize": 18, "min_h": 72, "line_px": 28, "max_h": 420},
    "formula": {"w": 760, "fontSize": 26, "min_h": 96, "line_px": 40, "max_h": 280},
}
GEOGEBRA_W = 560


def layout_theory(theory_id: int, content: str) -> list[dict]:
    cleaned, figures = geogebra_builder.process_text(content or "")
    by_id = {figure["id"]: figure for figure in figures}
    objects: list[dict] = []
    y = 40
    index = 0

    def add(obj: dict) -> None:
        nonlocal y, index
        obj["id"] = f"theory-{theory_id}-{index}"
        obj["y"] = y
        objects.append(obj)
        y += obj["h"] + GAP
        index += 1

    parts = PLACEHOLDER.split(cleaned)
    for part_index, part in enumerate(parts):
        if part_index % 2 == 1:
            figure = by_id.get(int(part))
            if figure is not None:
                add(_geogebra(theory_id, figure))
            continue
        for block in _text_blocks(part):
            add(_text(theory_id, block["kind"], block["text"]))
    return objects


def _text_blocks(segment: str) -> list[dict]:
    found: list[dict] = []
    for piece in FORMULA.split(segment):
        if not piece or not piece.strip():
            continue
        if piece is not segment and _is_formula_piece(segment, piece):
            found.append({"kind": "formula", "text": piece.strip()})
            continue
        for para in re.split(r"\n\s*\n", piece):
            para = para.strip()
            if not para:
                continue
            lines = para.splitlines()
            heading = HEADING.match(lines[0])
            if heading:
                found.append({"kind": "heading", "text": heading.group(2).strip()})
                rest = "\n".join(lines[1:]).strip()
                if rest:
                    found.append({"kind": "paragraph", "text": rest})
            else:
                found.append({"kind": "paragraph", "text": para})
    return found


def _is_formula_piece(segment: str, piece: str) -> bool:
    """FORMULA.split отдаёт и текст, и тело формулы. Тело — то, что стояло между $$."""
    return f"$${piece}$$" in segment


def _text(theory_id: int, kind: str, text: str) -> dict:
    style = BLOCK_STYLE[kind]
    shown = f"$${text}$$" if kind == "formula" else text
    return {
        "type": "text",
        "x": X,
        "w": style["w"],
        "h": _height(shown, style),
        "rotation": 0,
        "props": {
            "block": kind,
            "text": shown,
            "fontSize": style["fontSize"],
            "theoryId": theory_id,
        },
    }


def _geogebra(theory_id: int, figure: dict) -> dict:
    height = _geogebra_height(figure.get("height"))
    app = figure.get("app") or "geometry"
    return {
        "type": "geogebra",
        "x": X,
        "w": GEOGEBRA_W,
        "h": height,
        "rotation": 0,
        "props": {
            "block": "geogebra",
            "appName": "graphing" if app == "graphing" else "geometry",
            "templateId": "",
            "ggbBase64": "",
            "commands": list(figure.get("commands") or []),
            "theoryId": theory_id,
        },
    }


def _height(text: str, style: dict) -> int:
    lines = 0
    for line in text.splitlines() or [""]:
        lines += max(1, math.ceil(len(line) / 48))
    return min(style["max_h"], max(style["min_h"], lines * style["line_px"] + 24))


def _geogebra_height(value) -> int:
    try:
        height = int(str(value))
    except (TypeError, ValueError):
        height = 400
    return min(640, max(240, height))
