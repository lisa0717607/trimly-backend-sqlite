import os
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, UniqueConstraint
from sqlalchemy.orm import declarative_base, sessionmaker

# 檢查環境變數中是否有指定資料庫路徑，若無，則使用預設的持久化路徑
# 這個預設路徑 /var/data/trimly.db 正是我們在 Render 上設定的硬碟掛載點
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:////var/data/trimly.db")

print(f"Initializing database at: {DATABASE_URL}")  # 加上這行日誌，方便我們在 Render 上確認

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)

    email = Column(String, nullable=False, index=True)
    email_norm = Column(String, nullable=False, unique=True, index=True)

    password_hash = Column(String, nullable=False)
    role = Column(String, default="free")
    is_admin = Column(Boolean, default=False)

    minutes_balance_seconds = Column(Integer, default=0)
    free_quota_seconds_remaining = Column(Integer, default=1800)
    last_quota_reset_month = Column(String, default="")

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("email_norm", name="uq_users_email_norm"),
    )

def init_db():
    Base.metadata.create_all(bind=engine)

