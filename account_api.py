from fastapi import APIRouter, Depends, HTTPException, status, Response
from sqlalchemy.orm import Session
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, EmailStr

from models_extended import User, get_db
from auth import get_current_user, get_current_admin_user
from account_management import account_service
from utils import safe_json_loads, safe_json_dumps

# 建立路由器
router = APIRouter(prefix="/api/v1/account", tags=["Account Management"])

# Pydantic 模型
class UserProfileResponse(BaseModel):
    user: Dict[str, Any]
    subscription: Dict[str, Any]
    usage: Dict[str, Any]
    statistics: Dict[str, Any]

class UpdateProfileRequest(BaseModel):
    email: Optional[EmailStr] = None

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

class DeleteAccountRequest(BaseModel):
    password: str

# ==================== 個人資料管理 API ====================

@router.get("/profile", response_model=UserProfileResponse)
async def get_user_profile(
    current_user = Depends(get_current_user)
):
    """取得使用者個人資料"""
    
    profile_data = account_service.get_user_profile(current_user.id)
    
    if "error" in profile_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=profile_data["error"]
        )
    
    return profile_data

@router.put("/profile")
async def update_user_profile(
    request: UpdateProfileRequest,
    current_user = Depends(get_current_user)
):
    """更新使用者個人資料"""
    
    update_data = {}
    if request.email:
        update_data["email"] = request.email
    
    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No data provided for update"
        )
    
    result = account_service.update_user_profile(current_user.id, update_data)
    
    if result["success"]:
        return {"message": result["message"]}
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result["error"]
        )

@router.post("/change-password")
async def change_password(
    request: ChangePasswordRequest,
    current_user = Depends(get_current_user)
):
    """更改密碼"""
    
    result = account_service.change_password(
        current_user.id, 
        request.current_password, 
        request.new_password
    )
    
    if result["success"]:
        return {"message": result["message"]}
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result["error"]
        )

# ==================== 帳單和發票 API ====================

@router.get("/billing/history")
async def get_billing_history(
    limit: int = 50,
    current_user = Depends(get_current_user)
):
    """取得帳單歷史"""
    
    if limit > 100:
        limit = 100  # 限制最大查詢數量
    
    billing_history = account_service.get_billing_history(current_user.id, limit)
    
    return {
        "billing_history": billing_history,
        "total_records": len(billing_history)
    }

@router.get("/billing/invoices")
async def get_invoices(
    limit: int = 50,
    current_user = Depends(get_current_user)
):
    """取得發票列表"""
    
    if limit > 100:
        limit = 100  # 限制最大查詢數量
    
    invoices = account_service.get_invoices(current_user.id, limit)
    
    return {
        "invoices": invoices,
        "total_records": len(invoices)
    }

@router.get("/billing/invoices/{invoice_id}/download")
async def download_invoice(
    invoice_id: int,
    current_user = Depends(get_current_user)
):
    """下載發票"""
    
    result = account_service.download_invoice(current_user.id, invoice_id)
    
    if result["success"]:
        # 在實際應用中，這裡應該返回 PDF 檔案
        # 現在返回 JSON 資料
        return result["invoice"]
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=result["error"]
        )

# ==================== 使用分析 API ====================

@router.get("/analytics/usage")
async def get_usage_analytics(
    months: int = 6,
    current_user = Depends(get_current_user)
):
    """取得使用分析資料"""
    
    if months > 24:
        months = 24  # 限制最大查詢月數
    
    analytics = account_service.get_usage_analytics(current_user.id, months)
    
    return analytics

@router.get("/analytics/summary")
async def get_account_summary(
    current_user = Depends(get_current_user)
):
    """取得帳戶摘要資訊"""
    
    profile_data = account_service.get_user_profile(current_user.id)
    
    if "error" in profile_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=profile_data["error"]
        )
    
    # 提取關鍵摘要資訊
    summary = {
        "account_status": {
            "plan": profile_data["subscription"]["plan_display_name"],
            "status": profile_data["subscription"]["status"],
            "next_billing": profile_data["subscription"]["next_billing_date"],
            "expires_at": profile_data["subscription"]["expires_at"]
        },
        "current_usage": {
            "transcription": {
                "used": profile_data["usage"]["transcription_minutes_used"],
                "limit": profile_data["usage"]["transcription_minutes_limit"],
                "percentage": round(
                    (profile_data["usage"]["transcription_minutes_used"] / 
                     profile_data["usage"]["transcription_minutes_limit"]) * 100, 1
                ) if profile_data["usage"]["transcription_minutes_limit"] > 0 else 0
            },
            "ai_enhancements": {
                "used": profile_data["usage"]["ai_enhancements_used"],
                "limit": profile_data["usage"]["ai_enhancements_limit"],
                "percentage": round(
                    (profile_data["usage"]["ai_enhancements_used"] / 
                     profile_data["usage"]["ai_enhancements_limit"]) * 100, 1
                ) if profile_data["usage"]["ai_enhancements_limit"] > 0 else 0
            },
            "ai_summaries": {
                "used": profile_data["usage"]["ai_summaries_used"],
                "limit": profile_data["usage"]["ai_summaries_limit"],
                "percentage": round(
                    (profile_data["usage"]["ai_summaries_used"] / 
                     profile_data["usage"]["ai_summaries_limit"]) * 100, 1
                ) if profile_data["usage"]["ai_summaries_limit"] > 0 else 0
            },
            "storage": {
                "used": profile_data["usage"]["storage_gb_used"],
                "limit": profile_data["usage"]["storage_gb_limit"],
                "percentage": round(
                    (profile_data["usage"]["storage_gb_used"] / 
                     profile_data["usage"]["storage_gb_limit"]) * 100, 1
                ) if profile_data["usage"]["storage_gb_limit"] > 0 else 0
            }
        },
        "account_info": {
            "total_projects": profile_data["statistics"]["total_projects"],
            "account_age_days": profile_data["statistics"]["account_age_days"],
            "member_since": profile_data["user"]["created_at"]
        }
    }
    
    return summary

