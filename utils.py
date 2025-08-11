import os
import uuid
import hashlib
import mimetypes
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
import json

# 檔案處理工具
def generate_unique_filename(original_filename: str) -> str:
    """生成唯一的檔案名稱"""
    ext = os.path.splitext(original_filename)[1]
    unique_id = str(uuid.uuid4())
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{timestamp}_{unique_id}{ext}"

def get_file_info(file_path: str) -> Dict[str, Any]:
    """取得檔案資訊"""
    if not os.path.exists(file_path):
        return {}
    
    stat = os.stat(file_path)
    mime_type, _ = mimetypes.guess_type(file_path)
    
    return {
        "size_bytes": stat.st_size,
        "mime_type": mime_type,
        "created_at": datetime.fromtimestamp(stat.st_ctime),
        "modified_at": datetime.fromtimestamp(stat.st_mtime)
    }

def ensure_directory(path: str) -> None:
    """確保目錄存在"""
    os.makedirs(path, exist_ok=True)

# 音訊處理工具
def get_audio_duration(file_path: str) -> Optional[float]:
    """取得音訊檔案長度（秒）"""
    try:
        import librosa
        duration = librosa.get_duration(path=file_path)
        return duration
    except Exception as e:
        print(f"Error getting audio duration: {e}")
        return None

def validate_audio_file(file_path: str) -> bool:
    """驗證是否為有效的音訊檔案"""
    try:
        import librosa
        librosa.load(file_path, duration=1)  # 只載入1秒來測試
        return True
    except Exception:
        return False

# 文字處理工具
def normalize_email(email: str) -> str:
    """標準化 email 地址"""
    return email.lower().strip()

def hash_password(password: str) -> str:
    """密碼雜湊"""
    from passlib.context import CryptContext
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """驗證密碼"""
    from passlib.context import CryptContext
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    return pwd_context.verify(plain_password, hashed_password)

# JWT 工具
def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """建立 JWT token"""
    import jwt
    from datetime import datetime, timedelta
    
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(hours=24)
    
    to_encode.update({"exp": expire})
    
    secret_key = os.environ.get("JWT_SECRET", "your-secret-key")
    encoded_jwt = jwt.encode(to_encode, secret_key, algorithm="HS256")
    return encoded_jwt

def verify_token(token: str) -> Optional[Dict[str, Any]]:
    """驗證 JWT token"""
    import jwt
    
    try:
        secret_key = os.environ.get("JWT_SECRET", "your-secret-key")
        payload = jwt.decode(token, secret_key, algorithms=["HS256"])
        return payload
    except jwt.PyJWTError:
        return None

# 用量計算工具
def calculate_quota_usage(user_role: str) -> Dict[str, int]:
    """計算使用者配額"""
    quotas = {
        "free": {
            "monthly_minutes": 30,
            "ai_enhance_minutes": 1,
            "ai_summary_count": 5,
            "max_versions": 3
        },
        "starter": {
            "monthly_minutes": 300,  # 5小時
            "ai_enhance_minutes": 10,
            "ai_summary_count": 50,
            "max_versions": 10
        },
        "pro": {
            "monthly_minutes": 1200,  # 20小時
            "ai_enhance_minutes": 60,
            "ai_summary_count": 200,
            "max_versions": 30
        },
        "creator": {
            "monthly_minutes": -1,  # 無限制
            "ai_enhance_minutes": -1,
            "ai_summary_count": -1,
            "max_versions": 50
        }
    }
    
    return quotas.get(user_role, quotas["free"])

def check_quota_limit(user, action: str, amount: int = 1) -> bool:
    """檢查是否超過配額限制"""
    quotas = calculate_quota_usage(user.role)
    
    if action == "transcribe":
        if quotas["monthly_minutes"] == -1:
            return True
        return user.free_quota_seconds_remaining >= (amount * 60)
    
    elif action == "ai_enhance":
        if quotas["ai_enhance_minutes"] == -1:
            return True
        return user.ai_enhance_minutes_used < quotas["ai_enhance_minutes"]
    
    elif action == "ai_summary":
        if quotas["ai_summary_count"] == -1:
            return True
        return user.ai_summary_count_used < quotas["ai_summary_count"]
    
    return False

# 檔案路徑工具
def get_upload_path(user_id: int, project_id: int) -> str:
    """取得上傳檔案的儲存路徑"""
    base_path = os.environ.get("UPLOAD_PATH", "/var/data/uploads")
    path = os.path.join(base_path, str(user_id), str(project_id))
    ensure_directory(path)
    return path

def get_processed_path(user_id: int, project_id: int) -> str:
    """取得處理後檔案的儲存路徑"""
    base_path = os.environ.get("PROCESSED_PATH", "/var/data/processed")
    path = os.path.join(base_path, str(user_id), str(project_id))
    ensure_directory(path)
    return path

# JSON 處理工具
def safe_json_loads(json_str: str, default=None):
    """安全的 JSON 解析"""
    try:
        return json.loads(json_str) if json_str else default
    except (json.JSONDecodeError, TypeError):
        return default

def safe_json_dumps(obj, default=None) -> str:
    """安全的 JSON 序列化"""
    try:
        return json.dumps(obj, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return json.dumps(default) if default is not None else "{}"

# 錯誤處理工具
class TrimlyException(Exception):
    """自定義異常類別"""
    def __init__(self, message: str, code: str = "UNKNOWN_ERROR"):
        self.message = message
        self.code = code
        super().__init__(self.message)

class QuotaExceededException(TrimlyException):
    """配額超限異常"""
    def __init__(self, message: str = "Quota exceeded"):
        super().__init__(message, "QUOTA_EXCEEDED")

class FileProcessingException(TrimlyException):
    """檔案處理異常"""
    def __init__(self, message: str = "File processing failed"):
        super().__init__(message, "FILE_PROCESSING_ERROR")

class APIException(TrimlyException):
    """第三方 API 異常"""
    def __init__(self, message: str = "External API error"):
        super().__init__(message, "API_ERROR")

