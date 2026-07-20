from schemas.task import TaskBase, TaskResponse, TaskCreate, TaskCreateRequest, TaskUpdateRequest
from schemas.answer import AnswerSubmitRequest, AnswerResponse
from schemas.test import TestCreate, TestCreateRequest, TestResponse, TestResultResponse
from schemas.user import UserRegister, UserResponse, UserUpdate, ForgotPasswordRequest, ResetPasswordRequest, AssignStudentRequest
from schemas.stats import UserStats, UserResponseWithStats
from schemas.email import AllowedEmailBase, AllowedEmailResponse
from schemas.image import ImageUploadResponse
from schemas.assignment import TestAssignmentCreate, TestAssignmentResponse, StudentAssignmentResponse, TestGroupAssignment
from schemas.theory import TheoryBase, TheoryCreate, TheoryUpdate, TheoryResponse
from schemas.ai import AITestRequest

__all__ = [
    "TaskBase", "TaskResponse", "TaskCreate", "TaskCreateRequest", "TaskUpdateRequest",
    "AnswerSubmitRequest", "AnswerResponse",
    "TestCreate", "TestCreateRequest", "TestResponse", "TestResultResponse",
    "UserRegister", "UserResponse", "UserUpdate",
    "ForgotPasswordRequest", "ResetPasswordRequest", "AssignStudentRequest",
    "UserStats", "UserResponseWithStats",
    "AllowedEmailBase", "AllowedEmailResponse",
    "ImageUploadResponse",
    "TestAssignmentCreate", "TestAssignmentResponse", "StudentAssignmentResponse", "TestGroupAssignment",
    "TheoryBase", "TheoryCreate", "TheoryUpdate", "TheoryResponse",
    "AITestRequest",
]