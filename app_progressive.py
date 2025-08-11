"""
Trimly AI Audio Processing Platform - Progressive Feature Recovery
漸進式功能恢復版本
"""

import os
import logging
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, Depends, HTTPException, status, BackgroundTasks, UploadFile, File
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, Text, Float
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from sqlalchemy.exc import IntegrityError
from pydantic import BaseModel, EmailStr
from passlib.context import CryptContext
from jose import JWTError, jwt
import uvicorn

# ==================== 配置 ====================

# 環境變數
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:////var/data/trimly.db")
JWT_SECRET = os.getenv("JWT_SECRET", "your-secret-key-here")
ADMIN_EMAILS = os.getenv("ADMIN_EMAILS", "lisa0717607@gmail.com").split(",")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# 日誌配置
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 密碼加密
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# JWT 配置
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# 資料庫配置
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
Base = declarative_base()

# ==================== 資料庫模型 ====================

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(String, default="free")  # free, starter, pro, creator
    is_admin = Column(Boolean, default=False)
    
    # 配額管理
    transcription_minutes_used = Column(Integer, default=0)
    transcription_minutes_limit = Column(Integer, default=30)  # 免費版 30 分鐘
    ai_enhancements_used = Column(Integer, default=0)
    ai_enhancements_limit = Column(Integer, default=5)  # 免費版 5 次
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

class Project(Base):
    __tablename__ = "projects"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

class AudioFile(Base):
    __tablename__ = "audio_files"
    
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, nullable=False)
    user_id = Column(Integer, nullable=False)
    filename = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    file_size = Column(Integer, nullable=False)
    duration_seconds = Column(Float)
    
    # 處理狀態
    transcription_status = Column(String, default="pending")  # pending, processing, completed, failed
    transcription_text = Column(Text)
    
    created_at = Column(DateTime, default=datetime.utcnow)

# ==================== Pydantic 模型 ====================

class UserCreate(BaseModel):
    email: EmailStr
    password: str

class UserResponse(BaseModel):
    id: int
    email: str
    role: str
    is_admin: bool
    transcription_minutes_used: int
    transcription_minutes_limit: int
    ai_enhancements_used: int
    ai_enhancements_limit: int
    created_at: datetime

    class Config:
        from_attributes = True

class Token(BaseModel):
    access_token: str
    token_type: str
    user: UserResponse

class ProjectCreate(BaseModel):
    name: str
    description: Optional[str] = None

class ProjectResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True

class AudioFileResponse(BaseModel):
    id: int
    filename: str
    file_size: int
    duration_seconds: Optional[float]
    transcription_status: str
    transcription_text: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True

# ==================== FastAPI 應用程式 ====================

app = FastAPI(
    title="Trimly AI Audio Processing Platform",
    description="Progressive Feature Recovery Version",
    version="1.1.0-progressive"
)

# CORS 設定
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 安全性
security = HTTPBearer()

# ==================== 依賴注入 ====================

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET, algorithm=ALGORITHM)
    return encoded_jwt

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security), db: Session = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    
    user = db.query(User).filter(User.email == email).first()
    if user is None:
        raise credentials_exception
    return user

# ==================== API 端點 ====================

@app.get("/")
async def root():
    """根端點"""
    return {
        "message": "Trimly AI Audio Processing Platform",
        "version": "1.1.0-progressive",
        "status": "running",
        "features": [
            "user_authentication",
            "project_management", 
            "audio_upload",
            "transcription_ready",
            "ai_features_ready"
        ]
    }

@app.get("/health")
async def health_check():
    """健康檢查"""
    try:
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
        "version": "1.1.0-progressive",
        "openai_configured": bool(OPENAI_API_KEY)
    }

# ==================== 認證端點 ====================

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
    is_admin = user_data.email.strip().lower() in [email.strip().lower() for email in ADMIN_EMAILS]
    
    user = User(
        email=user_data.email,
        password_hash=hashed_password,
        is_admin=is_admin,
        role="starter" if is_admin else "free"
    )
    
    try:
        db.add(user)
        db.commit()
        db.refresh(user)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    
    # 建立 JWT token
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.email}, expires_delta=access_token_expires
    )
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": UserResponse.from_orm(user)
    }

@app.post("/auth/login", response_model=Token)
async def login(user_data: UserCreate, db: Session = Depends(get_db)):
    """使用者登入"""
    user = db.query(User).filter(User.email == user_data.email).first()
    if not user or not verify_password(user_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.email}, expires_delta=access_token_expires
    )
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": UserResponse.from_orm(user)
    }

@app.get("/auth/me", response_model=UserResponse)
async def get_current_user_info(current_user: User = Depends(get_current_user)):
    """取得當前使用者資訊"""
    return UserResponse.from_orm(current_user)

# ==================== 專案管理端點 ====================

