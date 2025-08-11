from datetime import datetime, timedelta
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Float, Text, ForeignKey
from sqlalchemy.orm import relationship
from models_extended import Base

class SubscriptionPlan(Base):
    """訂閱方案"""
    __tablename__ = "subscription_plans"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)  # free, starter, professional, creator
    display_name = Column(String, nullable=False)  # 免費版, 入門版, 專業版, 創作者版
    price_monthly = Column(Float, default=0.0)  # 月費
    price_yearly = Column(Float, default=0.0)   # 年費
    
    # 功能限制
    transcription_minutes_monthly = Column(Integer, default=30)  # 每月轉錄分鐘數
    ai_enhancements_monthly = Column(Integer, default=5)        # 每月 AI 增強次數
    ai_summaries_monthly = Column(Integer, default=10)          # 每月 AI 摘要次數
    projects_limit = Column(Integer, default=3)                # 專案數量限制
    version_history_limit = Column(Integer, default=3)         # 版本歷史限制
    storage_gb = Column(Float, default=1.0)                    # 儲存空間 GB
    
    # 功能開關
    advanced_ai_features = Column(Boolean, default=False)      # 進階 AI 功能
    priority_processing = Column(Boolean, default=False)       # 優先處理
    api_access = Column(Boolean, default=False)               # API 存取
    white_label = Column(Boolean, default=False)              # 白標服務
    
    # 系統欄位
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
    
    # 關聯
    subscriptions = relationship("UserSubscription", back_populates="plan")

class UserSubscription(Base):
    """使用者訂閱"""
    __tablename__ = "user_subscriptions"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    plan_id = Column(Integer, ForeignKey("subscription_plans.id"), nullable=False)
    
    # 訂閱狀態
    status = Column(String, default="active")  # active, cancelled, expired, suspended
    billing_cycle = Column(String, default="monthly")  # monthly, yearly
    
    # 時間資訊
    started_at = Column(DateTime, default=datetime.utcnow)
    current_period_start = Column(DateTime, default=datetime.utcnow)
    current_period_end = Column(DateTime)
    cancelled_at = Column(DateTime)
    expires_at = Column(DateTime)
    
    # 支付資訊
    paypal_subscription_id = Column(String)  # PayPal 訂閱 ID
    next_billing_date = Column(DateTime)
    
    # 系統欄位
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
    
    # 關聯
    plan = relationship("SubscriptionPlan", back_populates="subscriptions")
    payments = relationship("Payment", back_populates="subscription")
    
    def is_active(self):
        """檢查訂閱是否有效"""
        if self.status != "active":
            return False
        
        if self.expires_at and self.expires_at < datetime.utcnow():
            return False
            
        return True
    
    def days_until_renewal(self):
        """距離下次續費的天數"""
        if not self.next_billing_date:
            return None
        
        delta = self.next_billing_date - datetime.utcnow()
        return max(0, delta.days)

class Payment(Base):
    """支付記錄"""
    __tablename__ = "payments"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    subscription_id = Column(Integer, ForeignKey("user_subscriptions.id"))
    
    # 支付資訊
    paypal_payment_id = Column(String)  # PayPal 支付 ID
    paypal_order_id = Column(String)    # PayPal 訂單 ID
    amount = Column(Float, nullable=False)
    currency = Column(String, default="USD")
    
    # 支付狀態
    status = Column(String, default="pending")  # pending, completed, failed, refunded
    payment_method = Column(String, default="paypal")
    
    # 支付詳情
    description = Column(String)
    billing_period = Column(String)  # 對應的計費週期
    
    # 時間資訊
    paid_at = Column(DateTime)
    failed_at = Column(DateTime)
    refunded_at = Column(DateTime)
    
    # 系統欄位
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
    
    # 關聯
    subscription = relationship("UserSubscription", back_populates="payments")

class UsageQuota(Base):
    """使用配額追蹤"""
    __tablename__ = "usage_quotas"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    # 配額週期
    quota_month = Column(String, nullable=False)  # YYYY-MM 格式
    
    # 使用量統計
    transcription_minutes_used = Column(Float, default=0.0)
    ai_enhancements_used = Column(Integer, default=0)
    ai_summaries_used = Column(Integer, default=0)
    storage_gb_used = Column(Float, default=0.0)
    
    # 系統欄位
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f"<UsageQuota(user_id={self.user_id}, month={self.quota_month})>"

