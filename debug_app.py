"""
簡化的 Trimly 應用程式 - 用於除錯部署問題
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os

# 建立 FastAPI 應用
app = FastAPI(
    title="Trimly AI Audio Processing Platform (Debug)",
    description="AI-powered audio editing and transcription platform - Debug Version",
    version="1.0.0-debug"
)

# 設定 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    """根端點 - 確認服務運行狀態"""
    return {
        "message": "Trimly AI Audio Processing Platform - Debug Version",
        "status": "running",
        "version": "1.0.0-debug",
        "environment": os.getenv("ENV", "development")
    }

@app.get("/health")
async def health_check():
    """健康檢查端點"""
    return {
        "status": "healthy",
        "service": "trimly-backend",
        "version": "1.0.0-debug"
    }

@app.get("/debug/env")
async def debug_environment():
    """除錯環境變數"""
    env_vars = {}
    for key in ["DATABASE_URL", "OPENAI_API_KEY", "ENV", "RENDER_DISK_PATH"]:
        value = os.getenv(key)
        if value:
            # 隱藏敏感資訊
            if "KEY" in key or "SECRET" in key:
                env_vars[key] = f"{value[:8]}..." if len(value) > 8 else "***"
            else:
                env_vars[key] = value
        else:
            env_vars[key] = "Not set"
    
    return {
        "environment_variables": env_vars,
        "python_path": os.sys.path[:3],  # 只顯示前3個路徑
        "working_directory": os.getcwd()
    }

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)

