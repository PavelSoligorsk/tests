from pydantic import BaseModel
from dto_schemas.user import UserResponse

class UserStats(BaseModel):
    total_attempts: int
    avg_score: float

    class Config:
        from_attributes = True

class UserResponseWithStats(BaseModel):
    user: UserResponse
    stats: UserStats

    class Config:
        from_attributes = True