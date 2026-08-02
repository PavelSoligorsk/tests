# Education Platform API

Бэкенд образовательной платформы на **FastAPI** + **PostgreSQL**. Платформа позволяет учителям создавать тесты из банка заданий (включая AI-генерацию), назначать их ученикам и группам, вести расписание занятий и учёт оплат, а ученикам — проходить тесты, получать AI-подсказки и изучать теорию. Также есть Telegram-бот для родителей (баланс, оплаты) и учителей (уведомления).

**Прод:** https://tests-production-46d5.up.railway.app  
**Swagger UI:** https://tests-production-46d5.up.railway.app/docs  
**OpenAPI JSON:** https://tests-production-46d5.up.railway.app/openapi.json

---

## 📋 Содержание

- [🧱 Стек](#-стек)
- [📁 Структура проекта](#-структура-проекта)
- [👥 Роли пользователей](#-роли-пользователей)
- [🗄️ Модели данных](#️-модели-данных)
- [🔌 API-модули](#-api-модули)
- [🤖 AI-возможности](#-ai-возможности)
- [📅 Расписание и оплаты](#-расписание-и-оплаты)
- [🤖 Telegram-интеграция](#-telegram-интеграция)
- [‍💻 Redis-кеширование](#-redis-кеширование)
- [🚀 Быстрый старт (локально)](#-быстрый-старт-локально)
- [🐘 Работа с миграциями (Alembic)](#-работа-с-миграциями-alembic)
- [🚆 Деплой на Railway](#-деплой-на-railway)
- [🔧 Переменные окружения](#-переменные-окружения)
- [🧪 Тесты](#-тесты)
- [⚠️ Известные проблемы](#️-известные-проблемы)

---

## 🧱 Стек

| Слой | Технология |
|---|---|
| Веб-фреймворк | FastAPI 0.116 |
| База данных | PostgreSQL (SQLAlchemy 2.0 async + asyncpg) |
| Миграции | Alembic |
| Авторизация | JWT (python-jose), пароли bcrypt (passlib) |
| Кеш | Redis (опционально, fail-closed) |
| Файлы | Cloudflare R2 (boto3) — загрузка изображений |
| AI | DeepSeek / MistralAI / OpenAI — генерация тестов, подсказки, решения, классификация заданий |
| Нотификации | Telegram-бот + Email (SMTP) |
| Мониторинг | Sentry SDK |
| ASGI-сервер | Uvicorn |
| Python | 3.13 |

---

## 📁 Структура проекта

```
fastapi/
├── main.py                      # Точка входа, lifespan, миграции при старте, CORS
├── requirements.txt             # Зависимости
├── nixpacks.toml                # Пребилд-инструкции для Railway/Nixpacks
├── alembic.ini                  # Конфиг Alembic
├── alembic/
│   ├── env.py                   # Async-окружение Alembic (читает DATABASE_URL)
│   └── versions/                # Файлы миграций
├── core/
│   ├── auth.py                  # JWT-токены, hash-паролей, проверки ролей
│   ├── cache.py                 # Redis-кеш с DTO-сериализацией (fail-closed)
│   ├── config.py                # Pydantic Settings (DATABASE_URL)
│   ├── database.py              # Async engine, sessionmaker, Base, get_db
│   └── models.py                # Все SQLAlchemy-модели
├── api/                         # HTTP-слой (роутеры)
│   ├── auth_api.py              # Регистрация, вход, сброс пароля
│   ├── admin_api.py             # Админка: пользователи, задания, теория, батч-операции
│   ├── teacher_api.py           # Учитель: тесты, группы, назначения, результаты
│   ├── teacher_schedule_api.py  # Расписание, занятия, оплаты, родители
│   ├── student_api.py           # Студент: тесты, результаты, теория, AI
│   ├── stats_api.py             # Статистика (своя / по пользователям)
│   └── telegram_api.py          # Эндпоинты для Telegram-бота
├── services/                    # Бизнес-логика
│   ├── admin_service.py
│   ├── ai_service.py            # DeepSeek/Mistral/OpenAI
│   ├── auth_service.py
│   ├── schedule_service.py      # Расписание, оплаты, родители
│   ├── stats_service.py
│   ├── student_service.py
│   └── teacher_service.py
├── repositories/                # Слой доступа к данным (по сущностям)
├── dto_schemas/                 # Pydantic-схемы запросов/ответов
├── scripts/                     # Вспомогательные скрипты (батч-загрузка заданий, классификация)
└── tests/                       # Тесты (pytest, async)
```

---

## 👥 Роли пользователей

| Роль | Возможности |
|---|---|
| `admin` | Всё, что у учителя + управление пользователями (роли, удаление), банком заданий (CRUD, батч-операции), теорией, доступ по allow-list email, AI-классификация заданий, пересборка тестов |
| `teacher` | Создание/редактирование тестов (в т.ч. AI-генерация), управление группами учеников, назначение тестов ученикам и группам, просмотр результатов, расписание занятий, оплаты, родители учеников |
| `student` | Прохождение назначенных и доступных тестов, AI-подсказки и решения, теория и Q&A с AI, просмотр своей статистики и истории |

> Регистрация доступна только для email из allow-list (`allowed_emails`). Роль по умолчанию — `student`.

---

## 🗄️ Модели данных

Основные сущности (см. `core/models.py`):

| Модель | Таблица | Назначение |
|---|---|---|
| `User` | `users` | Пользователи (admin/teacher/student), профиль, tg_username/tg_chat_id, баланс в копейках BYN, привязка к родителю |
| `Parent` | `parents` | Родитель студента (один родитель → много студентов через `parent_id`) |
| `Group` / `GroupStudent` | `groups` / `group_students` | Группы учеников учителя (M2M) |
| `Task` | `tasks` | Банк заданий: класс, тема, раздел, контент, ответ, варианты (JSON), подсказка, решение, сложность |
| `Test` | `tests` | Тест: тайтл, создатель, target_class/topic, правила (max_attempts, time_limit_minutes, allow_interruptions, exam_start/end), is_autocompile, is_ai_generated |
| `TestTaskAssociation` | `test_task_association` | M2M тест ↔ задания |
| `TestResult` | `test_results` | Попытка прохождения: баллы, completed_at, тайминг (started_at, time_spent_seconds) |
| `UserAnswer` | `user_answers` | Ответ на задание: текст, is_correct, points_earned |
| `TestAssignment` | `test_assignments` | Назначение теста студенту или группе, due_date, is_completed (уникальность test_id+user_id) |
| `Theory` | `theory` | Теория по теме+разделу (уникальность topic+section) |
| `AllowedEmail` | `allowed_emails` | Allow-list email для регистрации |
| `TeacherStudent` | `teacher_students` | Связь учитель↔ученик (M2M) |
| `PasswordResetToken` | `password_reset_tokens` | Токены сброса пароля (email, token, expires_at, is_used) |
| `LessonSchedule` | `lesson_schedules` | Шаблон повторяющегося занятия: тип (individual/group), дни недели (JSON), время, длительность, цена, recur_until |
| `Lesson` | `lessons` | Конкретное занятие: статус (scheduled/completed/cancelled/rescheduled), фактические даты, переносы (rescheduled_from/to) |
| `Payment` | `payments` | Оплата: тип (per_lesson/monthly/package), статус (pending/paid/cancelled), пакеты (package_total/used), периоды |

**Особенности:**
- Баланс ученика хранится в **копейках BYN**.
- `datetime.utcnow` используется как default для created_at (⚠️ deprecated, см. BUGS.md).
- Расписание: шаблоны (`LessonSchedule`) генерируют конкретные занятия (`Lesson`).

---

## 🔌 API-модули

Все роутеры подключаются в `main.py` без префиксов (префиксы заданы в самих роутерах). Авторизация — заголовок `Authorization: Bearer <JWT>`.

### Аутентификация — `api/auth_api.py` (tags: Authentication)
| Метод | Путь | Описание |
|---|---|---|
| POST | `/register` | Регистрация (только allow-list email). Тело: `UserRegister` |
| POST | `/login` | OAuth2 Password form (`username`, `password`) → JWT |
| POST | `/forgot-password` | Отправить email со ссылкой сброса |
| POST | `/reset-password` | Сбросить пароль по токену (`token`, `new_password`, `confirm_password`) |
| GET | `/verify-reset-token/{token}` | Проверить валидность токена сброса |

### Админка — `api/admin_api.py` (prefix: `/admin`, tags: Admin)
- **Пользователи:** `GET /admin/users`, `PATCH /admin/users/{id}/role`, `DELETE /admin/users/{id}`, `GET /admin/users/{id}/profile`, `GET /admin/users/{id}/history`
- **Банк заданий:** `GET /admin/` (все задания), `GET/POST/PUT/DELETE /admin/tasks[/{id}]`, батч-операции `POST/PUT/DELETE /admin/tasks/batch` (до 500), `GET /admin/{task_id}` (короткая ссылка)
- **Результаты:** `GET /admin/results/{result_id}`
- **Allow-list email:** `GET /admin/allowed/emails`, `POST /admin/allowed-emails`, `DELETE /admin/allowed-emails/{email}`
- **Связи:** `POST /admin/assign-student-to-teacher`, `DELETE /admin/remove-student-from-teacher/{student_id}`
- **Теория:** `POST /admin/theory`, `GET /admin/theory/getall`, `GET/PUT/DELETE /admin/theory/{id}`
- **Прочее:** `POST /admin/upload-image` (Cloudflare R2), `POST /admin/tasks/{id}/send-to-tg`, `POST /admin/classify-tasks` (AI-классификация), `POST /admin/rebuild-all-static-tests`

### Учитель: тесты/группы — `api/teacher_api.py` (prefix: `/teacher`, tags: Teacher API)
- **Профиль:** `PUT /teacher/profile`
- **Банк заданий:** `GET /teacher/tasks` (с фильтрами), `GET /teacher/tasks-grouped`, `GET /teacher/tasks/by-class-topic`, `GET /teacher/tasks/by-topic/{topic}/section/{section}`, `GET /teacher/tasks/by-class/`, `GET /teacher/tasks/{id}`, `GET /teacher/tasks-meta`, `GET /teacher/tasks-meta-by-topic-section`
- **Тесты:** `GET/POST /teacher/tests`, `PUT/DELETE/GET /teacher/tests/{id}`, `GET /teacher/tests/{id}/tasks`, `POST /teacher/generate-test` (AI)
- **Результаты учеников:** `GET /teacher/students`, `GET /teacher/students-profile/{user_id}`, `GET /teacher/students-history/{user_id}`, `GET /teacher/results/{result_id}`
- **Назначения:** `POST /teacher/assign-test`, `GET /teacher/test/{test_id}/assignments`, `GET /teacher/student/{student_id}/assignments`, `DELETE /teacher/assignments/{assignment_id}`, `POST /teacher/assign-test-to-group`
- **Группы:** `GET/POST /teacher/groups/`, `PUT/DELETE /teacher/groups/{id}`, `POST /teacher/groups/{id}/students`, `DELETE /teacher/groups/{id}/students/{student_id}`, `GET /teacher/groups/{id}/students`, `GET /teacher/groups/{id}/assignments`

### Расписание/оплаты — `api/teacher_schedule_api.py` (prefix: `/teacher`, tags: Teacher Schedule)
- **Родители:** `POST/GET /teacher/parents`, `GET/PUT/DELETE /teacher/parents/{id}`, `POST /teacher/parents/{id}/link-student/{student_id}`, `DELETE /teacher/parents/unlink-student/{student_id}`, `GET /teacher/students/{student_id}/parents`
- **Расписания:** `POST/GET /teacher/schedules`, `GET/PUT/DELETE /teacher/schedules/{id}`, `POST /teacher/schedules/{id}/toggle`
- **Занятия:** `POST /teacher/lessons`, `GET /teacher/calendar`, `GET /teacher/lessons/{id}`, `POST /teacher/lessons/{id}/complete|cancel|reschedule`, `PUT/DELETE /teacher/lessons/{id}`
- **Оплаты:** `POST/GET /teacher/payments`, `POST /teacher/payments/{id}/paid`, `PUT/DELETE /teacher/payments/{id}`, `POST /teacher/payments/{id}/cancel`, `GET /teacher/payments/stats`

### Студент — `api/student_api.py` (prefix: `/student`, tags: Student API)
- **Профиль:** `GET/PUT /student/me`
- **Тесты:** `GET /student/tests`, `GET /student/tests/{id}`, `POST /student/tests/{id}/submit`, `POST /student/tests/{id}/save-progress`, `POST /student/start-test/{test_id}`, `POST /student/retake/{result_id}`, `GET /student/tests-meta`
- **AI:** `POST /student/tasks/{id}/hint`, `POST /student/tasks/{id}/ai-solve`, `POST /student/generate-test`, `POST /student/start-ai-test/{test_id}`
- **История:** `GET /student/history`, `GET /student/results/{result_id}`, `GET /student/my-assignments`, `GET /student/my-assignments-meta`, `GET /student/ai-tests`, `GET /student/ai-tests/incomplete`
- **Теория:** `GET /student/theory/topics`, `GET /student/theory/by-topic/{topic}`, `GET /student/theory/sections/{topic}`, `GET /student/theory/by-topic/{topic}/section/{section}`, `POST /student/theory/ask-ai`

### Статистика — `api/stats_api.py` (prefix: `/stats`, tags: Statistics)
- **Своя:** `GET /stats/me/period`, `GET /stats/me/topics`, `GET /stats/me/difficulty`, `GET /stats/me/full` (параметр: period = month/all/week)
- **По пользователю** (учитель/админ по разрешению): `GET /stats/user/{id}/period`, `…/topics`, `…/difficulty`, `…/full`

### Telegram-бот — `api/telegram_api.py` (prefix: `/telegram`, tags: Telegram Bot)
Защита — заголовок `X-Telegram-Bot-Key` (значение `TELEGRAM_BOT_TOKEN` или `BOT_TOKEN`).
- `GET /telegram/whoami/{tg_username}` — определение роли (teacher → parent → student)
- `GET /telegram/student/{id}/balance` — баланс + последние N операций
- `POST /telegram/confirm-payment` / `POST /telegram/reject-payment` — подтверждение/отклонение оплаты учителем
- `GET /telegram/student-balance/{student_tg_username}` — баланс по username
- `GET /telegram/student/{id}/payment-stats` — сводка оплат с пагинацией
- `POST /telegram/register-chat` — сохранение tg_chat_id учителя
- `GET /telegram/student/{id}/teacher-chat` — chat_id учителя для маршрутизации чеков

---

## 🤖 AI-возможности

Поддерживаются провайдеры: **DeepSeek** (`DEEPSEEK_API_KEY`), **Mistral** (`MISTRAL_TOKEN`), **OpenAI** (`OPENAI_API_KEY`) — выбор в `services/ai_service.py`.

- **AI-генерация теста** — учитель задаёт промпт (тему, класс), число заданий, сложность, список учеников/групп; AI классифицирует тему, подбирает задания из банка (исключая недавно решённые `recent_weeks`), создаёт тест с `is_ai_generated=True`. Аналогично для студента, но без привязки к ученикам.
- **Подсказка/Решение для задания** — `POST /student/tasks/{id}/hint|ai-solve`.
- **Теория Q&A** — `POST /student/theory/ask-ai`.
- **Классификация заданий** — админ `POST /admin/classify-tasks` (определение topic/section по содержимому).

---

## 📅 Расписание и оплаты

**Расписание** (`services/schedule_service.py`):
- Учитель создаёт `LessonSchedule` — повторяющийся шаблон (дни недели, время, длительность, цена, до какой даты).
- Генерация конкретных `Lesson` с датами.
- Занятия можно завершать, отменять (с пометкой), переносить (создаётся связь rescheduled_from/to), редактировать.
- Календарь: `GET /teacher/calendar?date_from=...&date_to=...`.

**Оплаты**:
- Типы: `per_lesson` (разовое), `monthly` (месячный абонемент с valid_from/valid_until), `package` (пакет занятий с package_total/package_used).
- Статусы: `pending` → `paid` / `cancelled`.
- Баланс ученика (копейки BYN): пополняется через `confirm-payment` (Telegram) или `mark_payment_paid`; списывается за занятия (`per_lesson` с lesson_id).
- Статистика: `GET /teacher/payments/stats`.

**Родители**:
- Сущность `Parent` привязывается к одному или нескольким ученикам (`users.parent_id`).
- Telegram-бот позволяет родителю видеть детей, баланс и историю оплат.

---

## 🤖 Telegram-интеграция

- Бот обращается к API с заголовком `X-Telegram-Bot-Key`.
- **Маршрутизация:** `whoami` определяет, кто написал боту (учитель/родитель/ученик).
- **Учитель:** регистрирует chat_id (`register-chat`), получает уведомления, подтверждает/отклоняет оплаты (`confirm-payment` / `reject-payment`).
- **Родитель:** видит список детей (`whoami` → children), баланс (`student-balance`), статистику оплат (`payment-stats`).
- **Ученик:** статус «скоро появится».

---

## 💻 Redis-кеширование

Реализовано в `core/cache.py`:

- **Fail-closed:** если Redis недоступен (или не задан `REDIS_URL`), всё работает без кеша.
- **DTO-first:** данные сериализуются в Pydantic-схемы (или ORM→DTO) перед записью в Redis — единый формат.
- **Ключи:** иерархические `prefix:user:entity[:hash-параметров]`.
- **Инвалидация:** по паттернам через `scan_iter` (без `KEYS`), `invalidate_user_cache(user_id, ...prefixes)`, `invalidate_cache_pattern(pattern)`, `invalidate_all_user_cache(user_id)`.
- Глобальный кеш: задания, тесты, теория. Персональный: профиль, история, назначения, результаты. TTL от 2 минут до 2 часов.

Использование: `async_cache_result(prefix, user_id, fetcher, model_class, ttl, ...params)`.

---

## 🚀 Быстрый старт (локально)

### 1. Клонируй репозиторий

```bash
git clone <repo-url>
cd fastapi
```

### 2. Создай виртуальное окружение и установи зависимости

```bash
python -m venv .venv
.venv\Scripts\activate    # Windows
# source .venv/bin/activate  # Linux/Mac

pip install -r requirements.txt
```

### 3. Создай `.env`-файл

```env
# База данных (обязательно)
DATABASE_URL=postgresql://postgres:your_password@localhost:5432/education_platform

# JWT
SECRET_KEY=super_secret_key_change_me_in_production
ALGORITHM=HS256

# AI (DeepSeek / Mistral / OpenAI — хотя бы один)
DEEPSEEK_API_KEY=...
MISTRAL_TOKEN=...
OPENAI_API_KEY=...

# Cloudflare R2 (загрузка изображений в админке)
R2_ACCESS_KEY_ID=...
R2_SECRET_ACCESS_KEY=...
R2_ENDPOINT_URL=https://...r2.cloudflarestorage.com
R2_BUCKET_NAME=edu-backet
R2_PUBLIC_URL=https://pub-...r2.dev

# Email (восстановление пароля)
MAIL_USERNAME=...
MAIL_PASSWORD=...
FRONTEND_URL=http://localhost:3000

# Telegram-бот
TELEGRAM_BOT_TOKEN=...

# Redis (опционально — без него кеш отключён)
REDIS_URL=redis://localhost:6379/0
```

> ⚠️ Файл `.env` **не должен** попадать в git (он уже в `.gitignore`). Настоятельно рекомендуется заполнять только через переменные окружения на сервере.

### 4. Примени миграции

```bash
alembic upgrade head
```

### 5. Запусти сервер

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Открой http://localhost:8000/docs — Swagger UI.

---

## 🐘 Работа с миграциями (Alembic)

```bash
# Создать новую миграцию (автогенерация)
alembic revision --autogenerate -m "описание изменений"

# Применить миграции
alembic upgrade head

# Откатить последнюю миграцию
alembic downgrade -1
```

**Важно:** миграции автоматически запускаются при старте приложения (lifespan в `main.py`). Локально можно пропустить:

```bash
SKIP_MIGRATIONS=1 uvicorn main:app --reload
```

---

## 🚆 Деплой на Railway

Проект настроен для Railway:

1. **Билд:** Railway читает `railway.json` → Nixpacks → `pip install -r requirements.txt`
2. **Старт:** `uvicorn main:app --host 0.0.0.0 --port $PORT`
3. **Миграции:** `main.py` вызывает `alembic upgrade head` в lifespan — до приёма трафика

В Railway-дашборде:
- Подключить PostgreSQL (сервис выдаст `DATABASE_URL`)
- Задать остальные переменные окружения из `.env`
- Порт выставляется автоматически через переменную `PORT`

`nixpacks.toml` позволяет добавить шаги до `pip install` (например, системные пакеты):

```toml
[phases.setup]
nixPkgs = ["postgresql.lib"]

[phases.install]
cmds = [
    "pip install -r requirements.txt",
]
```

---

## 🔧 Переменные окружения

| Переменная | Назначение | Обязательная |
|---|---|---|
| `DATABASE_URL` | PostgreSQL DSN | ✅ |
| `SECRET_KEY` | Ключ для JWT | ✅ |
| `ALGORITHM` | Алгоритм JWT (HS256) | ✅ |
| `DEEPSEEK_API_KEY` / `MISTRAL_TOKEN` / `OPENAI_API_KEY` | AI-провайдеры | для AI-функций |
| `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_ENDPOINT_URL`, `R2_BUCKET_NAME`, `R2_PUBLIC_URL` | Cloudflare R2 (изображения) | для загрузки файлов |
| `MAIL_USERNAME`, `MAIL_PASSWORD`, `FRONTEND_URL` | SMTP / ссылки в письмах | для сброса пароля |
| `TELEGRAM_BOT_TOKEN` (или `BOT_TOKEN`) | Ключ Telegram-бота (также заголовок `X-Telegram-Bot-Key`) | для Telegram-эндпоинтов |
| `REDIS_URL` | Redis-кеш | ❌ (без Redis кеш отключён) |
| `SKIP_MIGRATIONS` | Пропустить миграции при старте (`1`/`true`/`yes`) | ❌ |
| `PORT` | Порт (Railway выставляет автоматически) | ❌ |

---

## 🧪 Тесты

```bash
pytest tests/ -v
```

Конфигурация — `tests/pytest.ini`, фикстуры — `tests/conftest.py`, async-хелперы — `tests/helpers_async.py`.

---

## ⚠️ Известные проблемы

Список найденных багов, уязвимостей и странностей задокументирован в **[BUGS.md](./BUGS.md)**.

Основное:
- 🔴 Реальный API-ключ DeepSeek захардкожен в `check_deepseek.py:444` (нужна ротация ключа)
- 🟠 Неконсистентность путей в админке (`/admin/allowed/emails` vs `/admin/allowed-emails`)
- 🟠 Catch-all маршрут `GET /admin/{task_id}` может перехватывать чужие пути
- 🟡 `datetime.utcnow()` (deprecated в Python 3.12+)
- 🟡 Дублирование конфигурации (`core/config.py` не используется)
