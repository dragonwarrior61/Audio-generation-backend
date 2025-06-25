from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, Enum
from sqlalchemy.orm import relationship
from app.database import Base
from datetime import datetime
from enum import Enum as PyEnum

class SubscriptionStatus(PyEnum):
    INACTIVE = "inactive"
    ACTIVE = "active"
    CANCELLED = "cancelled"
    PAST_DUE = "past_due"
    PENDING = "pending"

class User(Base):
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    auth_provider = Column(String, nullable=False)
    provider_user_id = Column(Integer, nullable=True)
    is_verified = Column(Boolean, default=False)
    verification_token = Column(String, nullable=True)
    verification_token_expires = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_logged_in = Column(DateTime, nullable=True)
    
    subscription_status = Column(
        Enum(SubscriptionStatus),
        default=SubscriptionStatus.INACTIVE,
        nullable=False
    )
    subscription_id = Column(String, nullable=True)
    subscription_plan_id = Column(String, nullable=True)
    subsrciption_start_date = Column(String, nullable=True)
    subscription_end_date = Column(DateTime, nullable=True)
    subscription_cancel_at_period_end = Column(Boolean, default=False)
    subscription_auto_renew = Column(Boolean, default=True)
    payment_method = Column(String, nullable=True)
    
    character_balance = Column(Integer, default=0)
    voice_balance = Column(Integer, default=0)
    
    month_character_balance = Column(Integer, default=0)
    month_voice_balance = Column(Integer, default=0)
    subscription_history = relationship("SubscriptionHistory", back_populates="user")
    
