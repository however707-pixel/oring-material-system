# -*- coding: utf-8 -*-
"""
戰情室資料層。

這裡是「備料／上架 KPI 口徑」與「NAS Log 掃描」的單一來源：
16_wh_dashboard / 21_test_station / 23_assembly 與戰情室都應該從這裡取數，
避免同一套業務規則散在多個頁面各自漂移。
"""
import os
import re
from datetime import date, timedelta

import numpy as np
import pandas as pd
import streamlit as st

from db import queries as wh_db
from utils.workdays import TW_OFF_DAYS, prev_workday

# ══════════════════════════════════════════════════════════════
# 國定假日（與 16_wh_dashboard 共用）
# ══════════════════════════════════════════════════════════════
# 單一來源：utils/workdays.py（依人事行政總處 115 年辦公日曆表）。
# TW_OFF_DAYS = 國定假日 ∪ 臨時停班日（含 2026/7/10 颱風停班），沿用
# TW_HOLIDAYS 這個名稱是為了不動 pages/16_wh_dashboard.py 的既有匯入。
TW_HOLIDAYS = TW_OFF_DAYS

# 每日標準（第1~3季 / 第4季）
STD_B_Q13, STD_B_Q4 = 250, 300   # 備料
STD_I_Q13, STD_I_Q4 = 150, 200   # 上架（入庫）

# 待完成備料只計入這些狀態，排除空白／已完成等髒資料
PENDING_STATUSES = ('待備料', '備料中')


def _inhouse(df):
    """廠內判定：需求單位或單別含 生產加工／廠內／場內（『場』為常見錯字）。"""
    unit = df['需求單位'].astype(str)
    dan = df['單別'].astype(str)
    return (unit.str.contains('生產加工|廠內|場內', na=False)
            | dan.str.contains('廠內|場內', na=False))


def compute_wh_kpi(diao, inbound, yesterday):
    """
    備料／上架兩張 KPI 卡的口徑。回傳 dict。

    備料 已完成：完成日=昨日 且 狀態=已完成 → Σ需求筆數
    備料 待完成：需求日<=昨日、完成日空白、狀態∈(待備料,備料中) → Σ需求筆數
    上架 已完成：需求單位含「入庫」且 完成日=昨日 → Σ完成筆數（不看狀態，避免「上架W」等變體漏算）
    上架 待完成：入庫單據 完成日空白 → Σ筆數（顯示值為全部）
    上架 完成率分母：待完成只計已逾期（預計完成日<=昨日；空白視為逾期）
    """
    # ── 備料（調撥單）──
    b_done_rows = diao[
        diao['完成日'].notna()
        & (diao['完成日'].dt.date == yesterday)
        & (diao['狀態'] == '已完成')
    ]
    b_done = int(b_done_rows['需求筆數'].sum())
    _m = _inhouse(b_done_rows)
    b_done_inhouse = int(b_done_rows[_m]['需求筆數'].sum())
    b_done_outsource = b_done - b_done_inhouse

    _pend_base = (
        diao['需求日'].notna()
        & (diao['需求日'].dt.date <= yesterday)
        & diao['完成日'].isna()
    )
    b_pend_rows = diao[_pend_base & diao['狀態'].isin(PENDING_STATUSES)]
    b_pend = int(b_pend_rows['需求筆數'].sum())
    _pm = _inhouse(b_pend_rows)
    b_pend_inhouse = int(b_pend_rows[_pm]['需求筆數'].sum())
    b_pend_outsource = b_pend - b_pend_inhouse

    b_total = b_done + b_pend
    b_rate = b_done / b_total if b_total else 0

    # ── 上架（入庫）──
    ib_done_rows = diao[
        diao['需求單位'].astype(str).str.contains('入庫', na=False)
        & diao['完成日'].notna()
        & (diao['完成日'].dt.date == yesterday)
    ]
    i_done = int(ib_done_rows['完成筆數'].sum())

    ib_pend_rows = inbound[inbound['完成日'].isna()]
    i_pend = int(ib_pend_rows['筆數'].sum())

    _ib_not_due = (ib_pend_rows['預計完成日'].notna()
                   & (ib_pend_rows['預計完成日'].dt.date > yesterday))
    i_pend_overdue = int(ib_pend_rows[~_ib_not_due]['筆數'].sum())

    i_total = i_done + i_pend_overdue
    i_rate = i_done / i_total if i_total else 0

    q_num = (yesterday.month - 1) // 3 + 1
    return dict(
        yesterday=yesterday, q_num=q_num,
        b_done=b_done, b_done_inhouse=b_done_inhouse, b_done_outsource=b_done_outsource,
        b_pend=b_pend, b_pend_inhouse=b_pend_inhouse, b_pend_outsource=b_pend_outsource,
        b_rate=b_rate,
        b_rate_base=b_total,              # 完成率分母
        b_display_total=b_done + b_pend,  # 卡片顯示的「目標總筆數」
        b_target_day=(STD_B_Q4 if q_num == 4 else STD_B_Q13),
        i_done=i_done, i_pend=i_pend, i_pend_overdue=i_pend_overdue,
        i_rate=i_rate,
        i_rate_base=i_total,              # 完成率分母：只計逾期
        i_display_total=i_done + i_pend,  # 卡片顯示的「目標總筆數」＝全部未上架
        i_target_day=(STD_I_Q4 if q_num == 4 else STD_I_Q13),
    )


