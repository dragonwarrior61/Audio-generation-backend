from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from datetime import datetime, timedelta
from jose import JWTError, jwt
from pydantic import BaseModel
from typing import Optional
from app.routers.security import oauth2_scheme, create_access_token, create_refresh_token, verify_password
from app.database import get_db
from app.models.user import User
from app.config import settings
from app.schemas.user import UserRead
from fastapi.security import OAuth2PasswordRequestForm


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

class UserInDB(BaseModel):
    id: int
    email: str
    hashed_password: str

async def authenticate_user(db: AsyncSession, email: str, password: str):
    result = await db.execute(select(User).filter(User.email == email))
    user = result.scalars().first()
    if not user or not verify_password(password, user.hashed_password):
        return False

    return UserInDB(
        id=user.id,
        email=user.email,
        hashed_password=user.hashed_password
    )

@router.post("/token", response_model=Token)
async def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db)
):
    user = await authenticate_user(db, form_data.username, form_data.password)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Anthenticate": "bearer"},
        )
    
    await update_last_logged_in(db, user.id)
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    refresh_token_expires = timedelta(minutes=settings.REFRESH_TOKEN_EXPIRE_MINUTES)
    
    access_token = create_access_token(data={"email": user.email}, expires_delta=access_token_expires)
    refresh_token = create_refresh_token(data={"email": user.email}, expires_delta=refresh_token_expires)
    
    return {"access_token": access_token, "refresh_token": refresh_token}

@router.post("/refresh", response_model=Token)
async def refresh_access_token(refresh_token: str):
    try:
        payload = jwt.decode(refresh_token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        email: str = payload.get("email")
        
        if email is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
        token_data = TokenData(email=email)
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(data={"email": token_data.email}, expires_delta=access_token_expires)
    return {"access_token": access_token, "refresh_token": refresh_token}

@router.post("/verify_token", response_model=UserRead)
async def get_user(current_user: User = Depends(get_current_user)):
    return current_user


