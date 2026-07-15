from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os

# Пытаемся взять URL из переменных окружения (Railway)
DATABASE_URL = os.getenv("DATABASE_URL")

# Если переменной нет (локальная разработка) — используем SQLite
if not DATABASE_URL:
    DATABASE_URL = "sqlite:///./tasks_database.db"
    # Для SQLite нужен этот параметр
    connect_args = {"check_same_thread": False}
else:
    # Для PostgreSQL этот параметр не нужен
    connect_args = {}

# Создаем engine
engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()