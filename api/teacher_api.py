# ==================== routers/teacher.py ====================
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, case, select as sa_select
import models, dto, auth
from database import get_db
from typing import List, Optional
import datetime

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


@router.get("/tasks-grouped")
def get_tasks_grouped(
    db: Session = Depends(get_db),
    current_teacher: models.User = Depends(check_teacher)
):
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
    
    # Безопасная сортировка: числа первыми, текст в конце
    def sort_key(cls):
        if cls.isdigit():
            return (0, int(cls))  # Числа сортируем как числа
        else:
            return (1, cls)  # Текст сортируем по алфавиту
    
    return {
        "grouped": grouped,
        "total_tasks": len(tasks),
        "available_classes": sorted(grouped.keys(), key=sort_key)
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
    Получить тесты. Если пользователь - учитель, возвращаются только его тесты.
    Если администратор - все тесты.
    """
    query = db.query(models.Test).options(joinedload(models.Test.tasks))
    if current_teacher.role == "teacher":
        query = query.filter(models.Test.creator_id == current_teacher.id)
    return query.order_by(models.Test.id.desc()).all()


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

def _check_test_owner(test_id: int, teacher_id: int, db: Session):
    """Проверяет, что тест существует и принадлежит текущему учителю"""
    test = db.query(models.Test).filter(models.Test.id == test_id).first()
    if not test:
        raise HTTPException(status_code=404, detail="Тест не найден")
    if test.creator_id != teacher_id:
        raise HTTPException(status_code=403, detail="У вас нет доступа к этому тесту")
    return test

@router.put("/tests/{test_id}", response_model=dto.TestResponse)
def update_test(
    test_id: int,
    payload: dto.TestCreate,
    db: Session = Depends(get_db),
    current_teacher: models.User = Depends(check_teacher)
):
    test = _check_test_owner(test_id, current_teacher.id, db)

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
    """Удалить тест со всеми связанными данными"""
    test = db.query(models.Test).filter(models.Test.id == test_id).first()
    if not test:
        raise HTTPException(status_code=404, detail="Тест не найден")
    
    if current_teacher.role == "teacher" and test.creator_id != current_teacher.id:
        raise HTTPException(status_code=403, detail="Вы не можете удалить этот тест")
    
    try:
        # 1. Удаляем результаты прохождения теста
        db.query(models.TestResult).filter(
            models.TestResult.test_id == test_id
        ).delete()
        
        # 2. Удаляем все назначения
        db.query(models.TestAssignment).filter(
            models.TestAssignment.test_id == test_id
        ).delete()
        
        # 3. Удаляем связи с задачами
        db.query(models.TestTaskAssociation).filter(
            models.TestTaskAssociation.test_id == test_id
        ).delete()
        
        # 4. Удаляем сам тест
        db.delete(test)
        
        db.commit()
        
        return {"message": f"Тест #{test_id} и все связанные данные удалены"}
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Ошибка при удалении: {str(e)}")

@router.get("/tests/{test_id}", response_model=dto.TestResponse)
def get_test_detail(
    test_id: int,
    db: Session = Depends(get_db),
    current_teacher: models.User = Depends(check_teacher)
):
    """Получить тест с полной информацией о заданиях (только свои для учителя)"""
    test = db.query(models.Test)\
             .options(joinedload(models.Test.tasks))\
             .filter(models.Test.id == test_id)\
             .first()
    
    if not test:
        raise HTTPException(status_code=404, detail="Тест не найден")
    
    # Если текущий пользователь – учитель (не админ), проверяем владельца
    if current_teacher.role == "teacher" and test.creator_id != current_teacher.id:
        raise HTTPException(status_code=403, detail="У вас нет доступа к этому тесту")
    
    return test

# ==================== РЕЗУЛЬТАТЫ УЧЕНИКОВ ====================

@router.get("/students")
def get_my_students(
    db: Session = Depends(get_db),
    current_teacher: models.User = Depends(check_teacher)
):
    """Получить список учеников, привязанных к этому учителю"""
    # Находим все связи teacher_students, где teacher_id = current_teacher.id
    student_ids = db.query(models.TeacherStudent.student_id).filter(
        models.TeacherStudent.teacher_id == current_teacher.id
    ).subquery()
    
    students = db.query(models.User).filter(
        models.User.role == "student",
        models.User.id.in_(student_ids)
    ).all()
    
    return students
# api/student_api.py — исправь эндпоинт /history

# api/teacher_api.py

def _check_student_belongs_to_teacher(db: Session, student_id: int, teacher_id: int):
    link = db.query(models.TeacherStudent).filter(
        models.TeacherStudent.teacher_id == teacher_id,
        models.TeacherStudent.student_id == student_id
    ).first()
    if not link:
        raise HTTPException(status_code=403, detail="У вас нет доступа к этому ученику")

@router.get("/students-profile/{user_id}")
def get_student_profile(
    user_id: int,
    db: Session = Depends(get_db),
    current_teacher: models.User = Depends(check_teacher)
):
    
    _check_student_belongs_to_teacher(db, user_id, current_teacher.id)

    """Профиль ученика"""
    user = db.query(models.User).filter(
        models.User.id == user_id,
        models.User.role == "student"
    ).first()
    
    if not user:
        raise HTTPException(status_code=404, detail="Ученик не найден")

    total_attempts = db.query(models.TestResult).filter(
        models.TestResult.user_id == user_id
    ).count()

    return {
        "user": {
            "id": user.id,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "role": user.role,
            "phone": user.phone,
            "tg_username": user.tg_username
        },
        "stats": {
            "total_attempts": total_attempts,
            "avg_score": 0
        }
    }


@router.get("/students-history/{user_id}")
def get_student_history(
    user_id: int,
    db: Session = Depends(get_db),
    current_teacher: models.User = Depends(check_teacher)
):
    _check_student_belongs_to_teacher(db, user_id, current_teacher.id)

    """История тестов ученика"""
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
                "total_points": r.total_points or 0,
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
    Учитель видит все ответы, правильные ответы и решения.
    """
    result = db.query(models.TestResult).options(
        joinedload(models.TestResult.test),
        joinedload(models.TestResult.user)
    ).filter(models.TestResult.id == result_id).first()

    _check_student_belongs_to_teacher(db, result.user.id, current_teacher.id)


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
            "user": {
                "first_name": result.user.first_name if result.user else "Неизвестный",
                "last_name": result.user.last_name if result.user else ""
            },
            "details": []
        }

    # Получаем все задания теста
    all_tasks = (
        db.query(models.Task)
        .join(models.TestTaskAssociation)
        .filter(models.TestTaskAssociation.test_id == result.test_id)
        .order_by(models.Task.topic_number)
        .all()
    )

    # Получаем ответы ученика
    user_answers = db.query(models.UserAnswer)\
                     .filter(models.UserAnswer.result_id == result_id)\
                     .all()
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
        "total_points": result.total_points or 0,
        "max_points": total_max_points,
        "completed_at": result.completed_at,
        "difficulty_stats": difficulty_stats,
        "user": {
            "first_name": result.user.first_name if result.user else "Неизвестный",
            "last_name": result.user.last_name if result.user else ""
        },
        "details": details
    }

