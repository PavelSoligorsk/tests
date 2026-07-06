from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func
import models
from typing import List, Optional

class TestRepository:
    def __init__(self, db: Session):
        self.db = db
    
    def get_available_tests(self):
        return self.db.query(models.Test)\
            .options(joinedload(models.Test.tasks))\
            .filter(
                models.Test.is_active == True,
                (models.Test.is_autocompile == True) | (models.Test.is_autocompile == None)
            ).all()
    
    def get_test_by_id(self, test_id: int):
        return self.db.query(models.Test)\
            .options(joinedload(models.Test.tasks))\
            .filter(models.Test.id == test_id)\
            .first()
    
    def get_tests_by_ids(self, test_ids: List[int]):
        return self.db.query(models.Test)\
            .options(joinedload(models.Test.tasks))\
            .filter(models.Test.id.in_(test_ids))\
            .all()
    
    def create_test(self, test_data: dict, tasks: List[models.Task]):
        new_test = models.Test(**test_data)
        self.db.add(new_test)
        self.db.flush()
        new_test.tasks = tasks
        self.db.commit()
        self.db.refresh(new_test)
        return new_test
    
    def deactivate_test(self, test_id: int):
        test = self.get_test_by_id(test_id)
        if test:
            test.is_active = False
            self.db.commit()
        return test
    
    def get_test_with_tasks(self, test_id: int):
        return self.db.query(models.Test)\
            .options(joinedload(models.Test.tasks))\
            .filter(models.Test.id == test_id)\
            .first()
    
    def get_teacher_tests(self, teacher_id: int, role: str):
        """Получить тесты учителя или все для админа"""
        query = self.db.query(models.Test).options(joinedload(models.Test.tasks))
        
        if role == "teacher":
            query = query.filter(models.Test.creator_id == teacher_id)
        
        return query.order_by(models.Test.id.desc()).all()

    def update_test(self, test: models.Test, update_data: dict, tasks=None):
        """Обновить тест"""
        for field, value in update_data.items():
            setattr(test, field, value)
        
        if tasks is not None:
            test.tasks = tasks
        
        self.db.commit()
        self.db.refresh(test)
        return self.get_test_with_tasks(test.id)

    def delete_test_cascade(self, test_id: int):
        """Удалить тест и все связанные данные"""
        test = self.db.query(models.Test).filter(models.Test.id == test_id).first()
        if not test:
            return None
        
        try:
            # 1. Сначала удаляем ответы пользователей
            result_ids = self.db.query(models.TestResult.id).filter(
                models.TestResult.test_id == test_id
            ).all()
            result_ids = [r[0] for r in result_ids]
            
            if result_ids:
                self.db.query(models.UserAnswer).filter(
                    models.UserAnswer.result_id.in_(result_ids)
                ).delete(synchronize_session=False)
            
            # 2. Удаляем результаты
            self.db.query(models.TestResult).filter(
                models.TestResult.test_id == test_id
            ).delete(synchronize_session=False)
            
            # 3. Удаляем назначения
            self.db.query(models.TestAssignment).filter(
                models.TestAssignment.test_id == test_id
            ).delete(synchronize_session=False)
            
            # 4. 🔥 Очищаем связи с задачами ПЕРЕД удалением теста
            test.tasks = []  # ← Это очистит test_task_association
            self.db.flush()
            
            # 5. Удаляем сам тест
            self.db.delete(test)
            self.db.commit()
            return test
        except Exception as e:
            self.db.rollback()
            raise e


    def get_available_tests_meta(self):
        """Получить доступные тесты без загрузки заданий"""
        return self.db.query(models.Test).filter(
            models.Test.is_active == True,
            (models.Test.is_autocompile == True) | (models.Test.is_autocompile == None)
        ).all()


    def check_test_owner(self, test_id: int, teacher_id: int):
        """Проверить владельца теста"""
        test = self.get_test_by_id(test_id)
        if not test:
            return None
        if test.creator_id != teacher_id:
            return None
        return test

    def calculate_test_max_points(self, test) -> int:
        """Вычислить максимальные баллы за тест"""
        if not test.tasks:
            return 0
        
        max_points = 0
        for task in test.tasks:
            if task.is_open_answer:
                max_points += 2
            else:
                if task.options and len(task.options) >= 2:
                    max_points += 1
                else:
                    max_points += 2
        return max_points
    
    def get_ai_tests_by_user(self, user_id: int):
        """Получить AI-тесты, созданные пользователем"""
        return self.db.query(models.Test).filter(
            models.Test.creator_id == user_id,
            models.Test.is_ai_generated == True
        ).order_by(models.Test.id.desc()).all()