import os
import json
import asyncio
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
import tempfile
import subprocess

# 音訊處理相關
try:
    import librosa
    import soundfile as sf
    import numpy as np
    AUDIO_LIBS_AVAILABLE = True
except ImportError:
    AUDIO_LIBS_AVAILABLE = False
    print("Warning: Audio processing libraries not available. Install librosa and soundfile for full functionality.")

# OpenAI API
import openai
import httpx

from utils import TrimlyException, FileProcessingException, APIException

class AudioProcessor:
    """音訊處理核心類別"""
    
    def __init__(self):
        self.openai_client = openai.OpenAI()
        
    async def transcribe_audio(self, file_path: str, language: str = "zh") -> Dict[str, Any]:
        """
        使用 OpenAI Whisper API 進行語音轉文字
        返回包含時間戳的逐字稿
        """
        try:
            # 檢查檔案是否存在
            if not os.path.exists(file_path):
                raise FileProcessingException(f"Audio file not found: {file_path}")
            
            # 使用 OpenAI Whisper API
            with open(file_path, "rb") as audio_file:
                transcript = self.openai_client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                    language=language,
                    response_format="verbose_json",
                    timestamp_granularities=["word"]
                )
            
            # 處理回應，建立帶時間戳的逐字稿
            result = {
                "text": transcript.text,
                "language": transcript.language,
                "duration": transcript.duration if hasattr(transcript, 'duration') else None,
                "words": []
            }
            
            # 處理單詞級別的時間戳
            if hasattr(transcript, 'words') and transcript.words:
                for word_info in transcript.words:
                    result["words"].append({
                        "word": word_info.word,
                        "start": word_info.start,
                        "end": word_info.end
                    })
            
            return result
            
        except Exception as e:
            raise APIException(f"Transcription failed: {str(e)}")
    
    def identify_filler_words(self, transcript_data: Dict[str, Any], language: str = "zh") -> List[Dict[str, Any]]:
        """
        識別填充詞（嗯、啊、然後等）
        返回填充詞的位置和時間戳
        """
        
        # 定義不同語言的填充詞
        filler_words = {
            "zh": ["嗯", "呃", "啊", "然後", "那個", "就是", "就是說", "那一個", "這個", "那", "這"],
            "zh-TW": ["嗯", "呃", "啊", "然後", "那個", "就是", "就是說", "那一個", "這個", "那", "這"],
            "zh-CN": ["嗯", "呃", "啊", "然后", "那个", "就是", "就是说", "那一个", "这个", "那", "这"],
            "en": ["um", "uh", "like", "you know", "so", "well", "actually", "basically", "literally"]
        }
        
        target_fillers = filler_words.get(language, filler_words["zh"])
        identified_fillers = []
        
        # 檢查每個單詞
        for word_info in transcript_data.get("words", []):
            word = word_info["word"].strip().lower()
            
            # 移除標點符號進行比較
            clean_word = word.strip(".,!?;:\"'()[]{}").lower()
            
            if clean_word in target_fillers:
                identified_fillers.append({
                    "word": word_info["word"],
                    "start_time": word_info["start"],
                    "end_time": word_info["end"],
                    "type": "filler_word",
                    "confidence": 1.0  # 基於規則的識別，信心度設為1
                })
        
        return identified_fillers
    
    def search_keywords(self, transcript_data: Dict[str, Any], keywords: List[str]) -> List[Dict[str, Any]]:
        """
        在逐字稿中搜尋關鍵字
        返回關鍵字的位置和時間戳
        """
        found_keywords = []
        words = transcript_data.get("words", [])
        
        for keyword in keywords:
            keyword_lower = keyword.lower()
            
            # 單詞搜尋
            for word_info in words:
                word = word_info["word"].strip().lower()
                clean_word = word.strip(".,!?;:\"'()[]{}").lower()
                
                if keyword_lower in clean_word or clean_word in keyword_lower:
                    found_keywords.append({
                        "keyword": keyword,
                        "matched_word": word_info["word"],
                        "start_time": word_info["start"],
                        "end_time": word_info["end"],
                        "type": "keyword_match",
                        "confidence": 0.9
                    })
            
            # 片語搜尋（多個連續單詞）
            if len(keyword.split()) > 1:
                keyword_words = keyword_lower.split()
                for i in range(len(words) - len(keyword_words) + 1):
                    phrase_words = []
                    for j in range(len(keyword_words)):
                        word = words[i + j]["word"].strip().lower()
                        clean_word = word.strip(".,!?;:\"'()[]{}").lower()
                        phrase_words.append(clean_word)
                    
                    if " ".join(phrase_words) == keyword_lower:
                        found_keywords.append({
                            "keyword": keyword,
                            "matched_phrase": " ".join([words[i + j]["word"] for j in range(len(keyword_words))]),
                            "start_time": words[i]["start"],
                            "end_time": words[i + len(keyword_words) - 1]["end"],
                            "type": "phrase_match",
                            "confidence": 0.95
                        })
        
        return found_keywords
    
    async def cut_audio_segments(self, input_file: str, segments_to_remove: List[Dict[str, Any]], output_file: str) -> Dict[str, Any]:
        """
        根據時間戳切除音訊片段
        segments_to_remove: [{"start_time": float, "end_time": float, "reason": str}, ...]
        """
        try:
            if not AUDIO_LIBS_AVAILABLE:
                # 使用 ffmpeg 作為備選方案
                return await self._cut_audio_with_ffmpeg(input_file, segments_to_remove, output_file)
            
            # 載入音訊檔案
            audio, sr = librosa.load(input_file, sr=None)
            
            # 排序要移除的片段（按開始時間）
            segments_to_remove.sort(key=lambda x: x["start_time"])
            
            # 建立保留的片段列表
            keep_segments = []
            last_end = 0.0
            
            for segment in segments_to_remove:
                start_time = segment["start_time"]
                end_time = segment["end_time"]
                
                # 添加前一個保留片段
                if start_time > last_end:
                    keep_segments.append((last_end, start_time))
                
                last_end = max(last_end, end_time)
            
            # 添加最後一個保留片段
            audio_duration = len(audio) / sr
            if last_end < audio_duration:
                keep_segments.append((last_end, audio_duration))
            
            # 合併保留的音訊片段
            if not keep_segments:
                # 如果沒有保留片段，建立空音訊
                result_audio = np.array([])
            else:
                audio_segments = []
                for start, end in keep_segments:
                    start_sample = int(start * sr)
                    end_sample = int(end * sr)
                    audio_segments.append(audio[start_sample:end_sample])
                
                result_audio = np.concatenate(audio_segments)
            
            # 儲存結果
            sf.write(output_file, result_audio, sr)
            
            # 計算統計資訊
            original_duration = audio_duration
            new_duration = len(result_audio) / sr
            removed_duration = original_duration - new_duration
            
            return {
                "success": True,
                "original_duration": original_duration,
                "new_duration": new_duration,
                "removed_duration": removed_duration,
                "segments_removed": len(segments_to_remove),
                "output_file": output_file
            }
            
        except Exception as e:
            raise FileProcessingException(f"Audio cutting failed: {str(e)}")
    
    async def _cut_audio_with_ffmpeg(self, input_file: str, segments_to_remove: List[Dict[str, Any]], output_file: str) -> Dict[str, Any]:
        """
        使用 ffmpeg 進行音訊切割（備選方案）
        """
        try:
            # 排序要移除的片段
            segments_to_remove.sort(key=lambda x: x["start_time"])
            
            # 建立 ffmpeg 濾鏡字串
            filter_parts = []
            last_end = 0.0
            segment_index = 0
            
            for segment in segments_to_remove:
                start_time = segment["start_time"]
                end_time = segment["end_time"]
                
                # 添加保留片段
                if start_time > last_end:
                    filter_parts.append(f"[0:a]atrim=start={last_end}:end={start_time}[a{segment_index}]")
                    segment_index += 1
                
                last_end = max(last_end, end_time)
            
            # 取得原始音訊長度
            probe_cmd = [
                "ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                "-of", "csv=p=0", input_file
            ]
            result = subprocess.run(probe_cmd, capture_output=True, text=True)
            original_duration = float(result.stdout.strip())
            
            # 添加最後一個保留片段
            if last_end < original_duration:
                filter_parts.append(f"[0:a]atrim=start={last_end}[a{segment_index}]")
                segment_index += 1
            
            if not filter_parts:
                # 如果沒有保留片段，建立空音訊
                cmd = [
                    "ffmpeg", "-f", "lavfi", "-i", "anullsrc=duration=0.1:sample_rate=44100",
                    "-y", output_file
                ]
            else:
                # 合併所有保留片段
                concat_inputs = "".join([f"[a{i}]" for i in range(segment_index)])
                filter_complex = ";".join(filter_parts) + f";{concat_inputs}concat=n={segment_index}:v=0:a=1[out]"
                
                cmd = [
                    "ffmpeg", "-i", input_file,
                    "-filter_complex", filter_complex,
                    "-map", "[out]", "-y", output_file
                ]
            
            # 執行 ffmpeg
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode != 0:
                raise FileProcessingException(f"ffmpeg failed: {result.stderr}")
            
            # 取得新音訊長度
            probe_cmd = [
                "ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                "-of", "csv=p=0", output_file
            ]
            result = subprocess.run(probe_cmd, capture_output=True, text=True)
            new_duration = float(result.stdout.strip()) if result.stdout.strip() else 0.0
            
            return {
                "success": True,
                "original_duration": original_duration,
                "new_duration": new_duration,
                "removed_duration": original_duration - new_duration,
                "segments_removed": len(segments_to_remove),
                "output_file": output_file
            }
            
        except Exception as e:
            raise FileProcessingException(f"ffmpeg audio cutting failed: {str(e)}")

