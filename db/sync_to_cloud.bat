@echo off
chcp 65001 >nul
echo ============================================
echo   倉儲看板  一鍵同步到雲端
echo   步驟1：從 NAS 匯入資料到 SQLite
echo   步驟2：推送到 GitHub（雲端自動更新）
echo ============================================
echo.

cd /d "%~dp0.."

echo [1/3] 從 NAS 匯入資料...
python db\import_to_db.py
if %errorlevel% neq 0 (
    echo [ERROR] 匯入失敗，請確認 NAS 已連線。
    pause
    exit /b 1
)
echo.

echo [2/3] 將資料庫加入 Git...
git add data\wh_dashboard.db
git add -u
echo.

echo [3/3] 推送到 GitHub...
git commit -m "data: 更新倉儲看板資料庫 %date% %time%"
git push origin main
if %errorlevel% neq 0 (
    echo [ERROR] 推送失敗，請確認網路連線。
    pause
    exit /b 1
)
echo.
echo ============================================
echo   完成！Streamlit Cloud 將在 1 分鐘內
echo   自動重新部署並顯示最新資料。
echo ============================================
pause
