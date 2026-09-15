# Промт для Grok: подсистема GeoGebra

Скопируй всё, что ниже разделителя, в новый чат.

---

Ты продолжаешь работу над подсистемой генерации чертежей GeoGebra в проекте FastAPI (`d:\python\fastapi`).

## Как устроено

- `geogebra/examples/` — **статические few-shot** по теме/разделу. `index.yml` — каталог для stage1. Файлы `examples/{topic_slug}/{section_slug}.yml` содержат `commands:` (сырой GeoGebra Script), **без** `use`/`stack`.
- `services/geogebra_examples.py` — `list_catalog()`, `load_examples(topic, section)`, `parse_figure_route(text)`.
- `geogebra/pieces/*.yml` — внутренние куски для сборки (бэкенд); AI их **не** видит в промпте stage2.
- `geogebra/commands.yml` — whitelist команд.
- `services/geogebra_builder.py` — `render_spec` принимает JSON с полем `commands` (основной формат) или legacy `stack`/`extra`; починка имён, автокадрирование.
- Hint/solution — **двухэтапные**:
  1. `route_or_answer_*` — либо финальный текст без чертежа, либо `{"needs_figure":true,"topic":"...","section":"..."}`.
  2. Если нужен чертёж — `load_examples` + `get_hint`/`get_solution(..., examples=..., with_geogebra=True)`.
- Модель пишет блок:

```geogebra
{"app":"geometry","height":400,"commands":["SetPerspective(\"G\")","A = (0, 0)", "..."]}
```

Фронт без изменений: `geogebra[]` + `{{geogebra:N}}`.

## Факты о GeoGebra (проверено в апплете)

1. Нет `RegularPolygon` → `Polygon(A, B, n)`. Нет `Circumcircle` → `Circle(A, B, C)`.
2. `Polygon(P, Q, n)` падает на именах с `_` — используй `K`/`L` или `Polygon((0,0),(4,0),n)`.
3. В 3D нет правильного многоугольника через Polygon(P,Q,n) — вершины явно или Sequence.
4. Однобуквенные строчные `a,b,c,d,h,r` и имена функций `ln,sec,alt,...` ломают чертёж.
5. Высота: `ClosestPoint(Line(A,B), C)` + `Segment`, не `PerpendicularLine`.
6. 2D кадр: `ZoomIn(xmin,ymin,xmax,ymax)`; 3D: шесть аргументов. Билдер дописывает сам.

## Тесты

- `tests/test_geogebra_examples.py` — каталог, лоадер, парсер stage1, commands-only render.
- `tests/test_geogebra_builder.py` — билдер.
- `tests/test_student_async.py` — hint/solution с моками `route_or_answer_*` и двухэтапный сценарий.

Запуск юнитов без БД: `.\.venv\Scripts\python.exe -m pytest tests/test_geogebra_examples.py tests/test_geogebra_builder.py -q --noconftest`