@st.cache_data(ttl=60, show_spinner=False)
def ensure_latest_db():
    """NAS 有更新的「調件備料統計表」就立即匯入 db（60 秒內最多檢查一次）。

    與 16_wh_dashboard 的 _auto_sync 同一支；戰情室也要呼叫，
    否則只有看板開著時 db 才會更新，兩頁就會顯示不同版本的資料。
    回傳 (did_import, msg)。
    """
    try:
        from db import import_to_db as wh_sync
        return wh_sync.sync_if_newer()
    except Exception as e:                      # NAS 離線 / 雲端環境
        return False, f"同步失敗：{e}"


@st.cache_data(ttl=600, show_spinner=False)
def load_wh_kpi(mtime_key: str):
    """讀 DB → 算 KPI。

    mtime_key 用 db_mtime() 當快取鍵：**不可**加底線前綴，
    Streamlit 對底線開頭的參數刻意不納入 hash（cache_utils.py），
    加了底線資料換版時快取不會失效，只能等 TTL 到期 → 兩頁數字對不起來。
    """
    diao, inbound = wh_db.load_wh()
    return compute_wh_kpi(diao, inbound, prev_workday(date.today()))


# ══════════════════════════════════════════════════════════════
# 出貨工單概況（今日 ~ +4週）
# ══════════════════════════════════════════════════════════════
@st.cache_data(ttl=600, show_spinner=False)
def load_ship_weeks(mtime_key: str, n_weeks: int = 5):
    """
    由 shipment_schedule 彙總未來 n_weeks 個工作週。
    料況狀態沿用 queries.load_sched() 的判定（已齊料／缺料 x%／完全缺料）。

    拆分方式比照 15_kanban 的出貨工單概況卡：
    未齊料的工單若缺的料正在 IQC 驗收中，另外算成 n_iqc，
    真缺料 n_true_short = n_short - n_iqc（n_short 仍是「未齊料」總數）。
    """
    sched = wh_db.load_sched()
    if sched.empty:
        return []

    sched = sched.dropna(subset=['出貨日']).copy()
    if 'IQC中' not in sched.columns:          # 舊 db 尚未加欄位時
        sched['IQC中'] = False
    today = date.today()
    monday = today - timedelta(days=today.weekday())

    weeks = []
    for i in range(n_weeks):
        ws = monday + timedelta(days=7 * i)
        we = ws + timedelta(days=4)          # 週一~週五
        sub = sched[(sched['出貨日'] >= ws) & (sched['出貨日'] <= we)]
        n = len(sub)
        tq = int(pd.to_numeric(sub['預計產量'], errors='coerce').fillna(0).sum())
        ready_mask = sub['料況狀態'] == '已齊料'
        n_ready = int(ready_mask.sum())
        n_short = n - n_ready
        n_iqc = int((~ready_mask & sub['IQC中'].fillna(False).astype(bool)).sum())
        weeks.append(dict(
            label=f"W{ws.isocalendar()[1]}",
            start=ws, end=we, n=n, tq=tq,
            n_ready=n_ready, n_short=n_short,
            n_iqc=n_iqc, n_true_short=n_short - n_iqc,
            pct=int(n_ready / n * 100) if n else 0,
        ))
    return weeks


# ══════════════════════════════════════════════════════════════
# NAS Log 掃描（組裝 / 測試站）
# ══════════════════════════════════════════════════════════════
ASSEMBLY_ROOT = "//192.168.2.34/Oring_Share/Soft_Test/Log_file/OringAssembly"
TEST_ROOTS = {
    "第一測程": "//192.168.2.34/Oring_Share/Soft_Test/Log_file/OringLazybag",
    "第二測程": "//192.168.2.34/Oring_Share/Soft_Test/Log_file/OringPoE",
}

_FNAME_RE = re.compile(r"^([^_]+)_(\d{14})_")


def clean_pno(name: str) -> str:
    """料號資料夾名稱含 # 補位字元，顯示時去除"""
    return re.sub(r"#+", "", name)


