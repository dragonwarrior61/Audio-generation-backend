from fastapi import APIRouter, HTTPException, Depends, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from fastapi import Request
import stripe
import stripe.error
from app.config import settings
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.database import get_db
from app.models.user import User
from app.models.payment_history import PaymentHistory
from app.schemas.user import SubscriptionStatus
from datetime import datetime, timedelta
from typing import Optional, Literal
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
    cancel_url: str
    
async def create_stripe_customer(user: User):
    customer = stripe.Customer.create(
        email=user.email,
        metadata={
            "user_id": user.id,
            "app_name": settings.APP_NAME
        }
    )
    return customer.id

async def create_payment_history(
    db: AsyncSession,
    user_id: int,
    event_type: str,
    event_data: Optional[dict] = None
):
    history = PaymentHistory(
        user_id = user_id,
        event_type = event_type,
        event_data = str(event_data) if event_data else None
    )
    db.add(history)
    await db.commit()
    await db.refresh(history)
    return history

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
        
        history = PaymentHistory(
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
        
class StripeCharacterPaymentRequest(BaseModel):
    tier: Literal["small", "medium", "large", "enterprise"]
    user_id: int
    success_url: str
    cancel_url: str
    
CHARACTER_PACK_PRICES = {
    "small": 2000,
    "medium": 4000,
    "large": 18000,
    "enterprise": 70000
}

@router.post("/create_character_payment")
async def create_character_payment(
    payment_req: StripeCharacterPaymentRequest,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(User).where(User.id == payment_req.user_id))
    user = result.scalars().first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
        
    try:
        line_item = {
            "price_data": {
                "currency": "usd",
                "product_data": {
                    "name": f"{payment_req.tier.capitalize()} Character Pack",
                },
                "unit_amount": CHARACTER_PACK_PRICES[payment_req.tier],
            },
            "quantity": 1
        }
        description = f"Character Pack: {payment_req.tier}"
        
        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[line_item],
            mode='payment',
            success_url=payment_req.success_url,
            cancel_url=payment_req.cancel_url,
            metadata={
                "user_id": str(user.id),
                "product_type": "character_pack",
                "tier": payment_req.tier or "",
            }
        )
        
        history = PaymentHistory(
            user_id = user.id,
            event_type = "character_payment_created",
            event_data = json.dumps({
                "session_id": session.id,
                "product_type": "character_pack",
                "tier": payment_req.tier,
                "amount": line_item["price_data"]["unit_amount"] / 100,
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
        
class StripeVoicePaymentRequest(BaseModel):
    tier: Literal["pro", "business"]
    user_id: int
    success_url: str
    cancel_url: str
    
VOICE_PRICES = {
    "pro": 900,
    "business": 600
}

@router.post("/create_voice_payment")
async def create_character_payment(
    payment_req: StripeVoicePaymentRequest,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(User).where(User.id == payment_req.user_id))
    user = result.scalars().first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
        
    try:
        line_item = {
            "price_data": {
                "currency": "usd",
                "product_data": {
                    "name": f"{payment_req.tier.capitalize()} Voice",
                },
                "unit_amount": VOICE_PRICES[payment_req.tier],
            },
            "quantity": 1
        }
        description = f"Voice: {payment_req.tier}"
        
        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[line_item],
            mode='payment',
            success_url=payment_req.success_url,
            cancel_url=payment_req.cancel_url,
            metadata={
                "user_id": str(user.id),
                "product_type": "voice_clone",
                "tier": payment_req.tier or "",
            }
        )
        
        history = PaymentHistory(
            user_id = user.id,
            event_type = "voice_payment_created",
            event_data = json.dumps({
                "session_id": session.id,
                "product_type": "voice_clone",
                "tier": payment_req.tier,
                "amount": line_item["price_data"]["unit_amount"] / 100,
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
    
    if event_type == 'checkout.session.completed' and data.get('mode') == "subscription":
        user_id = data['metadata'].get('user_id')
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
        
        history = PaymentHistory(
            user_id=int(user_id),
            event_type="subscription_activated",
            event_data=json.dumps(data)
        )
        
        db.add(history)
        await db.commit()
    
    elif event_type == 'checkout.session.completed' and data.get('mode') == "payment":
        user_id = data['metadata'].get('user_id')
        product_type = data['metadata'].get('product_type')
        
        if not user_id:
            return JSONResponse({"status": "missing user_id"}, status_code=400)
        
        result = await db.execute(
            select(PaymentHistory).where(
                PaymentHistory.event_data.contains(f'"session_id":"{data["id"]}"')
            )
        )
        
        history = result.scalars().first()
        
        if history and history.user_id == int(user_id):
            history_data = json.loads(history.event_data)
            result = await db.execute(select(User).where(User.id == history.user_id))
            user = result.scalars().first()
            
            if user:
                if product_type == "character_pack":
                    tier = history_data.get('tier')
                    if tier == "small":
                        user.character_balance = user.character_balance + 500000
                    elif tier == "medium":
                        user.character_balance = user.character_balance + 1000000
                    elif tier == "large":
                        user.character_balance = user.character_balance + 5000000
                    elif tier == "enterprise":
                        user.character_balance = user.character_balance + 20000000
                elif product_type == "voice_clone":
                    user.voice_balance = user.voice_balance + 1
                    
                user.payment_method = "stripe"
                await db.commit()
                
                if product_type == "character_pack":    
                    await create_payment_history(
                        db=db,
                        user_id=user.id,
                        event_type="character_payment_completed",
                        event_data={
                            **data,
                            "new_balance": user.character_balance
                        }
                    )
                elif product_type == "voice_clone":
                    await create_payment_history(
                        db=db,
                        user_id=user.id,
                        event_type="voice_payment_completed",
                        event_data={
                            **data,
                            "new_balance": user.voice_balance
                        }
                    )
    elif event_type == 'customer.subscription.updated':
        subscription = data
        user_id = subscription['metadata'].get('user_id')
        
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
                
                history = PaymentHistory(
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
                history = PaymentHistory(
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
        
        history = PaymentHistory(
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