from pydantic import BaseModel
from typing import Optional

class AllowedEmailBase(BaseModel):
    email: str

class AllowedEmailResponse(AllowedEmailBase):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    tg_username: Optional[str] = None
    
    class Config:
        from_attributes = True