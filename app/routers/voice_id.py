from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field
from io import BytesIO
from fastapi import APIRouter, HTTPException, status, Depends, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from app.config import settings
from app.database import get_db
from sqlalchemy.future import select
from app.models.user import User
from app.routers.auth import get_current_user
from app.models.voice_id import Voice_ID
import os

from sqlalchemy.ext.asyncio import AsyncSession
import requests

router = APIRouter()

@router.get("/clonelist")
async def list_cloned_voices(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Voice_ID).where(Voice_ID.user_id == user.id, Voice_ID.detail_info == "Voice Clone"))
    voices = result.scalars().all()
    return voices

@router.get("/designlist")
async def list_designed_voices(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Voice_ID).where(Voice_ID.user_id == user.id, Voice_ID.detail_info == "Voice Design"))
    voices = result.scalars().all()
    return voices
    