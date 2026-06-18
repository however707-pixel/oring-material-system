@echo off
chcp 65001 >nul
echo ============================================
echo   ORing 資材系統  一鍵全站同步到雲端
echo   步驟1：NAS 資料複製到 data/
echo   步驟2：推送到 GitHub（雲端自動更新）
echo ============================================
echo.

cd /d "%~dp0.."

echo [1/4] 從 NAS 同步所有資料...
python db\sync_all.py
if %errorlevel% neq 0 (
    echo [ERROR] 資料同步失敗，請確認 NAS 已連線。
    pause
    exit /b 1
)
echo.

echo [2/4] 加入 Git 暫存區...
git add data\wh_dashboard.db
git add data\kanban_latest.xlsx 2>nul
git add data\kanban_prev.xlsx   2>nul
git add data\rma_latest.xlsx    2>nul
git add -u
echo.

echo [3/4] 建立提交...
git commit -m "data: 全站資料更新 %date% %time%"
echo.

echo [4/4] 推送到 GitHub...
git push origin main
if %errorlevel% neq 0 (
    echo [ERROR] 推送失敗，請確認網路連線。
    pause
    exit /b 1
)

echo.
echo ============================================
echo   完成！Streamlit Cloud 將在 1 分鐘內
echo   自動重新部署並顯示所有頁面的最新資料。
echo ============================================
pause
