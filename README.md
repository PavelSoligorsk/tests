# Education Platform API

Бэкенд образовательной платформы на **FastAPI** + **PostgreSQL**. Тесты, теория, группы, роли — админ, учитель, ученик.

## 🧱 Стек

| Слой | Технология |
|---|---|
| Веб-фреймворк | FastAPI 0.116 |
| База данных | PostgreSQL (через SQLAlchemy 2.0 async + asyncpg) |
| Миграции | Alembic |
| Авторизация | JWT (python-jose + bcrypt / passlib) |
| Файлы | Cloudflare R2 (boto3) |
| AI | MistralAI / DeepSeek (генерация тестов) |
| Нотификации | Telegram бот + Email (SMTP) |
| Мониторинг | Sentry SDK |
| Кеш | Redis |
| ASGI-сервер | Uvicorn |
| Python | 3.13 |

## 📁 Структура проекта

```
fastapi/
├── main.py                  # Точка входа, lifespan, миграции при старте
├── requirements.txt         # Зависимости
├── railway.json             # Конфигурация деплоя на Railway
├── nixpacks.toml            # Пребилд-инструкции для Railway/Nixpacks
├── alembic.ini              # Конфиг Alembic
├── alembic/
│   ├── env.py               # Async-окружение Alembic (читает DATABASE_URL)
│   └── versions/            # Файлы миграций
├── core/
│   ├── database.py          # Async engine, session, Base
│   └── models.py            # Все SQLAlchemy-модели
├── api/
│   ├── auth_api.py          # Регистрация, вход, сброс пароля
│   ├── admin_api.py         # Управление пользователями, тестами
│   ├── teacher_api.py       # Группы, назначения, проверка
│   ├── student_api.py       # Прохождение тестов, результаты
│   └── stats_api.py         # Статистика
├── services/                # Бизнес-логика (AI, email, R2, Telegram...)
├── repositories/            # Слой доступа к данным
├── dto_schemas/             # Pydantic-схемы (запросы/ответы)
└── tests/                   # Тесты
```

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

Скопируй пример ниже и заполни своими значениями:

```env
# База данных (обязательно)
DATABASE_URL=******localhost:5432/education_platform

# JWT
SECRET_KEY=super_secret_key_change_me_in_production
ALGORITHM=HS256

# Cloudflare R2 (файлы)
R2_ACCESS_KEY_ID=...
R2_SECRET_ACCESS_KEY=...
R2_ENDPOINT_URL=https://...r2.cloudflarestorage.com
R2_BUCKET_NAME=edu-backet
R2_PUBLIC_URL=https://pub-...r2.dev

# AI (Mistral / DeepSeek)
MISTRAL_TOKEN=...
DEEPSEEK_API_KEY=...

# Email (восстановление пароля)
MAIL_USERNAME=...
MAIL_PASSWORD=...
FRONTEND_URL=http://localhost:3000

# Telegram-нотификации
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

### 4. Примени миграции

```bash
alembic upgrade head
```

### 5. Запусти сервер

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Открой http://localhost:8000/docs — там будет автодокументация Swagger.

## 🐘 Работа с миграциями (Alembic)

После изменения моделей в `core/models.py`:

```bash
# Создать новую миграцию (автогенерация)
alembic revision --autogenerate -m "описание изменений"

# Применить миграции
alembic upgrade head

# Откатить последнюю миграцию
alembic downgrade -1
```

**Важно:** миграции автоматически запускаются при старте приложения на Railway/продакшене. Локально можно пропустить через переменную:

```bash
SKIP_MIGRATIONS=1 uvicorn main:app --reload
```

## 🚆 Railway — деплой

Проект уже настроен для Railway. При пуше в ветку:

1. **Билд:** Railway читает `railway.json` → Nixpacks → `pip install -r requirements.txt`
2. **Старт:** `uvicorn main:app --host 0.0.0.0 --port $PORT`
3. **Миграции:** `main.py` вызывает `alembic upgrade head` в lifespan — до приёма трафика

Что нужно сделать в Railway-дашборде:

- **Подключить PostgreSQL** (сервис сам выдаст `DATABASE_URL`)
- **Добавить переменные окружения** — все из `.env`, кроме `DATABASE_URL`
- `PORT` будет выставлен автоматически

### Пребилд-скрипт (`nixpacks.toml`)

Если нужны дополнительные шаги до `pip install` (системные библиотеки, скрипты), дописывай их в `[phases.setup]` файла `nixpacks.toml`:

```toml
[phases.setup]
nixPkgs = ["postgresql.lib"]   # если нужен psycopg2 (не -binary)

[phases.install]
cmds = [
    "pip install -r requirements.txt",
    # дополнительные команды...
]
```

## 👥 Роли пользователей

| Роль | Возможности |
|---|---|
| `admin` | Управление всеми пользователями, тестами, теорией, просмотр всей статистики |
| `teacher` | Создание тестов, управление группами, назначение тестов, просмотр результатов учеников |
| `student` | Прохождение назначенных тестов, просмотр своих результатов |

## 🔧 Переменные окружения

| Переменная | Назначение | Обязательная |
|---|---|---|
| `DATABASE_URL` | PostgreSQL DSN | ✅ |
| `SECRET_KEY` | Ключ для JWT | ✅ |
| `ALGORITHM` | Алгоритм JWT (HS256 / RS256) | ✅ |
| `R2_ACCESS_KEY_ID` | Cloudflare R2 access key | если нужны файлы |
| `R2_SECRET_ACCESS_KEY` | Cloudflare R2 secret key | если нужны файлы |
| `R2_ENDPOINT_URL` | Cloudflare R2 endpoint | если нужны файлы |
| `R2_BUCKET_NAME` | Имя бакета R2 | если нужны файлы |
| `R2_PUBLIC_URL` | Публичный URL бакета | если нужны файлы |
| `MAIL_USERNAME` | SMTP-логин | для сброса пароля |
| `MAIL_PASSWORD` | SMTP-пароль / app-password | для сброса пароля |
| `FRONTEND_URL` | URL фронтенда (для ссылок в письмах) | для сброса пароля |
| `TELEGRAM_BOT_TOKEN` | Токен Telegram-бота | для уведомлений |
| `TELEGRAM_CHAT_ID` | ID чата для уведомлений | для уведомлений |
| `DEEPSEEK_API_KEY` | API-ключ DeepSeek | для AI-генерации |
| `MISTRAL_TOKEN` | API-ключ MistralAI | для AI-генерации |
| `SKIP_MIGRATIONS` | Пропустить миграции при старте (`1`/`true`/`yes`) | ❌ |
| `PORT` | Порт (на Railway выставляется автоматически) | ❌ |

## 🧪 Тесты

```bash
pytest tests/ -v
```

## 📋 Полезные команды

```bash
# Форматирование (если добавишь ruff/black)
ruff check . --fix

# Проверить, что все импорты резолвятся
python -c "from core.models import *; print('OK')"

# Посмотреть логи Alembic подробнее
alembic -c alembic.ini upgrade head 2>&1
```
