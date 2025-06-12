from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from datetime import datetime, timedelta
from jose import JWTError, jwt
from pydantic import BaseModel
from typing import Optional
from app.routers.security import oauth2_scheme, create_access_token, create_refresh_token
from app.database import get_db
from app.models.user import User
from app.config import settings
from app.schemas.user import UserRead

router = APIRouter()

class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str
    
class TokenData(BaseModel):
    email: Optional[str] = None
    
async def update_last_logged_in(db:AsyncSession, user_id: int):
    result = await db.execute(select(User).where(User.id == user_id))
    db_user = result.scalars().first()
    
    if db_user:
        db_user.last_logged_in = datetime.utcnow()
        await db.commit()
        await db.refresh(db_user)
        
    return db_user

async def get_current_user(
    token: str = Depends(oauth2_scheme), 
    db: AsyncSession = Depends(get_db)
):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        headers={"WWW-Authenticate": "Bearer"}
    )
    
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        email: str = payload.get("email")
        if email is None:
            raise credentials_exception
        token_data = TokenData(email=email)
    except JWTError:
        raise credentials_exception
    
    result = await db.execute(select(User).where(User.email == token_data.email))
    user = result.scalars().first()
    
    if user is None:
        raise credentials_exception
    
    if not user.is_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Please verify your email first"
        )
        
    return user
