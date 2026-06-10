from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload
import models, dto, auth
from database import get_db
from typing import List
from models import Task, Test, TestTaskAssociation, User, UserAnswer, TestAssignment
import requests
from dto import ImageUploadResponse
from dto import AllowedEmailResponse
import uuid  # ← добавь эту строку
import boto3
from botocore.config import Config
import re

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
def rebuild_all_static_tests(db: Session = Depends(get_db), current_admin: User = Depends(auth.check_admin)):
    try:
        # 1. Собираем актуальные категории из задач (учитываем topic и section)
        active_categories = db.query(
    Task.task_class, 
    Task.topic_number
).distinct().all()               
        updated_test_ids = []

        for t_class, t_num in active_categories:
            test = db.query(Test).filter(
                Test.target_class == str(t_class),
                Test.target_topic == str(t_num)
            ).first()

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

            relevant_tasks = db.query(Task).filter(
                Task.task_class == t_class,
                Task.topic_number == t_num
            ).order_by(Task.is_open_answer.asc(), Task.difficulty.asc()).all()

            test.tasks = relevant_tasks
            updated_test_ids.append(test.id)

        db.flush()

        # 2. ЖЕСТКАЯ ЗАЧИСТКА (Снизу вверх по иерархии FK)
        bad_tests_query = db.query(Test.id).filter(
            (Test.id.not_in(updated_test_ids)) | (~Test.tasks.any())
        )
        bad_test_ids = [t[0] for t in bad_tests_query.all()]

        if bad_test_ids:
            # 1. Удаляем UserAnswer (через TestResult)
            bad_result_ids = [r[0] for r in db.query(TestResult.id).filter(TestResult.test_id.in_(bad_test_ids)).all()]

            if bad_result_ids:
                db.query(UserAnswer).filter(UserAnswer.result_id.in_(bad_result_ids)).delete(synchronize_session=False)
                db.query(TestResult).filter(TestResult.id.in_(bad_result_ids)).delete(synchronize_session=False)

            # 2. Удаляем связи test_task_association
            db.execute(
                TestTaskAssociation.__table__.delete().where(TestTaskAssociation.test_id.in_(bad_test_ids))
            )

            # 3. Удаляем назначения тестов (TestAssignment)
            db.query(TestAssignment).filter(TestAssignment.test_id.in_(bad_test_ids)).delete(synchronize_session=False)

            # 4. Теперь можно удалять tests
            deleted_count = db.query(Test).filter(Test.id.in_(bad_test_ids)).delete(synchronize_session=False)
        else:
            deleted_count = 0
        
        bad_test_ids = [t[0] for t in bad_tests_query.all()]

        if bad_test_ids:
            bad_result_ids = [r[0] for r in db.query(TestResult.id).filter(TestResult.test_id.in_(bad_test_ids)).all()]

            if bad_result_ids:
                db.query(UserAnswer).filter(UserAnswer.result_id.in_(bad_result_ids)).delete(synchronize_session=False)
                db.query(TestResult).filter(TestResult.id.in_(bad_result_ids)).delete(synchronize_session=False)

            db.execute(
                TestTaskAssociation.__table__.delete().where(TestTaskAssociation.test_id.in_(bad_test_ids))
            )

            deleted_count = db.query(Test).filter(Test.id.in_(bad_test_ids)).delete(synchronize_session=False)
        else:
            deleted_count = 0

        # 3. НОВАЯ ЛОГИКА: Перепроверка ответов пользователей для оставшихся (измененных) тестов
        rechecked_answers_count = 0
        rechecked_results_count = 0
        
        for test_id in updated_test_ids:
            # Получаем все результаты по этому тесту
            results = db.query(TestResult).filter(TestResult.test_id == test_id).all()
            
            for result in results:
                total_points = 0
                answers_changed = False
                
                # Получаем все ответы пользователя для этого результата
                user_answers = db.query(UserAnswer).filter(UserAnswer.result_id == result.id).all()
                
                for ua in user_answers:
                    # Получаем актуальную задачу
                    task = db.query(Task).filter(Task.id == ua.task_id).first()
                    if not task:
                        continue
                    
                    # Проверяем правильность ответа по новой логике
                    was_correct = ua.is_correct
                    is_correct_now = False
                    
                    if task.is_open_answer:
                        # Для открытых ответов: сравниваем строки (без учета регистра и пробелов)
                        is_correct_now = ua.user_text_answer.strip().lower() == task.answer.strip().lower()
                    else:
                        # Для закрытых тестов: проверяем совпадение с правильным ответом
                        if task.options and ua.user_text_answer in task.options:
                            # Если ответ пользователя совпадает с правильным вариантом
                            if task.answer in task.options and ua.user_text_answer == task.answer:
                                is_correct_now = True
                            # Альтернативная логика: правильный ответ может быть индексом
                            elif task.answer.isdigit() and int(task.answer) < len(task.options):
                                if task.options[int(task.answer)] == ua.user_text_answer:
                                    is_correct_now = True
                        # Прямое сравнение с ответом задачи
                        elif ua.user_text_answer == task.answer:
                            is_correct_now = True
                    
                    # Обновляем флажок правильности, если он изменился
                    if was_correct != is_correct_now:
                        ua.is_correct = is_correct_now
                        answers_changed = True
                    
                    # ОБНОВЛЕННАЯ ЛОГИКА БАЛЛОВ:
                    # 2 балла за открытый правильный ответ
                    # 1 балл за закрытый правильный ответ
                    # 0 баллов за неправильный ответ
                    if is_correct_now:
                        if task.is_open_answer:
                            new_points = 2  # Открытый вопрос - 2 балла
                        else:
                            new_points = 1  # Закрытый вопрос (тест) - 1 балл
                    else:
                        new_points = 0
                    
                    if ua.points_earned != new_points:
                        ua.points_earned = new_points
                        answers_changed = True
                    
                    if is_correct_now:
                        total_points += new_points
                
                # Пересчитываем общий балл за тест
                if answers_changed or result.total_points != total_points:
                    old_total = result.total_points
                    result.total_points = total_points
                    rechecked_results_count += 1
                    rechecked_answers_count += len(user_answers)
                    
                    # Логируем изменение (опционально)
                    print(f"TestResult {result.id}: points changed from {old_total} to {total_points}")

        db.commit()
        
        return {
            "status": "success", 
            "message": f"Deleted {deleted_count} empty tests. Rechecked {rechecked_answers_count} answers in {rechecked_results_count} test results."
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Postgres Error: {str(e)}")
  
    
@router.delete("/tasks/{task_id}")
def delete_task(
    task_id: int, 
    db: Session = Depends(get_db), 
    current_admin: models.User = Depends(auth.check_admin)
):
    """Полностью удалить задание из базы данных и всех связанных записей"""
    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Задание не найдено"
        )
    
    try:
        # 1. Удаляем ответы пользователей на эту задачу
        # Без этого Postgres не даст удалить задачу из-за связи в UserAnswer
        db.query(models.UserAnswer).filter(models.UserAnswer.task_id == task_id).delete(synchronize_session=False)

        # 2. Удаляем связи задачи с тестами в ассоциативной таблице
        # SQLAlchemy может делать это сам через relationship, но для надежности в Postgres делаем явно
        db.execute(
            models.TestTaskAssociation.__table__.delete().where(
                models.TestTaskAssociation.task_id == task_id
            )
        )

        # 3. Удаляем саму задачу
        db.delete(task)
        
        db.commit()
        return {"message": f"Задание с ID {task_id} и связанные данные успешно удалены"}
        
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

