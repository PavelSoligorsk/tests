from sqlalchemy.orm import Session
import models

class TheoryRepository:
    def __init__(self, db: Session):
        self.db = db
    
    def get_all_topics(self):
        return self.db.query(models.Theory.topic).distinct().all()
    
    def get_all_theory(self):
        """Получить весь теоретический материал"""
        return self.db.query(models.Theory).order_by(
            models.Theory.topic, 
            models.Theory.section
        ).all()
    
    def get_theory_by_topic(self, topic: str):
        return self.db.query(models.Theory)\
            .filter(models.Theory.topic == topic)\
            .order_by(models.Theory.section)\
            .all()
    
    def get_theory_by_topic_and_section(self, topic: str, section: str):
        return self.db.query(models.Theory)\
            .filter(
                models.Theory.topic == topic,
                models.Theory.section == section
            ).first()
    
    def get_theory_by_id(self, theory_id: int):
        return self.db.query(models.Theory)\
            .filter(models.Theory.id == theory_id)\
            .first()
    
    def get_theory_sections_count(self, topic: str):
        return self.db.query(models.Theory)\
            .filter(models.Theory.topic == topic)\
            .count()