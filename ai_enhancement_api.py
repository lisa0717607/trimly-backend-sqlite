from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks, Query
from sqlalchemy.orm import Session
from typing import List, Dict, Any, Optional

from models_extended import (
    AudioFile, Transcript, AIEnhancement, ContentSummary, Project, get_db
)
from schemas import (
    AIEnhancementCreate, AIEnhancement as AIEnhancementSchema,
    ContentSummaryCreate, ContentSummary as ContentSummarySchema,
    APIResponse
)
from auth import get_current_user
from utils import check_quota_limit, TrimlyException
from background_tasks import task_manager

# 建立路由器
router = APIRouter(prefix="/api/v1/ai", tags=["Advanced AI Features"])

# ==================== 進階音質改善 API ====================

@router.post("/audio/{audio_id}/enhance-advanced", response_model=AIEnhancementSchema)
async def enhance_audio_advanced(
    audio_id: int,
    enhancement_type: str = Query(..., description="Enhancement type: noise_reduction, speech_clarity, volume_normalize, full_enhance"),
    provider: str = Query("openai", description="AI provider: openai, adobe, dolby, krisp"),
    background_tasks: BackgroundTasks,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """進階 AI 音質改善"""
    
    # 驗證音訊檔案存在且屬於當前使用者
    audio_file = db.query(AudioFile).join(Project).filter(
        AudioFile.id == audio_id,
        Project.user_id == current_user.id
    ).first()
    
    if not audio_file:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Audio file not found"
        )
    
    # 檢查配額
    if not check_quota_limit(current_user, "ai_enhance", 1):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="AI enhancement quota exceeded. Please upgrade your plan."
        )
    
    # 驗證增強類型
    valid_enhancement_types = ["noise_reduction", "speech_clarity", "volume_normalize", "full_enhance"]
    if enhancement_type not in valid_enhancement_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid enhancement type. Must be one of: {', '.join(valid_enhancement_types)}"
        )
    
    # 驗證提供商
    valid_providers = ["openai", "adobe", "dolby", "krisp"]
    if provider not in valid_providers:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid provider. Must be one of: {', '.join(valid_providers)}"
        )
    
    # 建立 AI 增強記錄
    ai_enhancement = AIEnhancement(
        audio_file_id=audio_id,
        enhancement_type=enhancement_type,
        input_file_path=audio_file.file_path,
        output_file_path="",  # 稍後設定
        status="processing",
        api_provider=provider
    )
    
    db.add(ai_enhancement)
    db.commit()
    db.refresh(ai_enhancement)
    
    # 啟動背景任務
    background_tasks.add_task(
        task_manager.process_ai_enhancement,
        audio_id,
        enhancement_type,
        current_user.id,
        provider
    )
    
    return AIEnhancementSchema.from_orm(ai_enhancement)

@router.get("/audio/{audio_id}/enhancements/compare")
async def compare_enhancements(
    audio_id: int,
    enhancement_ids: List[int] = Query(..., description="List of enhancement IDs to compare"),
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """比較不同的音質改善結果"""
    
    # 驗證音訊檔案存在且屬於當前使用者
    audio_file = db.query(AudioFile).join(Project).filter(
        AudioFile.id == audio_id,
        Project.user_id == current_user.id
    ).first()
    
    if not audio_file:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Audio file not found"
        )
    
    # 取得增強記錄
    enhancements = db.query(AIEnhancement).filter(
        AIEnhancement.id.in_(enhancement_ids),
        AIEnhancement.audio_file_id == audio_id
    ).all()
    
    if len(enhancements) != len(enhancement_ids):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="One or more enhancements not found"
        )
    
    # 比較結果
    comparison_results = []
    
    for enhancement in enhancements:
        from utils import safe_json_loads
        enhancement_details = safe_json_loads(enhancement.enhancement_details, {})
        
        comparison_results.append({
            "enhancement_id": enhancement.id,
            "enhancement_type": enhancement.enhancement_type,
            "provider": enhancement.api_provider,
            "status": enhancement.status,
            "processing_time": enhancement.processing_duration_seconds,
            "quality_metrics": enhancement_details.get("quality_metrics", {}),
            "file_path": enhancement.output_file_path,
            "created_at": enhancement.created_at
        })
    
    return {
        "audio_id": audio_id,
        "total_enhancements": len(comparison_results),
        "enhancements": comparison_results
    }

# ==================== 進階內容摘要 API ====================

@router.post("/transcripts/{transcript_id}/summarize-advanced", response_model=ContentSummarySchema)
async def create_advanced_summary(
    transcript_id: int,
    summary_type: str = Query(..., description="Summary type: summary, highlights, social_posts, key_points, action_items, questions"),
    language: str = Query("zh-TW", description="Language: zh-TW, zh-CN, en"),
    custom_prompt: Optional[str] = Query(None, description="Custom prompt for summary generation"),
    background_tasks: BackgroundTasks,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """進階內容摘要生成"""
    
    # 驗證逐字稿存在且屬於當前使用者
    transcript = db.query(Transcript).join(AudioFile).join(Project).filter(
        Transcript.id == transcript_id,
        Project.user_id == current_user.id
    ).first()
    
    if not transcript:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transcript not found"
        )
    
    if transcript.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Transcript is not completed yet"
        )
    
    # 檢查配額
    if not check_quota_limit(current_user, "ai_summary", 1):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="AI summary quota exceeded. Please upgrade your plan."
        )
    
    # 驗證摘要類型
    valid_summary_types = ["summary", "highlights", "social_posts", "key_points", "action_items", "questions"]
    if summary_type not in valid_summary_types and not custom_prompt:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid summary type. Must be one of: {', '.join(valid_summary_types)} or provide custom_prompt"
        )
    
    # 驗證語言
    valid_languages = ["zh-TW", "zh-CN", "en"]
    if language not in valid_languages:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid language. Must be one of: {', '.join(valid_languages)}"
        )
    
    # 建立摘要記錄
    content_summary = ContentSummary(
        transcript_id=transcript_id,
        summary_type=summary_type,
        content="",
        status="processing"
    )
    
    db.add(content_summary)
    db.commit()
    db.refresh(content_summary)
    
    # 啟動背景任務
    background_tasks.add_task(
        task_manager.process_content_summary,
        transcript_id,
        summary_type,
        current_user.id,
        language,
        custom_prompt
    )
    
    return ContentSummarySchema.from_orm(content_summary)

