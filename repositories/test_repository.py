from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func
from typing import List, Optional

from core.models import (
    Test, Task, TestResult, UserAnswer, TestAssignment
)


class TestRepository:
    def __init__(self, db: Session):
        self.db = db
    
    def get_available_tests(self):
        return self.db.query(Test)\
            .options(joinedload(Test.tasks))\
            .filter(
                Test.is_active == True,
                (Test.is_autocompile == True) | (Test.is_autocompile == None)
            ).all()
    
    def get_test_by_id(self, test_id: int):
        return self.db.query(Test)\
            .options(joinedload(Test.tasks))\
            .filter(Test.id == test_id)\
            .first()
    
    def get_tests_by_ids(self, test_ids: List[int]):
        return self.db.query(Test)\
            .options(joinedload(Test.tasks))\
            .filter(Test.id.in_(test_ids))\
            .all()
    
    def create_test(self, test_data: dict, tasks: List[Task]):
        new_test = Test(**test_data)
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
        return self.db.query(Test)\
            .options(joinedload(Test.tasks))\
            .filter(Test.id == test_id)\
            .first()
    
    def get_teacher_tests(self, teacher_id: int, role: str):
        """Получить тесты учителя или все для админа"""
        query = self.db.query(Test).options(joinedload(Test.tasks))
        
        if role == "teacher":
            query = query.filter(Test.creator_id == teacher_id)
        
        return query.order_by(Test.id.desc()).all()

    def update_test(self, test: Test, update_data: dict, tasks=None):
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
        test = self.db.query(Test).filter(Test.id == test_id).first()
        if not test:
            return None
        
        try:
            # 1. Сначала удаляем ответы пользователей
            result_ids = self.db.query(TestResult.id).filter(
                TestResult.test_id == test_id
            ).all()
            result_ids = [r[0] for r in result_ids]
            
            if result_ids:
                self.db.query(UserAnswer).filter(
                    UserAnswer.result_id.in_(result_ids)
                ).delete(synchronize_session=False)
            
            # 2. Удаляем результаты
            self.db.query(TestResult).filter(
                TestResult.test_id == test_id
            ).delete(synchronize_session=False)
            
            # 3. Удаляем назначения
            self.db.query(TestAssignment).filter(
                TestAssignment.test_id == test_id
            ).delete(synchronize_session=False)
            
            # 4. Очищаем связи с задачами ПЕРЕД удалением теста
            test.tasks = []
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
        return self.db.query(Test).options(
            joinedload(Test.tasks)
        ).filter(
            Test.is_active == True,
            (Test.is_autocompile == True) | (Test.is_autocompile == None)
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
        return self.db.query(Test).filter(
            Test.creator_id == user_id,
            Test.is_ai_generated == True
        ).order_by(Test.id.desc()).all()

    def get_test_ids_by_creator(self, creator_id: int) -> List[int]:
        """Получить IDs всех тестов создателя"""
        return [t[0] for t in self.db.query(Test.id).filter(
            Test.creator_id == creator_id
        ).all()]

    def delete_tests_by_ids(self, test_ids: List[int]):
        """Удалить тесты по IDs"""
        from core.models import TestTaskAssociation
        result_ids = [r[0] for r in self.db.query(TestResult.id).filter(
            TestResult.test_id.in_(test_ids)
        ).all()]
        if result_ids:
            self.db.query(UserAnswer).filter(
                UserAnswer.result_id.in_(result_ids)
            ).delete(synchronize_session=False)
            self.db.query(TestResult).filter(
                TestResult.id.in_(result_ids)
            ).delete(synchronize_session=False)
        self.db.query(TestTaskAssociation).filter(
            TestTaskAssociation.test_id.in_(test_ids)
        ).delete(synchronize_session=False)
        self.db.query(TestAssignment).filter(
            TestAssignment.test_id.in_(test_ids)
        ).delete(synchronize_session=False)
        self.db.query(Test).filter(
            Test.id.in_(test_ids)
        ).delete(synchronize_session=False)
