# -*- coding: utf-8 -*-
"""
Dashboard 用的 SQLite 讀取層。

優先順序：
  1. 本機 data/wh_dashboard.db
  2. DBHub.io 下載（雲端 / NAS 離線時自動觸發）

回傳的 DataFrame 欄位名稱與原本直接讀 Excel 的 load_wh() 完全一致。
"""
import os
import sqlite3
import pandas as pd

BASE_DIR    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH     = os.path.join(BASE_DIR, "data", "wh_dashboard.db")
DBHUB_CACHE = os.path.join(BASE_DIR, "data", "wh_cloud.db")   # 雲端下載暫存


# ── DBHub 下載（只在雲端 / 本機 DB 不存在時呼叫）──────────────────────────────

def _try_pull_from_dbhub(dest: str = DBHUB_CACHE) -> str | None:
    """嘗試從 DBHub.io 下載 DB，成功回傳路徑，失敗回傳 None。"""
    try:
        from db.dbhub_sync import pull, dbhub_configured
        if not dbhub_configured():
            return None
        return pull(dest)
    except Exception:
        return None


def _effective_path() -> str | None:
    """
    回傳可用的 DB 檔案路徑：
      - 本機 DB 存在 → 直接用
      - 本機 DB 不存在 → 嘗試從 DBHub 下載
      - 都失敗 → None
    """
    if os.path.exists(DB_PATH):
        return DB_PATH
    # 先看暫存是否已下載過（避免每次重新下載）
    if os.path.exists(DBHUB_CACHE):
        return DBHUB_CACHE
    return _try_pull_from_dbhub()


# ── 公開介面 ──────────────────────────────────────────────────────────────────

def db_exists() -> bool:
    return _effective_path() is not None


def db_mtime():
    path = _effective_path()
    if not path:
        return None
    try:
        conn = sqlite3.connect(path)
        row = conn.execute(
            "SELECT source_mtime FROM import_log ORDER BY imported_at DESC LIMIT 1"
        ).fetchone()
        conn.close()
        if row and row[0]:
            return pd.to_datetime(row[0])
    except Exception:
        pass
    return pd.Timestamp(os.path.getmtime(path), unit="s")


def source_filename() -> str | None:
    path = _effective_path()
    if not path:
        return None
    try:
        conn = sqlite3.connect(path)
        row = conn.execute(
            "SELECT source_file FROM import_log ORDER BY imported_at DESC LIMIT 1"
        ).fetchone()
        conn.close()
        return os.path.basename(row[0]) if row and row[0] else None
    except Exception:
        return None


def load_wh():
    """回傳 (diao, inbound) 兩個 DataFrame，欄位同原 Excel 版。"""
    path = _effective_path()
    if not path:
        raise FileNotFoundError("找不到資料庫，且 DBHub 未設定或下載失敗。")
    conn = sqlite3.connect(path)
    try:
        diao = pd.read_sql_query("""
            SELECT order_date AS 開單日, order_type AS 單別, order_no AS 單號,
                   id AS 編號, demand_unit AS 需求單位, demand_date AS 需求日,
                   demand_qty AS 需求筆數, complete_qty AS 完成筆數,
                   prep_staff AS 備料人員, prep_date AS 備料日, complete_date AS 完成日,
                   note AS 備註, status AS 狀態, deduction AS 扣帳,
                   error_qty AS 出錯筆數, error_reason AS 出錯原因, note2 AS 備註2
            FROM transfer_orders
        """, conn)
        inbound = pd.read_sql_query("""
            SELECT inspect_date AS 驗畢日期, receive_date AS 接單日期,
                   expect_date AS 預計完成日, order_type AS 單別, order_no AS 單號,
                   id AS 編號, qty AS 筆數, pickup_date AS 取單日,
                   complete_date AS 完成日, inbound_staff AS 入庫人員, note AS 備註
            FROM inbound_orders
        """, conn)
    finally:
        conn.close()

    for c in ["開單日", "需求日", "備料日", "完成日"]:
        diao[c] = pd.to_datetime(diao[c], errors="coerce")
    for c in ["需求筆數", "完成筆數"]:
        diao[c] = pd.to_numeric(diao[c], errors="coerce").fillna(0)

    for c in ["驗畢日期", "接單日期", "預計完成日", "完成日", "取單日"]:
        inbound[c] = pd.to_datetime(inbound[c], errors="coerce")
    inbound["筆數"] = pd.to_numeric(inbound["筆數"], errors="coerce").fillna(0)

    return diao, inbound


def load_sched():
    """回傳排程 DataFrame，欄位：出貨日 / 料況狀態 / 預計產量（同原版）。"""
    path = _effective_path()
    if not path:
        return pd.DataFrame()
    conn = sqlite3.connect(path)
    try:
        df = pd.read_sql_query("""
            SELECT ship_date, planned_qty, material_rate, status_note
            FROM shipment_schedule
        """, conn)
    finally:
        conn.close()

    rows = []
    for _, r in df.iterrows():
        rate = float(r["material_rate"]) if pd.notna(r["material_rate"]) else 0.0
        hint_qi = any(k in str(r["status_note"]) for k in ("已發料", "已齊料", "已發放", "齊料"))
        if rate >= 1.0 or hint_qi:
            status = "已齊料"
        elif rate == 0.0:
            status = "完全缺料"
        else:
            status = f"缺料 {rate:.0%}"
        ship = pd.to_datetime(r["ship_date"]).date() if pd.notna(r["ship_date"]) else None
        rows.append({"出貨日": ship, "料況狀態": status, "預計產量": r["planned_qty"]})
    return pd.DataFrame(rows)