# В routers/teacher.py добавьте:

# ==================== НАЗНАЧЕНИЕ ТЕСТОВ ====================

@router.post("/assign-test", response_model=List[dto.TestAssignmentResponse])
def assign_test_to_students(
    assignment: dto.TestAssignmentCreate,
    db: Session = Depends(get_db),
    current_teacher: models.User = Depends(check_teacher)
):
    


    """
    Назначить тест одному или нескольким студентам.
    
    Пример body:
    {
        "test_id": 1,
        "user_ids": [2, 3, 5],
        "due_date": "2024-12-31T23:59:59"
    }
    """
    # Проверяем, что тест существует
    test = db.query(models.Test).filter(models.Test.id == assignment.test_id).first()
    if not test:
        raise HTTPException(status_code=404, detail="Тест не найден")
    
            # Проверяем, что тест принадлежит текущему учителю (или админу)
    if current_teacher.role == "teacher" and test.creator_id != current_teacher.id:
        raise HTTPException(status_code=403, detail="Вы не можете назначать этот тест")
    
    # Проверяем, что все указанные пользователи - студенты
    students = db.query(models.User).filter(
        models.User.id.in_(assignment.user_ids),
        models.User.role == "student"
    ).all()
    
    if len(students) != len(assignment.user_ids):
        raise HTTPException(status_code=400, detail="Некоторые пользователи не найдены или не являются студентами")
    
        # После проверки студентов, добавьте фильтр по teacher_students
    assigned_students = db.query(models.TeacherStudent).filter(
        models.TeacherStudent.teacher_id == current_teacher.id,
        models.TeacherStudent.student_id.in_(assignment.user_ids)
    ).all()
    if len(assigned_students) != len(assignment.user_ids):
        # Найдём, каких студентов нет в списке
        assigned_ids = {s.student_id for s in assigned_students}
        missing = [uid for uid in assignment.user_ids if uid not in assigned_ids]
        raise HTTPException(status_code=403, detail=f"Вы не можете назначать тесты студентам: {missing}")

    # Создаём назначения
    created_assignments = []
    for user_id in assignment.user_ids:
        # Проверяем, не назначен ли уже этот тест студенту
        existing = db.query(models.TestAssignment).filter(
            models.TestAssignment.test_id == assignment.test_id,
            models.TestAssignment.user_id == user_id
        ).first()
        
        if existing:
            continue  # Пропускаем уже назначенные
        
        new_assignment = models.TestAssignment(
            test_id=assignment.test_id,
            user_id=user_id,
            due_date=assignment.due_date,
            assigned_at=datetime.datetime.utcnow()
        )
        db.add(new_assignment)
        created_assignments.append(new_assignment)
    
    db.commit()
    
    # Загружаем созданные назначения с дополнительной информацией
    result = []
    for ca in created_assignments:
        db.refresh(ca)
        student = db.query(models.User).filter(models.User.id == ca.user_id).first()
        result.append({
            "id": ca.id,
            "test_id": ca.test_id,
            "test_title": test.title,
            "user_id": ca.user_id,
            "student_name": f"{student.first_name} {student.last_name}" if student else "Неизвестный",
            "assigned_at": ca.assigned_at,
            "due_date": ca.due_date,
            "is_completed": ca.is_completed,
            "completed_at": ca.completed_at
        })
    
    return result


