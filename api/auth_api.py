from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
import dto
from core.database import get_db
from services.auth_service import AuthService, PermissionError

router = APIRouter(tags=["Authentication"])


def get_auth_service(db: Session = Depends(get_db)) -> AuthService:
    return AuthService(db)


@router.post("/register")
def register(
    user_data: dto.UserRegister,
    service: AuthService = Depends(get_auth_service)
):
    try:
        return service.register(user_data)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/login")
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


@router.post("/forgot-password")
async def forgot_password(
    request: dto.ForgotPasswordRequest,
    service: AuthService = Depends(get_auth_service)
):
    return service.forgot_password(request.email)


@router.post("/reset-password")
async def reset_password(
    request: dto.ResetPasswordRequest,
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


@router.get("/verify-reset-token/{token}")
async def verify_reset_token(
    token: str,
    service: AuthService = Depends(get_auth_service)
):
    try:
        return service.verify_reset_token(token)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))