from pydantic import BaseModel
from schemas.user import UserResponse

class UserStats(BaseModel):
    total_attempts: int
    avg_score: float

class UserResponseWithStats(BaseModel):
    user: UserResponse
    stats: UserStats