@router.get("/test/{test_id}/assignments", response_model=List[dto.TestAssignmentResponse])
def get_test_assignments(
    test_id: int,
    db: Session = Depends(get_db),
    current_teacher: models.User = Depends(check_teacher)
):
    """
    Получить список студентов, которым назначен тест.
    Для каждого назначения вычисляется реальный статус выполнения
    (наличие завершённого TestResult).
    """
    # 1. Проверяем, что тест существует
    test = db.query(models.Test).filter(models.Test.id == test_id).first()
    if not test:
        raise HTTPException(status_code=404, detail="Тест не найден")
    
    # 2. Проверяем, что тест принадлежит текущему учителю (или админу)
    if current_teacher.role == "teacher" and test.creator_id != current_teacher.id:
        raise HTTPException(status_code=403, detail="Вы не можете просматривать назначения этого теста")
    
    # 3. Получаем все назначения для этого теста
    assignments = db.query(models.TestAssignment).filter(
        models.TestAssignment.test_id == test_id
    ).order_by(models.TestAssignment.assigned_at.desc()).all()
    
    # 4. За один запрос получаем все завершённые результаты для этого теста
    #    (группируем по user_id и берём последний по дате)
    from sqlalchemy import func
    subq = db.query(
        models.TestResult.user_id,
        func.max(models.TestResult.completed_at).label('max_completed_at')
    ).filter(models.TestResult.test_id == test_id)\
     .group_by(models.TestResult.user_id).subquery()

    latest_results = db.query(models.TestResult).join(
        subq,
        (models.TestResult.user_id == subq.c.user_id) &
        (models.TestResult.completed_at == subq.c.max_completed_at)
    ).all()

    # Собираем словарь {user_id: TestResult}
    results_map = {r.user_id: r for r in latest_results}
    
    # 5. Формируем ответ
    result = []
    for assignment in assignments:
        student = db.query(models.User).filter(models.User.id == assignment.user_id).first()
        
        latest_result = results_map.get(assignment.user_id)
        is_completed = latest_result is not None
        completed_at = latest_result.completed_at if latest_result else None
        total_points = latest_result.total_points if latest_result else None
        result_id = latest_result.id if latest_result else None
        
        result.append({
            "id": assignment.id,
            "test_id": assignment.test_id,
            "test_title": test.title,
            "user_id": assignment.user_id,
            "student_name": f"{student.first_name} {student.last_name}" if student else "Неизвестный",
            "student_username": student.username if student else None,
            "assigned_at": assignment.assigned_at,
            "due_date": assignment.due_date,
            "is_completed": is_completed,          # реальный статус из TestResult
            "completed_at": completed_at,          # дата завершения из TestResult
            "total_tasks": len(test.tasks) if test.tasks else 0,
            "total_points": total_points,          # набранные баллы
            "result_id": result_id                 # ID результата для перехода
        })
    
    # Сортируем: сначала невыполненные, потом по имени
    result.sort(key=lambda x: (x['is_completed'], x['student_name']))
    
    return result

