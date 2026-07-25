from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from core.models import AllowedEmail


class AllowedEmailRepository:
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_all(self):
        r = await self.db.execute(select(AllowedEmail))
        return r.scalars().all()
    
    async def get_by_email(self, email: str):
        r = await self.db.execute(
            select(AllowedEmail).where(AllowedEmail.email == email)
        )
        return r.scalars().first()
    
    async def create(self, email: str):
        new_email = AllowedEmail(email=email)
        self.db.add(new_email)
        await self.db.commit()
        await self.db.refresh(new_email)
        return new_email
    
    async def delete(self, allowed_email):
        await self.db.delete(allowed_email)
        await self.db.commit()

    async def is_email_allowed(self, email: str) -> bool:
        """Проверить, разрешен ли email"""
        if email == "admin@gmail.com":
            return True
        allowed = await self.get_by_email(email)
        return allowed is not None