# ==================== 資料匯出和帳戶刪除 API ====================

@router.get("/export")
async def export_user_data(
    current_user = Depends(get_current_user)
):
    """匯出使用者資料（GDPR 合規）"""
    
    result = account_service.export_user_data(current_user.id)
    
    if result["success"]:
        # 在實際應用中，這裡應該生成檔案並提供下載連結
        # 現在直接返回資料
        return {
            "message": "User data exported successfully",
            "export_date": result["data"]["export_date"],
            "data": result["data"]
        }
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=result["error"]
        )

@router.delete("/delete")
async def delete_account(
    request: DeleteAccountRequest,
    current_user = Depends(get_current_user)
):
    """刪除帳戶"""
    
    result = account_service.delete_account(current_user.id, request.password)
    
    if result["success"]:
        return {"message": result["message"]}
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result["error"]
        )

# ==================== 通知和偏好設定 API ====================

@router.get("/notifications/settings")
async def get_notification_settings(
    current_user = Depends(get_current_user)
):
    """取得通知設定"""
    
    # 這裡應該從資料庫讀取使用者的通知偏好
    # 為了簡化，返回預設設定
    return {
        "email_notifications": {
            "billing_reminders": True,
            "usage_alerts": True,
            "feature_updates": False,
            "marketing": False
        },
        "usage_alerts": {
            "quota_warning_threshold": 80,  # 當使用量達到 80% 時警告
            "quota_critical_threshold": 95  # 當使用量達到 95% 時緊急警告
        }
    }

@router.put("/notifications/settings")
async def update_notification_settings(
    settings: Dict[str, Any],
    current_user = Depends(get_current_user)
):
    """更新通知設定"""
    
    # 這裡應該將設定儲存到資料庫
    # 為了簡化，直接返回成功
    return {
        "message": "Notification settings updated successfully",
        "settings": settings
    }

# ==================== API 金鑰管理 API ====================

@router.get("/api-keys")
async def get_api_keys(
    current_user = Depends(get_current_user)
):
    """取得 API 金鑰列表"""
    
    # 檢查使用者是否有 API 存取權限
    from subscription_service import subscription_service
    plan = subscription_service.get_user_plan(current_user.id)
    
    if not plan.api_access:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="API access not available in your current plan"
        )
    
    # 這裡應該從資料庫讀取 API 金鑰
    # 為了簡化，返回空列表
    return {
        "api_keys": [],
        "max_keys": 5,
        "api_access_enabled": True
    }

@router.post("/api-keys")
async def create_api_key(
    name: str,
    current_user = Depends(get_current_user)
):
    """建立新的 API 金鑰"""
    
    # 檢查使用者是否有 API 存取權限
    from subscription_service import subscription_service
    plan = subscription_service.get_user_plan(current_user.id)
    
    if not plan.api_access:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="API access not available in your current plan"
        )
    
    # 這裡應該生成新的 API 金鑰並儲存到資料庫
    # 為了簡化，返回模擬資料
    import secrets
    api_key = f"trimly_{secrets.token_urlsafe(32)}"
    
    return {
        "message": "API key created successfully",
        "api_key": api_key,
        "name": name,
        "created_at": datetime.utcnow().isoformat(),
        "warning": "Please save this API key securely. It will not be shown again."
    }

@router.delete("/api-keys/{key_id}")
async def delete_api_key(
    key_id: int,
    current_user = Depends(get_current_user)
):
    """刪除 API 金鑰"""
    
    # 這裡應該從資料庫刪除 API 金鑰
    # 為了簡化，直接返回成功
    return {
        "message": "API key deleted successfully"
    }

