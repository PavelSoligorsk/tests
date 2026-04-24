from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
import models, dto, auth
from database import get_db
from typing import List

router = APIRouter(prefix="/student", tags=["Student API"])

from sqlalchemy import func, select, case

@router.get("/me", response_model=dto.UserResponseWithStats)
def get_student_profile(
    db: Session = Depends(get_db), 
    current_user: models.User = Depends(auth.get_current_user)
):
    # 1. Подзапрос: считаем макс. балл каждого теста на основе веса задач
    # (2 за открытый вопрос, 1 за тест с вариантами)
    task_points_expr = case(
        (models.Task.is_open_answer == True, 2),
        else_=1
    )

    test_max_points_sub = (
        select(
            models.TestTaskAssociation.test_id,
            func.sum(task_points_expr).label("max_total")
        )
        .join(models.Task, models.TestTaskAssociation.task_id == models.Task.id)
        .group_by(models.TestTaskAssociation.test_id)
        .subquery()
    )

    # 2. Считаем общее кол-во попыток
    total_attempts = db.query(models.TestResult).filter(
        models.TestResult.user_id == current_user.id
    ).count()
    
    # 3. Считаем средний процент успеха (Среднее от: набрано / макс * 100)
    avg_percentage = db.query(
        func.avg(
            (models.TestResult.total_points * 100.0) / test_max_points_sub.c.max_total
        )
    ).join(
        test_max_points_sub, 
        models.TestResult.test_id == test_max_points_sub.c.test_id
    ).filter(
        models.TestResult.user_id == current_user.id,
        test_max_points_sub.c.max_total > 0
    ).scalar() or 0

    return {
        "user": current_user,
        "stats": {
            "total_attempts": total_attempts,
            "avg_score": round(float(avg_percentage), 1)
        }
    }

from sqlalchemy.orm import joinedload

@router.get("/tests", response_model=List[dto.TestResponse])
def get_student_tests(db: Session = Depends(get_db)):
    # Загружаем тесты вместе с задачами, чтобы поле tasks в DTO не было пустым
    return db.query(models.Test)\
             .options(joinedload(models.Test.tasks))\
             .filter(models.Test.is_active == True)\
             .all()

