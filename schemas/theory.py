from pydantic import BaseModel
from typing import Optional

class TheoryBase(BaseModel):
    topic: str
    section: str
    content: str

class TheoryCreate(TheoryBase):
    pass

class TheoryUpdate(BaseModel):
    topic: Optional[str] = None
    section: Optional[str] = None
    content: Optional[str] = None

class TheoryResponse(TheoryBase):
    id: int
    
    class Config:
        from_attributes = True