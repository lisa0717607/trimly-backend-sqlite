from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks, Response
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
import os
import tempfile

from models_extended import User, Project, AudioFile, get_db
from auth import get_current_user
from export_service import export_service
from file_management import file_service
from subscription_service import subscription_service
from utils import safe_json_loads, safe_json_dumps

# 建立路由器
router = APIRouter(prefix="/api/v1/export", tags=["Export"])

# Pydantic 模型
class AudioExportRequest(BaseModel):
    audio_file_id: int
    output_format: str  # mp3, wav, flac, aac, ogg
    quality_settings: Optional[Dict[str, Any]] = None

class TranscriptExportRequest(BaseModel):
    audio_file_id: int
    format: str  # txt, srt, vtt, docx, json
    include_timestamps: Optional[bool] = False
    include_speaker_labels: Optional[bool] = False
    include_metadata: Optional[bool] = True

class BatchExportRequest(BaseModel):
    audio_file_ids: List[int]
    export_types: List[str]  # 可包含 audio_mp3, audio_wav, transcript_txt, transcript_srt 等
    create_package: Optional[bool] = True
    package_name: Optional[str] = None

class ExportResponse(BaseModel):
    success: bool
    export_id: Optional[str] = None
    download_url: Optional[str] = None
    filename: Optional[str] = None
    file_size: Optional[int] = None
    format: Optional[str] = None
    expires_at: Optional[str] = None
    error: Optional[str] = None

# ==================== 音訊匯出 API ====================

@router.post("/audio", response_model=ExportResponse)
async def export_audio(
    request: AudioExportRequest,
    background_tasks: BackgroundTasks,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """匯出音訊檔案"""
    
    # 檢查音訊檔案是否存在且屬於該使用者
    audio_file = db.query(AudioFile).filter(
        AudioFile.id == request.audio_file_id,
        AudioFile.user_id == current_user.id
    ).first()
    
    if not audio_file:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Audio file not found"
        )
    
    # 檢查檔案是否存在
    if not os.path.exists(audio_file.file_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Audio file not found on disk"
        )
    
    # 檢查配額
    plan = subscription_service.get_user_plan(current_user.id)
    if not subscription_service.check_quota(current_user.id, "exports", 1):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Export quota exceeded for {plan.display_name} plan"
        )
    
    # 執行音訊匯出
    result = await export_service.export_audio(
        audio_file.file_path,
        request.output_format,
        request.quality_settings
    )
    
    if not result["success"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result["error"]
        )
    
    # 消耗配額
    subscription_service.consume_quota(current_user.id, "exports", 1)
    
    # 安排清理暫存檔案
    background_tasks.add_task(
        export_service.cleanup_temp_files, 
        [result["output_path"]]
    )
    
    return ExportResponse(
        success=True,
        download_url=f"/api/v1/export/download/{os.path.basename(result['output_path'])}",
        filename=result["filename"],
        file_size=result["file_size"],
        format=result["format"],
        expires_at=(datetime.utcnow() + timedelta(hours=24)).isoformat()
    )

# ==================== 逐字稿匯出 API ====================

