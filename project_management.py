import os
import shutil
from typing import List, Dict, Any, Optional
from datetime import datetime
from sqlalchemy.orm import Session

from models_extended import (
    Project, AudioFile, AudioVersion, User, UsageLog, SessionLocal
)
from utils import (
    calculate_quota_usage, get_upload_path, get_processed_path,
    safe_json_loads, safe_json_dumps, TrimlyException
)

class ProjectManager:
    """專案管理器"""
    
    def __init__(self):
        pass
    
    def create_project_structure(self, user_id: int, project_id: int) -> Dict[str, str]:
        """為專案建立完整的目錄結構"""
        
        base_paths = {
            "uploads": get_upload_path(user_id, project_id),
            "processed": get_processed_path(user_id, project_id),
            "exports": os.path.join(get_processed_path(user_id, project_id), "exports"),
            "backups": os.path.join(get_processed_path(user_id, project_id), "backups")
        }
        
        # 建立所有必要的目錄
        for path_type, path in base_paths.items():
            os.makedirs(path, exist_ok=True)
        
        return base_paths
    
    def get_project_stats(self, project_id: int, user_id: int, db: Session) -> Dict[str, Any]:
        """取得專案統計資訊"""
        
        # 驗證專案屬於使用者
        project = db.query(Project).filter(
            Project.id == project_id,
            Project.user_id == user_id
        ).first()
        
        if not project:
            raise TrimlyException("Project not found", "PROJECT_NOT_FOUND")
        
        # 統計音訊檔案
        audio_files = db.query(AudioFile).filter(AudioFile.project_id == project_id).all()
        total_audio_files = len(audio_files)
        
        # 統計總時長
        total_duration = sum(
            audio.duration_seconds or 0 for audio in audio_files
        )
        
        # 統計版本數量
        total_versions = 0
        for audio in audio_files:
            versions = db.query(AudioVersion).filter(AudioVersion.audio_file_id == audio.id).count()
            total_versions += versions
        
        # 統計檔案大小
        total_size = 0
        for audio in audio_files:
            if os.path.exists(audio.file_path):
                total_size += os.path.getsize(audio.file_path)
            
            # 加上版本檔案大小
            versions = db.query(AudioVersion).filter(AudioVersion.audio_file_id == audio.id).all()
            for version in versions:
                if version.file_path and os.path.exists(version.file_path):
                    total_size += os.path.getsize(version.file_path)
        
        # 統計使用量
        usage_logs = db.query(UsageLog).filter(UsageLog.user_id == user_id).all()
        
        transcription_minutes = sum(
            log.duration_seconds / 60 for log in usage_logs 
            if log.action == "transcribe"
        )
        
        editing_operations = len([
            log for log in usage_logs if log.action == "edit"
        ])
        
        ai_enhancements = len([
            log for log in usage_logs if log.action == "enhance"
        ])
        
        return {
            "project_id": project_id,
            "project_name": project.name,
            "created_at": project.created_at,
            "updated_at": project.updated_at,
            "total_audio_files": total_audio_files,
            "total_versions": total_versions,
            "total_duration_minutes": round(total_duration / 60, 2),
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "transcription_minutes_used": round(transcription_minutes, 2),
            "editing_operations_count": editing_operations,
            "ai_enhancements_count": ai_enhancements
        }
    
    def cleanup_old_versions(self, user_id: int, db: Session) -> Dict[str, Any]:
        """清理舊版本（根據使用者方案限制）"""
        
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise TrimlyException("User not found", "USER_NOT_FOUND")
        
        quotas = calculate_quota_usage(user.role)
        max_versions = quotas.get("max_versions", 3)
        
        if max_versions == -1:  # 無限制
            return {"cleaned_files": 0, "freed_space_mb": 0}
        
        cleaned_files = 0
        freed_space = 0
        
        # 取得使用者的所有專案
        projects = db.query(Project).filter(Project.user_id == user_id).all()
        
        for project in projects:
            audio_files = db.query(AudioFile).filter(AudioFile.project_id == project.id).all()
            
            for audio_file in audio_files:
                # 取得所有版本，按建立時間排序
                versions = db.query(AudioVersion).filter(
                    AudioVersion.audio_file_id == audio_file.id
                ).order_by(AudioVersion.created_at.desc()).all()
                
                # 如果版本數超過限制，刪除最舊的版本
                if len(versions) > max_versions:
                    versions_to_delete = versions[max_versions:]
                    
                    for version in versions_to_delete:
                        # 刪除檔案
                        if version.file_path and os.path.exists(version.file_path):
                            file_size = os.path.getsize(version.file_path)
                            os.remove(version.file_path)
                            freed_space += file_size
                            cleaned_files += 1
                        
                        # 刪除資料庫記錄
                        db.delete(version)
        
        db.commit()
        
        return {
            "cleaned_files": cleaned_files,
            "freed_space_mb": round(freed_space / (1024 * 1024), 2)
        }

