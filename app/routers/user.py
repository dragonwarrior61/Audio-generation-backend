from datetime import timedelta, datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from sqlalchemy import func, or_
from app.database import get_db
from app.models.user import User
from app.schemas.user import UserCreate, UserRead, UserUpdate
from app.config import settings
from starlette.config import Config
from authlib.integrations.starlette_client import OAuth
from fastapi import Request
from jose import jwt
from passlib.context import CryptContext
import secrets
from pydantic import EmailStr
from fastapi_mail import FastMail, MessageSchema

router = APIRouter()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

SECRET_KEY = settings.SECRET_KEY
ALGORITHM = settings.ALGORITHM
ACCESS_TOKEN_EXPIRE_MINUTES = settings.ACCESS_TOKEN_EXPIRE_MINUTES

config = Config('.env')
oauth = OAuth(config)

oauth.register(
    name='google',
    client_id=config('GOOGLE_CLIENT_ID'),
    client_secret=config('GOOGLE_CLIENT_SECRET'),
    authorize_url='https://accounts.google.com/o/oauth2/auth',
    authorize_params=None,
    access_token_url='https://accounts.google.com/o/oauth2/token',
    refresh_token_url=None,
    client_kwargs={'scope': 'openid email profile'}
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
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(User).where(User.email == user_data.email))
    existing_user = result.scalars().first()
    
    if existing_user:
        if existing_user.hashed_password:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered"
            )
        else:
            existing_user.hashed_password = get_password_hash(user_data.password)
            existing_user.auth_provider = "email"
            existing_user.verification_token = secrets.token_urlsafe(32)
            existing_user.verification_token_expires = datetime.utcnow() + timedelta(minutes=10)
            existing_user.updated_at = datetime.utcnow()
            
            await db.commit()
            await db.refresh(existing_user)
            
            await send_verification_email(existing_user.email, existing_user.verification_token)
            return existing_user
    
    user = User(
        email=user_data.email,
        hashed_password=get_password_hash(user_data.password),
        auth_provider="email",
        email_verified=False
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user

async def send_verification_email(email: EmailStr, token: str):
    verfication_url = f"{settings.BASE_URL}/auth/verify-email?token={token}"
    message = MessageSchema(
        subject = "Please verify your email address",
        recipients=[email],
        body=f"""
        <h2>Welcome to our service!</h2>
        <p>Please click the link below to verify your email address:</p>
        <p><a href="{verfication_url}">Verify Email</a></p>
        <p>This link will expire in 10 minutes.</p>
        <p>If you didn't request this, please ignore this email.</p>
        """,
        subtype="html"
    )
    
    fm = FastMail(settings.email_conf)
    await fm.send_message(message)

@router.get("/login/google")
async def login_google(request: Request):
    redirect_uri = request.url_for('auth_google')
    return await oauth.google.authorize_redirect(request, redirect_uri)

@router.get("/auth/google")
async def auth_googel(request: Request):
    token = await oauth.google.authorize_access_token(request)
    user_data = await oauth.google.parse_id_token(request, token)
    email = user_data.get('email')
    
    user = await get_or_create_user(email)
    
    return {"user": user.email, "access_token": create_jwt_token(user.id)}