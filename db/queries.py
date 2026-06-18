# -*- coding: utf-8 -*-
"""
Dashboard 用的 SQLite 讀取層。
資料庫 data/wh_dashboard.db 由 db/import_to_db.py 從 NAS 匯入，
並透過 git push 同步到 GitHub，Streamlit Cloud 直接讀取 repo 內的檔案。
"""
import os
import sqlite3
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH  = os.path.join(BASE_DIR, "data", "wh_dashboard.db")


def db_exists() -> bool:
    return os.path.exists(DB_PATH)


def db_mtime():
    if not db_exists():
        return None
    try:
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            "SELECT source_mtime FROM import_log ORDER BY imported_at DESC LIMIT 1"
        ).fetchone()
        conn.close()
        if row and row[0]:
            return pd.to_datetime(row[0])
    except Exception:
        pass
    return pd.Timestamp(os.path.getmtime(DB_PATH), unit="s")


def source_filename() -> str | None:
    if not db_exists():
        return None
    try:
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            "SELECT source_file FROM import_log ORDER BY imported_at DESC LIMIT 1"
        ).fetchone()
        conn.close()
        return os.path.basename(row[0]) if row and row[0] else None
    except Exception:
        return None


def load_wh():
    """回傳 (diao, inbound) 兩個 DataFrame，欄位同原 Excel 版。"""
    conn = sqlite3.connect(DB_PATH)
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
    if not db_exists():
        return pd.DataFrame()
    conn = sqlite3.connect(DB_PATH)
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