@router.get("/allowed/emails", response_model=list[AllowedEmailResponse])
def get_allowed_emails(db: Session = Depends(get_db)):
    allowed_emails = db.query(models.AllowedEmail).all()
    
    result = []
    for ae in allowed_emails:
        # Ищем пользователя по username = email
        user = db.query(models.User).filter(models.User.username == ae.email).first()
        
        result.append({
            "email": ae.email,
            "first_name": user.first_name if user else None,
            "last_name": user.last_name if user else None,
            "tg_username": user.tg_username if user else None,
        })
    
    return result

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

import base64
import requests
from dotenv import load_dotenv
import os
load_dotenv()
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY")
R2_ENDPOINT_URL = os.getenv("R2_ENDPOINT_URL")
R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME")
R2_PUBLIC_URL = os.getenv("R2_PUBLIC_URL")

@router.post("/upload-image", response_model=ImageUploadResponse)
async def upload_to_r2(
    payload: dict,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(auth.check_admin)
):
    """
    Загружает изображение в Cloudflare R2 и возвращает прямую ссылку.
    Точная копия логики из test_r2.py
    """
    print("🚀 Начинаем загрузку в Cloudflare R2...")
    
    try:
        # 1. Настраиваем клиент (как в тестовом файле)
        print("📡 Подключаюсь к R2...")
        s3_client = boto3.client(
            's3',
            endpoint_url=R2_ENDPOINT_URL,
            aws_access_key_id=R2_ACCESS_KEY_ID,
            aws_secret_access_key=R2_SECRET_ACCESS_KEY,
            region_name='auto',
            config=Config(signature_version='s3v4')
        )
        print("✅ Клиент создан")
        
        # 2. Получаем base64 из запроса
        image_data = payload.get("image") or payload.get("image_data", "")
        
        if not image_data:
            raise HTTPException(
                status_code=400, 
                detail="Missing image data. Send 'image' or 'image_data' field with base64"
            )
        
        # 3. Убираем префикс data:image/...;base64, если есть
        if "," in image_data:
            image_base64 = image_data.split(",")[1]
        else:
            image_base64 = image_data
        
        # 4. Декодируем base64 в байты (как в тестовом файле)
        print("🖼️ Декодирую изображение...")
        image_bytes = base64.b64decode(image_base64)
        print(f"✅ Размер изображения: {len(image_bytes)} байт")
        
        # 5. Генерируем имя файла (как в тестовом файле)
        filename = f"tasks/{uuid.uuid4().hex}.png"
        print(f"📝 Имя файла: {filename}")
        
        # 6. Загружаем в R2 (как в тестовом файле)
        print("☁️ Загружаю в R2...")
        s3_client.put_object(
            Bucket=R2_BUCKET_NAME,
            Key=filename,
            Body=image_bytes,
            ContentType='image/png',
            CacheControl='max-age=31536000'
        )
        print("✅ Загрузка успешна!")
        
        # 7. Формируем публичную ссылку (как в тестовом файле)
        file_url = f"{R2_PUBLIC_URL}/{filename}"
        
        # 8. Возвращаем ответ
        return ImageUploadResponse(
            url=file_url,
            filename=filename,
            size=len(image_bytes)
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"\n❌ ОШИБКА: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    

# ==================== УПРАВЛЕНИЕ ТЕОРИЕЙ ====================

@router.post("/theory", response_model=dto.TheoryResponse)
def create_theory(
    payload: dto.TheoryCreate,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(auth.check_admin)
):
    """Создать новый теоретический материал"""
    
    # Проверяем, нет ли уже теории с такой комбинацией topic + section
    existing = db.query(models.Theory).filter(
        models.Theory.topic == payload.topic,
        models.Theory.section == payload.section
    ).first()
    
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Теория для темы '{payload.topic}' и раздела '{payload.section}' уже существует"
        )
    
    new_theory = models.Theory(**payload.dict())
    db.add(new_theory)
    db.commit()
    db.refresh(new_theory)
    
    return new_theory