@router.get("/history", response_model=list[dto.TestResultResponse])
def get_my_history(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    # Используем joinedload, чтобы сразу подтянуть данные теста (название и т.д.)
    return db.query(models.TestResult)\
             .options(joinedload(models.TestResult.test))\
             .filter(models.TestResult.user_id == current_user.id)\
             .order_by(models.TestResult.completed_at.desc())\
             .all()

# 4. Получить конкретный тест для прохождения
@router.get("/tests/{test_id}", response_model=dto.TestResponse)
def get_test_for_passing(
    test_id: int, 
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    test = db.query(models.Test).filter(models.Test.id == test_id).first()
    if not test:
        raise HTTPException(status_code=404, detail="Тест не найден")
    return test

@router.post("/tests/{test_id}/submit")
def submit_test_results(
    test_id: int,
    answers: List[dict],
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    test = db.query(models.Test).filter(models.Test.id == test_id).first()
    if not test:
        raise HTTPException(status_code=404, detail="Тест не найден")

    total_points = 0

    # 1. Создаем запись о попытке
    new_result = models.TestResult(
        test_id=test_id,
        user_id=current_user.id,
        total_points=0 
    )
    db.add(new_result)
    db.flush() 

    # 2. Проверяем каждый ответ
    for ans in answers:
        task = db.query(models.Task).filter(models.Task.id == ans['task_id']).first()
        if not task: 
            continue

        user_val = ans['user_answer']
        is_correct = False

        # Логика проверки правильности
        if not task.is_open_answer and isinstance(user_val, list):
            # Множественный выбор
            correct_answers = {a.strip().lower() for a in task.answer.split(',')}
            student_answers = {str(a).strip().lower() for a in user_val}
            is_correct = correct_answers == student_answers
        else:
            # Одиночный ответ или открытый вопрос
            is_correct = str(user_val).strip().lower() == str(task.answer).strip().lower()

        # Начисление баллов в зависимости от типа вопроса
        current_points = 0
        if is_correct:
            # Открытый тип - 2 балла, закрытый (выбор) - 1 балл
            current_points = 2 if task.is_open_answer else 1
            total_points += current_points

        # Сохраняем детальный ответ
        user_answer = models.UserAnswer(
            result_id=new_result.id,
            task_id=task.id,
            user_text_answer=str(user_val),
            is_correct=is_correct,
            points_earned=current_points # Теперь переменная определена
        )
        db.add(user_answer)

    # 3. Обновляем итоговый балл в записи результата
    new_result.total_points = total_points
    db.commit()

    return {
        "status": "success", 
        "score": total_points, 
        "max_score_possible": sum(2 if t.is_open_answer else 1 for t in test.tasks)
    }

@router.get("/results/{result_id}")
def get_detailed_result(

    result_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    # 1. Получаем результат (обязательно с подгрузкой теста через joinedload)
    result = db.query(models.TestResult).options(
        joinedload(models.TestResult.test)
    ).filter(
        models.TestResult.id == result_id,
        models.TestResult.user_id == current_user.id
    ).first()

    if not result:
        raise HTTPException(status_code=404, detail="Результат не найден")

    # 2. Достаем задачи
    all_tasks = (
        db.query(models.Task)
        .join(models.TestTaskAssociation)
        .filter(models.TestTaskAssociation.test_id == result.test_id)
        .order_by(models.Task.topic_number)
        .all()
    )

    # 3. Достаем ответы пользователя
    user_answers = db.query(models.UserAnswer).filter(models.UserAnswer.result_id == result_id).all()
    answers_map = {ua.task_id: ua for ua in user_answers}

    details = []
    total_max_points = 0
    stats = {str(i): {"total": 0, "correct": 0} for i in range(1, 6)}
    
    for task in all_tasks:
        ua = answers_map.get(task.id)
        
        # ЛОГИКА БАЛЛОВ (важно для знаменателя на фронте)
        max_task_points = 2 if task.is_open_answer else 1
        total_max_points += max_task_points
        
        # СТАТИСТИКА ПО СЛОЖНОСТИ
        diff = str(task.difficulty) if task.difficulty else "1"
        if diff in stats:
            stats[diff]["total"] += 1
            if ua and ua.is_correct:
                stats[diff]["correct"] += 1

        # НАПОЛНЯЕМ DETAILS (без этого список пустой!)
        details.append({
            "task_id": task.id,
            "content": task.content,
            "options": task.options,
            "correct_answer": task.answer,
            "user_answer": ua.user_text_answer if ua else "Нет ответа",
            "is_correct": ua.is_correct if ua else False,
            "solution": task.solution,
            "difficulty": task.difficulty  # <--- ОБЯЗАТЕЛЬНО ДОБАВИТЬ
        })

    return {
        "test_title": result.test.title,
        "total_points": result.total_points,  # Сколько набрал
        "max_points": total_max_points,       # Имя поля должно совпадать с фронтом!
        "completed_at": result.completed_at,
        "difficulty_stats": stats,
        "details": details  # Теперь тут есть данные
    }

@router.put("/me", response_model=dto.UserResponse) # Или dto.User, смотря что в схемах
def update_student_profile(
    obj_in: dto.UserUpdate, 
    db: Session = Depends(get_db), 
    current_user: models.User = Depends(auth.get_current_user)
):
    """
    Обновление данных профиля текущего студента
    """
    # Обновляем поля модели из пришедших данных
    update_data = obj_in.dict(exclude_unset=True)
    
    for field in update_data:
        setattr(current_user, field, update_data[field])

    try:
        db.add(current_user)
        db.commit()
        db.refresh(current_user)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail="Ошибка при обновлении профиля")

    return current_user