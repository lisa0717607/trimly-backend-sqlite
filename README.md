# Trimly — Clean SQLite Backend (FastAPI)

這是最小可用（MVP）的後端，使用 FastAPI + SQLite。已內建：
- 註冊 `/auth/register`、登入 `/auth/login`、JWT 驗證（Swagger 右上 Authorize）
- `/me` 驗證範例、`/api/health` 健康檢查
- OpenAPI 自動帶 Bearer（貼 token 本體即可）

## 部署（Render）
1. 建新 Web Service（選 Docker）。
2. 上傳本專案（根目錄需包含：`requirements.txt`、`Dockerfile`、`models.py`、`app.py`）。
3. Environment 新增：
   - `JWT_SECRET`：至少 64 字的亂碼（固定不要改動）
   - `ADMIN_EMAILS`：你的管理員信箱（例如 `lisa0717607@gmail.com`）
4. Manual Deploy → Clear build cache & deploy
5. 進 `/docs` 測試：
   - `POST /auth/register` → 拿 `token`
   - 右上 Authorize → 貼 **token 本體**
   - `GET /me` → 200

## 注意
- 免費層 SQLite 放在 `/tmp`，service 重啟會清空；之後升級請改用 Persistent Disk 或 PostgreSQL。
- 更換 `JWT_SECRET` 後，舊 token 會失效，需要重新登入拿新的。
