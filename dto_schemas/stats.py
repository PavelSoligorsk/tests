from pydantic import BaseModel, ConfigDict
from dto_schemas.user import UserResponse

class UserStats(BaseModel):
    total_attempts: int
    avg_score: float

    model_config = ConfigDict(from_attributes=True)

class UserResponseWithStats(BaseModel):
    user: UserResponse
    stats: UserStats

    model_config = ConfigDict(from_attributes=True)