@app.post("/projects", response_model=ProjectResponse)
async def create_project(
    project_data: ProjectCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """建立新專案"""
    project = Project(
        user_id=current_user.id,
        name=project_data.name,
        description=project_data.description
    )
    
    db.add(project)
    db.commit()
    db.refresh(project)
    
    return ProjectResponse.from_orm(project)

@app.get("/projects", response_model=List[ProjectResponse])
async def get_projects(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """取得使用者的所有專案"""
    projects = db.query(Project).filter(Project.user_id == current_user.id).all()
    return [ProjectResponse.from_orm(project) for project in projects]

@app.get("/projects/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """取得特定專案"""
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == current_user.id
    ).first()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    
    return ProjectResponse.from_orm(project)

# ==================== 音訊檔案端點 ====================

@app.post("/projects/{project_id}/audio", response_model=AudioFileResponse)
async def upload_audio(
    project_id: int,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """上傳音訊檔案到專案"""
    # 驗證專案存在且屬於當前使用者
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == current_user.id
    ).first()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    
    # 檢查檔案類型
    allowed_types = ["audio/mpeg", "audio/wav", "audio/mp3", "audio/m4a", "audio/flac"]
    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type: {file.content_type}"
        )
    
    # 讀取檔案內容
    content = await file.read()
    file_size = len(content)
    
    # 檢查檔案大小 (最大 100MB)
    max_size = 100 * 1024 * 1024  # 100MB
    if file_size > max_size:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File too large. Maximum size is 100MB"
        )
    
    # 建立檔案記錄（暫時不實際儲存檔案）
    audio_file = AudioFile(
        project_id=project_id,
        user_id=current_user.id,
        filename=file.filename,
        file_path=f"/tmp/{file.filename}",  # 暫時路徑
        file_size=file_size,
        transcription_status="pending"
    )
    
    db.add(audio_file)
    db.commit()
    db.refresh(audio_file)
    
    return AudioFileResponse.from_orm(audio_file)

@app.get("/projects/{project_id}/audio", response_model=List[AudioFileResponse])
async def get_project_audio_files(
    project_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """取得專案的所有音訊檔案"""
    # 驗證專案存在且屬於當前使用者
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == current_user.id
    ).first()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    
    audio_files = db.query(AudioFile).filter(AudioFile.project_id == project_id).all()
    return [AudioFileResponse.from_orm(audio_file) for audio_file in audio_files]

# ==================== AI 功能端點（準備中）====================

@app.post("/audio/{audio_id}/transcribe")
async def start_transcription(
    audio_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """開始音訊轉錄（準備中）"""
    # 檢查音訊檔案存在且屬於當前使用者
    audio_file = db.query(AudioFile).filter(
        AudioFile.id == audio_id,
        AudioFile.user_id == current_user.id
    ).first()
    
    if not audio_file:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Audio file not found"
        )
    
    # 檢查配額
    if current_user.transcription_minutes_used >= current_user.transcription_minutes_limit:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Transcription quota exceeded"
        )
    
    # 更新狀態為處理中
    audio_file.transcription_status = "processing"
    db.commit()
    
    return {
        "message": "Transcription started",
        "audio_id": audio_id,
        "status": "processing",
        "note": "This is a demo response. Full AI integration coming soon."
    }

@app.get("/audio/{audio_id}/transcript")
async def get_transcript(
    audio_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """取得音訊轉錄結果"""
    audio_file = db.query(AudioFile).filter(
        AudioFile.id == audio_id,
        AudioFile.user_id == current_user.id
    ).first()
    
    if not audio_file:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Audio file not found"
        )
    
    return {
        "audio_id": audio_id,
        "status": audio_file.transcription_status,
        "text": audio_file.transcription_text,
        "note": "Full AI transcription integration coming soon."
    }

# ==================== 管理員端點 ====================

@app.get("/admin/users", response_model=List[UserResponse])
async def get_all_users(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """取得所有使用者（僅管理員）"""
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    
    users = db.query(User).all()
    return [UserResponse.from_orm(user) for user in users]

# ==================== 資料庫初始化 ====================

@app.on_event("startup")
async def startup_event():
    """應用程式啟動時初始化資料庫"""
    try:
        print(f"Starting Trimly AI Audio Processing Platform - Progressive Version")
        print(f"Database URL: {DATABASE_URL}")
        print(f"Admin emails: {ADMIN_EMAILS}")
        print(f"OpenAI API configured: {bool(OPENAI_API_KEY)}")
        
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
        
        print("Progressive feature recovery application startup completed successfully")
        
    except Exception as e:
        print(f"Startup error: {str(e)}")
        # 不要在啟動時拋出異常，讓應用程式繼續運行
        pass

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(
        "app_progressive:app",
        host="0.0.0.0",
        port=port,
        reload=False,
        log_level="info"
    )

