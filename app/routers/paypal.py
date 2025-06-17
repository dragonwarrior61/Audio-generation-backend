from fastapi import APIRouter, Request, HTTPException, Depends, status
from fastapi.responses import RedirectResponse, JSONResponse
import httpx
from app.config import settings
from pydantic import BaseModel
from datetime import datetime, timedelta
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.models.user import User
from app.models.subscription_history import SubScriptionHistory
from app.schemas.user import SubscriptionStatus
from typing import Optional

router = APIRouter()

PAYPAL_CLIENT_ID = settings.PAYPAL_CLIENT_ID
PAYPAL_SECRET = settings.PAYPAL_SECRET
PAYPAL_BASE_URL = settings.PAYPAL_BASE_URL
PAYPAL_WEBHOOK_ID = settings.PAYPAL_WEBHOOK_ID

class SubscriptionRequest(BaseModel):
    plan_id: str
    user_id: int
    return_url: str
    cancel_url: str
    
async def get_paypal_access_token():
    auth = (PAYPAL_CLIENT_ID, PAYPAL_SECRET)
    data = {"grant_type": "client_credentials"}
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{PAYPAL_BASE_URL}/v1/oauth2/token",
            auth=auth,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        
    if response.status_code != 200:
        return HTTPException(status_code=400, detail="Failed to get Paypal access token")
    
    return response.json()["access_token"]

async def update_user_subscription(
    db: AsyncSession,
    user_id: int,
    subscription_id: str,
    plan_id: str,
    sub_status: SubscriptionStatus
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
        
    user.subscription_id = subscription_id
    user.subscription_plan_id = plan_id
    user.subscription_status = sub_status
    user.payment_method = "paypal"
    
    if sub_status == SubscriptionStatus.ACTIVE:
        user.subsrciption_start_date = datetime.utcnow()
        user.subscription_end_date = datetime.utcnow() + timedelta(days=30)
    
    await db.commit()
    await db.refresh(user)
    return user

async def create_subscription_history(
    db: AsyncSession,
    user_id: int,
    event_type: str,
    event_data: Optional[dict] = None
):
    history = SubScriptionHistory(
        user_id = user_id,
        event_type = event_type,
        event_data = str(event_data) if event_data else None
    )
    db.add(history)
    await db.commit()
    await db.refresh(history)
    return history

@router.post("/create_subscription")
async def create_subscription(
    sub_req: SubscriptionRequest,
    db: AsyncSession = Depends(get_db)
):
    
    result = await db.execute(select(User).where(User.id == sub_req.user_id))
    user = result.scalars().first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail = "User not found"
        )
    
    access_token = await get_paypal_access_token()
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {access_token}",
        "Prefer": "return=representation"
    }
    
    subscription_data = {
        "plan_id": sub_req.plan_id,
        "start_time": (datetime.utcnow() + timedelta(minutes=5)).isoformat() + "Z",
        "subscriber": {
            "email-address": user.email
        },
        "application_context": {
            "brand_name": settings.APP_NAME,
            "locale": "en-US",
            "shipping_preference": "NO_SHIPPING",
            "user_action": "SUBSCRIBE_NOW",
            "payment_method": {
                "payer_selected": "PAYPAL",
                "payee_preferred": "IMMEDIATE_PAYMENT_REQUIRED"
            },
            "return_url": sub_req.return_url,
            "cancel_url": sub_req.cancel_url
        }
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{PAYPAL_BASE_URL}/v1/billing/subscriptions",
            headers=headers,
            json=subscription_data
        )
        
    if response.status_code != 201:
        raise HTTPException(status_code=400, detail="Failed to create subscription")
    
    subscription = response.json()
    approval_url = next(
        link["href"] for link in subscription["links"]
        if link["rel"] == "approve"
    )
    
    await create_subscription_history(
        db=db,
        user_id=sub_req.user_id,
        event_type="subscription_created",
        event_data={
            "subscription_id": subscription["id"],
            "plan_id": sub_req.plan_id,
            "status": "pending"
        }
    )
    
    return {"approval_url": approval_url, "subscription_id": subscription["id"]}

