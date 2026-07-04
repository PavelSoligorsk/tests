import os
import secrets
import httpx
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
import models, auth

from repositories.user_repository import UserRepository
from repositories.allowed_email_repository import AllowedEmailRepository
from repositories.password_reset_repository import PasswordResetRepository


class AuthService:
    def __init__(self, db: Session):
        self.user_repo = UserRepository(db)
        self.allowed_email_repo = AllowedEmailRepository(db)
        self.password_reset_repo = PasswordResetRepository(db)
        self.db = db
    
    def register(self, user_data):
        # Проверяем email
        if not self.allowed_email_repo.is_email_allowed(user_data.username):
            raise PermissionError("Регистрация для данного Email запрещена")
        
        # Проверяем существование
        if self.user_repo.get_user_by_email(user_data.username):
            raise ValueError("Пользователь с таким Email уже существует")
        
        # Создаем пользователя
        role = "admin" if user_data.username == "admin@gmail.com" else "student"
        
        user = self.user_repo.create_user(
            username=user_data.username,
            password=user_data.password,
            role=role,
            first_name=user_data.first_name,
            last_name=user_data.last_name,
            phone=user_data.phone,
            tg_username=user_data.tg_username
        )
        
        return {"message": "Регистрация прошла успешно!"}
    
    def login(self, username: str, password: str):
        user = self.user_repo.get_user_by_email(username)
        
        if not user or not auth.verify_password(password, user.hashed_password):
            raise ValueError("Неверный логин или пароль")
        
        access_token = auth.create_access_token(
            data={"sub": user.username, "role": user.role}
        )
        
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "role": user.role,
            "username": user.username
        }
    
    def forgot_password(self, email: str):
        user = self.user_repo.get_user_by_email(email)
        
        if not user:
            return {"message": "Если такой email зарегистрирован, инструкция отправлена"}
        
        # Удаляем старые токены
        self.password_reset_repo.delete_existing_tokens(email)
        
        # Создаем новый токен
        token = secrets.token_urlsafe(32)
        self.password_reset_repo.create_token(
            email=email,
            token=token,
            expires_at=datetime.utcnow() + timedelta(hours=1)
        )
        self.db.commit()
        
        # Отправляем email
        reset_link = f"https://test-front-lac.vercel.app/reset-password?token={token}"
        
        try:
            httpx.post(
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
        
        return {"message": "Если такой email зарегистрирован, инструкция отправлена"}
    
    def reset_password(self, token: str, new_password: str, confirm_password: str):
        if new_password != confirm_password:
            raise ValueError("Пароли не совпадают")
        
        if len(new_password) < 8:
            raise ValueError("Пароль должен быть минимум 8 символов")
        
        reset_token = self.password_reset_repo.get_valid_token(token)
        if not reset_token:
            raise ValueError("Токен недействителен или истек")
        
        user = self.user_repo.get_user_by_email(reset_token.email)
        if not user:
            raise ValueError("Пользователь не найден")
        
        self.user_repo.update_password(user, new_password)
        self.password_reset_repo.mark_token_used(reset_token)
        self.db.commit()
        
        return {"message": "Пароль успешно изменен"}
    
    def verify_reset_token(self, token: str):
        reset_token = self.password_reset_repo.get_valid_token(token)
        if not reset_token:
            raise ValueError("Токен недействителен")
        return {"valid": True}


class PermissionError(Exception):
    pass