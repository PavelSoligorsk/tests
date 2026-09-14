"""Сборка GeoGebra из кусков YAML и inline-блоков в тексте."""
from __future__ import annotations

import re

import pytest

from services.geogebra_builder import GeoGebraBuilder, geogebra_builder


def test_render_stack_and_extra() -> None:
    spec = {
        "app": "geometry",
        "height": 400,
        "stack": [
            {"use": "view_2d", "params": {"axes": True, "grid": False}},
            {"use": "point", "params": {"name": "A", "at": "(2, 0)"}},
            {"use": "circle", "params": {"name": "c", "center": "A", "r": 3}},
        ],
        "extra": [
            'SetColor(c, "#3b82f6")',
            "ShowLabel(A, true)",
            "api.eval('hack')",
            "SetColor(Z, \"#000000\")",
        ],
    }
    rendered = geogebra_builder.render_spec(spec)
    assert rendered is not None
    assert rendered["app"] == "geometry"
    assert rendered["height"] == "400"
    cmds = rendered["commands"]
    assert cmds[0] == 'SetPerspective("G")'
    assert cmds.count('SetPerspective("G")') == 1
    assert "A = (2, 0)" in cmds
    assert "c = Circle(A, 3)" in cmds
    assert 'SetColor(c, "#3b82f6")' in cmds
    assert "ShowLabel(A, true)" in cmds
    assert not any("api.eval" in c for c in cmds)
    assert not any("SetColor(Z" in c for c in cmds)


def test_midpoint_piece_and_catalog_commands() -> None:
    rendered = geogebra_builder.render_spec({
        "stack": [
            {"use": "point", "params": {"name": "A", "at": "(0,0)"}},
            {"use": "point", "params": {"name": "B", "at": "(2,0)"}},
            {"use": "midpoint", "params": {"name": "M", "a": "A", "b": "B"}},
        ],
        "extra": [
            "PerpendicularBisector(A, B)",
            'Execute("Delete(A)")',
            "Точка(A)",
        ],
    })
    assert rendered is not None
    assert "M = Midpoint(A, B)" in rendered["commands"]
    assert "PerpendicularBisector(A, B)" in rendered["commands"]
    assert not any("Execute" in c for c in rendered["commands"])
    assert not any("Точка" in c for c in rendered["commands"])
    assert "Midpoint" in geogebra_builder.extra_commands
    assert "Prism" in geogebra_builder.extra_commands
    assert "Execute" in geogebra_builder.forbidden


def test_drops_broken_prism_extra_that_blanked_applet() -> None:
    rendered = geogebra_builder.render_spec({
        "app": "3d",
        "stack": [{"use": "view_3d", "params": {}}],
        "extra": [
            "ABC = RegularPolygon(6, 6, 3)",
            "D = (3, 10.3923, 0)",
            "Prism = Prism(ABC, D)",
            "AD = Segment(A, D)",
            "Text1 = Text(a = 6, (3, 0, -1))",
            "SetPerspective(Prism, 150, 30)",
            'Text2 = Text("h = 8", (3, 8, 0))',
        ],
    })
    assert rendered is not None
    cmds = rendered["commands"]
    assert not any("RegularPolygon" in c for c in cmds)
    assert "ABC = Polygon(A, B, 3)" in cmds
    assert not any("SetPerspective(Prism" in c for c in cmds)
    assert 'Text1 = Text("a = 6", (3, 0, -1))' in cmds
    # A теперь объявлена починкой RegularPolygon(6, 6, 3), так что отрезок валиден.
    assert "AD = Segment(A, D)" in cmds
    assert any("SetPerspective(\"T\")" in c for c in cmds)
    assert 'Text2 = Text("h = 8", (3, 8, 0))' in cmds
    assert "D = (3, 10.3923, 0)" in cmds


def test_repairs_numeric_regular_polygon_so_prism_is_complete() -> None:
    rendered = geogebra_builder.render_spec({
        "app": "3d",
        "stack": [{"use": "view_3d", "params": {}}],
        "extra": [
            "base = RegularPolygon(6, 6, 3)",
            "prism = Prism(base, 8)",
            "label = Text(a = 6, (0, 0, 0))",
            "A = (0, 0, 0)",
            "B = (6, 0, 0)",
            "C = (3, 5.196, 0)",
            "A_top = (0, 0, 8)",
            "B_top = (6, 0, 8)",
            "C_top = (3, 5.196, 8)",
            "AB = Segment(A, B)",
            "AA_top = Segment(A, A_top)",
            'ABtop = Segment(A_top, B_top)',
        ],
    })
    assert rendered is not None
    cmds = rendered["commands"]
    assert "base = Polygon(A, B, 3)" in cmds
    assert "prism = Prism(base, 8)" in cmds
    assert 'label = Text("a = 6", (0, 0, 0))' in cmds
    assert "A_top = (0, 0, 8)" in cmds
    assert "ABtop = Segment(A_top, B_top)" in cmds