class PromoCode(Base):
    """促銷代碼"""
    __tablename__ = "promo_codes"
    
    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, unique=True, nullable=False)
    
    # 折扣資訊
    discount_type = Column(String, nullable=False)  # percentage, fixed_amount, free_trial
    discount_value = Column(Float, nullable=False)  # 折扣值
    
    # 適用範圍
    applicable_plans = Column(String)  # JSON 格式，適用的方案 ID 列表
    min_amount = Column(Float, default=0.0)  # 最低消費金額
    
    # 使用限制
    max_uses = Column(Integer)  # 最大使用次數
    max_uses_per_user = Column(Integer, default=1)  # 每個使用者最大使用次數
    current_uses = Column(Integer, default=0)  # 目前使用次數
    
    # 時間限制
    valid_from = Column(DateTime, default=datetime.utcnow)
    valid_until = Column(DateTime)
    
    # 系統欄位
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
    
    # 關聯
    redemptions = relationship("PromoCodeRedemption", back_populates="promo_code")
    
    def is_valid(self):
        """檢查促銷代碼是否有效"""
        if not self.is_active:
            return False
        
        now = datetime.utcnow()
        if self.valid_from and now < self.valid_from:
            return False
        
        if self.valid_until and now > self.valid_until:
            return False
        
        if self.max_uses and self.current_uses >= self.max_uses:
            return False
        
        return True

class PromoCodeRedemption(Base):
    """促銷代碼使用記錄"""
    __tablename__ = "promo_code_redemptions"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    promo_code_id = Column(Integer, ForeignKey("promo_codes.id"), nullable=False)
    payment_id = Column(Integer, ForeignKey("payments.id"))
    
    # 折扣資訊
    discount_amount = Column(Float, nullable=False)
    original_amount = Column(Float, nullable=False)
    final_amount = Column(Float, nullable=False)
    
    # 系統欄位
    redeemed_at = Column(DateTime, default=datetime.utcnow)
    
    # 關聯
    promo_code = relationship("PromoCode", back_populates="redemptions")

class Invoice(Base):
    """發票記錄"""
    __tablename__ = "invoices"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    payment_id = Column(Integer, ForeignKey("payments.id"))
    
    # 發票資訊
    invoice_number = Column(String, unique=True, nullable=False)
    amount = Column(Float, nullable=False)
    currency = Column(String, default="USD")
    tax_amount = Column(Float, default=0.0)
    total_amount = Column(Float, nullable=False)
    
    # 發票狀態
    status = Column(String, default="draft")  # draft, sent, paid, overdue, cancelled
    
    # 時間資訊
    issue_date = Column(DateTime, default=datetime.utcnow)
    due_date = Column(DateTime)
    paid_date = Column(DateTime)
    
    # 發票內容
    description = Column(Text)
    billing_address = Column(Text)
    
    # 系統欄位
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

# 預設訂閱方案資料
DEFAULT_SUBSCRIPTION_PLANS = [
    {
        "name": "free",
        "display_name": "免費版",
        "price_monthly": 0.0,
        "price_yearly": 0.0,
        "transcription_minutes_monthly": 30,
        "ai_enhancements_monthly": 2,
        "ai_summaries_monthly": 5,
        "projects_limit": 3,
        "version_history_limit": 3,
        "storage_gb": 1.0,
        "advanced_ai_features": False,
        "priority_processing": False,
        "api_access": False,
        "white_label": False
    },
    {
        "name": "starter",
        "display_name": "入門版",
        "price_monthly": 10.0,
        "price_yearly": 100.0,
        "transcription_minutes_monthly": 120,
        "ai_enhancements_monthly": 10,
        "ai_summaries_monthly": 25,
        "projects_limit": 10,
        "version_history_limit": 10,
        "storage_gb": 5.0,
        "advanced_ai_features": True,
        "priority_processing": False,
        "api_access": False,
        "white_label": False
    },
    {
        "name": "professional",
        "display_name": "專業版",
        "price_monthly": 20.0,
        "price_yearly": 200.0,
        "transcription_minutes_monthly": 300,
        "ai_enhancements_monthly": 25,
        "ai_summaries_monthly": 60,
        "projects_limit": 50,
        "version_history_limit": 30,
        "storage_gb": 15.0,
        "advanced_ai_features": True,
        "priority_processing": True,
        "api_access": True,
        "white_label": False
    },
    {
        "name": "creator",
        "display_name": "創作者版",
        "price_monthly": 30.0,
        "price_yearly": 300.0,
        "transcription_minutes_monthly": 600,
        "ai_enhancements_monthly": 50,
        "ai_summaries_monthly": 120,
        "projects_limit": 100,
        "version_history_limit": 50,
        "storage_gb": 50.0,
        "advanced_ai_features": True,
        "priority_processing": True,
        "api_access": True,
        "white_label": True
    }
]

