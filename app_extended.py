from fastapi import FastAPI, Depends, HTTPException, status, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from typing import List, Optional
import os
from datetime import datetime, timedelta

# 導入模組
from models_extended import (
    User, Project, AudioFile, Transcript, AudioVersion, 
    init_db, get_db, SessionLocal
)
from schemas import (
    UserCreate, UserLogin, User as UserSchema, TokenResponse,
    ProjectCreate, Project as ProjectSchema,
    AudioFileCreate, AudioFile as AudioFileSchema,
    TranscriptCreate, Transcript as TranscriptSchema,
    APIResponse, UsageStats, EditRequest
)
from auth import get_current_user, get_current_admin_user, require_admin
from utils import (
    normalize_email, hash_password, verify_password, create_access_token,
    check_admin_emails, generate_unique_filename, get_upload_path,
    calculate_quota_usage, check_quota_limit, TrimlyException
)

# 導入 AI 功能 API
from api_endpoints import router as ai_router
from project_api import router as project_router
from ai_enhancement_api import router as ai_enhancement_router
from subscription_api import router as subscription_router
from account_api import router as account_router

# 建立 FastAPI 應用
app = FastAPI(
    title="Trimly API",
    description="AI 聲音剪輯平台 - 完整版",
    version="1.0.0"
)

# CORS 設定
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 在生產環境中應該限制特定域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 註冊 AI 功能路由
app.include_router(ai_router)
app.include_router(project_router)
app.include_router(ai_enhancement_router)
app.include_router(subscription_router)
app.include_router(account_router)

# 初始化資料庫
@app.on_event("startup")
async def startup_event():
    from models_extended import init_all_db
    init_all_db()
    print("Database initialized successfully")
    print("AI Audio Processing features enabled")
    print("Project Management and Version Control enabled")
    print("Advanced AI Enhancement and Summary features enabled")
    print("Subscription and Payment system enabled")
    print("Account Management and Billing system enabled")

# 錯誤處理
@app.exception_handler(TrimlyException)
async def trimly_exception_handler(request, exc: TrimlyException):
    return JSONResponse(
        status_code=400,
        content={"success": False, "message": exc.message, "code": exc.code}
    )

# ==================== 認證相關 API ====================

@app.post("/auth/register", response_model=TokenResponse)
async def register(user_data: UserCreate, db: Session = Depends(get_db)):
    """使用者註冊"""
    
    # 檢查 email 是否已存在
    email_norm = normalize_email(user_data.email)
    existing_user = db.query(User).filter(User.email_norm == email_norm).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    
    # 建立新使用者
    hashed_password = hash_password(user_data.password)
    is_admin = check_admin_emails(user_data.email)
    
    new_user = User(
        email=user_data.email,
        email_norm=email_norm,
        password_hash=hashed_password,
        is_admin=is_admin,
        role="free"
    )
    
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    # 建立 token
    access_token = create_access_token(data={"sub": new_user.email})
    
    return TokenResponse(
        access_token=access_token,
        user=UserSchema.from_orm(new_user)
    )

@app.post("/auth/login", response_model=TokenResponse)
async def login(user_data: UserLogin, db: Session = Depends(get_db)):
    """使用者登入"""
    
    # 查詢使用者
    email_norm = normalize_email(user_data.email)
    user = db.query(User).filter(User.email_norm == email_norm).first()
    
    if not user or not verify_password(user_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password"
        )
    
    # 建立 token
    access_token = create_access_token(data={"sub": user.email})
    
    return TokenResponse(
        access_token=access_token,
        user=UserSchema.from_orm(user)
    )

@app.get("/me", response_model=UserSchema)
async def get_current_user_info(current_user: User = Depends(get_current_user)):
    """取得當前使用者資訊"""
    return UserSchema.from_orm(current_user)

@app.get("/me/usage", response_model=UsageStats)
async def get_usage_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """取得使用者用量統計"""
    
    # 計算統計數據
    total_projects = db.query(Project).filter(Project.user_id == current_user.id).count()
    total_audio_files = db.query(AudioFile).join(Project).filter(Project.user_id == current_user.id).count()
    
    quotas = calculate_quota_usage(current_user.role)
    
    return UsageStats(
        total_projects=total_projects,
        total_audio_files=total_audio_files,
        total_processing_minutes=0,  # TODO: 計算實際處理時間
        ai_enhance_minutes_used=current_user.ai_enhance_minutes_used,
        ai_summary_count_used=current_user.ai_summary_count_used,
        remaining_quota=current_user.free_quota_seconds_remaining
    )

# ==================== 專案管理 API ====================

