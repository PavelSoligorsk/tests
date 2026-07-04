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