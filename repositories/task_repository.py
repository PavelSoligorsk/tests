from sqlalchemy.orm import Session
from sqlalchemy import func, or_, and_
import models
from typing import List, Optional

class TaskRepository:
    def __init__(self, db: Session):
        self.db = db
    
    def get_task_by_id(self, task_id: int):
        return self.db.query(models.Task).filter(models.Task.id == task_id).first()
    
    def get_tasks_by_ids(self, task_ids: List[int]):
        return self.db.query(models.Task).filter(models.Task.id.in_(task_ids)).all()
    
    def get_tasks_by_topics(self, topics: List[str], sections_map: dict, difficulties: List[int], limit: int = 300):
        conditions = []
        for topic, sections in sections_map.items():
            if sections:
                conditions.append(
                    and_(
                        models.Task.topic == topic,
                        models.Task.section.in_(sections)
                    )
                )
            else:
                conditions.append(models.Task.topic == topic)
        
        if conditions:
            return self.db.query(models.Task).filter(
                or_(*conditions),
                models.Task.difficulty.in_(difficulties)
            ).limit(limit).all()
        return []
    
    def get_random_tasks(self, count: int, task_type: Optional[bool] = None, difficulties: List[int] = None):
        query = self.db.query(models.Task)
        
        if task_type is not None:
            query = query.filter(models.Task.is_open_answer == task_type)
        
        if difficulties:
            query = query.filter(models.Task.difficulty.in_(difficulties))
        
        return query.order_by(func.random()).limit(count).all()
    
    def get_tasks_by_keywords(self, keywords: List[str], difficulties: List[int], limit: int = 300):
        like_conditions = [models.Task.topic.ilike(f"%{word}%") for word in keywords]
        return self.db.query(models.Task).filter(
            or_(*like_conditions),
            models.Task.difficulty.in_(difficulties)
        ).limit(limit).all()
    
    def get_tasks_structure(self):
        return self.db.query(models.Task.topic, models.Task.section)\
            .filter(models.Task.topic != None)\
            .distinct().all()
    
    def get_tasks_by_test_id(self, test_id: int):
        return self.db.query(models.Task)\
            .join(models.TestTaskAssociation)\
            .filter(models.TestTaskAssociation.test_id == test_id)\
            .order_by(models.Task.topic_number)\
            .all()