@app.post("/projects", response_model=ProjectSchema)
async def create_project(
    project_data: ProjectCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """建立新專案"""
    
    new_project = Project(
        user_id=current_user.id,
        name=project_data.name,
        description=project_data.description
    )
    
    db.add(new_project)
    db.commit()
    db.refresh(new_project)
    
    return ProjectSchema.from_orm(new_project)

@app.get("/projects", response_model=List[ProjectSchema])
async def get_projects(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """取得使用者的所有專案"""
    
    projects = db.query(Project).filter(Project.user_id == current_user.id).all()
    return [ProjectSchema.from_orm(project) for project in projects]

@app.get("/projects/{project_id}", response_model=ProjectSchema)
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
    
    return ProjectSchema.from_orm(project)

# ==================== 音訊檔案管理 API ====================

@app.post("/projects/{project_id}/upload", response_model=AudioFileSchema)
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
    
    # 驗證檔案類型
    if not file.content_type.startswith('audio/'):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File must be an audio file"
        )
    
    # 生成唯一檔名並儲存
    unique_filename = generate_unique_filename(file.filename)
    upload_path = get_upload_path(current_user.id, project_id)
    file_path = os.path.join(upload_path, unique_filename)
    
    # 儲存檔案
    with open(file_path, "wb") as buffer:
        content = await file.read()
        buffer.write(content)
    
    # 建立資料庫記錄
    audio_file = AudioFile(
        project_id=project_id,
        filename=unique_filename,
        original_filename=file.filename,
        file_path=file_path,
        file_size_bytes=len(content),
        mime_type=file.content_type,
        upload_status="uploaded"
    )
    
    db.add(audio_file)
    db.commit()
    db.refresh(audio_file)
    
    return AudioFileSchema.from_orm(audio_file)

@app.get("/projects/{project_id}/audio", response_model=List[AudioFileSchema])
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
    return [AudioFileSchema.from_orm(audio_file) for audio_file in audio_files]

# ==================== 逐字稿 API ====================

@app.post("/audio/{audio_id}/transcribe", response_model=TranscriptSchema)
async def create_transcript(
    audio_id: int,
    transcript_data: TranscriptCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """為音訊檔案建立逐字稿"""
    
    # 驗證音訊檔案存在且屬於當前使用者
    audio_file = db.query(AudioFile).join(Project).filter(
        AudioFile.id == audio_id,
        Project.user_id == current_user.id
    ).first()
    
    if not audio_file:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Audio file not found"
        )
    
    # 檢查配額
    if not check_quota_limit(current_user, "transcribe", 1):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Quota exceeded"
        )
    
    # 建立逐字稿記錄
    transcript = Transcript(
        audio_file_id=audio_id,
        language=transcript_data.language,
        status="processing"
    )
    
    db.add(transcript)
    db.commit()
    db.refresh(transcript)
    
    # TODO: 在這裡啟動背景任務進行實際的語音轉文字處理
    
    return TranscriptSchema.from_orm(transcript)

@app.get("/audio/{audio_id}/transcripts", response_model=List[TranscriptSchema])
async def get_transcripts(
    audio_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """取得音訊檔案的所有逐字稿"""
    
    # 驗證音訊檔案存在且屬於當前使用者
    audio_file = db.query(AudioFile).join(Project).filter(
        AudioFile.id == audio_id,
        Project.user_id == current_user.id
    ).first()
    
    if not audio_file:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Audio file not found"
        )
    
    transcripts = db.query(Transcript).filter(Transcript.audio_file_id == audio_id).all()
    return [TranscriptSchema.from_orm(transcript) for transcript in transcripts]

# ==================== 管理員 API ====================

@app.get("/admin/users", response_model=List[UserSchema])
async def admin_get_users(
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """管理員取得所有使用者"""
    users = db.query(User).all()
    return [UserSchema.from_orm(user) for user in users]

@app.get("/admin/stats")
async def admin_get_stats(
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """管理員取得系統統計"""
    
    total_users = db.query(User).count()
    total_projects = db.query(Project).count()
    total_audio_files = db.query(AudioFile).count()
    total_transcripts = db.query(Transcript).count()
    
    return {
        "total_users": total_users,
        "total_projects": total_projects,
        "total_audio_files": total_audio_files,
        "total_transcripts": total_transcripts,
        "admin_user": current_admin.email
    }

# ==================== 健康檢查 API ====================

@app.get("/api/health")
async def health_check():
    """系統健康檢查"""
    return {
        "ok": True,
        "version": "1.0.0",
        "timestamp": datetime.utcnow().isoformat(),
        "database": "connected"
    }

@app.get("/")
async def root():
    """根路徑"""
    return {"message": "Trimly AI Audio Editing Platform API", "version": "1.0.0"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

