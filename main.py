from fastapi import FastAPI
import models
from database import engine

from api.auth_api import router as auth_router
from api.admin_api import router as admin_router
from api.teacher_api import router as teacher_router
from api.student_api import router as student_router


from fastapi.middleware.cors import CORSMiddleware # 1. Обязательный импорт
from fastapi.security import OAuth2PasswordRequestForm

# Создание таблиц в базе данных SQLite
models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Education Platform API (SQLite)")

# Настраиваем список разрешенных адресов
origins = [
    "http://localhost:5173",    # Стандартный порт Vite (React)
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "https://edu-frontend.vercel.app"  # Ваш Vercel домен
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


