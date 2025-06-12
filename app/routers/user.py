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
from app.config import settings
from app.routers.email_service import send_verification_email
from starlette.config import Config
from authlib.integrations.starlette_client import OAuth
from fastapi import Request
from jose import jwt, JWTError
from app.routers.security import get_password_hash, create_access_token
import secrets
from pydantic import EmailStr
from fastapi_mail import FastMail, MessageSchema

router = APIRouter()

SECRET_KEY = settings.SECRET_KEY
ALGORITHM = settings.ALGORITHM
ACCESS_TOKEN_EXPIRE_MINUTES = settings.ACCESS_TOKEN_EXPIRE_MINUTES

config = Config('.env')
oauth = OAuth(config)

# oauth.register(
#     name='google',
#     client_id=config('GOOGLE_CLIENT_ID'),
#     client_secret=config('GOOGLE_CLIENT_SECRET'),
#     authorize_url='https://accounts.google.com/o/oauth2/auth',
#     authorize_params=None,
#     access_token_url='https://accounts.google.com/o/oauth2/token',
#     refresh_token_url=None,
#     client_kwargs={'scope': 'openid email profile'}
# )

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
            email_verified=True if provider else False,
            auth_provider=provider,
            provider_user_id=provider_user_id
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
    existing_user_by_email = result.scalars().first()
    
    if existing_user_by_email:
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
        verification_token_expires=datetime.utcnow() + timedelta(minutes=10)
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
    return {"message": "Verification email sent. Please check your email."}

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

# @router.get("/login/google")
# async def login_google(request: Request)
#     redirect_uri = request.url_for('auth_google')
#     return await oauth.google.authorize_redirect(request, redirect_uri)

# @router.get("/auth/google")
# async def auth_googel(request: Request):
#     token = await oauth.google.authorize_access_token(request)
#     user_data = await oauth.google.parse_id_token(request, token)
#     email = user_data.get('email')
    
#     user = await get_or_create_user(email)
    
#     return {"user": user.email, "access_token": create_jwt_token(user.id)}