@router.get("/student/{student_id}/assignments", response_model=List[dto.TestAssignmentResponse])
def get_student_assignments(
    student_id: int,
    db: Session = Depends(get_db),
    current_teacher: models.User = Depends(check_teacher)
):
    """
    Получить все назначенные тесты для конкретного студента.
    Для каждого назначения вычисляется реальный статус выполнения
    (наличие завершённого TestResult).
    """
    # 1. Проверяем, что студент существует
    student = db.query(models.User).filter(
        models.User.id == student_id,
        models.User.role == "student"
    ).first()
    if not student:
        raise HTTPException(status_code=404, detail="Студент не найден")

    # 2. Если учитель (не админ) – проверяем принадлежность
    if current_teacher.role == "teacher":
        _check_student_belongs_to_teacher(db, student_id, current_teacher.id)

    # 3. Получаем все назначения для этого студента
    assignments = db.query(models.TestAssignment).filter(
        models.TestAssignment.user_id == student_id
    ).order_by(models.TestAssignment.assigned_at.desc()).all()

    # 4. За один запрос получаем все завершённые результаты этого студента
    #    (группируем по test_id и берём последний по дате)
    from sqlalchemy import func
    subq = db.query(
        models.TestResult.test_id,
        func.max(models.TestResult.completed_at).label('max_completed_at')
    ).filter(models.TestResult.user_id == student_id)\
     .group_by(models.TestResult.test_id).subquery()

    latest_results = db.query(models.TestResult).join(
        subq,
        (models.TestResult.test_id == subq.c.test_id) &
        (models.TestResult.completed_at == subq.c.max_completed_at)
    ).all()

    # Собираем словарь {test_id: TestResult}
    results_map = {r.test_id: r for r in latest_results}

    # 5. Формируем ответ
    response = []
    for assignment in assignments:
        test = db.query(models.Test).filter(models.Test.id == assignment.test_id).first()
        if not test:
            # Если тест удалён, можно либо пропустить, либо вернуть с пометкой
            continue

        latest_result = results_map.get(assignment.test_id)
        is_completed = latest_result is not None
        completed_at = latest_result.completed_at if latest_result else None
        total_points = latest_result.total_points if latest_result else None
        result_id = latest_result.id if latest_result else None

        response.append({
            "id": assignment.id,
            "test_id": assignment.test_id,
            "test_title": test.title,
            "user_id": assignment.user_id,
            "student_name": f"{student.first_name} {student.last_name}",
            "assigned_at": assignment.assigned_at,
            "due_date": assignment.due_date,
            "is_completed": is_completed,          # теперь реальный статус
            "completed_at": completed_at,          # дата завершения
            "total_tasks": len(test.tasks) if test.tasks else 0,
            "total_points": total_points,          # набранные баллы
            "result_id": result_id                 # ID результата для перехода
        })

    return response

