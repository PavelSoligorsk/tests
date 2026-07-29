# Инструкция для фронта: Расписание, занятия, оплаты, родители

> Все эндпоинты доступны С ТОКЕНОМ УЧИТЕЛЯ (роль `teacher` или `admin`).  
> Префикс: `/teacher`  
> Базовый URL: `https://ваш-домен`

---

## 1. Родители (Parents)

Родитель — **отдельная таблица**. Один родитель → много студентов.  
Связь: `User.parent_id → Parent.id` (SET NULL при удалении родителя).

### 1.1 Создать родителя

```
POST /teacher/parents
Content-Type: application/json
Authorization: Bearer <teacher_token>
```

**Тело:**
```json
{
  "name": "Иван Иванович",
  "phone": "+79001234567",
  "tg_username": "@ivan_parent",
  "comment": "Предпочитает оплату наличными"
}
```

**Ответ 200:**
```json
{
  "id": 1,
  "name": "Иван Иванович",
  "phone": "+79001234567",
  "tg_username": "@ivan_parent",
  "comment": "Предпочитает оплату наличными",
  "student_ids": [],
  "created_at": "2026-07-28T12:00:00"
}
```

**Ошибки:** `400` — некорректные данные.

---

### 1.2 Список родителей

```
GET /teacher/parents
Authorization: Bearer <teacher_token>
```

**Ответ 200:**
```json
[
  {
    "id": 1,
    "name": "Иван Иванович",
    "phone": "+79001234567",
    "tg_username": "@ivan_parent",
    "comment": "Предпочитает оплату наличными",
    "student_ids": [42, 43],
    "created_at": "2026-07-28T12:00:00"
  }
]
```

> Возвращает родителей **всех** студентов учителя (у кого `parent_id` не null).

---

### 1.3 Редактировать родителя

```
PUT /teacher/parents/{parent_id}
Authorization: Bearer <teacher_token>
```

**Тело** (только изменяемые поля):
```json
{
  "phone": "+79009999999",
  "comment": "Новый комментарий"
}
```

**Ответ 200:** см. 1.1

**Ошибки:** `404` — родитель не найден.

---

### 1.4 Удалить родителя

```
DELETE /teacher/parents/{parent_id}
Authorization: Bearer <teacher_token>
```

**Ответ 200:**
```json
{ "ok": true }
```

> После удаления `parent_id` на студентах зануляется (SET NULL), студенты остаются.

---

### 1.5 Привязать студента к родителю

```
POST /teacher/parents/{parent_id}/link-student/{student_id}
Authorization: Bearer <teacher_token>
```

**Ответ 200:**
```json
{ "ok": true }
```

**Ошибки:** `404` — студент не найден.

---

### 1.6 Отвязать студента от родителя

```
DELETE /teacher/parents/unlink-student/{student_id}
Authorization: Bearer <teacher_token>
```

**Ответ 200:**
```json
{ "ok": true }
```

---

## 2. Расписание (Lesson Schedules)

Шаблон **повторяющегося** занятия. При создании — автогенерация уроков на 4 недели вперёд (или до `recur_until`).  
При изменении дней/времени/`recur_until` — перегенерация.  
Повторяется до даты `recur_until` (если указана) или бессрочно при `is_active = true`.

### 2.1 Создать расписание

```
POST /teacher/schedules
Authorization: Bearer <teacher_token>
```

**Тело:**
```json
{
  "title": "Математика 11 класс",
  "description": "Подготовка к ЕГЭ",
  "schedule_type": "individual",
  "student_id": 42,
  "group_id": null,
  "days_of_week": ["mon", "wed", "fri"],
  "time_start": "16:00",
  "duration_minutes": 90,
  "price_per_lesson": 1500,
  "recur_until": "2026-12-31T23:59:59"
}
```

> `schedule_type`: `"individual"` — нужен `student_id`, `"group"` — нужен `group_id`.  
> `days_of_week`: коды дней `["mon", "tue", "wed", "thu", "fri", "sat", "sun"]`.  
> `time_start`: строка `"HH:MM"` (UTC).  
> `recur_until`: **до какой даты генерировать** (NULL = бессрочно). Можно менять позже через `PUT`.

