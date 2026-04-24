from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload
import models, dto, auth
from database import get_db
from typing import List
from models import Task, Test, TestTaskAssociation, User

router = APIRouter(prefix="/admin", tags=["Admin"])

# --- УПРАВЛЕНИЕ ПОЛЬЗОВАТЕЛЯМИ ---

@router.get("/users", response_model=list[dto.UserResponse])
def get_all_users(
    db: Session = Depends(get_db), 
    current_admin: models.User = Depends(auth.check_admin)
):
    """Получить список всех пользователей"""
    return db.query(models.User).all()

@router.patch("/users/{user_id}/role")
def change_user_role(
    user_id: int, 
    new_role: str, 
    db: Session = Depends(get_db), 
    current_admin: models.User = Depends(auth.check_admin)
):
    """Изменить роль пользователя (admin, teacher, student)"""
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    # Проверка, чтобы админ не разжаловал сам себя (опционально)
    if user.id == current_admin.id and new_role != "admin":
        raise HTTPException(status_code=400, detail="Вы не можете снять роль админа с самого себя")

    user.role = new_role
    db.commit()
    return {"message": f"Роль пользователя {user.username} изменена на {new_role}"}

@router.delete("/users/{user_id}")
def delete_user(
    user_id: int, 
    db: Session = Depends(get_db), 
    current_admin: models.User = Depends(auth.check_admin)
):
    """Удалить пользователя из системы"""
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    db.delete(user)
    db.commit()
    return {"message": "Пользователь удален"}

# --- УПРАВЛЕНИЕ ЗАДАНИЯМИ (Tasks) ---

@router.post("/tasks", response_model=dto.TaskResponse)
def create_task(
    payload: dto.TaskCreate, 
    db: Session = Depends(get_db), 
    current_admin: models.User = Depends(auth.check_admin)
):
    """Создать новое задание"""
    new_task = models.Task(**payload.dict())
    db.add(new_task)
    db.commit()
    db.refresh(new_task)
    return new_task

@router.put("/tasks/{task_id}", response_model=dto.TaskResponse)
def update_task(
    task_id: int, 
    payload: dto.TaskCreate, 
    db: Session = Depends(get_db), 
    current_admin: models.User = Depends(auth.check_admin)
):
    """Редактировать существующее задание"""
    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Задание не найдено")
    
    for key, value in payload.dict().items():
        setattr(task, key, value)
    
    db.commit()
    db.refresh(task)
    return task

@router.get("/", response_model=List[dto.TaskResponse])
def get_tasks(db: Session = Depends(get_db),
                  current_admin: models.User = Depends(auth.check_admin)
):
    return db.query(models.Task).all()

@router.get("/{task_id}", response_model=dto.TaskResponse)
def get_task(task_id: int, db: Session = Depends(get_db),
                 current_admin: models.User = Depends(auth.check_admin)
):
    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task

@router.post("/rebuild-all-static-tests")
def rebuild_all_static_tests(db: Session = Depends(get_db), current_admin: models.User = Depends(auth.check_admin)):
    try:
        # 1. Получаем все уникальные комбинации (Класс + Тема), которые реально есть в задачах
        active_categories = db.query(Task.task_class, Task.topic_number).distinct().all()
        
        # Список ID тестов, которые мы обновим (чтобы знать, кого НЕ удалять)
        updated_test_ids = []

        for t_class, t_num in active_categories:
            # Ищем тест для этой категории (все тесты считаем статичными)
            test = db.query(Test).filter(
                Test.target_class == str(t_class),
                Test.target_topic == str(t_num)
            ).first()

            # Если теста под эти задачи нет — создаем
            if not test:
                test = Test(
                    title=f"Тест: {t_class} класс, Тема {t_num}",
                    target_class=str(t_class),
                    target_topic=str(t_num),
                    is_autocompile=True,
                    creator_id=current_admin.id
                )
                db.add(test)
                db.flush()

            # Выгребаем задачи СТРОГО этой категории
            relevant_tasks = db.query(Task).filter(
                Task.task_class == t_class,
                Task.topic_number == t_num
            ).order_by(
                Task.is_open_answer.asc(),
                Task.difficulty.asc()
            ).all()

            # Принудительная синхронизация: всё лишнее из test.tasks вылетит само
            test.tasks = relevant_tasks
            updated_test_ids.append(test.id)

        db.flush()

        # 2. ТОТАЛЬНАЯ ЗАЧИСТКА
        # Удаляем любые тесты, которые:
        # а) Не попали в список обновленных (значит их категории больше нет в Task)
        # б) Или у которых почему-то 0 задач (даже если ID в списке)
        deleted_count = db.query(Test).filter(
            (Test.id.not_in(updated_test_ids)) | (~Test.tasks.any())
        ).delete(synchronize_session=False)

        db.commit()
        return {
            "status": "success", 
            "message": f"Rebuild complete. Active tests: {len(updated_test_ids)}, Deleted: {deleted_count}"
        }
    
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    
@router.delete("/tasks/{task_id}")
def delete_task(
    task_id: int, 
    db: Session = Depends(get_db), 
    current_admin: models.User = Depends(auth.check_admin)
):
    """Полностью удалить задание из базы данных"""
    # 1. Ищем задачу
    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Задание не найдено"
        )
    
    try:
        # 2. Удаляем
        db.delete(task)
        db.commit()
        return {"message": f"Задание с ID {task_id} успешно удалено"}
        
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
            detail=f"Ошибка при удалении: {str(e)}"
        )
    
from sqlalchemy import func
from models import TestResult, Test

from sqlalchemy import func, select, case

