from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, BackgroundTasks
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
import os
import tempfile
import shutil
from datetime import datetime

from models_extended import User, Project, AudioFile, get_db
from auth import get_current_user
from file_management import file_service
from subscription_service import subscription_service
from utils import safe_json_loads, safe_json_dumps

# 建立路由器
router = APIRouter(prefix="/api/v1/files", tags=["File Management"])

# Pydantic 模型
class FileUploadResponse(BaseModel):
    success: bool
    file_id: Optional[int] = None
    filename: Optional[str] = None
    file_size: Optional[int] = None
    message: Optional[str] = None
    error: Optional[str] = None

class FileInfoResponse(BaseModel):
    success: bool
    file_info: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

class StorageAnalyticsResponse(BaseModel):
    total_files: int
    total_size_gb: float
    storage_limit_gb: float
    usage_percentage: float
    remaining_gb: float
    projects_breakdown: Dict[str, Any]
    plan_name: str

class FileMoveRequest(BaseModel):
    target_project_id: int

class FileCopyRequest(BaseModel):
    target_project_id: int
    new_filename: Optional[str] = None

# ==================== 檔案上傳 API ====================

@router.post("/upload/{project_id}", response_model=FileUploadResponse)
async def upload_audio_file(
    project_id: int,
    file: UploadFile = File(...),
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
    background_tasks: BackgroundTasks = Depends()
):
    """上傳音訊檔案到專案"""
    
    # 檢查專案是否存在且屬於該使用者
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
    if not file.content_type or not file.content_type.startswith("audio/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid file type. Expected audio file, got: {file.content_type}"
        )
    
    # 建立暫存檔案
    temp_file_path = None
    try:
        # 建立暫存檔案
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1]) as temp_file:
            temp_file_path = temp_file.name
            
            # 複製上傳的檔案內容
            shutil.copyfileobj(file.file, temp_file)
        
        # 儲存檔案到永久位置
        storage_result = file_service.store_audio_file(
            temp_file_path,
            current_user.id,
            project_id,
            file.filename
        )
        
        if not storage_result["success"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=storage_result["error"]
            )
        
        # 建立資料庫記錄
        audio_file = AudioFile(
            user_id=current_user.id,
            project_id=project_id,
            original_filename=file.filename,
            filename=storage_result["filename"],
            file_path=storage_result["file_path"],
            file_size=storage_result["file_size"],
            file_hash=storage_result["file_hash"],
            mime_type=storage_result["mime_type"],
            status="uploaded"
        )
        
        db.add(audio_file)
        db.commit()
        db.refresh(audio_file)
        
        # 安排清理暫存檔案
        if temp_file_path:
            background_tasks.add_task(lambda: os.remove(temp_file_path) if os.path.exists(temp_file_path) else None)
        
        return FileUploadResponse(
            success=True,
            file_id=audio_file.id,
            filename=storage_result["filename"],
            file_size=storage_result["file_size"],
            message="File uploaded successfully"
        )
        
    except HTTPException:
        # 清理暫存檔案
        if temp_file_path and os.path.exists(temp_file_path):
            os.remove(temp_file_path)
        raise
    except Exception as e:
        # 清理暫存檔案
        if temp_file_path and os.path.exists(temp_file_path):
            os.remove(temp_file_path)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"File upload failed: {str(e)}"
        )

# ==================== 檔案資訊查詢 API ====================

@router.get("/info/{project_id}/{filename}", response_model=FileInfoResponse)
async def get_file_info(
    project_id: int,
    filename: str,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """取得檔案詳細資訊"""
    
    # 檢查專案是否存在且屬於該使用者
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == current_user.id
    ).first()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    
    # 取得檔案資訊
    result = file_service.get_file_info(current_user.id, project_id, filename)
    
    if not result["success"]:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=result["error"]
        )
    
    return FileInfoResponse(
        success=True,
        file_info=result
    )

@router.get("/list/{project_id}")
async def list_project_files(
    project_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """列出專案中的所有檔案"""
    
    # 檢查專案是否存在且屬於該使用者
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == current_user.id
    ).first()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    
    # 取得檔案列表
    files = file_service.get_project_files(current_user.id, project_id)
    
    # 同時從資料庫取得音訊檔案記錄
    audio_files = db.query(AudioFile).filter(
        AudioFile.project_id == project_id,
        AudioFile.user_id == current_user.id
    ).all()
    
    # 合併檔案系統和資料庫資訊
    file_list = []
    for file_info in files:
        # 尋找對應的資料庫記錄
        audio_file = next((af for af in audio_files if af.filename == file_info["filename"]), None)
        
        file_data = {
            "filename": file_info["filename"],
            "file_size": file_info["file_size"],
            "mime_type": file_info["mime_type"],
            "created_at": file_info["created_at"].isoformat(),
            "modified_at": file_info["modified_at"].isoformat()
        }
        
        if audio_file:
            file_data.update({
                "id": audio_file.id,
                "original_filename": audio_file.original_filename,
                "status": audio_file.status,
                "has_transcript": bool(audio_file.transcript_data),
                "processing_status": audio_file.processing_status
            })
        
        file_list.append(file_data)
    
    return {
        "project_id": project_id,
        "project_name": project.name,
        "files": file_list,
        "total_files": len(file_list),
        "total_size": sum(f["file_size"] for f in file_list)
    }

