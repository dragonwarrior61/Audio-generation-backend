import json
import time
from typing import Optional, List
from pydantic import BaseModel, Field
from io import BytesIO
from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from app.config import settings
from app.database import get_db
from sqlalchemy.ext.asyncio import AsyncSession
import requests

router = APIRouter()

GROUP_ID = settings.GROUP_ID
API_KEY = settings.API_KEY
TTS_URL = f"https://api.minimax.io/v1/t2a_v2?GroupId={GROUP_ID}"

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
async def generate_tts(request: TTSRequest):
    try:
        headers = {
            "Authorization": f"Bearer {API_KEY}",
            "Content_Type": "application/json"
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