class EditingEngine:
    """音訊編輯引擎"""
    
    def __init__(self):
        self.audio_processor = AudioProcessor()
    
    async def process_edit_operations(self, audio_file_path: str, transcript_data: Dict[str, Any], 
                                    operations: List[Dict[str, Any]], output_path: str) -> Dict[str, Any]:
        """
        處理編輯操作
        operations: [{"type": "delete_filler|delete_keyword|delete_text", "start_time": float, "end_time": float, ...}]
        """
        
        segments_to_remove = []
        
        for operation in operations:
            op_type = operation.get("type")
            
            if op_type == "delete_filler":
                # 自動識別填充詞
                language = operation.get("language", "zh")
                fillers = self.audio_processor.identify_filler_words(transcript_data, language)
                
                for filler in fillers:
                    segments_to_remove.append({
                        "start_time": filler["start_time"],
                        "end_time": filler["end_time"],
                        "reason": f"filler_word: {filler['word']}"
                    })
            
            elif op_type == "delete_keyword":
                # 搜尋並刪除關鍵字
                keywords = operation.get("keywords", [])
                found_keywords = self.audio_processor.search_keywords(transcript_data, keywords)
                
                for keyword_match in found_keywords:
                    segments_to_remove.append({
                        "start_time": keyword_match["start_time"],
                        "end_time": keyword_match["end_time"],
                        "reason": f"keyword: {keyword_match['keyword']}"
                    })
            
            elif op_type == "delete_text":
                # 直接指定時間範圍刪除
                start_time = operation.get("start_time")
                end_time = operation.get("end_time")
                text = operation.get("text", "")
                
                if start_time is not None and end_time is not None:
                    segments_to_remove.append({
                        "start_time": start_time,
                        "end_time": end_time,
                        "reason": f"manual_delete: {text}"
                    })
        
        # 合併重疊的片段
        merged_segments = self._merge_overlapping_segments(segments_to_remove)
        
        # 執行音訊切割
        result = await self.audio_processor.cut_audio_segments(
            audio_file_path, merged_segments, output_path
        )
        
        # 添加編輯操作記錄
        result["edit_operations"] = operations
        result["segments_removed_detail"] = merged_segments
        
        return result
    
    def _merge_overlapping_segments(self, segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """合併重疊的時間片段"""
        if not segments:
            return []
        
        # 按開始時間排序
        sorted_segments = sorted(segments, key=lambda x: x["start_time"])
        merged = [sorted_segments[0]]
        
        for current in sorted_segments[1:]:
            last = merged[-1]
            
            # 如果當前片段與上一個片段重疊或相鄰
            if current["start_time"] <= last["end_time"]:
                # 合併片段
                last["end_time"] = max(last["end_time"], current["end_time"])
                last["reason"] += f"; {current['reason']}"
            else:
                # 添加新片段
                merged.append(current)
        
        return merged

# 全域實例
audio_processor = AudioProcessor()
editing_engine = EditingEngine()

