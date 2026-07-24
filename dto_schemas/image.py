from pydantic import BaseModel
from typing import Optional

class ImageUploadResponse(BaseModel):
    url: str
    filename: Optional[str] = None
    size: Optional[int] = None

    class Config:
        from_attributes = True