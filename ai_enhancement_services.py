import os
import asyncio
import aiohttp
import openai
from typing import Dict, Any, Optional, List
from datetime import datetime

from utils import safe_json_loads, safe_json_dumps

class AudioEnhancementService:
    """AI 音質改善服務"""
    
    def __init__(self):
        self.openai_client = openai.OpenAI()
        # 這裡可以整合其他音質改善服務的 API
        self.enhancement_providers = {
            "openai": self._enhance_with_openai,
            "adobe": self._enhance_with_adobe,  # 模擬
            "dolby": self._enhance_with_dolby,  # 模擬
            "krisp": self._enhance_with_krisp   # 模擬
        }
    
    async def enhance_audio(self, input_path: str, output_path: str, 
                          enhancement_type: str, provider: str = "openai") -> Dict[str, Any]:
        """執行音質改善"""
        
        if provider not in self.enhancement_providers:
            raise ValueError(f"Unsupported enhancement provider: {provider}")
        
        enhancement_func = self.enhancement_providers[provider]
        
        start_time = datetime.utcnow()
        
        try:
            result = await enhancement_func(input_path, output_path, enhancement_type)
            
            processing_time = (datetime.utcnow() - start_time).total_seconds()
            
            return {
                "success": True,
                "provider": provider,
                "enhancement_type": enhancement_type,
                "input_path": input_path,
                "output_path": output_path,
                "processing_time_seconds": processing_time,
                "quality_metrics": result.get("quality_metrics", {}),
                "enhancement_details": result.get("details", {})
            }
            
        except Exception as e:
            processing_time = (datetime.utcnow() - start_time).total_seconds()
            
            return {
                "success": False,
                "provider": provider,
                "enhancement_type": enhancement_type,
                "error": str(e),
                "processing_time_seconds": processing_time
            }
    
    async def _enhance_with_openai(self, input_path: str, output_path: str, 
                                 enhancement_type: str) -> Dict[str, Any]:
        """使用 OpenAI 進行音質改善（模擬實現）"""
        
        # 注意：OpenAI 目前沒有直接的音質改善 API
        # 這裡是模擬實現，實際應用中需要使用專門的音質改善服務
        
        await asyncio.sleep(3)  # 模擬處理時間
        
        # 複製檔案作為模擬結果
        import shutil
        shutil.copy2(input_path, output_path)
        
        # 模擬品質指標
        quality_metrics = {
            "noise_reduction_db": 15.2,
            "clarity_improvement": 0.85,
            "volume_normalization": True,
            "frequency_response_improved": True
        }
        
        details = {
            "algorithm": "deep_learning_denoiser",
            "model_version": "v2.1",
            "processing_quality": "high"
        }
        
        return {
            "quality_metrics": quality_metrics,
            "details": details
        }
    
    async def _enhance_with_adobe(self, input_path: str, output_path: str, 
                                enhancement_type: str) -> Dict[str, Any]:
        """使用 Adobe Enhance Speech API（模擬實現）"""
        
        # 模擬 Adobe Enhance Speech API 調用
        await asyncio.sleep(4)  # 模擬處理時間
        
        import shutil
        shutil.copy2(input_path, output_path)
        
        quality_metrics = {
            "speech_clarity": 0.92,
            "background_noise_reduction": 0.88,
            "echo_removal": 0.75,
            "overall_quality_score": 0.89
        }
        
        details = {
            "provider": "Adobe Enhance Speech",
            "enhancement_level": "professional",
            "processing_mode": "cloud"
        }
        
        return {
            "quality_metrics": quality_metrics,
            "details": details
        }
    
    async def _enhance_with_dolby(self, input_path: str, output_path: str, 
                                enhancement_type: str) -> Dict[str, Any]:
        """使用 Dolby.io API（模擬實現）"""
        
        await asyncio.sleep(5)  # 模擬處理時間
        
        import shutil
        shutil.copy2(input_path, output_path)
        
        quality_metrics = {
            "dynamic_range_enhancement": 0.91,
            "spatial_audio_improvement": 0.87,
            "loudness_optimization": True,
            "frequency_balance": 0.93
        }
        
        details = {
            "provider": "Dolby.io",
            "enhancement_preset": "podcast_optimize",
            "dolby_atmos_enabled": False
        }
        
        return {
            "quality_metrics": quality_metrics,
            "details": details
        }
    
    async def _enhance_with_krisp(self, input_path: str, output_path: str, 
                                enhancement_type: str) -> Dict[str, Any]:
        """使用 Krisp AI（模擬實現）"""
        
        await asyncio.sleep(2)  # 模擬處理時間
        
        import shutil
        shutil.copy2(input_path, output_path)
        
        quality_metrics = {
            "noise_suppression": 0.95,
            "voice_isolation": 0.89,
            "echo_cancellation": 0.82,
            "real_time_processing": True
        }
        
        details = {
            "provider": "Krisp AI",
            "ai_model": "voice_isolation_v3",
            "processing_speed": "real_time"
        }
        
        return {
            "quality_metrics": quality_metrics,
            "details": details
        }