# NAS Log 掃描很重（冷快取約 2 分鐘），戰情室每 5 分鐘自動刷新，
# 這幾支的快取拉長到 30 分鐘，避免每次刷新都卡在掃描上（DB 的 KPI 仍然 5 分鐘更新）
@st.cache_data(ttl=1800, show_spinner=False)
def scan_assembly(root: str = ASSEMBLY_ROOT):
    """
    掃描 NAS 組裝 Log 樹：料號 / 工單 / Start|End / 序號_YYYYMMDDHHMMSS_Start(End).txt
    以「同序號 Start→End 配對」計工時。回傳 (DataFrame, 錯誤訊息或 None)
    """
    rows = []
    try:
        lv1 = [d for d in os.scandir(root) if d.is_dir()]
    except OSError as e:
        return pd.DataFrame(), f"無法連線 NAS：{e}"

    for pno_dir in lv1:
        pno = clean_pno(pno_dir.name)
        try:
            wos = [d for d in os.scandir(pno_dir.path) if d.is_dir()]
        except OSError:
            continue
        for wo_dir in wos:
            stamps = {}   # 序號 -> {'Start': dt, 'End': dt}
            for phase in ("Start", "End"):
                pdir = os.path.join(wo_dir.path, phase)
                if not os.path.isdir(pdir):
                    continue
                try:
                    files = [f for f in os.scandir(pdir) if f.is_file()]
                except OSError:
                    continue
                for f in files:
                    m = _FNAME_RE.match(f.name)
                    if not m:
                        continue
                    sn, ts = m.group(1), m.group(2)
                    try:
                        dt = pd.to_datetime(ts, format="%Y%m%d%H%M%S")
                    except Exception:
                        continue
                    d = stamps.setdefault(sn, {})
                    # 同序號多筆時取最早 Start、最晚 End
                    if phase == "Start":
                        d['Start'] = min(d.get('Start', dt), dt)
                    else:
                        d['End'] = max(d.get('End', dt), dt)
            for sn, d in stamps.items():
                start, end = d.get('Start'), d.get('End')
                mins = round((end - start).total_seconds() / 60, 1) if (start and end) else None
                rows.append({
                    "成品料號": pno, "工單號碼": wo_dir.name, "序號": sn,
                    "開始時間": start, "結束時間": end, "工時(分)": mins,
                })

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("開始時間", ascending=False, na_position="last").reset_index(drop=True)
    return df, None


@st.cache_data(ttl=1800, show_spinner=False)
def scan_test_logs(root: str):
    """
    每 料號/工單/人員 一列的測試彙總：平均耗時(分) = (末件 − 首件) / (筆數 − 1)。
    只取 PASS；檔案數 < 2 的資料夾跳過（無法計算區間）。
    回傳 (DataFrame, 錯誤訊息或 None)

    直接聚合 scan_test_raw() 的逐檔資料——戰情室同時要用這支和總計工時表，
    共用同一份掃描結果才不會把同一棵測試樹走兩次（各約 40 秒）。
    數值與舊版逐檔自行掃描的結果相同（含 round() 的進位方式）。
    """
    df, err = scan_test_raw(root)
    if err:
        return pd.DataFrame(), err
    if df.empty:
        return pd.DataFrame(), None

    g = (df.groupby(TEST_GROUP_KEYS)["測試時間"]
           .agg(完成台數="size", 首件時間="min", 末件時間="max")
           .reset_index())
    span = (g["末件時間"] - g["首件時間"]).dt.total_seconds() / 60
    # 用內建 round 逐筆算，跟舊版的進位一致（numpy 的 .round() 在 x.x5 會差 0.1）
    g["平均耗時(分)"] = [round(v / (c - 1), 1) if c > 1 else None
                         for v, c in zip(span, g["完成台數"])]
    return g[["成品料號", "工單號碼", "人員工號", "完成台數",
              "平均耗時(分)", "首件時間", "末件時間"]], None


@st.cache_data(ttl=1800, show_spinner=False)
def load_fastest_per_model():
    """
    每機種最快完成時間：各測程分別取該料號最快的一組平均耗時；
    兩測程都有資料的機種，一台最快合計 = 第一測程 + 第二測程。
    """
    frames = []
    errs = []
    for stage, root in TEST_ROOTS.items():
        df, err = scan_test_logs(root)
        if err:
            errs.append(f"{stage}：{err}")
            continue
        if not df.empty:
            df = df.copy()
            df["測程"] = stage
            frames.append(df)
    if not frames:
        return pd.DataFrame(), (errs[0] if errs else "沒有可用的測試 Log")

    summary = pd.concat(frames, ignore_index=True)
    best = summary.dropna(subset=["平均耗時(分)"])
    if best.empty:
        return pd.DataFrame(), "沒有可計算的平均耗時"

    idx_min = best.groupby(["測程", "成品料號"])["平均耗時(分)"].idxmin()
    per_stage = best.loc[idx_min].set_index("成品料號")
    per_stage["工單/人員"] = per_stage["工單號碼"] + " / " + per_stage["人員工號"]

    s1 = per_stage[per_stage["測程"] == "第一測程"]
    s2 = per_stage[per_stage["測程"] == "第二測程"]

    fastest = pd.DataFrame(index=sorted(set(s1.index) | set(s2.index)))
    fastest.index.name = "成品料號"
    fastest["第一測程最快(分)"] = s1["平均耗時(分)"]
    fastest["第二測程最快(分)"] = s2["平均耗時(分)"]
    fastest["一台最快合計(分)"] = (
        fastest["第一測程最快(分)"].fillna(0) + fastest["第二測程最快(分)"].fillna(0)
    ).round(1)
    fastest["第一測程 工單/人員"] = s1["工單/人員"]
    fastest["第二測程 工單/人員"] = s2["工單/人員"]
    fastest = fastest.reset_index().sort_values("一台最快合計(分)").reset_index(drop=True)
    return fastest, (errs[0] if errs else None)