@router.post("/paypal-webhook")
async def paypal_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    access_token = await get_paypal_access_token()
    headers = {
        "Content-type": "application/json",
        "Authorization": f"Bearer {access_token}"
    }
    
    body = await request.json()
    webhook_event = body.get("event_type")
    
    async with httpx.AsyncClient() as client:
        verify_response = await client.post(
            f"{PAYPAL_BASE_URL}/v1/notifications/verify-webhook-signature",
            headers=headers,
            json={
                "transmission_id": request.headers.get("PAYPAL-TRANSMISSION-ID"),
                "transmission_time": request.headers.get("PAYPAL-TRANSMISSION-TIME"),
                "cert_url": request.headers.get("PAYPAL-CERT-URL"),
                "auth_algo": request.headers.get("PAYPAL-AUTH-ALGO"),
                "transmission_sig": request.headers.get("PAYPAL-TRANSMISSION-SIG"),
                "webhook_id": PAYPAL_WEBHOOK_ID,
                "webhook_event": body
            }
        )
        
    if verify_response.status_code != 200 or verify_response.json()["verification_status"] != "SUCCESS":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Webhook verification failed"
        )
        
    subscription_id = None
    user_id = None
    
    
    if webhook_event == "BILLING.SUBSCRIPTION.ACTIVATED":
        subscription_id = body["resource"]["id"]
        result = await db.execute(select(User).where(User.subscription_id == subscription_id))
        user = result.scalars().first()
        
        if user:
            await update_user_subscription(
                db=db,
                user_id=user.id,
                subscription_id=subscription_id,
                plan_id=user.subscription_plan_id,
                sub_status=SubscriptionStatus.ACTIVE
            )
            
            if user.payment_method != "paypal":
                user.payment_method ="paypal"
                await db.commit()
            await create_subscription_history(
                db=db,
                user_id=user.id,
                event_type="subscription_activated",
                event_data=body
            )
        
    elif webhook_event == "BILLING.SUBSCRIPTION.CANCELLED":
        subscription_id = body["resource"]["id"]
        result = await db.execute(select(User).where(User.subscription_id == subscription_id))
        user = result.scalars().first()
        if user:
            await update_user_subscription(
                db=db,
                user_id=user.id,
                subscription_id=subscription_id,
                plan_id=user.subscription_plan_id,
                sub_status=SubscriptionStatus.CANCELLED
            )
            await create_subscription_history(
                db=db,
                user_id=user.id,
                event_type="subscription_cancelled",
                event_data=body
            )
        
    elif webhook_event == "PAYMENT.SALE.COMPLETED":
        subscription_id = body["resource"]["billing_agreement_id"]
        result = await db.execute(select(User).where(User.subscription_id == subscription_id))
        user = result.scalars().first()
        
        if user:
            await create_subscription_history(
                db=db,
                user_id=user.id,
                event_type="payment_received",
                event_data=body
            )
        
    return {"status": "success"}

@router.get("/subscription/{subscription_id}")
async def get_subscription(
    subscription_id: str,
    db: AsyncSession = Depends(get_db)
):
    access_token = await get_paypal_access_token()
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {access_token}"
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{PAYPAL_BASE_URL}/v1/billing/subscriptions/{subscription_id}",
            headers=headers
        )
        
    if response.status_code != 200:
        raise HTTPException(status_code=400, detail="Failed to get subscription detials")
    
    
    subscription_data = response.json()
    status_mapping = {
        "ACTIVE": SubscriptionStatus.ACTIVE,
        "CANCELLED": SubscriptionStatus.CANCELLED,
        "EXPIRED": SubscriptionStatus.INACTIVE,
        "SUSPENDED": SubscriptionStatus.PAST_DUE
    }
    
    if subscription_data.get("status") in status_mapping:
        result = await db.execute(select(User).where(User.subscription_id == subscription_id))
        user = result.scalars().first()
        if user:
            await update_user_subscription(
                db=db,
                user_id=user.id,
                subscription_id=subscription_id,
                plan_id=user.subscription_plan_id,
                sub_status=status_mapping[subscription_data["status"]]
            )
    
    return subscription_data
