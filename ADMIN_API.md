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
Пакетное создание заданий (до 500 за раз).
```json
{
  "tasks": [
    {
      "task_class": "10",
      "topic_number": "1.1",
      "content": "Решите уравнение \\\\(x^2 - 5x + 6 = 0\\\\)",
      "answer": "2; 3",
      "is_open_answer": true,
      "difficulty": 2,
      "topic": "Алгебра",
      "section": "Квадратные уравнения"
    },
    {
      "task_class": "10",
      "topic_number": "1.1",
      "content": "Сколько корней?",
      "options": ["0", "1", "2"],
      "answer": "2",
      "is_open_answer": false,
      "difficulty": 1
    }
  ]
}
```

**Валидация:**
- `task_class`, `topic_number`, `content`, `answer` — обязательны
- `is_open_answer: false` → `options` обязателен (массив строк)
- `is_open_answer: true` (или не указано) → `options` не нужен
- `difficulty` — 1..5

### PUT /admin/tasks/batch
Пакетное обновление заданий (до 500). Каждый объект должен содержать `id` + поля для обновления:
```json
{
  "tasks": [
    { "id": 1, "difficulty": 3, "topic": "Алгебра", "section": "Квадратные уравнения" },
    { "id": 2, "answer": "4", "hint": "Подумайте" }
  ]
}
```

### DELETE /admin/tasks/batch
Пакетное удаление (до 500):
```json
{ "ids": [1, 2, 3] }
```

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

### GET /admin/theory/getall
### POST /admin/theory
### GET/PUT/DELETE /admin/theory/{id}

## Email-доступ

### GET /admin/allowed/emails
### POST /admin/allowed-emails — `{ "email": "..." }`
### DELETE /admin/allowed-emails/{email}

## Изображения

### POST /admin/upload-image — `{ "image": "base64..." }`

## Результаты

### GET /admin/results/{result_id} — детальный результат теста