import asyncio
import os
from typing import Dict, Any, Optional
from datetime import datetime
from sqlalchemy.orm import Session

from models_extended import (
    AudioFile, Transcript, AudioVersion, AIEnhancement, 
    ContentSummary, UsageLog, SessionLocal
)
from audio_processing import audio_processor, editing_engine
from utils import safe_json_dumps, safe_json_loads, get_processed_path

class BackgroundTaskManager:
    """背景任務管理器"""
    
    def __init__(self):
        self.running_tasks = {}
    
    async def process_transcription(self, transcript_id: int, audio_file_path: str, language: str = "zh"):
        """處理語音轉文字任務"""
        db = SessionLocal()
        try:
            # 取得逐字稿記錄
            transcript = db.query(Transcript).filter(Transcript.id == transcript_id).first()
            if not transcript:
                return
            
            # 更新狀態為處理中
            transcript.status = "processing"
            db.commit()
            
            start_time = datetime.utcnow()
            
            try:
                # 執行語音轉文字
                result = await audio_processor.transcribe_audio(audio_file_path, language)
                
                # 更新逐字稿內容
                transcript.content = safe_json_dumps(result)
                transcript.status = "completed"
                transcript.word_count = len(result.get("words", []))
                transcript.completed_at = datetime.utcnow()
                transcript.processing_duration_seconds = (datetime.utcnow() - start_time).total_seconds()
                
                # 記錄使用量
                audio_file = db.query(AudioFile).filter(AudioFile.id == transcript.audio_file_id).first()
                if audio_file and audio_file.project:
                    usage_log = UsageLog(
                        user_id=audio_file.project.user_id,
                        action="transcribe",
                        resource_type="transcript",
                        resource_id=transcript_id,
                        duration_seconds=result.get("duration", 0),
                        cost_credits=0
                    )
                    db.add(usage_log)
                
            except Exception as e:
                # 處理失敗
                transcript.status = "error"
                transcript.error_message = str(e)
                transcript.completed_at = datetime.utcnow()
                transcript.processing_duration_seconds = (datetime.utcnow() - start_time).total_seconds()
            
            db.commit()
            
        finally:
            db.close()
    
    async def process_audio_editing(self, audio_file_id: int, edit_operations: List[Dict[str, Any]], 
                                  version_name: str, user_id: int):
        """處理音訊編輯任務"""
        db = SessionLocal()
        try:
            # 取得音訊檔案和逐字稿
            audio_file = db.query(AudioFile).filter(AudioFile.id == audio_file_id).first()
            if not audio_file:
                return
            
            transcript = db.query(Transcript).filter(
                Transcript.audio_file_id == audio_file_id,
                Transcript.status == "completed"
            ).first()
            
            if not transcript:
                raise Exception("No completed transcript found for this audio file")
            
            # 準備輸出路徑
            output_dir = get_processed_path(user_id, audio_file.project_id)
            output_filename = f"{version_name}_{audio_file.filename}"
            output_path = os.path.join(output_dir, output_filename)
            
            start_time = datetime.utcnow()
            
            try:
                # 解析逐字稿內容
                transcript_data = safe_json_loads(transcript.content, {})
                
                # 執行編輯操作
                result = await editing_engine.process_edit_operations(
                    audio_file.file_path,
                    transcript_data,
                    edit_operations,
                    output_path
                )
                
                # 建立新版本記錄
                audio_version = AudioVersion(
                    audio_file_id=audio_file_id,
                    version_name=version_name,
                    file_path=output_path,
                    edit_operations=safe_json_dumps(edit_operations),
                    edit_summary=self._generate_edit_summary(edit_operations),
                    duration_seconds=result.get("new_duration"),
                    file_size_bytes=os.path.getsize(output_path) if os.path.exists(output_path) else 0
                )
                
                db.add(audio_version)
                
                # 記錄使用量
                usage_log = UsageLog(
                    user_id=user_id,
                    action="edit",
                    resource_type="audio_version",
                    resource_id=audio_version.id,
                    duration_seconds=result.get("original_duration", 0),
                    cost_credits=0
                )
                db.add(usage_log)
                
                db.commit()
                
                return {
                    "success": True,
                    "audio_version_id": audio_version.id,
                    "result": result
                }
                
            except Exception as e:
                raise Exception(f"Audio editing failed: {str(e)}")
            
        finally:
            db.close()
    
    async def process_ai_enhancement(self, audio_file_id: int, enhancement_type: str, user_id: int):
        """處理 AI 音質增強任務"""
        db = SessionLocal()
        try:
            # 取得音訊檔案
            audio_file = db.query(AudioFile).filter(AudioFile.id == audio_file_id).first()
            if not audio_file:
                return
            
            # 建立 AI 增強記錄
            ai_enhancement = AIEnhancement(
                audio_file_id=audio_file_id,
                enhancement_type=enhancement_type,
                input_file_path=audio_file.file_path,
                output_file_path="",  # 稍後設定
                status="processing"
            )
            
            db.add(ai_enhancement)
            db.commit()
            db.refresh(ai_enhancement)
            
            # 準備輸出路徑
            output_dir = get_processed_path(user_id, audio_file.project_id)
            output_filename = f"enhanced_{enhancement_type}_{audio_file.filename}"
            output_path = os.path.join(output_dir, output_filename)
            
            ai_enhancement.output_file_path = output_path
            
            start_time = datetime.utcnow()
            
            try:
                # 這裡應該調用實際的 AI 增強服務
                # 目前先模擬處理
                await self._simulate_ai_enhancement(audio_file.file_path, output_path, enhancement_type)
                
                ai_enhancement.status = "completed"
                ai_enhancement.completed_at = datetime.utcnow()
                ai_enhancement.processing_duration_seconds = (datetime.utcnow() - start_time).total_seconds()
                ai_enhancement.api_provider = "simulated"
                
                # 記錄使用量
                usage_log = UsageLog(
                    user_id=user_id,
                    action="enhance",
                    resource_type="ai_enhancement",
                    resource_id=ai_enhancement.id,
                    duration_seconds=audio_file.duration_seconds or 0,
                    cost_credits=1  # AI 增強消耗 1 點數
                )
                db.add(usage_log)
                
            except Exception as e:
                ai_enhancement.status = "error"
                ai_enhancement.error_message = str(e)
                ai_enhancement.completed_at = datetime.utcnow()
                ai_enhancement.processing_duration_seconds = (datetime.utcnow() - start_time).total_seconds()
            
            db.commit()
            
        finally:
            db.close()
    
    async def process_content_summary(self, transcript_id: int, summary_type: str, user_id: int):
        """處理內容摘要生成任務"""
        db = SessionLocal()
        try:
            # 取得逐字稿
            transcript = db.query(Transcript).filter(Transcript.id == transcript_id).first()
            if not transcript or transcript.status != "completed":
                return
            
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
            
            start_time = datetime.utcnow()
            
            try:
                # 解析逐字稿內容
                transcript_data = safe_json_loads(transcript.content, {})
                text_content = transcript_data.get("text", "")
                
                if not text_content:
                    raise Exception("No text content found in transcript")
                
                # 生成摘要
                summary_content = await self._generate_summary(text_content, summary_type)
                
                content_summary.content = summary_content
                content_summary.status = "completed"
                content_summary.completed_at = datetime.utcnow()
                content_summary.processing_duration_seconds = (datetime.utcnow() - start_time).total_seconds()
                content_summary.token_count = len(summary_content.split())
                
                # 記錄使用量
                usage_log = UsageLog(
                    user_id=user_id,
                    action="summarize",
                    resource_type="content_summary",
                    resource_id=content_summary.id,
                    duration_seconds=0,
                    cost_credits=1  # 摘要生成消耗 1 點數
                )
                db.add(usage_log)
                
            except Exception as e:
                content_summary.status = "error"
                content_summary.error_message = str(e)
                content_summary.completed_at = datetime.utcnow()
                content_summary.processing_duration_seconds = (datetime.utcnow() - start_time).total_seconds()
            
            db.commit()
            
        finally:
            db.close()
    
    async def _simulate_ai_enhancement(self, input_path: str, output_path: str, enhancement_type: str):
        """模擬 AI 音質增強（實際應用中應該調用真實的 AI 服務）"""
        # 這裡只是複製檔案作為模擬
        import shutil
        await asyncio.sleep(2)  # 模擬處理時間
        shutil.copy2(input_path, output_path)
    
    async def _generate_summary(self, text: str, summary_type: str) -> str:
        """使用 OpenAI API 生成內容摘要"""
        try:
            prompts = {
                "summary": "請為以下內容生成一個簡潔的摘要，重點突出主要觀點和結論：",
                "highlights": "請從以下內容中提取最重要的亮點和關鍵信息：",
                "social_posts": "請基於以下內容生成適合社交媒體分享的短文（限制在280字以內）："
            }
            
            prompt = prompts.get(summary_type, prompts["summary"])
            
            response = await asyncio.to_thread(
                lambda: audio_processor.openai_client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=[
                        {"role": "system", "content": "你是一個專業的內容摘要助手，擅長提取重點和生成簡潔的摘要。"},
                        {"role": "user", "content": f"{prompt}\n\n{text}"}
                    ],
                    max_tokens=500,
                    temperature=0.7
                )
            )
            
            return response.choices[0].message.content.strip()
            
        except Exception as e:
            raise Exception(f"Summary generation failed: {str(e)}")
    
    def _generate_edit_summary(self, edit_operations: List[Dict[str, Any]]) -> str:
        """生成編輯操作的人類可讀摘要"""
        summary_parts = []
        
        for operation in edit_operations:
            op_type = operation.get("type")
            
            if op_type == "delete_filler":
                summary_parts.append("移除填充詞")
            elif op_type == "delete_keyword":
                keywords = operation.get("keywords", [])
                if keywords:
                    summary_parts.append(f"移除關鍵字: {', '.join(keywords)}")
            elif op_type == "delete_text":
                text = operation.get("text", "")
                if text:
                    summary_parts.append(f"移除文字: {text[:20]}...")
                else:
                    start = operation.get("start_time", 0)
                    end = operation.get("end_time", 0)
                    summary_parts.append(f"移除片段: {start:.1f}s-{end:.1f}s")
        
        return "; ".join(summary_parts) if summary_parts else "自定義編輯"

# 全域實例
task_manager = BackgroundTaskManager()

