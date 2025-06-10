from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime

class UserBase(BaseModel):
    address: Optional[str] = None
    username: str
    email: EmailStr
    full_name: Optional[str] = None
    
class UserCreate(UserBase):
    password: str
    
class UserRead(UserBase):
    id: int
    created_at: datetime
    updated_at: datetime
    last_logged_in: Optional[datetime] = None
    
    class Config:
        orm_mode = True
        from_attributes = True
        
class UserUpdate(UserBase):
    password: str