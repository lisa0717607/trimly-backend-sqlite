from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks, Request
from sqlalchemy.orm import Session
from typing import List, Dict, Any, Optional
from pydantic import BaseModel

from subscription_models import (
    SubscriptionPlan, UserSubscription, Payment, UsageQuota, 
    PromoCode, PromoCodeRedemption, Invoice
)
from models_extended import User, get_db
from auth import get_current_user, get_current_admin_user
from subscription_service import subscription_service
from paypal_service import paypal_service
from utils import safe_json_loads, safe_json_dumps

# 建立路由器
router = APIRouter(prefix="/api/v1/subscription", tags=["Subscription & Payment"])

# Pydantic 模型
class SubscriptionPlanResponse(BaseModel):
    id: int
    name: str
    display_name: str
    price_monthly: float
    price_yearly: float
    transcription_minutes_monthly: int
    ai_enhancements_monthly: int
    ai_summaries_monthly: int
    projects_limit: int
    version_history_limit: int
    storage_gb: float
    advanced_ai_features: bool
    priority_processing: bool
    api_access: bool
    white_label: bool
    
    class Config:
        from_attributes = True

class CreateSubscriptionRequest(BaseModel):
    plan_name: str
    billing_cycle: str = "monthly"  # monthly, yearly
    promo_code: Optional[str] = None

class PromoCodeValidationRequest(BaseModel):
    code: str
    plan_id: int

class UsageQuotaResponse(BaseModel):
    quota_month: str
    transcription_minutes_used: float
    transcription_minutes_limit: int
    ai_enhancements_used: int
    ai_enhancements_limit: int
    ai_summaries_used: int
    ai_summaries_limit: int
    storage_gb_used: float
    storage_gb_limit: float

# ==================== 訂閱方案 API ====================

@router.get("/plans", response_model=List[SubscriptionPlanResponse])
async def get_subscription_plans(db: Session = Depends(get_db)):
    """取得所有訂閱方案"""
    
    plans = db.query(SubscriptionPlan).filter(
        SubscriptionPlan.is_active == True
    ).order_by(SubscriptionPlan.price_monthly).all()
    
    return plans

@router.get("/plans/{plan_id}", response_model=SubscriptionPlanResponse)
async def get_subscription_plan(
    plan_id: int,
    db: Session = Depends(get_db)
):
    """取得特定訂閱方案"""
    
    plan = db.query(SubscriptionPlan).filter(
        SubscriptionPlan.id == plan_id,
        SubscriptionPlan.is_active == True
    ).first()
    
    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subscription plan not found"
        )
    
    return plan

# ==================== 使用者訂閱 API ====================

@router.get("/my-subscription")
async def get_my_subscription(
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """取得當前使用者的訂閱資訊"""
    
    subscription = subscription_service.get_user_subscription(current_user.id)
    plan = subscription_service.get_user_plan(current_user.id)
    
    if subscription:
        return {
            "has_subscription": True,
            "subscription": {
                "id": subscription.id,
                "status": subscription.status,
                "billing_cycle": subscription.billing_cycle,
                "started_at": subscription.started_at,
                "current_period_start": subscription.current_period_start,
                "current_period_end": subscription.current_period_end,
                "next_billing_date": subscription.next_billing_date,
                "cancelled_at": subscription.cancelled_at,
                "expires_at": subscription.expires_at,
                "days_until_renewal": subscription.days_until_renewal()
            },
            "plan": SubscriptionPlanResponse.from_orm(plan)
        }
    else:
        return {
            "has_subscription": False,
            "subscription": None,
            "plan": SubscriptionPlanResponse.from_orm(plan)  # 免費方案
        }

@router.post("/subscribe")
async def create_subscription(
    request: CreateSubscriptionRequest,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """建立新訂閱"""
    
    # 驗證方案存在
    plan = db.query(SubscriptionPlan).filter(
        SubscriptionPlan.name == request.plan_name,
        SubscriptionPlan.is_active == True
    ).first()
    
    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subscription plan not found"
        )
    
    # 驗證計費週期
    if request.billing_cycle not in ["monthly", "yearly"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid billing cycle. Must be 'monthly' or 'yearly'"
        )
    
    # 驗證促銷代碼（如果提供）
    discount_info = None
    if request.promo_code:
        promo_validation = subscription_service.validate_promo_code(
            request.promo_code, current_user.id, plan.id
        )
        
        if not promo_validation["valid"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=promo_validation["error"]
            )
        
        # 計算折扣
        original_amount = plan.price_yearly if request.billing_cycle == "yearly" else plan.price_monthly
        discount_info = subscription_service.calculate_discount(
            original_amount, promo_validation["promo_code"]
        )
    
    # 建立訂閱
    result = await subscription_service.create_subscription(
        current_user.id, request.plan_name, request.billing_cycle
    )
    
    if result["success"]:
        response_data = {
            "success": True,
            "subscription_id": result["subscription_id"],
            "requires_payment": result["requires_payment"]
        }
        
        if result["requires_payment"]:
            response_data.update({
                "approve_link": result["approve_link"],
                "paypal_subscription_id": result["paypal_subscription_id"]
            })
        
        if discount_info:
            response_data["discount_applied"] = discount_info
        
        return response_data
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result["error"]
        )