def test_quotes_text_and_rewrites_zero_height_prism_to_pyramid_base() -> None:
    rendered = geogebra_builder.render_spec({
        "app": "3d",
        "stack": [{"use": "view_3d"}],
        "extra": [
            "base_A = (0, 0, 0)",
            "base_B = (6, 0, 0)",
            "base_base = RegularPolygon(base_A, base_B, 4)",
            "base = Prism(base_base, 0)",
            "apex = (3, 3, 5)",
            "pyramid = Pyramid(base, apex)",
            "volume_text = Text(V = 60, (0, 0, 6))",
            "S_label = Text(S_{бок} = 144, (0, 0, 7))",
        ],
    })
    cmds = rendered["commands"]
    assert not any("Prism(base_base, 0)" in c for c in cmds)
    # base_A / base_B — литералы координат, строчное имя дало бы вектор.
    assert "Pt_base_A = (0, 0, 0)" in cmds
    assert "Pt_apex = (3, 3, 5)" in cmds
    assert "pyramid = Pyramid(base_base, Pt_apex)" in cmds
    assert 'volume_text = Text("V = 60", (0, 0, 6))' in cmds
    assert 'S_label = Text("S_{бок} = 144", (0, 0, 7))' in cmds


def test_regular_prism_piece() -> None:
    rendered = geogebra_builder.render_spec({
        "stack": [
            {"use": "view_3d"},
            {"use": "regular_prism", "params": {"a": 6, "h": 8, "n": 3}},
        ],
    })
    assert rendered is not None
    cmds = "\n".join(rendered["commands"])
    # В 3D правильное основание строится Sequence — Polygon(P, Q, n) там не работает.
    assert "pr_base = Polygon(Sequence(" in cmds
    assert "pr = Prism(pr_base, 8)" in cmds


def test_drop_orphan_pyramid_vertices() -> None:
    rendered = geogebra_builder.render_spec({
        "app": "3d",
        "stack": [
            {"use": "view_3d"},
            {"use": "regular_pyramid", "params": {"a": 6, "h": 5, "n": 4}},
        ],
        "extra": [
            "A = (-3, -3, 0)",
            "B = (3, -3, 0)",
            "C = (3, 3, 0)",
            "D = (-3, 3, 0)",
            "V = (0, 0, 5)",
            'label_a = Text("a = 6", (3, -3, 0))',
            "ShowLabel(A, true)",
            "ShowLabel(V, true)",
        ],
    })
    assert rendered is not None
    cmds = rendered["commands"]
    assert not any(re.match(r"^[ABCDV] =", c) for c in cmds)
    assert not any("ShowLabel(A" in c or "ShowLabel(V" in c for c in cmds)
    assert any("Pyramid(" in c for c in cmds)
    assert any("label_a = Text" in c for c in cmds)


def test_rename_reserved_cylinder() -> None:
    rendered = geogebra_builder.render_spec({
        "app": "3d",
        "stack": [{"use": "view_3d"}],
        "extra": [
            "Cylinder = Cylinder((0,0,0), (0,0,5), 3)",
            'Label = Text("r = 3", (3,0,0))',
        ],
    })
    assert rendered is not None
    cmds = rendered["commands"]
    assert any(c.startswith("obj_cylinder = Cylinder(") for c in cmds)
    assert not any(c.startswith("Cylinder =") for c in cmds)
    assert any(c.startswith("obj_label = Text(") for c in cmds)


def test_parallelepiped_keeps_diagonal_points() -> None:
    rendered = geogebra_builder.render_spec({
        "stack": [
            {"use": "view_3d"},
            {"use": "parallelepiped", "params": {"a": 2, "b": 3, "c": 6}},
        ],
        "extra": [
            "d = Segment(A, G)",
            "A = (0, 0, 0)",
            "G = (2, 3, 6)",
            'd_label = Text("d = 7", (3, 3.5, 3))',
        ],
    })
    assert rendered is not None
    cmds = rendered["commands"]
    assert "A = (0, 0, 0)" in cmds
    assert "G = (2, 3, 6)" in cmds
    assert cmds.count("A = (0, 0, 0)") == 1
    assert "obj_d = Segment(A, G)" in cmds


