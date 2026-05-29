@echo off
title ORing 材料系統
echo ================================================
echo   ORing 材料管理系統 啟動中，請稍候...
echo ================================================
echo.

REM 切換到專案目錄
cd /d "C:\Users\T26019\Desktop\oring_project_v8\oring_project"

REM 啟動 Streamlit（會自動開啟瀏覽器）
"C:\Users\T26019\AppData\Local\Python\pythoncore-3.14-64\python.exe" -m streamlit run app.py --server.headless false

pause