class ContentSummaryService:
    """內容摘要生成服務"""
    
    def __init__(self):
        self.openai_client = openai.OpenAI()
        
        # 不同類型摘要的提示詞模板
        self.summary_prompts = {
            "summary": {
                "system": "你是一個專業的內容摘要助手，擅長提取重點和生成簡潔的摘要。",
                "user_template": "請為以下內容生成一個簡潔的摘要，重點突出主要觀點和結論：\n\n{content}"
            },
            "highlights": {
                "system": "你是一個專業的內容分析師，擅長識別和提取關鍵信息。",
                "user_template": "請從以下內容中提取最重要的亮點和關鍵信息，以條列式呈現：\n\n{content}"
            },
            "social_posts": {
                "system": "你是一個社交媒體內容專家，擅長創作吸引人的短文。",
                "user_template": "請基於以下內容生成適合社交媒體分享的短文（限制在280字以內），要有吸引力且易於理解：\n\n{content}"
            },
            "key_points": {
                "system": "你是一個專業的內容整理師，擅長提取和組織關鍵要點。",
                "user_template": "請從以下內容中提取關鍵要點，並按重要性排序：\n\n{content}"
            },
            "action_items": {
                "system": "你是一個專業的會議記錄助手，擅長識別行動項目和任務。",
                "user_template": "請從以下內容中識別所有的行動項目、任務和決策，並清楚列出：\n\n{content}"
            },
            "questions": {
                "system": "你是一個專業的內容分析師，擅長生成相關問題。",
                "user_template": "請基於以下內容生成5-10個相關的問題，這些問題可以幫助深入理解內容：\n\n{content}"
            }
        }
    
    async def generate_summary(self, content: str, summary_type: str, 
                             language: str = "zh-TW", custom_prompt: str = None) -> Dict[str, Any]:
        """生成內容摘要"""
        
        if summary_type not in self.summary_prompts and not custom_prompt:
            raise ValueError(f"Unsupported summary type: {summary_type}")
        
        start_time = datetime.utcnow()
        
        try:
            if custom_prompt:
                system_prompt = "你是一個專業的內容助手，請根據使用者的要求處理內容。"
                user_prompt = custom_prompt.format(content=content)
            else:
                prompt_config = self.summary_prompts[summary_type]
                system_prompt = prompt_config["system"]
                user_prompt = prompt_config["user_template"].format(content=content)
            
            # 根據語言調整提示詞
            if language == "en":
                system_prompt = self._translate_prompt_to_english(system_prompt)
                user_prompt = self._translate_prompt_to_english(user_prompt)
            
            response = await asyncio.to_thread(
                lambda: self.openai_client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    max_tokens=800,
                    temperature=0.7
                )
            )
            
            summary_content = response.choices[0].message.content.strip()
            processing_time = (datetime.utcnow() - start_time).total_seconds()
            
            # 分析摘要品質
            quality_metrics = self._analyze_summary_quality(content, summary_content)
            
            return {
                "success": True,
                "summary_type": summary_type,
                "language": language,
                "content": summary_content,
                "processing_time_seconds": processing_time,
                "token_count": len(summary_content.split()),
                "character_count": len(summary_content),
                "quality_metrics": quality_metrics,
                "model_used": "gpt-3.5-turbo"
            }
            
        except Exception as e:
            processing_time = (datetime.utcnow() - start_time).total_seconds()
            
            return {
                "success": False,
                "summary_type": summary_type,
                "language": language,
                "error": str(e),
                "processing_time_seconds": processing_time
            }
    
    async def generate_multiple_summaries(self, content: str, summary_types: List[str], 
                                        language: str = "zh-TW") -> Dict[str, Any]:
        """同時生成多種類型的摘要"""
        
        tasks = []
        for summary_type in summary_types:
            task = self.generate_summary(content, summary_type, language)
            tasks.append(task)
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        summaries = {}
        successful_count = 0
        
        for i, result in enumerate(results):
            summary_type = summary_types[i]
            
            if isinstance(result, Exception):
                summaries[summary_type] = {
                    "success": False,
                    "error": str(result)
                }
            else:
                summaries[summary_type] = result
                if result.get("success"):
                    successful_count += 1
        
        return {
            "total_summaries": len(summary_types),
            "successful_summaries": successful_count,
            "summaries": summaries
        }
    
    def _translate_prompt_to_english(self, chinese_prompt: str) -> str:
        """將中文提示詞翻譯為英文（簡化實現）"""
        
        translations = {
            "你是一個專業的內容摘要助手，擅長提取重點和生成簡潔的摘要。": 
                "You are a professional content summarization assistant, skilled at extracting key points and generating concise summaries.",
            "你是一個專業的內容分析師，擅長識別和提取關鍵信息。": 
                "You are a professional content analyst, skilled at identifying and extracting key information.",
            "你是一個社交媒體內容專家，擅長創作吸引人的短文。": 
                "You are a social media content expert, skilled at creating engaging short posts.",
            "你是一個專業的內容整理師，擅長提取和組織關鍵要點。": 
                "You are a professional content organizer, skilled at extracting and organizing key points.",
            "你是一個專業的會議記錄助手，擅長識別行動項目和任務。": 
                "You are a professional meeting notes assistant, skilled at identifying action items and tasks.",
            "你是一個專業的內容分析師，擅長生成相關問題。": 
                "You are a professional content analyst, skilled at generating relevant questions."
        }
        
        return translations.get(chinese_prompt, chinese_prompt)
    
    def _analyze_summary_quality(self, original_content: str, summary_content: str) -> Dict[str, Any]:
        """分析摘要品質"""
        
        original_length = len(original_content)
        summary_length = len(summary_content)
        
        compression_ratio = summary_length / original_length if original_length > 0 else 0
        
        # 簡單的品質指標
        quality_metrics = {
            "compression_ratio": round(compression_ratio, 3),
            "length_appropriate": 0.1 <= compression_ratio <= 0.5,
            "has_structure": "。" in summary_content or "." in summary_content,
            "word_count": len(summary_content.split()),
            "estimated_reading_time_seconds": len(summary_content.split()) * 0.5  # 假設每分鐘120字
        }
        
        return quality_metrics

# 全域服務實例
audio_enhancement_service = AudioEnhancementService()
content_summary_service = ContentSummaryService()

