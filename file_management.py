import os
import shutil
import hashlib
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Tuple
from pathlib import Path
import mimetypes
import asyncio

from sqlalchemy.orm import Session
from models_extended import SessionLocal, Project, AudioFile
from subscription_service import subscription_service
from utils import safe_json_loads, safe_json_dumps, generate_unique_filename

class FileManagementService:
    """檔案管理服務"""
    
    def __init__(self):
        self.db = SessionLocal()
        
        # 檔案儲存路徑
        self.base_storage_path = "/var/data/files"
        self.temp_storage_path = "/tmp/trimly_temp"
        
        # 確保目錄存在
        os.makedirs(self.base_storage_path, exist_ok=True)
        os.makedirs(self.temp_storage_path, exist_ok=True)
        
        # 支援的檔案類型
        self.supported_audio_types = {
            "audio/mpeg": [".mp3"],
            "audio/wav": [".wav"],
            "audio/x-wav": [".wav"],
            "audio/flac": [".flac"],
            "audio/aac": [".aac"],
            "audio/ogg": [".ogg"],
            "audio/mp4": [".m4a"],
            "audio/x-m4a": [".m4a"]
        }
        
        # 檔案大小限制（按訂閱方案）
        self.file_size_limits = {
            "free": 50 * 1024 * 1024,      # 50MB
            "starter": 100 * 1024 * 1024,   # 100MB
            "professional": 500 * 1024 * 1024,  # 500MB
            "creator": 1024 * 1024 * 1024   # 1GB
        }
    
    def get_user_storage_path(self, user_id: int) -> str:
        """取得使用者儲存路徑"""
        user_path = os.path.join(self.base_storage_path, f"user_{user_id}")
        os.makedirs(user_path, exist_ok=True)
        return user_path
    
    def get_project_storage_path(self, user_id: int, project_id: int) -> str:
        """取得專案儲存路徑"""
        project_path = os.path.join(
            self.get_user_storage_path(user_id), 
            f"project_{project_id}"
        )
        os.makedirs(project_path, exist_ok=True)
        return project_path
    
    def calculate_file_hash(self, file_path: str) -> str:
        """計算檔案 MD5 雜湊值"""
        hash_md5 = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()
    
    def validate_audio_file(self, file_path: str, user_id: int) -> Dict[str, Any]:
        """驗證音訊檔案"""
        
        # 檢查檔案是否存在
        if not os.path.exists(file_path):
            return {
                "valid": False,
                "error": "File not found"
            }
        
        # 檢查檔案大小
        file_size = os.path.getsize(file_path)
        plan = subscription_service.get_user_plan(user_id)
        size_limit = self.file_size_limits.get(plan.name, self.file_size_limits["free"])
        
        if file_size > size_limit:
            return {
                "valid": False,
                "error": f"File size ({file_size / 1024 / 1024:.1f}MB) exceeds limit ({size_limit / 1024 / 1024:.1f}MB) for {plan.display_name} plan"
            }
        
        # 檢查檔案類型
        mime_type, _ = mimetypes.guess_type(file_path)
        if not mime_type or not any(mime_type.startswith(audio_type) for audio_type in self.supported_audio_types.keys()):
            return {
                "valid": False,
                "error": f"Unsupported file type: {mime_type}"
            }
        
        # 檢查儲存配額
        current_usage = self.get_user_storage_usage(user_id)
        storage_limit_gb = plan.storage_gb
        storage_limit_bytes = storage_limit_gb * 1024 * 1024 * 1024
        
        if current_usage + file_size > storage_limit_bytes:
            return {
                "valid": False,
                "error": f"Storage quota exceeded. Current: {current_usage / 1024 / 1024 / 1024:.2f}GB, Limit: {storage_limit_gb}GB"
            }
        
        return {
            "valid": True,
            "file_size": file_size,
            "mime_type": mime_type,
            "storage_usage_after": current_usage + file_size
        }
    
    def store_audio_file(self, temp_file_path: str, user_id: int, project_id: int, 
                        original_filename: str) -> Dict[str, Any]:
        """儲存音訊檔案到永久位置"""
        
        try:
            # 驗證檔案
            validation = self.validate_audio_file(temp_file_path, user_id)
            if not validation["valid"]:
                return {
                    "success": False,
                    "error": validation["error"]
                }
            
            # 生成唯一檔名
            file_extension = Path(original_filename).suffix.lower()
            unique_filename = generate_unique_filename("audio", file_extension)
            
            # 取得儲存路徑
            storage_path = self.get_project_storage_path(user_id, project_id)
            final_path = os.path.join(storage_path, unique_filename)
            
            # 複製檔案
            shutil.copy2(temp_file_path, final_path)
            
            # 計算檔案雜湊值
            file_hash = self.calculate_file_hash(final_path)
            
            # 取得檔案資訊
            file_size = os.path.getsize(final_path)
            
            # 更新儲存配額
            subscription_service.consume_quota(
                user_id, "storage", file_size / (1024 * 1024 * 1024)
            )
            
            return {
                "success": True,
                "file_path": final_path,
                "filename": unique_filename,
                "original_filename": original_filename,
                "file_size": file_size,
                "file_hash": file_hash,
                "mime_type": validation["mime_type"]
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": f"File storage failed: {str(e)}"
            }
    
    def get_user_storage_usage(self, user_id: int) -> int:
        """取得使用者儲存使用量（位元組）"""
        
        user_path = self.get_user_storage_path(user_id)
        total_size = 0
        
        try:
            for dirpath, dirnames, filenames in os.walk(user_path):
                for filename in filenames:
                    file_path = os.path.join(dirpath, filename)
                    if os.path.exists(file_path):
                        total_size += os.path.getsize(file_path)
        except Exception as e:
            print(f"Error calculating storage usage for user {user_id}: {str(e)}")
        
        return total_size
    
    def get_project_files(self, user_id: int, project_id: int) -> List[Dict[str, Any]]:
        """取得專案中的所有檔案"""
        
        project_path = self.get_project_storage_path(user_id, project_id)
        files = []
        
        try:
            for filename in os.listdir(project_path):
                file_path = os.path.join(project_path, filename)
                if os.path.isfile(file_path):
                    file_stat = os.stat(file_path)
                    mime_type, _ = mimetypes.guess_type(file_path)
                    
                    files.append({
                        "filename": filename,
                        "file_path": file_path,
                        "file_size": file_stat.st_size,
                        "mime_type": mime_type,
                        "created_at": datetime.fromtimestamp(file_stat.st_ctime),
                        "modified_at": datetime.fromtimestamp(file_stat.st_mtime)
                    })
        except Exception as e:
            print(f"Error listing project files: {str(e)}")
        
        return files
    
    def delete_file(self, user_id: int, project_id: int, filename: str) -> Dict[str, Any]:
        """刪除檔案"""
        
        try:
            project_path = self.get_project_storage_path(user_id, project_id)
            file_path = os.path.join(project_path, filename)
            
            if not os.path.exists(file_path):
                return {
                    "success": False,
                    "error": "File not found"
                }
            
            # 檢查檔案是否屬於該使用者
            if not file_path.startswith(self.get_user_storage_path(user_id)):
                return {
                    "success": False,
                    "error": "Access denied"
                }
            
            # 取得檔案大小（用於更新配額）
            file_size = os.path.getsize(file_path)
            
            # 刪除檔案
            os.remove(file_path)
            
            # 更新儲存配額
            subscription_service.consume_quota(
                user_id, "storage", -(file_size / (1024 * 1024 * 1024))
            )
            
            return {
                "success": True,
                "message": "File deleted successfully",
                "freed_space": file_size
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": f"File deletion failed: {str(e)}"
            }
    
    def move_file(self, user_id: int, source_project_id: int, target_project_id: int, 
                 filename: str) -> Dict[str, Any]:
        """移動檔案到另一個專案"""
        
        try:
            source_path = self.get_project_storage_path(user_id, source_project_id)
            target_path = self.get_project_storage_path(user_id, target_project_id)
            
            source_file = os.path.join(source_path, filename)
            target_file = os.path.join(target_path, filename)
            
            if not os.path.exists(source_file):
                return {
                    "success": False,
                    "error": "Source file not found"
                }
            
            if os.path.exists(target_file):
                return {
                    "success": False,
                    "error": "File already exists in target project"
                }
            
            # 移動檔案
            shutil.move(source_file, target_file)
            
            return {
                "success": True,
                "message": "File moved successfully",
                "new_path": target_file
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": f"File move failed: {str(e)}"
            }
    
    def copy_file(self, user_id: int, source_project_id: int, target_project_id: int, 
                 filename: str, new_filename: str = None) -> Dict[str, Any]:
        """複製檔案到另一個專案"""
        
        try:
            source_path = self.get_project_storage_path(user_id, source_project_id)
            target_path = self.get_project_storage_path(user_id, target_project_id)
            
            source_file = os.path.join(source_path, filename)
            
            if not new_filename:
                new_filename = filename
            
            target_file = os.path.join(target_path, new_filename)
            
            if not os.path.exists(source_file):
                return {
                    "success": False,
                    "error": "Source file not found"
                }
            
            if os.path.exists(target_file):
                return {
                    "success": False,
                    "error": "File already exists in target project"
                }
            
            # 檢查儲存配額
            file_size = os.path.getsize(source_file)
            validation = self.validate_audio_file(source_file, user_id)
            
            if not validation["valid"]:
                return {
                    "success": False,
                    "error": validation["error"]
                }
            
            # 複製檔案
            shutil.copy2(source_file, target_file)
            
            # 更新儲存配額
            subscription_service.consume_quota(
                user_id, "storage", file_size / (1024 * 1024 * 1024)
            )
            
            return {
                "success": True,
                "message": "File copied successfully",
                "new_path": target_file,
                "new_filename": new_filename
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": f"File copy failed: {str(e)}"
            }
    
    def cleanup_temp_files(self, max_age_hours: int = 24):
        """清理暫存檔案"""
        
        try:
            cutoff_time = datetime.now() - timedelta(hours=max_age_hours)
            
            for filename in os.listdir(self.temp_storage_path):
                file_path = os.path.join(self.temp_storage_path, filename)
                
                if os.path.isfile(file_path):
                    file_mtime = datetime.fromtimestamp(os.path.getmtime(file_path))
                    
                    if file_mtime < cutoff_time:
                        try:
                            os.remove(file_path)
                            print(f"Cleaned up temp file: {filename}")
                        except Exception as e:
                            print(f"Failed to cleanup temp file {filename}: {str(e)}")
                            
        except Exception as e:
            print(f"Temp file cleanup failed: {str(e)}")
    
    def get_storage_analytics(self, user_id: int) -> Dict[str, Any]:
        """取得儲存分析資料"""
        
        try:
            user_path = self.get_user_storage_path(user_id)
            plan = subscription_service.get_user_plan(user_id)
            
            # 計算各專案的使用量
            projects_usage = {}
            total_files = 0
            total_size = 0
            
            # 取得使用者的所有專案
            projects = self.db.query(Project).filter(Project.user_id == user_id).all()
            
            for project in projects:
                project_path = self.get_project_storage_path(user_id, project.id)
                project_size = 0
                project_files = 0
                
                if os.path.exists(project_path):
                    for filename in os.listdir(project_path):
                        file_path = os.path.join(project_path, filename)
                        if os.path.isfile(file_path):
                            file_size = os.path.getsize(file_path)
                            project_size += file_size
                            project_files += 1
                
                projects_usage[project.id] = {
                    "project_name": project.name,
                    "file_count": project_files,
                    "size_bytes": project_size,
                    "size_mb": project_size / (1024 * 1024),
                    "percentage": 0  # 稍後計算
                }
                
                total_files += project_files
                total_size += project_size
            
            # 計算百分比
            for project_id in projects_usage:
                if total_size > 0:
                    projects_usage[project_id]["percentage"] = (
                        projects_usage[project_id]["size_bytes"] / total_size * 100
                    )
            
            # 計算配額使用情況
            storage_limit_gb = plan.storage_gb
            storage_limit_bytes = storage_limit_gb * 1024 * 1024 * 1024
            usage_percentage = (total_size / storage_limit_bytes * 100) if storage_limit_bytes > 0 else 0
            
            return {
                "total_files": total_files,
                "total_size_bytes": total_size,
                "total_size_mb": total_size / (1024 * 1024),
                "total_size_gb": total_size / (1024 * 1024 * 1024),
                "storage_limit_gb": storage_limit_gb,
                "usage_percentage": usage_percentage,
                "remaining_gb": max(0, storage_limit_gb - (total_size / (1024 * 1024 * 1024))),
                "projects_breakdown": projects_usage,
                "plan_name": plan.display_name
            }
            
        except Exception as e:
            return {
                "error": f"Storage analytics failed: {str(e)}"
            }
    
    def get_file_info(self, user_id: int, project_id: int, filename: str) -> Dict[str, Any]:
        """取得檔案詳細資訊"""
        
        try:
            project_path = self.get_project_storage_path(user_id, project_id)
            file_path = os.path.join(project_path, filename)
            
            if not os.path.exists(file_path):
                return {
                    "success": False,
                    "error": "File not found"
                }
            
            # 檢查存取權限
            if not file_path.startswith(self.get_user_storage_path(user_id)):
                return {
                    "success": False,
                    "error": "Access denied"
                }
            
            file_stat = os.stat(file_path)
            mime_type, _ = mimetypes.guess_type(file_path)
            file_hash = self.calculate_file_hash(file_path)
            
            # 如果是音訊檔案，嘗試取得音訊資訊
            audio_info = None
            if mime_type and mime_type.startswith("audio/"):
                try:
                    from pydub import AudioSegment
                    audio = AudioSegment.from_file(file_path)
                    audio_info = {
                        "duration_ms": len(audio),
                        "duration_seconds": len(audio) / 1000,
                        "channels": audio.channels,
                        "frame_rate": audio.frame_rate,
                        "sample_width": audio.sample_width
                    }
                except Exception as e:
                    print(f"Failed to get audio info: {str(e)}")
            
            return {
                "success": True,
                "filename": filename,
                "file_size": file_stat.st_size,
                "mime_type": mime_type,
                "file_hash": file_hash,
                "created_at": datetime.fromtimestamp(file_stat.st_ctime),
                "modified_at": datetime.fromtimestamp(file_stat.st_mtime),
                "audio_info": audio_info
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to get file info: {str(e)}"
            }

# 全域檔案管理服務實例
file_service = FileManagementService()

