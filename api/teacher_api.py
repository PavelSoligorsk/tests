# ==================== routers/teacher.py ====================
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, case, select as sa_select
import models, dto, auth
from database import get_db
from typing import List, Optional

router = APIRouter(prefix="/teacher", tags=["Teacher API"])


# ==================== ПРОВЕРКА РОЛИ ====================
def check_teacher(user: models.User = Depends(auth.get_current_user)):
    """Проверяет, что пользователь — учитель или админ"""
    if user.role not in ["teacher", "admin"]:
        raise HTTPException(status_code=403, detail="Доступ запрещён. Требуется роль teacher или admin")
    return user


# ==================== БАНК ЗАДАНИЙ ====================

@router.get("/tasks", response_model=List[dto.TaskResponse])
def get_all_tasks(
    task_class: Optional[int] = Query(None, description="Фильтр по классу"),
    topic: Optional[str] = Query(None, description="Фильтр по основной теме (numbers, expressions, equations, functions, geometry)"),
    topic_number: Optional[str] = Query(None, description="Фильтр по номеру темы"),
    section: Optional[str] = Query(None, description="Фильтр по разделу"),
    db: Session = Depends(get_db),
    current_teacher: models.User = Depends(check_teacher)
):
    """
    Получить список заданий с возможностью фильтрации.
    Используется для банка заданий учителя.
    """
    query = db.query(models.Task).order_by(
        models.Task.task_class,
        models.Task.topic_number,
        models.Task.is_open_answer.asc(),
        models.Task.difficulty.asc()
    )
    
    if task_class is not None:
        query = query.filter(models.Task.task_class == str(task_class))
    if topic:
        query = query.filter(models.Task.topic == topic)
    if topic_number:
        query = query.filter(models.Task.topic_number == topic_number)
    if section:
        query = query.filter(models.Task.section == section)
    
    return query.all()


@router.get("/tasks/grouped", response_model=dict)
def get_tasks_grouped(
    db: Session = Depends(get_db),
    current_teacher: models.User = Depends(check_teacher)
):
    """
    Возвращает задания, сгруппированные по классам и номерам тем.
    Нужно фронтенду для отображения дерева банка заданий.
    
    Ответ:
    {
        "grouped": {
            "7": {
                "1": [{task1}, {task2}],
                "2": [{task3}]
            },
            "8": { ... }
        },
        "total_tasks": 150,
        "available_classes": ["7", "8", "9", "10", "11"]
    }
    """
    tasks = db.query(models.Task).order_by(
        models.Task.task_class,
        models.Task.topic_number,
        models.Task.is_open_answer.asc(),
        models.Task.difficulty.asc()
    ).all()
    
    grouped = {}
    for task in tasks:
        cls = str(task.task_class)
        topic_num = str(task.topic_number)
        
        if cls not in grouped:
            grouped[cls] = {}
        if topic_num not in grouped[cls]:
            grouped[cls][topic_num] = []
        
        grouped[cls][topic_num].append({
            "id": task.id,
            "task_class": task.task_class,
            "topic_number": task.topic_number,
            "topic": task.topic,
            "section": task.section,
            "content": task.content,
            "answer": task.answer,
            "hint": task.hint,
            "solution": task.solution,
            "is_open_answer": task.is_open_answer,
            "options": task.options,
            "difficulty": task.difficulty
        })
    
    return {
        "grouped": grouped,
        "total_tasks": len(tasks),
        "available_classes": sorted(grouped.keys(), key=lambda x: int(x))
    }


@router.get("/tasks/{task_id}", response_model=dto.TaskResponse)
def get_single_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_teacher: models.User = Depends(check_teacher)
):
    """Получить одно задание по ID"""
    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Задание не найдено")
    return task


# ==================== КОНСТРУКТОР ТЕСТОВ ====================

@router.get("/tests", response_model=List[dto.TestResponse])
def get_teacher_tests(
    db: Session = Depends(get_db),
    current_teacher: models.User = Depends(check_teacher)
):
    """
    Получить все тесты (в том числе созданные учителем).
    """
    return db.query(models.Test)\
             .options(joinedload(models.Test.tasks))\
             .order_by(models.Test.id.desc())\
             .all()


@router.post("/tests", response_model=dto.TestResponse)
def create_test(
    payload: dto.TestCreate,
    db: Session = Depends(get_db),
    current_teacher: models.User = Depends(check_teacher)
):
    """
    Создать новый тест.
    
    Пример body:
    {
        "title": "Контрольная работа №1",
        "target_class": "9",
        "target_topic": "1",
        "is_autocompile": false,
        "task_ids": [1, 2, 3, 4, 5]
    }
    """
    new_test = models.Test(
        title=payload.title,
        target_class=str(payload.target_class) if payload.target_class else None,
        target_topic=str(payload.target_topic) if payload.target_topic else None,
        is_autocompile=payload.is_autocompile,
        creator_id=current_teacher.id,
        is_active=True
    )
    db.add(new_test)
    db.flush()  # Получаем ID теста
    
    # Привязываем задания, если указаны
    if payload.task_ids:
        tasks = db.query(models.Task).filter(models.Task.id.in_(payload.task_ids)).all()
        new_test.tasks = tasks
    
    db.commit()
    db.refresh(new_test)
    
    # Возвращаем тест с заданиями
    return db.query(models.Test)\
             .options(joinedload(models.Test.tasks))\
             .filter(models.Test.id == new_test.id)\
             .first()


