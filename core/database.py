from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
from dotenv import load_dotenv

load_dotenv()

# Берём URL из переменной окружения (Railway, локальный PostgreSQL и т.д.)
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError(
        "DATABASE_URL не задан. Укажите PostgreSQL URL в переменной окружения.\n"
        "Пример для локальной разработки:\n"
        '  DATABASE_URL="postgresql://postgres:postgres@localhost:5432/education_platform"\n'
        "Его можно указать в .env файле или через export/установку переменной."
    )

# Для PostgreSQL connect_args обычно пустые
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