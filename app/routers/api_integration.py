import json
import time
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

GROUP_ID = settings.GROUP_ID
API_KEY = settings.API_KEY
TTS_URL = f"https://api.minimax.io/v1/t2a_v2?GroupId={GROUP_ID}"

SUPPORTED_FORMATS = {
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
    "flac": "audio/flac",
    "pcm": "audio/x-wav"
}
class Voice(BaseModel):
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    vol: float = Field(default=1.0, gt=0, le=10)
    pitch: int = Field(default=0, ge=-12, le=12)
    voice_id: Optional[str] = Field(
        None,
        description="Predefined voice ID (e.g., 'Wise_Woman')"
    )
    emotion: Optional[str] = Field(
        None,
        enum=["happy", "sad", "angry", "fearful", "disgusted", "surprised", "neutral"]
    )
    english_normalization : bool = False
    
class Audio(BaseModel):
    sample_rate: int = Field(
        default=32000,
        enum=[8000, 16000, 22050, 24000, 32000, 44100]
    )
    bitrate: int = Field(default=128000, enum=[32000, 64000, 128000, 256000])
    format: str = Field(default="mp3", enum=["mp3", "pcm", "flac"])
    channel: int = Field(default=1, enum=[1, 2])
    
class PronunciationDict(BaseModel):
    replacements: List[str] = Field(
        default=[],
        example=["燕少飞/(yan4)(shao3)(fei1)", "达菲/(da2)(fei1)"],
        description="Text/symbol replacements with pronunciation"
    )
    
class TimberWeight(BaseModel):
    voice_id: str = Field(..., description="System voice ID for mixing")
    weight: int = Field(..., ge=1, le=100, description="Weight (1-100)")
    
class TTSRequest(BaseModel):
    text: str = Field(..., max_length=5000)
    model: str = Field(
        default="speech-02-turbo",
        enum=["speech-02-hd", "speech-01-turbo", "speech-01-hd", "speech-01-turbo"]
    )
    voice_settings: Voice
    audio_settings: Audio = Field(default_factory=Audio)
    pronuncation_dict: Optional[PronunciationDict] = None
    timber_weights: Optional[List[TimberWeight]] = None
    stream: bool = Field(default=False)
    language_boost: Optional[str] = Field(
        None,
        enum = [
            'Chinese', 'Chinese,Yue', 'English', 'Arabic', 
            'Russian', 'Spanish', 'French', 'Portuguese',
            'German', 'Turkish', 'Dutch', 'Ukrainian',
            'Vietnamese', 'Indonesian', 'Japanese', 'Italian',
            'Korean', 'Thai', 'Polish', 'Romanian',
            'Greek', 'Czech', 'Finnish', 'Hindi', 'auto'
        ]
    )
    subtitle_enable: bool = Field(default=False)
    output_format: str = Field(default="hex", enum=["url", "hex"])

@router.post("/generate")
async def generate_tts(request: TTSRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if user.subscription_status != "ACTIVE":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="Active subscription required for TTS generation"
        )
    
    system_voice = [ "Wise_Woman", "Friendly_Person", "Inspirational_girl", "Deep_Voice_Man", "Calm_Woman", 
                    "Casual_Guy", "Lively_Girl", "Patient_Man", "Young_Knight", "Determined_Man", "Lovely_Girl",
                    "Decent_Boy", "Imposing_Manner", "Elegant_Man", "Abbess", "Sweet_Girl_2", "Exuberant_Girl"]
    
    if request.audio_settings.format not in SUPPORTED_FORMATS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Upsupported audio format. Supported formats: {list(SUPPORTED_FORMATS.keys())}"
        )
    
    request_voice_id = request.voice_settings.voice_id
    
    result = await db.execute(select(Voice_ID).where(Voice_ID.voice_id == request_voice_id, Voice_ID.user_id == user.id))
    db_voice = result.scalars().first()
    
    if db_voice is None and request_voice_id not in system_voice:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Can't use this voice id {request_voice_id}"
        )
    try:
        headers = {
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json"
        }
        
        payload = {**request.dict(exclude_none=True)}
        
        response = requests.post(TTS_URL, headers=headers, json=payload)
        response.raise_for_status()
        
        audio_buffer = BytesIO(response.content)
        media_type = {
            "mp3": "audio/mpeg",
            "wav": "audio/wav",
            "flac": "audio/flac",
            "pcm": "audio/x-wav"
        }.get(request.audio_settings.format, "audio/mpeg")
        
        return StreamingResponse(
            audio_buffer,
            media_type=media_type,
            headers={
                "Content-Disposition": f"attachment; filename=tts_audio.{request.audio_settings.format}"
            }
        )
        
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Minimax API error: {str(e)}")
    
VOICE_DESING_URL = "https://api.minimax.io/v1/voice_design"

class VoiceDesignRequest(BaseModel):
    prompt: str = Field(..., min_length=10, max_length=1000, description="Detailed description of desired voice characteristics")
    preview_text: str = Field(..., max_length=500, description="Text for preview audio(max 500 chars)")
    
class VoiceDesignResponse(BaseModel):
    voice_id: str
    preview_audio: str
    activation_status: bool
    expires_at: Optional[datetime]
    
