from sqlalchemy.orm import Session, joinedload
import models
from typing import List

class ResultRepository:
    def __init__(self, db: Session):
        self.db = db
    
    def create_result(self, test_id: int, user_id: int, total_points: int = 0):
        new_result = models.TestResult(
            test_id=test_id,
            user_id=user_id,
            total_points=total_points
        )
        self.db.add(new_result)
        self.db.flush()
        return new_result
    
    def save_answer(self, result_id: int, task_id: int, user_answer: str, is_correct: bool, points: int):
        answer = models.UserAnswer(
            result_id=result_id,
            task_id=task_id,
            user_text_answer=user_answer,
            is_correct=is_correct,
            points_earned=points
        )
        self.db.add(answer)
        return answer
    
    def update_result_points(self, result_id: int, total_points: int):
        result = self.get_result_by_id(result_id)
        if result:
            result.total_points = total_points
            self.db.commit()
        return result
    
    def get_result_by_id(self, result_id: int):
        return self.db.query(models.TestResult)\
            .options(joinedload(models.TestResult.test))\
            .filter(models.TestResult.id == result_id)\
            .first()
    
    def get_user_history(self, user_id: int):
        return self.db.query(models.TestResult)\
            .options(joinedload(models.TestResult.test))\
            .filter(models.TestResult.user_id == user_id)\
            .order_by(models.TestResult.completed_at.desc())\
            .all()
    
    def get_user_answers_for_result(self, result_id: int):
        return self.db.query(models.UserAnswer)\
            .filter(models.UserAnswer.result_id == result_id)\
            .all()
    
    def get_user_results_for_topic(self, user_id: int, topic_number: int):
        results = self.db.query(models.TestResult)\
            .filter(models.TestResult.user_id == user_id)\
            .all()
        
        result_ids = [r.id for r in results]
        
        if result_ids:
            return self.db.query(models.UserAnswer)\
                .join(models.Task)\
                .filter(
                    models.UserAnswer.result_id.in_(result_ids),
                    models.Task.topic_number == topic_number
                ).all()
        return []
    
    def has_incomplete_attempt(self, user_id: int, test_id: int) -> bool:
        """Проверить, есть ли незавершённая попытка (result без completed_at)"""
        result = self.db.query(models.TestResult).filter(
            models.TestResult.user_id == user_id,
            models.TestResult.test_id == test_id,
            models.TestResult.completed_at == None
        ).first()
        return result is not None