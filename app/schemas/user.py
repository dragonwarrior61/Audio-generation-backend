from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime
from enum import Enum

class SubscriptionStatus(str, Enum):
    INACTIVE = "inactive"
    ACTIVE = "active"
    CANCELLED = "cancelled"
    PAST_DUE = "past_due"
    PENDING = "pending"
class UserBase(BaseModel):
    email: EmailStr
    auth_provider: str
    
class UserCreate(UserBase):
    password: Optional[str] = None
    provider_user_id: Optional[int] = None
    
class UserRead(UserBase):
    id: int
    is_verified: bool
    created_at: datetime
    updated_at: datetime
    last_logged_in: Optional[datetime] = None
    subscription_status: SubscriptionStatus
    subscription_id: Optional[str]
    subscription_plan_id: Optional[str]
    subscription_start_date: Optional[datetime]
    subscription_end_date: Optional[datetime]
    subscription_cancel_at_period_end: bool
    subscription_auto_renew: bool
    payment_method: Optional[str]
    character_balance: int
    voice_balance: int
    month_character_balance: int
    month_voice_balance: int
    class Config:
        orm_mode = True
class UserUpdate(UserBase):
    password: Optional[str] = None
    is_verified: Optional[bool] = None
    last_logged_in: Optional[datetime] = None
    subscription_status: Optional[SubscriptionStatus] = None
    subscription_id: Optional[str] = None
    subscription_plan_id: Optional[str] = None
    subscription_start_date: Optional[datetime] = None
    subscription_end_date: Optional[datetime] = None
    subscription_cancel_at_period_end: Optional[bool] = None
    subscription_auto_renew: Optional[bool] = None
    payment_method: Optional[str] = None
    
class UserInDB(UserRead):
    hashed_password: str
    verification_token: Optional[str]
    verification_token_expires: Optional[datetime]