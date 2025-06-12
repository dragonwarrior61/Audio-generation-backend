from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import user
import ssl
import uvicorn
import logging
from pydantic import BaseModel

app = FastAPI()

class MemeberResponse(BaseModel):
    username: str
    role_name: str
    access_level: str
    
ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
ssl_context.load_cert_chain('ssl/cert.pem', keyfile='ssl/key.pem')

origins = [
    "*"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins = origins,
    allow_credentials = True,
    allow_methods = ["*"],
    allow_headers = ["*"]
)

app.include_router(user.router, prefix="/api/users", tags=["users"])

# async def init_models():
#     async with engine.begin() as conn:
#         await conn.run_sync(Base.metadata.create_all)
        
# @app.on_event("startup")
# async def on_startup():
#     await init_models()

if __name__ == "__main__":
    
    ssl_keyfile = "ssl/key.pem"
    ssl_certfile = "ssl/cert.pem"
    
    uvicorn.run(
        "main:app",
        host = "0.0.0.0",
        port = 8000,
        ssl_keyfile = ssl_keyfile,
        ssl_certfile = ssl_certfile
    )