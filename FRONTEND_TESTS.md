# Инструкция для фронта: попытка теста

Попытка — одна строка. Её id называется `result_id`. Ответы лежат отдельно и привязаны к этой строке. Пока ученик не нажал «завершить», у попытки пустой `completed_at`. После сдачи сервер записывает туда время.

Базовый URL — тот же, что у остального API. Авторизация — `Authorization: Bearer <token>`.

Поля этих ответов — snake_case (`result_id`, `completed_at`, `is_completed`). Это не доски: у досок camelCase.

Ошибки бизнес-правил приходят как `400` или `403`, текст в `detail`.

---

## Как понять, что попытка сдана

Смотреть `completed_at` и `is_completed` в `GET /student/history`.

| Попытка | `completed_at` | `is_completed` |
| --- | --- | --- |
| Начата, сохранена или пересдана, но не сдана | `null` | `false` |
| Сдана через `submit` или через работу над ошибками | время | `true` |

`is_completed` в `GET /student/my-assignments` на это не смотреть: колонка назначения при сдаче не меняется.

---

## Начать

Назначенный тест и автосборка:

```
POST /student/start-test/{testId}
```

AI-тест:

```
POST /student/start-ai-test/{testId}
```

Тела нет.

```json
{
  "result_id": 81,
  "test_title": "Дроби",
  "tasks": [
    {
      "id": 15,
      "content": "2 + 2 = ?",
      "options": ["3", "4", "5", "6"],
      "answer": "4",
      "is_open_answer": false,
      "difficulty": 1
    }
  ],
  "time_limit": null,
  "time_limit_minutes": 20,
  "allow_interruptions": true,
  "time_spent_seconds": 0,
  "attempts_used": 0,
  "max_attempts": 3,
  "previous_answers": []
}
```

`result_id` запомнить: им открывают результат, пересдачу и работу над ошибками.

`time_limit_minutes` — лимит в минутах. `null` значит лимита нет. Поле `time_limit` сейчас всегда `null`, его не использовать.

`attempts_used` — сколько попыток этого теста уже сдано. `max_attempts` равный `null` значит без лимита.

`previous_answers` — ответы незаконченной попытки, если ученик возвращается:

```json
[{ "task_id": 15, "user_answer": "3" }]
```

`user_answer` — строка или список строк, как ответ сохранили.

Поведение старта:

- `allow_interruptions: true` (так по умолчанию) — сервер продолжает ту же незаконченную попытку и отдаёт её `result_id` и `previous_answers`. `time_spent_seconds` — уже накопленное время. `started_at` ставится на момент этого открытия: пауза, пока тест был закрыт, в следующее сохранение не попадёт.
- `allow_interruptions: false` — старая незаконченная попытка выбрасывается, начинается новая с нуля.
- Учительский тест проверяет окно экзамена и `max_attempts`. Лимит исчерпан или экзамен ещё не начался / уже кончился — `403`, текст в `detail`.
- Назначенный тест без назначения или с прошедшим `due_date` — `403`.
- AI-тест после сдачи деактивирован. Повторный старт — `400`.

---

## Сохранить, не сдавая

```
POST /student/tests/{testId}/save-progress
Content-Type: application/json
```

```json
{
  "answers": [
    { "task_id": 15, "user_answer": "3" },
    { "task_id": 16, "user_answer": ["а", "б"] }
  ]
}
```

`user_answer` — строка, число или список строк и чисел. Закрытый вопрос с несколькими вариантами слать списком.

Можно звать при уходе со страницы и по таймеру. Повтор по тому же `task_id` затирает прошлый ответ. Попытка остаётся незаконченной.

```json
{
  "status": "saved",
  "saved_count": 2,
  "result_id": 81,
  "total_tasks_in_test": 5
}
```

Неизвестный тест — `404`.

---

## Сдать

```
POST /student/tests/{testId}/submit
Content-Type: application/json
```

Тело — массив, не объект:

```json
[
  { "task_id": 15, "user_answer": "4" },
  { "task_id": 16, "user_answer": "6" }
]
```

Если массив не пустой, эти ответы заменяют все ранее сохранённые в попытке. Если массив пустой (`[]`), сдаются ответы, которые уже лежат после `save-progress`. Пустой массив без черновика — `404`, «Нет незавершённой попытки» или «Нет сохранённых ответов».

```json
{
  "status": "success",
  "score": 1,
  "max_score_possible": 2
}
```

Балл закрытого задания — 1, открытого — 2, ошибка — 0. После этого `completed_at` заполнен.

Учительский тест перед сдачей снова проверяет лимит попыток. Если задан `time_limit_minutes` и время вышло, ответы не принимаются: `404`, в `detail` есть «Время вышло». AI-тест после успешной сдачи выключается.

`submit` и `save-progress` сами ищут незаконченную попытку этого теста. Отдельный `result_id` в адресе не нужен.

---

## История

```
GET /student/history
```

Все попытки ученика, и сданные, и нет. Незаконченные стоят сверху.

```json
[
  {
    "id": 81,
    "test_id": 4,
    "user_id": 12,
    "total_points": 0,
    "completed_at": null,
    "is_completed": false,
    "started_at": "2026-11-26T09:00:00",
    "time_spent_seconds": 0,
    "test_title": "Дроби",
    "test": { "id": 4, "title": "Дроби" }
  },
  {
    "id": 70,
    "test_id": 3,
    "user_id": 12,
    "total_points": 2,
    "completed_at": "2026-11-26T09:15:00",
    "is_completed": true,
    "test_title": "Проценты",
    "test": { "id": 3, "title": "Проценты" }
  }
]
```

