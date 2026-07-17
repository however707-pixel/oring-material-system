import io
import os
import re
import sys
from datetime import datetime

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from utils.shared import inject_css, render_header, render_sidebar

st.set_page_config(page_title="測試站 製程時間分析", page_icon="🧪", layout="wide")
inject_css()
render_header(title="測試站 製程時間分析", subtitle="Test Station Cycle Time Analysis · Process Station", badge="製程站 PS")
render_sidebar()

# ─── NAS 掃描 ─────────────────────────────────────────────────────────────────
# 目錄層級：料號 / 工單 / 人員工號 / PASS / 序號_YYYYMMDDHHMMSS_結果.txt
# 兩個測程共用同一套計時邏輯；同一料號的最快完成時間 = 各測程最快平均相加

LOG_ROOTS = {
    "第一測程": "//192.168.2.34/Oring_Share/Soft_Test/Log_file/OringLazybag",
    "第二測程": "//192.168.2.34/Oring_Share/Soft_Test/Log_file/OringPoE",
}

_FNAME_RE = re.compile(r"^([^_]+)_(\d{14})_")

GROUP_KEYS = ["測程", "成品料號", "工單號碼", "人員工號"]


def _clean_pno(name: str) -> str:
    """料號資料夾名稱含 # 補位字元，顯示時去除"""
    return re.sub(r"#+", "", name)


@st.cache_data(ttl=600, show_spinner=False)
def scan_logs(root: str):
    """
    掃描 NAS Log 樹，只取 PASS 資料夾；檔案數 < 2 的資料夾跳過（無法計算區間）。
    回傳 (DataFrame, 錯誤訊息或 None)
    """
    rows = []
    try:
        lv1 = [d for d in os.scandir(root) if d.is_dir()]
    except OSError as e:
        return pd.DataFrame(), f"無法連線 NAS：{e}"

    for d1 in lv1:                                     # 成品料號
        try:
            lv2 = [d for d in os.scandir(d1.path) if d.is_dir()]
        except OSError:
            continue
        for d2 in lv2:                                 # 工單號碼
            try:
                lv3 = [d for d in os.scandir(d2.path) if d.is_dir()]
            except OSError:
                continue
            for d3 in lv3:                             # 人員工號
                try:
                    lv4 = [d for d in os.scandir(d3.path) if d.is_dir()]
                except OSError:
                    continue
                for d4 in lv4:                         # PASS / FAIL
                    if d4.name.upper() != "PASS":      # 只看無異常的 PASS
                        continue
                    try:
                        files = [f.name for f in os.scandir(d4.path) if f.is_file()]
                    except OSError:
                        continue
                    parsed = []
                    for fn in files:
                        m = _FNAME_RE.match(fn)
                        if not m:
                            continue
                        try:
                            ts = datetime.strptime(m.group(2), "%Y%m%d%H%M%S")
                        except ValueError:
                            continue
                        parsed.append((m.group(1), ts, fn))
                    if len(parsed) < 2:                # 只有一筆 → 跳過
                        continue
                    for sn, ts, fn in parsed:
                        rows.append({
                            "成品料號": _clean_pno(d1.name),
                            "工單號碼": d2.name,
                            "人員工號": d3.name,
                            "序號":     sn,
                            "測試時間": ts,
                            "檔名":     fn,
                        })
    return pd.DataFrame(rows), None


# ─── 計算邏輯說明 ─────────────────────────────────────────────────────────────

