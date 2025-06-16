from datetime import timedelta, datetime
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi import BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from sqlalchemy import func, or_
from app.database import get_db
from app.models.user import User
from app.schemas.user import UserCreate, UserRead, UserUpdate
from app.schemas.subscription_history import SubscriptionHistoryRead
from app.config import settings
from app.routers.email_service import send_verification_email
from jose import jwt, JWTError
from app.routers.security import get_password_hash, create_access_token, verify_password
import secrets
from pydantic import EmailStr
from app.routers.auth import get_current_user
from fastapi_mail import FastMail, MessageSchema
from starlette.config import Config
from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import Request
from pydantic import BaseModel

router = APIRouter()

SECRET_KEY = settings.SECRET_KEY
ALGORITHM = settings.ALGORITHM
ACCESS_TOKEN_EXPIRE_MINUTES = settings.ACCESS_TOKEN_EXPIRE_MINUTES

oauth = OAuth()

oauth.register(
    name='google',
    client_id=settings.GOOGLE_GLIENT_ID,
    client_secret=settings.GOOGLE_CLIENT_SECRET,
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={
        'scope': 'openid email profile',
        'prompt': 'select_account',
    }
)

async def get_or_create_user(db: AsyncSession, email: str, provider: str = None, provider_user_id: str = None):
    result = await db.execute(
        select(User).where(
            or_(
                User.email == email,
                User.provider_user_id == provider_user_id
            )
        )
    )
    
    user = result.scalars().first()
    
    if not user:
        user = User(
            email=email,
            auth_provider=provider,
            provider_user_id=provider_user_id,
            is_verified=True if provider else False,
            subscription_status="inactive"
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
    elif provider and not user.auth_provider:
        user.auth_provider = provider
        user.provider_user_id = provider_user_id
        user.is_verified = True
        await db.commit()
        await db.refresh(user)
    
    return user

@router.post("/register", response_model=UserRead)
async def register_user(
    user_data: UserCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(User).where(User.email == user_data.email))
    existing_user = result.scalars().first()
    
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User already registered",
        )
    
    hashed_password = get_password_hash(user_data.password)
    verification_token = create_access_token(
        data={"email": user_data.email},
        expires_delta=timedelta(minutes=10)
    )
    
    user = User(
        email=user_data.email,
        hashed_password=hashed_password,
        auth_provider="email",
        email_verified=False,
        verification_token=verification_token,
        verification_token_expires=datetime.utcnow() + timedelta(minutes=10),
        subscription_status="inactive"
    )
    db.add(user)
    await db.flush()
    
    await send_verification_email(
        background_tasks,
        email=user_data.email,
        token=verification_token
    )
    
    await db.commit()
    await db.refresh(user)
    return user

@router.post("/verifiy-email")
async def verify_email(
    token: str,
    email: str,
    db: AsyncSession = Depends(get_db)
):
    try:
        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=ALGORITHM
        )
        get_email = payload.get("email")
        
        if get_email is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid token"
            )
        
        if get_email != email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email doesn't match token"
            )
            
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalars().first()
        
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
            
        if user.is_verified:
            return {"message": "Email already verified"}
        
        if user.verification_token != token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid verification token"
            )
            
        user.is_verified = True
        user.verification_token = None
        user.verification_token_expires = None
        await db.commit()
        
        return {"message": "Email verified successfully"}
    
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid token"
        )

@router.get("/login/google")
async def login_google(request: Request):
    redirect_uri = request.url_for("auth_google")
    return await oauth.google.authorize_redirect(request, redirect_uri)

@router.get("/auth/google")
async def auth_googel(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    try:
        token = await oauth.google.authorize_access_token(request)
    except OAuthError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(error)
        )
        
    user_info = token.get("userinfo")
    if not user_info:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not get user info"
        )
    
    email = user_info.get('email')
    if not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email not provided by Google"
        )
        
    try:
        user = await get_or_create_user(
            db=db,
            email=email,
            provider="google",
            provider_user_id=user_info.get("sub"),
        )

        access_token = create_access_token(
            data={"email": str(user.email)}
        )
        return {"access_token": access_token, "token_type": "bearer"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
        
        
@router.get("/{user_id}", response_model=UserRead)
async def read_user(user_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if user.id != user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authenciation error")
    
    result = await db.execute(select(User).where(User.id == user_id))
    db_user = result.scalars().first()
    
    if db_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    
    return db_user

@router.put("/{user_id}", response_model=UserRead)
async def update_user(user_id: int, user: UserUpdate, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authenciation error")
    
    result = await db.execute(select(User).where(User.id == user_id))
    db_user = result.scalars().first()
    
    if db_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    
    for var, value in vars(user).items():
        setattr(db_user, var, value) if value is not None else None
        
    if user.password:
        db_user.hashed_password = get_password_hash(user.password)
        
    db_user.updated_at = datetime.utcnow()
    
    await db.commit()
    await db.refresh(db_user)
    
    return db_user

@router.delete("/{user_id}", response_model=UserRead)
async def delete_user(user_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if user.id != user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authenciation error")
    
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    
    await db.delete(user)
    await db.commit()
    
    return user

@router.post("/{user_id}/subscription-history", response_model=Subscription)