@router.get("/theory/getall", response_model=list[dto.TheoryResponse])
def get_all_theory(
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(auth.check_admin)
):
    """Получить весь теоретический материал"""
    return db.query(models.Theory).order_by(
        models.Theory.topic, 
        models.Theory.section
    ).all()

@router.get("/theory/{theory_id}", response_model=dto.TheoryResponse)
def get_theory_by_id(
    theory_id: int,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(auth.check_admin)
):
    """Получить теорию по ID"""
    theory = db.query(models.Theory).filter(models.Theory.id == theory_id).first()
    
    if not theory:
        raise HTTPException(status_code=404, detail="Теория не найдена")
    
    return theory

@router.get("/theory/by-topic/{topic}/section/{section}", response_model=dto.TheoryResponse)
def get_theory_by_topic_section(
    topic: str,
    section: str,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(auth.check_admin)
):
    """Получить теорию по теме и разделу"""
    theory = db.query(models.Theory).filter(
        models.Theory.topic == topic,
        models.Theory.section == section
    ).first()
    
    if not theory:
        raise HTTPException(
            status_code=404,
            detail=f"Теория для темы '{topic}' и раздела '{section}' не найдена"
        )
    
    return theory

@router.put("/theory/{theory_id}", response_model=dto.TheoryResponse)
def update_theory(
    theory_id: int,
    payload: dto.TheoryUpdate,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(auth.check_admin)
):
    """Обновить теоретический материал"""
    theory = db.query(models.Theory).filter(models.Theory.id == theory_id).first()
    
    if not theory:
        raise HTTPException(status_code=404, detail="Теория не найдена")
    
    # Если меняются topic или section, проверяем уникальность
    if payload.topic is not None or payload.section is not None:
        new_topic = payload.topic if payload.topic is not None else theory.topic
        new_section = payload.section if payload.section is not None else theory.section
        
        # Проверяем, не занята ли новая комбинация
        existing = db.query(models.Theory).filter(
            models.Theory.topic == new_topic,
            models.Theory.section == new_section,
            models.Theory.id != theory_id
        ).first()
        
        if existing:
            raise HTTPException(
                status_code=400,
                detail=f"Теория для темы '{new_topic}' и раздела '{new_section}' уже существует"
            )
    
    # Обновляем поля
    update_data = payload.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(theory, key, value)
    
    db.commit()
    db.refresh(theory)
    
    return theory

