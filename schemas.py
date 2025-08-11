from pydantic import BaseModel, EmailStr
from typing import Optional, List, Dict, Any
from datetime import datetime

# 使用者相關
class UserBase(BaseModel):
    email: EmailStr

class UserCreate(UserBase):
    password: str

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class User(UserBase):
    id: int
    role: str
    is_admin: bool
    minutes_balance_seconds: int
    free_quota_seconds_remaining: int
    ai_enhance_minutes_used: int
    ai_summary_count_used: int
    created_at: datetime
    
    class Config:
        from_attributes = True

# 專案相關
class ProjectBase(BaseModel):
    name: str
    description: Optional[str] = None

class ProjectCreate(ProjectBase):
    pass

class Project(ProjectBase):
    id: int
    user_id: int
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True

# 音訊檔案相關
class AudioFileBase(BaseModel):
    original_filename: str

class AudioFileCreate(AudioFileBase):
    project_id: int

class AudioFile(AudioFileBase):
    id: int
    project_id: int
    filename: str
    file_path: str
    duration_seconds: Optional[float]
    file_size_bytes: Optional[int]
    mime_type: Optional[str]
    upload_status: str
    created_at: datetime
    
    class Config:
        from_attributes = True

# 逐字稿相關
class TranscriptBase(BaseModel):
    language: str = "zh-TW"

class TranscriptCreate(TranscriptBase):
    audio_file_id: int

class Transcript(TranscriptBase):
    id: int
    audio_file_id: int
    content: Optional[str]
    status: str
    error_message: Optional[str]
    word_count: Optional[int]
    created_at: datetime
    completed_at: Optional[datetime]
    
    class Config:
        from_attributes = True

# 版本控制相關
class AudioVersionBase(BaseModel):
    version_name: str
    edit_summary: Optional[str]

class AudioVersionCreate(AudioVersionBase):
    audio_file_id: int
    edit_operations: Dict[str, Any]

class AudioVersion(AudioVersionBase):
    id: int
    audio_file_id: int
    file_path: str
    duration_seconds: Optional[float]
    file_size_bytes: Optional[int]
    created_at: datetime
    
    class Config:
        from_attributes = True

# AI 增強相關
class AIEnhancementBase(BaseModel):
    enhancement_type: str

class AIEnhancementCreate(AIEnhancementBase):
    audio_file_id: int

class AIEnhancement(AIEnhancementBase):
    id: int
    audio_file_id: int
    status: str
    error_message: Optional[str]
    api_provider: Optional[str]
    created_at: datetime
    completed_at: Optional[datetime]
    
    class Config:
        from_attributes = True

# 內容摘要相關
class ContentSummaryBase(BaseModel):
    summary_type: str

class ContentSummaryCreate(ContentSummaryBase):
    transcript_id: int

class ContentSummary(ContentSummaryBase):
    id: int
    transcript_id: int
    content: str
    status: str
    error_message: Optional[str]
    token_count: Optional[int]
    created_at: datetime
    completed_at: Optional[datetime]
    
    class Config:
        from_attributes = True

# API 回應格式
class APIResponse(BaseModel):
    success: bool
    message: str
    data: Optional[Any] = None

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: User

# 編輯操作
class EditOperation(BaseModel):
    type: str  # delete_text, delete_filler, delete_keyword
    start_time: float
    end_time: float
    text: Optional[str]
    reason: Optional[str]

class EditRequest(BaseModel):
    operations: List[EditOperation]
    version_name: Optional[str] = None

# 檔案上傳
class UploadResponse(BaseModel):
    audio_file: AudioFile
    upload_url: Optional[str] = None

# 用量統計
class UsageStats(BaseModel):
    total_projects: int
    total_audio_files: int
    total_processing_minutes: int
    ai_enhance_minutes_used: int
    ai_summary_count_used: int
    remaining_quota: int

