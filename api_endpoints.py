from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.orm import Session
from typing import List, Dict, Any

from models_extended import (
    AudioFile, Transcript, AudioVersion, AIEnhancement, 
    ContentSummary, Project, get_db
)
from schemas import (
    TranscriptCreate, Transcript as TranscriptSchema,
    AudioVersionCreate, AudioVersion as AudioVersionSchema,
    AIEnhancementCreate, AIEnhancement as AIEnhancementSchema,
    ContentSummaryCreate, ContentSummary as ContentSummarySchema,
    EditRequest, APIResponse
)
from auth import get_current_user
from utils import check_quota_limit, safe_json_loads
from background_tasks import task_manager

# 建立路由器
router = APIRouter(prefix="/api/v1", tags=["AI Audio Processing"])

# ==================== 逐字稿相關 API ====================

@router.post("/audio/{audio_id}/transcribe", response_model=TranscriptSchema)
async def create_transcript(
    audio_id: int,
    transcript_data: TranscriptCreate,
    background_tasks: BackgroundTasks,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """為音訊檔案建立逐字稿"""
    
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
    if not check_quota_limit(current_user, "transcribe", 1):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Transcription quota exceeded. Please upgrade your plan."
        )
    
    # 檢查是否已有處理中的逐字稿
    existing_transcript = db.query(Transcript).filter(
        Transcript.audio_file_id == audio_id,
        Transcript.status.in_(["processing", "completed"])
    ).first()
    
    if existing_transcript:
        if existing_transcript.status == "processing":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Transcription is already in progress"
            )
        else:
            return TranscriptSchema.from_orm(existing_transcript)
    
    # 建立逐字稿記錄
    transcript = Transcript(
        audio_file_id=audio_id,
        language=transcript_data.language,
        status="processing"
    )
    
    db.add(transcript)
    db.commit()
    db.refresh(transcript)
    
    # 啟動背景任務
    background_tasks.add_task(
        task_manager.process_transcription,
        transcript.id,
        audio_file.file_path,
        transcript_data.language
    )
    
    return TranscriptSchema.from_orm(transcript)

@router.get("/audio/{audio_id}/transcripts", response_model=List[TranscriptSchema])
async def get_transcripts(
    audio_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """取得音訊檔案的所有逐字稿"""
    
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
    
    transcripts = db.query(Transcript).filter(Transcript.audio_file_id == audio_id).all()
    return [TranscriptSchema.from_orm(transcript) for transcript in transcripts]

@router.get("/transcripts/{transcript_id}", response_model=TranscriptSchema)
async def get_transcript(
    transcript_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """取得特定逐字稿"""
    
    transcript = db.query(Transcript).join(AudioFile).join(Project).filter(
        Transcript.id == transcript_id,
        Project.user_id == current_user.id
    ).first()
    
    if not transcript:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transcript not found"
        )
    
    return TranscriptSchema.from_orm(transcript)

# ==================== 音訊編輯相關 API ====================

@router.post("/audio/{audio_id}/edit", response_model=AudioVersionSchema)
async def edit_audio(
    audio_id: int,
    edit_request: EditRequest,
    background_tasks: BackgroundTasks,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """執行音訊編輯操作"""
    
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
    
    # 檢查是否有完成的逐字稿
    transcript = db.query(Transcript).filter(
        Transcript.audio_file_id == audio_id,
        Transcript.status == "completed"
    ).first()
    
    if not transcript:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No completed transcript found. Please transcribe the audio first."
        )
    
    # 生成版本名稱
    existing_versions = db.query(AudioVersion).filter(
        AudioVersion.audio_file_id == audio_id
    ).count()
    
    version_name = edit_request.version_name or f"v{existing_versions + 1}"
    
    # 檢查版本名稱是否已存在
    existing_version = db.query(AudioVersion).filter(
        AudioVersion.audio_file_id == audio_id,
        AudioVersion.version_name == version_name
    ).first()
    
    if existing_version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Version '{version_name}' already exists"
        )
    
    # 建立臨時版本記錄（稍後由背景任務更新）
    audio_version = AudioVersion(
        audio_file_id=audio_id,
        version_name=version_name,
        file_path="",  # 稍後設定
        edit_operations="",  # 稍後設定
        edit_summary="Processing..."
    )
    
    db.add(audio_version)
    db.commit()
    db.refresh(audio_version)
    
    # 啟動背景任務
    background_tasks.add_task(
        task_manager.process_audio_editing,
        audio_id,
        [op.dict() for op in edit_request.operations],
        version_name,
        current_user.id
    )
    
    return AudioVersionSchema.from_orm(audio_version)