@router.post("/cancel")
async def cancel_subscription(
    reason: str = "User requested cancellation",
    current_user = Depends(get_current_user)
):
    """取消訂閱"""
    
    result = await subscription_service.cancel_subscription(current_user.id, reason)
    
    if result["success"]:
        return result
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result["error"]
        )

# ==================== 配額管理 API ====================

@router.get("/quota", response_model=UsageQuotaResponse)
async def get_usage_quota(
    month: Optional[str] = None,
    current_user = Depends(get_current_user)
):
    """取得使用配額資訊"""
    
    plan = subscription_service.get_user_plan(current_user.id)
    quota = subscription_service.get_usage_quota(current_user.id, month)
    
    return UsageQuotaResponse(
        quota_month=quota.quota_month,
        transcription_minutes_used=quota.transcription_minutes_used,
        transcription_minutes_limit=plan.transcription_minutes_monthly,
        ai_enhancements_used=quota.ai_enhancements_used,
        ai_enhancements_limit=plan.ai_enhancements_monthly,
        ai_summaries_used=quota.ai_summaries_used,
        ai_summaries_limit=plan.ai_summaries_monthly,
        storage_gb_used=quota.storage_gb_used,
        storage_gb_limit=plan.storage_gb
    )

@router.get("/quota/check")
async def check_quota_availability(
    resource_type: str,
    amount: float = 1,
    current_user = Depends(get_current_user)
):
    """檢查配額是否足夠"""
    
    available = subscription_service.check_quota_limit(
        current_user.id, resource_type, amount
    )
    
    plan = subscription_service.get_user_plan(current_user.id)
    quota = subscription_service.get_usage_quota(current_user.id)
    
    # 取得當前使用量和限制
    if resource_type == "transcription":
        used = quota.transcription_minutes_used
        limit = plan.transcription_minutes_monthly
    elif resource_type == "ai_enhancement":
        used = quota.ai_enhancements_used
        limit = plan.ai_enhancements_monthly
    elif resource_type == "ai_summary":
        used = quota.ai_summaries_used
        limit = plan.ai_summaries_monthly
    elif resource_type == "storage":
        used = quota.storage_gb_used
        limit = plan.storage_gb
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid resource type"
        )
    
    return {
        "available": available,
        "resource_type": resource_type,
        "requested_amount": amount,
        "current_usage": used,
        "limit": limit,
        "remaining": max(0, limit - used),
        "would_exceed": not available
    }

# ==================== 促銷代碼 API ====================

