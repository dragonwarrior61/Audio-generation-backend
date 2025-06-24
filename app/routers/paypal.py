from fastapi import APIRouter, Request, HTTPException, Depends, status
from fastapi.responses import JSONResponse
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
from typing import Optional, Literal
import json

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

class OneTimePaymentRequest(BaseModel):
    tier: Literal["small", "medium", "large", "enterprise"]
    user_id: int
    return_url: str
    cancel_url: str

TIER_PRICES = {
    "small": 20,
    "medium": 40,
    "large": 180,
    "enterprise": 700
}

@router.post("/create_one_time_payment")
async def create_one_time_payment(
    payment_req: OneTimePaymentRequest,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(User).where(User.id == payment_req.user_id))
    user = result.scalars().first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    access_token = await get_paypal_access_token()
    
    order_data = {
        "intent": "CAPTURE",
        "purchase_units": [{
            "reference_id": f"otp_{payment_req.user_id}_{datetime.utcnow().timestamp()}",
            "amount": {
                "currency_code": "USD",
                "value": TIER_PRICES[payment_req.tier],
            },
            "description": f"{payment_req.tier.capitalize()}"
        }],
        "application_context": {
            "return_url": payment_req.return_url,
            "cancel_url": payment_req.cancel_url,
            "brand_name": settings.APP_NAME
        }
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{PAYPAL_BASE_URL}/v2/checkout/orders",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            },
            json=order_data
        )
        
    if response.status_code != 201:
        raise HTTPException(status_code=400, detail="Failed to create ")
    
    payment_data = response.json()
    approval_url = next(
        link["href"] for link in payment_data["links"]
        if link["rel"] == "approve"
    )
    
    
    await create_subscription_history(
        db=db,
        user_id=payment_req.user_id,
        event_type="one_time_payment_created",
        event_data={
            "tier": payment_req.tier,
            "amount": TIER_PRICES[payment_req.tier],
            "paypal_order_id": payment_data["id"],
            "status": "pending"
        }
    )
    
    return {"approval_url": approval_url, "order_id": payment_data["id"]}

@router.post("/paypal-webhook")
async def paypal_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    
    try:
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
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Webhook processing error: {str(e)}"
        )
        
    try:
        webhook_event = body.get("event_type")
        resource = body.get("resource", {})
        
        if webhook_event == "BILLING.SUBSCRIPTION.ACTIVATED":
            subscription_id = resource.get("id")
            if not subscription_id:
                return JSONResponse({"status": "missing subscription_id"}, status_code=400)
            
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
                    user.payment_method = "paypal"
                    await db.commit()
                    
                await create_subscription_history(
                    db=db,
                    user_id=user.id,
                    event_type="subscription_activated",
                    event_data=body
                )
            
        elif webhook_event == "BILLING.SUBSCRIPTION.CANCELLED":
            subscription_id = resource.get("id")
            if not subscription_id:
                return JSONResponse({"status": "missing subscription_id"}, status_code=400)
            
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
            subscription_id = resource.get("billing_agreement_id")
            if not subscription_id:
                return JSONResponse({"status": "missing subscription_id"}, status_code=400)
            
            result = await db.execute(select(User).where(User.subscription_id == subscription_id))
            user = result.scalars().first()
            
            if user:
                await create_subscription_history(
                    db=db,
                    user_id=user.id,
                    event_type="payment_received",
                    event_data=body
                )
                
        elif webhook_event == "PAYMENT.CAPTURE.COMPLETED":
            order_id = resource.get("id")
            amount = float(resource.get("amount", {}).get("value", 0))
            if not order_id:
                raise JSONResponse({"status": "missing order_id"}, status_code=400)
            
            result = await db.execute(
                select(SubScriptionHistory).where(
                    SubScriptionHistory.event_data.contains(f'"paypal_order_id": "{order_id}')
                )
            )
            history = result.scalars().first()
            
            if history:
                history_data = json.loads(history.event_data)
                result = await db.execute(select(User).where(User.id == history.user_id))
                user = result.scalars().first()
                
                if user:
                    if history_data.get("tier") == "small":
                        user.character_balance = user.character_balance + 500000
                    elif history_data.get("tier") == "medium":
                        user.character_balance = user.character_balance + 1000000
                    elif history_data.get("tier") == "large":
                        user.character_balance = user.character_balance + 5000000
                    elif history_data.get("tier") == "enterprise":
                        user.character_balance = user.character_balance + 20000000

                    user.payment_method = "paypal"
                    await db.commit()
                    
                    await create_subscription_history(
                        db=db,
                        user_id=user.id,
                        event_type="one_time_payment_completed",
                        event_data={
                            **body,
                            "characters_added": user.character_balance
                        }
                    )
        
        return {"status": "success"}
    
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing webhook: {str(e)}"
        )



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
