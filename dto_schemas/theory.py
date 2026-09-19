from pydantic import BaseModel, ConfigDict, Field
from typing import Optional

class TheoryBase(BaseModel):
    topic: str
    section: str
    content: str
    theory_class: int = Field(..., ge=5, le=11)

    model_config = ConfigDict(from_attributes=True)

class TheoryCreate(TheoryBase):
    priority: int = 0

class TheoryUpdate(BaseModel):
    topic: Optional[str] = None
    section: Optional[str] = None
    content: Optional[str] = None
    theory_class: Optional[int] = Field(default=None, ge=5, le=11)
    priority: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)

class TheoryResponse(TheoryBase):
    id: int

    model_config = ConfigDict(from_attributes=True)
