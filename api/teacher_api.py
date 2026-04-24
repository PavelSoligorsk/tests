from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
import models, dto
from database import get_db

router = APIRouter(prefix="/teacher", tags=["Teacher Dashboard"])

# --- УПРАВЛЕНИЕ ТЕСТАМИ ---

@router.get("/tests", response_model=List[dto.TestResponse])
def get_all_tests(db: Session = Depends(get_db)):
    """Получить все созданные тесты"""
    return db.query(models.Test).all()

@router.delete("/tests/{test_id}")
def delete_test(test_id: int, db: Session = Depends(get_db)):
    test = db.query(models.Test).filter(models.Test.id == test_id).first()
    if not test:
        raise HTTPException(status_code=404, detail="Тест не найден")
    db.delete(test)
    db.commit()
    return {"message": "Тест удален"}

# --- УПРАВЛЕНИЕ УЧЕНИКАМИ ---

@router.get("/students")
def get_students(db: Session = Depends(get_db)):
    """Получить список всех учеников с краткой статистикой"""
    students = db.query(models.User).filter(models.User.role == "student").all()
    # В реальном проекте здесь будет агрегация через func.avg(TestResult.total_points)
    return [
        {
            "id": s.id,
            "name": f"{s.first_name} {s.last_name}",
            "username": s.username,
            "avgScore": 85.5, # Заглушка, пока нет расчетов
            "lastActive": "Сегодня"
        } for s in students
    ]

# --- БАНК ЗАДАНИЙ ДЛЯ КОНСТРУКТОРА ---

@router.get("/tasks-bank")
def get_tasks_bank(db: Session = Depends(get_db)):
    """Задания для выбора в конструкторе"""
    return db.query(models.Task).all()