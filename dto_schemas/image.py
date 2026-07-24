from pydantic import BaseModel, ConfigDict
from typing import Optional

class ImageUploadResponse(BaseModel):
    url: str
    filename: Optional[str] = None
    size: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)