@st.cache_data(ttl=600, show_spinner=False)
def load_ship_detail(mtime_key: str, limit: int = 500):
    """
    出貨工單明細（有出貨日者）。
    註：預計齊料日／緩衝天數／達標差距／延遲物料 需 kanban 的 NAS 供需表才能算，
        DB 的 shipment_schedule 沒有這些欄位，故此處僅提供 DB 有的五欄。
    """
    import sqlite3
    conn = sqlite3.connect(wh_db.DB_PATH)
    try:
        try:
            df = pd.read_sql_query("""
                SELECT work_order AS 工單, product_no AS 成品料號,
                       planned_qty AS 預計產量, ship_date AS 出貨日,
                       material_rate AS _rate, status_note AS _note,
                       COALESCE(iqc_flag, 0) AS _iqc
                FROM shipment_schedule
                WHERE ship_date IS NOT NULL AND ship_date >= date('now')
                ORDER BY ship_date, work_order
            """, conn)
        except Exception:                      # 舊 db 尚未有 iqc_flag 欄位
            df = pd.read_sql_query("""
                SELECT work_order AS 工單, product_no AS 成品料號,
                       planned_qty AS 預計產量, ship_date AS 出貨日,
                       material_rate AS _rate, status_note AS _note
                FROM shipment_schedule
                WHERE ship_date IS NOT NULL AND ship_date >= date('now')
                ORDER BY ship_date, work_order
            """, conn)
            df["_iqc"] = 0
    finally:
        conn.close()
    if df.empty:
        return df, 0

    def _status(r):
        rate = float(r["_rate"]) if pd.notna(r["_rate"]) else 0.0
        if rate >= 1.0 or any(k in str(r["_note"]) for k in ("已發料", "已齊料", "已發放", "齊料")):
            return "已齊料"
        base = "未備料" if rate == 0.0 else f"齊料 {rate:.0%}"
        # 缺的料在 IQC 驗收中：與看板卡片同一個維度，明細也標出來
        return f"{base}・IQC中" if r["_iqc"] else base

    df["料況狀態"] = df.apply(_status, axis=1)
    df["出貨日"] = pd.to_datetime(df["出貨日"], errors="coerce").dt.strftime("%Y-%m-%d")
    total = len(df)
    return df.drop(columns=["_rate", "_note", "_iqc"]).head(limit), total


# ── 組裝節拍（頭頭）與標準工時 ──────────────────────────────────
# 舊口徑用「同序號 End − Start」（頭尾）算單台工時，問題有二：
#   ① 有近六成的單台沒刷 End，整個工單算不出平均
#   ② 頭尾時間是單台在線上的停留時間，不等於投入的人力工時
# 改用「頭頭」節拍：同工單內下一台 Start − 本台 Start，再乘線上人數，
# 即為一台份的標準工時。節拍分布右偏（換線／等料／休息會製造假節拍），
# 故兩端各修剪 10% 後取平均——實測與中位數幾乎一致但保留 80% 樣本。
TAKT_PEOPLE = 4      # 只有 Start 時：標準工時 = 節拍 × 人數
TAKT_TRIM = 0.25     # 兩端各修剪 25%，只取中間 50% 平均
ASSEMBLY_KEY = ["成品料號", "工單號碼"]


def trim_mean(v, trim: float = TAKT_TRIM):
    """兩端各去 trim 比例後取平均；樣本少到修剪不動時退回全體平均"""
    a = np.asarray(v, dtype=float)
    a = np.sort(a[~np.isnan(a)])
    if a.size == 0:
        return np.nan
    k = int(a.size * trim)
    core = a[k:a.size - k] if a.size - 2 * k >= 1 else a
    return float(core.mean())


def add_takt(p: pd.DataFrame, gap_min: int = 120) -> pd.DataFrame:
    """
    在單台配對表上加入頭頭節拍欄位。
      節拍(分) = 同一 料號/工單 內依開始時間排序後「下一台 Start − 本台 Start」
      節拍有效 = 有下一台 且 同日 且 0 < 節拍 <= gap_min
    每個工單的最後一台沒有下一台，節拍為 NaN（先天限制，不計入平均）。
    """
    p = p.sort_values(ASSEMBLY_KEY + ["開始時間"]).reset_index(drop=True)
    nxt = p.groupby(ASSEMBLY_KEY)["開始時間"].shift(-1)
    p["節拍(分)"] = (nxt - p["開始時間"]).dt.total_seconds() / 60
    p["節拍有效"] = (p["節拍(分)"].notna()
                     & (p["開始時間"].dt.date == nxt.dt.date)
                     & (p["節拍(分)"] > 0)
                     & (p["節拍(分)"] <= gap_min))
    return p