def test_strips_text_named_kwargs() -> None:
    rendered = geogebra_builder.render_spec({
        "app": "3d",
        "stack": [
            {"use": "view_3d"},
            {"use": "parallelepiped", "params": {"a": 2, "b": 3, "c": 6}},
        ],
        "extra": [
            "d = Segment(A, G)",
            'SetColor(d, "#0066ff")',
            'Text("d = 7", (1, 1.5, 3), fontSize=3)',
        ],
    })
    assert rendered is not None
    cmds = rendered["commands"]
    assert 'Text("d = 7", (1, 1.5, 3))' in cmds
    assert not any("fontSize" in c for c in cmds)
    assert 'SetColor(obj_d, "#0066ff")' in cmds


def test_2d_always_gets_perspective_g() -> None:
    rendered = geogebra_builder.render_spec({
        "app": "geometry",
        "stack": [
            {"use": "point", "params": {"name": "A", "at": "(0,0)"}},
            {"use": "circle", "params": {"name": "c", "center": "A", "r": 2}},
        ],
        "extra": ['SetPerspective("T")', 'SetPerspective("2")'],
    })
    assert rendered is not None
    cmds = rendered["commands"]
    assert cmds[0] == 'SetPerspective("G")'
    assert not any('SetPerspective("T")' in c for c in cmds)
    assert not any('SetPerspective("2")' in c for c in cmds)
    assert cmds.count('SetPerspective("G")') == 1
    assert "ZoomIn(-3, -3, 3, 3)" in cmds


def test_2d_auto_fits_bounds_when_fit_piece_missing() -> None:
    rendered = geogebra_builder.render_spec({
        "app": "geometry",
        "stack": [
            {"use": "view_2d"},
            {"use": "point", "params": {"name": "A", "at": "(0, 0)"}},
            {"use": "point", "params": {"name": "B", "at": "(13, 0)"}},
            {"use": "point", "params": {"name": "C", "at": "(10, 6)"}},
            {"use": "point", "params": {"name": "D", "at": "(3, 6)"}},
            {"use": "polygon", "params": {"name": "trap", "vertices": "A, B, C, D"}},
        ],
    })
    assert rendered is not None
    cmds = rendered["commands"]
    assert cmds[-1] == "ZoomIn(-1, -1, 14, 7)"


def test_setfilling_hex_becomes_color_and_opacity() -> None:
    rendered = geogebra_builder.render_spec({
        "app": "geometry",
        "stack": [
            {"use": "view_2d"},
            {"use": "point", "params": {"name": "A", "at": "(0,0)"}},
            {"use": "point", "params": {"name": "B", "at": "(13,0)"}},
            {"use": "point", "params": {"name": "C", "at": "(10,6)"}},
            {"use": "point", "params": {"name": "D", "at": "(3,6)"}},
            {"use": "polygon", "params": {"name": "trapezoid", "vertices": "A, B, C, D"}},
        ],
        "extra": [
            'S = Text("S = 60", (7, 3))',
            'SetFilling(trapezoid, "#3b82f6")',
        ],
    })
    assert rendered is not None
    cmds = rendered["commands"]
    assert 'SetColor(trapezoid, "#3b82f6")' in cmds
    assert "SetFilling(trapezoid, 0.3)" in cmds
    assert not any('SetFilling(trapezoid, "#3b82f6")' in c for c in cmds)