@router.post("/transcript", response_model=ExportResponse)
async def export_transcript(
    request: TranscriptExportRequest,
    background_tasks: BackgroundTasks,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """匯出逐字稿"""
    
    # 檢查音訊檔案是否存在且屬於該使用者
    audio_file = db.query(AudioFile).filter(
        AudioFile.id == request.audio_file_id,
        AudioFile.user_id == current_user.id
    ).first()
    
    if not audio_file:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Audio file not found"
        )
    
    # 檢查是否有逐字稿資料
    if not audio_file.transcript_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No transcript data available for this audio file"
        )
    
    # 檢查配額
    plan = subscription_service.get_user_plan(current_user.id)
    if not subscription_service.check_quota(current_user.id, "exports", 1):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Export quota exceeded for {plan.display_name} plan"
        )
    
    # 解析逐字稿資料
    transcript_data = safe_json_loads(audio_file.transcript_data)
    
    # 取得專案資訊（用於 DOCX 匯出）
    project = db.query(Project).filter(Project.id == audio_file.project_id).first()
    project_info = {
        "name": project.name if project else "Unknown Project",
        "created_at": project.created_at.isoformat() if project else None,
        "duration": transcript_data.get("duration", 0)
    }
    
    # 根據格式執行匯出
    result = None
    
    if request.format == "txt":
        result = export_service.export_transcript_txt(
            transcript_data,
            request.include_timestamps,
            request.include_speaker_labels
        )
    elif request.format == "srt":
        result = export_service.export_transcript_srt(transcript_data)
    elif request.format == "vtt":
        result = export_service.export_transcript_vtt(transcript_data)
    elif request.format == "docx":
        result = export_service.export_transcript_docx(transcript_data, project_info)
    elif request.format == "json":
        result = export_service.export_transcript_json(
            transcript_data,
            request.include_metadata
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported transcript format: {request.format}"
        )
    
    if not result["success"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result["error"]
        )
    
    # 消耗配額
    subscription_service.consume_quota(current_user.id, "exports", 1)
    
    # 安排清理暫存檔案
    background_tasks.add_task(
        export_service.cleanup_temp_files, 
        [result["output_path"]]
    )
    
    return ExportResponse(
        success=True,
        download_url=f"/api/v1/export/download/{os.path.basename(result['output_path'])}",
        filename=result["filename"],
        file_size=os.path.getsize(result["output_path"]),
        format=result["format"],
        expires_at=(datetime.utcnow() + timedelta(hours=24)).isoformat()
    )

# ==================== 批量匯出 API ====================

@router.post("/batch", response_model=ExportResponse)
async def batch_export(
    request: BatchExportRequest,
    background_tasks: BackgroundTasks,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """批量匯出多個檔案"""
    
    # 檢查音訊檔案是否都存在且屬於該使用者
    audio_files = db.query(AudioFile).filter(
        AudioFile.id.in_(request.audio_file_ids),
        AudioFile.user_id == current_user.id
    ).all()
    
    if len(audio_files) != len(request.audio_file_ids):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Some audio files not found"
        )
    
    # 檢查配額
    total_exports = len(request.audio_file_ids) * len(request.export_types)
    plan = subscription_service.get_user_plan(current_user.id)
    
    if not subscription_service.check_quota(current_user.id, "exports", total_exports):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Export quota exceeded. Requested: {total_exports}, Available: {plan.exports_per_month - subscription_service.get_usage(current_user.id, 'exports')}"
        )
    
    # 執行批量匯出
    exports = []
    temp_files = []
    
    for audio_file in audio_files:
        for export_type in request.export_types:
            try:
                if export_type.startswith("audio_"):
                    # 音訊匯出
                    format_name = export_type.replace("audio_", "")
                    result = await export_service.export_audio(
                        audio_file.file_path,
                        format_name
                    )
                    
                elif export_type.startswith("transcript_"):
                    # 逐字稿匯出
                    if not audio_file.transcript_data:
                        continue  # 跳過沒有逐字稿的檔案
                    
                    format_name = export_type.replace("transcript_", "")
                    transcript_data = safe_json_loads(audio_file.transcript_data)
                    
                    if format_name == "txt":
                        result = export_service.export_transcript_txt(transcript_data)
                    elif format_name == "srt":
                        result = export_service.export_transcript_srt(transcript_data)
                    elif format_name == "vtt":
                        result = export_service.export_transcript_vtt(transcript_data)
                    elif format_name == "docx":
                        project = db.query(Project).filter(Project.id == audio_file.project_id).first()
                        project_info = {
                            "name": f"{project.name if project else 'Unknown'} - {audio_file.original_filename}",
                            "created_at": project.created_at.isoformat() if project else None,
                            "duration": transcript_data.get("duration", 0)
                        }
                        result = export_service.export_transcript_docx(transcript_data, project_info)
                    elif format_name == "json":
                        result = export_service.export_transcript_json(transcript_data)
                    else:
                        continue
                
                if result and result["success"]:
                    exports.append(result)
                    temp_files.append(result["output_path"])
                    
            except Exception as e:
                print(f"Export failed for {audio_file.original_filename} ({export_type}): {str(e)}")
                continue
    
    if not exports:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No files could be exported"
        )
    
    # 建立套件（如果請求）
    if request.create_package and len(exports) > 1:
        package_name = request.package_name or f"trimly_export_{current_user.id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        package_result = export_service.create_export_package(exports, package_name)
        
        if package_result["success"]:
            # 消耗配額
            subscription_service.consume_quota(current_user.id, "exports", total_exports)
            
            # 安排清理暫存檔案
            background_tasks.add_task(
                export_service.cleanup_temp_files, 
                temp_files + [package_result["package_path"]]
            )
            
            return ExportResponse(
                success=True,
                download_url=f"/api/v1/export/download/{package_result['package_filename']}",
                filename=package_result["package_filename"],
                file_size=package_result["package_size"],
                format="zip",
                expires_at=(datetime.utcnow() + timedelta(hours=24)).isoformat()
            )
    
    # 如果只有一個檔案或不建立套件，返回第一個匯出結果
    first_export = exports[0]
    
    # 消耗配額
    subscription_service.consume_quota(current_user.id, "exports", len(exports))
    
    # 安排清理暫存檔案
    background_tasks.add_task(
        export_service.cleanup_temp_files, 
        temp_files
    )
    
    return ExportResponse(
        success=True,
        download_url=f"/api/v1/export/download/{os.path.basename(first_export['output_path'])}",
        filename=first_export["filename"],
        file_size=first_export.get("file_size", os.path.getsize(first_export["output_path"])),
        format=first_export["format"],
        expires_at=(datetime.utcnow() + timedelta(hours=24)).isoformat()
    )