with st.expander("📖 計算邏輯說明"):
    st.markdown(f"""
| 步驟 | 規則 |
|---|---|
| **資料來源** | 第一測程：`{LOG_ROOTS["第一測程"]}`<br>第二測程：`{LOG_ROOTS["第二測程"]}`<br>層級：**成品料號 → 工單號碼 → 人員工號 → PASS / FAIL** |
| **讀取範圍** | 只讀 **PASS** 資料夾（無異常）；資料夾內只有 **1 筆** Log 直接跳過 |
| **時間解析** | 檔名 `序號_YYYYMMDDHHMMSS_PASS` 取 `_` 後 14 碼時間戳，**秒數捨去**（例：16:03:43 → 16:03） |
| **單台耗時** | 依時間排序後，與**前一筆** Log 的分鐘差<br>（例：16:03 → 16:06 = 3 分鐘，依此一路推演）；兩個測程分開各自計算 |
| **排除條件** | ① **跨日**區間直接剔除　② 同日內間隔 > **中斷排除門檻**（預設 30 分）視為休息/換線，不計入平均 |
| **平均耗時** | 同一 測程/料號/工單/人員 的有效區間平均 |
| **生產台數** | 不重複序號數（同序號重測只算 1 台，「測試筆數」則含重測） |
| **最快完成時間** | 各測程分別取該料號最快的一組平均耗時；若同料號兩測程都有資料，**一台最快合計 = 第一測程 + 第二測程** |
""", unsafe_allow_html=True)

# ─── 控制列 ───────────────────────────────────────────────────────────────────

c_btn, c_gap, _ = st.columns([1.2, 1.2, 3.6])
with c_btn:
    st.markdown("<div style='height:1.75rem'></div>", unsafe_allow_html=True)
    if st.button("🔄 重新掃描 NAS", use_container_width=True):
        scan_logs.clear()
        st.rerun()
with c_gap:
    gap_min = st.number_input("中斷排除門檻 (分)", min_value=5, max_value=480, value=30,
                              help="兩筆 Log 間隔超過此分鐘數視為休息/換線中斷，不計入平均")

with st.spinner("掃描 NAS 測試 Log 中…"):
    _frames = []
    for _stage, _root in LOG_ROOTS.items():
        _d, _e = scan_logs(_root)
        if _e:
            st.warning(f"{_stage}：{_e}")
        elif not _d.empty:
            _d = _d.copy()
            _d.insert(0, "測程", _stage)
            _frames.append(_d)

df_raw = pd.concat(_frames, ignore_index=True) if _frames else pd.DataFrame()
if df_raw.empty:
    st.warning("PASS 資料夾中沒有可分析的 Log（每個資料夾至少需要 2 筆檔案）。")
    st.stop()

# ─── 篩選 ─────────────────────────────────────────────────────────────────────

ALL = "全部"
f0, f1, f2, f3 = st.columns(4)
with f0:
    sel_stage = st.selectbox("測程", [ALL] + list(LOG_ROOTS.keys()))
    opts_pno = df_raw if sel_stage == ALL else df_raw[df_raw["測程"] == sel_stage]
with f1:
    sel_pno = st.selectbox("成品料號", [ALL] + sorted(opts_pno["成品料號"].unique()))
with f2:
    opts_wo = opts_pno if sel_pno == ALL else opts_pno[opts_pno["成品料號"] == sel_pno]
    sel_wo = st.selectbox("工單號碼", [ALL] + sorted(opts_wo["工單號碼"].unique()))
with f3:
    opts_op = opts_wo if sel_wo == ALL else opts_wo[opts_wo["工單號碼"] == sel_wo]
    sel_op = st.selectbox("人員工號", [ALL] + sorted(opts_op["人員工號"].unique()))

df = df_raw.copy()
if sel_stage != ALL:
    df = df[df["測程"] == sel_stage]
if sel_pno != ALL:
    df = df[df["成品料號"] == sel_pno]
if sel_wo != ALL:
    df = df[df["工單號碼"] == sel_wo]
if sel_op != ALL:
    df = df[df["人員工號"] == sel_op]

# ─── 區間計算：秒數捨去，取與前一筆的分鐘差 ───────────────────────────────────

df["測試時間_分"] = df["測試時間"].dt.floor("min")          # 秒不理他
df = df.sort_values(GROUP_KEYS + ["測試時間_分"]).reset_index(drop=True)

