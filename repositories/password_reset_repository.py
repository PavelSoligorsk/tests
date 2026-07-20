from sqlalchemy.orm import Session
from datetime import datetime
from core.models import PasswordResetToken


class PasswordResetRepository:
    def __init__(self, db: Session):
        self.db = db
    
    def delete_existing_tokens(self, email: str):
        self.db.query(PasswordResetToken).filter(
            PasswordResetToken.email == email,
            PasswordResetToken.is_used == False
        ).delete()
    
    def create_token(self, email: str, token: str, expires_at):
        reset_token = PasswordResetToken(
            email=email,
            token=token,
            expires_at=expires_at
        )
        self.db.add(reset_token)
        return reset_token
    
    def get_valid_token(self, token: str):
        return self.db.query(PasswordResetToken).filter(
            PasswordResetToken.token == token,
            PasswordResetToken.is_used == False,
            PasswordResetToken.expires_at > datetime.utcnow()
        ).first()
    
    def mark_token_used(self, reset_token):
        reset_token.is_used = True