def add_standard_hours(p: pd.DataFrame, gap_min: int = 120,
                       people: int = TAKT_PEOPLE,
                       use_takt: bool = True) -> pd.DataFrame:
    """
    逐台計算標準工時，依「該台有沒有刷 End」擇一取值：
      ① 有刷 End（頭尾有效）→ 頭尾工時（End − Start），直接採用
      ② 只有 Start          → 節拍（頭頭）× people
    兩者皆不成立者為 NaN，不計入平均。
    工單層級再對這些值取「去頭 25%、去尾 25%，只算中間 50%」的平均。

    須先跑過 add_takt()（要用到 節拍(分) / 節拍有效）。
    實測全廠約 38% 走 ①、62% 走 ②；同一台兩者都算得出來時中位數
    分別約 3.2 / 3.1 分，落在同一個水準，故可混在一起取平均。

    use_takt=False：關掉 ②，只認頭尾工時（給每台都會刷 End 的製程用，
    例如包裝——只有 Start 代表還在生產中，不是缺資料，不該補值）。
    此時可以不必先跑 add_takt()。
    """
    p["工時(分)"] = pd.to_numeric(p["工時(分)"], errors="coerce")
    done = p["開始時間"].notna() & p["結束時間"].notna() & (p["工時(分)"] >= 0)
    cross_day = done & (p["開始時間"].dt.date != p["結束時間"].dt.date)
    p["頭尾有效"] = done & ~cross_day & (p["工時(分)"] <= gap_min)

    if use_takt:
        takt_ok = p["節拍有效"].to_numpy(dtype=bool)
        takt_val = pd.to_numeric(p["節拍(分)"], errors="coerce").to_numpy(float) * people
    else:
        takt_ok = np.zeros(len(p), dtype=bool)
        takt_val = np.full(len(p), np.nan)

    p["標準工時(分)"] = np.where(
        p["頭尾有效"], p["工時(分)"], np.where(takt_ok, takt_val, np.nan))
    p["工時來源"] = np.where(
        p["頭尾有效"], "頭尾", np.where(takt_ok, f"頭頭×{people}", "—"))
    p["工時有效"] = pd.notna(p["標準工時(分)"])
    return p


@st.cache_data(ttl=1800, show_spinner=False)
def assembly_summary(gap_min: int = 120, people: int = TAKT_PEOPLE,
                     trim: float = TAKT_TRIM):
    """
    產量與組裝標準工時（口徑同 pages/23_assembly.py）：
      單台取值     = 有刷 End → 頭尾工時；只有 Start → 節拍 × 人數
      標準工時(分) = 上述單台值，去頭 trim、去尾 trim 後的平均
      有效樣本     = 兩種取值至少成立一種的台數
    回傳 (DataFrame, 錯誤訊息或 None)

    註：trim／people 走參數而非直接讀模組常數，改設定時快取鍵才會跟著變，
        否則調了 TAKT_TRIM 但畫面仍停在舊值（ttl 內不會重算）。
    """
    df, err = scan_assembly()
    if err:
        return pd.DataFrame(), err
    if df.empty:
        return pd.DataFrame(), None

    p = add_standard_hours(add_takt(df.copy(), gap_min), gap_min, people)
    p["完成"] = p["開始時間"].notna() & p["結束時間"].notna() & (p["工時(分)"] >= 0)
    p["組裝中"] = p["開始時間"].notna() & (p["結束時間"].isna() | (p["工時(分)"] < 0))

    ok = p[p["工時有效"]]
    out = (p.groupby(ASSEMBLY_KEY)
             .agg(**{"完成台數": ("完成", "sum"),
                     "組裝中":   ("組裝中", "sum"),
                     "有效樣本": ("工時有效", "sum")})
             .join(ok.groupby(ASSEMBLY_KEY)["標準工時(分)"]
                     .agg(**{"標準工時(分)": lambda s: trim_mean(s, trim)}))
             .reset_index())
    out["標準工時(分)"] = out["標準工時(分)"].astype(float).round(1)
    out = out.sort_values("完成台數", ascending=False).reset_index(drop=True)
    return out, None


# ══════════════════════════════════════════════════════════════
# 成品總計工時（組裝 + 第一測程 + 第二測程 + 包裝）
# ══════════════════════════════════════════════════════════════
# 四個站的 Log 都以「成品料號」為頂層資料夾，去掉 # 補位字元後字串可以直接對上，
# 所以機種層級就用 clean_pno() 後的成品料號當 key（實測：組裝∩第一測程 20 種）。
# 各站沿用各自頁面的口徑，這裡只負責相加，不另立新算法：
#   組裝 → 23_assembly.py：有刷 End 取頭尾、只有 Start 取節拍×人數，再去頭去尾 25%
#   包裝 → 28_packaging.py：只取頭尾（每台都會刷 End，只有 Start＝還在生產中）
#   測試 → 21_test_station.py：相鄰兩筆 PASS Log 的分鐘差，排除跨日與 > 中斷門檻
PACKAGE_ROOT = "//192.168.2.34/Oring_Share/Soft_Test/Log_file/OringPackage"
TEST_GROUP_KEYS = ["成品料號", "工單號碼", "人員工號"]


