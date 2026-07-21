from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/education_platform"  # Для локальной разработки
    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()