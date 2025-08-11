"""
Trimly AI Audio Processing Platform - 最小化版本
用於確保基礎部署成功
"""

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, Text
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from sqlalchemy.sql import func
from pydantic import BaseModel, EmailStr
from passlib.context import CryptContext
from datetime import datetime, timedelta
import jwt
import os
from typing import Optional

# 環境變數
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:////var/data/trimly.db")
JWT_SECRET = os.getenv("JWT_SECRET", "your-secret-key-here")
ADMIN_EMAILS = os.getenv("ADMIN_EMAILS", "lisa0717607@gmail.com").split(",")

# 資料庫設定
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# 密碼加密
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()

# 建立 FastAPI 應用
app = FastAPI(
    title="Trimly AI Audio Processing Platform",
    description="AI-powered audio editing and transcription platform - Minimal Version",
    version="1.0.0-minimal"
)

# 設定 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==================== 資料模型 ====================

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    is_admin = Column(Boolean, default=False)
    role = Column(String, default="free")
    created_at = Column(DateTime, default=func.now())

# ==================== Pydantic 模型 ====================

class UserCreate(BaseModel):
    email: EmailStr
    password: str

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class UserResponse(BaseModel):
    id: int
    email: str
    role: str
    is_admin: bool
    created_at: datetime

    class Config:
        from_attributes = True

class Token(BaseModel):
    access_token: str
    token_type: str
    user: UserResponse

# ==================== 工具函數 ====================

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(hours=24)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET, algorithm="HS256")
    return encoded_jwt

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security), db: Session = Depends(get_db)):
    try:
        token = credentials.credentials
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        email: str = payload.get("sub")
        if email is None:
            raise HTTPException(status_code=401, detail="Invalid token")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    user = db.query(User).filter(User.email == email).first()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    return user

# ==================== API 端點 ====================

@app.get("/")
async def root():
    """根端點"""
    return {
        "message": "Trimly AI Audio Processing Platform",
        "version": "1.0.0-minimal",
        "status": "running",
        "database": "connected" if DATABASE_URL else "not configured"
    }

@app.get("/health")
async def health_check():
    """健康檢查"""
    try:
        # 測試資料庫連接
        db = SessionLocal()
        db.execute("SELECT 1")
        db.close()
        db_status = "connected"
    except Exception as e:
        db_status = f"error: {str(e)[:50]}"
    
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "database": db_status,
        "version": "1.0.0-minimal"
    }

@app.post("/auth/register", response_model=Token)
async def register(user_data: UserCreate, db: Session = Depends(get_db)):
    """使用者註冊"""
    
    # 檢查使用者是否已存在
    existing_user = db.query(User).filter(User.email == user_data.email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    
    # 建立新使用者
    hashed_password = get_password_hash(user_data.password)
    is_admin = user_data.email in ADMIN_EMAILS
    
    user = User(
        email=user_data.email,
        password_hash=hashed_password,
        is_admin=is_admin,
        role="admin" if is_admin else "free"
    )
    
    db.add(user)
    db.commit()
    db.refresh(user)
    
    # 建立 JWT token
    access_token = create_access_token(data={"sub": user.email})
    
    return Token(
        access_token=access_token,
        token_type="bearer",
        user=UserResponse.from_orm(user)
    )

@app.post("/auth/login", response_model=Token)
async def login(user_data: UserLogin, db: Session = Depends(get_db)):
    """使用者登入"""
    
    user = db.query(User).filter(User.email == user_data.email).first()
    if not user or not verify_password(user_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password"
        )
    
    access_token = create_access_token(data={"sub": user.email})
    
    return Token(
        access_token=access_token,
        token_type="bearer",
        user=UserResponse.from_orm(user)
    )

@app.get("/auth/me", response_model=UserResponse)
async def get_current_user_info(current_user: User = Depends(get_current_user)):
    """取得當前使用者資訊"""
    return UserResponse.from_orm(current_user)

@app.get("/users/count")
async def get_user_count(db: Session = Depends(get_db)):
    """取得使用者總數"""
    total_users = db.query(User).count()
    admin_users = db.query(User).filter(User.is_admin == True).count()
    
    return {
        "total_users": total_users,
        "admin_users": admin_users,
        "regular_users": total_users - admin_users
    }

@app.get("/admin/users")
async def list_users(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """列出所有使用者（僅管理員）"""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    users = db.query(User).all()
    return [UserResponse.from_orm(user) for user in users]

# ==================== 資料庫初始化 ====================

@app.on_event("startup")
async def startup_event():
    """應用程式啟動時初始化資料庫"""
    try:
        print(f"Starting Trimly AI Audio Processing Platform - Minimal Version")
        print(f"Database URL: {DATABASE_URL}")
        print(f"Admin emails: {ADMIN_EMAILS}")
        
        # 確保資料庫目錄存在
        db_path = DATABASE_URL.replace("sqlite:///", "")
        db_dir = os.path.dirname(db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)
            print(f"Created database directory: {db_dir}")
        
        # 初始化資料庫
        Base.metadata.create_all(bind=engine)
        print("Database initialized successfully")
        
        # 測試資料庫連接
        db = SessionLocal()
        result = db.execute("SELECT 1").fetchone()
        db.close()
        print(f"Database connection test: {result}")
        
        print("Application startup completed successfully")
        
    except Exception as e:
        print(f"Startup error: {str(e)}")
        # 不要在啟動時拋出異常，讓應用程式繼續運行
        pass

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)

