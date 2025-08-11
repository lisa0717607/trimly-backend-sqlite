from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from typing import Optional
import os

from models_extended import User, get_db
from utils import verify_token, normalize_email

security = HTTPBearer()

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> User:
    """取得當前登入使用者"""
    
    # 驗證 token
    payload = verify_token(credentials.credentials)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # 取得使用者 email
    email: str = payload.get("sub")
    if email is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # 從資料庫查詢使用者
    user = db.query(User).filter(User.email_norm == normalize_email(email)).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return user

def get_current_admin_user(current_user: User = Depends(get_current_user)) -> User:
    """取得當前管理員使用者"""
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions"
        )
    return current_user

def check_admin_emails(email: str) -> bool:
    """檢查是否為管理員 email"""
    admin_emails = os.environ.get("ADMIN_EMAILS", "").split(",")
    admin_emails = [email.strip().lower() for email in admin_emails if email.strip()]
    return normalize_email(email) in admin_emails

def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db)
) -> Optional[User]:
    """取得可選的當前使用者（用於公開端點）"""
    if credentials is None:
        return None
    
    try:
        return get_current_user(credentials, db)
    except HTTPException:
        return None

class PermissionChecker:
    """權限檢查器"""
    
    def __init__(self, required_role: Optional[str] = None, admin_only: bool = False):
        self.required_role = required_role
        self.admin_only = admin_only
    
    def __call__(self, current_user: User = Depends(get_current_user)) -> User:
        if self.admin_only and not current_user.is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin access required"
            )
        
        if self.required_role:
            role_hierarchy = ["free", "starter", "pro", "creator"]
            user_level = role_hierarchy.index(current_user.role) if current_user.role in role_hierarchy else 0
            required_level = role_hierarchy.index(self.required_role) if self.required_role in role_hierarchy else 0
            
            if user_level < required_level:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Subscription level '{self.required_role}' or higher required"
                )
        
        return current_user

# 預定義的權限檢查器
require_admin = PermissionChecker(admin_only=True)
require_starter = PermissionChecker(required_role="starter")
require_pro = PermissionChecker(required_role="pro")
require_creator = PermissionChecker(required_role="creator")