# ==================== 檔案操作 API ====================

@router.delete("/{project_id}/{filename}")
async def delete_file(
    project_id: int,
    filename: str,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """刪除檔案"""
    
    # 檢查專案是否存在且屬於該使用者
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == current_user.id
    ).first()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    
    # 從資料庫刪除記錄
    audio_file = db.query(AudioFile).filter(
        AudioFile.project_id == project_id,
        AudioFile.user_id == current_user.id,
        AudioFile.filename == filename
    ).first()
    
    if audio_file:
        db.delete(audio_file)
        db.commit()
    
    # 從檔案系統刪除檔案
    result = file_service.delete_file(current_user.id, project_id, filename)
    
    if not result["success"]:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=result["error"]
        )
    
    return {
        "message": "File deleted successfully",
        "freed_space": result["freed_space"]
    }

@router.post("/{project_id}/{filename}/move")
async def move_file(
    project_id: int,
    filename: str,
    request: FileMoveRequest,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """移動檔案到另一個專案"""
    
    # 檢查來源專案
    source_project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == current_user.id
    ).first()
    
    if not source_project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Source project not found"
        )
    
    # 檢查目標專案
    target_project = db.query(Project).filter(
        Project.id == request.target_project_id,
        Project.user_id == current_user.id
    ).first()
    
    if not target_project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Target project not found"
        )
    
    # 移動檔案
    result = file_service.move_file(
        current_user.id,
        project_id,
        request.target_project_id,
        filename
    )
    
    if not result["success"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result["error"]
        )
    
    # 更新資料庫記錄
    audio_file = db.query(AudioFile).filter(
        AudioFile.project_id == project_id,
        AudioFile.user_id == current_user.id,
        AudioFile.filename == filename
    ).first()
    
    if audio_file:
        audio_file.project_id = request.target_project_id
        audio_file.file_path = result["new_path"]
        db.commit()
    
    return {
        "message": "File moved successfully",
        "new_project_id": request.target_project_id,
        "new_path": result["new_path"]
    }

@router.post("/{project_id}/{filename}/copy")
async def copy_file(
    project_id: int,
    filename: str,
    request: FileCopyRequest,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """複製檔案到另一個專案"""
    
    # 檢查來源專案
    source_project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == current_user.id
    ).first()
    
    if not source_project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Source project not found"
        )
    
    # 檢查目標專案
    target_project = db.query(Project).filter(
        Project.id == request.target_project_id,
        Project.user_id == current_user.id
    ).first()
    
    if not target_project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Target project not found"
        )
    
    # 複製檔案
    result = file_service.copy_file(
        current_user.id,
        project_id,
        request.target_project_id,
        filename,
        request.new_filename
    )
    
    if not result["success"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result["error"]
        )
    
    # 建立新的資料庫記錄
    original_audio_file = db.query(AudioFile).filter(
        AudioFile.project_id == project_id,
        AudioFile.user_id == current_user.id,
        AudioFile.filename == filename
    ).first()
    
    if original_audio_file:
        new_audio_file = AudioFile(
            user_id=current_user.id,
            project_id=request.target_project_id,
            original_filename=original_audio_file.original_filename,
            filename=result["new_filename"],
            file_path=result["new_path"],
            file_size=original_audio_file.file_size,
            file_hash=original_audio_file.file_hash,
            mime_type=original_audio_file.mime_type,
            status="uploaded"
        )
        
        db.add(new_audio_file)
        db.commit()
        db.refresh(new_audio_file)
    
    return {
        "message": "File copied successfully",
        "new_project_id": request.target_project_id,
        "new_filename": result["new_filename"],
        "new_path": result["new_path"]
    }

# ==================== 儲存分析 API ====================