@router.delete("/theory/{theory_id}")
def delete_theory(
    theory_id: int,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(auth.check_admin)
):
    """Удалить теоретический материал"""
    theory = db.query(models.Theory).filter(models.Theory.id == theory_id).first()
    
    if not theory:
        raise HTTPException(status_code=404, detail="Теория не найдена")
    
    db.delete(theory)
    db.commit()
    
    return {"message": f"Теория для темы '{theory.topic}' и раздела '{theory.section}' успешно удалена"}

import httpx # Убедитесь, что импорт есть в начале файла

def parse_correct_option_ids(task_answer: str, render_options: list[str]) -> list[int]:
    """
    Универсальный парсер правильных ответов.
    Возвращает список 0-indexed индексов для рендер-бота.
    """
    correct_option_ids = []
    raw_answers = str(task_answer).strip()

    # Сценарий 1: В базе лежит строка с цифрами-указателями вариантов (например, "2,4", " 2 ; 3 ", "1")
    # Регулярка проверяет, что в строке нет ничего, кроме цифр, запятых, точек с запятой и пробелов
    if re.match(r'^[\d\s,;]+$', raw_answers):
        digit_answers = re.findall(r'\d+', raw_answers)
        for num_str in digit_answers:
            idx = int(num_str) - 1  # Переводим из человеческого отсчета (с 1) в кодерский (с 0)
            if 0 <= idx < len(render_options):
                if idx not in correct_option_ids:
                    correct_option_ids.append(idx)
        
        if correct_option_ids:
            return sorted(correct_option_ids)

    # Сценарий 2: В базе лежит сам текст ответа или массив ответов в виде строки (например, "$arcsin\\sqrt{2}$")
    # Дробим строку по популярным разделителям
    clean_answers_list = [a.strip().# Очищаем от возможных случайных внешних кавычек
                          strip('"').strip("'") 
                          for a in re.split(r'[,;|\n]', raw_answers) if a.strip()]

    for idx, opt in enumerate(render_options):
        clean_opt = opt.strip().strip('"').strip("'")
        # Строгое сравнение «один в один», чтобы цифры внутри LaTeX не давали ложных срабатываний
        if any(ans == clean_opt for ans in clean_answers_list):
            correct_option_ids.append(idx)

    # Фолбэк-страховка: если в базе данных вообще пусто или формат совсем сломался,
    # отдаем 0 индекс, чтобы Telegram не упал при отправке
    if not correct_option_ids:
        correct_option_ids.append(0)

    return sorted(correct_option_ids)

