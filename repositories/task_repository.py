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
    
    def get_filtered_tasks(self, task_class=None, topic=None, topic_number=None, section=None):
        """Получить задания с фильтрацией"""
        query = self.db.query(models.Task).order_by(
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

    def get_all_tasks_ordered(self):
        """Получить все задания с сортировкой"""
        return self.db.query(models.Task).order_by(
            models.Task.task_class,
            models.Task.topic_number,
            models.Task.is_open_answer.asc(),
            models.Task.difficulty.asc()
        ).all()
    
    def get_all_tasks(self):
        """Получить все задания"""
        return self.db.query(models.Task).all()

    def create_task(self, task_data: dict):
        """Создать задание"""
        new_task = models.Task(**task_data)
        self.db.add(new_task)
        self.db.commit()
        self.db.refresh(new_task)
        return new_task

    def update_task(self, task: models.Task, update_data: dict):
        """Обновить задание"""
        for key, value in update_data.items():
            setattr(task, key, value)
        self.db.commit()
        self.db.refresh(task)
        return task

    def delete_task(self, task_id: int):
        """Удалить задание и связанные данные"""
        try:
            self.db.query(models.UserAnswer).filter(
                models.UserAnswer.task_id == task_id
            ).delete(synchronize_session=False)
            
            self.db.query(models.TestTaskAssociation).filter(
                models.TestTaskAssociation.task_id == task_id
            ).delete(synchronize_session=False)
            
            task = self.get_task_by_id(task_id)
            if task:
                self.db.delete(task)
                self.db.commit()
            return True
        except Exception as e:
            self.db.rollback()
            raise e

    def get_active_categories(self):
        """Получить уникальные пары класс-тема"""
        return self.db.query(
            models.Task.task_class,
            models.Task.topic_number
        ).distinct().all()

    def get_all_tasks_dict(self):
        """Получить словарь {id: task}"""
        tasks = self.db.query(models.Task).all()
        return {task.id: task for task in tasks}

    def get_tasks_by_class_and_topic(self, task_class, topic_number):
        """Получить задания по классу и теме"""
        return self.db.query(models.Task).filter(
            models.Task.task_class == task_class,
            models.Task.topic_number == topic_number
        ).order_by(
            models.Task.is_open_answer.asc(),
            models.Task.difficulty.asc()
        ).all()