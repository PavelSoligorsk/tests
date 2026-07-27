import os
import subprocess
import sys
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response

from api.auth_api import router as auth_router
from api.admin_api import router as admin_router
from api.teacher_api import router as teacher_router
from api.student_api import router as student_router
from api.stats_api import router as stats_router

from fastapi.middleware.cors import CORSMiddleware

# Корень проекта (там же, где main.py)
PROJECT_ROOT = Path(__file__).resolve().parent


def _run_alembic_migrations() -> None:
    """Запускает alembic upgrade head перед стартом приложения."""
    if os.getenv("SKIP_MIGRATIONS", "").lower() in ("1", "true", "yes"):
        print("[ALEMBIC] SKIP_MIGRATIONS=1 → skipping")
        return

    print("[ALEMBIC] Running migrations...")
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
    )
    if result.returncode != 0:
        print(f"[ALEMBIC ERROR] {result.stderr}")
        raise RuntimeError(f"Alembic migrations failed:\n{result.stderr}")
    print(f"[ALEMBIC] Migrations applied successfully:\n{result.stdout}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _run_alembic_migrations()
    yield


app = FastAPI(title="Education Platform API", lifespan=lifespan)

# Настраиваем список разрешенных адресов
origins = [
    "http://localhost:5173",    # Стандартный порт Vite (React)
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "https://edu-frontend.vercel.app",
    "https://test-front-lac.vercel.app" # Ваш Vercel домен
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,            # Разрешаем запросы с этих адресов
    allow_credentials=True,
    allow_methods=["*"],              # Разрешаем все методы (GET, POST, PUT, DELETE и т.д.)
    allow_headers=["*"],              # Разрешаем все заголовки (включая Authorization)
)

app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(teacher_router)
app.include_router(student_router)
app.include_router(stats_router)  # ← Добавляем эту строку

@app.options("/{rest_of_path:path}")
async def options_handler():
    return Response(status_code=200)

