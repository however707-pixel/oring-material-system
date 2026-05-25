@echo off
chcp 65001 >nul
echo ============================================
echo  供需表自動抓取腳本
echo  執行時間：%date% %time%
echo ============================================

set NAS_DIR=\\192.168.2.34\MO_Storage\ORing MO\ORing-MO 鼎新系統報表\LRPMR05庫存供需表(分倉)-每日(AM4-00抓取)(Ian提供)-2020
set LOCAL_DIR=C:\Users\T26019\Desktop\oring_project_v8\oring_project\data

:: 確認 NAS 可連線
if not exist "%NAS_DIR%" (
    echo [錯誤] NAS 路徑無法存取：%NAS_DIR%
    echo 請確認已連上公司網路。
    exit /b 1
)

:: 找最新的供需表（依檔名排序取最後一個）
set LATEST=
for /f "delims=" %%f in ('dir /b /o:n "%NAS_DIR%\供需表(分倉)-????????.xlsx" 2^>nul') do set LATEST=%%f

if "%LATEST%"=="" (
    echo [錯誤] NAS 資料夾中找不到供需表檔案。
    exit /b 1
)

echo [資訊] 最新供需表：%LATEST%

:: 複製到本機 data 資料夾
copy /y "%NAS_DIR%\%LATEST%" "%LOCAL_DIR%\sd_latest.xlsx" >nul
if errorlevel 1 (
    echo [錯誤] 複製失敗。
    exit /b 1
)

echo [成功] 已複製至：%LOCAL_DIR%\sd_latest.xlsx
echo ============================================
