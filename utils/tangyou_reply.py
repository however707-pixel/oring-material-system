# -*- coding: utf-8 -*-
"""
唐佑缺料回信：H2O缺料明細 P欄（E.T.A 預計進料日）自動改寫

口徑（2026/07 唐佑回信規則，逐「列」計算）：
  時間窗 = 只改 B欄預計齊料日 ≤ 基準日+2週(14天) 的列（逾期/空白視為窗內），
           超過的列 P欄不動；因需求依日期先後分配，排除晚的列不影響窗內結果
  供給池 = 我司四倉（電子/機構/半成品/成品倉，同 3_h2o.py VALID_SRC）庫存可用量
           ＋「預計進貨」（我司四倉＋唐佑倉；進唐佑倉的只保留給唐佑）
  需求   = 其他委外廠未滿足需求（各代工倉自身庫存/進貨掃過後仍缺的量，帶需求日）
           ＋ 唐佑各列缺料（H2O 明細 N欄不足數量，需求日=B欄預計齊料日）
  分配   = 需求日早者先給料（同日委外優先，取保守），逐列判定：
    ・全由現有庫存補齊             → P = 基準日 + 2 工作天
    ・需等進貨，最後補齊那筆為準   → P = 該進貨日 + 4 工作天
    ・補齊靠的進貨已逾期           → P = 基準日 + 4 工作天，標示提醒
    ・供給不足 / 供需表查無品號    → P 欄不動，摘要標紅人工處理
  工作天：僅跳過週六/週日（國定假日不扣）。
寫回：Excel COM 只改 H2O 工作表 P 欄（依工作表列號逐列），其餘內容/格式不動。
"""
import datetime as _dt
import glob
import os
import re

import pandas as pd

from utils.wo_material_trace import WH_GROUP

# 供需表(分倉) 每日檔（Ian 提供，表頭在第 1 列；異於 LRPMR05 原始匯出的 header=3）
NAS_LRP_DIR = (r"\\192.168.2.34\MO_Storage\ORing MO\ORing-MO 鼎新系統報表"
               r"\LRPMR05庫存供需表(分倉)-每日(AM4-00抓取)(Ian提供)-2020")
LRP_PATTERN = "供需表(分倉)-*.xlsx"

# 唐佑每日缺料明細（複本 H2O缺料明細YYMMDD.xls）
NAS_H2O_DIR = (r"\\192.168.2.34\MO_Storage\ORing MO\ORing-MO 工作\資材部"
               r"\每日調撥與送燒ic(NEW)\@唐佑專屬缺料表")
H2O_PATTERN = "*H2O缺料明細*.xls*"

# 我司可調撥倉（名稱＋代號；口徑同 pages/3_h2o.py VALID_SRC）
OUR_WH = {"電子倉", "R01", "機構倉", "R02", "半成品倉", "R04", "成品倉", "R05"}
# 唐佑相關倉（進貨直送唐佑也視為供給，但保留給唐佑、不給其他委外分）
TANG_WH = {"唐佑代工倉", "S07", "S02", "唐佑-在途倉", "S071"}
# 其他委外代工倉（含代號與名稱；沿用 wo_material_trace 的庫群組對照）
COMP_WH = {k for k, v in WH_GROUP.items()
           if "代工倉" in v and not v.startswith("4")}

DEMAND_KINDS = {"預計領用", "異動領料", "預計銷售"}
LOCAL_SUPPLY_KINDS = {"預計進貨", "異動入庫"}

ST_STOCK = "庫存滿足"
ST_INCOMING = "等進貨"
ST_OVERDUE = "逾期進貨"
ST_SHORT = "供給不足"
ST_NOT_FOUND = "供需表查無"
ST_NOQTY = "無需求量"
ST_FUTURE = "超過2週"
NO_CHANGE = {ST_SHORT, ST_NOT_FOUND, ST_NOQTY}


def latest_lrp_file(folder: str = NAS_LRP_DIR) -> str | None:
    """取資料夾中日期最新的 供需表(分倉)-YYYYMMDD.xlsx（檔名排序即日期排序）。"""
    files = [f for f in glob.glob(os.path.join(folder, LRP_PATTERN))
             if not os.path.basename(f).startswith("~$")]
    return max(files, default=None, key=os.path.basename)


