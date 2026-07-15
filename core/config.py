from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite:///./tasks_database.db"  # Значение по умолчанию для локалки

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()