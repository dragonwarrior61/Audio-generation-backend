from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime

class UserBase(BaseModel):
    email: EmailStr
    auth_provider: str
    provider_user_id: Optional[int] = None
    
class UserCreate(UserBase):
    password: str
    
class UserRead(UserBase):
    id: int
    is_verified: bool
    verification_token: Optional[str] = None
    verification_token_expires: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    last_logged_in: Optional[datetime] = None
    
    class Config:
        orm_mode = True
        from_attributes = True
        
class UserUpdate(UserBase):
    password: Optional[str] = None
    is_verified: Optional[bool] = None
    verificiation_token: Optional[str] = None
    verificiation_token_expires: Optional[datetime] = None
    last_logged_in: Optional[datetime] = None
    
    class Config:
        orm_mode = True
        from_atrributes = True