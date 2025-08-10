import os, time
from datetime import datetime
from typing import Optional, Annotated

from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from pydantic import BaseModel, EmailStr

import jwt
from passlib.hash import bcrypt

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
app = FastAPI(title="Trimly API — Phase 0 (SQLite Clean Backend)", version="0.1.0")

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
    # 讓所有路由預設套用 Bearer（右上鎖頭）
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

# 把 Authorization 從 Swagger 參數隱藏（include_in_schema=False）
def current_user(
    Authorization: Annotated[Optional[str], Header(include_in_schema=False)] = None
) -> User:
    if not Authorization or not Authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Missing token")
    token = Authorization.split(" ", 1)[1].strip()
    try:
        data = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        uid = data["uid"]
    except Exception:
        raise HTTPException(401, "Invalid token")
    with SessionLocal() as db:
        user = db.query(User).filter(User.id == uid).first()
        if not user:
            raise HTTPException(401, "User not found")
        ensure_monthly_quota(user)
        db.commit()
        return user

def admin_only(user: User):
    if not user.is_admin:
        raise HTTPException(403, "Admin only")

# ---------------- Auth ----------------
@app.post("/auth/register")
def register(body: RegisterBody):
    email_norm = body.email.strip().lower()
    with SessionLocal() as db:
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
def login(body: LoginBody):
    email_norm = body.email.strip().lower()
    with SessionLocal() as db:
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
def me(user: User = Depends(current_user)):
    return {
        "email": user.email,
        "role": user.role,
        "is_admin": user.is_admin,
        "minutes_balance_seconds": user.minutes_balance_seconds,
        "free_quota_seconds_remaining": user.free_quota_seconds_remaining,
        "last_quota_reset_month": user.last_quota_reset_month,
    }

@app.get("/api/health")
def health():
    return {"ok": True, "version": app.version}

# ---- Debug（只用來檢查實際收到的 Authorization；之後可以移除）----
@app.get("/debug/echo_auth")
def debug_echo_auth(Authorization: Annotated[Optional[str], Header()] = None):
    return {"authorization": Authorization}
