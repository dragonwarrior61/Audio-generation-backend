from fastapi import APIRouter, HTTPException, Depends, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel
from fastapi import Request
import stripe
import stripe.error
from app.config import settings
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.database import get_db
from app.models.user import User
from app.models.subscription_history import SubScriptionHistory
from app.schemas.user import SubscriptionStatus
from datetime import datetime, timedelta
from typing import Optional
import json

router = APIRouter()
# Load your Stripe secret key from an environment variable
stripe.api_key = settings.STRIPE_API_KEY
WEBHOOK_SECRET = settings.STRIPE_WEBHOOK_SECRET
# Request model for payment data

class StripeSubscriptionRequest(BaseModel):
    price_id: str
    user_id: int
    success_url: str
    cancle_url: str
    
async def create_stripe_customer(user: User):
    customer = stripe.Customer.create(
        email=user.email,
        metadata={
            "user_id": user.id,
            "app_name": settings.APP_NAME
        }
    )
    return customer.id

async def update_user_stripe_info(
    db: AsyncSession,
    user_id: int,
    subscription_id: Optional[str] = None,
    plan_id: Optional[str] = None,
    sub_status: Optional[SubscriptionStatus] = None,
    payment_method: Optional[str] = None
):
    
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
        
    if subscription_id:
        user.subscription_id = subscription_id
    
    if plan_id:
        user.subscription_plan_id = plan_id
        
    if sub_status:
        user.subscription_status = sub_status
    
    if payment_method:
        user.payment_method = payment_method
    
    if sub_status == SubscriptionStatus.ACTIVE:
        user.subsrciption_start_date = datetime.utcnow()
        user.subscription_end_date = datetime.utcnow() + timedelta(days=30)
        
    await db.commit()
    await db.refresh(user)
    return user

@router.post("/create-subscription")
async def create_subscription(
    sub_req: StripeSubscriptionRequest,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(User).where(User.id == sub_req.user_id))
    user = result.scalars().first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
        
    try:
        session = stripe.checkout.Session.create(
            customer_email=user.email,
            payment_method_types=['card'],
            line_items=[{
                'price': sub_req.price_id,
                'quantity': 1,
            }],
            mode='subscription',
            success_url=sub_req.success_url,
            cancel_url=sub_req.cancel_url,
            metadata={
                "user_id": str(user.id),
                "price_id": sub_req.price_id
            }
        )
        
        history = SubScriptionHistory(
            user_id=user.id,
            event_type="checkout_session_created",
            event_data=json.dumps({
                "session_id": session.id,
                "price_id": sub_req.price_id,
                "status": "pending"
            })
        )
        db.add(history)
        await db.commit()
        
        return {"checkout_url": session.url}
    except stripe.error.StripeError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
        
@router.post("/webhook/")
async def stripe_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    payload = await request.body()
    sig_header = request.headers.get('stripe-signature')
    
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, WEBHOOK_SECRET
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid payload: {str(e)}"
        )
    except stripe.error.SignatureVerificationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid signature: {str(e)}"
        )

    event_type = event['type']
    data = event['data']['object']
    
    if event_type == 'checkout.session.completed':
        user_id = data['meatadata'].get('user_id')
        if not user_id:
            return JSONResponse({"status": "missing user_id"}, status_code=400)
        
        subscription_id = data.get('subscription')
        price_id = data['metadata'].get('price_id')
        
        await update_user_stripe_info(
            db=db,
            user_id=int(user_id),
            subscription_id=subscription_id,
            plan_id=price_id,
            sub_status=SubscriptionStatus.ACTIVE,
            payment_method="stripe"
        )
        
        history = SubScriptionHistory(
            user_id=int(user_id),
            event_type="subscription_activated",
            event_data=json.dumps(data)
        )
        
        db.add(history)
        await db.commit()
        
    elif event_type == 'customer.subscription.updated':
        subscription = data
        user_id = subscription['metadata'].get['user_id']
        
        if user_id:
            status_map = {
                'active': SubscriptionStatus.ACTIVE,
                'past_due': SubscriptionStatus.PAST_DUE,
                'canceled': SubscriptionStatus.CANCELLED,
                'unpaid': SubscriptionStatus.PAST_DUE,
                'incomplete': SubscriptionStatus.PENDING,
                'incomplete_expired': SubscriptionStatus.CANCELLED
            }
            
            new_status = status_map.get(subscription['status'])
            
            if new_status:
                await update_user_stripe_info(
                    db=db,
                    user_id=int(user_id),
                    subscription_id=subscription['id'],
                    sub_status=new_status
                )
                
                history = SubScriptionHistory(
                    user_id = int(user_id),
                    event_type = "subscription_updated",
                    event_data = json.dumps(subscription)
                )
                db.add(history)
                await db.commit()
        
        elif event_type == 'invoice.paid':
            subscription_id = data['subscription']
            result = await db.execute(
                select(User).where(User.subscription_id == subscription_id)
            )
            user = result.scalars().first()
            
            if user:
                history = SubScriptionHistory(
                    user_id = user.id,
                    event_type = "payment_received",
                    event_data = json.dumps(data)
                )
                db.add(history)
                await db.commit()
                
        return JSONResponse({"status": "success"})

@router.get("/subscription/{subscription_id}")
async def get_subscripton(
    subscription_id: str,
    db: AsyncSession = Depends(get_db)
):
    try:
        subscription = stripe.Subscription.retrieve(subscription_id)
        
        result = await db.execute(select(User).where(User.subscription_id == subscription_id))
        
        user = result.scalars().first()
        
        if user:
            status_map = {
                'active': SubscriptionStatus.ACTIVE,
                'past_due': SubscriptionStatus.PAST_DUE,
                'canceled': SubscriptionStatus.CANCELLED,
                'unpaid': SubscriptionStatus.PAST_DUE
            }
            
            new_status = status_map.get(subscription['status'])
            
            if new_status and user.subscription_status != new_status:
                await update_user_stripe_info(
                    db=db,
                    user_id=user.id,
                    subscription_id=subscription_id,
                    sub_status=new_status
                )
                
        return subscription
    
    except stripe.error.StripeError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

@router.post("/cancel_subscription")
async def cancel_subscription(
    user_id: int,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    
    if not user or not user.subscription_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Subscription not found"
        )
        
    try:
        subsciption = stripe.Subscription.modify(
            user.subscription_id,
            cancel_at_period_end=True
        )
        
        await update_user_stripe_info(
            db=db,
            user_id=user.id,
            sub_status=SubscriptionStatus.CANCELLED,
            payment_method="stripe"
        )
        
        history = SubScriptionHistory(
            user_id = user.id,
            event_type = "subscription_cancelled",
            event_data = json.dumps(subsciption)
        )
        
        db.add(history)
        await db.commit()
        
        return {"status": "success", "message": "Subscription will cancel at period end"}
    
    except stripe.error.StripeError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )