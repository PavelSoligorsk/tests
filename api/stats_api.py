from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, case, select, and_
import models, dto, auth
from database import get_db
from typing import List, Optional
from datetime import datetime, timedelta

router = APIRouter(prefix="/stats", tags=["Statistics"])

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================

def _get_period_dates(period: str) -> tuple:
    """Возвращает (start_date, end_date) для указанного периода."""
    now = datetime.utcnow()
    period_map = {
        "week": now - timedelta(days=7),
        "month": now - timedelta(days=30),
        "3months": now - timedelta(days=90),
        "6months": now - timedelta(days=180),
        "year": now - timedelta(days=365),
        "all": None
    }
    
    if period not in period_map:
        raise HTTPException(status_code=400, detail="Допустимые периоды: week, month, 3months, 6months, year, all")
    
    return period_map[period], now


def _check_access(user_id: int, db: Session, current_user: models.User):
    """
    Проверяет доступ к статистике пользователя.
    - Студент: только своя статистика
    - Учитель: только свои ученики
    - Админ: любой пользователь
    """
    if current_user.role == "student" and current_user.id != user_id:
        raise HTTPException(status_code=403, detail="Вы можете смотреть только свою статистику")
    
    if current_user.role == "teacher":
        if current_user.id == user_id:
            pass
        else:
            link = db.query(models.TeacherStudent).filter(
                models.TeacherStudent.teacher_id == current_user.id,
                models.TeacherStudent.student_id == user_id
            ).first()
            
            if not link:
                raise HTTPException(status_code=403, detail="У вас нет доступа к этому ученику")
    
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    return user


def _calculate_streak(daily_dates: List[str], end_date: datetime) -> int:
    """Вычисляет серию дней подряд."""
    if not daily_dates:
        return 0
    
    dates_set = set(daily_dates)
    today = end_date.date()
    streak = 0
    
    if today.isoformat() in dates_set:
        streak = 1
        check_date = today - timedelta(days=1)
        while check_date.isoformat() in dates_set:
            streak += 1
            check_date -= timedelta(days=1)
    elif (today - timedelta(days=1)).isoformat() in dates_set:
        streak = 1
        check_date = today - timedelta(days=2)
        while check_date.isoformat() in dates_set:
            streak += 1
            check_date -= timedelta(days=1)
    
    return streak


# ==================== ЭНДПОИНТЫ ДЛЯ ТЕКУЩЕГО ПОЛЬЗОВАТЕЛЯ (/me) ====================