@router.get("/storage/analytics", response_model=StorageAnalyticsResponse)
async def get_storage_analytics(
    current_user = Depends(get_current_user)
):
    """取得儲存使用分析"""
    
    analytics = file_service.get_storage_analytics(current_user.id)
    
    if "error" in analytics:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=analytics["error"]
        )
    
    return StorageAnalyticsResponse(**analytics)

@router.get("/storage/quota")
async def get_storage_quota(
    current_user = Depends(get_current_user)
):
    """取得儲存配額資訊"""
    
    plan = subscription_service.get_user_plan(current_user.id)
    current_usage_bytes = file_service.get_user_storage_usage(current_user.id)
    current_usage_gb = current_usage_bytes / (1024 * 1024 * 1024)
    
    return {
        "plan_name": plan.display_name,
        "storage_limit_gb": plan.storage_gb,
        "storage_used_gb": current_usage_gb,
        "storage_remaining_gb": max(0, plan.storage_gb - current_usage_gb),
        "usage_percentage": (current_usage_gb / plan.storage_gb * 100) if plan.storage_gb > 0 else 0,
        "storage_used_bytes": current_usage_bytes,
        "storage_limit_bytes": plan.storage_gb * 1024 * 1024 * 1024
    }

# ==================== 檔案下載 API ====================

@router.get("/download/{project_id}/{filename}")
async def download_file(
    project_id: int,
    filename: str,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """下載檔案"""
    
    # 檢查專案是否存在且屬於該使用者
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == current_user.id
    ).first()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    
    # 取得檔案路徑
    project_path = file_service.get_project_storage_path(current_user.id, project_id)
    file_path = os.path.join(project_path, filename)
    
    if not os.path.exists(file_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found"
        )
    
    # 檢查存取權限
    user_path = file_service.get_user_storage_path(current_user.id)
    if not file_path.startswith(user_path):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )
    
    # 取得原始檔名
    audio_file = db.query(AudioFile).filter(
        AudioFile.project_id == project_id,
        AudioFile.user_id == current_user.id,
        AudioFile.filename == filename
    ).first()
    
    download_filename = audio_file.original_filename if audio_file else filename
    
    # 確定 MIME 類型
    import mimetypes
    mime_type, _ = mimetypes.guess_type(file_path)
    if not mime_type:
        mime_type = "application/octet-stream"
    
    return FileResponse(
        path=file_path,
        filename=download_filename,
        media_type=mime_type
    )

# ==================== 批量操作 API ====================

@router.post("/batch/delete")
async def batch_delete_files(
    file_list: List[Dict[str, Any]],  # [{"project_id": 1, "filename": "file.mp3"}, ...]
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """批量刪除檔案"""
    
    results = []
    total_freed_space = 0
    
    for file_item in file_list:
        project_id = file_item.get("project_id")
        filename = file_item.get("filename")
        
        if not project_id or not filename:
            results.append({
                "project_id": project_id,
                "filename": filename,
                "success": False,
                "error": "Missing project_id or filename"
            })
            continue
        
        try:
            # 檢查專案權限
            project = db.query(Project).filter(
                Project.id == project_id,
                Project.user_id == current_user.id
            ).first()
            
            if not project:
                results.append({
                    "project_id": project_id,
                    "filename": filename,
                    "success": False,
                    "error": "Project not found"
                })
                continue
            
            # 從資料庫刪除記錄
            audio_file = db.query(AudioFile).filter(
                AudioFile.project_id == project_id,
                AudioFile.user_id == current_user.id,
                AudioFile.filename == filename
            ).first()
            
            if audio_file:
                db.delete(audio_file)
                db.commit()
            
            # 從檔案系統刪除檔案
            result = file_service.delete_file(current_user.id, project_id, filename)
            
            if result["success"]:
                total_freed_space += result["freed_space"]
                results.append({
                    "project_id": project_id,
                    "filename": filename,
                    "success": True,
                    "freed_space": result["freed_space"]
                })
            else:
                results.append({
                    "project_id": project_id,
                    "filename": filename,
                    "success": False,
                    "error": result["error"]
                })
                
        except Exception as e:
            results.append({
                "project_id": project_id,
                "filename": filename,
                "success": False,
                "error": str(e)
            })
    
    successful_deletions = len([r for r in results if r["success"]])
    
    return {
        "message": f"Batch deletion completed. {successful_deletions}/{len(file_list)} files deleted.",
        "total_freed_space": total_freed_space,
        "results": results
    }

# ==================== 清理功能 API ====================

@router.post("/cleanup/temp")
async def cleanup_temp_files(
    current_user = Depends(get_current_user)
):
    """清理暫存檔案（僅管理員）"""
    
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    
    file_service.cleanup_temp_files()
    
    return {
        "message": "Temporary files cleanup completed"
    }

