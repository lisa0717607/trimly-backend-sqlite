import os, time, json
from datetime import datetime, timedelta
from typing import Optional, Annotated

import jwt
from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from passlib.hash import bcrypt
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
from sqlalchemy import func
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
app = FastAPI(title="Trimly API — Phase 0 (SQLite Clean Backend)", version="0.1.2") # 版本號微調

def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description="Trimly backend API — clean SQLite build",
        routes=app.routes,
    )
    components = schema.setdefault("components", {})
    security_schemes = components.setdefault("securitySchemes", {})
    security_schemes["BearerAuth"] = {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "JWT",
    }
    for path in schema.get("paths", {} ).values():
        for op in path.values():
            op.setdefault("security", []).append({"BearerAuth": []})
    app.openapi_schema = schema
    return app.openapi_schema

app.openapi = custom_openapi

# CORS

origins = [
    "http://localhost",
    "http://localhost:3000",
    "http://localhost:5173",
    "https://trimly-frontend.onrender.com", # 假設的線上前端網域
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins, # <--- 使用我們定義的白名單
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
    
class ProcessTextBody(BaseModel):
    text: str


# ---------------- Helpers ----------------
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def month_key_now():
    now = datetime.utcnow()
    return f"{now.year:04}-{now.month:02}"

def ensure_monthly_quota(user: User):
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

AuthDep = Annotated[Optional[str], Header(include_in_schema=False)]
DbDep = Annotated[Session, Depends(get_db)]

def current_user(db: DbDep, Authorization: AuthDep = None) -> User:
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

    user = db.query(User).filter(User.id == uid).first()
    
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    
    ensure_monthly_quota(user)
    db.commit()
    
    return user

def admin_only(user: Annotated[User, Depends(current_user)]):
    """
    這是一個依賴項，它本身又依賴於 current_user。
    它會先確保使用者已登入，然後再檢查該使用者是否為管理員。
    如果不是管理員，會拋出 403 Forbidden 錯誤。
    """
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user

# ---------------- Auth ----------------
@app.post("/auth/register")
def register(body: RegisterBody, db: DbDep):
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
def login(body: LoginBody, db: DbDep):
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
def me(user: Annotated[User, Depends(current_user)]):
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
    return {"ok": True, "version": app.version, "deployment_version": "v2-with-deduction"}


# ====================================================================
#  ↓↓↓ 新增的管理員專用路由 ↓↓↓
# ====================================================================
@app.get("/admin/ping", tags=["Admin"])
def admin_ping(admin_user: Annotated[User, Depends(admin_only)]):
    """
    一個僅限管理員存取的測試端點。
    如果請求者不是管理員，將會收到 403 Forbidden 錯誤。
    可以用來快速驗證一個 Token 是否具有管理員權限。
    """
    return {"message": f"Pong! Hello admin {admin_user.email}."}

# ====================================================================
#  ↑↑↑ Debug 路由已被移除 ↑↑↑
# ====================================================================
# ================================================
#                Admin Panel APIs
# ================================================

@app.get("/admin/users")
def admin_list_users(
    user: User = Depends(current_user),
    page: int = 1,
    page_size: int = 20,
    q: Optional[str] = None,
    sort: str = "-created_at",
):
    admin_only(user)

    if page < 1: page = 1
    if page_size < 1: page_size = 20
    if page_size > 200: page_size = 200

    with SessionLocal() as db:
        query = db.query(User)

        if q:
            kw = f"%{q.strip().lower()}%"
            query = query.filter(
                (func.lower(User.email).like(kw)) | (User.email_norm.like(kw))
            )

        if sort.lstrip("-") == "email":
            col = func.lower(User.email)
        else:
            col = User.created_at
        
        if sort.startswith("-"):
            query = query.order_by(col.desc())
        else:
            query = query.order_by(col.asc())

        total = query.count()
        rows = query.offset((page - 1) * page_size).limit(page_size).all()

        items = [{
            "id": r.id,
            "email": r.email,
            "role": r.role,
            "is_admin": bool(r.is_admin),
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            "minutes_balance_seconds": int(r.minutes_balance_seconds or 0),
            "free_quota_seconds_remaining": int(r.free_quota_seconds_remaining or 0),
            "last_quota_reset_month": r.last_quota_reset_month or "",
        } for r in rows]

        return {
            "page": page,
            "page_size": page_size,
            "total": total,
            "items": items,
        }

@app.get("/admin/metrics")
def admin_metrics(user: User = Depends(current_user)):
    admin_only(user)
    now = datetime.utcnow()
    today_utc = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    since_7d = now - timedelta(days=7)

    with SessionLocal() as db:
        total_users = db.query(func.count(User.id)).scalar() or 0
        new_users_today = db.query(func.count(User.id)).filter(User.created_at >= today_utc).scalar() or 0
        active_7d = db.query(func.count(User.id)).filter(User.updated_at >= since_7d).scalar() or 0
        admin_users = db.query(func.count(User.id)).filter(User.is_admin == True).scalar() or 0

        latest_rows = (db.query(User)
                         .order_by(User.created_at.desc())
                         .limit(10).all())
        latest_users = [{
            "id": r.id,
            "email": r.email,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "is_admin": bool(r.is_admin),
            "role": r.role,
        } for r in latest_rows]

        return {
            "generated_at": now.isoformat(),
            "totals": {
                "total_users": total_users,
                "admin_users": admin_users,
                "new_users_today": new_users_today,
                "active_7d": active_7d,
            },
            "latest_users": latest_users,
        }
# ================================================
#                Core Business Logic
# ================================================

@app.post("/api/process-text")
def process_text(body: ProcessTextBody, user: User = Depends(current_user)):
    # 步驟 1：驗證使用者身份 (Depends(current_user) 已經幫我們做好了)
    # 如果沒有有效的 Token，程式碼根本不會執行到這裡。

    # 步驟 2：執行核心任務 (目前先用一個簡單的例子：計算字數)
    word_count = len(body.text.split())

    # 步驟 3：準備回傳給使用者的結果
    result = {
        "message": "Text processed successfully.",
        "input_text": body.text,
        "word_count": word_count,
        "user_email": user.email, # 加上這個來確認我們正確地識別了使用者
    }
    
    return result