def latest_h2o_file(folder: str = NAS_H2O_DIR) -> str | None:
    """取 NAS 唐佑專屬缺料表資料夾中最新的 H2O缺料明細（以修改時間排序）。"""
    files = [f for f in glob.glob(os.path.join(folder, H2O_PATTERN))
             if not os.path.basename(f).startswith("~$")]
    return max(files, default=None, key=os.path.getmtime)


def add_workdays(base: _dt.date, n: int) -> _dt.date:
    """base 起算加 n 個工作天（跳過週六日）。"""
    d = base
    for _ in range(n):
        d += _dt.timedelta(days=1)
        while d.weekday() >= 5:
            d += _dt.timedelta(days=1)
    return d


def _s(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip()


def parse_lrp_daily(src) -> pd.DataFrame:
    """解析每日 供需表(分倉)（結構同 utils.wo_material_trace.parse_lrp，但表頭第 1 列）。"""
    df = pd.read_excel(src, header=0, engine="calamine")
    df.columns = [re.sub(r"\s+", "", str(c)) for c in df.columns]
    need = ["品號", "庫別", "日期", "異動別", "異動數量"]
    miss = [c for c in need if c not in df.columns]
    if miss:
        raise ValueError(f"供需表缺少欄位 {miss}，請確認是『供需表(分倉)-YYYYMMDD.xlsx』每日檔")

    out = pd.DataFrame({
        "品號": _s(df["品號"]), "庫別": _s(df["庫別"]),
        "日期str": _s(df["日期"]), "異動別": _s(df["異動別"]),
        "數量": pd.to_numeric(df["異動數量"], errors="coerce").fillna(0.0),
    })
    # 合計列的庫別欄放品號（污染回填）先剔除；小計列回填後才刪（同 parse_lrp 註解）
    out = out[~out["日期str"].str.startswith("合計")].copy()
    out["is_stock"] = out["日期str"].str.startswith("庫存可用量")
    wh = out["庫別"].replace("", pd.NA).bfill().fillna("")
    out["庫別"] = out["庫別"].where(~out["is_stock"], wh)
    out = out[~out["日期str"].str.startswith("小計")].copy()
    out["日期"] = pd.to_datetime(out["日期str"], format="ISO8601", errors="coerce")
    out = out[out["品號"] != ""]
    out = out[out["is_stock"] | ((out["異動別"] != "") & out["日期"].notna())]
    return out.reset_index(drop=True)


# ═══════════════════════════════════════════════════════════════════════════
# 配料模擬
# ═══════════════════════════════════════════════════════════════════════════
def _competitor_unmet(comp_blocks: dict) -> list[tuple[_dt.date, float]]:
    """其他委外代工倉的未滿足需求 [(需求日, 數量)]。

    各代工倉獨立掃時間軸：自身庫存起算，領用先吃自身庫存/自身進貨，
    吃不到的量即為要向我司調撥的競爭需求。
    comp_blocks = {庫群組: {"bal": 期初可用量, "rows": [(日期, 異動別, 數量)]}}
    """
    unmet = []
    for blk in comp_blocks.values():
        bal = blk["bal"]
        for d, kind, qty in sorted(blk["rows"], key=lambda x: x[0]):
            if kind in DEMAND_KINDS:
                take = min(bal, qty)
                bal -= take
                if qty - take > 0:
                    unmet.append((d, qty - take))
            elif kind in LOCAL_SUPPLY_KINDS:
                bal += qty
    return unmet


def _index_lrp(lrp: pd.DataFrame, parts: set) -> dict:
    """一次掃描把供需表整理成純 python 結構（逐品號 pandas 過濾 930 次會跑數十秒）。

    回傳 {品號: {"stock_our": 我司四倉可用量,
                 "arr": [(日期, 數量, tang_only)],
                 "comp": {庫群組: {"bal":…, "rows":[(日期,異動別,數量)]}}}}
    """
    sub = lrp[lrp["品號"].isin(parts)]
    data: dict = {}
    for pno, wh, kind, qty, is_stock, d in zip(
            sub["品號"].tolist(), sub["庫別"].tolist(), sub["異動別"].tolist(),
            sub["數量"].tolist(), sub["is_stock"].tolist(), sub["日期"].tolist()):
        rec = data.setdefault(pno, {"stock_our": 0.0, "arr": [], "comp": {}})
        in_comp = wh in COMP_WH
        if in_comp:
            grp = rec["comp"].setdefault(WH_GROUP.get(wh, wh), {"bal": 0.0, "rows": []})
        if is_stock:
            if wh in OUR_WH:
                rec["stock_our"] += float(qty)
            elif in_comp:
                grp["bal"] += float(qty)
            continue
        if pd.isna(d):
            continue
        day = d.date()
        if kind == "預計進貨" and (wh in OUR_WH or wh in TANG_WH):
            rec["arr"].append((day, float(qty), wh in TANG_WH))
        if in_comp:
            grp["rows"].append((day, kind, float(qty)))
    return data


def compute_allocation(lrp: pd.DataFrame, h2o: pd.DataFrame,
                       base_date: _dt.date, horizon_days: int = 14) -> pd.DataFrame:
    """逐列配料。h2o 需含欄位：sheet_row/品號/齊料日/需求N。

    只處理 齊料日 ≤ 基準日+horizon_days 的列（逾期/空白視為窗內）；
    超過時間窗的列不進需求隊列、P欄不改。因需求依日期先後分配，
    排除較晚的列不影響窗內列的結果。
    回傳 h2o 附加欄位：狀態/新P日期/我司庫存/委外競爭/說明。
    """
    cutoff = base_date + _dt.timedelta(days=horizon_days)
    known = set(lrp["品號"].unique())
    data = _index_lrp(lrp, set(h2o["品號"].unique()))
    res: dict = {}      # h2o index -> (狀態, 新P日期, 我司庫存, 委外競爭, 說明)

    def _kd(row) -> _dt.date:
        kd = row["齊料日"]
        if pd.isna(kd):
            return base_date
        return kd.date() if isinstance(kd, _dt.datetime) else kd

    def _future_note(kd: _dt.date) -> str:
        return f"齊料日 {kd:%Y/%m/%d} 超過基準日+{horizon_days}天，P欄不修改"

    for pno, rows in h2o.groupby("品號", sort=False):
        if pno not in known:
            for idx, r in rows.iterrows():
                kd = _kd(r)
                if kd > cutoff:
                    res[idx] = (ST_FUTURE, None, 0.0, 0.0, _future_note(kd))
                else:
                    res[idx] = (ST_NOT_FOUND, None, 0.0, 0.0, "供需表沒有此品號，P欄不修改")
            continue

        rec = data[pno]
        stock = rec["stock_our"]

        # 供給層：現有庫存(基準日) + 預計進貨(逾期者視為基準日到貨)
        layers = [{"date": base_date, "qty": stock, "kind": "stock",
                   "tang_only": False}]
        for d, qty, tang_only in sorted(rec["arr"], key=lambda x: x[0]):
            layers.append({"date": max(d, base_date), "qty": qty,
                           "kind": "overdue" if d < base_date else "arrival",
                           "tang_only": tang_only})
        layers.sort(key=lambda x: (x["date"], x["kind"] != "stock"))

        comp = _competitor_unmet(rec["comp"])
        comp_total = sum(q for _, q in comp)

        # 需求依需求日排序（同日委外優先＝保守）；唐佑列以齊料日、缺 N欄量。
        # 超過時間窗的列不進隊列、直接標記不改。
        demands = [(d, 0, None, q) for d, q in comp]
        row_out = {}
        for idx, r in rows.iterrows():
            kd = _kd(r)
            if kd > cutoff:
                row_out[idx] = (ST_FUTURE, None, _future_note(kd))
            else:
                demands.append((kd, 1, idx, float(r["需求N"])))
        demands.sort(key=lambda x: (x[0], x[1]))
        for _, _, ridx, need in demands:
            if ridx is not None and need <= 0:
                row_out[ridx] = (ST_NOQTY, None, "N欄無不足數量，P欄不修改")
                continue
            remain, last = need, None
            for ly in layers:
                if remain <= 0:
                    break
                if ly["qty"] <= 0 or (ridx is None and ly["tang_only"]):
                    continue
                take = min(ly["qty"], remain)
                ly["qty"] -= take
                remain -= take
                last = ly
            if ridx is None:
                continue
            if remain > 0:
                row_out[ridx] = (ST_SHORT, None,
                                 f"供給不足（缺 {remain:,.0f}），P欄不修改，請人工確認")
            elif last["kind"] == "stock":
                row_out[ridx] = (ST_STOCK, add_workdays(base_date, 2),
                                 "庫存補齊 → 基準日+2工作天")
            elif last["kind"] == "overdue":
                row_out[ridx] = (ST_OVERDUE, add_workdays(base_date, 4),
                                 "補齊靠的進貨已逾期 → 基準日+4工作天")
            else:
                row_out[ridx] = (ST_INCOMING, add_workdays(last["date"], 4),
                                 f"等進貨 {last['date']:%Y/%m/%d} 補齊 → +4工作天")

        for idx in rows.index:
            stt, nd, note = row_out[idx]
            full = (f"庫存 {stock:,.0f}"
                    + (f"、委外先佔 {comp_total:,.0f}" if comp_total else "")
                    + " ｜ " + note)
            res[idx] = (stt, nd, stock, comp_total, full)

    out = h2o.copy()
    for pos, col in enumerate(["狀態", "新P日期", "我司庫存", "委外競爭", "說明"]):
        out[col] = [res[i][pos] for i in out.index]
    return out


# ═══════════════════════════════════════════════════════════════════════════
# Excel COM 寫回（只動 H2O 工作表 P 欄，其餘原樣保留）
# ═══════════════════════════════════════════════════════════════════════════
_EXCEL_EPOCH = _dt.date(1899, 12, 30)


def write_p_column(xls_path: str, new_dates: dict[int, _dt.date],
                   sheet: str = "H2O", pn_col: int = 10, p_col: int = 16) -> dict:
    """依 {工作表列號: 新日期} 寫回 P 欄（Excel 序號值＋沿用既有日期格式）。

    回傳 {"rows_updated": n, "rows_total": m}。檔案被鎖定/唯讀時丟 RuntimeError。
    """
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    app = None
    try:
        app = win32com.client.DispatchEx("Excel.Application")
        app.Visible = False
        app.DisplayAlerts = False
        wb = app.Workbooks.Open(os.path.abspath(xls_path))
        try:
            if wb.ReadOnly:
                raise RuntimeError("檔案目前為唯讀（可能已在 Excel 開啟），請關閉後重試")
            ws = wb.Worksheets(sheet)
            last = ws.Cells(ws.Rows.Count, pn_col).End(-4162).Row  # xlUp
            if last < 2:
                return {"rows_updated": 0, "rows_total": 0}

            def _rows(rng):                      # 單列時 .Value 回傳純量
                v = rng.Value
                return [(v,)] if last == 2 else [tuple(r) for r in v]

            p_rng = ws.Range(ws.Cells(2, p_col), ws.Cells(last, p_col))
            raw_p = _rows(p_rng)

            # 原值一律轉 Excel 序號（pywintypes 日期帶時區，原樣回寫可能位移）；
            # 並沿用欄內第一個日期儲存格的格式，找不到就用 yyyy/m/d
            p_vals, fmt = [], None
            for i, (v,) in enumerate(raw_p):
                if isinstance(v, _dt.datetime):
                    serial = float((v.date() - _EXCEL_EPOCH).days)
                    serial += (v.hour * 3600 + v.minute * 60 + v.second) / 86400.0
                    p_vals.append([serial])
                    if fmt is None:
                        fmt = ws.Cells(2 + i, p_col).NumberFormat
                else:
                    p_vals.append([v])
            fmt = fmt or "yyyy/m/d"

            updated = 0
            for i in range(len(p_vals)):
                nd = new_dates.get(i + 2)        # 工作表列號 = 資料起始列2 + i
                if nd is not None:
                    p_vals[i][0] = float((nd - _EXCEL_EPOCH).days)
                    updated += 1
            p_rng.Value = p_vals
            p_rng.NumberFormat = fmt
            wb.Save()
            return {"rows_updated": updated, "rows_total": len(p_vals)}
        finally:
            wb.Close(SaveChanges=False)
    finally:
        if app is not None:
            app.Quit()
        pythoncom.CoUninitialize()
