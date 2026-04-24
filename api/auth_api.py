from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
import models, dto, auth
from database import get_db

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