def test_strips_text_alignment_and_puts_zoom_last() -> None:
    rendered = geogebra_builder.render_spec({
        "app": "geometry",
        "stack": [
            {"use": "view_2d"},
            {"use": "point", "params": {"name": "A", "at": "(0, 0)"}},
            {"use": "point", "params": {"name": "B", "at": "(13, 0)"}},
            {"use": "point", "params": {"name": "C", "at": "(10, 6)"}},
            {"use": "point", "params": {"name": "D", "at": "(3, 6)"}},
            {"use": "polygon", "params": {"name": "trapezoid", "vertices": "A, B, C, D"}},
            {"use": "fit_2d", "params": {"xmin": -1, "ymin": -2, "xmax": 14, "ymax": 7}},
        ],
        "extra": [
            'Text("a = 7", (6.5, -0.5), 0.5, "top")',
            'Text("h = 6", (14, 3), 0.5, "right")',
        ],
    })
    assert rendered is not None
    cmds = rendered["commands"]
    assert 'Text("a = 7", (6.5, -0.5))' in cmds
    assert 'Text("h = 6", (14, 3))' in cmds
    assert not any('"top"' in c or '"right"' in c for c in cmds)
    assert not any(c == "ZoomIn(1)" for c in cmds)
    assert cmds[-1].startswith("ZoomIn(")
    assert cmds[-1] == "ZoomIn(-1, -1, 14, 7)"


def test_unknown_piece_skipped() -> None:
    rendered = geogebra_builder.render_spec({
        "stack": [
            {"use": "no_such_piece"},
            {"use": "point", "params": {"name": "P", "at": "(1,1)"}},
        ],
        "extra": [],
    })
    assert rendered is not None
    assert "P = (1,1)" in rendered["commands"]


def test_process_text_multiple_inline_figures() -> None:
    text = (
        "Сначала окружность:\n"
        "```geogebra\n"
        '{"app":"geometry","height":400,"stack":['
        '{"use":"view_2d","params":{}},'
        '{"use":"circle","params":{"name":"c","center":"(0,0)","r":2}}'
        '],"extra":[]}\n'
        "```\n"
        "Потом график:\n"
        "```geogebra\n"
        '{"app":"graphing","height":450,"stack":['
        '{"use":"view_graph","params":{}},'
        '{"use":"function","params":{"name":"f","expr":"x^2"}}'
        '],"extra":[]}\n'
        "```\n"
        "Конец."
    )
    cleaned, figures = geogebra_builder.process_text(text)
    assert "{{geogebra:0}}" in cleaned
    assert "{{geogebra:1}}" in cleaned
    assert cleaned.index("{{geogebra:0}}") < cleaned.index("Потом график")
    assert cleaned.index("{{geogebra:1}}") < cleaned.index("Конец.")
    assert "```geogebra" not in cleaned
    assert len(figures) == 2
    assert figures[0]["id"] == 0
    assert figures[1]["app"] == "graphing"
    assert any("Circle" in c for c in figures[0]["commands"])
    assert any("x^2" in c for c in figures[1]["commands"])


def test_process_text_legacy_jsx() -> None:
    text = 'Смотри\n<GeoGebra setup={`A = (0,0)\nB = (1,0)`} height="300" />\nдальше'
    cleaned, figures = geogebra_builder.process_text(text)
    assert "{{geogebra:0}}" in cleaned
    assert "GeoGebra" not in cleaned
    assert figures[0]["commands"] == ["A = (0,0)", "B = (1,0)"]
    assert figures[0]["height"] == "300"


def test_fit_2d_zooms_to_bounds() -> None:
    rendered = geogebra_builder.render_spec({
        "app": "geometry",
        "stack": [
            {"use": "view_2d"},
            {"use": "point", "params": {"name": "A", "at": "(0, 0)"}},
            {"use": "point", "params": {"name": "B", "at": "(13, 0)"}},
            {"use": "point", "params": {"name": "C", "at": "(10, 6)"}},
            {"use": "point", "params": {"name": "D", "at": "(3, 6)"}},
            {"use": "polygon", "params": {"name": "trap", "vertices": "A, B, C, D"}},
            {"use": "fit_2d", "params": {"xmin": -1, "ymin": -1, "xmax": 14, "ymax": 8}},
        ],
    })
    assert rendered is not None
    cmds = rendered["commands"]
    assert cmds[0] == 'SetPerspective("G")'
    assert "trap = Polygon(A, B, C, D)" in cmds
    assert "ZoomIn(-1, -1, 14, 7)" in cmds
    assert cmds[-1] == "ZoomIn(-1, -1, 14, 7)"


def test_parallelogram_piece() -> None:
    rendered = geogebra_builder.render_spec({
        "app": "geometry",
        "stack": [
            {"use": "view_2d"},
            {"use": "parallelogram", "params": {"a": 8, "h": 5, "s": 2}},
        ],
    })
    assert rendered is not None
    cmds = rendered["commands"]
    assert "A = (0, 0)" in cmds
    assert "B = (8, 0)" in cmds
    assert "D = (2, 5)" in cmds
    assert "C = (8 + 2, 5)" in cmds
    assert "pg = Polygon(A, B, C, D)" in cmds
    assert cmds[-1] == "ZoomIn(-1, -1, 11, 6)"