@router.post("/design")
async def design_voice(
    request: VoiceDesignRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if user.subscription_status != "ACTIVE":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Active subscription reuqired for voice design"
        )
        
    try:
        design_headers = {
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json"
        }
        
        design_payload = {
            "prompt": request.prompt,
            "preview_text": request.preview_text,
        }
        
        design_response = requests.post(
            VOICE_DESING_URL,
            headers=design_headers,
            json=design_payload,
            timeout=30
        )
        
        design_response.raise_for_status()
        design_data = design_response.json()
        
        activation_payload = {
            "text": request.prompt,
            "voice_setting": {
                "voice_id": design_data["voice_id"]
            },
            "audio_setting": {
                "format": "mp3"
            }
        }
        
        activation_response = requests.post(
            TTS_URL,
            headers=design_headers,
            json=activation_payload,
            timeout=30
        )
        
        activation_response.raise_for_status()
        
        voice = Voice_ID(
            user_id = user.id,
            voice_id = design_data["voice_id"],
            detail_info = "Voice Design"
        )
        
        db.add(voice)
        await db.commit()
        
        return {
            "voice_id": design_data["voice_id"],
            "preview_audio": design_data.get("trial_audio", ""),
            "activation_status": True,
            "expires_at": None
        }
    
    except requests.Timeout:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Voice design service timeout"
        )
        
    except requests.HTTPError as e:
        error_detail = f"Minimax API error: {str(e)}"
        if e.response.status_code == 402:
            error_detail = "Insufficient credits for voice design"
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=error_detail
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Voice design failed: {str(e)}"
        )


FILE_UPLOAD_URL = f"https://api.minimax.io/v1/files/upload?GroupId={GROUP_ID}"
VOICE_CLONE_URL = f"https://api.minimax.io/v1/voice_clone?GroupId={GROUP_ID}"

class FileUploadResponse(BaseModel):
    file_id: str
    filename: str
    bytes: int
    created_at: int
    
class VoiceCloneRequest(BaseModel):
    file_id: str
    voice_id: str = Field(..., min_length=8, regex="^[a-zA-Z][a-zA-Z0-9]{7,}$")
    need_noise_reduction: bool = False
    text: Optional[str] = Field(None, max_length=2000)
    model: Optional[str] = Field(None, enum = ["speech-02-hd", "speech-02-turbo", "speech-01-hd", "speech-01-turbo"])
    accuracy: Optional[float] = Field(None, ge=0, le=1)
    need_volumn_normalization: bool = False
    
class VoiceCloneResponse(BaseModel):
    voice_id: str
    input_sensitive: bool
    preview_audio: Optional[str] = None
    
@router.post("/upload", response_model=FileUploadResponse)
async def upload_voice_sample(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    purpose: str = Form("voice_clone")
):
    allowed_type = ["audio/mpeg", "audio/m4a", "audio/wav"]
    if file.content_type not in allowed_type:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported file type. Allowed: MP3, M4A, WAV"
        )
        
    try:
        headers = {
            "Authorization": f"Bearer {API_KEY}"
        }
        
        files = {
            "file": (file.filename, file.file, file.content_type)
        }
        
        data = {
            "purpose": purpose
        }
        
        response = requests.post(
            FILE_UPLOAD_URL,
            headers=headers,
            files=files,
            data=data
        )
        
        response.raise_for_status()
        
        file_data = response.json()["file"]
        return FileUploadResponse(**file_data)
    
    except requests.HTTPError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File upload failed: {str(e)}"
        )
        
@router.post("/clone", response_model=VoiceCloneRequest)
async def clone_voice(
    request: VoiceCloneRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if user.subscription_status != "ACTIVE":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Active subscription required for voice cloning"
        )
        
    try:
        headers = {
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json"
        }
        
        result = await db.execute(select(Voice_ID).where(Voice_ID.voice_id == request.voice_id))
        existing_voice = result.scalars().first()
        
        if existing_voice:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Voice ID already exists"
            )
            
        response = requests.post(
            VOICE_CLONE_URL,
            headers=headers,
            json=request.model_dump(exclude_none=True)
        )
        
        response.raise_for_status()
        clone_data = response.json()
        
        voice = Voice(
            user_id=user.id,
            voice_id=request.voice_id,
            detail_info="Voice Clone",
        )
        
        db.add(voice)
        await db.commit()
        
        activation_payload = {
            "text": "Voice activation",
            "voice_setting": {
                "voice_id": request.voice_id
            },
            "audio_setting": {
                "format": "mp3"
            }
        }
        
        activation_response = requests.post(
            TTS_URL,
            headers=headers,
            json=activation_payload
        )
        activation_response.raise_for_status()
        
        return VoiceCloneResponse(
            voice_id=request.voice_id,
            input_sensitive=clone_data.get("input_sensitive", False),
            preview_audio=clone_data.get("preview_audio")
        )
        
    except requests.HTTPError as e:
        await db.rollback()
        error_detail = f"Voice cloning failed: {str(e)}"
        if e.response.status_code == 402:
            error_detail = "Insufficient credits for voice cloning"
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_detail
        )
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Voice cloning error: {str(e)}"
        )
        
