# ============================================================
#  ORing 供需表自動抓取腳本
#  邏輯：
#    每日 09:00 起每小時執行一次
#    ① 若今日供需表已成功抓取（sd_fetch_done.txt 記錄今日日期）→ 直接結束
#    ② 嘗試抓今日檔案（供需表(分倉)-YYYYMMDD.xlsx）
#       → 找到：複製至 data\sd_latest.xlsx，寫入完成標記，結束
#       → 找不到：複製最近一筆（前一天）供 App 暫用，不寫完成標記
# ============================================================

$NasDir    = "\\192.168.2.34\MO_Storage\ORing MO\ORing-MO 鼎新系統報表\LRPMR05庫存供需表(分倉)-每日(AM4-00抓取)(Ian提供)-2020"
$LocalDir  = "C:\Users\T26019\Desktop\oring_project_v8\oring_project\data"
$LocalFile = "$LocalDir\sd_latest.xlsx"
$DoneFile  = "$LocalDir\sd_fetch_done.txt"
$Today     = Get-Date -Format "yyyyMMdd"
$TodayXlsx = "供需表(分倉)-$Today.xlsx"
$LogFile   = "$LocalDir\fetch_log.txt"

function Write-Log($msg) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "$ts  $msg" | Tee-Object -FilePath $LogFile -Append
}

Write-Log "===== 開始執行 ====="

# ① 已完成今日抓取 → 不需重複
if (Test-Path $DoneFile) {
    $doneDate = (Get-Content $DoneFile -ErrorAction SilentlyContinue).Trim()
    if ($doneDate -eq $Today) {
        Write-Log "[略過] 今日 ($Today) 供需表已抓取完成，無需重複執行。"
        exit 0
    }
}

# ② 確認 NAS 可連線
if (-not (Test-Path $NasDir)) {
    Write-Log "[錯誤] NAS 路徑無法存取，請確認公司網路連線。"
    exit 1
}

# ③ 嘗試抓今日檔案
$TodayPath = Join-Path $NasDir $TodayXlsx
if (Test-Path $TodayPath) {
    Copy-Item $TodayPath $LocalFile -Force
    $Today | Out-File $DoneFile -Encoding UTF8 -NoNewline
    Write-Log "[成功] 已抓取今日供需表：$TodayXlsx → sd_latest.xlsx"
    Write-Log "===== 完成（今日任務結束，後續不再抓取）====="
    exit 0
}

# ④ 今日尚未產生 → 找最近的備用
Write-Log "[提示] 今日供需表尚未產生，改用最近一筆備用。"
$AllFiles = Get-ChildItem -Path $NasDir -Filter "供需表(分倉)-????????.xlsx" |
            Sort-Object Name
if ($AllFiles.Count -eq 0) {
    Write-Log "[錯誤] NAS 找不到任何供需表。"
    exit 1
}
$Fallback = $AllFiles[-1]
Copy-Item $Fallback.FullName $LocalFile -Force
Write-Log "[備用] 使用最新供需表：$($Fallback.Name) → sd_latest.xlsx（未標記完成，下次繼續嘗試今日）"
Write-Log "===== 完成 ====="
exit 0