PLANIMETRY_PIECES = [
    ("square", {"a": 6}, "Polygon(A, B, C, D)"),
    ("rectangle", {"a": 8, "b": 5}, "Polygon(A, B, C, D)"),
    ("parallelogram", {"a": 8, "h": 5, "s": 2}, "Polygon(A, B, C, D)"),
    ("rhombus", {"p": 8, "q": 6}, "Polygon(A, B, C, D)"),
    ("trapezoid", {"a": 13, "b": 7, "h": 6}, "Polygon(A, B, C, D)"),
    ("right_trapezoid", {"a": 10, "b": 6, "h": 5}, "Polygon(A, B, C, D)"),
    ("right_triangle", {"a": 6, "b": 8}, "Polygon(A, B, C)"),
    ("isosceles_triangle", {"a": 8, "h": 6}, "Polygon(A, B, C)"),
    ("equilateral_triangle", {"a": 6}, "Polygon(A, B, C)"),
    ("triangle", {"bx": 8, "cx": -3, "cy": 4}, "Polygon(A, B, C)"),
    ("regular_ngon", {"a": 4, "n": 6}, "Polygon(A, B, 6)"),
    ("sector", {"r": 4, "alpha": 90}, "CircularSector(O, P, Q)"),
    ("circle_segment", {"r": 4, "alpha": 120}, "CircularArc(O, P, Q)"),
]


@pytest.mark.parametrize("piece,params,expected", PLANIMETRY_PIECES)
def test_planimetry_piece_renders_and_fits(piece, params, expected) -> None:
    rendered = geogebra_builder.render_spec({
        "app": "geometry",
        "stack": [{"use": "view_2d"}, {"use": piece, "params": params}],
    })
    assert rendered is not None, piece
    cmds = rendered["commands"]
    assert rendered["app"] == "geometry"
    assert cmds[0] == 'SetPerspective("G")'
    assert any(expected in c for c in cmds), cmds
    assert cmds[-1].startswith("ZoomIn(") and cmds[-1].count(",") == 3, cmds[-1]


def test_regular_ngon_fit_covers_whole_hexagon() -> None:
    rendered = geogebra_builder.render_spec({
        "app": "geometry",
        "stack": [{"use": "view_2d"}, {"use": "regular_ngon", "params": {"a": 4, "n": 6}}],
    })
    assert rendered is not None
    # Шестиугольник со стороной 4 занимает x -2..6, y 0..6.93 — кадр с запасом 1.
    assert rendered["commands"][-1] == "ZoomIn(-3, -1, 7, 7.93)"


def test_sector_fit_does_not_take_whole_circle() -> None:
    rendered = geogebra_builder.render_spec({
        "app": "geometry",
        "stack": [{"use": "view_2d"}, {"use": "sector", "params": {"r": 4, "alpha": 90}}],
    })
    assert rendered is not None
    cmds = rendered["commands"]
    assert "O = (0, 0)" in cmds
    assert cmds[-1] == "ZoomIn(-1, -1, 5, 5)"


def test_circle_segment_keeps_center_point() -> None:
    rendered = geogebra_builder.render_spec({
        "app": "geometry",
        "stack": [{"use": "view_2d"}, {"use": "circle_segment", "params": {"r": 4, "alpha": 120}}],
    })
    assert rendered is not None
    cmds = rendered["commands"]
    assert "O = (0, 0)" in cmds
    assert "seg_chord = Segment(P, Q)" in cmds


def test_circumcircle_fits_in_frame() -> None:
    rendered = geogebra_builder.render_spec({
        "app": "geometry",
        "stack": [
            {"use": "view_2d"},
            {"use": "right_triangle", "params": {"a": 6, "b": 8}},
            {"use": "circumcircle", "params": {"name": "circ"}},
        ],
    })
    assert rendered is not None
    # Описанная окружность прямоугольного треугольника 6x8: центр (3,4), R=5.
    assert rendered["commands"][-1] == "ZoomIn(-3, -2, 9, 10)"


