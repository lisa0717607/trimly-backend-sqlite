from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from sqlalchemy.orm import Session
from passlib.context import CryptContext

from models_extended import User, SessionLocal
from subscription_models import UserSubscription, Payment, Invoice
from subscription_service import subscription_service
from utils import safe_json_loads, safe_json_dumps

# 密碼加密
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

class AccountManagementService:
    """帳戶管理服務"""
    
    def __init__(self):
        self.db = SessionLocal()
    
    def get_user_profile(self, user_id: int) -> Dict[str, Any]:
        """取得使用者個人資料"""
        
        user = self.db.query(User).filter(User.id == user_id).first()
        if not user:
            return {"error": "User not found"}
        
        # 取得訂閱資訊
        subscription = subscription_service.get_user_subscription(user_id)
        plan = subscription_service.get_user_plan(user_id)
        quota = subscription_service.get_usage_quota(user_id)
        
        # 計算帳戶統計
        total_projects = self.db.query(Project).filter(Project.user_id == user_id).count()
        
        return {
            "user": {
                "id": user.id,
                "email": user.email,
                "role": user.role,
                "is_admin": user.is_admin,
                "created_at": user.created_at,
                "updated_at": user.updated_at
            },
            "subscription": {
                "plan_name": plan.name,
                "plan_display_name": plan.display_name,
                "status": subscription.status if subscription else "free",
                "billing_cycle": subscription.billing_cycle if subscription else None,
                "next_billing_date": subscription.next_billing_date if subscription else None,
                "expires_at": subscription.expires_at if subscription else None
            },
            "usage": {
                "transcription_minutes_used": quota.transcription_minutes_used,
                "transcription_minutes_limit": plan.transcription_minutes_monthly,
                "ai_enhancements_used": quota.ai_enhancements_used,
                "ai_enhancements_limit": plan.ai_enhancements_monthly,
                "ai_summaries_used": quota.ai_summaries_used,
                "ai_summaries_limit": plan.ai_summaries_monthly,
                "storage_gb_used": quota.storage_gb_used,
                "storage_gb_limit": plan.storage_gb
            },
            "statistics": {
                "total_projects": total_projects,
                "account_age_days": (datetime.utcnow() - user.created_at).days
            }
        }
    
    def update_user_profile(self, user_id: int, update_data: Dict[str, Any]) -> Dict[str, Any]:
        """更新使用者個人資料"""
        
        user = self.db.query(User).filter(User.id == user_id).first()
        if not user:
            return {"success": False, "error": "User not found"}
        
        # 允許更新的欄位
        allowed_fields = ["email"]
        
        for field, value in update_data.items():
            if field in allowed_fields and hasattr(user, field):
                if field == "email":
                    # 檢查 email 是否已被使用
                    existing_user = self.db.query(User).filter(
                        User.email_norm == value.lower(),
                        User.id != user_id
                    ).first()
                    
                    if existing_user:
                        return {"success": False, "error": "Email already in use"}
                    
                    user.email = value
                    user.email_norm = value.lower()
                else:
                    setattr(user, field, value)
        
        user.updated_at = datetime.utcnow()
        self.db.commit()
        
        return {"success": True, "message": "Profile updated successfully"}
    
    def change_password(self, user_id: int, current_password: str, new_password: str) -> Dict[str, Any]:
        """更改密碼"""
        
        user = self.db.query(User).filter(User.id == user_id).first()
        if not user:
            return {"success": False, "error": "User not found"}
        
        # 驗證當前密碼
        if not pwd_context.verify(current_password, user.password_hash):
            return {"success": False, "error": "Current password is incorrect"}
        
        # 驗證新密碼強度
        if len(new_password) < 8:
            return {"success": False, "error": "New password must be at least 8 characters long"}
        
        # 更新密碼
        user.password_hash = pwd_context.hash(new_password)
        user.updated_at = datetime.utcnow()
        self.db.commit()
        
        return {"success": True, "message": "Password changed successfully"}
    
    def get_billing_history(self, user_id: int, limit: int = 50) -> List[Dict[str, Any]]:
        """取得帳單歷史"""
        
        payments = self.db.query(Payment).filter(
            Payment.user_id == user_id
        ).order_by(Payment.created_at.desc()).limit(limit).all()
        
        billing_history = []
        for payment in payments:
            billing_history.append({
                "id": payment.id,
                "amount": payment.amount,
                "currency": payment.currency,
                "status": payment.status,
                "description": payment.description,
                "billing_period": payment.billing_period,
                "paid_at": payment.paid_at,
                "created_at": payment.created_at,
                "paypal_payment_id": payment.paypal_payment_id
            })
        
        return billing_history
    
    def get_invoices(self, user_id: int, limit: int = 50) -> List[Dict[str, Any]]:
        """取得發票列表"""
        
        invoices = self.db.query(Invoice).filter(
            Invoice.user_id == user_id
        ).order_by(Invoice.created_at.desc()).limit(limit).all()
        
        invoice_list = []
        for invoice in invoices:
            invoice_list.append({
                "id": invoice.id,
                "invoice_number": invoice.invoice_number,
                "amount": invoice.amount,
                "tax_amount": invoice.tax_amount,
                "total_amount": invoice.total_amount,
                "currency": invoice.currency,
                "status": invoice.status,
                "issue_date": invoice.issue_date,
                "due_date": invoice.due_date,
                "paid_date": invoice.paid_date,
                "description": invoice.description
            })
        
        return invoice_list
    
    def download_invoice(self, user_id: int, invoice_id: int) -> Dict[str, Any]:
        """下載發票"""
        
        invoice = self.db.query(Invoice).filter(
            Invoice.id == invoice_id,
            Invoice.user_id == user_id
        ).first()
        
        if not invoice:
            return {"success": False, "error": "Invoice not found"}
        
        # 這裡應該生成 PDF 發票
        # 為了簡化，返回發票資料
        return {
            "success": True,
            "invoice": {
                "invoice_number": invoice.invoice_number,
                "amount": invoice.amount,
                "tax_amount": invoice.tax_amount,
                "total_amount": invoice.total_amount,
                "currency": invoice.currency,
                "status": invoice.status,
                "issue_date": invoice.issue_date,
                "due_date": invoice.due_date,
                "paid_date": invoice.paid_date,
                "description": invoice.description,
                "billing_address": invoice.billing_address
            }
        }
    
    def get_usage_analytics(self, user_id: int, months: int = 6) -> Dict[str, Any]:
        """取得使用分析資料"""
        
        # 取得過去幾個月的配額資料
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=months * 30)
        
        monthly_usage = []
        current_date = start_date.replace(day=1)
        
        while current_date <= end_date:
            month_str = current_date.strftime("%Y-%m")
            quota = subscription_service.get_usage_quota(user_id, month_str)
            plan = subscription_service.get_user_plan(user_id)
            
            monthly_usage.append({
                "month": month_str,
                "transcription_minutes": quota.transcription_minutes_used,
                "ai_enhancements": quota.ai_enhancements_used,
                "ai_summaries": quota.ai_summaries_used,
                "storage_gb": quota.storage_gb_used,
                "limits": {
                    "transcription_minutes": plan.transcription_minutes_monthly,
                    "ai_enhancements": plan.ai_enhancements_monthly,
                    "ai_summaries": plan.ai_summaries_monthly,
                    "storage_gb": plan.storage_gb
                }
            })
            
            # 移到下個月
            if current_date.month == 12:
                current_date = current_date.replace(year=current_date.year + 1, month=1)
            else:
                current_date = current_date.replace(month=current_date.month + 1)
        
        # 計算總計
        total_usage = {
            "transcription_minutes": sum(m["transcription_minutes"] for m in monthly_usage),
            "ai_enhancements": sum(m["ai_enhancements"] for m in monthly_usage),
            "ai_summaries": sum(m["ai_summaries"] for m in monthly_usage),
            "storage_gb": max(m["storage_gb"] for m in monthly_usage) if monthly_usage else 0
        }
        
        return {
            "monthly_usage": monthly_usage,
            "total_usage": total_usage,
            "analysis_period": {
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "months": months
            }
        }
    
    def delete_account(self, user_id: int, password: str) -> Dict[str, Any]:
        """刪除帳戶"""
        
        user = self.db.query(User).filter(User.id == user_id).first()
        if not user:
            return {"success": False, "error": "User not found"}
        
        # 驗證密碼
        if not pwd_context.verify(password, user.password_hash):
            return {"success": False, "error": "Password is incorrect"}
        
        try:
            # 取消所有活躍訂閱
            subscription = subscription_service.get_user_subscription(user_id)
            if subscription:
                subscription_service.cancel_subscription(
                    user_id, "Account deletion requested"
                )
            
            # 刪除使用者相關資料
            # 注意：在實際應用中，可能需要保留某些資料以符合法規要求
            
            # 刪除專案和相關檔案
            projects = self.db.query(Project).filter(Project.user_id == user_id).all()
            for project in projects:
                # 這裡應該刪除相關的音訊檔案
                self.db.delete(project)
            
            # 刪除配額記錄
            quotas = self.db.query(UsageQuota).filter(UsageQuota.user_id == user_id).all()
            for quota in quotas:
                self.db.delete(quota)
            
            # 刪除支付記錄（可能需要保留以符合法規）
            # payments = self.db.query(Payment).filter(Payment.user_id == user_id).all()
            # for payment in payments:
            #     self.db.delete(payment)
            
            # 最後刪除使用者
            self.db.delete(user)
            self.db.commit()
            
            return {"success": True, "message": "Account deleted successfully"}
            
        except Exception as e:
            self.db.rollback()
            return {"success": False, "error": f"Error deleting account: {str(e)}"}
    
    def export_user_data(self, user_id: int) -> Dict[str, Any]:
        """匯出使用者資料（GDPR 合規）"""
        
        user = self.db.query(User).filter(User.id == user_id).first()
        if not user:
            return {"success": False, "error": "User not found"}
        
        # 收集所有使用者資料
        profile_data = self.get_user_profile(user_id)
        billing_history = self.get_billing_history(user_id, limit=1000)
        invoices = self.get_invoices(user_id, limit=1000)
        usage_analytics = self.get_usage_analytics(user_id, months=24)
        
        # 取得專案資料
        projects = self.db.query(Project).filter(Project.user_id == user_id).all()
        projects_data = []
        for project in projects:
            projects_data.append({
                "id": project.id,
                "name": project.name,
                "description": project.description,
                "created_at": project.created_at.isoformat(),
                "updated_at": project.updated_at.isoformat()
            })
        
        export_data = {
            "export_date": datetime.utcnow().isoformat(),
            "user_profile": profile_data,
            "projects": projects_data,
            "billing_history": billing_history,
            "invoices": invoices,
            "usage_analytics": usage_analytics
        }
        
        return {
            "success": True,
            "data": export_data,
            "format": "json"
        }

# 全域帳戶管理服務實例
account_service = AccountManagementService()

