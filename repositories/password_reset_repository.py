from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime
from core.models import PasswordResetToken


class PasswordResetRepository:
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def delete_existing_tokens(self, email: str):
        await self.db.execute(
            delete(PasswordResetToken).where(
                PasswordResetToken.email == email,
                PasswordResetToken.is_used == False
            )
        )
    
    async def create_token(self, email: str, token: str, expires_at):
        reset_token = PasswordResetToken(
            email=email,
            token=token,
            expires_at=expires_at
        )
        self.db.add(reset_token)
        return reset_token
    
    async def get_valid_token(self, token: str):
        r = await self.db.execute(
            select(PasswordResetToken).where(
                PasswordResetToken.token == token,
                PasswordResetToken.is_used == False,
                PasswordResetToken.expires_at > datetime.utcnow()
            )
        )
        return r.scalars().first()
    
    async def mark_token_used(self, reset_token):
        reset_token.is_used = True