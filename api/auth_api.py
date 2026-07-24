from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from dto_schemas import (
    UserRegister, ForgotPasswordRequest, ResetPasswordRequest,
    LoginResponse, TokenVerifyResponse, MessageResponse,
)
from core.database import get_db
from services.auth_service import AuthService, PermissionError

router = APIRouter(tags=["Authentication"])


def get_auth_service(db: Session = Depends(get_db)) -> AuthService:
    return AuthService(db)


@router.post("/register", response_model=MessageResponse)
def register(
    user_data: UserRegister,
    service: AuthService = Depends(get_auth_service)
):
    try:
        return service.register(user_data)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/login", response_model=LoginResponse)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    service: AuthService = Depends(get_auth_service)
):
    try:
        return service.login(form_data.username, form_data.password)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        )


@router.post("/forgot-password", response_model=MessageResponse)
async def forgot_password(
    request: ForgotPasswordRequest,
    service: AuthService = Depends(get_auth_service)
):
    return service.forgot_password(request.email)


@router.post("/reset-password", response_model=MessageResponse)
async def reset_password(
    request: ResetPasswordRequest,
    service: AuthService = Depends(get_auth_service)
):
    try:
        return service.reset_password(
            request.token,
            request.new_password,
            request.confirm_password
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/verify-reset-token/{token}", response_model=TokenVerifyResponse)
async def verify_reset_token(
    token: str,
    service: AuthService = Depends(get_auth_service)
):
    try:
        return service.verify_reset_token(token)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))