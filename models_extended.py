import os
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, UniqueConstraint, ForeignKey, Float, Text
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

# 檢查環境變數中是否有指定資料庫路徑，若無，則使用預設的持久化路徑
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:////var/data/trimly.db")

print(f"Initializing database at: {DATABASE_URL}")

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)

    email = Column(String, nullable=False, index=True)
    email_norm = Column(String, nullable=False, unique=True, index=True)

    password_hash = Column(String, nullable=False)
    role = Column(String, default="free")  # free, starter, pro, creator
    is_admin = Column(Boolean, default=False)

    # 用量追蹤
    minutes_balance_seconds = Column(Integer, default=0)
    free_quota_seconds_remaining = Column(Integer, default=1800)  # 30分鐘免費額度
    last_quota_reset_month = Column(String, default="")
    
    # AI 功能用量
    ai_enhance_minutes_used = Column(Integer, default=0)
    ai_summary_count_used = Column(Integer, default=0)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    # 關聯
    projects = relationship("Project", back_populates="user")

    __table_args__ = (
        UniqueConstraint("email_norm", name="uq_users_email_norm"),
    )

class Project(Base):
    __tablename__ = "projects"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    name = Column(String, nullable=False)
    description = Column(String)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    # 關聯
    user = relationship("User", back_populates="projects")
    audio_files = relationship("AudioFile", back_populates="project")

class AudioFile(Base):
    __tablename__ = "audio_files"
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    
    filename = Column(String, nullable=False)  # 系統生成的檔名
    original_filename = Column(String, nullable=False)  # 使用者上傳的原始檔名
    file_path = Column(String, nullable=False)  # 檔案儲存路徑
    
    duration_seconds = Column(Float)
    file_size_bytes = Column(Integer)
    mime_type = Column(String)
    
    upload_status = Column(String, default="uploaded")  # uploaded, processing, completed, error
    
    created_at = Column(DateTime, default=datetime.utcnow)

    # 關聯
    project = relationship("Project", back_populates="audio_files")
    transcripts = relationship("Transcript", back_populates="audio_file")
    versions = relationship("AudioVersion", back_populates="audio_file")

class Transcript(Base):
    __tablename__ = "transcripts"
    id = Column(Integer, primary_key=True, index=True)
    audio_file_id = Column(Integer, ForeignKey("audio_files.id"), nullable=False)
    
    content = Column(Text)  # JSON 格式，包含時間戳和文字
    language = Column(String, default="zh-TW")  # zh-TW, zh-CN, en
    
    status = Column(String, default="processing")  # processing, completed, error
    error_message = Column(String)
    
    # 處理統計
    processing_duration_seconds = Column(Float)
    word_count = Column(Integer)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime)

    # 關聯
    audio_file = relationship("AudioFile", back_populates="transcripts")

class AudioVersion(Base):
    __tablename__ = "audio_versions"
    id = Column(Integer, primary_key=True, index=True)
    audio_file_id = Column(Integer, ForeignKey("audio_files.id"), nullable=False)
    
    version_name = Column(String, nullable=False)  # v1, v2, v3 等
    file_path = Column(String, nullable=False)
    
    # 編輯記錄
    edit_operations = Column(Text)  # JSON 格式記錄所有編輯操作
    edit_summary = Column(String)  # 人類可讀的編輯摘要
    
    # 檔案資訊
    duration_seconds = Column(Float)
    file_size_bytes = Column(Integer)
    
    created_at = Column(DateTime, default=datetime.utcnow)

    # 關聯
    audio_file = relationship("AudioFile", back_populates="versions")

class AIEnhancement(Base):
    __tablename__ = "ai_enhancements"
    id = Column(Integer, primary_key=True, index=True)
    audio_file_id = Column(Integer, ForeignKey("audio_files.id"), nullable=False)
    
    enhancement_type = Column(String, nullable=False)  # noise_reduction, speech_enhance
    input_file_path = Column(String, nullable=False)
    output_file_path = Column(String, nullable=False)
    
    status = Column(String, default="processing")  # processing, completed, error
    error_message = Column(String)
    
    # 處理統計
    processing_duration_seconds = Column(Float)
    api_provider = Column(String)  # adobe, dolby, etc.
    
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime)

class ContentSummary(Base):
    __tablename__ = "content_summaries"
    id = Column(Integer, primary_key=True, index=True)
    transcript_id = Column(Integer, ForeignKey("transcripts.id"), nullable=False)
    
    summary_type = Column(String, nullable=False)  # summary, highlights, social_posts
    content = Column(Text, nullable=False)  # 生成的內容
    
    status = Column(String, default="processing")  # processing, completed, error
    error_message = Column(String)
    
    # 處理統計
    processing_duration_seconds = Column(Float)
    token_count = Column(Integer)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime)

class UsageLog(Base):
    __tablename__ = "usage_logs"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    action = Column(String, nullable=False)  # upload, transcribe, edit, enhance, summarize
    resource_type = Column(String)  # audio_file, transcript, etc.
    resource_id = Column(Integer)
    
    # 用量統計
    duration_seconds = Column(Float)  # 音訊長度或處理時間
    cost_credits = Column(Integer, default=0)  # 消耗的點數
    
    created_at = Column(DateTime, default=datetime.utcnow)

def init_db():
    Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