class VersionManager:
    """版本控制管理器"""
    
    def __init__(self):
        pass
    
    def create_version_from_original(self, audio_file_id: int, version_name: str, 
                                   user_id: int, db: Session) -> Dict[str, Any]:
        """從原始檔案建立新版本"""
        
        audio_file = db.query(AudioFile).join(Project).filter(
            AudioFile.id == audio_file_id,
            Project.user_id == user_id
        ).first()
        
        if not audio_file:
            raise TrimlyException("Audio file not found", "AUDIO_FILE_NOT_FOUND")
        
        # 檢查版本名稱是否已存在
        existing_version = db.query(AudioVersion).filter(
            AudioVersion.audio_file_id == audio_file_id,
            AudioVersion.version_name == version_name
        ).first()
        
        if existing_version:
            raise TrimlyException(f"Version '{version_name}' already exists", "VERSION_EXISTS")
        
        # 複製原始檔案
        output_dir = get_processed_path(user_id, audio_file.project_id)
        output_filename = f"{version_name}_{audio_file.filename}"
        output_path = os.path.join(output_dir, output_filename)
        
        shutil.copy2(audio_file.file_path, output_path)
        
        # 建立版本記錄
        audio_version = AudioVersion(
            audio_file_id=audio_file_id,
            version_name=version_name,
            file_path=output_path,
            edit_operations=safe_json_dumps([]),
            edit_summary="Copy of original file",
            duration_seconds=audio_file.duration_seconds,
            file_size_bytes=os.path.getsize(output_path)
        )
        
        db.add(audio_version)
        db.commit()
        db.refresh(audio_version)
        
        return {
            "version_id": audio_version.id,
            "version_name": version_name,
            "file_path": output_path,
            "created_at": audio_version.created_at
        }
    
    def create_branch_from_version(self, source_version_id: int, new_version_name: str,
                                 user_id: int, db: Session) -> Dict[str, Any]:
        """從現有版本建立分支"""
        
        source_version = db.query(AudioVersion).join(AudioFile).join(Project).filter(
            AudioVersion.id == source_version_id,
            Project.user_id == user_id
        ).first()
        
        if not source_version:
            raise TrimlyException("Source version not found", "VERSION_NOT_FOUND")
        
        # 檢查新版本名稱是否已存在
        existing_version = db.query(AudioVersion).filter(
            AudioVersion.audio_file_id == source_version.audio_file_id,
            AudioVersion.version_name == new_version_name
        ).first()
        
        if existing_version:
            raise TrimlyException(f"Version '{new_version_name}' already exists", "VERSION_EXISTS")
        
        # 複製檔案
        audio_file = source_version.audio_file
        output_dir = get_processed_path(user_id, audio_file.project_id)
        output_filename = f"{new_version_name}_{audio_file.filename}"
        output_path = os.path.join(output_dir, output_filename)
        
        shutil.copy2(source_version.file_path, output_path)
        
        # 建立新版本記錄
        new_version = AudioVersion(
            audio_file_id=source_version.audio_file_id,
            version_name=new_version_name,
            file_path=output_path,
            edit_operations=source_version.edit_operations,
            edit_summary=f"Branch from {source_version.version_name}",
            duration_seconds=source_version.duration_seconds,
            file_size_bytes=os.path.getsize(output_path)
        )
        
        db.add(new_version)
        db.commit()
        db.refresh(new_version)
        
        return {
            "version_id": new_version.id,
            "version_name": new_version_name,
            "source_version": source_version.version_name,
            "file_path": output_path,
            "created_at": new_version.created_at
        }
    
    def get_version_history(self, audio_file_id: int, user_id: int, db: Session) -> List[Dict[str, Any]]:
        """取得版本歷史"""
        
        # 驗證音訊檔案屬於使用者
        audio_file = db.query(AudioFile).join(Project).filter(
            AudioFile.id == audio_file_id,
            Project.user_id == user_id
        ).first()
        
        if not audio_file:
            raise TrimlyException("Audio file not found", "AUDIO_FILE_NOT_FOUND")
        
        versions = db.query(AudioVersion).filter(
            AudioVersion.audio_file_id == audio_file_id
        ).order_by(AudioVersion.created_at.desc()).all()
        
        history = []
        for version in versions:
            edit_operations = safe_json_loads(version.edit_operations, [])
            
            history.append({
                "version_id": version.id,
                "version_name": version.version_name,
                "edit_summary": version.edit_summary,
                "duration_seconds": version.duration_seconds,
                "file_size_bytes": version.file_size_bytes,
                "edit_operations_count": len(edit_operations),
                "created_at": version.created_at,
                "can_download": os.path.exists(version.file_path) if version.file_path else False
            })
        
        return history
    
    def compare_versions(self, version1_id: int, version2_id: int, user_id: int, 
                        db: Session) -> Dict[str, Any]:
        """比較兩個版本"""
        
        version1 = db.query(AudioVersion).join(AudioFile).join(Project).filter(
            AudioVersion.id == version1_id,
            Project.user_id == user_id
        ).first()
        
        version2 = db.query(AudioVersion).join(AudioFile).join(Project).filter(
            AudioVersion.id == version2_id,
            Project.user_id == user_id
        ).first()
        
        if not version1 or not version2:
            raise TrimlyException("One or both versions not found", "VERSION_NOT_FOUND")
        
        if version1.audio_file_id != version2.audio_file_id:
            raise TrimlyException("Versions must belong to the same audio file", "INVALID_COMPARISON")
        
        # 解析編輯操作
        ops1 = safe_json_loads(version1.edit_operations, [])
        ops2 = safe_json_loads(version2.edit_operations, [])
        
        return {
            "version1": {
                "id": version1.id,
                "name": version1.version_name,
                "duration": version1.duration_seconds,
                "size": version1.file_size_bytes,
                "operations_count": len(ops1),
                "created_at": version1.created_at
            },
            "version2": {
                "id": version2.id,
                "name": version2.version_name,
                "duration": version2.duration_seconds,
                "size": version2.file_size_bytes,
                "operations_count": len(ops2),
                "created_at": version2.created_at
            },
            "differences": {
                "duration_diff": (version2.duration_seconds or 0) - (version1.duration_seconds or 0),
                "size_diff": (version2.file_size_bytes or 0) - (version1.file_size_bytes or 0),
                "operations_diff": len(ops2) - len(ops1)
            }
        }
    
    def delete_version(self, version_id: int, user_id: int, db: Session) -> Dict[str, Any]:
        """刪除版本"""
        
        version = db.query(AudioVersion).join(AudioFile).join(Project).filter(
            AudioVersion.id == version_id,
            Project.user_id == user_id
        ).first()
        
        if not version:
            raise TrimlyException("Version not found", "VERSION_NOT_FOUND")
        
        # 刪除檔案
        freed_space = 0
        if version.file_path and os.path.exists(version.file_path):
            freed_space = os.path.getsize(version.file_path)
            os.remove(version.file_path)
        
        # 刪除資料庫記錄
        version_name = version.version_name
        db.delete(version)
        db.commit()
        
        return {
            "deleted_version": version_name,
            "freed_space_bytes": freed_space
        }

# 全域實例
project_manager = ProjectManager()
version_manager = VersionManager()

