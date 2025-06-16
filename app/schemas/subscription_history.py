from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class SubscriptionHistoryBase(BaseModel):
    event_type: str
    event_data: Optional[str] = None
    
class SubscriptionHistoryCreate(SubscriptionHistoryBase):
    user_id: int
    
class SubscriptionHistoryRead(SubscriptionHistoryBase):
    id: int
    user_id: int
    created_at: datetime
    
    class Config:
        orm_mode = True
        
class SubscriptionHistoryUpdate(BaseModel):
    event_type: Optional[str] = None
    event_data: Optional[str] = None
    