"""Теория раскладывается на доску разными объектами по виду блока."""
from services.theory_board import layout_theory


CONTENT = """# Квадратные уравнения

Дискриминант считается так.

$$b^2-4ac$$

```geogebra
{"app":"geometry","height":400,"commands":["SetPerspective(\\"G\\")","A = (0, 0)","c = Circle(A, 2)"]}
```

Дальше текст.
"""


def test_blocks_become_different_board_objects() -> None:
    objects = layout_theory(7, CONTENT)
    kinds = [(obj["type"], obj["props"]["block"]) for obj in objects]
    assert kinds == [
        ("text", "heading"),
        ("text", "paragraph"),
        ("text", "formula"),
        ("geogebra", "geogebra"),
        ("text", "paragraph"),
    ]

    heading, paragraph, formula, figure, tail = objects
    assert heading["props"]["fontSize"] > paragraph["props"]["fontSize"]
    assert heading["h"] <= paragraph["h"] or heading["props"]["text"] == "Квадратные уравнения"
    assert formula["props"]["text"] == "$$b^2-4ac$$"
    assert formula["h"] > 90
    assert figure["props"]["appName"] == "geometry"
    assert figure["props"]["ggbBase64"] == ""
    assert any("Circle" in command for command in figure["props"]["commands"])
    assert figure["w"] < paragraph["w"]
    assert figure["h"] == 400
    assert [obj["id"] for obj in objects] == [f"theory-7-{index}" for index in range(5)]
    assert all(objects[index]["y"] < objects[index + 1]["y"] for index in range(4))
    assert tail["props"]["text"] == "Дальше текст."
    assert all(obj["props"]["theoryId"] == 7 for obj in objects)