**Ответ 200:**
```json
{
  "id": 1,
  "teacher_id": 5,
  "title": "Математика 11 класс",
  "description": "Подготовка к ЕГЭ",
  "schedule_type": "individual",
  "student_id": 42,
  "group_id": null,
  "days_of_week": ["mon", "wed", "fri"],
  "time_start": "16:00",
  "duration_minutes": 90,
  "price_per_lesson": 1500,
  "is_active": true,
  "recur_until": "2026-12-31T23:59:59",
  "created_at": "2026-07-28T12:00:00",
  "stopped_at": null
}
```

**Ошибки:** `400` — не указан student_id/group_id для соответствующего типа.

> **После создания:** занятия на 4 недели уже сгенерированы, доступны через `/teacher/calendar`.

---

### 2.2 Список расписаний

```
GET /teacher/schedules
Authorization: Bearer <teacher_token>
```

**Ответ 200:** массив ScheduleResponse (см. 2.1).

---

### 2.3 Получить одно расписание

```
GET /teacher/schedules/{schedule_id}
Authorization: Bearer <teacher_token>
```

**Ошибки:** `404` — не найдено.

---

### 2.4 Редактировать расписание

```
PUT /teacher/schedules/{schedule_id}
Authorization: Bearer <teacher_token>
```

**Тело** (только изменяемые поля):
```json
{
  "days_of_week": ["mon", "thu"],
  "time_start": "17:00",
  "price_per_lesson": 2000,
  "recur_until": "2026-06-01T00:00:00",
  "is_active": false
}
```

> Если изменились `days_of_week`, `time_start`, `duration_minutes` или `recur_until` — будущие занятия перегенерируются.  
> `recur_until` можно продлить (догенерирует) или сократить (старые останутся, новые не создадутся).  
> `is_active: false` — останавливает расписание, проставляет `stopped_at`.

**Ошибки:** `404`.

---

### 2.5 Включить/выключить расписание (toggle)

```
POST /teacher/schedules/{schedule_id}/toggle?active=true
POST /teacher/schedules/{schedule_id}/toggle?active=false
Authorization: Bearer <teacher_token>
```

**Ответ 200:** ScheduleResponse с обновлённым `is_active` и `stopped_at`.

---

### 2.6 Удалить расписание

```
DELETE /teacher/schedules/{schedule_id}
Authorization: Bearer <teacher_token>
```

**Ответ 200:**
```json
{ "ok": true }
```

> Занятия (lessons) не удаляются — у них `schedule_id` станет NULL (SET NULL).

---

## 3. Занятия (Lessons)

Конкретный урок: запланированный, проведённый, отменённый, перенесённый.

**Статусы:**
| Статус | Описание |
|--------|----------|
| `scheduled` | Запланирован |
| `completed` | Проведён |
| `cancelled` | Отменён |
| `rescheduled` | Перенесён (смотрит на новое занятие через `rescheduled_to_id`) |

### 3.1 Календарь (главный экран)

```
GET /teacher/calendar?date_from=2026-07-28T00:00:00&date_to=2026-08-31T23:59:59
Authorization: Bearer <teacher_token>
```

**Ответ 200:**
```json
{
  "days": [
    {
      "date": "2026-07-29",
      "lessons": [
        {
          "id": 101,
          "schedule_id": 1,
          "teacher_id": 5,
          "title": "Математика 11 класс",
          "lesson_type": "individual",
          "student_id": 42,
          "group_id": null,
          "scheduled_date": "2026-07-29T16:00:00",
          "duration_minutes": 90,
          "actual_start": null,
          "actual_end": null,
          "status": "scheduled",
          "rescheduled_from_id": null,
          "rescheduled_to_id": null,
          "teacher_note": null,
          "created_at": "2026-07-28T12:00:00",
          "payment_status": "paid",
          "coverage_type": "per_lesson",
          "student_name": "Петя Иванов",
          "group_name": null
        }
      ]
    }
  ]
}
```

