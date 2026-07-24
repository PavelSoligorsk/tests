from pydantic import BaseModel, ConfigDict, model_validator
from typing import Optional

class ImageUploadRequest(BaseModel):
    image: Optional[str] = None
    image_data: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="after")
    def validate_payload(self):
        if not self.image and not self.image_data:
            raise ValueError("Нужно передать image или image_data")
        return self

class ImageUploadResponse(BaseModel):
    url: str
    filename: Optional[str] = None
    size: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)