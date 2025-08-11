from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from sqlalchemy.orm import Session

from subscription_models import (
    SubscriptionPlan, UserSubscription, Payment, UsageQuota, 
    PromoCode, PromoCodeRedemption, Invoice, DEFAULT_SUBSCRIPTION_PLANS
)
from models_extended import User, SessionLocal
from paypal_service import paypal_service
from utils import safe_json_loads, safe_json_dumps

class SubscriptionService:
    """訂閱管理服務"""
    
    def __init__(self):
        self.db = SessionLocal()
    
    def initialize_default_plans(self):
        """初始化預設訂閱方案"""
        
        for plan_data in DEFAULT_SUBSCRIPTION_PLANS:
            existing_plan = self.db.query(SubscriptionPlan).filter(
                SubscriptionPlan.name == plan_data["name"]
            ).first()
            
            if not existing_plan:
                plan = SubscriptionPlan(**plan_data)
                self.db.add(plan)
        
        self.db.commit()
    
    def get_user_subscription(self, user_id: int) -> Optional[UserSubscription]:
        """取得使用者當前訂閱"""
        
        return self.db.query(UserSubscription).filter(
            UserSubscription.user_id == user_id,
            UserSubscription.status == "active"
        ).first()
    
    def get_user_plan(self, user_id: int) -> SubscriptionPlan:
        """取得使用者當前方案（如果沒有訂閱則返回免費方案）"""
        
        subscription = self.get_user_subscription(user_id)
        
        if subscription and subscription.is_active():
            return subscription.plan
        
        # 返回免費方案
        free_plan = self.db.query(SubscriptionPlan).filter(
            SubscriptionPlan.name == "free"
        ).first()
        
        return free_plan
    
    def get_usage_quota(self, user_id: int, month: str = None) -> UsageQuota:
        """取得使用者當月配額使用情況"""
        
        if not month:
            month = datetime.utcnow().strftime("%Y-%m")
        
        quota = self.db.query(UsageQuota).filter(
            UsageQuota.user_id == user_id,
            UsageQuota.quota_month == month
        ).first()
        
        if not quota:
            quota = UsageQuota(
                user_id=user_id,
                quota_month=month
            )
            self.db.add(quota)
            self.db.commit()
            self.db.refresh(quota)
        
        return quota
    
    def check_quota_limit(self, user_id: int, resource_type: str, amount: float = 1) -> bool:
        """檢查配額限制"""
        
        plan = self.get_user_plan(user_id)
        quota = self.get_usage_quota(user_id)
        
        if resource_type == "transcription":
            limit = plan.transcription_minutes_monthly
            used = quota.transcription_minutes_used
            return (used + amount) <= limit
            
        elif resource_type == "ai_enhancement":
            limit = plan.ai_enhancements_monthly
            used = quota.ai_enhancements_used
            return (used + amount) <= limit
            
        elif resource_type == "ai_summary":
            limit = plan.ai_summaries_monthly
            used = quota.ai_summaries_used
            return (used + amount) <= limit
            
        elif resource_type == "storage":
            limit = plan.storage_gb
            used = quota.storage_gb_used
            return (used + amount) <= limit
        
        return False
    
    def consume_quota(self, user_id: int, resource_type: str, amount: float):
        """消耗配額"""
        
        quota = self.get_usage_quota(user_id)
        
        if resource_type == "transcription":
            quota.transcription_minutes_used += amount
        elif resource_type == "ai_enhancement":
            quota.ai_enhancements_used += int(amount)
        elif resource_type == "ai_summary":
            quota.ai_summaries_used += int(amount)
        elif resource_type == "storage":
            quota.storage_gb_used += amount
        
        quota.updated_at = datetime.utcnow()
        self.db.commit()
    
    async def create_subscription(self, user_id: int, plan_name: str, 
                                billing_cycle: str = "monthly") -> Dict[str, Any]:
        """建立新訂閱"""
        
        # 取得方案
        plan = self.db.query(SubscriptionPlan).filter(
            SubscriptionPlan.name == plan_name
        ).first()
        
        if not plan:
            return {
                "success": False,
                "error": "Subscription plan not found"
            }
        
        # 取得使用者
        user = self.db.query(User).filter(User.id == user_id).first()
        if not user:
            return {
                "success": False,
                "error": "User not found"
            }
        
        # 檢查是否已有活躍訂閱
        existing_subscription = self.get_user_subscription(user_id)
        if existing_subscription:
            return {
                "success": False,
                "error": "User already has an active subscription"
            }
        
        # 免費方案不需要支付
        if plan.name == "free":
            subscription = UserSubscription(
                user_id=user_id,
                plan_id=plan.id,
                status="active",
                billing_cycle=billing_cycle,
                current_period_start=datetime.utcnow(),
                current_period_end=datetime.utcnow() + timedelta(days=30)
            )
            
            self.db.add(subscription)
            self.db.commit()
            
            return {
                "success": True,
                "subscription_id": subscription.id,
                "requires_payment": False
            }
        
        # 付費方案需要建立 PayPal 訂閱
        try:
            # 準備 PayPal 訂閱資料
            user_data = {
                "user_id": user_id,
                "email": user.email,
                "first_name": user.email.split("@")[0],  # 簡化實現
                "return_url": "https://trimly.com/subscription/success",
                "cancel_url": "https://trimly.com/subscription/cancel"
            }
            
            # 這裡需要先建立 PayPal 方案（如果還沒有的話）
            # 為了簡化，我們假設方案已經在 PayPal 中建立
            paypal_plan_id = f"P-{plan.name.upper()}-{billing_cycle.upper()}"
            
            paypal_result = await paypal_service.create_subscription(
                paypal_plan_id, user_data
            )
            
            if paypal_result["success"]:
                # 建立本地訂閱記錄
                subscription = UserSubscription(
                    user_id=user_id,
                    plan_id=plan.id,
                    status="pending",  # 等待 PayPal 確認
                    billing_cycle=billing_cycle,
                    paypal_subscription_id=paypal_result["subscription_id"]
                )
                
                self.db.add(subscription)
                self.db.commit()
                
                return {
                    "success": True,
                    "subscription_id": subscription.id,
                    "requires_payment": True,
                    "approve_link": paypal_result["approve_link"],
                    "paypal_subscription_id": paypal_result["subscription_id"]
                }
            else:
                return {
                    "success": False,
                    "error": "Failed to create PayPal subscription",
                    "details": paypal_result["error"]
                }
                
        except Exception as e:
            return {
                "success": False,
                "error": f"Error creating subscription: {str(e)}"
            }
    
    async def activate_subscription(self, subscription_id: int, 
                                  paypal_subscription_data: Dict[str, Any]) -> Dict[str, Any]:
        """啟用訂閱（PayPal 確認後）"""
        
        subscription = self.db.query(UserSubscription).filter(
            UserSubscription.id == subscription_id
        ).first()
        
        if not subscription:
            return {
                "success": False,
                "error": "Subscription not found"
            }
        
        # 更新訂閱狀態
        subscription.status = "active"
        subscription.started_at = datetime.utcnow()
        subscription.current_period_start = datetime.utcnow()
        
        # 根據計費週期設定結束時間
        if subscription.billing_cycle == "yearly":
            subscription.current_period_end = datetime.utcnow() + timedelta(days=365)
            subscription.next_billing_date = datetime.utcnow() + timedelta(days=365)
        else:
            subscription.current_period_end = datetime.utcnow() + timedelta(days=30)
            subscription.next_billing_date = datetime.utcnow() + timedelta(days=30)
        
        subscription.updated_at = datetime.utcnow()
        
        # 更新使用者角色
        user = self.db.query(User).filter(User.id == subscription.user_id).first()
        if user:
            user.role = subscription.plan.name
            user.updated_at = datetime.utcnow()
        
        self.db.commit()
        
        return {
            "success": True,
            "message": "Subscription activated successfully"
        }
    
    async def cancel_subscription(self, user_id: int, reason: str = "User requested") -> Dict[str, Any]:
        """取消訂閱"""
        
        subscription = self.get_user_subscription(user_id)
        
        if not subscription:
            return {
                "success": False,
                "error": "No active subscription found"
            }
        
        try:
            # 如果有 PayPal 訂閱，先取消 PayPal 訂閱
            if subscription.paypal_subscription_id:
                paypal_result = await paypal_service.cancel_subscription(
                    subscription.paypal_subscription_id, reason
                )
                
                if not paypal_result["success"]:
                    return {
                        "success": False,
                        "error": "Failed to cancel PayPal subscription",
                        "details": paypal_result["error"]
                    }
            
            # 更新本地訂閱狀態
            subscription.status = "cancelled"
            subscription.cancelled_at = datetime.utcnow()
            subscription.updated_at = datetime.utcnow()
            
            # 設定到期時間（讓使用者用完當前週期）
            if not subscription.expires_at:
                subscription.expires_at = subscription.current_period_end
            
            # 將使用者降級為免費方案
            user = self.db.query(User).filter(User.id == user_id).first()
            if user:
                user.role = "free"
                user.updated_at = datetime.utcnow()
            
            self.db.commit()
            
            return {
                "success": True,
                "message": "Subscription cancelled successfully",
                "expires_at": subscription.expires_at
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": f"Error cancelling subscription: {str(e)}"
            }
    
    def validate_promo_code(self, code: str, user_id: int, plan_id: int) -> Dict[str, Any]:
        """驗證促銷代碼"""
        
        promo = self.db.query(PromoCode).filter(
            PromoCode.code == code.upper()
        ).first()
        
        if not promo:
            return {
                "valid": False,
                "error": "Promo code not found"
            }
        
        if not promo.is_valid():
            return {
                "valid": False,
                "error": "Promo code is expired or inactive"
            }
        
        # 檢查使用者是否已經使用過
        existing_redemption = self.db.query(PromoCodeRedemption).filter(
            PromoCodeRedemption.user_id == user_id,
            PromoCodeRedemption.promo_code_id == promo.id
        ).first()
        
        if existing_redemption:
            return {
                "valid": False,
                "error": "Promo code already used by this user"
            }
        
        # 檢查適用方案
        if promo.applicable_plans:
            applicable_plans = safe_json_loads(promo.applicable_plans, [])
            if plan_id not in applicable_plans:
                return {
                    "valid": False,
                    "error": "Promo code not applicable to this plan"
                }
        
        return {
            "valid": True,
            "promo_code": promo,
            "discount_type": promo.discount_type,
            "discount_value": promo.discount_value
        }
    
    def calculate_discount(self, original_amount: float, promo_code: PromoCode) -> Dict[str, Any]:
        """計算折扣金額"""
        
        if promo_code.discount_type == "percentage":
            discount_amount = original_amount * (promo_code.discount_value / 100)
        elif promo_code.discount_type == "fixed_amount":
            discount_amount = min(promo_code.discount_value, original_amount)
        else:
            discount_amount = 0
        
        final_amount = max(0, original_amount - discount_amount)
        
        return {
            "original_amount": original_amount,
            "discount_amount": discount_amount,
            "final_amount": final_amount,
            "discount_percentage": (discount_amount / original_amount * 100) if original_amount > 0 else 0
        }
    
    def get_subscription_analytics(self, user_id: int = None) -> Dict[str, Any]:
        """取得訂閱分析資料"""
        
        query = self.db.query(UserSubscription)
        if user_id:
            query = query.filter(UserSubscription.user_id == user_id)
        
        subscriptions = query.all()
        
        analytics = {
            "total_subscriptions": len(subscriptions),
            "active_subscriptions": len([s for s in subscriptions if s.status == "active"]),
            "cancelled_subscriptions": len([s for s in subscriptions if s.status == "cancelled"]),
            "by_plan": {},
            "by_billing_cycle": {},
            "revenue_data": {
                "monthly_recurring_revenue": 0,
                "annual_recurring_revenue": 0
            }
        }
        
        for subscription in subscriptions:
            # 按方案統計
            plan_name = subscription.plan.name
            if plan_name not in analytics["by_plan"]:
                analytics["by_plan"][plan_name] = 0
            analytics["by_plan"][plan_name] += 1
            
            # 按計費週期統計
            billing_cycle = subscription.billing_cycle
            if billing_cycle not in analytics["by_billing_cycle"]:
                analytics["by_billing_cycle"][billing_cycle] = 0
            analytics["by_billing_cycle"][billing_cycle] += 1
            
            # 收入統計（僅計算活躍訂閱）
            if subscription.status == "active":
                if subscription.billing_cycle == "monthly":
                    analytics["revenue_data"]["monthly_recurring_revenue"] += subscription.plan.price_monthly
                elif subscription.billing_cycle == "yearly":
                    analytics["revenue_data"]["annual_recurring_revenue"] += subscription.plan.price_yearly
        
        return analytics

# 全域訂閱服務實例
subscription_service = SubscriptionService()