@router.post("/promo-code/validate")
async def validate_promo_code(
    request: PromoCodeValidationRequest,
    current_user = Depends(get_current_user)
):
    """驗證促銷代碼"""
    
    result = subscription_service.validate_promo_code(
        request.code, current_user.id, request.plan_id
    )
    
    if result["valid"]:
        # 計算折扣預覽
        plan = db.query(SubscriptionPlan).filter(
            SubscriptionPlan.id == request.plan_id
        ).first()
        
        if plan:
            monthly_discount = subscription_service.calculate_discount(
                plan.price_monthly, result["promo_code"]
            )
            yearly_discount = subscription_service.calculate_discount(
                plan.price_yearly, result["promo_code"]
            )
            
            return {
                "valid": True,
                "discount_type": result["discount_type"],
                "discount_value": result["discount_value"],
                "monthly_pricing": monthly_discount,
                "yearly_pricing": yearly_discount
            }
    
    return result

# ==================== PayPal Webhook API ====================

@router.post("/webhook/paypal")
async def paypal_webhook(
    request: Request,
    db: Session = Depends(get_db)
):
    """處理 PayPal Webhook 事件"""
    
    # 取得請求資料
    headers = dict(request.headers)
    body = await request.body()
    body_str = body.decode('utf-8')
    
    try:
        event_data = safe_json_loads(body_str, {})
        
        # 驗證 Webhook 簽名（簡化實現）
        webhook_id = "your-webhook-id"  # 應該從環境變數讀取
        is_valid = paypal_service.verify_webhook_signature(headers, body_str, webhook_id)
        
        if not is_valid:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid webhook signature"
            )
        
        # 處理事件
        result = await paypal_service.process_webhook_event(event_data)
        
        # 根據事件類型執行相應操作
        event_type = event_data.get("event_type")
        resource = event_data.get("resource", {})
        
        if event_type == "BILLING.SUBSCRIPTION.ACTIVATED":
            # 訂閱啟用
            paypal_subscription_id = resource.get("id")
            
            # 找到對應的本地訂閱
            subscription = db.query(UserSubscription).filter(
                UserSubscription.paypal_subscription_id == paypal_subscription_id
            ).first()
            
            if subscription:
                await subscription_service.activate_subscription(
                    subscription.id, resource
                )
        
        elif event_type == "BILLING.SUBSCRIPTION.CANCELLED":
            # 訂閱取消
            paypal_subscription_id = resource.get("id")
            
            subscription = db.query(UserSubscription).filter(
                UserSubscription.paypal_subscription_id == paypal_subscription_id
            ).first()
            
            if subscription:
                subscription.status = "cancelled"
                subscription.cancelled_at = datetime.utcnow()
                db.commit()
        
        elif event_type == "PAYMENT.SALE.COMPLETED":
            # 支付完成
            payment_id = resource.get("id")
            amount = float(resource.get("amount", {}).get("total", 0))
            
            # 記錄支付
            # 這裡需要根據實際需求實現支付記錄邏輯
        
        return {"status": "success", "processed": result["processed"]}
        
    except Exception as e:
        # 記錄錯誤但不返回錯誤（避免 PayPal 重試）
        print(f"Webhook processing error: {str(e)}")
        return {"status": "error", "message": str(e)}

# ==================== 管理員 API ====================

@router.get("/admin/analytics")
async def get_subscription_analytics(
    current_admin = Depends(get_current_admin_user)
):
    """取得訂閱分析資料（管理員專用）"""
    
    analytics = subscription_service.get_subscription_analytics()
    return analytics

@router.post("/admin/plans", response_model=SubscriptionPlanResponse)
async def create_subscription_plan(
    plan_data: dict,
    current_admin = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """建立新的訂閱方案（管理員專用）"""
    
    plan = SubscriptionPlan(**plan_data)
    db.add(plan)
    db.commit()
    db.refresh(plan)
    
    return plan

@router.put("/admin/plans/{plan_id}", response_model=SubscriptionPlanResponse)
async def update_subscription_plan(
    plan_id: int,
    plan_data: dict,
    current_admin = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """更新訂閱方案（管理員專用）"""
    
    plan = db.query(SubscriptionPlan).filter(
        SubscriptionPlan.id == plan_id
    ).first()
    
    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subscription plan not found"
        )
    
    for key, value in plan_data.items():
        if hasattr(plan, key):
            setattr(plan, key, value)
    
    plan.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(plan)
    
    return plan

