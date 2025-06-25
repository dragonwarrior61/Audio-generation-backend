from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class PaymentHistoryBase(BaseModel):
    event_type: str
    event_data: Optional[str] = None
    
class PaymentHistoryCreate(PaymentHistoryBase):
    user_id: int
    
class PaymentHistoryRead(PaymentHistoryBase):
    id: int
    user_id: int
    created_at: datetime
    
    class Config:
        orm_mode = True
        
class PaymentHistoryUpdate(BaseModel):
    event_type: Optional[str] = None
    event_data: Optional[str] = None
    