# Admin API — Инструкция по эндпоинтам

## Банк заданий (ленивая загрузка)

### GET /admin/tasks-meta
Структура заданий без содержимого: `{ class: { topic_number: count } }`

### GET /admin/tasks-meta-by-topic-section
Структура: `{ topic: { section: count } }`

### GET /admin/tasks/by-class/?task_class=10&topic_number=1.1
Задания по классу и номеру темы (ленивая загрузка)

### GET /admin/tasks/by-topic/{topic}/section/{section}
Задания по теме и разделу (ленивая загрузка). Пример:
`/admin/tasks/by-topic/Алгебра/section/Квадратные уравнения`

---

## Тесты

### GET /admin/tests
Все тесты (админ видит все)

### GET /admin/tests/{test_id}
Детали теста с задачами

### GET /admin/tests/{test_id}/tasks
Только задания теста (ленивая загрузка)

---

## Пакетные операции

### POST /admin/tasks/batch
Пакетное создание заданий (до 500 за раз). Тело запроса — JSON `{"tasks": [ ... ]}` с теми же полями, что в YAML ниже. Для агента удобнее `create_tasks_yaml`.

```yaml
- task_class: "Выражения и их преобразования"
  topic_number: "Рациональная дробь"
  content: |
    Упростите выражение.

    $$
    \left(\frac{x}{5} - \frac{x}{3}\right) \cdot \frac{9}{x^2}
    $$
  options:
    - '$-\frac{6}{5x}$'
    - '$\frac{6}{5x}$'
    - '$-\frac{6x}{5}$'
    - '$-\frac{5}{6x}$'
  answer: "1"
  is_open_answer: false
  difficulty: 2
  topic: "expressions"
  section: "Рациональная дробь"

- task_class: "Выражения и их преобразования"
  topic_number: "Рациональная дробь"
  content: |
    Найдите значение выражения.

    $$
    \left(\frac{2}{m} - \frac{1}{n}\right) : \frac{2n - m}{3mn}
    $$

    {{image}}
  answer: "3"
  is_open_answer: true
  difficulty: 2
  topic: "expressions"
  section: "Рациональная дробь"
  image: "screenshots/figura.png"
```

**Поля**
- `task_class` — название блока программы, не номер класса (`"Выражения и их преобразования"`).
- `topic_number` — название подтемы (`"Рациональная дробь"`).
- `topic` — короткий код (`"expressions"`). `section` — то же имя раздела, что у `topic_number`.
- `content` — условие. Формулы в `$$ ... $$`.
- Закрытое (`is_open_answer: false`): `options` — формулы вариантов, `answer` — номер варианта с 1 (`"1"`, `"2"`, …), не текст варианта.
- Открытое (`is_open_answer: true`): `options` нет, `answer` — само значение (`"3"`, `"14"`, `"-1"`).
- `difficulty` — 1..5.
- Картинка: `image` / `screenshot` — путь к png или base64 (в HTTP это делает MCP, не сам JSON). `{{image}}` в `content` заменяется на `![](url)`. Без плейсхолдера ссылка дописывается в конец условия. Несколько файлов — список `images`.

### PUT /admin/tasks/batch
Пакетное обновление (до 500). У каждого объекта обязателен `id`, остальные поля — как при создании: закрытому `answer` остаётся номером варианта, формулы в `$...$`.

```yaml
- id: 12
  difficulty: 3
  topic: "expressions"
  section: "Рациональная дробь"
- id: 13
  answer: "2"
  options:
    - '$-\frac{6}{5x}$'
    - '$\frac{6}{5x}$'
```

### DELETE /admin/tasks/batch
Пакетное удаление (до 500):
```json
{ "ids": [1, 2, 3] }
```

## MCP для агента (пакетные задания)

stdio-сервер `python -m mcp_admin`. Ходит в те же `/admin/tasks/batch` под админом. Формат заданий — YAML из раздела пакетного создания.

Инструменты: `tasks_meta`, `list_tasks`, `list_tasks_by_class`, `get_task`, `create_tasks`, `create_tasks_yaml`, `update_tasks`, `delete_tasks`, `apply_tasks` (create → update → delete в одном вызове), `upload_task_image`.

`upload_task_image(file_path)` только загружает png и возвращает `url` вместе с `![](url)`, если картинку нужно вставить вручную.

```json
{
  "mcpServers": {
    "admin-tasks": {
      "command": "D:/python/fastapi/.venv/Scripts/python.exe",
      "args": ["-m", "mcp_admin"],
      "cwd": "D:/python/fastapi",
      "env": {
        "ADMIN_API_BASE": "https://tests-production-46d5.up.railway.app",
        "ADMIN_USERNAME": "admin@example.com",
        "ADMIN_PASSWORD": "..."
      }
    }
  }
}
```

Вместо логина можно `ADMIN_TOKEN` (JWT админа).

---

## AI-классификация

### POST /admin/classify-tasks
```json
{
  "task_ids": [1, 2, 3],
  "include_classified": true
}
```
- `task_ids`: пустой массив = все задания
- `include_classified`: `true` = включая уже классифицированные, `false` = только неклассифицированные

### POST /admin/rebuild-all-static-tests
Пересборка всех статических (автособранных) тестов.

---

## Пользователи

### GET /admin/users — список
### PATCH /admin/users/{id}/role?new_role=teacher — смена роли
### DELETE /admin/users/{id} — удаление
### GET /admin/users/{id}/profile — профиль со статистикой
### GET /admin/users/{id}/history — история тестов

## Назначение учителей

### POST /admin/assign-student-to-teacher — `{ "teacher_id": 1, "student_id": 2 }`
### DELETE /admin/remove-student-from-teacher/{student_id}

## Теория

### GET /admin/theory-meta
Структура без контента, с классом и порядком тем:

```json
{
  "9": {
    "algebra": {
      "priority": 2,
      "sections": { "quadratic_equations": 12 }
    }
  }
}
```

`theory_class → topic → { priority, sections: { section: theory_id } }`. Меньший `priority` — раньше в программе.

### POST /admin/theory
```json
{
  "topic": "algebra",
  "section": "quadratic_equations",
  "content": "...",
  "theory_class": 9,
  "priority": 2
}
```
`theory_class`: целое 5–11. `priority`: порядок темы внутри класса.

### GET /admin/theory/{id}
`id`, `topic`, `section`, `content`, `theory_class`. **`priority` нет.**

### PUT/DELETE /admin/theory/{id}

## Email-доступ

### GET /admin/allowed/emails
### POST /admin/allowed-emails — `{ "email": "..." }`
### DELETE /admin/allowed-emails/{email}

## Изображения

### POST /admin/upload-image
Тело: `{ "image": "<base64 png>" }`. Ответ: `{ "url": "https://.../tasks/<id>.png" }`.

В условие задания URL кладётся так: `![](https://.../tasks/<id>.png)`. MCP подставляет эту строку вместо `{{image}}` в `content`.

## Результаты

### GET /admin/results/{result_id} — детальный результат теста