from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List, Dict, Any, Optional

from models_extended import (
    Project, AudioFile, AudioVersion, get_db
)
from schemas import (
    ProjectCreate, Project as ProjectSchema,
    AudioVersion as AudioVersionSchema,
    APIResponse
)
from auth import get_current_user
from project_management import project_manager, version_manager
from utils import TrimlyException

# 建立路由器
router = APIRouter(prefix="/api/v1/projects", tags=["Project Management"])

# ==================== 專案管理 API ====================

@router.post("", response_model=ProjectSchema)
async def create_project(
    project_data: ProjectCreate,
    current_user = Depends(get_current_user),
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
    
    # 建立專案目錄結構
    project_manager.create_project_structure(current_user.id, new_project.id)
    
    return ProjectSchema.from_orm(new_project)

@router.get("", response_model=List[ProjectSchema])
async def get_projects(
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """取得使用者的所有專案"""
    
    projects = db.query(Project).filter(
        Project.user_id == current_user.id
    ).order_by(Project.updated_at.desc()).all()
    
    return [ProjectSchema.from_orm(project) for project in projects]

@router.get("/{project_id}", response_model=ProjectSchema)
async def get_project(
    project_id: int,
    current_user = Depends(get_current_user),
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

@router.put("/{project_id}", response_model=ProjectSchema)
async def update_project(
    project_id: int,
    project_data: ProjectCreate,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """更新專案資訊"""
    
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == current_user.id
    ).first()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    
    project.name = project_data.name
    project.description = project_data.description
    project.updated_at = datetime.utcnow()
    
    db.commit()
    db.refresh(project)
    
    return ProjectSchema.from_orm(project)

@router.delete("/{project_id}")
async def delete_project(
    project_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """刪除專案（包含所有相關檔案）"""
    
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == current_user.id
    ).first()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    
    # 刪除所有相關的音訊檔案和版本
    audio_files = db.query(AudioFile).filter(AudioFile.project_id == project_id).all()
    
    deleted_files = 0
    freed_space = 0
    
    for audio_file in audio_files:
        # 刪除原始檔案
        if os.path.exists(audio_file.file_path):
            freed_space += os.path.getsize(audio_file.file_path)
            os.remove(audio_file.file_path)
            deleted_files += 1
        
        # 刪除所有版本
        versions = db.query(AudioVersion).filter(AudioVersion.audio_file_id == audio_file.id).all()
        for version in versions:
            if version.file_path and os.path.exists(version.file_path):
                freed_space += os.path.getsize(version.file_path)
                os.remove(version.file_path)
                deleted_files += 1
            db.delete(version)
        
        db.delete(audio_file)
    
    # 刪除專案目錄
    import shutil
    from utils import get_upload_path, get_processed_path
    
    try:
        upload_dir = get_upload_path(current_user.id, project_id)
        if os.path.exists(upload_dir):
            shutil.rmtree(upload_dir)
        
        processed_dir = get_processed_path(current_user.id, project_id)
        if os.path.exists(processed_dir):
            shutil.rmtree(processed_dir)
    except Exception as e:
        print(f"Warning: Could not delete project directories: {e}")
    
    # 刪除專案記錄
    db.delete(project)
    db.commit()
    
    return {
        "success": True,
        "message": f"Project '{project.name}' deleted successfully",
        "deleted_files": deleted_files,
        "freed_space_mb": round(freed_space / (1024 * 1024), 2)
    }

@router.get("/{project_id}/stats")
async def get_project_stats(
    project_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """取得專案統計資訊"""
    
    try:
        stats = project_manager.get_project_stats(project_id, current_user.id, db)
        return stats
    except TrimlyException as e:
        raise HTTPException(status_code=400, detail=e.message)

# ==================== 版本控制 API ====================

@router.post("/{project_id}/audio/{audio_id}/versions")
async def create_version_from_original(
    project_id: int,
    audio_id: int,
    version_name: str = Query(..., description="Name for the new version"),
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """從原始檔案建立新版本"""
    
    try:
        result = version_manager.create_version_from_original(
            audio_id, version_name, current_user.id, db
        )
        return result
    except TrimlyException as e:
        raise HTTPException(status_code=400, detail=e.message)

@router.post("/versions/{version_id}/branch")
async def create_branch_from_version(
    version_id: int,
    new_version_name: str = Query(..., description="Name for the new branch"),
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """從現有版本建立分支"""
    
    try:
        result = version_manager.create_branch_from_version(
            version_id, new_version_name, current_user.id, db
        )
        return result
    except TrimlyException as e:
        raise HTTPException(status_code=400, detail=e.message)

@router.get("/{project_id}/audio/{audio_id}/versions")
async def get_version_history(
    project_id: int,
    audio_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """取得音訊檔案的版本歷史"""
    
    try:
        history = version_manager.get_version_history(audio_id, current_user.id, db)
        return {
            "audio_id": audio_id,
            "total_versions": len(history),
            "versions": history
        }
    except TrimlyException as e:
        raise HTTPException(status_code=400, detail=e.message)

@router.get("/versions/{version1_id}/compare/{version2_id}")
async def compare_versions(
    version1_id: int,
    version2_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """比較兩個版本"""
    
    try:
        comparison = version_manager.compare_versions(
            version1_id, version2_id, current_user.id, db
        )
        return comparison
    except TrimlyException as e:
        raise HTTPException(status_code=400, detail=e.message)

@router.delete("/versions/{version_id}")
async def delete_version(
    version_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """刪除版本"""
    
    try:
        result = version_manager.delete_version(version_id, current_user.id, db)
        return {
            "success": True,
            "message": f"Version '{result['deleted_version']}' deleted successfully",
            "freed_space_bytes": result["freed_space_bytes"]
        }
    except TrimlyException as e:
        raise HTTPException(status_code=400, detail=e.message)

# ==================== 專案清理 API ====================

@router.post("/cleanup/old-versions")
async def cleanup_old_versions(
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """清理舊版本（根據使用者方案限制）"""
    
    try:
        result = project_manager.cleanup_old_versions(current_user.id, db)
        return {
            "success": True,
            "message": "Old versions cleaned up successfully",
            "cleaned_files": result["cleaned_files"],
            "freed_space_mb": result["freed_space_mb"]
        }
    except TrimlyException as e:
        raise HTTPException(status_code=400, detail=e.message)

@router.get("/storage/usage")
async def get_storage_usage(
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """取得使用者的儲存空間使用情況"""
    
    projects = db.query(Project).filter(Project.user_id == current_user.id).all()
    
    total_size = 0
    project_details = []
    
    for project in projects:
        project_size = 0
        audio_count = 0
        version_count = 0
        
        audio_files = db.query(AudioFile).filter(AudioFile.project_id == project.id).all()
        
        for audio_file in audio_files:
            audio_count += 1
            
            # 原始檔案大小
            if os.path.exists(audio_file.file_path):
                project_size += os.path.getsize(audio_file.file_path)
            
            # 版本檔案大小
            versions = db.query(AudioVersion).filter(AudioVersion.audio_file_id == audio_file.id).all()
            for version in versions:
                version_count += 1
                if version.file_path and os.path.exists(version.file_path):
                    project_size += os.path.getsize(version.file_path)
        
        total_size += project_size
        
        project_details.append({
            "project_id": project.id,
            "project_name": project.name,
            "size_mb": round(project_size / (1024 * 1024), 2),
            "audio_files": audio_count,
            "versions": version_count
        })
    
    return {
        "total_size_mb": round(total_size / (1024 * 1024), 2),
        "total_projects": len(projects),
        "projects": project_details
    }