@st.cache_data(ttl=1800, show_spinner=False)
def scan_test_raw(root: str):
    """
    掃描測試 Log 樹並逐檔回傳（口徑同 21_test_station.py 的 scan_logs）：
    料號 / 工單 / 人員工號 / PASS / 序號_YYYYMMDDHHMMSS_結果.txt，
    只取 PASS，資料夾內檔案數 < 2 者跳過（算不出區間）。
    回傳 (DataFrame, 錯誤訊息或 None)

    註：warroom 那支 scan_test_logs() 只回「首末件平均」的彙總列，
        算不了跨日／中斷門檻的排除，所以總計工時表另外用這支逐檔的。
    """
    rows = []
    try:
        lv1 = [d for d in os.scandir(root) if d.is_dir()]
    except OSError as e:
        return pd.DataFrame(), f"無法連線 NAS：{e}"

    for pno_dir in lv1:
        pno = clean_pno(pno_dir.name)
        try:
            wos = [d for d in os.scandir(pno_dir.path) if d.is_dir()]
        except OSError:
            continue
        for wo_dir in wos:
            try:
                staffs = [d for d in os.scandir(wo_dir.path) if d.is_dir()]
            except OSError:
                continue
            for st_dir in staffs:
                pass_dir = os.path.join(st_dir.path, "PASS")
                if not os.path.isdir(pass_dir):
                    continue
                try:
                    files = [f for f in os.scandir(pass_dir) if f.is_file()]
                except OSError:
                    continue
                parsed = []
                for f in files:
                    m = _FNAME_RE.match(f.name)
                    if not m:
                        continue
                    try:
                        parsed.append((m.group(1),
                                       pd.to_datetime(m.group(2), format="%Y%m%d%H%M%S")))
                    except Exception:
                        continue
                if len(parsed) < 2:
                    continue
                for sn, ts in parsed:
                    rows.append({"成品料號": pno, "工單號碼": wo_dir.name,
                                 "人員工號": st_dir.name, "序號": sn, "測試時間": ts})
    return pd.DataFrame(rows), None


def _std_hours_by_model(df: pd.DataFrame, gap_min: int, people: int,
                        trim: float, use_takt: bool):
    """
    把 scan_assembly() 那種「單台配對表」壓成每料號一列的標準工時。
    回傳 (平均 Series, 有效樣本數 Series)，index 都是成品料號。
    """
    empty = (pd.Series(dtype=float), pd.Series(dtype=int))
    if df is None or df.empty:
        return empty
    p = df.copy()
    for c in ("開始時間", "結束時間"):
        p[c] = pd.to_datetime(p[c], errors="coerce")
    if use_takt:
        p = add_takt(p, gap_min)
    p = add_standard_hours(p, gap_min, people, use_takt=use_takt)
    ok = p[p["工時有效"]]
    if ok.empty:
        return empty
    avg = ok.groupby("成品料號")["標準工時(分)"].agg(lambda s: trim_mean(s, trim))
    cnt = ok.groupby("成品料號")["標準工時(分)"].size()
    return avg, cnt


def _test_avg_by_model(root: str, gap_min: int):
    """
    每料號的測試平均耗時：同一 料號/工單/人員 內相鄰兩筆 PASS 的分鐘差
    （秒數捨去），排除跨日與 > gap_min 的中斷，再把該料號的有效區間全部取平均。
    回傳 (平均 Series, 台數 Series, 錯誤訊息或 None)
    """
    empty = (pd.Series(dtype=float), pd.Series(dtype=int))
    df, err = scan_test_raw(root)
    if err:
        return empty[0], empty[1], err
    if df.empty:
        return empty[0], empty[1], None

    d = df.copy()
    d["測試時間_分"] = d["測試時間"].dt.floor("min")
    d = d.sort_values(TEST_GROUP_KEYS + ["測試時間_分"]).reset_index(drop=True)
    prev = d.groupby(TEST_GROUP_KEYS)["測試時間_分"].shift()
    d["耗時(分)"] = (d["測試時間_分"] - prev).dt.total_seconds() / 60
    cross_day = prev.notna() & (d["測試時間_分"].dt.date != prev.dt.date)
    d["有效"] = d["耗時(分)"].notna() & ~cross_day & (d["耗時(分)"] <= gap_min)

    ok = d[d["有效"]]
    avg = ok.groupby("成品料號")["耗時(分)"].mean() if not ok.empty else empty[0]
    cnt = d.groupby("成品料號")["序號"].nunique()
    return avg, cnt, None


