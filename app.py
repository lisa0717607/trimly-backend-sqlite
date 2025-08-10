import os, time, json
from datetime import datetime
from typing import Optional, Annotated

import jwt
from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from passlib.hash import bcrypt
from pydantic import BaseModel, EmailStr

from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session 

from models import init_db, SessionLocal, User 


# ---------------- Config ----------------
JWT_SECRET = os.environ.get("JWT_SECRET", "dev_secret_change_me")
ADMIN_EMAILS = {
    e.strip().lower()
    for e in os.environ.get("ADMIN_EMAILS", "").split(",")
    if e.strip()
}

# ---------------- App & OpenAPI ----------------
init_db()
app = FastAPI(title="Trimly API — Phase 0 (SQLite Clean Backend)", version="0.1.1")

def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description="Trimly backend API — clean SQLite build",
        routes=app.routes,
    )
    # Bearer 定義
    components = schema.setdefault("components", {})
    security_schemes = components.setdefault("securitySchemes", {})
    security_schemes["BearerAuth"] = {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "JWT",
    }
    # 讓所有路由預設套用 Bearer（Swagger 右上鎖頭 ）
    for path in schema.get("paths", {}).values():
        for op in path.values():
            op.setdefault("security", []).append({"BearerAuth": []})
    app.openapi_schema = schema
    return app.openapi_schema

app.openapi = custom_openapi

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------- Schemas ----------------
class RegisterBody(BaseModel):
    email: EmailStr
    password: str

class LoginBody(BaseModel):
    email: EmailStr
    password: str

# ---------------- Helpers ----------------
def get_db():
    """
    FastAPI Dependency to get a DB session.
    Ensures the session is closed after the request is finished.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def month_key_now():
    now = datetime.utcnow()
    return f"{now.year:04}-{now.month:02}"

def ensure_monthly_quota(user: User):
    """每月免費額度重置"""
    mk = month_key_now()
    if user.last_quota_reset_month != mk:
        user.free_quota_seconds_remaining = 1800
        user.last_quota_reset_month = mk

def create_token(user: User) -> str:
    payload = {
        "uid": user.id,
        "email": user.email,
        "is_admin": user.is_admin,
        "role": user.role,
        "exp": int(time.time()) + 60 * 60 * 24 * 14,  # 14 days
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")

# ====================================================================
#  ↓↓↓ 主要修改區域 ↓↓↓
# ====================================================================

# 把 Authorization 從 Swagger 參數隱藏（include_in_schema=False）
# Annotated 寫法在 FastAPI 0.95.0+ 成為主流
AuthDep = Annotated[Optional[str], Header(include_in_schema=False)]
DbDep = Annotated[Session, Depends(get_db)]

def current_user(db: DbDep, Authorization: AuthDep = None) -> User:
    """
    (修正後)
    這是一個 FastAPI 依賴項，用於驗證 JWT 並返回 User 物件。
    它依賴於 get_db，確保在同一個請求生命週期中使用同一個資料庫會話。
    """
    if not Authorization or not Authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing token")
    
    token = Authorization.split(" ", 1)[1].strip()
    
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        uid = payload.get("uid")
        if uid is None:
            raise HTTPException(status_code=401, detail="Invalid token payload")
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

    # 使用由 get_db 提供的、在整個請求中都有效的會話 `db`
    user = db.query(User).filter(User.id == uid).first()
    
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    
    # ensure_monthly_quota 會修改 user 物件，這會被 SQLAlchemy 追蹤
    ensure_monthly_quota(user)
    
    # 因為 get_db 的 try...finally 區塊會處理 commit/rollback 和 close，
    # 所以這裡通常不需要手動 db.commit()，除非您確定要立即寫入。
    # 讓修改保留在會話中，直到請求結束時由 get_db 處理即可。
    # 如果 ensure_monthly_quota 確實需要立即寫入，可以保留 commit。
    db.commit()
    
    return user

# ====================================================================
#  ↑↑↑ 主要修改區域 ↑↑↑
# ====================================================================

def admin_only(user: Annotated[User, Depends(current_user)]):
    if not user.is_admin:
        raise HTTPException(403, "Admin only")

# ---------------- Auth ----------------
@app.post("/auth/register")
def register(body: RegisterBody, db: DbDep): # <-- 注入 db
    email_norm = body.email.strip().lower()
    if db.query(User).filter(User.email_norm == email_norm).first():
        raise HTTPException(400, "Email already registered")
    u = User(
        email=body.email,
        email_norm=email_norm,
        password_hash=bcrypt.hash(body.password),
        is_admin=(email_norm in ADMIN_EMAILS),
        role="free",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    ensure_monthly_quota(u)
    db.add(u); db.commit(); db.refresh(u)
    token = create_token(u)
    return {"token": token, "user": {"email": u.email, "is_admin": u.is_admin, "role": u.role}}

@app.post("/auth/login")
def login(body: LoginBody, db: DbDep): # <-- 注入 db
    email_norm = body.email.strip().lower()
    u = db.query(User).filter(User.email_norm == email_norm).first()
    if not u or not bcrypt.verify(body.password, u.password_hash):
        raise HTTPException(401, "Invalid credentials")
    should_admin = (email_norm in ADMIN_EMAILS)
    if u.is_admin != should_admin:
        u.is_admin = should_admin
        db.commit()
    token = create_token(u)
    return {"token": token, "user": {"email": u.email, "is_admin": u.is_admin, "role": u.role}}

# ---------------- API ----------------
@app.get("/me")
def me(user: Annotated[User, Depends(current_user)]): # <-- 使用 Annotated 讓語法更清晰
    # 現在 user 物件是附加到一個有效會話上的，可以安全存取所有屬性
    return {
        "email": user.email,
        "role": user.role,
        "is_admin": user.is_admin,
        "minutes_balance_seconds": user.minutes_balance_seconds or 0,
        "free_quota_seconds_remaining": user.free_quota_seconds_remaining or 0,
        "last_quota_reset_month": user.last_quota_reset_month or "",
    }

@app.get("/api/health")
def health():
    return {"ok": True, "version": app.version}

# ---------------- Debug（可用後移除） ----------------
@app.get("/debug/echo_auth")
def debug_echo_auth(Authorization: Annotated[Optional[str], Header()] = None):
    return {"authorization": Authorization}

@app.get("/debug/decode")
def debug_decode(db: DbDep, Authorization: AuthDep = None): # <-- 注入 db
    if not Authorization or not Authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Missing token")
    token = Authorization.split(" ", 1)[1].strip()
    try:
        data = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except Exception as e:
        print(f"[DEBUG][JWT ERROR] {str(e)}")
        raise HTTPException(401, f"JWT decode error: {str(e)}")

    user = db.query(User).filter(User.id == data.get("uid")).first()
    return {
        "decoded": data,
        "db_user": None if not user else {
            "id": user.id,
            "email": user.email,
            "is_admin": user.is_admin,
            "role": user.role
        }
    }