grp = df.groupby(GROUP_KEYS)
df["前筆時間"] = grp["測試時間_分"].shift()
df["耗時(分)"] = (df["測試時間_分"] - df["前筆時間"]).dt.total_seconds() / 60
df["跨日"] = df["前筆時間"].notna() & (df["測試時間_分"].dt.date != df["前筆時間"].dt.date)
df["有效"] = df["耗時(分)"].notna() & ~df["跨日"] & (df["耗時(分)"] <= gap_min)

avg = (
    df[df["有效"]]
    .groupby(GROUP_KEYS)["耗時(分)"]
    .mean()
    .rename("平均耗時(分)")
)
df = df.join(avg, on=GROUP_KEYS)

# ─── 一、彙總：成品 / 工單 / 人員 / 生產幾台 / 平均時間 ───────────────────────

summary = (
    df.groupby(GROUP_KEYS)
    .agg(**{
        "生產台數":   ("序號", "nunique"),
        "測試筆數":   ("序號", "size"),
        "有效區間數": ("有效", "sum"),
    })
    .join(avg)
    .reset_index()
)
summary["平均耗時(分)"] = summary["平均耗時(分)"].round(1)

m1, m2, m3 = st.columns(3)
m1.metric("成品料號數", f'{summary["成品料號"].nunique()} 項')
m2.metric("工單數", f'{summary["工單號碼"].nunique()} 張')
m3.metric("生產台數合計", f'{df["序號"].nunique()} 台',
          help="不重複序號數；同一台在兩個測程都測過只算 1 台")

st.subheader("📋 產量與平均製程時間")
st.caption("平均耗時 = 同一 測程/料號/工單/人員 內，相鄰兩筆 PASS Log 的分鐘差平均（排除跨日與超過中斷門檻的區間）")
st.dataframe(summary, use_container_width=True, hide_index=True)

buf_s = io.BytesIO()
summary.to_excel(buf_s, index=False, engine="openpyxl")
buf_s.seek(0)
st.download_button("⬇ 匯出彙總表 (Excel)", data=buf_s,
                   file_name="test_station_summary.xlsx",
                   mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# ─── 每機種最快完成時間（兩測程相加）─────────────────────────────────────────

st.divider()
st.subheader("🏁 每機種最快完成時間")
st.caption("各測程分別取該料號最快的一組平均耗時；兩測程都有資料的機種，一台最快合計 = 第一測程 + 第二測程")

best_src = summary.dropna(subset=["平均耗時(分)"])
if best_src.empty:
    st.info("沒有可計算的平均耗時。")
else:
    idx_min = best_src.groupby(["測程", "成品料號"])["平均耗時(分)"].idxmin()
    per_stage = best_src.loc[idx_min].set_index("成品料號")
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

    st.dataframe(fastest, use_container_width=True, hide_index=True)

    buf_f = io.BytesIO()
    fastest.to_excel(buf_f, index=False, engine="openpyxl")
    buf_f.seek(0)
    st.download_button("⬇ 匯出最快完成時間 (Excel)", data=buf_f,
                       file_name="test_station_fastest.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# ─── 已排除的中斷區間（同日內間隔超過門檻；跨日直接剔除不顯示）────────────────

excluded = df[df["耗時(分)"].notna() & ~df["有效"] & ~df["跨日"]].copy()
if not excluded.empty:
    with st.expander(f"🕐 已排除的中斷區間（同日內間隔 > {gap_min} 分，共 {len(excluded)} 筆）"):
        ex = excluded[GROUP_KEYS + ["序號", "測試時間", "耗時(分)"]].copy()
        ex["測試時間"] = ex["測試時間"].dt.strftime("%Y-%m-%d %H:%M")
        ex["耗時(分)"] = ex["耗時(分)"].round(0).astype(int)
        ex = ex.rename(columns={"耗時(分)": "與前筆間隔(分)"})
        st.dataframe(ex, use_container_width=True, hide_index=True)