`id` здесь — это `result_id`.

Учитель и админ видят те же попытки, включая незаконченные:

```
GET /teacher/students-history/{studentId}
GET /admin/users/{userId}/history
```

```json
[
  {
    "test_title": "Дроби",
    "result": {
      "id": 81,
      "total_points": 0,
      "completed_at": null,
      "is_completed": false,
      "started_at": "2026-11-26T09:00:00",
      "time_spent_seconds": 125
    }
  }
]
```

Учитель видит только своего ученика, иначе `403`.

`time_spent_seconds` — секунды уже закрытых заходов. Секунды текущего захода начинаются с `started_at` и дописываются в `time_spent_seconds` только при `save-progress` или `submit`. Повторный `start-test` начинает заход заново и не прибавляет время, пока тест был закрыт. У только что начатой попытки `time_spent_seconds` равен 0.

Те же `started_at` и `time_spent_seconds` есть в `GET /student/results/{resultId}` и в детальном результате учителя и админа.

Незаконченная попытка, которую не трогали 10 дней (`started_at` старше 10 суток или пустой), раз в сутки удаляется вместе с ответами. Сданные попытки эта уборка не трогает.

Один и тот же список кэшируется около двух минут. `submit`, пересдача и сдача работы над ошибками кэш сбрасывают. Сразу после `start-test` или `save-progress` история может ещё не содержать новую попытку: тогда запросить её ещё раз чуть позже или обновить экран после сдачи.

Карточка одной попытки, уже с разбором:

```
GET /student/results/{resultId}
```

```json
{
  "test_title": "Дроби",
  "total_points": 1,
  "max_points": 2,
  "completed_at": "2026-11-26T09:15:00",
  "started_at": "2026-11-26T09:00:00",
  "time_spent_seconds": 125,
  "difficulty_stats": {
    "1": { "total": 2, "correct": 1 }
  },
  "details": [
    {
      "task_id": 15,
      "content": "2 + 2 = ?",
      "options": ["3", "4", "5", "6"],
      "correct_answer": "4",
      "user_answer": "3",
      "is_correct": false,
      "solution": "2 + 2 = 4",
      "difficulty": 1,
      "points_earned": 0,
      "max_task_points": 1,
      "hint": null
    }
  ]
}
```

У незаконченной попытки `completed_at` равен `null`. Задание без ответа приходит как `user_answer: "Нет ответа"` и `is_correct: false`. Чужая или неизвестная попытка — `400`.

---

## Пересдача

```
POST /student/retake/{resultId}
```

Тела нет. Это та же попытка: `result_id` в ответе совпадает с адресом.

Что меняется у строки:

- ответы удалены;
- `total_points` равен 0;
- `completed_at` снова `null`, в истории `is_completed: false`;
- `time_spent_seconds` равен 0, отсчёт начат заново;
- `previous_answers` пустой.

Форма ответа та же, что у `start-test`.

До сброса проверяются те же правила, что у старта учительского теста: окно экзамена и `max_attempts`. Если сданных попыток уже не меньше лимита, пересдача не начинается — `400`, в тексте есть «лимит». Сданный AI-тест пересдать нельзя: `400`, тест деактивирован.

---

## Работа над ошибками

Только для уже сданной попытки. Верные ответы не стираются и в список не попадают. Новой попытки нет, `max_attempts` не тратится.

Показать ошибки:

```
POST /student/results/{resultId}/mistakes
```

```json
{
  "result_id": 81,
  "test_title": "Дроби",
  "tasks": [
    {
      "id": 15,
      "content": "2 + 2 = ?",
      "options": ["3", "4", "5", "6"],
      "is_open_answer": false,
      "difficulty": 1,
      "user_answer": "3"
    }
  ]
}
```

Правильного ответа в этом списке нет. Его видно в `GET /student/results/{resultId}`, в поле `correct_answer`. Если ошибок нет или попытка ещё не сдана — `400`.

Сдать исправления:

```
POST /student/results/{resultId}/mistakes/submit
Content-Type: application/json
```

```json
[
  { "task_id": 15, "user_answer": "4" }
]
```

В массиве только задания из списка ошибок. Верное задание или чужой `task_id` — `400`.

```json
{
  "status": "success",
  "score": 2,
  "max_score_possible": 2,
  "fixed": 1,
  "remaining_mistakes": 0
}
```

`fixed` — сколько из присланных ответов стали верными. `remaining_mistakes` — сколько ошибок в попытке осталось, включая те, которые в этот раз не прислали. Попытка остаётся сданной: `completed_at` обновляется на сейчас. Когда `remaining_mistakes` равен 0, следующий вызов `mistakes` отвечает `400` «Ошибок нет».

---

## Сценарий

1. Ученик открывает тест: `POST /student/start-test/{testId}`. На экране рисуются `tasks`. Если `previous_answers` не пустой, подставить их.
2. Пока решает, слать `save-progress`. Это не сдача.
3. «Завершить» — `submit` с текущими ответами. В истории у этой строки `is_completed: true`.
4. Разбор — `GET /student/results/{resultId}`.
5. «Пересдать» — `POST /student/retake/{resultId}`, затем снова решать и звать `submit`. Тот же `result_id`.
6. «Работа над ошибками» — `POST /student/results/{resultId}/mistakes`, затем `mistakes/submit` только по этим заданиям.
