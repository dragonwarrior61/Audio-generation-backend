from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse
import httpx
from app.config import settings
from pydantic import BaseModel
from datetime import datetime, timedelta

router = FastAPI()

PAYPAL_CLIENT_ID = settings.PAYPAL_CLIENT_ID
PAYPAL_SECRET = settings.PAYPAL_SECRET
PAYPAL_BASE_URL = settings.PAYPAL_BASE_URL
PAYPAL_WEBHOOK_ID = settings.PAYPAL_WEBHOOK_ID

class SubscriptionRequest(BaseModel):
    plan_id: str
    user_id: str
    
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

@router.post("/create_subscription")
async def create_subscription(sub_req: SubscriptionRequest):
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
            "email-address": "user@example.com"
        },
        "application_context": {
            "brand_name": "",
            "locale": "en-US",
            "shipping_preference": "NO_SHIPPING",
            "user_action": "SUBSCRIBE_NOW",
            "payment_method": {
                "payer_selected": "PAYPAL",
                "payee_preferred": "IMMEDIATE_PAYMENT_REQUIRED"
            },
            "return_url": "https://",
            "cancel_url": ""
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
    
    return {"approval_url": approval_url, "subscription_id": subscription["id"]}

@router.post("/paypal-webhook")
async def paypal_webhook(request: Request):
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
        raise HTTPException(status_code=400, detail="Webhook verification failed")
    
    if webhook_event == "BILLING.SUBSCRIPTION.ACTIVATED":
        subscription_id = body["resource"]["id"]
        
    elif webhook_event == "BILLING.SUBSCRIPTION.CANCELLED":
        subscription_id = body["resource"]["id"]
        
    elif webhook_event == "PAYMENT.SALE.COMPLETED":
        subscription_id = body["resource"]["billing_agreement_id"]
        
    return {"status": "success"}

@router.get("/subscription/{subscription_id}")
async def get_subscription(subscription_id: str):
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
    
    return response.json()