@router.delete("/assignments/{assignment_id}")
def delete_assignment(
    assignment_id: int,
    db: Session = Depends(get_db),
    current_teacher: models.User = Depends(check_teacher)
):
    """Отменить назначение теста. Учитель может удалять только назначения для своих тестов."""
    # Находим назначение
    assignment = db.query(models.TestAssignment).filter(
        models.TestAssignment.id == assignment_id
    ).first()
    if not assignment:
        raise HTTPException(status_code=404, detail="Назначение не найдено")

    # Получаем тест
    test = db.query(models.Test).filter(models.Test.id == assignment.test_id).first()
    if not test:
        # Если тест удалён, всё равно можно удалить назначение (или запретить)
        # Здесь лучше запретить, чтобы не было мусора
        raise HTTPException(status_code=404, detail="Связанный тест не найден")

    # Проверяем, что текущий учитель — владелец теста (или админ)
    if current_teacher.role == "teacher" and test.creator_id != current_teacher.id:
        raise HTTPException(status_code=403, detail="Вы не можете удалить это назначение (тест не ваш)")

    # Удаляем назначение
    db.delete(assignment)
    db.commit()

    return {"message": "Назначение удалено"}

@router.post("/assign-test-to-group")
def assign_test_to_group(
    assignment: dto.TestGroupAssignment,
    db: Session = Depends(get_db),
    current_teacher: models.User = Depends(check_teacher)
):
    """Назначить тест всей группе (прокси для быстрого заполнения test_assignments)"""
    
    # Находим группу
    group = db.query(models.Group).filter(
        models.Group.id == assignment.group_id,
        models.Group.teacher_id == current_teacher.id
    ).first()
    
    if not group:
        raise HTTPException(status_code=404, detail="Группа не найдена")
    
    # Получаем ID студентов группы
    student_ids = [s.id for s in group.students]
    
    if not student_ids:
        raise HTTPException(status_code=400, detail="В группе нет студентов")
    
    # 🔥 Используем ТУ ЖЕ логику, что и в assign_test_to_students
    # Проверяем тест
    test = db.query(models.Test).filter(models.Test.id == assignment.test_id).first()
    if not test:
        raise HTTPException(status_code=404, detail="Тест не найден")
    
    if current_teacher.role == "teacher" and test.creator_id != current_teacher.id:
        raise HTTPException(status_code=403, detail="Вы не можете назначать этот тест")
    
    # Проверяем что все студенты принадлежат учителю
    assigned_students = db.query(models.TeacherStudent).filter(
        models.TeacherStudent.teacher_id == current_teacher.id,
        models.TeacherStudent.student_id.in_(student_ids)
    ).all()
    
    assigned_ids = {s.student_id for s in assigned_students}
    
    created = 0
    for student_id in student_ids:
        if student_id not in assigned_ids:
            continue  # Пропускаем чужих студентов
        
        # Проверяем, не назначен ли уже тест
        existing = db.query(models.TestAssignment).filter(
            models.TestAssignment.test_id == assignment.test_id,
            models.TestAssignment.user_id == student_id
        ).first()
        
        if existing:
            continue
        
        # 🔥 Создаём ТОЧНО такую же запись, как в assign_test_to_students
        db.add(models.TestAssignment(
            test_id=assignment.test_id,
            user_id=student_id,
            group_id=group.id,  # Просто помечаем что назначено через группу
            due_date=assignment.due_date,
            assigned_at=datetime.datetime.utcnow()
        ))
        created += 1
    
    db.commit()
    
    return {
        "message": f"Тест назначен {created} студентам группы '{group.name}'",
        "assigned_count": created,
        "group_id": group.id,
        "test_id": assignment.test_id
    }