@router.post("/tasks/{task_id}/send-to-tg")
async def send_task_to_tg(
    task_id: int,
    chat_id: str,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(auth.check_admin)
):
    """
    Отправляет задачу в указанный Telegram чат через рендер-бот.
    Если у задачи закрытый ответ, генерирует викторину (Quiz) или опрос с множественным выбором.
    """
    # 1. Получаем задачу из БД
    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Задание не найдено")

    # 2. Логика вариантов ответов под новую структуру рендер-бота
    render_options = []
    correct_option_ids = []  # Теперь собираем список индексов правильных ответов
    
    # Задание является тестом (закрытый ответ), если флаг open_answer равен False
    is_quiz = not task.is_open_answer
    
    if is_quiz and task.options:
        # Приводим элементы к строкам и чистим пробелы
        if isinstance(task.options, list):
            render_options = [str(opt).strip() for opt in task.options]
        elif isinstance(task.options, dict):
            render_options = [str(val).strip() for val in task.options.values()]

        correct_option_ids = parse_correct_option_ids(task.answer, render_options)
            
    # Telegram не пропустит опрос, если в нем меньше 2 вариантов ответа
    if is_quiz and len(render_options) < 2:
        is_quiz = False

    # 3. Формируем красивый caption с метаданными (Раздел/Тема/Сложность)
    task_difficulty = int(task.difficulty) if task.difficulty is not None else 1
    difficulty_stars = "⭐" * min(max(1, task_difficulty), 5)
    
    meta_info = f"{task.task_class} | {task.topic_number}"
    if task.section:
        meta_info += f"\n📂 Раздел: {task.section}"
    if task.topic:
        meta_info += f"\n📖 Тема: {task.topic}"

    telegram_caption = (
        f"{meta_info}\n"
        f"🔥 Сложность: {difficulty_stars}\n"
        f"🆔 ID задачи: {task.id}"
    )

    # 4. Формируем обновленный контракт данных (совпадает с моделью MathMessage)
    render_payload = {
        "chat_id": chat_id,
        "latex": task.content.strip(), # Только текст задания (без вариантов, они уйдут в options)
        "caption": telegram_caption,   # Метаданные в текстовое описание под фото
        "is_quiz": is_quiz,
        "options": render_options,     # Массив вариантов, который бот нарисует на картинке
        "correct_option_ids": correct_option_ids, # Массив индексов для создания правильного пулла
        "diff": task.difficulty
    }

    # 5. Безопасная отправка запроса к рендер-боту
    BASE_URL = os.getenv("RENDER_API_URL", "http://localhost:8000")
    
    # Убираем дублирование /send_math, если оно уже зашито в конфиг на Railway
    if BASE_URL.endswith("/send_math"):
        RENDER_API_URL = BASE_URL
    else:
        RENDER_API_URL = f"{BASE_URL.rstrip('/')}/send_math"
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                RENDER_API_URL,
                json=render_payload,
                timeout=30.0
            )
            
            if response.status_code != 200:
                raise HTTPException(
                    status_code=500, 
                    detail=f"Ошибка рендер-бота: {response.text}"
                )
            
            return {"message": "Задача успешно отправлена в Telegram"}
            
        except httpx.RequestError as e:
            raise HTTPException(
                status_code=500, 
                detail=f"Не удалось связаться с рендер-ботом: {str(e)}"
            )