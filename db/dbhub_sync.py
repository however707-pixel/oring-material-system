# -*- coding: utf-8 -*-
"""
DBHub.io 同步工具

上傳（本機 → DBHub）：
    python db/dbhub_sync.py push

下載（DBHub → 本機，供雲端 Streamlit 使用）：
    python db/dbhub_sync.py pull

設定方式（三擇一）：
  1. 在 .streamlit/secrets.toml 填入 [dbhub] 區塊
  2. 設定環境變數 DBHUB_API_KEY / DBHUB_OWNER / DBHUB_DBNAME
  3. 直接在本檔案最下方的 DEFAULT_* 填入
"""
import os
import sys
import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH  = os.path.join(BASE_DIR, "data", "wh_dashboard.db")

# ── 備用預設值（不建議直接填 API Key，建議用 secrets.toml 或環境變數）──────
DEFAULT_API_KEY = ""
DEFAULT_OWNER   = ""
DEFAULT_DBNAME  = "wh_dashboard.db"

UPLOAD_URL   = "https://api.dbhub.io/v1/upload"
DOWNLOAD_URL = "https://api.dbhub.io/v1/download"


def _get_config():
    """優先順序：secrets.toml > 環境變數 > 預設值"""
    api_key = owner = dbname = ""
    try:
        import streamlit as st
        cfg = st.secrets.get("dbhub", {})
        api_key = cfg.get("api_key", "")
        owner   = cfg.get("owner",   "")
        dbname  = cfg.get("dbname",  DEFAULT_DBNAME)
    except Exception:
        pass
    if not api_key:
        api_key = os.environ.get("DBHUB_API_KEY", DEFAULT_API_KEY)
    if not owner:
        owner   = os.environ.get("DBHUB_OWNER",   DEFAULT_OWNER)
    if not dbname:
        dbname  = os.environ.get("DBHUB_DBNAME",  DEFAULT_DBNAME)
    return api_key.strip(), owner.strip(), dbname.strip()


def push():
    """上傳本機 SQLite 到 DBHub.io"""
    api_key, owner, dbname = _get_config()
    if not api_key:
        print("[ERROR] 請先設定 DBHUB_API_KEY（見 .streamlit/secrets.toml）")
        return False
    if not os.path.exists(DB_PATH):
        print(f"[ERROR] 找不到資料庫：{DB_PATH}")
        return False
    print(f"[INFO] 上傳 {DB_PATH} → DBHub.io ({owner}/{dbname}) ...")
    with open(DB_PATH, "rb") as f:
        db_bytes = f.read()
    try:
        resp = requests.post(
            UPLOAD_URL,
            data={"apikey": api_key, "dbname": dbname, "public": "false", "force": "true"},
            files={"database": (dbname, db_bytes, "application/octet-stream")},
            timeout=120,
        )
        if resp.status_code == 200:
            size_kb = len(db_bytes) / 1024
            print(f"[OK] 上傳成功（{size_kb:.1f} KB）→ https://dbhub.io/{owner}/{dbname}")
            return True
        else:
            print(f"[ERROR] 上傳失敗 HTTP {resp.status_code}：{resp.text[:200]}")
            return False
    except Exception as e:
        print(f"[ERROR] 連線失敗：{e}")
        return False


def pull(dest_path: str = None):
    """從 DBHub.io 下載 SQLite，回傳存檔路徑或 None"""
    api_key, owner, dbname = _get_config()
    if not api_key or not owner:
        return None
    dest = dest_path or DB_PATH
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    try:
        resp = requests.post(
            DOWNLOAD_URL,
            data={"apikey": api_key, "dbowner": owner, "dbname": dbname},
            timeout=60,
        )
        if resp.status_code == 200 and len(resp.content) > 1024:
            with open(dest, "wb") as f:
                f.write(resp.content)
            return dest
    except Exception:
        pass
    return None


def dbhub_configured():
    """回傳是否已設定 DBHub 憑證"""
    api_key, owner, _ = _get_config()
    return bool(api_key and owner)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "push"
    if cmd == "push":
        sys.exit(0 if push() else 1)
    elif cmd == "pull":
        path = pull()
        print(f"[OK] 下載至：{path}" if path else "[ERROR] 下載失敗")
        sys.exit(0 if path else 1)
    else:
        print(f"用法：python db/dbhub_sync.py [push|pull]")
        sys.exit(1)
