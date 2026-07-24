from pydantic import BaseModel, ConfigDict
from typing import Optional

class TheoryBase(BaseModel):
    topic: str
    section: str
    content: str

    model_config = ConfigDict(from_attributes=True)

class TheoryCreate(TheoryBase):
    pass

class TheoryUpdate(BaseModel):
    topic: Optional[str] = None
    section: Optional[str] = None
    content: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

class TheoryResponse(TheoryBase):
    id: int
    
    model_config = ConfigDict(from_attributes=True)