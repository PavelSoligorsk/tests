from sqlalchemy.orm import Session
from datetime import datetime
import models

class PasswordResetRepository:
    def __init__(self, db: Session):
        self.db = db
    
    def delete_existing_tokens(self, email: str):
        self.db.query(models.PasswordResetToken).filter(
            models.PasswordResetToken.email == email,
            models.PasswordResetToken.is_used == False
        ).delete()
    
    def create_token(self, email: str, token: str, expires_at):
        reset_token = models.PasswordResetToken(
            email=email,
            token=token,
            expires_at=expires_at
        )
        self.db.add(reset_token)
        return reset_token
    
    def get_valid_token(self, token: str):
        return self.db.query(models.PasswordResetToken).filter(
            models.PasswordResetToken.token == token,
            models.PasswordResetToken.is_used == False,
            models.PasswordResetToken.expires_at > datetime.utcnow()
        ).first()
    
    def mark_token_used(self, reset_token):
        reset_token.is_used = True