# ==================== 檔案下載 API ====================

@router.get("/download/{filename}")
async def download_file(
    filename: str,
    current_user = Depends(get_current_user)
):
    """下載匯出的檔案"""
    
    file_path = f"/tmp/{filename}"
    
    if not os.path.exists(file_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found or expired"
        )
    
    # 檢查檔案是否過期（24小時）
    file_age = datetime.utcnow() - datetime.fromtimestamp(os.path.getmtime(file_path))
    if file_age > timedelta(hours=24):
        try:
            os.remove(file_path)
        except:
            pass
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="File has expired"
        )
    
    # 確定 MIME 類型
    import mimetypes
    mime_type, _ = mimetypes.guess_type(file_path)
    if not mime_type:
        mime_type = "application/octet-stream"
    
    return FileResponse(
        path=file_path,
        filename=filename,
        media_type=mime_type
    )

# ==================== 匯出格式和限制查詢 API ====================

@router.get("/formats")
async def get_supported_formats(
    current_user = Depends(get_current_user)
):
    """取得支援的匯出格式"""
    
    formats = export_service.get_supported_formats()
    plan = subscription_service.get_user_plan(current_user.id)
    
    # 根據訂閱方案限制某些格式
    if plan.name == "free":
        # 免費版限制某些高品質格式
        restricted_audio = ["flac"]
        for format_name in restricted_audio:
            if format_name in formats["audio_formats"]:
                formats["audio_formats"][format_name]["restricted"] = True
                formats["audio_formats"][format_name]["restriction_reason"] = "Available in paid plans"
    
    return {
        "supported_formats": formats,
        "plan_restrictions": {
            "plan_name": plan.display_name,
            "exports_per_month": plan.exports_per_month,
            "exports_used": subscription_service.get_usage(current_user.id, "exports"),
            "exports_remaining": plan.exports_per_month - subscription_service.get_usage(current_user.id, "exports")
        }
    }

@router.get("/quota")
async def get_export_quota(
    current_user = Depends(get_current_user)
):
    """取得匯出配額資訊"""
    
    plan = subscription_service.get_user_plan(current_user.id)
    usage = subscription_service.get_usage(current_user.id, "exports")
    
    return {
        "plan_name": plan.display_name,
        "exports_limit": plan.exports_per_month,
        "exports_used": usage,
        "exports_remaining": max(0, plan.exports_per_month - usage),
        "usage_percentage": (usage / plan.exports_per_month * 100) if plan.exports_per_month > 0 else 0,
        "reset_date": subscription_service.get_quota_reset_date(current_user.id)
    }

# ==================== 匯出歷史 API ====================

@router.get("/history")
async def get_export_history(
    limit: int = 50,
    current_user = Depends(get_current_user)
):
    """取得匯出歷史記錄"""
    
    # 這裡應該從資料庫讀取匯出歷史
    # 為了簡化，返回模擬資料
    
    return {
        "export_history": [],
        "total_exports": 0,
        "message": "Export history tracking will be implemented in future updates"
    }

