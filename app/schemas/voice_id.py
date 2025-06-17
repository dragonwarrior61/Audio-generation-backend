from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class VoiceBase(BaseModel):
    user_id: int
    voice_id: Optional[str] = None
    
class VoiceCreate(VoiceBase):
    pass

class VoiceRead(VoiceBase):
    id: int
    created_at: datetime
    