@router.put("/tests/{test_id}", response_model=dto.TestResponse)
def update_test(
    test_id: int,
    payload: dto.TestCreate,
    db: Session = Depends(get_db),
    current_teacher: models.User = Depends(check_teacher)
):
    """Редактировать существующий тест"""
    test = db.query(models.Test).filter(models.Test.id == test_id).first()
    if not test:
        raise HTTPException(status_code=404, detail="Тест не найден")
    
    # Обновляем основные поля
    test.title = payload.title
    test.target_class = str(payload.target_class) if payload.target_class else test.target_class
    test.target_topic = str(payload.target_topic) if payload.target_topic else test.target_topic
    test.is_autocompile = payload.is_autocompile
    
    # Обновляем список заданий
    if payload.task_ids is not None:
        tasks = db.query(models.Task).filter(models.Task.id.in_(payload.task_ids)).all()
        test.tasks = tasks
    
    db.commit()
    db.refresh(test)
    
    return db.query(models.Test)\
             .options(joinedload(models.Test.tasks))\
             .filter(models.Test.id == test.id)\
             .first()


@router.delete("/tests/{test_id}")
def delete_test(
    test_id: int,
    db: Session = Depends(get_db),
    current_teacher: models.User = Depends(check_teacher)
):
    """Удалить тест"""
    test = db.query(models.Test).filter(models.Test.id == test_id).first()
    if not test:
        raise HTTPException(status_code=404, detail="Тест не найден")
    
    # Удаляем связи с задачами
    db.execute(
        models.TestTaskAssociation.__table__.delete().where(
            models.TestTaskAssociation.test_id == test_id
        )
    )
    
    db.delete(test)
    db.commit()
    
    return {"message": "Тест удалён"}


@router.get("/tests/{test_id}", response_model=dto.TestResponse)
def get_test_detail(
    test_id: int,
    db: Session = Depends(get_db),
    current_teacher: models.User = Depends(check_teacher)
):
    """Получить тест с полной информацией о заданиях"""
    test = db.query(models.Test)\
             .options(joinedload(models.Test.tasks))\
             .filter(models.Test.id == test_id)\
             .first()
    if not test:
        raise HTTPException(status_code=404, detail="Тест не найден")
    return test


# ==================== РЕЗУЛЬТАТЫ УЧЕНИКОВ ====================

@router.get("/students")
def get_my_students(
    db: Session = Depends(get_db),
    current_teacher: models.User = Depends(check_teacher)
):
    return db.query(models.User).filter(models.User.role == "student").all()

@router.get("/students/{user_id}/history")
def get_student_history(
    user_id: int,
    db: Session = Depends(get_db),
    current_teacher: models.User = Depends(check_teacher)
):
    """Посмотреть историю тестов конкретного ученика"""
    user = db.query(models.User).filter(
        models.User.id == user_id,
        models.User.role == "student"
    ).first()
    if not user:
        raise HTTPException(status_code=404, detail="Ученик не найден")
    
    results = db.query(models.TestResult)\
                .options(joinedload(models.TestResult.test))\
                .filter(models.TestResult.user_id == user_id)\
                .order_by(models.TestResult.completed_at.desc())\
                .all()
    
    return [
        {
            "test_title": r.test.title if r.test else "Тест удалён",
            "result": {
                "id": r.id,
                "total_points": r.total_points,
                "completed_at": r.completed_at
            }
        } for r in results
    ]


@router.get("/results/{result_id}")
def get_teacher_detailed_result(
    result_id: int,
    db: Session = Depends(get_db),
    current_teacher: models.User = Depends(check_teacher)
):
    """
    Детальный просмотр результата теста ученика.
    Учитель может видеть все ответы.
    """
    result = db.query(models.TestResult).options(
        joinedload(models.TestResult.test),
        joinedload(models.TestResult.user)
    ).filter(models.TestResult.id == result_id).first()

    if not result:
        raise HTTPException(status_code=404, detail="Результат не найден")

    # Получаем все задания теста
    all_tasks = (
        db.query(models.Task)
        .join(models.TestTaskAssociation)
        .filter(models.TestTaskAssociation.test_id == result.test_id)
        .order_by(models.Task.topic_number)
        .all()
    )

    # Получаем ответы ученика
    user_answers = db.query(models.UserAnswer).filter(
        models.UserAnswer.result_id == result_id
    ).all()
    answers_map = {ua.task_id: ua for ua in user_answers}

    details = []
    total_max_points = 0
    difficulty_stats = {}

    for task in all_tasks:
        ua = answers_map.get(task.id)
        is_correct = ua.is_correct if ua else False
        
        diff_level = str(task.difficulty) if task.difficulty else "1"
        
        if diff_level not in difficulty_stats:
            difficulty_stats[diff_level] = {"correct": 0, "total": 0}
        
        difficulty_stats[diff_level]["total"] += 1
        if is_correct:
            difficulty_stats[diff_level]["correct"] += 1

        max_task_points = 2 if task.is_open_answer else 1
        total_max_points += max_task_points
        
        details.append({
            "task_id": task.id,
            "content": task.content,
            "options": task.options,
            "difficulty": diff_level,
            "correct_answer": task.answer,
            "user_answer": ua.user_text_answer if ua else "Нет ответа",
            "is_correct": is_correct,
            "points_earned": ua.points_earned if ua else 0,
            "max_task_points": max_task_points,
            "solution": task.solution,
            "hint": task.hint
        })

    return {
        "test_title": result.test.title,
        "total_points": result.total_points,
        "max_points": total_max_points,
        "completed_at": result.completed_at,
        "difficulty_stats": difficulty_stats,
        "user": {
            "first_name": result.user.first_name,
            "last_name": result.user.last_name,
        },
        "details": details
    }