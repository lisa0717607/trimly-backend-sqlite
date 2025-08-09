from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, UniqueConstraint
from sqlalchemy.orm import declarative_base, sessionmaker

# Free tier: use /tmp (ephemeral). When you upgrade, point to /app/data with a persistent disk.
DB_PATH = "sqlite:////tmp/trimly.db"

engine = create_engine(DB_PATH, connect_args={"check_same_thread": False})
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
