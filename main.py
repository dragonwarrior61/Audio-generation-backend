from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import ssl
import logging
from pydantic import BaseModel

app = FastAPI()

class MemeberResponse(BaseModel):
    username: str
    role_name: str
    access_level: str
    
