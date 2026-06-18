@echo off
chcp 65001 >nul
echo ============================================
echo   倉儲看板 一鍵同步到雲端
echo   步驟1：從 NAS 匯入資料到 SQLite
echo   步驟2：上傳 SQLite 到 DBHub.io
echo ============================================
echo.

cd /d "%~dp0.."

echo [1/2] 從 NAS 匯入資料...
python db\import_to_db.py
if %errorlevel% neq 0 (
    echo [ERROR] 匯入失敗，請確認 NAS 已連線。
    pause
    exit /b 1
)
echo.

echo [2/2] 上傳到 DBHub.io...
python db\dbhub_sync.py push
if %errorlevel% neq 0 (
    echo [ERROR] 上傳失敗，請確認 .streamlit\secrets.toml 設定正確。
    pause
    exit /b 1
)
echo.
echo ============================================
echo   完成！雲端看板將在幾秒內顯示最新資料。
echo ============================================
pause