@st.cache_data(ttl=1800, show_spinner=False)
def total_worktime_table(gap_assy: int = 120, gap_test: int = 30,
                         people: int = TAKT_PEOPLE, trim: float = TAKT_TRIM):
    """
    每機種成品工時表：組裝 + 第一測程 + 第二測程 + 包裝 相加。
      合計工時(分) = 組裝 + 測試小計 + 包裝，缺資料的站以 0 計，並在「資料狀態」標出來
      完成品        = 組裝／測試（任一測程即可）／包裝三站都有值
    回傳 (DataFrame, 警告訊息 list)

    註：gap／people／trim 走參數而非模組常數，改設定時快取鍵才會跟著變。
    """
    warns = []

    a_df, a_err = scan_assembly(ASSEMBLY_ROOT)
    if a_err:
        warns.append(f"組裝：{a_err}")
    a_avg, a_cnt = _std_hours_by_model(a_df, gap_assy, people, trim, use_takt=True)

    # 包裝的目錄結構與組裝相同，直接共用同一支掃描（快取鍵不同，不會互相蓋掉）
    p_df, p_err = scan_assembly(PACKAGE_ROOT)
    if p_err:
        warns.append(f"包裝：{p_err}")
    p_avg, p_cnt = _std_hours_by_model(p_df, gap_assy, people, trim, use_takt=False)

    t_avg, t_cnt = {}, {}
    for stage, root in TEST_ROOTS.items():
        avg, cnt, err = _test_avg_by_model(root, gap_test)
        if err:
            warns.append(f"{stage}：{err}")
        t_avg[stage], t_cnt[stage] = avg, cnt

    models = set(a_avg.index) | set(p_avg.index)
    for s in t_avg.values():
        models |= set(s.index)
    if not models:
        return pd.DataFrame(), warns

    out = pd.DataFrame(index=pd.Index(sorted(models), name="成品料號"))
    out["組裝(分)"] = a_avg.round(1)
    out["第一測程(分)"] = t_avg.get("第一測程", pd.Series(dtype=float)).round(1)
    out["第二測程(分)"] = t_avg.get("第二測程", pd.Series(dtype=float)).round(1)
    out["測試小計(分)"] = (out["第一測程(分)"].fillna(0)
                           + out["第二測程(分)"].fillna(0)).round(1)
    out["包裝(分)"] = p_avg.round(1)
    out["合計工時(分)"] = (out["組裝(分)"].fillna(0) + out["測試小計(分)"]
                           + out["包裝(分)"].fillna(0)).round(1)

    out["組裝樣本(台)"] = a_cnt
    out["第一測程台數"] = t_cnt.get("第一測程", pd.Series(dtype=int))
    out["第二測程台數"] = t_cnt.get("第二測程", pd.Series(dtype=int))
    out["包裝樣本(台)"] = p_cnt

    # 測試不一定兩站都跑：有的機種只需要一個測程，所以只要任一測程有值就算過了測試。
    # 組裝、測試、包裝三站都有值 → 這個機種的工時是「完成品」的完整工時。
    no_assy = out["組裝(分)"].isna()
    no_test = out["第一測程(分)"].isna() & out["第二測程(分)"].isna()
    no_pack = out["包裝(分)"].isna()
    out["完成品"] = ~(no_assy | no_test | no_pack)
    out["資料狀態"] = [
        "✅ 完成品" if not miss else "缺 " + "、".join(miss)
        for miss in ([n for n, f in (("組裝", a), ("測試", t), ("包裝", p)) if f]
                     for a, t, p in zip(no_assy, no_test, no_pack))
    ]

    out = (out.reset_index()
              .sort_values(["完成品", "合計工時(分)"], ascending=[False, False])
              .reset_index(drop=True))
    return out, warns


@st.cache_data(ttl=1800, show_spinner=False)
def packaging_summary(gap_min: int = 120, trim: float = TAKT_TRIM):
    """
    產量與包裝標準工時（口徑同 pages/28_packaging.py）：
      單台取值     = 只認頭尾工時 End − Start（包裝每台都會刷 End，
                     只有 Start 代表那台還在包裝中，不補值也不計入）
      標準工時(分) = 上述單台值，去頭 trim、去尾 trim 後的平均
    回傳 (DataFrame, 錯誤訊息或 None)
    """
    df, err = scan_assembly(PACKAGE_ROOT)      # 目錄結構與組裝相同，共用同一支掃描
    if err:
        return pd.DataFrame(), err
    if df.empty:
        return pd.DataFrame(), None

    p = add_standard_hours(df.copy(), gap_min, use_takt=False)
    p["完成"] = p["開始時間"].notna() & p["結束時間"].notna() & (p["工時(分)"] >= 0)
    p["包裝中"] = p["開始時間"].notna() & (p["結束時間"].isna() | (p["工時(分)"] < 0))

    ok = p[p["工時有效"]]
    out = (p.groupby(ASSEMBLY_KEY)
             .agg(**{"完成台數": ("完成", "sum"),
                     "包裝中":   ("包裝中", "sum"),
                     "有效樣本": ("工時有效", "sum")})
             .join(ok.groupby(ASSEMBLY_KEY)["標準工時(分)"]
                     .agg(**{"標準工時(分)": lambda s: trim_mean(s, trim)}))
             .reset_index())
    out["標準工時(分)"] = out["標準工時(分)"].astype(float).round(1)
    out = out.sort_values("完成台數", ascending=False).reset_index(drop=True)
    return out, None


