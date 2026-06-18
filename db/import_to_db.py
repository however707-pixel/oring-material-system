# -*- coding: utf-8 -*-
"""
匯入腳本：NAS Excel → SQLite

用法：
    python db/import_to_db.py            # 自動抓 NAS 最新檔匯入
    python db/import_to_db.py 某檔.xlsx  # 指定檔案匯入

可由 Windows 工作排程器 / auto_fetch_sd.bat 定時呼叫。
"""
import os
import re
import sys
import glob
import sqlite3
from datetime import date, datetime

import pandas as pd

# ── 路徑設定 ─────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH  = os.path.join(BASE_DIR, "data", "wh_dashboard.db")
SCHEMA   = os.path.join(BASE_DIR, "db", "schema.sql")

_NAS_DIR  = r"\\192.168.2.34\MO_Storage\ORing MO\ORing-MO 工作\資材部\每日調撥與送燒ic(NEW)\3月-6月進貨資料表\調件備料統計表"
_FILE_PFX = "調件備料統計"

_SCHED_DIR  = r"\\192.168.2.34\MO_Storage\ORing MO\ORing-MO 工作\早會資料夾"
_SCHED_FILE = "簡版-工單缺料狀況.xlsx"


# ── 尋找來源檔 ───────────────────────────────────────────
def find_latest_wh():
    try:
        files = [
            os.path.join(_NAS_DIR, f)
            for f in os.listdir(_NAS_DIR)
            if not f.startswith("~$") and _FILE_PFX in f
            and f.lower().endswith((".xlsx", ".xls"))
        ]
        if not files:
            files = glob.glob(os.path.join(_NAS_DIR, f"**/*{_FILE_PFX}*.xlsx"), recursive=True)
        if not files:
            return None, None
        files.sort(key=os.path.getmtime, reverse=True)
        f = files[0]
        return f, datetime.fromtimestamp(os.path.getmtime(f))
    except Exception as e:
        print(f"[WARN] 找不到調件備料統計檔：{e}")
        return None, None


def find_latest_sched():
    try:
        files = glob.glob(os.path.join(_SCHED_DIR, "**", _SCHED_FILE), recursive=True)
        if not files:
            return None
        files.sort(key=os.path.getmtime, reverse=True)
        return files[0]
    except Exception:
        return None


# ── 小工具 ───────────────────────────────────────────────
def _d(v):
    """轉日期字串 YYYY-MM-DD 或 None"""
    if pd.isna(v):
        return None
    try:
        ts = pd.to_datetime(v, errors="coerce")
        return None if pd.isna(ts) else ts.strftime("%Y-%m-%d")
    except Exception:
        return None


def _i(v):
    """轉整數或 None"""
    if pd.isna(v):
        return None
    try:
        return int(float(v))
    except Exception:
        return None


def _s(v):
    if pd.isna(v):
        return None
    s = str(v).strip()
    return s if s and s.lower() != "nan" else None


def _header_df(xls, sheet):
    """讀分頁，把第一列當欄名"""
    df = pd.read_excel(xls, sheet_name=sheet, header=None)
    df.columns = df.iloc[0]
    return df.iloc[1:].reset_index(drop=True)


# ── 解析各分頁 → list of tuples ──────────────────────────
def parse_transfer(xls):
    df = _header_df(xls, "調撥單")
    rows = []
    for _, r in df.iterrows():
        oid = _s(r.get("編號"))
        if not oid:
            continue
        rows.append((
            oid, _s(r.get("單別")), _s(r.get("單號")), _d(r.get("開單日")),
            _s(r.get("需求單位")), _d(r.get("需求日")), _i(r.get("需求筆數")),
            _i(r.get("完成筆數")), _s(r.get("備料人員")), _d(r.get("備料日")),
            _d(r.get("完成日")), _s(r.get("狀態")), _s(r.get("備註")),
            _s(r.get("扣帳")), _i(r.get("出錯筆數")), _s(r.get("出錯原因")),
            _s(r.get("備註2")),
        ))
    return rows


def parse_inbound(xls):
    df = _header_df(xls, "入庫單據")
    rows = []
    for _, r in df.iterrows():
        oid = _s(r.get("編號"))
        if not oid:
            continue
        rows.append((
            oid, _s(r.get("單別")), _s(r.get("單號")), _d(r.get("驗畢日期")),
            _d(r.get("接單日期")), _d(r.get("預計完成日")), _i(r.get("筆數")),
            _d(r.get("取單日")), _d(r.get("完成日")), _s(r.get("入庫人員")),
            _s(r.get("備註")),
        ))
    return rows


def parse_error(xls):
    df = _header_df(xls, "錯料歸還追蹤")
    rows = []
    for _, r in df.iterrows():
        # 至少要有通知日期或單號才算一筆
        if _s(r.get("單號")) is None and _d(r.get("通知日期")) is None and _s(r.get("料號")) is None:
            continue
        rows.append((
            _d(r.get("通知日期")), _s(r.get("備料人員")), _s(r.get("單號")),
            _s(r.get("料號")), _i(r.get("數量")), _d(r.get("結案日期")),
            _s(r.get("單位")), _s(r.get("備註")),
        ))
    return rows


