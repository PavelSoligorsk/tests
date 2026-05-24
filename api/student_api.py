from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload, Query
from sqlalchemy import func, select, case
import models, dto, auth
from database import get_db
from typing import List, Optional
from datetime import datetime
import os
from mistralai.client import Mistral
from dotenv import load_dotenv
from dto import AITestRequest
# В начале файла нужно добавить импорт
from sqlalchemy.orm import joinedload

load_dotenv()
MISTRAL_TOKEN = os.getenv("MISTRAL_TOKEN")
mistral_client = Mistral(api_key=MISTRAL_TOKEN)

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

    if test.is_ai_generated:
        test.is_active = False
        db.commit()

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

@router.post("/tasks/{task_id}/hint")
def get_ai_hint_while_solving(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    """
    Получить ИИ-подсказку во время решения.
    Без проверок — просто задание + контекст студента.
    """
    # 1. Задание
    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Задание не найдено")

    # 2. Статистика студента по теме
    all_results = db.query(models.TestResult).filter(
        models.TestResult.user_id == current_user.id
    ).all()
    result_ids = [r.id for r in all_results]

    if result_ids:
        answers_same_topic = db.query(models.UserAnswer).join(
            models.Task
        ).filter(
            models.UserAnswer.result_id.in_(result_ids),
            models.Task.topic_number == task.topic_number
        ).all()

        same_topic_total = len(answers_same_topic)
        same_topic_correct = sum(1 for a in answers_same_topic if a.is_correct)
        topic_mastery = round((same_topic_correct / same_topic_total) * 100) if same_topic_total > 0 else None
    else:
        same_topic_total = 0
        same_topic_correct = 0
        topic_mastery = None

    # 3. Промпт
    prompt = f"""Ты — AI-репетитор по математике. Студент решает задание и просит подсказку.
НЕ ДАВАЙ ГОТОВЫЙ ОТВЕТ. Объясни подход, метод, наведи на мысль.

=== ФОРМАТ ФОРМУЛ ===
- Для формул внутри строки используй $...$ (например, $ax^2 + bx + c = 0$)
- Для вынесенных формул и выражений используй $$...$$ (например, $$\\int_{{a}}^{{b}} f(x) dx$$)
- Все математические записи ОБЯЗАТЕЛЬНО заключай в $...$ или $$...$$

=== ЗАДАНИЕ ===
Класс: {task.task_class}
Тема №: {task.topic_number}
Тема: {task.topic or 'Не указана'}
Раздел: {task.section or 'Не указан'}
Сложность (1-5): {task.difficulty}
Тип: {'открытый ответ' if task.is_open_answer else 'выбор варианта'}

Условие:
{task.content}

Варианты: {task.options if task.options else 'Нет (открытый вопрос)'}
"""

    if topic_mastery is not None:
        prompt += f"""
=== УСВОЕНИЕ ТЕМЫ ===
Решено задач по этой теме: {same_topic_total}
Правильно: {same_topic_correct} ({topic_mastery}%)
"""

    prompt += """
=== ИНСТРУКЦИЯ ДЛЯ AI ===

Ты помогаешь студенту решить задачу, но НЕ даёшь готовый ответ.

Правила оформления:
1. Пиши простыми, понятными предложениями (3-6 предложений)
2. Используй переносы строк между смысловыми блоками
3. Выражения в тексте оформляй как $...$ (например, $c^2$, $a^3$, $x^2$)
4. КЛЮЧЕВОЕ ПРАВИЛО: все формулы, преобразования, вычисления и промежуточные шаги выноси на отдельную строку с центрированием через $$...$$. ДО и ПОСЛЕ каждой формулы ОБЯЗАТЕЛЬНО ставь пустую строку.
5. Показывай каждый шаг преобразования отдельной формулой
6. Не используй звёздочки, списки, маркеры и нумерацию — пиши связным текстом

Пример оформления:

Тема — свойства степеней. Нужно упростить выражение и сравнить с $a^3$.

Вспомни основное правило умножения степеней:

$$
a^m \cdot a^n = a^{m+n}
$$

Теперь примени это правило к выражению $a \cdot a^2$:

$$
a^1 \cdot a^2 = a^{1+2} = a^3
$$

Получили $a^3$, значит этот вариант подходит.

Теперь проверь $a^4 : a$:

$$
a^4 : a = a^{4-1} = a^3
$$

Тоже подходит.

А теперь $(a^2)^2$:

$$
(a^2)^2 = a^{2 \cdot 2} = a^4
$$

Здесь получилось $a^4$, а не $a^3$, значит этот вариант не подходит.

Так же проверь остальные варианты, применяя свойства степеней и оформляя каждое преобразование в отдельную формулу с центрированием.

НЕ пиши: "Ответ: ..." или "Правильный вариант — ..."
НЕ решай полностью — только направляй, показывая примеры преобразований.
"""

    # 4. Отправка в Mistral
    try:
        response = mistral_client.chat.complete(
            model="mistral-large-latest",
            messages=[
                {
                    "role": "system",
                    "content": "Ты — терпеливый ИИ-репетитор. Помогаешь понять, а не решаешь за студента. ВСЕ математические формулы и выражения ОБЯЗАТЕЛЬНО оформляй в $...$ (строчные) или $$...$$ (вынесенные)."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.7,
            max_tokens=800
        )
        hint_text = response.choices[0].message.content
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка AI: {str(e)}")

    return {
        "task_id": task_id,
        "hint": hint_text,
        "context": {
            "task_class": task.task_class,
            "topic_number": task.topic_number,
            "difficulty": task.difficulty,
            "topic_mastery_percent": topic_mastery
        }
    }

@router.post("/tasks/{task_id}/ai-solve")
def get_ai_solution(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    """
    Получить решение задачи от ИИ.
    Нейронка сначала решает, потом сверяется с правильным ответом.
    """
    # 1. Задание
    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Задание не найдено")

    # 2. Статистика студента (для контекста)
    all_results = db.query(models.TestResult).filter(
        models.TestResult.user_id == current_user.id
    ).all()
    result_ids = [r.id for r in all_results]

    if result_ids:
        answers_same_topic = db.query(models.UserAnswer).join(
            models.Task
        ).filter(
            models.UserAnswer.result_id.in_(result_ids),
            models.Task.topic_number == task.topic_number
        ).all()
        same_topic_total = len(answers_same_topic)
        same_topic_correct = sum(1 for a in answers_same_topic if a.is_correct)
        topic_mastery = round((same_topic_correct / same_topic_total) * 100) if same_topic_total > 0 else None
    else:
        topic_mastery = None

    # 3. Промпт для решения (как в hint, но для решения)
    solve_prompt = f"""Ты — AI-репетитор по математике. Реши задачу и дай полное, подробное решение.

=== ФОРМАТ ФОРМУЛ ===
- Для формул внутри строки используй $...$ (например, $ax^2 + bx + c = 0$)
- Для вынесенных формул и выражений используй $$...$$ (например, $$\\int_{{a}}^{{b}} f(x) dx$$)
- Все математические записи ОБЯЗАТЕЛЬНО заключай в $...$ или $$...$$

=== ЗАДАНИЕ ===
Класс: {task.task_class}
Тема №: {task.topic_number}
Тема: {task.topic or 'Не указана'}
Раздел: {task.section or 'Не указан'}
Сложность (1-5): {task.difficulty}
Тип: {'открытый ответ' if task.is_open_answer else 'выбор варианта'}

Условие:
{task.content}

Варианты ответа: {task.options if task.options else 'Нет (открытый вопрос)'}
"""

    if topic_mastery is not None:
        solve_prompt += f"""
=== УСВОЕНИЕ ТЕМЫ ===
Решено задач по этой теме: {same_topic_total}
Правильно: {same_topic_correct} ({topic_mastery}%)
"""

    solve_prompt += """
=== ТРЕБОВАНИЯ ДЛЯ KATEX ===
1. Реши задачу пошагово
2. В конце напиши: "=== ОТВЕТ === ..."
3. Используй ТОЛЬКО $...$ для формул внутри текста
4. Используй ТОЛЬКО $$...$$ для вынесенных формул
5. НЕ ИСПОЛЬЗУЙ \(...\) и \[...\] — они НЕ РАБОТАЮТ в KaTeX
6. Для дробей пиши \\frac{числитель}{знаменатель}
7. Не используй списки, маркеры, звёздочки
8. Пиши связным текстом с выделением шагов
9. Для вопроса с варианатми ответа - в ответе укажи номер или номера правильных вариантов. Если без вариантов - число
10. Используй картинки по смыслу, которые есть в контексте. Просто вставляй их, как в обычный маркдаун 

=== ПРИМЕР ПРАВИЛЬНОГО ОФОРМЛЕНИЯ ===

Решим задачу: найти значение выражения $a \\cdot a^2$.

Применим правило умножения степеней:

$$
a^m \\cdot a^n = a^{m+n}
$$

Подставим $m=1$, $n=2$:

$$
a^1 \\cdot a^2 = a^{1+2} = a^3
$$

=== ОТВЕТ === 1 (в случае открытого номер/номера правильного/ных), -255 (в случае закрытого число)

ЗАПОМНИ: используй ТОЛЬКО $...$ и $$...$$, НИКОГДА не используй \\( ... \\) или \\[ ... \\]
"""
    # 4. Отправка в Mistral для решения
    try:
        response = mistral_client.chat.complete(
            model="mistral-large-latest",
            messages=[
                {
                    "role": "system",
                    "content": "Ты — математический эксперт. Решай задачи подробно, показывай все шаги. В конце обязательно укажи ответ в формате '=== ОТВЕТ === ...'"
                },
                {
                    "role": "user",
                    "content": solve_prompt
                }
            ],
            temperature=0.3,
            max_tokens=2000
        )
        ai_solution = response.choices[0].message.content
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка AI: {str(e)}")

    # 5. Извлечение ответа ИИ
    import re
    answer_pattern = r'=== ОТВЕТ ===\s*(.+?)(?:\n|$)'
    match = re.search(answer_pattern, ai_solution, re.IGNORECASE)
    
    if not match:
        return {
            "task_id": task_id,
            "success": False,
            "message": "Решение ИИ не найдено (нет маркера '=== ОТВЕТ ===')",
            "ai_solution": ai_solution,
            "verified": False
        }
    
    ai_answer = match.group(1).strip()
    
    # 6. Сверка с правильным ответом
    correct_answer = task.answer.strip() if task.answer else None
    
    if not correct_answer:
        return {
            "task_id": task_id,
            "success": False,
            "message": "В задании нет правильного ответа для сверки",
            "ai_solution": ai_solution,
            "ai_answer": ai_answer,
            "verified": False
        }
    
    # Нормализация ответов для сравнения
    def normalize_answer(text):
        if not text:
            return ""
        result = text.lower().strip()
        result = result.replace(' ', '')
        result = result.replace('(', '')
        result = result.replace(')', '')
        result = result.replace('.', '')
        result = result.replace(',', '')
        return result
    
    ai_normalized = normalize_answer(ai_answer)
    correct_normalized = normalize_answer(correct_answer)
    
    is_correct = ai_normalized == correct_normalized
    
    # 7. Результат
    return {
        "task_id": task_id,
        "success": True,
        "verified": is_correct,
        "message": "Решение найдено и проверено. Ответ совпадает." if is_correct else "Решение найдено, но ответ не совпадает с правильным.",
        "ai_solution": ai_solution,
        "ai_answer": ai_answer,
        "correct_answer": correct_answer,
        "context": {
            "task_class": task.task_class,
            "topic_number": task.topic_number,
            "difficulty": task.difficulty,
            "topic_mastery_percent": topic_mastery
        }
    }


# ==================== ЭНДПОИНТЫ ДЛЯ СТУДЕНТА (ТЕОРИЯ) ====================

@router.get("/theory/topics")
def get_theory_topics(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    """Получить все доступные темы (уникальные topic)"""
    topics = db.query(models.Theory.topic).distinct().all()
    
    # Словарь для красивых названий
    MAIN_TOPICS = {
        'numbers': 'Числа и вычисления',
        'expressions': 'Выражения и их преобразования',
        'equations': 'Уравнения и неравенства',
        'functions': 'Координаты и функции',
        'geometry': 'Геометрия'
    }
    
    result = []
    for topic in topics:
        if topic[0]:
            result.append({
                "topic": topic[0],
                "label": MAIN_TOPICS.get(topic[0], topic[0]),
                "sections_count": db.query(models.Theory).filter(models.Theory.topic == topic[0]).count()
            })
    
    return result


@router.get("/theory/sections/{topic}")
def get_theory_sections(
    topic: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    """Получить все разделы по теме"""
    theories = db.query(models.Theory).filter(
        models.Theory.topic == topic
    ).order_by(models.Theory.section).all()
    
    result = []
    for theory in theories:
        result.append({
            "section": theory.section,
            "theory_id": theory.id
        })
    
    return result


@router.get("/theory/by-topic/{topic}")
def get_theory_by_topic(
    topic: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    """Получить всю теорию по теме (все разделы)"""
    theories = db.query(models.Theory).filter(
        models.Theory.topic == topic
    ).order_by(models.Theory.section).all()
    
    if not theories:
        raise HTTPException(
            status_code=404,
            detail=f"Теория для темы '{topic}' не найдена"
        )
    
    return theories


@router.get("/theory/by-topic/{topic}/section/{section}")
def get_theory_by_topic_section(
    topic: str,
    section: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
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

@router.post("/theory/ask-ai")
def ask_ai_about_theory(
    request: dict,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    """
    Задать вопрос ИИ по теоретическому материалу.
    Нейронка получает полный контекст теории и вопрос студента.
    """
    theory_id = request.get("theory_id")
    question = request.get("question", "").strip()
    theory_content = request.get("theory_content", "")  # опционально, если передан с фронта
    
    if not question:
        raise HTTPException(status_code=400, detail="Вопрос не может быть пустым")
    
    # Если передан theory_id, загружаем теорию из БД
    theory_context = ""
    topic_name = ""
    section_name = ""
    
    if theory_id:
        theory = db.query(models.Theory).filter(models.Theory.id == theory_id).first()
        if theory:
            theory_context = theory.content or ""
            topic_name = theory.topic or ""
            section_name = theory.section or ""
    elif theory_content:
        theory_context = theory_content
    else:
        raise HTTPException(status_code=400, detail="Не указан theory_id или theory_content")
    
    # Собираем промпт
    prompt = f"""Ты — AI-репетитор по математике. Студент изучает теорию и задаёт вопрос.
Твоя задача — объяснить материал понятно, с примерами, но не давать готовых ответов, если студент не просит решить задачу.

=== ФОРМАТ ФОРМУЛ ===
- Для формул внутри строки используй $...$ (например, $ax^2 + bx + c = 0$)
- Для вынесенных формул и выражений используй $$...$$ (например, $$\\frac{{a}}{{b}}$$)
- Все математические записи ОБЯЗАТЕЛЬНО заключай в $...$ или $$...$$
- НИКОГДА не используй \\( ... \\) или \\[ ... \\]

=== ТЕОРЕТИЧЕСКИЙ МАТЕРИАЛ ===
Тема: {topic_name or 'Не указана'}
Раздел: {section_name or 'Не указан'}

Содержание теории:
{theory_context}

=== ВОПРОС СТУДЕНТА ===
{question}

=== ИНСТРУКЦИЯ ДЛЯ AI ===
1. Отвечай простыми, понятными предложениями
2. Используй примеры для иллюстрации
3. Объясняй «почему», а не только «как»
4. Если вопрос не по теме — вежливо направь к материалу
5. ВСЕ математические выражения оформляй в $...$ или $$...$$
6. Не используй списки с маркерами, пиши связным текстом
7. Если студент просит решить задачу — реши пошагово с объяснениями
8. Используй картинки по смыслу, которые есть в контексте. Просто вставляй их, как в обычный маркдаун 

=== ПРИМЕР ПРАВИЛЬНОГО ОФОРМЛЕНИЯ ===

Решим задачу: найти значение выражения $a \\cdot a^2$.

Применим правило умножения степеней:

$$
a^m \\cdot a^n = 
$$

Подставим $m=1$, $n=2$:

$$
a^1 \\cdot a^2 = a^3 = a^3
$$


"""

    try:
        response = mistral_client.chat.complete(
            model="mistral-large-latest",
            messages=[
                {
                    "role": "system",
                    "content": "Ты — терпеливый ИИ-репетитор по математике. Объясняешь теорию, отвечаешь на вопросы, помогаешь понять материал. ВСЕ математические формулы и выражения ОБЯЗАТЕЛЬНО оформляй в $...$ (строчные) или $$...$$ (вынесенные). НИКОГДА не используй \\(...\\) или \\[...\\]."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.7,
            max_tokens=3000
        )
        ai_answer = response.choices[0].message.content
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка AI: {str(e)}")

    return {
        "success": True,
        "question": question,
        "answer": ai_answer,
        "context": {
            "topic": topic_name,
            "section": section_name
        }
    }

import json
import re
import random
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_

# Предполагаем, что импорты моделей и mistral_client уже есть
@router.post("/generate-test")
def generate_ai_test(
    request: AITestRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    """
    AI подбирает задания из базы по промпту студента.
    Шаг 1: AI определяет темы и разделы (с привязкой разделов к темам)
    Шаг 2: Бэкенд фильтрует задания по этим темам (макс 300)
    Шаг 3: AI анализирует отфильтрованные задания и выбирает лучшие
    """
    
    # ========== ШАГ 1: AI определяет темы и разделы (с привязкой) ==========
    
    structure_data = db.query(models.Task.topic, models.Task.section).filter(models.Task.topic != None).distinct().all()
    
    topics_structure = {}
    for topic, section in structure_data:
        if topic not in topics_structure:
            topics_structure[topic] = set()
        if section:
            topics_structure[topic].add(section)
    
    hierarchy_context = []
    for topic, sections in topics_structure.items():
        hierarchy_context.append(f"- Тема: {topic}")
        if sections:
            hierarchy_context.append(f"  Разделы: {', '.join(sorted(sections))}")
            
    topic_prompt = f"""Ты — классификатор учебных заданий по математике.
Анализируй запрос студента и сопоставляй его исключительно с ТЕМАМИ и РАЗДЕЛАМИ из реальной структуры базы данных ниже.

=== РЕАЛЬНАЯ СТРУКТУРА БАЗЫ ДАННЫХ ===
{chr(10).join(hierarchy_context)}

=== ЗАПРОС СТУДЕНТА ===
{request.prompt}

Ты — классификатор учебных заданий по математике.
Анализируй запрос студента и сопоставляй его с ТЕМАМИ и РАЗДЕЛАМИ из реальной структуры базы данных ниже.

=== РЕАЛЬНАЯ СТРУКТУРА БАЗЫ ДАННЫХ ===
{chr(10).join(hierarchy_context)}

=== ЗАПРОС СТУДЕНТА ===
{request.prompt}

=== ПОДРОБНАЯ ИНСТРУКЦИЯ ===

1. **Анализ запроса:**
   - Внимательно прочитай запрос студента
   - Определи, о каких математических темах идёт речь

2. **Правила выбора тем:**
   - Если студент пишет "отработка уравнений" → возьми ВСЕ темы из раздела "Уравнения и неравенства", которые содержат слово "уравнение" (Квадратные уравнения, Логарифмические уравнения, Показательные уравнения и т.д.)
   - Если "дроби" → возьми тему "Числа и вычисления" с разделами про дроби
   - Если "геометрия" → возьми тему "Геометрия" со всеми её разделами
   - Если "стереометрия" → возьми тему "Геометрия" с разделами по стереометрии

3. **Правила выбора разделов:**
   - Если запрос точный ("квадратные уравнения") → укажи конкретный раздел
   - Если запрос общий ("уравнения") → укажи ВСЕ разделы, где есть слово "уравнение" в названии (но не системы уравнений или т.п. ВСЁ ДОЛЖНО БЫТЬ ПО СМЫСЛУ)
   - Если запрос очень общий ("математика") → выбери 3-5 основных тем

4. **Примеры:**
   - Запрос: "отработка уравнений" → 
     {{"topics": [{{"name": "Уравнения и неравенства", "sections": ["Квадратные уравнения", "Логарифмические уравнения", "Показательные уравнения"]}}]}}
   
   - Запрос: "хочу квадратные уравнения и проценты" →
     {{"topics": [
        {{"name": "Уравнения и неравенства", "sections": ["Квадратные уравнения"]}},
        {{"name": "Числа и вычисления", "sections": ["Проценты"]}}
     ]}}
   
   - Запрос: "подготовка к экзамену по геометрии" →
     {{"topics": [{{"name": "Геометрия", "sections": []}}]}}
     (пустой массив sections = все разделы этой темы)

5. **Если точного совпадения нет:**
   - Выбери максимально близкие по смыслу темы и разделы
   - Если unsure, лучше выбрать больше, чем меньше

=== ВАЖНО ===
- sections можно оставить пустым массивом [], если нужно взять ВСЕ разделы темы
- Если тема не указана в структуре БД, НЕ придумывай её

Верни ТОЛЬКО JSON строго в формате:
{{
  "topics": [
    {{"name": "Название темы 1", "sections": ["Раздел 1", "Раздел 2"]}},
    {{"name": "Название темы 2", "sections": []}}
  ]
}}
"""

    detected_topics_with_sections = []

    try:
        topic_response = mistral_client.chat.complete(
            model="mistral-large-latest",
            messages=[
                {"role": "system", "content": "Ты — строгий классификатор. Отвечаешь только валидным JSON без разметки markdown."},
                {"role": "user", "content": topic_prompt}
            ],
            temperature=0.1,
            max_tokens=500
        )
        ai_content = topic_response.choices[0].message.content
        
        json_match = re.search(r'\{.*\}', ai_content, re.DOTALL)
        if json_match:
            classification = json.loads(json_match.group())
            detected_topics_with_sections = classification.get("topics", [])
            
    except Exception as e:
        print(f"[ERROR] AI classification failed: {e}")

    # Преобразуем в удобный формат
    detected_topics = []
    topic_section_map = {}  # тема -> список разделов
    
    for item in detected_topics_with_sections:
        topic_name = item.get("name")
        sections = item.get("sections", [])
        
        if topic_name:
            detected_topics.append(topic_name)
            topic_section_map[topic_name] = sections
    
    print(f"[DEBUG] Topics with sections: {topic_section_map}")
    
    # ========== ШАГ 2: Фильтрация заданий ==========
    
    # Маппинг сложности (поддержка None)
    difficulty_map = {
        "easy": [1, 2],
        "medium": [2, 3, 4],
        "hard": [4, 5]
    }
    
    # Если difficulty = None, берём все сложности
    if request.difficulty:
        target_difficulties = difficulty_map.get(request.difficulty, [1, 2, 3, 4, 5])
        difficulty_text = request.difficulty
    else:
        target_difficulties = [1, 2, 3, 4, 5]
        difficulty_text = "Любая (Рататуй 🍲)"
    
    filtered_tasks = []
    
    if detected_topics:
        from sqlalchemy import or_, and_
        
        # Строим условия для каждой темы с её разделами
        conditions = []
        for topic, sections in topic_section_map.items():
            if sections:
                # Если для темы указаны разделы — ищем строго по ним
                conditions.append(
                    and_(
                        models.Task.topic == topic,
                        models.Task.section.in_(sections)
                    )
                )
            else:
                # Если разделы не указаны — берём все задания темы
                conditions.append(
                    models.Task.topic == topic
                )
        
        if conditions:
            query = db.query(models.Task).filter(
                or_(*conditions),
                models.Task.difficulty.in_(target_difficulties)
            )
            filtered_tasks = query.limit(300).all()
        
        print(f"[DEBUG] Найдено заданий по темам {detected_topics}: {len(filtered_tasks)}")
    
    # Fallback: если ничего не нашли по темам
    if not filtered_tasks:
        keywords = [w for w in re.sub(r'[^\w\s]', '', request.prompt).split() if len(w) > 3]
        if keywords:
            like_conditions = [models.Task.topic.ilike(f"%{word}%") for word in keywords]
            filtered_tasks = db.query(models.Task).filter(
                or_(*like_conditions),
                models.Task.difficulty.in_(target_difficulties)
            ).limit(300).all()
    
    # Финальный fallback: любые задания
    if not filtered_tasks:
        filtered_tasks = db.query(models.Task).filter(
            models.Task.difficulty.in_(target_difficulties)
        ).limit(300).all()
    
    if not filtered_tasks:
        raise HTTPException(status_code=404, detail="Нет доступных заданий")
    
    # ========== ШАГ 3: AI анализирует отфильтрованные задания и выбирает лучшие ==========
    
    tasks_for_ai = []
    for task in filtered_tasks:
        tasks_for_ai.append(
            f"ID:{task.id} | Тема:{task.topic or 'Н/Д'} | Раздел:{task.section or 'Н/Д'} | "
            f"Сложность:{task.difficulty or 'Н/Д'} | Тип:{'открытый' if task.is_open_answer else 'закрытый'} | "
            f"Содержание:{(task.content or '')[:120]}..."
        )
    
    selection_prompt = f"""Ты — эксперт по подбору учебных заданий по математике.

=== ЗАПРОС СТУДЕНТА ===
{request.prompt}

=== ПАРАМЕТРЫ ===
Нужно выбрать заданий: {request.task_count}
Сложность: {difficulty_text}

=== ОТФИЛЬТРОВАННЫЕ ЗАДАНИЯ ===
Всего доступно: {len(tasks_for_ai)} заданий

Список заданий:
{chr(10).join(tasks_for_ai)}

=== ИНСТРУКЦИЯ ===
1. Проанализируй запрос студента: "{request.prompt}"
2. Из предложенных заданий выбери {request.task_count} НАИБОЛЕЕ ПОДХОДЯЩИХ
3. Учитывай содержание задания, тему, сложность
4. Верни ТОЛЬКО JSON: {{"task_ids": [45, 67, 123, ...]}}
5. Если подходящих меньше {request.task_count} — верни сколько есть
"""

    selected_ids = []
    
    try:
        response = mistral_client.chat.complete(
            model="mistral-large-latest",
            messages=[
                {"role": "system", "content": "Ты — эксперт. Отвечай ТОЛЬКО JSON: {\"task_ids\": [1,2,3]}"},
                {"role": "user", "content": selection_prompt}
            ],
            temperature=0.3,
            max_tokens=800
        )
        ai_content = response.choices[0].message.content
        
        json_match = re.search(r'\{.*\}', ai_content, re.DOTALL)
        if json_match:
            result_data = json.loads(json_match.group())
            selected_ids = result_data.get("task_ids", [])
            
    except Exception as e:
        print(f"[ERROR] AI selection failed: {e}")
    
    # ========== ШАГ 4: Загружаем выбранные задания ==========
    
    if selected_ids:
        selected_tasks = db.query(models.Task).filter(
            models.Task.id.in_(selected_ids)
        ).all()
        
        if len(selected_tasks) < request.task_count:
            remaining_ids = [t.id for t in filtered_tasks if t.id not in selected_ids]
            if remaining_ids:
                needed = request.task_count - len(selected_tasks)
                extra_ids = random.sample(remaining_ids, min(needed, len(remaining_ids)))
                extra_tasks = db.query(models.Task).filter(models.Task.id.in_(extra_ids)).all()
                selected_tasks.extend(extra_tasks)
    else:
        print("[WARNING] AI не вернул ID, используем random.sample")
        selected_tasks = random.sample(filtered_tasks, min(request.task_count, len(filtered_tasks)))
    
    if not selected_tasks:
        raise HTTPException(status_code=404, detail="Не удалось подобрать задания")
    
    # ========== ШАГ 5: Сортировка ==========
    
    closed_tasks = sorted(
        [t for t in selected_tasks if not t.is_open_answer],
        key=lambda t: t.difficulty or 0
    )
    open_tasks = sorted(
        [t for t in selected_tasks if t.is_open_answer],
        key=lambda t: t.difficulty or 0
    )
    sorted_tasks = closed_tasks + open_tasks
    
    # ========== ШАГ 6: Создание теста ==========
    
    topics_used = list(set([t.topic for t in selected_tasks if t.topic]))
    title_topics = ", ".join(topics_used[:3])
    if len(topics_used) > 3:
        title_topics += f" и ещё {len(topics_used)-3} тем"
        
    if not title_topics:
        title_topics = "Умный подбор"

    new_test = models.Test(
        title=f"AI: {title_topics}",
        target_class=None,
        target_topic=request.prompt[:255],
        is_autocompile=False,
        is_ai_generated=True,
        creator_id=current_user.id,
        is_active=True
    )
    db.add(new_test)
    db.flush()

    new_test.tasks = sorted_tasks
    db.commit()
    db.refresh(new_test)

    result = db.query(models.Test)\
               .options(joinedload(models.Test.tasks))\
               .filter(models.Test.id == new_test.id)\
               .first()

    return result