@router.post("/transcripts/{transcript_id}/summarize-batch")
async def create_batch_summaries(
    transcript_id: int,
    summary_types: List[str] = Query(..., description="List of summary types to generate"),
    language: str = Query("zh-TW", description="Language: zh-TW, zh-CN, en"),
    background_tasks: BackgroundTasks,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """批量生成多種類型的摘要"""
    
    # 驗證逐字稿存在且屬於當前使用者
    transcript = db.query(Transcript).join(AudioFile).join(Project).filter(
        Transcript.id == transcript_id,
        Project.user_id == current_user.id
    ).first()
    
    if not transcript:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transcript not found"
        )
    
    if transcript.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Transcript is not completed yet"
        )
    
    # 檢查配額（每種摘要類型消耗 1 點數）
    if not check_quota_limit(current_user, "ai_summary", len(summary_types)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"AI summary quota exceeded. Need {len(summary_types)} credits, please upgrade your plan."
        )
    
    # 驗證摘要類型
    valid_summary_types = ["summary", "highlights", "social_posts", "key_points", "action_items", "questions"]
    invalid_types = [t for t in summary_types if t not in valid_summary_types]
    if invalid_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid summary types: {', '.join(invalid_types)}. Must be one of: {', '.join(valid_summary_types)}"
        )
    
    # 啟動背景任務
    background_tasks.add_task(
        task_manager.process_multiple_summaries,
        transcript_id,
        summary_types,
        current_user.id,
        language
    )
    
    return {
        "success": True,
        "message": f"Batch summary generation started for {len(summary_types)} types",
        "transcript_id": transcript_id,
        "summary_types": summary_types,
        "language": language
    }

@router.get("/transcripts/{transcript_id}/summaries/compare")
async def compare_summaries(
    transcript_id: int,
    summary_ids: List[int] = Query(..., description="List of summary IDs to compare"),
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """比較不同類型的摘要"""
    
    # 驗證逐字稿存在且屬於當前使用者
    transcript = db.query(Transcript).join(AudioFile).join(Project).filter(
        Transcript.id == transcript_id,
        Project.user_id == current_user.id
    ).first()
    
    if not transcript:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transcript not found"
        )
    
    # 取得摘要記錄
    summaries = db.query(ContentSummary).filter(
        ContentSummary.id.in_(summary_ids),
        ContentSummary.transcript_id == transcript_id
    ).all()
    
    if len(summaries) != len(summary_ids):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="One or more summaries not found"
        )
    
    # 比較結果
    comparison_results = []
    
    for summary in summaries:
        from utils import safe_json_loads
        metadata = safe_json_loads(summary.summary_metadata, {})
        
        comparison_results.append({
            "summary_id": summary.id,
            "summary_type": summary.summary_type,
            "status": summary.status,
            "content_length": len(summary.content) if summary.content else 0,
            "word_count": summary.token_count,
            "processing_time": summary.processing_duration_seconds,
            "language": metadata.get("language", "unknown"),
            "quality_metrics": metadata.get("quality_metrics", {}),
            "created_at": summary.created_at,
            "content_preview": summary.content[:200] + "..." if summary.content and len(summary.content) > 200 else summary.content
        })
    
    return {
        "transcript_id": transcript_id,
        "total_summaries": len(comparison_results),
        "summaries": comparison_results
    }

# ==================== AI 功能統計 API ====================

@router.get("/usage/stats")
async def get_ai_usage_stats(
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """取得 AI 功能使用統計"""
    
    from models_extended import UsageLog
    from sqlalchemy import func
    
    # 統計各種 AI 功能的使用情況
    usage_stats = db.query(
        UsageLog.action,
        func.count(UsageLog.id).label("count"),
        func.sum(UsageLog.duration_seconds).label("total_duration"),
        func.sum(UsageLog.cost_credits).label("total_credits")
    ).filter(
        UsageLog.user_id == current_user.id
    ).group_by(UsageLog.action).all()
    
    stats_dict = {}
    total_credits_used = 0
    
    for stat in usage_stats:
        stats_dict[stat.action] = {
            "count": stat.count,
            "total_duration_minutes": round((stat.total_duration or 0) / 60, 2),
            "total_credits": stat.total_credits or 0
        }
        total_credits_used += stat.total_credits or 0
    
    # 取得配額資訊
    from utils import calculate_quota_usage
    quotas = calculate_quota_usage(current_user.role)
    
    return {
        "user_role": current_user.role,
        "total_credits_used": total_credits_used,
        "usage_by_action": stats_dict,
        "quotas": quotas,
        "quota_usage_percentage": {
            "transcription": min(100, (stats_dict.get("transcribe", {}).get("total_duration_minutes", 0) / quotas.get("transcription_minutes", 1)) * 100),
            "ai_enhancements": min(100, (stats_dict.get("enhance", {}).get("count", 0) / quotas.get("ai_enhancements", 1)) * 100),
            "ai_summaries": min(100, (stats_dict.get("summarize", {}).get("count", 0) / quotas.get("ai_summaries", 1)) * 100)
        }
    }

