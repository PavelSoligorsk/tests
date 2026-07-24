from pydantic import BaseModel, ConfigDict, EmailStr
from typing import Optional

class AllowedEmailBase(BaseModel):
    email: EmailStr

    model_config = ConfigDict(from_attributes=True)


class AllowedEmailCreate(AllowedEmailBase):
    model_config = ConfigDict(from_attributes=True)

class AllowedEmailResponse(AllowedEmailBase):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    tg_username: Optional[str] = None
    
    model_config = ConfigDict(from_attributes=True)