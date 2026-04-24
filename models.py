import enum
from sqlalchemy import Column, Integer, String, Boolean, JSON, ForeignKey, Enum, Text, DateTime
from sqlalchemy.orm import relationship
from database import Base
import datetime

class UserRole(str, enum.Enum):
    ADMIN = "admin"
    TEACHER = "teacher"
    STUDENT = "student"

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(String, default=UserRole.STUDENT)
    
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    tg_username = Column(String, nullable=True)

    # ИСПРАВЛЕННЫЕ СВЯЗИ:
    # 1. Вместо прямых ответов ссылаемся на "Результаты тестов" (попытки)
    test_results = relationship("TestResult", back_populates="user")
    
    # 2. Оставляем связь для учителей
    created_tests = relationship("Test", back_populates="creator")

class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    
    # Основная информация
    task_class = Column(String(50), nullable=False, index=True) 
    topic_number = Column(String(50), nullable=False, index=True)
    
    # Контент (используем Text для больших объемов Markdown)
    content = Column(Text, nullable=False) # Текст задачи + Markdown ссылки на фото
    hint = Column(Text, nullable=True)    # Подсказка
    solution = Column(Text, nullable=True) # Полное решение
    
    # Ответы
    answer = Column(String, nullable=False) # Правильный ответ
    is_open_answer = Column(Boolean, default=False) # True - число/текст, False - выбор варианта
    options = Column(JSON, nullable=True) # Список вариантов ["1", "2", "3", "4"]
    difficulty = Column(Integer, default=1, nullable=False)

class Test(Base):
    __tablename__ = "tests"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=True) # Название теста
    creator_id = Column(Integer, ForeignKey("users.id"))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    target_class = Column(String(50), nullable=True) 
    target_topic = Column(String(50), nullable=True)
    is_autocompile = Column(Boolean, default=True) # Флаг: собирать ли задачи по фильтру
    
    creator = relationship("User", back_populates="created_tests")
    tasks = relationship("Task", secondary="test_task_association")
    
    # Теперь тест ссылается на результаты (попытки прохождения)
    results = relationship("TestResult", back_populates="test")

class TestResult(Base):
    __tablename__ = "test_results"
    id = Column(Integer, primary_key=True, index=True)
    test_id = Column(Integer, ForeignKey("tests.id"))
    user_id = Column(Integer, ForeignKey("users.id"))
    
    total_points = Column(Integer, default=0)
    completed_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    test = relationship("Test", back_populates="results")
    
    # ИСПРАВЛЕНО: добавляем back_populates, чтобы User видел свои результаты
    user = relationship("User", back_populates="test_results") 
    
    answers = relationship("UserAnswer", back_populates="result")

class UserAnswer(Base):
    __tablename__ = "user_answers"
    id = Column(Integer, primary_key=True, index=True)
    
    result_id = Column(Integer, ForeignKey("test_results.id"))
    task_id = Column(Integer, ForeignKey("tasks.id"))
    
    user_text_answer = Column(String, nullable=False)
    is_correct = Column(Boolean, default=False)
    points_earned = Column(Integer, default=0)
    
    # Здесь НЕТ user_id, поэтому UserAnswer не может иметь back_populates="user"
    result = relationship("TestResult", back_populates="answers")
    task = relationship("Task")

class TestTaskAssociation(Base):
    __tablename__ = "test_task_association"
    test_id = Column(Integer, ForeignKey("tests.id"), primary_key=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), primary_key=True)

class AllowedEmail(Base):
    __tablename__ = "allowed_emails"
    
    # Email теперь и ID, и уникальное поле
    email = Column(String(255), primary_key=True, index=True, nullable=False)