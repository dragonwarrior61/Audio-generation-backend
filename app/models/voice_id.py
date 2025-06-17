from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.orm import relationship
from app.database import Base
from datetime import datetime

class Voice(Base):
    __tablename__ = 'voice'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, index=True)
    voice_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)