> **Новые поля для календаря:**
> - `payment_status`: `"paid"` / `null` — есть ли оплата (прямой платёж, месячный абонемент или пакет)
> - `coverage_type`: `"per_lesson"` / `"monthly"` / `"package"` — чем покрыто занятие
> - `student_name`: `"Имя Фамилия"` — для отображения в календаре (у групповых — null)
> - `group_name`: название группы (у индивидуальных — null)

> Сгруппировано по дням (строка `"YYYY-MM-DD"`), отсортировано по дате.

---

### 3.2 Создать разовое занятие (вне расписания)

```
POST /teacher/lessons
Authorization: Bearer <teacher_token>
```

**Тело:**
```json
{
  "title": "Консультация перед экзаменом",
  "lesson_type": "individual",
  "student_id": 42,
  "scheduled_date": "2026-08-15T18:00:00",
  "duration_minutes": 60,
  "teacher_note": "Разобрать задачу 17"
}
```

**Ответ 200:** LessonResponse (см. структуру в календаре).

**Ошибки:** `409` — конфликт с другим занятием (пересечение по времени).

---

### 3.3 Получить занятие

```
GET /teacher/lessons/{lesson_id}
Authorization: Bearer <teacher_token>
```

**Ошибки:** `404`.

---

### 3.4 Завершить занятие (completed)

```
POST /teacher/lessons/{lesson_id}/complete
Authorization: Bearer <teacher_token>
```

> Проставляет `status = "completed"`, `actual_end = now`.  
> Если `actual_start` не было — берёт `scheduled_date`.  
> **Авто-списание:** если у студента есть активный пакет → `package_used += 1`.  
> Если есть месячный абонемент → создаётся `per_lesson`-платёж с `amount: 0` (покрыто абонементом).  
> **Возвращает полный LessonResponse** (с обновлённым `status`, можно сразу обновить UI).

**Ответ 200:** LessonResponse со `status: "completed"`  
**Ошибки:** `400` — занятие не в статусе `scheduled`.

---

### 3.5 Отменить занятие

```
POST /teacher/lessons/{lesson_id}/cancel?note=Причина отмены
Authorization: Bearer <teacher_token>
```

> `note` — опциональный query-параметр.  
> **Возвращает полный LessonResponse** (status: "cancelled").

---

### 3.6 Перенести занятие

```
POST /teacher/lessons/{lesson_id}/reschedule
Authorization: Bearer <teacher_token>
```

**Тело:**
```json
{
  "new_date": "2026-08-16T19:00:00",
  "reason": "Ученик не сможет в это время"
}
```

> **Логика:** создаётся **новое** Lesson со статусом `scheduled` и `rescheduled_from_id = lesson_id`.  
> Старое занятие получает `status = "rescheduled"` и `rescheduled_to_id = new_lesson.id`.  
> Возвращается **новое** занятие.

**Ошибки:**
- `400` — занятие не в статусе `scheduled`
- `409` — конфликт с другим занятием на новое время

---

## 4. Оплаты (Payments)

**Типы оплат:**
| Тип | Описание |
|-----|----------|
| `per_lesson` | За одно занятие |
| `monthly` | Месячный абонемент (нужны `valid_from` / `valid_until`) |
| `package` | Пакет из N занятий (нужен `package_total`) |

**Статусы:** `pending` → `paid` → (можно обратно в `cancelled`)

### 4.1 Создать платёж

```
POST /teacher/payments
Authorization: Bearer <teacher_token>
```

**Тело (поурочный):**
```json
{
  "student_id": 42,
  "payment_type": "per_lesson",
  "amount": 1500,
  "lesson_id": 101,
  "comment": "Оплата за 29.07"
}
```

**Тело (месячный абонемент):**
```json
{
  "student_id": 42,
  "payment_type": "monthly",
  "amount": 12000,
  "valid_from": "2026-08-01T00:00:00",
  "valid_until": "2026-08-31T23:59:59",
  "comment": "Август 2026"
}
```

**Тело (пакет из 8 занятий):**
```json
{
  "student_id": 42,
  "payment_type": "package",
  "amount": 10000,
  "package_total": 8,
  "comment": "Пакет 8 занятий со скидкой"
}
```

