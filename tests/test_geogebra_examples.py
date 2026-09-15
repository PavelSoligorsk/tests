"""Тесты статических примеров GeoGebra и парсера stage1."""

from services.geogebra_builder import geogebra_builder
from services.geogebra_examples import (
    catalog_text,
    clear_catalog_cache,
    list_catalog,
    load_examples,
    parse_figure_route,
)


def setup_function() -> None:
    clear_catalog_cache()


def test_catalog_has_planimetry() -> None:
    cat = list_catalog()
    assert "Планиметрия" in cat
    assert "Трапеция" in cat["Планиметрия"]
    assert "Планиметрия" in catalog_text()


def test_load_examples_trapezoid_has_commands() -> None:
    text = load_examples("Планиметрия", "Трапеция")
    assert "### Пример" in text
    assert "```geogebra" in text
    assert '"commands"' in text
    assert "Polygon" in text
    assert '"use"' not in text
    assert "stack" not in text


def test_load_examples_unknown_section_falls_back() -> None:
    text = load_examples("Планиметрия", "НесуществующийРазделXYZ")
    # fallback на первую секцию темы — не пусто
    assert text
    assert "```geogebra" in text


def test_load_examples_unknown_topic_empty() -> None:
    assert load_examples("НетТакойТемы", "Трапеция") == ""


def test_parse_figure_route_json() -> None:
    d = parse_figure_route(
        '{"needs_figure": true, "topic": "Планиметрия", "section": "Трапеция"}'
    )
    assert d == {
        "needs_figure": True,
        "topic": "Планиметрия",
        "section": "Трапеция",
    }


def test_parse_figure_route_false() -> None:
    d = parse_figure_route('```json\n{"needs_figure": false}\n```')
    assert d == {"needs_figure": False, "topic": "", "section": ""}


def test_parse_figure_route_fenced() -> None:
    d = parse_figure_route(
        '```json\n{"needs_figure": true, "topic": "Стереометрия", "section": "Пирамида"}\n```'
    )
    assert d is not None
    assert d["topic"] == "Стереометрия"
    assert d["section"] == "Пирамида"


def test_parse_figure_route_plain_text_is_none() -> None:
    assert parse_figure_route("Перенеси 5 вправо и раздели на 2.") is None
    assert parse_figure_route('{"foo": 1}') is None


def test_render_commands_only_spec() -> None:
    rendered = geogebra_builder.render_spec({
        "app": "geometry",
        "height": 400,
        "commands": [
            'SetPerspective("G")',
            "A = (0, 0)",
            "B = (4, 0)",
            "c = Circle(A, 2)",
        ],
    })
    assert rendered is not None
    assert rendered["app"] == "geometry"
    assert any("Circle" in c for c in rendered["commands"])
    assert any(c.startswith("ZoomIn(") for c in rendered["commands"])


def test_process_text_commands_fence() -> None:
    text = (
        "Смотри:\n"
        "```geogebra\n"
        '{"app":"geometry","height":400,"commands":["A = (0, 0)","B = (3, 0)","s = Segment(A, B)"]}\n'
        "```\n"
        "Готово."
    )
    cleaned, figures = geogebra_builder.process_text(text)
    assert "{{geogebra:0}}" in cleaned
    assert figures and any("Segment" in c for c in figures[0]["commands"])