@router.get("/users/{user_id}/profile", response_model=dto.UserResponseWithStats)
def get_user_profile(
    user_id: int, 
    db: Session = Depends(get_db), 
    current_admin: models.User = Depends(auth.check_admin)
):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    # 1. Подзапрос для расчета макс. баллов каждого теста (через ассоциацию с задачами)
    # Используем твою логику: 2 за открытый, 1 за выбор
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

    # 2. Считаем статистику
    results_query = db.query(models.TestResult).filter(models.TestResult.user_id == user_id)
    total_attempts = results_query.count()
    
    # 3. Расчет среднего процента успеха
    # Соединяем результаты с нашим подзапросом макс. баллов
    avg_success_rate = db.query(
        func.avg(
            (models.TestResult.total_points * 100.0) / test_max_points_sub.c.max_total
        )
    ).join(
        test_max_points_sub, 
        models.TestResult.test_id == test_max_points_sub.c.test_id
    ).filter(
        models.TestResult.user_id == user_id,
        test_max_points_sub.c.max_total > 0
    ).scalar() or 0

    return {
        "user": user,
        "stats": {
            "total_attempts": total_attempts,
            "avg_score": round(float(avg_success_rate), 1), # Теперь это средний %
            "last_activity": results_query.order_by(models.TestResult.id.desc()).limit(5).all()
        }
    }

# --- УПРАВЛЕНИЕ ДОСТУПОМ (Allowed Emails) ---

@router.get("/allowed/emails") # Убрали response_model
def get_allowed_emails(db: Session = Depends(get_db)):
    # Просто возвращаем результат запроса как есть
    return db.query(models.AllowedEmail).all()

@router.post("/allowed-emails") # Убрали response_model
def add_allowed_email(payload: dict, db: Session = Depends(get_db)):
    # Используем payload: dict, чтобы не зависеть от классов
    email_value = payload.get("email")
    
    if not email_value:
        raise HTTPException(status_code=400, detail="Email is required")

    exists = db.query(models.AllowedEmail).filter(models.AllowedEmail.email == email_value).first()
    if exists:
        raise HTTPException(status_code=400, detail="Email уже в списке")
    
    new_email = models.AllowedEmail(email=email_value)
    db.add(new_email)
    db.commit()
    db.refresh(new_email)
    return new_email

@router.delete("/allowed-emails/{email}")
def delete_allowed_email(email: str, db: Session = Depends(get_db)):
    allowed = db.query(models.AllowedEmail).filter(models.AllowedEmail.email == email).first()
    if not allowed:
        raise HTTPException(status_code=404, detail="Email не найден")
    
    db.delete(allowed)
    db.commit()
    return {"status": "ok", "message": f"Доступ для {email} аннулирован"}

@router.get("/users/{user_id}/history")
def get_user_history_for_admin(
    user_id: int,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(auth.check_admin)
):
    results = db.query(models.TestResult)\
                .options(joinedload(models.TestResult.test))\
                .filter(models.TestResult.user_id == user_id)\
                .order_by(models.TestResult.completed_at.desc())\
                .all()
    
    # Название теста + результат (объект)
    return [
        {
            "test_title": r.test.title if r.test else "Тест удален",
            "result": {
                "id": r.id,
                "total_points": r.total_points,
                "completed_at": r.completed_at
            }
        } for r in results
    ]

@router.get("/results/{result_id}")
def get_admin_detailed_result(
    result_id: int,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(auth.check_admin)
):
    # 1. Получаем результат, данные теста и пользователя
    result = db.query(models.TestResult).options(
        joinedload(models.TestResult.test),
        joinedload(models.TestResult.user)
    ).filter(models.TestResult.id == result_id).first()

    if not result:
        raise HTTPException(status_code=404, detail="Результат не найден")

    # 2. Получаем все задачи этого теста
    all_tasks = (
        db.query(models.Task)
        .join(models.TestTaskAssociation)
        .filter(models.TestTaskAssociation.test_id == result.test_id)
        .order_by(models.Task.topic_number)
        .all()
    )

    # 3. Получаем ответы пользователя
    user_answers = db.query(models.UserAnswer).filter(models.UserAnswer.result_id == result_id).all()
    answers_map = {ua.task_id: ua for ua in user_answers}

    details = []
    total_max_points = 0
    
    # --- НОВАЯ ЛОГИКА СТАТИСТИКИ ---
    # Структура: { "1": {"correct": 0, "total": 0}, "2": ... }
    difficulty_stats = {}

    for task in all_tasks:
        ua = answers_map.get(task.id)
        is_correct = ua.is_correct if ua else False
        
        # Определяем сложность (если в базе нет, ставим 1 по умолчанию)
        diff_level = str(task.difficulty) if hasattr(task, 'difficulty') and task.difficulty else "1"
        
        # Инициализируем уровень в статистике, если его еще нет
        if diff_level not in difficulty_stats:
            difficulty_stats[diff_level] = {"correct": 0, "total": 0}
        
        # Обновляем счетчики сложности
        difficulty_stats[diff_level]["total"] += 1
        if is_correct:
            difficulty_stats[diff_level]["correct"] += 1

        # ЛОГИКА БАЛЛОВ
        max_task_points = 2 if task.is_open_answer else 1
        total_max_points += max_task_points
        
        details.append({
            "task_id": task.id,
            "content": task.content,
            "options": task.options,
            "difficulty": diff_level, # Добавили поле для фронта
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
        "difficulty_stats": difficulty_stats,  # ТЕПЕРЬ ПЕРЕДАЕТСЯ НА ФРОНТ
        "user": {
            "first_name": result.user.first_name,
            "last_name": result.user.last_name,
        },
        "details": details
    }