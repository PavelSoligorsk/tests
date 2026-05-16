from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload, Query
from sqlalchemy import func, select, case
import models, dto, auth
from database import get_db
from typing import List, Optional
from datetime import datetime

router = APIRouter(prefix="/student", tags=["Student API"])


@router.get("/me", response_model=dto.UserResponseWithStats)
def get_student_profile(
    db: Session = Depends(get_db), 
    current_user: models.User = Depends(auth.get_current_user)
):
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

    total_attempts = db.query(models.TestResult).filter(
        models.TestResult.user_id == current_user.id
    ).count()
    
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


@router.get("/tests", response_model=List[dto.TestResponse])
def get_student_tests(db: Session = Depends(get_db)):
    """
    Получить тесты для студента.
    Возвращает ТОЛЬКО autocompile тесты (is_autocompile != False).
    """
    return db.query(models.Test)\
             .options(joinedload(models.Test.tasks))\
             .filter(
                 models.Test.is_active == True,
                 (models.Test.is_autocompile == True) | (models.Test.is_autocompile == None)
             )\
             .all()

@router.get("/history")  # ← Убрал response_model, возвращаем dict вручную
def get_my_history(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    """
    История попыток студента.
    Защита от удалённых тестов — если тест удалён, показываем "Тест удалён".
    """
    results = db.query(models.TestResult)\
                .options(joinedload(models.TestResult.test))\
                .filter(models.TestResult.user_id == current_user.id)\
                .order_by(models.TestResult.completed_at.desc())\
                .all()
    
    # Формируем ответ вручную, проверяя каждый test
    history = []
    for r in results:
        history.append({
            "id": r.id,
            "test_id": r.test_id if r.test_id is not None else 0,
            "user_id": r.user_id,
            "total_points": r.total_points or 0,
            "completed_at": r.completed_at,
            "test_title": r.test.title if r.test else "Тест удалён",
            "test": {
                "id": r.test.id,
                "title": r.test.title
            } if r.test else None
        })
    
    return history


@router.get("/tests/{test_id}", response_model=dto.TestResponse)
def get_test_for_passing(
    test_id: int, 
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    test = db.query(models.Test)\
             .options(joinedload(models.Test.tasks))\
             .filter(models.Test.id == test_id)\
             .first()
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
    test = db.query(models.Test)\
             .options(joinedload(models.Test.tasks))\
             .filter(models.Test.id == test_id)\
             .first()
    if not test:
        raise HTTPException(status_code=404, detail="Тест не найден")

    total_points = 0

    new_result = models.TestResult(
        test_id=test_id,
        user_id=current_user.id,
        total_points=0 
    )
    db.add(new_result)
    db.flush() 

    for ans in answers:
        task = db.query(models.Task).filter(models.Task.id == ans['task_id']).first()
        if not task: 
            continue

        user_val = ans['user_answer']
        is_correct = False

        if not task.is_open_answer and isinstance(user_val, list):
            correct_answers = {a.strip().lower() for a in task.answer.split(',')}
            student_answers = {str(a).strip().lower() for a in user_val}
            is_correct = correct_answers == student_answers
        else:
            is_correct = str(user_val).strip().lower() == str(task.answer).strip().lower()

        current_points = 0
        if is_correct:
            current_points = 2 if task.is_open_answer else 1
            total_points += current_points

        user_answer = models.UserAnswer(
            result_id=new_result.id,
            task_id=task.id,
            user_text_answer=str(user_val),
            is_correct=is_correct,
            points_earned=current_points
        )
        db.add(user_answer)

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
    result = db.query(models.TestResult).options(
        joinedload(models.TestResult.test)
    ).filter(
        models.TestResult.id == result_id,
        models.TestResult.user_id == current_user.id
    ).first()

    if not result:
        raise HTTPException(status_code=404, detail="Результат не найден")

    # Защита от удалённого теста
    if not result.test:
        return {
            "test_title": "Тест удалён",
            "total_points": result.total_points or 0,
            "max_points": 0,
            "completed_at": result.completed_at,
            "difficulty_stats": {},
            "details": []
        }

    all_tasks = (
        db.query(models.Task)
        .join(models.TestTaskAssociation)
        .filter(models.TestTaskAssociation.test_id == result.test_id)
        .order_by(models.Task.topic_number)
        .all()
    )

    user_answers = db.query(models.UserAnswer)\
                     .filter(models.UserAnswer.result_id == result_id)\
                     .all()
    answers_map = {ua.task_id: ua for ua in user_answers}

    details = []
    total_max_points = 0
    stats = {str(i): {"total": 0, "correct": 0} for i in range(1, 6)}
    
    for task in all_tasks:
        ua = answers_map.get(task.id)
        
        max_task_points = 2 if task.is_open_answer else 1
        total_max_points += max_task_points
        
        diff = str(task.difficulty) if task.difficulty else "1"
        if diff in stats:
            stats[diff]["total"] += 1
            if ua and ua.is_correct:
                stats[diff]["correct"] += 1

        details.append({
            "task_id": task.id,
            "content": task.content,
            "options": task.options,
            "correct_answer": task.answer,
            "user_answer": ua.user_text_answer if ua else "Нет ответа",
            "is_correct": ua.is_correct if ua else False,
            "solution": task.solution,
            "difficulty": task.difficulty
        })

    return {
        "test_title": result.test.title,
        "total_points": result.total_points or 0,
        "max_points": total_max_points,
        "completed_at": result.completed_at,
        "difficulty_stats": stats,
        "details": details
    }


@router.put("/me", response_model=dto.UserResponse)
def update_student_profile(
    obj_in: dto.UserUpdate, 
    db: Session = Depends(get_db), 
    current_user: models.User = Depends(auth.get_current_user)
):
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

@router.get("/my-assignments")
def get_my_assignments(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    """Студент видит назначенные ему тесты"""
    assignments = db.query(models.TestAssignment).filter(
        models.TestAssignment.user_id == current_user.id
    ).order_by(models.TestAssignment.assigned_at.desc()).all()
    
    result = []
    for assignment in assignments:
        test = db.query(models.Test).options(
            joinedload(models.Test.tasks)
        ).filter(models.Test.id == assignment.test_id).first()
        
        tasks_count = len(test.tasks) if test else 0
        
        result.append({
            "assignment_id": assignment.id,
            "test_id": assignment.test_id,
            "test_title": test.title if test else "Тест удалён",
            "target_class": test.target_class if test else "",
            "target_topic": test.target_topic if test else "",
            "is_autocompile": test.is_autocompile if test else None,
            "tasks": [{"id": t.id, "content": t.content} for t in (test.tasks if test else [])],
            "assigned_at": assignment.assigned_at,
            "due_date": assignment.due_date,
            "is_completed": assignment.is_completed,
            "completed_at": assignment.completed_at,
            "total_tasks": tasks_count,
            "time_left": str(assignment.due_date - datetime.datetime.utcnow()) if assignment.due_date else None
        })
    
    return result


@router.post("/start-test/{test_id}")
def start_assigned_test(
    test_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    """Студент начинает выполнение назначенного теста"""
    # Проверяем, что тест назначен этому студенту
    assignment = db.query(models.TestAssignment).filter(
        models.TestAssignment.test_id == test_id,
        models.TestAssignment.user_id == current_user.id,
        models.TestAssignment.is_completed == False
    ).first()
    
    if not assignment:
        raise HTTPException(
            status_code=403, 
            detail="Тест не назначен вам или уже выполнен"
        )
    
    # Проверяем дедлайн
    if assignment.due_date and assignment.due_date < datetime.datetime.utcnow():
        raise HTTPException(status_code=400, detail="Срок выполнения теста истёк")
    
    # Здесь вызываем логику начала теста (создание TestResult)
    test = db.query(models.Test).options(
        joinedload(models.Test.tasks)
    ).filter(models.Test.id == test_id).first()
    
    if not test or not test.tasks:
        raise HTTPException(status_code=404, detail="Тест не содержит заданий")
    
    # Создаём результат (попытку)
    new_result = models.TestResult(
        test_id=test_id,
        user_id=current_user.id,
        total_points=0
    )
    db.add(new_result)
    db.commit()
    db.refresh(new_result)
    
    # Возвращаем задания теста
    tasks = []
    for task in test.tasks:
        tasks.append({
            "id": task.id,
            "content": task.content,
            "options": task.options,
            "is_open_answer": task.is_open_answer,
            "difficulty": task.difficulty,
            # НЕ возвращаем правильный ответ!
        })
    
    return {
        "result_id": new_result.id,
        "test_title": test.title,
        "tasks": tasks,
        "time_limit": None  # Можно добавить ограничение по времени
    }