def test_nested_call_in_extra_survives() -> None:
    rendered = geogebra_builder.render_spec({
        "app": "geometry",
        "stack": [
            {"use": "view_2d"},
            {"use": "triangle", "params": {"bx": 8, "cx": 3, "cy": 5}},
        ],
        "extra": [
            "foot = ClosestPoint(Line(A, B), C)",
            "drop = Segment(C, foot)",
        ],
    })
    assert rendered is not None
    cmds = rendered["commands"]
    assert "foot = ClosestPoint(Line(A, B), C)" in cmds
    assert "drop = Segment(C, foot)" in cmds


def test_hex_color_does_not_drop_command() -> None:
    rendered = geogebra_builder.render_spec({
        "app": "geometry",
        "stack": [
            {"use": "view_2d"},
            {"use": "triangle", "params": {"bx": 8, "cx": 3, "cy": 5}},
        ],
        "extra": ['SetColor(tri, "#ef4444")', 'SetColor(tri, "#abcdef")'],
    })
    assert rendered is not None
    cmds = rendered["commands"]
    assert 'SetColor(tri, "#ef4444")' in cmds
    assert 'SetColor(tri, "#abcdef")' in cmds


def test_single_letter_names_renamed_consistently() -> None:
    rendered = geogebra_builder.render_spec({
        "app": "geometry",
        "stack": [
            {"use": "view_2d"},
            {"use": "trapezoid", "params": {"a": 13, "b": 7, "h": 6}},
        ],
        "extra": [
            'a = Text("13", (6.5, -0.6))',
            "h = Segment(D, (3, 0))",
            'SetColor(h, "#ef4444")',
        ],
    })
    assert rendered is not None
    cmds = rendered["commands"]
    assert 'obj_a = Text("13", (6.5, -0.6))' in cmds
    assert "obj_h = Segment(D, (3, 0))" in cmds
    assert 'SetColor(obj_h, "#ef4444")' in cmds


def test_rename_skips_string_literals() -> None:
    rendered = geogebra_builder.render_spec({
        "app": "geometry",
        "stack": [{"use": "view_2d"}, {"use": "triangle"}],
        "extra": ["h = Segment(A, C)", 'Text("h", (1, 2))'],
    })
    assert rendered is not None
    assert 'Text("h", (1, 2))' in rendered["commands"]


def test_height_piece_builds_altitude() -> None:
    rendered = geogebra_builder.render_spec({
        "app": "geometry",
        "stack": [
            {"use": "view_2d"},
            {"use": "triangle", "params": {"bx": 8, "cx": 3, "cy": 5}},
            {"use": "height", "params": {"apex": "C"}},
        ],
    })
    assert rendered is not None
    cmds = rendered["commands"]
    assert "hgt_foot = ClosestPoint(Line(A, B), C)" in cmds
    assert "hgt = Segment(C, hgt_foot)" in cmds
    assert not any(c.startswith("PerpendicularLine") for c in cmds)


def test_diagonal_piece() -> None:
    rendered = geogebra_builder.render_spec({
        "app": "geometry",
        "stack": [
            {"use": "view_2d"},
            {"use": "square", "params": {"a": 6}},
            {"use": "diagonal", "params": {"name": "diag", "a": "A", "b": "C"}},
        ],
    })
    assert rendered is not None
    assert "diag = Segment(A, C)" in rendered["commands"]


def test_incircle_with_center_and_radius() -> None:
    rendered = geogebra_builder.render_spec({
        "app": "geometry",
        "stack": [
            {"use": "view_2d"},
            {"use": "triangle", "params": {"bx": 8, "cx": 3, "cy": 6}},
            {"use": "incircle", "params": {"name": "inc"}},
        ],
        "extra": ["O = Center(inc)", "rad = Segment(O, ClosestPoint(inc, A))"],
    })
    assert rendered is not None
    cmds = rendered["commands"]
    assert "inc = Incircle(A, B, C)" in cmds
    assert "O = Center(inc)" in cmds
    # rad — функция GeoGebra (радианы), имя переименовано.
    assert "obj_rad = Segment(O, ClosestPoint(inc, A))" in cmds


def test_unknown_nested_command_still_dropped() -> None:
    rendered = geogebra_builder.render_spec({
        "app": "geometry",
        "stack": [{"use": "view_2d"}, {"use": "triangle"}],
        "extra": ["bad = Segment(A, Execute(A))", "worse = Segment(A, Bogus(B))"],
    })
    assert rendered is not None
    assert not any("Execute" in c or "Bogus" in c for c in rendered["commands"])


