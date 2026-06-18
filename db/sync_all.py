# -*- coding: utf-8 -*-
"""
全站 NAS → data/ 資料同步腳本
執行後再 git push，Streamlit Cloud 即可自動載入所有頁面資料。
"""
import os, glob, shutil, sys, subprocess, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")

KANBAN_DIR  = r"\\192.168.2.34\MO_Storage\ORing MO\ORing-MO 工作\早會資料夾"
KANBAN_FILE = "簡版-工單缺料狀況.xlsx"

RMA_DIR = (r"\\192.168.2.34\MO_Storage\ORing MO\ORing-MO 工作\維修部"
           r"\3_紀錄文件\3_01_RMA紀錄_交換機\3_01_01_每日統計_交換機\RMA總表")


def step_wh_db():
    print("[1/3] 匯入倉儲資料到 SQLite (wh_dashboard.db)...")
    script = os.path.join(BASE, "db", "import_to_db.py")
    r = subprocess.run([sys.executable, script], capture_output=True, text=True)
    if r.returncode != 0:
        print(f"  ⚠ 警告：{r.stderr.strip()[:200]}")
    else:
        print("  ✓ 完成")


def step_kanban():
    print("[2/3] 複製工單缺料狀況檔案...")
    pattern = os.path.join(KANBAN_DIR, "**", KANBAN_FILE)
    files = glob.glob(pattern, recursive=True)
    if not files:
        print("  ⚠ 找不到 簡版-工單缺料狀況.xlsx，請確認 NAS 已連線")
        return False
    files.sort(key=os.path.getmtime, reverse=True)
    shutil.copy2(files[0], os.path.join(DATA, "kanban_latest.xlsx"))
    folder0 = os.path.basename(os.path.dirname(files[0]))
    print(f"  ✓ 最新版：{folder0}\\{KANBAN_FILE}")
    prev = files[1] if len(files) >= 2 else files[0]
    shutil.copy2(prev, os.path.join(DATA, "kanban_prev.xlsx"))
    folder1 = os.path.basename(os.path.dirname(prev))
    print(f"  ✓ 前一版：{folder1}\\{KANBAN_FILE}")
    return True


def step_rma():
    print("[3/3] 複製 RMA 總表...")
    try:
        files = [
            f for f in os.listdir(RMA_DIR)
            if not f.startswith("~$") and "RMA" in f and f.lower().endswith(".xlsx")
        ]
        if not files:
            print("  ⚠ 找不到 RMA 總表，請確認 NAS 已連線")
            return False
        files.sort(key=lambda f: os.path.getmtime(os.path.join(RMA_DIR, f)), reverse=True)
        shutil.copy2(os.path.join(RMA_DIR, files[0]), os.path.join(DATA, "rma_latest.xlsx"))
        print(f"  ✓ {files[0]}")
        return True
    except Exception as e:
        print(f"  ⚠ 警告：{e}")
        return False


if __name__ == "__main__":
    print("=" * 52)
    print("  ORing 資材系統  ·  全站資料同步到 data/")
    print("=" * 52)
    step_wh_db()
    step_kanban()
    step_rma()
    print()
    print("✓ 同步完成，data/ 資料夾已更新。")
    print("  接下來：git add data/ && git push 推送到雲端")