@router.get("/audio/{audio_id}/versions", response_model=List[AudioVersionSchema])
async def get_audio_versions(
    audio_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """取得音訊檔案的所有版本"""
    
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
    
    versions = db.query(AudioVersion).filter(
        AudioVersion.audio_file_id == audio_id
    ).order_by(AudioVersion.created_at.desc()).all()
    
    return [AudioVersionSchema.from_orm(version) for version in versions]

# ==================== 智能功能 API ====================

@router.post("/audio/{audio_id}/remove-fillers")
async def remove_filler_words(
    audio_id: int,
    language: str = "zh",
    version_name: str = None,
    background_tasks: BackgroundTasks,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """一鍵移除填充詞"""
    
    edit_operations = [{
        "type": "delete_filler",
        "language": language
    }]
    
    edit_request = EditRequest(
        operations=edit_operations,
        version_name=version_name or "no_fillers"
    )
    
    return await edit_audio(audio_id, edit_request, background_tasks, current_user, db)

@router.post("/audio/{audio_id}/remove-keywords")
async def remove_keywords(
    audio_id: int,
    keywords: List[str],
    version_name: str = None,
    background_tasks: BackgroundTasks,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """移除包含特定關鍵字的片段"""
    
    edit_operations = [{
        "type": "delete_keyword",
        "keywords": keywords
    }]
    
    edit_request = EditRequest(
        operations=edit_operations,
        version_name=version_name or f"no_keywords_{len(keywords)}"
    )
    
    return await edit_audio(audio_id, edit_request, background_tasks, current_user, db)

@router.post("/transcripts/{transcript_id}/search-keywords")
async def search_keywords_in_transcript(
    transcript_id: int,
    keywords: List[str],
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """在逐字稿中搜尋關鍵字"""
    
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
    
    # 解析逐字稿內容
    transcript_data = safe_json_loads(transcript.content, {})
    
    # 搜尋關鍵字
    from audio_processing import audio_processor
    found_keywords = audio_processor.search_keywords(transcript_data, keywords)
    
    return {
        "transcript_id": transcript_id,
        "keywords": keywords,
        "matches": found_keywords,
        "total_matches": len(found_keywords)
    }

# ==================== AI 增強功能 API ====================

@router.post("/audio/{audio_id}/enhance", response_model=AIEnhancementSchema)
async def enhance_audio(
    audio_id: int,
    enhancement_data: AIEnhancementCreate,
    background_tasks: BackgroundTasks,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """AI 音質增強"""
    
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
    
    # 建立 AI 增強記錄
    ai_enhancement = AIEnhancement(
        audio_file_id=audio_id,
        enhancement_type=enhancement_data.enhancement_type,
        input_file_path=audio_file.file_path,
        output_file_path="",  # 稍後設定
        status="processing"
    )
    
    db.add(ai_enhancement)
    db.commit()
    db.refresh(ai_enhancement)
    
    # 啟動背景任務
    background_tasks.add_task(
        task_manager.process_ai_enhancement,
        audio_id,
        enhancement_data.enhancement_type,
        current_user.id
    )
    
    return AIEnhancementSchema.from_orm(ai_enhancement)

@router.get("/audio/{audio_id}/enhancements", response_model=List[AIEnhancementSchema])
async def get_audio_enhancements(
    audio_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """取得音訊檔案的所有 AI 增強記錄"""
    
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
    
    enhancements = db.query(AIEnhancement).filter(
        AIEnhancement.audio_file_id == audio_id
    ).order_by(AIEnhancement.created_at.desc()).all()
    
    return [AIEnhancementSchema.from_orm(enhancement) for enhancement in enhancements]

# ==================== 內容摘要 API ====================

@router.post("/transcripts/{transcript_id}/summarize", response_model=ContentSummarySchema)
async def create_content_summary(
    transcript_id: int,
    summary_data: ContentSummaryCreate,
    background_tasks: BackgroundTasks,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """生成內容摘要"""
    
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
    
    # 建立摘要記錄
    content_summary = ContentSummary(
        transcript_id=transcript_id,
        summary_type=summary_data.summary_type,
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
        summary_data.summary_type,
        current_user.id
    )
    
    return ContentSummarySchema.from_orm(content_summary)

@router.get("/transcripts/{transcript_id}/summaries", response_model=List[ContentSummarySchema])
async def get_content_summaries(
    transcript_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """取得逐字稿的所有摘要"""
    
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
    
    summaries = db.query(ContentSummary).filter(
        ContentSummary.transcript_id == transcript_id
    ).order_by(ContentSummary.created_at.desc()).all()
    
    return [ContentSummarySchema.from_orm(summary) for summary in summaries]