**Ответ 200:**
```json
{
  "id": 1,
  "lesson_id": 101,
  "student_id": 42,
  "payment_type": "per_lesson",
  "amount": 1500,
  "status": "paid",
  "package_total": null,
  "package_used": null,
  "valid_from": null,
  "valid_until": null,
  "comment": "Оплата за 29.07",
  "paid_at": "2026-07-28T12:00:00",
  "created_at": "2026-07-28T12:00:00"
}
```

---

### 4.2 Список оплат

```
GET /teacher/payments                          # все оплаты всех студентов учителя
GET /teacher/payments?student_id=42            # оплаты конкретного студента
Authorization: Bearer <teacher_token>
```

**Ответ 200:** массив PaymentResponse.

---

### 4.3 Отметить как оплачено

```
POST /teacher/payments/{payment_id}/paid
Authorization: Bearer <teacher_token>
```

> Меняет `status` → `"paid"`, проставляет `paid_at`.

**Ошибки:** `404`.

---

### 4.4 Отменить платёж

```
POST /teacher/payments/{payment_id}/cancel
Authorization: Bearer <teacher_token>
```

> Меняет `status` → `"cancelled"`.

---

### 4.5 Статистика по оплатам

```
GET /teacher/payments/stats
GET /teacher/payments/stats?from_date=2026-07-01T00:00:00&to_date=2026-07-31T23:59:59
GET /teacher/payments/stats?student_id=42
Authorization: Bearer <teacher_token>
```

> Все параметры опциональны. `student_id` — фильтр по конкретному ученику.

**Ответ 200:**
```json
{
  "total": 45000,
  "per_lesson": 15000,
  "monthly": 12000,
  "package": 18000,
  "count": 5,
  "pending_count": 2
}
```

---

## 5. Типовые сценарии (UI flow)

### Сценарий A: Учитель настраивает регулярное занятие

1. `POST /teacher/schedules` → создать шаблон
2. `GET /teacher/calendar?date_from=...&date_to=...` → календарь, показать занятия
3. Учитель жмёт «Завершить» → `POST /teacher/lessons/{id}/complete`
4. Учитель жмёт «Перенести» → модалка с датой → `POST /teacher/lessons/{id}/reschedule`
5. Учитель жмёт «Отменить» → `POST /teacher/lessons/{id}/cancel`

### Сценарий B: Учитель добавляет родителя ученику

1. `POST /teacher/parents` → создать родителя
2. `POST /teacher/parents/{id}/link-student/{student_id}` → привязать

### Сценарий C: Учитель фиксирует оплату

1. Завершили занятие → `POST /teacher/payments` с `payment_type: "per_lesson"` и `lesson_id`
2. Или ученик купил абонемент → `POST /teacher/payments` с `payment_type: "monthly"` или `"package"`
3. Пришли деньги → `POST /teacher/payments/{id}/paid`
4. В конце месяца → `GET /teacher/payments/stats` → посмотреть выручку

### Сценарий D: Приостановка на каникулы

1. `POST /teacher/schedules/{id}/toggle?active=false` → остановить
2. Через месяц: `POST /teacher/schedules/{id}/toggle?active=true` → возобновить

---

## 6. Важные замечания

1. **Автогенерация:** при создании расписания занятия генерируются на 4 недели. Если нужно дальше — фронт может дёргать `GET /teacher/calendar` на более широкий диапазон, бэк догенерирует при необходимости (или можно добавить эндпоинт «сгенерировать ещё»).

2. **Конфликты:** при создании/переносе занятия бэк проверяет пересечение по времени у того же учителя. При конфликте — 409 с текстом ошибки.

3. **Цепочка переносов:** `rescheduled_from_id` / `rescheduled_to_id` позволяют отследить всю историю переносов. На фронте можно показывать «Перенесено с 29.07 → 30.07 → 02.08».

4. **Все даты в UTC.** Фронт должен конвертировать в локальный часовой пояс.

5. **Токен:** все эндпоинты требуют `Authorization: Bearer <token>` учителя (роль `teacher` или `admin`).