def parse_schedule(path):
    """簡版-工單缺料狀況 LIST"""
    df = pd.read_excel(path, sheet_name="LIST", header=0)
    today = date.today()
    rows = []
    for _, r in df.iterrows():
        wo = _s(r.iloc[1])               # 工單
        if not wo:
            continue
        product = _s(r.iloc[2])          # 產品編號
        qty = _i(r.iloc[3])              # 預計產量
        rate = 0.0
        if pd.notna(r.iloc[5]):
            try:
                rate = float(r.iloc[5])
            except Exception:
                rate = 0.0
        note = _s(r.iloc[8])             # 重點提示

        # 出貨日（沿用原 dashboard 解析邏輯）
        ship = None
        raw_ship = r.iloc[12]
        if pd.notna(raw_ship):
            s = str(raw_ship).strip()
            if s not in ("", "nan", "None", "TBD", "試產", "00:00:00"):
                try:
                    ship = pd.to_datetime(s).strftime("%Y-%m-%d")
                except Exception:
                    found = re.findall(r"(\d{1,2})/(\d{1,2})", s)
                    if found:
                        m2, d2 = int(found[0][0]), int(found[0][1])
                        try:
                            ship = date(today.year, m2, d2).strftime("%Y-%m-%d")
                        except Exception:
                            pass
        rows.append((wo, product, qty, rate, ship, note))
    return rows


# ── 主流程 ───────────────────────────────────────────────
def init_db(conn):
    with open(SCHEMA, encoding="utf-8") as f:
        conn.executescript(f.read())


def main(src_arg=None):
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    if src_arg:
        src_file = src_arg
        src_mtime = datetime.fromtimestamp(os.path.getmtime(src_file))
    else:
        src_file, src_mtime = find_latest_wh()

    if not src_file or not os.path.exists(src_file):
        print("[ERROR] 找不到來源 Excel，請確認 NAS 連線。")
        sys.exit(1)

    print(f"[INFO] 來源檔：{src_file}")
    print(f"[INFO] 資料庫：{DB_PATH}")

    xls = pd.ExcelFile(src_file)
    transfer_rows = parse_transfer(xls)
    inbound_rows  = parse_inbound(xls)
    error_rows    = parse_error(xls)

    sched_path = find_latest_sched()
    sched_rows = parse_schedule(sched_path) if sched_path else []

    conn = sqlite3.connect(DB_PATH)
    try:
        init_db(conn)
        cur = conn.cursor()

        # 調撥單：以編號 upsert
        cur.executemany("""
            INSERT INTO transfer_orders
              (id, order_type, order_no, order_date, demand_unit, demand_date,
               demand_qty, complete_qty, prep_staff, prep_date, complete_date,
               status, note, deduction, error_qty, error_reason, note2, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
            ON CONFLICT(id) DO UPDATE SET
              order_type=excluded.order_type, order_no=excluded.order_no,
              order_date=excluded.order_date, demand_unit=excluded.demand_unit,
              demand_date=excluded.demand_date, demand_qty=excluded.demand_qty,
              complete_qty=excluded.complete_qty, prep_staff=excluded.prep_staff,
              prep_date=excluded.prep_date, complete_date=excluded.complete_date,
              status=excluded.status, note=excluded.note, deduction=excluded.deduction,
              error_qty=excluded.error_qty, error_reason=excluded.error_reason,
              note2=excluded.note2, updated_at=CURRENT_TIMESTAMP
        """, transfer_rows)

        # 入庫單據：以編號 upsert
        cur.executemany("""
            INSERT INTO inbound_orders
              (id, order_type, order_no, inspect_date, receive_date, expect_date,
               qty, pickup_date, complete_date, inbound_staff, note, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
            ON CONFLICT(id) DO UPDATE SET
              order_type=excluded.order_type, inspect_date=excluded.inspect_date,
              receive_date=excluded.receive_date, expect_date=excluded.expect_date,
              qty=excluded.qty, pickup_date=excluded.pickup_date,
              complete_date=excluded.complete_date, inbound_staff=excluded.inbound_staff,
              note=excluded.note, updated_at=CURRENT_TIMESTAMP
        """, inbound_rows)

        # 錯料追蹤：無自然鍵，整表重建
        cur.execute("DELETE FROM error_returns")
        cur.executemany("""
            INSERT INTO error_returns
              (notify_date, prep_staff, order_no, part_no, qty, close_date, unit, note)
            VALUES (?,?,?,?,?,?,?,?)
        """, error_rows)

        # 出貨排程：只保最新快照，整表重建後 upsert
        if sched_rows:
            cur.execute("DELETE FROM shipment_schedule")
            cur.executemany("""
                INSERT INTO shipment_schedule
                  (work_order, product_no, planned_qty, material_rate, ship_date, status_note, updated_at)
                VALUES (?,?,?,?,?,?,CURRENT_TIMESTAMP)
                ON CONFLICT(work_order) DO UPDATE SET
                  product_no=excluded.product_no, planned_qty=excluded.planned_qty,
                  material_rate=excluded.material_rate, ship_date=excluded.ship_date,
                  status_note=excluded.status_note, updated_at=CURRENT_TIMESTAMP
            """, sched_rows)

        # 匯入紀錄
        cur.execute("""
            INSERT INTO import_log
              (source_file, source_mtime, transfer_rows, inbound_rows, error_rows, schedule_rows)
            VALUES (?,?,?,?,?,?)
        """, (src_file, src_mtime.strftime("%Y-%m-%d %H:%M:%S"),
              len(transfer_rows), len(inbound_rows), len(error_rows), len(sched_rows)))

        conn.commit()
        print(f"[OK] 調撥單 {len(transfer_rows)} ｜入庫 {len(inbound_rows)} ｜"
              f"錯料 {len(error_rows)} ｜排程 {len(sched_rows)}")
    finally:
        conn.close()


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
