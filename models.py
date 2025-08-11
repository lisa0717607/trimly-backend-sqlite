import os
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, UniqueConstraint
from sqlalchemy.orm import declarative_base, sessionmaker

# --- vvv NEW CODE vvv ---
# 1. 從環境變數讀取持久化硬碟的路徑。
#    如果在 Render 上，這個值會是 /var/data (我們稍後會設定)。
#    如果在本機或其他環境，它會使用當前目錄下的 'local_data' 資料夾作為備用。
DATA_DIR = os.environ.get("RENDER_DISK_PATH", "local_data")

# 2. 確保這個資料夾存在，如果不存在就自動建立。
#    這可以防止因資料夾不存在而導致的錯誤。
os.makedirs(DATA_DIR, exist_ok=True)

# 3. 組合出完整的資料庫檔案路徑。
#    例如，在 Render 上它會變成 /var/data/trimly.db
DB_FILE_PATH = os.path.join(DATA_DIR, "trimly.db")
DATABASE_URL = f"sqlite:///{DB_FILE_PATH}"
# --- ^^^ END OF NEW CODE ^^^ ---


# 我們現在使用新的 DATABASE_URL，而不是寫死的路徑
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
    # 這行會印出資料庫實際儲存的路徑，方便您在 logs 中確認是否設定正確
    print(f"Initializing database at: {DATABASE_URL}") 
    Base.metadata.create_all(bind=engine)