@router.get("/me/period")
def get_my_period_stats(
    period: str = Query("month", description="week, month, 3months, 6months, year, all"),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    """Моя статистика по периоду."""
    return _get_period_stats(current_user.id, period, db, current_user)


@router.get("/me/topics")
def get_my_topic_stats(
    period: str = Query("all", description="week, month, 3months, 6months, year, all"),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    """Моя статистика по темам с разделами."""
    return _get_topics_stats(current_user.id, period, db, current_user)


@router.get("/me/difficulty")
def get_my_difficulty_stats(
    period: str = Query("all", description="week, month, 3months, 6months, year, all"),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    """Моя статистика по сложности."""
    return _get_difficulty_stats(current_user.id, period, db, current_user)


@router.get("/me/full")
def get_my_full_stats(
    period: str = Query("month", description="week, month, 3months, 6months, year, all"),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    """Моя полная статистика."""
    return _get_full_stats(current_user.id, period, db, current_user)


# ==================== ЭНДПОИНТЫ ДЛЯ КОНКРЕТНОГО ПОЛЬЗОВАТЕЛЯ ====================

@router.get("/user/{user_id}/period")
def get_user_period_stats(
    user_id: int,
    period: str = Query("month"),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    """Статистика пользователя по периоду (для учителя/админа)."""
    return _get_period_stats(user_id, period, db, current_user)


@router.get("/user/{user_id}/topics")
def get_user_topic_stats(
    user_id: int,
    period: str = Query("all"),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    """Статистика пользователя по темам с разделами (для учителя/админа)."""
    return _get_topics_stats(user_id, period, db, current_user)


@router.get("/user/{user_id}/difficulty")
def get_user_difficulty_stats(
    user_id: int,
    period: str = Query("all"),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    """Статистика пользователя по сложности (для учителя/админа)."""
    return _get_difficulty_stats(user_id, period, db, current_user)


@router.get("/user/{user_id}/full")
def get_user_full_stats(
    user_id: int,
    period: str = Query("month"),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    """Полная статистика пользователя (для учителя/админа)."""
    return _get_full_stats(user_id, period, db, current_user)


# ==================== ВНУТРЕННИЕ ФУНКЦИИ (логика) ====================

def _get_period_stats(user_id: int, period: str, db: Session, current_user: models.User) -> dict:
    """Логика получения статистики по периоду."""
    user = _check_access(user_id, db, current_user)
    start_date, end_date = _get_period_dates(period)
    
    # Запрос результатов
    results_query = db.query(models.TestResult).filter(models.TestResult.user_id == user_id)
    if start_date:
        results_query = results_query.filter(models.TestResult.completed_at >= start_date)
    
    results = results_query.order_by(models.TestResult.completed_at.desc()).all()
    
    if not results:
        return {...}  # пустой ответ
    
    result_ids = [r.id for r in results]
    test_ids = list(set(r.test_id for r in results))
    
    # 🔥 ОДИН запрос: количество УНИКАЛЬНЫХ задач во всех тестах
    unique_tasks_count = db.query(
        func.count(func.distinct(models.TestTaskAssociation.task_id))
    ).filter(
        models.TestTaskAssociation.test_id.in_(test_ids)
    ).scalar() or 0
    
    # Все ответы за период
    user_answers = db.query(models.UserAnswer).filter(
        models.UserAnswer.result_id.in_(result_ids)
    ).all()
    
    # 🔥 Группируем ответы по task_id — берём лучший результат для каждого задания
    best_answers = {}
    for a in user_answers:
        task_id = a.task_id
        if task_id not in best_answers:
            best_answers[task_id] = a
        else:
            # Берём ответ с максимальными баллами
            if (a.points_earned or 0) > (best_answers[task_id].points_earned or 0):
                best_answers[task_id] = a
            # При равных баллах — берём более поздний
            elif (a.points_earned or 0) == (best_answers[task_id].points_earned or 0):
                if a.result.completed_at and best_answers[task_id].result.completed_at:
                    if a.result.completed_at > best_answers[task_id].result.completed_at:
                        best_answers[task_id] = a
    
    # Правильными считаем только непустые и верные ответы (из лучших)
    correct_tasks = sum(
        1 for a in best_answers.values()
        if a.is_correct and a.user_text_answer and str(a.user_text_answer).strip() not in ['', '[]', 'None', 'null']
    )
    
    # Подсчёт максимальных баллов для тестов
    task_points_expr = case((models.Task.is_open_answer == True, 2), else_=1)
    test_max_points = dict(
        db.query(
            models.TestTaskAssociation.test_id,
            func.sum(task_points_expr).label("max_total")
        )
        .join(models.Task, models.TestTaskAssociation.task_id == models.Task.id)
        .filter(models.TestTaskAssociation.test_id.in_(test_ids))
        .group_by(models.TestTaskAssociation.test_id)
        .all()
    )
    
    # Проценты по тестам
    percentages = []
    for r in results:
        max_points = test_max_points.get(r.test_id, 0)
        if max_points > 0:
            percentage = (r.total_points or 0) * 100.0 / max_points
            percentages.append(percentage)
    
    avg_score = round(sum(percentages) / len(percentages), 1) if percentages else 0.0
    best_score = round(max(percentages), 1) if percentages else 0.0
    worst_score = round(min(percentages), 1) if percentages else 0.0
    
    # Группировка по дням
    daily_map = {}
    for r in results:
        day_key = r.completed_at.strftime("%Y-%m-%d") if r.completed_at else end_date.strftime("%Y-%m-%d")
        if day_key not in daily_map:
            daily_map[day_key] = {
                "date": day_key,
                "tests_count": 0,
                "total_tasks": 0,
                "correct_tasks": 0,
                "scores": [],
                "seen_tasks": set()  # 🔥 Отслеживаем уникальные задания в дне
            }
        
        daily_map[day_key]["tests_count"] += 1
        
        # 🔥 Считаем уникальные задания теста для этого дня
        test_tasks = db.query(models.TestTaskAssociation.task_id).filter(
            models.TestTaskAssociation.test_id == r.test_id
        ).all()
        
        for (task_id,) in test_tasks:
            if task_id not in daily_map[day_key]["seen_tasks"]:
                daily_map[day_key]["seen_tasks"].add(task_id)
                daily_map[day_key]["total_tasks"] += 1
                
                # Проверяем, решено ли задание правильно (из лучших)
                best = best_answers.get(task_id)
                if best and best.is_correct and best.user_text_answer and str(best.user_text_answer).strip() not in ['', '[]', 'None', 'null']:
                    daily_map[day_key]["correct_tasks"] += 1
        
        max_points = test_max_points.get(r.test_id, 0)
        if max_points > 0:
            percentage = (r.total_points or 0) * 100.0 / max_points
            daily_map[day_key]["scores"].append(percentage)
    
    daily_stats = []
    for day_key in sorted(daily_map.keys()):
        day_data = daily_map[day_key]
        day_data["avg_score"] = round(
            sum(day_data["scores"]) / len(day_data["scores"]), 1
        ) if day_data["scores"] else 0.0
        del day_data["scores"]
        del day_data["seen_tasks"]
        daily_stats.append(day_data)
    
    streak = _calculate_streak([d["date"] for d in daily_stats], end_date)
    
    return {
        "period": period,
        "user_id": user_id,
        "user_name": f"{user.first_name or ''} {user.last_name or ''}".strip() or user.username,
        "start_date": start_date.isoformat() if start_date else None,
        "end_date": end_date.isoformat(),
        "total_tests": len(results),
        "total_tasks": unique_tasks_count,  # 🔥 Уникальные задания
        "correct_tasks": correct_tasks,      # Лучшие правильные ответы
        "avg_score": avg_score,
        "best_score": best_score,
        "worst_score": worst_score,
        "streak_days": streak,
        "daily_stats": daily_stats
    }

def _get_topics_stats(user_id: int, period: str, db: Session, current_user: models.User) -> dict:
    """Логика получения статистики по темам с их разделами."""
    user = _check_access(user_id, db, current_user)
    start_date, end_date = _get_period_dates(period)
    
    # Получаем результаты
    results_query = db.query(models.TestResult).filter(models.TestResult.user_id == user_id)
    if start_date:
        results_query = results_query.filter(models.TestResult.completed_at >= start_date)
    
    results = results_query.all()
    result_ids = [r.id for r in results]
    test_ids = list(set(r.test_id for r in results))
    
    # 🔥 Шаг 1: Все УНИКАЛЬНЫЕ задачи в тестах по темам/разделам
    total_tasks_query = db.query(
        models.Task.topic,
        models.Task.section,
        func.count(func.distinct(models.Task.id)).label("total_unique")
    ).join(
        models.TestTaskAssociation, models.Task.id == models.TestTaskAssociation.task_id
    ).filter(
        models.TestTaskAssociation.test_id.in_(test_ids)
    ).group_by(
        models.Task.topic,
        models.Task.section
    ).all()
    
    total_tasks_map = {}
    for topic, section, total in total_tasks_query:
        key = (topic, section or "Общее")
        total_tasks_map[key] = total
    
    # 🔥 Шаг 2: Получаем лучшие ответы по каждому заданию
    user_answers = db.query(models.UserAnswer).filter(
        models.UserAnswer.result_id.in_(result_ids)
    ).all()
    
    # Группируем по task_id — берём лучший результат
    best_answers = {}
    for a in user_answers:
        task_id = a.task_id
        if task_id not in best_answers:
            best_answers[task_id] = a
        elif (a.points_earned or 0) > (best_answers[task_id].points_earned or 0):
            best_answers[task_id] = a
    
    # 🔥 Шаг 3: Считаем правильные ответы по темам (только лучшие, уникальные)
    correct_map = {}
    for task_id, answer in best_answers.items():
        if answer.is_correct and answer.user_text_answer and str(answer.user_text_answer).strip() not in ['', '[]', 'None', 'null']:
            task = db.query(models.Task).filter(models.Task.id == task_id).first()
            if task and task.topic:
                key = (task.topic, task.section or "Общее")
                correct_map[key] = correct_map.get(key, 0) + 1
    
    # Группируем по темам
    topics_map = {}
    
    for (topic, section), total in total_tasks_map.items():
        if not topic:
            continue
        
        correct = correct_map.get((topic, section), 0)
        mastery = round((correct / total) * 100, 1) if total > 0 else 0.0
        
        if topic not in topics_map:
            topics_map[topic] = {
                "topic": topic,
                "total_tasks": 0,
                "correct_tasks": 0,
                "sections": {}
            }
        
        topics_map[topic]["total_tasks"] += total
        topics_map[topic]["correct_tasks"] += correct
        
        topics_map[topic]["sections"][section] = {
            "section": section,
            "total_tasks": total,
            "correct_tasks": correct,
            "mastery_percent": mastery
        }
    
    # Формируем результат
    topics = []
    strongest = None
    weakest = None
    max_mastery = -1
    min_mastery = 101
    
    for topic_data in topics_map.values():
        total = topic_data["total_tasks"]
        correct = topic_data["correct_tasks"]
        topic_mastery = round((correct / total) * 100, 1) if total > 0 else 0.0
        
        sections_list = list(topic_data["sections"].values())
        sections_list.sort(key=lambda x: x["mastery_percent"])
        
        topic_item = {
            "topic": topic_data["topic"],
            "total_tasks": total,
            "correct_tasks": correct,
            "mastery_percent": topic_mastery,
            "sections": sections_list
        }
        topics.append(topic_item)
        
        if topic_mastery > max_mastery:
            max_mastery = topic_mastery
            strongest = {
                "topic": topic_data["topic"],
                "total_tasks": total,
                "correct_tasks": correct,
                "mastery_percent": topic_mastery
            }
        
        if topic_mastery < min_mastery and total >= 3:
            min_mastery = topic_mastery
            weakest = {
                "topic": topic_data["topic"],
                "total_tasks": total,
                "correct_tasks": correct,
                "mastery_percent": topic_mastery
            }
    
    topics.sort(key=lambda x: x["mastery_percent"])
    
    return {
        "period": period,
        "user_id": user_id,
        "user_name": f"{user.first_name or ''} {user.last_name or ''}".strip() or user.username,
        "topics": topics,
        "strongest_topic": strongest,
        "weakest_topic": weakest
    }

def _get_difficulty_stats(user_id: int, period: str, db: Session, current_user: models.User) -> dict:
    """Логика получения статистики по сложности."""
    user = _check_access(user_id, db, current_user)
    start_date, end_date = _get_period_dates(period)
    
    results_query = db.query(models.TestResult).filter(models.TestResult.user_id == user_id)
    if start_date:
        results_query = results_query.filter(models.TestResult.completed_at >= start_date)
    
    results = results_query.all()
    result_ids = [r.id for r in results]
    test_ids = list(set(r.test_id for r in results))
    
    # 🔥 Шаг 1: Все УНИКАЛЬНЫЕ задачи в тестах по сложности
    total_tasks_query = db.query(
        models.Task.difficulty,
        func.count(func.distinct(models.Task.id)).label("total_unique")
    ).join(
        models.TestTaskAssociation, models.Task.id == models.TestTaskAssociation.task_id
    ).filter(
        models.TestTaskAssociation.test_id.in_(test_ids)
    ).group_by(
        models.Task.difficulty
    ).all()
    
    total_map = {diff: total for diff, total in total_tasks_query if diff}
    
    # 🔥 Шаг 2: Получаем лучшие ответы
    user_answers = db.query(models.UserAnswer).filter(
        models.UserAnswer.result_id.in_(result_ids)
    ).all()
    
    best_answers = {}
    for a in user_answers:
        task_id = a.task_id
        if task_id not in best_answers:
            best_answers[task_id] = a
        elif (a.points_earned or 0) > (best_answers[task_id].points_earned or 0):
            best_answers[task_id] = a
    
    # 🔥 Шаг 3: Считаем правильные по сложности (только уникальные)
    correct_map = {}
    for task_id, answer in best_answers.items():
        if answer.is_correct and answer.user_text_answer and str(answer.user_text_answer).strip() not in ['', '[]', 'None', 'null']:
            task = db.query(models.Task).filter(models.Task.id == task_id).first()
            if task and task.difficulty:
                correct_map[task.difficulty] = correct_map.get(task.difficulty, 0) + 1
    
    difficulties = []
    for diff in sorted(set(list(total_map.keys()) + list(correct_map.keys()))):
        total = total_map.get(diff, 0)
        correct = correct_map.get(diff, 0)
        mastery = round((correct / total) * 100, 1) if total > 0 else 0.0
        
        difficulties.append({
            "difficulty": diff,
            "total_tasks": total,       # Уникальные задания
            "correct_tasks": correct,   # Лучшие правильные
            "mastery_percent": mastery
        })
    
    difficulties.sort(key=lambda x: x["difficulty"])
    
    return {
        "period": period,
        "user_id": user_id,
        "user_name": f"{user.first_name or ''} {user.last_name or ''}".strip() or user.username,
        "difficulties": difficulties
    }

def _get_full_stats(user_id: int, period: str, db: Session, current_user: models.User) -> dict:
    """Логика получения полной статистики."""
    _check_access(user_id, db, current_user)
    
    return {
        "period": _get_period_stats(user_id, period, db, current_user),
        "topics": _get_topics_stats(user_id, period, db, current_user),
        "difficulties": _get_difficulty_stats(user_id, period, db, current_user)
    }