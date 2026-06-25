from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
import models, dto, auth
from database import get_db
from datetime import datetime, timedelta
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import secrets
from fastapi import BackgroundTasks
import os

router = APIRouter(tags=["Authentication"])

@router.post("/register")
def register(user_data: dto.UserRegister, db: Session = Depends(get_db)):
    # 1. Проверяем, разрешен ли этот email админом
    if user_data.username != "admin@gmail.com":
        allowed = db.query(models.AllowedEmail).filter(models.AllowedEmail.email == user_data.username).first()
        if not allowed or user_data == "admin@gmail.com":
            raise HTTPException(
              status_code=403, 
              detail="Регистрация для данного Email запрещена. Обратитесь к администратору."
          )

    # 2. Проверяем, не зарегистрирован ли уже такой Email
    email_exists = db.query(models.User).filter(models.User.username == user_data.username).first()
    if email_exists:
        raise HTTPException(status_code=400, detail="Пользователь с таким Email уже существует")

    # 3. Проверяем username
    existing_user = db.query(models.User).filter(models.User.username == user_data.username).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Логин занят")
    
    # 4. Создаем пользователя
    new_user = models.User(
        username=user_data.username, 
        hashed_password=auth.get_password_hash(user_data.password), 
        role="admin" if user_data.username == "admin@gmail.com" else "student",
        first_name=user_data.first_name,
        last_name=user_data.last_name,
        phone=user_data.phone,
        tg_username=user_data.tg_username
    )
    db.add(new_user)
    db.commit()
    return {"message": "Регистрация прошла успешно!"}

@router.post("/login")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.username == form_data.username).first()
    
    if not user or not auth.verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="Неверный логин или пароль",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Генерируем токен, упаковывая туда sub (username) и роль
    access_token = auth.create_access_token(data={"sub": user.username, "role": user.role})
    
    return {
        "access_token": access_token, 
        "token_type": "bearer", 
        "role": user.role, 
        "username": user.username
    }

import os
import secrets
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta

import os
import secrets
import httpx
from datetime import datetime, timedelta

@router.post("/forgot-password")
async def forgot_password(
    request: dto.ForgotPasswordRequest,
    db: Session = Depends(get_db)
):
    user = db.query(models.User).filter(models.User.username == request.email).first()
    
    if not user:
        return {"message": "Если такой email зарегистрирован, инструкция отправлена"}
    
    db.query(models.PasswordResetToken).filter(
        models.PasswordResetToken.email == request.email,
        models.PasswordResetToken.is_used == False
    ).delete()
    
    token = secrets.token_urlsafe(32)
    reset_token = models.PasswordResetToken(
        email=request.email,
        token=token,
        expires_at=datetime.utcnow() + timedelta(hours=1)
    )
    
    db.add(reset_token)
    db.commit()
    
    reset_link = f"http://localhost:3000/reset-password?token={token}"
    
    try:
        response = httpx.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {os.getenv('RESEND_API_KEY')}",
                "Content-Type": "application/json"
            },
            json={
                "from": "onboarding@resend.dev",
                "to": request.email,
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
        
        print(f"Resend status: {response.status_code}")
        
    except Exception as e:
        print(f"Email error: {e}")
    
    return {"message": "Если такой email зарегистрирован, инструкция отправлена"}

@router.post("/reset-password")
async def reset_password(
    request: dto.ResetPasswordRequest,
    db: Session = Depends(get_db)
):
    # Проверяем совпадение паролей
    if request.new_password != request.confirm_password:
        raise HTTPException(status_code=400, detail="Пароли не совпадают")
    
    if len(request.new_password) < 8:
        raise HTTPException(status_code=400, detail="Пароль должен быть минимум 8 символов")
    
    # Ищем валидный токен
    reset_token = db.query(models.PasswordResetToken).filter(
        models.PasswordResetToken.token == request.token,
        models.PasswordResetToken.is_used == False,
        models.PasswordResetToken.expires_at > datetime.utcnow()
    ).first()
    
    if not reset_token:
        raise HTTPException(status_code=400, detail="Токен недействителен или истек")
    
    # Находим пользователя
    user = db.query(models.User).filter(models.User.username == reset_token.email).first()
    
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    # Меняем пароль
    user.hashed_password = auth.get_password_hash(request.new_password)
    reset_token.is_used = True
    db.commit()
    
    return {"message": "Пароль успешно изменен"}


@router.get("/verify-reset-token/{token}")
async def verify_reset_token(token: str, db: Session = Depends(get_db)):
    """Проверка валидности токена (для фронтенда)"""
    reset_token = db.query(models.PasswordResetToken).filter(
        models.PasswordResetToken.token == token,
        models.PasswordResetToken.is_used == False,
        models.PasswordResetToken.expires_at > datetime.utcnow()
    ).first()
    
    if not reset_token:
        raise HTTPException(status_code=400, detail="Токен недействителен")
    
    return {"valid": True}