# ══════════════════════════════════════════════════════════════
# 廠內改機排程（寶橋廠）的生產進度
# ══════════════════════════════════════════════════════════════
# 生管每週更新一份「寶橋廠排程MMDD.xlsx」，舊的搬到 寶橋廠排程/2026 子資料夾，
# 所以固定抓 2026 資料夾裡最新的那一份，檔名換日期不用改程式。
# 兩個工作表都是「線別｜製令(工單)｜機種｜數量｜E｜F…」的欄序：
#   已完工：E 欄＝進度說明，值是 已完工／指定完工／取消  ← 完工判定就看這欄
#   排程　：E 欄＝進度（生產中／品檢中／未完工／未齊料…，常留白），
#           F 欄＝進度說明明細（「未完工，組裝33，待換料小板2…」）
MO_SCHEDULE_DIR = ("//192.168.2.34/MO_Storage/ORing MO/ORing-MO 工作/生管部/"
                   "09. 廠內改機排程/2026")
MO_SCHEDULE_PREFIX = "寶橋廠排程"


def norm_mo_key(s) -> str:
    """製令／機種的比對鍵：去空白、去 # 補位字元、轉大寫"""
    return re.sub(r"[\s#]+", "", str(s)).upper()


def _latest_schedule_file():
    """2026 資料夾裡最新的一份寶橋廠排程（排除 Excel 開檔產生的 ~$ 暫存檔）"""
    try:
        files = [f for f in os.scandir(MO_SCHEDULE_DIR)
                 if f.is_file() and not f.name.startswith("~$")
                 and f.name.startswith(MO_SCHEDULE_PREFIX)
                 and f.name.lower().endswith((".xlsx", ".xlsm"))]
    except OSError as e:
        return None, f"無法連線 NAS：{e}"
    if not files:
        return None, f"找不到 {MO_SCHEDULE_PREFIX}*.xlsx"
    return max(files, key=lambda f: f.stat().st_mtime), None


@st.cache_data(ttl=600, show_spinner=False)
def load_mo_progress():
    """
    以 (製令, 機種) 查生產進度。已完工優先，其次才看排程表的進度。
    回傳 (dict, 來源檔名, 錯誤訊息或 None)
      dict[(製令, 機種)] = {"進度": str, "說明": str, "來源": "已完工"|"排程"}
      另外會塞一份 (製令, "") 當只比對製令的退路
    """
    ent, err = _latest_schedule_file()
    if err:
        return {}, "", err
    try:
        xl = pd.ExcelFile(ent.path, engine="calamine")
    except Exception as e:
        return {}, ent.name, f"讀取 {ent.name} 失敗：{e}"

    out = {}

    def _put(wo, pn, prog, note, src):
        wo = norm_mo_key(wo)
        if not wo or wo == "NAN":
            return
        rec = {"進度": prog, "說明": note, "來源": src}
        out.setdefault((wo, norm_mo_key(pn)), rec)
        out.setdefault((wo, ""), rec)

    # 已完工先寫入，setdefault 讓排程表不會覆蓋掉完工狀態
    for sheet in ("已完工", "排程"):
        if sheet not in xl.sheet_names:
            continue
        try:
            df = xl.parse(sheet, header=0)
        except Exception:
            continue
        if df.shape[1] < 6 or df.empty:
            continue
        c_wo, c_pn, c_e, c_f = df.columns[1], df.columns[2], df.columns[4], df.columns[5]
        for wo, pn, e, f in zip(df[c_wo], df[c_pn], df[c_e], df[c_f]):
            if pd.isna(wo):
                continue
            prog = "" if pd.isna(e) else str(e).strip()
            note = "" if (sheet == "已完工" or pd.isna(f)) else str(f).strip()
            if not prog and sheet == "排程":
                # 進度欄留白＝在排程上但還沒標進度；說明欄常常只是「7/20更新」這種備註，
                # 拿它當進度會變成一堆看不懂的字串，所以只放進 tooltip
                prog = "排程中"
            if not prog:
                continue
            _put(wo, pn, prog, note, sheet)

    return out, ent.name, None


def mo_progress_of(prog_map: dict, wo, pno):
    """先用 (製令, 機種) 查，查不到退回只比對製令；都沒有回 None"""
    if not prog_map:
        return None
    wo = norm_mo_key(wo)
    return prog_map.get((wo, norm_mo_key(pno))) or prog_map.get((wo, ""))