def test_incircle_ngon_fits_square() -> None:
    rendered = geogebra_builder.render_spec({
        "app": "geometry",
        "stack": [
            {"use": "view_2d"},
            {"use": "square", "params": {"name": "sq", "a": 6}},
            {"use": "incircle_ngon", "params": {"poly": "sq"}},
        ],
    })
    assert rendered is not None
    # Вписанная окружность внутри квадрата: кадр по квадрату 0..6 плюс запас.
    assert rendered["commands"][-1] == "ZoomIn(-1, -1, 7, 7)"


def test_circumcircle_ngon_expands_frame() -> None:
    rendered = geogebra_builder.render_spec({
        "app": "geometry",
        "stack": [
            {"use": "view_2d"},
            {"use": "square", "params": {"name": "sq", "a": 6}},
            {"use": "circumcircle_ngon", "params": {"poly": "sq"}},
        ],
    })
    assert rendered is not None
    # Центр (3,3), R = 3*sqrt(2) ≈ 4.24 — окружность выходит за квадрат.
    assert rendered["commands"][-1] == "ZoomIn(-2.24, -2.24, 8.24, 8.24)"


def test_circumcircle_ngon_on_regular_hexagon() -> None:
    rendered = geogebra_builder.render_spec({
        "app": "geometry",
        "stack": [
            {"use": "view_2d"},
            {"use": "regular_ngon", "params": {"name": "hex", "a": 4, "n": 6}},
            {"use": "circumcircle_ngon", "params": {"poly": "hex"}},
        ],
    })
    assert rendered is not None
    cmds = rendered["commands"]
    # Vertex(hex, i) работает для любого многоугольника, независимо от имён вершин.
    assert "circ = Circle(Centroid(hex), Distance(Centroid(hex), Vertex(hex, 1)))" in cmds
    assert cmds[-1] == "ZoomIn(-3, -1.54, 7, 8.46)"


def test_geogebra_function_names_are_renamed() -> None:
    rendered = geogebra_builder.render_spec({
        "app": "geometry",
        "stack": [{"use": "view_2d"}, {"use": "triangle"}],
        "extra": ["alt = Segment(A, C)", 'SetColor(alt, "#ef4444")', "ln = Line(A, B)"],
    })
    assert rendered is not None
    cmds = rendered["commands"]
    assert "obj_alt = Segment(A, C)" in cmds
    assert 'SetColor(obj_alt, "#ef4444")' in cmds
    assert "obj_ln = Line(A, B)" in cmds


def test_dead_commands_are_rewritten() -> None:
    rendered = geogebra_builder.render_spec({
        "app": "geometry",
        "stack": [{"use": "view_2d"}, {"use": "triangle"}],
        "extra": ["cc = Circumcircle(A, B, C)", "hx = RegularPolygon(A, B, 6)"],
    })
    assert rendered is not None
    cmds = rendered["commands"]
    assert "cc = Circle(A, B, C)" in cmds
    assert "hx = Polygon(A, B, 6)" in cmds
    assert not any("Circumcircle" in c or "RegularPolygon" in c for c in cmds)


def test_catalog_includes_pieces() -> None:
    catalog = geogebra_builder.catalog_text()
    assert "parallelogram:" in catalog
    assert "parallelepiped:" in catalog
    assert "rhombus:" in catalog
    assert "trapezoid:" in catalog
    assert "sector:" in catalog
    assert "regular_ngon:" in catalog
    assert "view_2d:" in catalog
    assert "sphere:" in catalog
    assert "slider_3d:" in catalog
    assert "midpoint:" in catalog
    assert "cube:" in catalog


def test_reload_from_custom_dir(tmp_path) -> None:
    pieces = tmp_path / "pieces"
    pieces.mkdir()
    (pieces / "dot.yml").write_text(
        "id: dot\nsummary: Точка-тест.\nparams:\n  name: {default: D}\n"
        "creates: ['{{name}}']\ncommands:\n  - '{{name}} = (0,0)'\n",
        encoding="utf-8",
    )
    builder = GeoGebraBuilder(pieces_dir=pieces, whitelist_path=tmp_path / "missing.yml")
    rendered = builder.render_spec({"stack": [{"use": "dot", "params": {"name": "Q"}}]})
    assert rendered is not None
    assert "Q = (0,0)" in rendered["commands"]
