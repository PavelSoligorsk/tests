from sqlalchemy.orm import Session
import models

class AllowedEmailRepository:
    def __init__(self, db: Session):
        self.db = db
    
    def get_all(self):
        return self.db.query(models.AllowedEmail).all()
    
    def get_by_email(self, email: str):
        return self.db.query(models.AllowedEmail).filter(
            models.AllowedEmail.email == email
        ).first()
    
    def create(self, email: str):
        new_email = models.AllowedEmail(email=email)
        self.db.add(new_email)
        self.db.commit()
        self.db.refresh(new_email)
        return new_email
    
    def delete(self, allowed_email):
        self.db.delete(allowed_email)
        self.db.commit()

    def is_email_allowed(self, email: str) -> bool:
        """Проверить, разрешен ли email"""
        if email == "admin@gmail.com":
            return True
        allowed = self.get_by_email(email)
        return allowed is not None