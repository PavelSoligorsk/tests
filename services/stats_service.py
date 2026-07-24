from datetime import datetime, timedelta
from typing import List, Optional
from sqlalchemy.orm import Session
from repositories.stats_repository import StatsRepository

from dto_schemas.stats import (
    DailyStatsItem,
    PeriodStatsResponse,
    TopicSectionItem,
    TopicSummaryItem,
    TopicItem,
    TopicsStatsResponse,
    DifficultyItem,
    DifficultyStatsResponse,
    FullStatsResponse,
)


class StatsService:
    def __init__(self, db: Session):
        self.stats_repo = StatsRepository(db)
        self.db = db
    
    def _get_period_dates(self, period: str) -> tuple:
        """Возвращает (start_date, end_date) для указанного периода"""
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
            raise ValueError("Допустимые периоды: week, month, 3months, 6months, year, all")
        
        return period_map[period], now
    
    def _check_access(self, user_id: int, current_user):
        """Проверяет доступ к статистике"""
        if current_user.role == "student" and current_user.id != user_id:
            raise PermissionError("Вы можете смотреть только свою статистику")
        
        if current_user.role == "teacher" and current_user.id != user_id:
            if not self.stats_repo.check_teacher_student_link(current_user.id, user_id):
                raise PermissionError("У вас нет доступа к этому ученику")
        
        user = self.stats_repo.get_user_by_id(user_id)
        if not user:
            raise ValueError("Пользователь не найден")
        
        return user
    
    def _get_best_answers(self, user_answers):
        """Группирует ответы по task_id — берёт лучший результат"""
        best_answers = {}
        for a in user_answers:
            task_id = a.task_id
            if task_id not in best_answers:
                best_answers[task_id] = a
            elif (a.points_earned or 0) > (best_answers[task_id].points_earned or 0):
                best_answers[task_id] = a
            elif (a.points_earned or 0) == (best_answers[task_id].points_earned or 0):
                if a.result.completed_at and best_answers[task_id].result.completed_at:
                    if a.result.completed_at > best_answers[task_id].result.completed_at:
                        best_answers[task_id] = a
        return best_answers
    
    def _is_valid_answer(self, answer) -> bool:
        """Проверяет, что ответ непустой и правильный"""
        if not answer.is_correct:
            return False
        text = str(answer.user_text_answer).strip() if answer.user_text_answer else ""
        return text not in ['', '[]', 'None', 'null']
    
    def _calculate_streak(self, daily_dates: List[str], end_date: datetime) -> int:
        """Вычисляет серию дней подряд"""
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
    
    def get_period_stats(self, user_id: int, period: str, current_user) -> PeriodStatsResponse:
        """Статистика по периоду"""
        user = self._check_access(user_id, current_user)
        start_date, end_date = self._get_period_dates(period)
        
        results = self.stats_repo.get_user_results(user_id, start_date)
        
        if not results:
            return self._empty_period_response(user_id, period, user, start_date, end_date)
        
        result_ids = [r.id for r in results]
        test_ids = list(set(r.test_id for r in results))
        
        unique_tasks_count = self.stats_repo.get_unique_tasks_count(test_ids)
        user_answers = self.stats_repo.get_user_answers_by_results(result_ids)
        best_answers = self._get_best_answers(user_answers)
        
        correct_tasks = sum(1 for a in best_answers.values() if self._is_valid_answer(a))
        test_max_points = self.stats_repo.get_test_max_points(test_ids)
        
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
        daily_stats = self._build_daily_stats(results, test_ids, test_max_points, best_answers, end_date)
        streak = self._calculate_streak([d["date"] for d in daily_stats], end_date)
        
        return PeriodStatsResponse(
            period=period,
            user_id=user_id,
            user_name=f"{user.first_name or ''} {user.last_name or ''}".strip() or user.username,
            start_date=start_date.isoformat() if start_date else None,
            end_date=end_date.isoformat(),
            total_tests=len(results),
            total_tasks=unique_tasks_count,
            correct_tasks=correct_tasks,
            avg_score=avg_score,
            best_score=best_score,
            worst_score=worst_score,
            streak_days=streak,
            daily_stats=daily_stats,
        )
    
    def get_topics_stats(self, user_id: int, period: str, current_user) -> TopicsStatsResponse:
        """Статистика по темам с разделами"""
        user = self._check_access(user_id, current_user)
        start_date, end_date = self._get_period_dates(period)
        
        results = self.stats_repo.get_user_results(user_id, start_date)
        
        if not results:
            return self._empty_topics_response(user_id, period, user)
        
        result_ids = [r.id for r in results]
        test_ids = list(set(r.test_id for r in results))
        
        total_tasks_query = self.stats_repo.get_topics_with_counts(test_ids)
        user_answers = self.stats_repo.get_user_answers_by_results(result_ids)
        best_answers = self._get_best_answers(user_answers)
        
        # Считаем правильные по темам
        correct_map = {}
        for task_id, answer in best_answers.items():
            if self._is_valid_answer(answer):
                task = self.stats_repo.get_task_by_id(task_id)
                if task and task.topic:
                    key = (task.topic, task.section or "Общее")
                    correct_map[key] = correct_map.get(key, 0) + 1
        
        return self._build_topics_response(total_tasks_query, correct_map, user_id, period, user)
    
    def get_difficulty_stats(self, user_id: int, period: str, current_user) -> DifficultyStatsResponse:
        """Статистика по сложности"""
        user = self._check_access(user_id, current_user)
        start_date, end_date = self._get_period_dates(period)
        
        results = self.stats_repo.get_user_results(user_id, start_date)
        
        if not results:
            return self._empty_difficulty_response(user_id, period, user)
        
        result_ids = [r.id for r in results]
        test_ids = list(set(r.test_id for r in results))
        
        total_tasks_query = self.stats_repo.get_difficulty_counts(test_ids)
        user_answers = self.stats_repo.get_user_answers_by_results(result_ids)
        best_answers = self._get_best_answers(user_answers)
        
        correct_map = {}
        for task_id, answer in best_answers.items():
            if self._is_valid_answer(answer):
                task = self.stats_repo.get_task_by_id(task_id)
                if task and task.difficulty:
                    correct_map[task.difficulty] = correct_map.get(task.difficulty, 0) + 1
        
        return self._build_difficulty_response(total_tasks_query, correct_map, user_id, period, user)
    
    def get_full_stats(self, user_id: int, period: str, current_user) -> FullStatsResponse:
        """Полная статистика"""
        self._check_access(user_id, current_user)
        
        return FullStatsResponse(
            period=self.get_period_stats(user_id, period, current_user),
            topics=self.get_topics_stats(user_id, period, current_user),
            difficulties=self.get_difficulty_stats(user_id, period, current_user),
        )
    
    # Вспомогательные методы сборки ответов
    def _build_daily_stats(self, results, test_ids, test_max_points, best_answers, end_date):
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
                    "seen_tasks": set()
                }
            
            daily_map[day_key]["tests_count"] += 1
            
            test_tasks = self.stats_repo.get_test_tasks(r.test_id)
            for task_id in test_tasks:
                if task_id not in daily_map[day_key]["seen_tasks"]:
                    daily_map[day_key]["seen_tasks"].add(task_id)
                    daily_map[day_key]["total_tasks"] += 1
                    
                    best = best_answers.get(task_id)
                    if best and self._is_valid_answer(best):
                        daily_map[day_key]["correct_tasks"] += 1
            
            max_points = test_max_points.get(r.test_id, 0)
            if max_points > 0:
                percentage = (r.total_points or 0) * 100.0 / max_points
                daily_map[day_key]["scores"].append(percentage)
        
        daily_stats = []
        for day_key in sorted(daily_map.keys()):
            day_data = daily_map[day_key]
            avg = round(
                sum(day_data["scores"]) / len(day_data["scores"]), 1
            ) if day_data["scores"] else 0.0
            daily_stats.append(DailyStatsItem(
                date=day_data["date"],
                tests_count=day_data["tests_count"],
                total_tasks=day_data["total_tasks"],
                correct_tasks=day_data["correct_tasks"],
                avg_score=avg,
            ))
        
        return daily_stats
    
    def _build_topics_response(self, total_tasks_query, correct_map, user_id, period, user) -> TopicsStatsResponse:
        topics_map = {}
        
        for topic, section, total in total_tasks_query:
            if not topic:
                continue
            
            correct = correct_map.get((topic, section or "Общее"), 0)
            mastery = round((correct / total) * 100, 1) if total > 0 else 0.0
            
            if topic not in topics_map:
                topics_map[topic] = {
                    "total_tasks": 0,
                    "correct_tasks": 0,
                    "sections": {}
                }
            
            topics_map[topic]["total_tasks"] += total
            topics_map[topic]["correct_tasks"] += correct
            topics_map[topic]["sections"][section or "Общее"] = TopicSectionItem(
                section=section or "Общее",
                total_tasks=total,
                correct_tasks=correct,
                mastery_percent=mastery,
            )
        
        topics = []
        strongest = None
        weakest = None
        max_mastery = -1.0
        min_mastery = 101.0
        
        for topic_name, topic_data in topics_map.items():
            total = topic_data["total_tasks"]
            correct = topic_data["correct_tasks"]
            topic_mastery = round((correct / total) * 100, 1) if total > 0 else 0.0
            
            sections_list = sorted(
                topic_data["sections"].values(),
                key=lambda x: x.mastery_percent
            )
            
            topic_item = TopicItem(
                topic=topic_name,
                total_tasks=total,
                correct_tasks=correct,
                mastery_percent=topic_mastery,
                sections=sections_list,
            )
            topics.append(topic_item)
            
            if topic_mastery > max_mastery:
                max_mastery = topic_mastery
                strongest = TopicSummaryItem(
                    topic=topic_name,
                    total_tasks=total,
                    correct_tasks=correct,
                    mastery_percent=topic_mastery,
                )
            
            if topic_mastery < min_mastery and total >= 3:
                min_mastery = topic_mastery
                weakest = TopicSummaryItem(
                    topic=topic_name,
                    total_tasks=total,
                    correct_tasks=correct,
                    mastery_percent=topic_mastery,
                )
        
        topics.sort(key=lambda x: x.mastery_percent)
        
        return TopicsStatsResponse(
            period=period,
            user_id=user_id,
            user_name=f"{user.first_name or ''} {user.last_name or ''}".strip() or user.username,
            topics=topics,
            strongest_topic=strongest,
            weakest_topic=weakest,
        )
    
    def _build_difficulty_response(self, total_tasks_query, correct_map, user_id, period, user) -> DifficultyStatsResponse:
        total_map = {diff: total for diff, total in total_tasks_query if diff}
        
        difficulties = []
        for diff in sorted(set(list(total_map.keys()) + list(correct_map.keys()))):
            total = total_map.get(diff, 0)
            correct = correct_map.get(diff, 0)
            mastery = round((correct / total) * 100, 1) if total > 0 else 0.0
            
            difficulties.append(DifficultyItem(
                difficulty=diff,
                total_tasks=total,
                correct_tasks=correct,
                mastery_percent=mastery,
            ))
        
        difficulties.sort(key=lambda x: x.difficulty)
        
        return DifficultyStatsResponse(
            period=period,
            user_id=user_id,
            user_name=f"{user.first_name or ''} {user.last_name or ''}".strip() or user.username,
            difficulties=difficulties,
        )
    
    def _empty_period_response(self, user_id, period, user, start_date, end_date) -> PeriodStatsResponse:
        return PeriodStatsResponse(
            period=period,
            user_id=user_id,
            user_name=f"{user.first_name or ''} {user.last_name or ''}".strip() or user.username,
            start_date=start_date.isoformat() if start_date else None,
            end_date=end_date.isoformat(),
            total_tests=0,
            total_tasks=0,
            correct_tasks=0,
            avg_score=0.0,
            best_score=0.0,
            worst_score=0.0,
            streak_days=0,
            daily_stats=[],
        )
    
    def _empty_topics_response(self, user_id, period, user) -> TopicsStatsResponse:
        return TopicsStatsResponse(
            period=period,
            user_id=user_id,
            user_name=f"{user.first_name or ''} {user.last_name or ''}".strip() or user.username,
            topics=[],
            strongest_topic=None,
            weakest_topic=None,
        )
    
    def _empty_difficulty_response(self, user_id, period, user) -> DifficultyStatsResponse:
        return DifficultyStatsResponse(
            period=period,
            user_id=user_id,
            user_name=f"{user.first_name or ''} {user.last_name or ''}".strip() or user.username,
            difficulties=[],
        )


class PermissionError(Exception):
    pass