from fastapi import BackgroundTasks
from fastapi_mail import FastMail, MessageSchema, ConnectionConfig
from app.config import settings
from pathlib import Path
from typing import Dict

conf = ConnectionConfig(
    MAIL_USERNAME=settings.MAIL_USERNAME,
    MAIL_PASSWORD=settings.MAIL_PASSWORD,
    MAIL_FROM=settings.MAIL_FROM,
    MAIL_PORT=settings.MAIL_PORT,
    MAIL_SERVER=settings.MAIL_SERVER,
    MAIL_TLS=True,
    MAIL_SSL=False,
    USE_CREDENTIALS=True
)

async def send_verification_email(background_tasks: BackgroundTasks, email: str, token: str):
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
    
    fm = FastMail(conf)
    background_tasks.add_task(
        fm.send_message, message, template_name="verification_email.html"
    )