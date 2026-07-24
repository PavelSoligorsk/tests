from pydantic import BaseModel, ConfigDict
from typing import Optional

class AllowedEmailBase(BaseModel):
    email: str

    model_config = ConfigDict(from_attributes=True)

class AllowedEmailResponse(AllowedEmailBase):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    tg_username: Optional[str] = None
    
    model_config = ConfigDict(from_attributes=True)