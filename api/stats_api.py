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
        return {
            "period": period,
            "user_id": user_id,
            "user_name": f"{user.first_name or ''} {user.last_name or ''}".strip() or user.username,
            "start_date": start_date.isoformat() if start_date else None,
            "end_date": end_date.isoformat(),
            "total_tests": 0,
            "total_tasks": 0,
            "correct_tasks": 0,
            "avg_score": 0.0,
            "best_score": 0.0,
            "worst_score": 0.0,
            "streak_days": 0,
            "daily_stats": []
        }
    
    result_ids = [r.id for r in results]
    
    # Все ответы за период
    user_answers = db.query(models.UserAnswer).filter(
        models.UserAnswer.result_id.in_(result_ids)
    ).all()
    
    # Считаем ВСЕ задачи (включая пустые ответы)
    total_tasks = len(user_answers)
    
    # Правильными считаем только непустые и верные ответы
    correct_tasks = sum(
        1 for a in user_answers 
        if a.is_correct and a.user_text_answer and str(a.user_text_answer).strip() not in ['', '[]', 'None', 'null']
    )
    
    # Подсчёт максимальных баллов для тестов
    task_points_expr = case((models.Task.is_open_answer == True, 2), else_=1)
    test_max_points_sub = (
        select(
            models.TestTaskAssociation.test_id,
            func.sum(task_points_expr).label("max_total")
        )
        .join(models.Task, models.TestTaskAssociation.task_id == models.Task.id)
        .group_by(models.TestTaskAssociation.test_id)
        .subquery()
    )
    
    # Проценты по тестам
    percentages = []
    for r in results:
        max_points = db.query(test_max_points_sub.c.max_total).filter(
            test_max_points_sub.c.test_id == r.test_id
        ).scalar()
        
        if max_points and max_points > 0:
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
                "scores": []
            }
        
        daily_map[day_key]["tests_count"] += 1
        
        max_points = db.query(test_max_points_sub.c.max_total).filter(
            test_max_points_sub.c.test_id == r.test_id
        ).scalar()
        
        if max_points and max_points > 0:
            percentage = (r.total_points or 0) * 100.0 / max_points
            daily_map[day_key]["scores"].append(percentage)
        
        # Считаем задания за этот день с учётом пустых ответов
        day_answers = [a for a in user_answers if a.result_id == r.id]
        daily_map[day_key]["total_tasks"] += len(day_answers)
        daily_map[day_key]["correct_tasks"] += sum(
            1 for a in day_answers 
            if a.is_correct and a.user_text_answer and str(a.user_text_answer).strip() not in ['', '[]', 'None', 'null']
        )
    
    daily_stats = []
    for day_key in sorted(daily_map.keys()):
        day_data = daily_map[day_key]
        day_data["avg_score"] = round(
            sum(day_data["scores"]) / len(day_data["scores"]), 1
        ) if day_data["scores"] else 0.0
        del day_data["scores"]
        daily_stats.append(day_data)
    
    streak = _calculate_streak([d["date"] for d in daily_stats], end_date)
    
    return {
        "period": period,
        "user_id": user_id,
        "user_name": f"{user.first_name or ''} {user.last_name or ''}".strip() or user.username,
        "start_date": start_date.isoformat() if start_date else None,
        "end_date": end_date.isoformat(),
        "total_tests": len(results),
        "total_tasks": total_tasks,
        "correct_tasks": correct_tasks,
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
    
    # Запрос: группируем по topic + section
    answers_query = db.query(
        models.Task.topic,
        models.Task.section,
        func.count(models.UserAnswer.id).label("total"),
        func.sum(
            case(
                (
                    (models.UserAnswer.is_correct == True) & 
                    (models.UserAnswer.user_text_answer != None) & 
                    (models.UserAnswer.user_text_answer != '') & 
                    (models.UserAnswer.user_text_answer != '[]'),
                    1
                ), 
                else_=0
            )
        ).label("correct")
    ).join(
        models.Task, models.UserAnswer.task_id == models.Task.id
    ).join(
        models.TestResult, models.UserAnswer.result_id == models.TestResult.id
    ).filter(
        models.TestResult.user_id == user_id
    )
    
    if start_date:
        answers_query = answers_query.filter(models.TestResult.completed_at >= start_date)
    
    answers_query = answers_query.group_by(
        models.Task.topic, 
        models.Task.section
    ).order_by(
        models.Task.topic,
        models.Task.section
    ).all()
    
    # Группируем: тема → {общая статистика + разделы}
    topics_map = {}
    
    for topic, section, total, correct in answers_query:
        if not topic:
            continue
        
        section_name = section or "Общее"
        mastery = round((correct / total) * 100, 1) if total > 0 else 0.0
        
        if topic not in topics_map:
            topics_map[topic] = {
                "topic": topic,
                "total_tasks": 0,
                "correct_tasks": 0,
                "sections": []
            }
        
        # Суммируем общую статистику темы
        topics_map[topic]["total_tasks"] += total
        topics_map[topic]["correct_tasks"] += correct
        
        # Добавляем раздел
        topics_map[topic]["sections"].append({
            "section": section_name,
            "total_tasks": total,
            "correct_tasks": correct,
            "mastery_percent": mastery
        })
    
    # Считаем общий процент для каждой темы и формируем результат
    topics = []
    strongest = None
    weakest = None
    max_mastery = -1
    min_mastery = 101
    
    for topic_data in topics_map.values():
        total = topic_data["total_tasks"]
        correct = topic_data["correct_tasks"]
        topic_mastery = round((correct / total) * 100, 1) if total > 0 else 0.0
        
        # Сортируем разделы от худшего к лучшему
        topic_data["sections"].sort(key=lambda x: x["mastery_percent"])
        
        topic_item = {
            "topic": topic_data["topic"],
            "total_tasks": total,
            "correct_tasks": correct,
            "mastery_percent": topic_mastery,
            "sections": topic_data["sections"]
        }
        topics.append(topic_item)
        
        # Определяем сильные/слабые темы
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
    
    # Сортируем темы по проценту усвоения (худшие сверху)
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
    
    answers_query = db.query(
        models.Task.difficulty,
        func.count(models.UserAnswer.id).label("total"),
        func.sum(
            case(
                (
                    (models.UserAnswer.is_correct == True) & 
                    (models.UserAnswer.user_text_answer != None) & 
                    (models.UserAnswer.user_text_answer != '') & 
                    (models.UserAnswer.user_text_answer != '[]'),
                    1
                ), 
                else_=0
            )
        ).label("correct")
    ).join(
        models.Task, models.UserAnswer.task_id == models.Task.id
    ).join(
        models.TestResult, models.UserAnswer.result_id == models.TestResult.id
    ).filter(
        models.TestResult.user_id == user_id
    )
    
    if start_date:
        answers_query = answers_query.filter(models.TestResult.completed_at >= start_date)
    
    answers_query = answers_query.group_by(models.Task.difficulty).all()
    
    difficulties = []
    for diff, total, correct in answers_query:
        if not diff:
            continue
        
        mastery = round((correct / total) * 100, 1) if total > 0 else 0.0
        
        difficulties.append({
            "difficulty": diff,
            "total_tasks": total,
            "correct_tasks": correct,
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