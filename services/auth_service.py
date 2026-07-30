import os
import secrets
import httpx
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from core import models
import core.auth as auth

from core.auth import *

from repositories.user_repository import UserRepository
from repositories.allowed_email_repository import AllowedEmailRepository
from repositories.password_reset_repository import PasswordResetRepository

from dto_schemas.user import LoginResponse, TokenVerifyResponse, MessageResponse


class AuthService:
    def __init__(self, db: AsyncSession):
        self.user_repo = UserRepository(db)
        self.allowed_email_repo = AllowedEmailRepository(db)
        self.password_reset_repo = PasswordResetRepository(db)
        self.db = db
    
    async def register(self, user_data):
        # Проверяем email
        if not await self.allowed_email_repo.is_email_allowed(user_data.username):
            raise PermissionError("Регистрация для данного Email запрещена")
        
        # Проверяем существование
        if await self.user_repo.get_user_by_email(user_data.username):
            raise ValueError("Пользователь с таким Email уже существует")
        
        # Проверяем уникальность tg_username
        if user_data.tg_username and await self.user_repo.is_tg_username_taken(user_data.tg_username):
            raise ValueError("Пользователь с таким Telegram username уже зарегистрирован")
        
        # Создаем пользователя
        role = "admin" if user_data.username == "admin@gmail.com" else "student"
        
        user = await self.user_repo.create_user(
            username=user_data.username,
            password=user_data.password,
            role=role,
            first_name=user_data.first_name,
            last_name=user_data.last_name,
            phone=user_data.phone,
            tg_username=user_data.tg_username
        )
        
        return MessageResponse(message="Регистрация прошла успешно!")
    
    async def login(self, username: str, password: str) -> LoginResponse:
        user = await self.user_repo.get_user_by_email(username)
        
        if not user or not auth.verify_password(password, user.hashed_password):
            raise ValueError("Неверный логин или пароль ")
        
        access_token = auth.create_access_token(
            data={"sub": user.username, "role": user.role}
        )
        
        return LoginResponse(
            access_token=access_token,
            token_type="bearer",
            role=user.role,
            username=user.username
        )
    
    async def forgot_password(self, email: str):
        user = await self.user_repo.get_user_by_email(email)
        
        if not user:
            return MessageResponse(message="Если такой email зарегистрирован, инструкция отправлена")
        
        # Удаляем старые токены
        await self.password_reset_repo.delete_existing_tokens(email)
        
        # Создаем новый токен
        token = secrets.token_urlsafe(32)
        await self.password_reset_repo.create_token(
            email=email,
            token=token,
            expires_at=datetime.utcnow() + timedelta(hours=1)
        )
        await self.db.commit()
        
        # Отправляем email
        reset_link = f"https://test-front-lac.vercel.app/reset-password?token={token}"
        
        try:
            async with httpx.AsyncClient() as client:
                await client.post(
                    "https://api.resend.com/emails",
                    headers={
                        "Authorization": f"Bearer {os.getenv('RESEND_API_KEY')}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "from": "onboarding@resend.dev",
                        "to": email,
                        "subject": "Сброс пароля",
                        "html": f"""
                        <h2>Сброс пароля</h2>
                        <p>Для сброса пароля перейдите по ссылке:</p>
                        <a href="{reset_link}">{reset_link}</a>
                        <p>Ссылка действительна 1 час.</p>
                        """
                    },
                    timeout=10.0
                )
        except Exception as e:
            print(f"Email error: {e}")
        
        return MessageResponse(message="Если такой email зарегистрирован, инструкция отправлена")
    
    async def reset_password(self, token: str, new_password: str, confirm_password: str):
        if new_password != confirm_password:
            raise ValueError("Пароли не совпадают")
        
        if len(new_password) < 8:
            raise ValueError("Пароль должен быть минимум 8 символов")
        
        reset_token = await self.password_reset_repo.get_valid_token(token)
        if not reset_token:
            raise ValueError("Токен недействителен или истек")
        
        user = await self.user_repo.get_user_by_email(reset_token.email)
        if not user:
            raise ValueError("Пользователь не найден")
        
        await self.user_repo.update_password(user, new_password)
        await self.password_reset_repo.mark_token_used(reset_token)
        await self.db.commit()
        
        return MessageResponse(message="Пароль успешно изменен")
    
    async def verify_reset_token(self, token: str) -> TokenVerifyResponse:
        reset_token = await self.password_reset_repo.get_valid_token(token)
        if not reset_token:
            raise ValueError("Токен недействителен")
        return TokenVerifyResponse(valid=True)


class PermissionError(Exception):
    pass