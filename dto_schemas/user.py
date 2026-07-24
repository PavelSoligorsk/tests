from pydantic import BaseModel, EmailStr
from typing import Optional

class UserRegister(BaseModel):
    username: str
    password: str
    first_name: str
    last_name: str
    phone: Optional[str] = None
    tg_username: Optional[str] = None

    class Config:
        from_attributes = True

class TeacherInfo(BaseModel):
    first_name: str
    last_name: str

    class Config:
        from_attributes = True

class UserResponse(BaseModel):
    id: int
    username: str
    role: str
    first_name: str
    last_name: Optional[str]
    phone: Optional[str]
    tg_username: Optional[str]
    teacher: Optional[TeacherInfo] = None

    class Config:
        from_attributes = True

class UserUpdate(BaseModel):
    first_name: Optional[str]
    last_name: Optional[str]
    phone: Optional[str]
    tg_username: Optional[str]

    class Config:
        from_attributes = True

class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str
    confirm_password: str

class AssignStudentRequest(BaseModel):
    teacher_id: int
    student_id: int