import io
import os
import re
import sys
from datetime import datetime, date

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from utils.shared import inject_css, render_header, render_sidebar

st.set_page_config(page_title="組裝 製程時間分析", page_icon="🔩", layout="wide")
inject_css()
render_header(title="組裝 製程時間分析", subtitle="Assembly Cycle Time Analysis · Process Station", badge="製程站 PS")
render_sidebar()

# ─── NAS 掃描 ─────────────────────────────────────────────────────────────────
# 目錄層級：料號 / 工單 / Start|End / 序號_YYYYMMDDHHMMSS_Start(End).txt
# 與測試站同一套檔名時間戳邏輯；差別：組裝以「同序號 Start→End 配對」計工時

LOG_ROOT = "//192.168.2.34/Oring_Share/Soft_Test/Log_file/OringAssembly"

_FNAME_RE = re.compile(r"^([^_]+)_(\d{14})_")

KEY = ["成品料號", "工單號碼", "序號"]


def _clean_pno(name: str) -> str:
    """料號資料夾名稱含 # 補位字元，顯示時去除"""
    return re.sub(r"#+", "", name)


@st.cache_data(ttl=600, show_spinner=False)
def scan_assembly(root: str):
    """掃描 NAS 組裝 Log 樹。回傳 (DataFrame, 錯誤訊息或 None)"""
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
            for d3 in lv3:                             # Start / End
                phase = d3.name.strip().capitalize()
                if phase not in ("Start", "End"):
                    continue
                try:
                    files = [f.name for f in os.scandir(d3.path) if f.is_file()]
                except OSError:
                    continue
                for fn in files:
                    m = _FNAME_RE.match(fn)
                    if not m:
                        continue
                    try:
                        ts = datetime.strptime(m.group(2), "%Y%m%d%H%M%S")
                    except ValueError:
                        continue
                    rows.append({
                        "成品料號": _clean_pno(d1.name),
                        "工單號碼": d2.name,
                        "序號":     m.group(1),
                        "階段":     phase,
                        "時間":     ts,
                    })
    return pd.DataFrame(rows), None


# ─── 計算邏輯說明 ─────────────────────────────────────────────────────────────

with st.expander("📖 計算邏輯說明"):
    st.markdown(f"""
| 步驟 | 規則 |
|---|---|
| **資料來源** | `{LOG_ROOT}`<br>層級：**成品料號 → 工單號碼 → Start / End** |
| **時間解析** | 檔名 `序號_YYYYMMDDHHMMSS_Start(End)` 取 `_` 後 14 碼時間戳 |
| **配對方式** | 同一 料號/工單 內，**相同序號**的 Start 與 End 配對；同序號重複刷入時取**最後一筆** |
| **單台工時** | **End 時間 − Start 時間**（分鐘） |
| **狀態分類** | ✅ 完成＝有 Start 有 End；🔧 組裝中＝有 Start 無 End（或 End 早於 Start）；⚠ 缺 Start＝只有 End |
| **排除條件** | ① **跨日**（過夜未刷 End）　② 工時 > **異常門檻**（預設 480 分）<br>此兩類不計入平均，但仍列於明細供追查 |
| **平均工時** | 同一 料號/工單 的有效完成台平均 |
""", unsafe_allow_html=True)

# ─── 控制列 ───────────────────────────────────────────────────────────────────

c_btn, c_gap, _ = st.columns([1.2, 1.2, 3.6])
with c_btn:
    st.markdown("<div style='height:1.75rem'></div>", unsafe_allow_html=True)
    if st.button("🔄 重新掃描 NAS", use_container_width=True):
        scan_assembly.clear()
        st.rerun()
with c_gap:
    gap_min = st.number_input("異常工時門檻 (分)", min_value=30, max_value=1440, value=480,
                              help="單台工時超過此分鐘數視為異常（忘刷/中斷），不計入平均")

with st.spinner("掃描 NAS 組裝 Log 中…"):
    df_raw, err = scan_assembly(LOG_ROOT)

if err:
    st.error(err)
    st.stop()
if df_raw.empty:
    st.warning("OringAssembly 資料夾中沒有可解析的 Log。")
    st.stop()

# ─── Start / End 配對 ─────────────────────────────────────────────────────────

starts = (df_raw[df_raw["階段"] == "Start"]
          .groupby(KEY)["時間"].agg(開始時間="max", Start筆數="count"))
ends = (df_raw[df_raw["階段"] == "End"]
        .groupby(KEY)["時間"].agg(結束時間="max", End筆數="count"))
pair = starts.join(ends, how="outer").reset_index()

pair["工時(分)"] = (pair["結束時間"] - pair["開始時間"]).dt.total_seconds() / 60

def _status(r):
    if pd.isna(r["開始時間"]):
        return "⚠ 缺 Start"
    if pd.isna(r["結束時間"]) or r["工時(分)"] < 0:
        return "🔧 組裝中"
    return "✅ 完成"

pair["狀態"] = pair.apply(_status, axis=1)
done = pair["狀態"] == "✅ 完成"
pair["跨日"] = done & (pair["開始時間"].dt.date != pair["結束時間"].dt.date)
pair["有效"] = done & ~pair["跨日"] & (pair["工時(分)"] <= gap_min)
pair.loc[~done, "工時(分)"] = pd.NA

# ─── 篩選 ─────────────────────────────────────────────────────────────────────

ALL = "全部"
f1, f2, f3 = st.columns(3)
with f1:
    sel_pno = st.selectbox("成品料號", [ALL] + sorted(pair["成品料號"].unique()))
    opts_wo = pair if sel_pno == ALL else pair[pair["成品料號"] == sel_pno]
with f2:
    sel_wo = st.selectbox("工單號碼", [ALL] + sorted(opts_wo["工單號碼"].unique()))
with f3:
    sel_day = st.selectbox("開始日期", [ALL] + sorted(
        pair["開始時間"].dropna().dt.date.astype(str).unique(), reverse=True))

view = pair.copy()
if sel_pno != ALL:
    view = view[view["成品料號"] == sel_pno]
if sel_wo != ALL:
    view = view[view["工單號碼"] == sel_wo]
if sel_day != ALL:
    view = view[view["開始時間"].dt.date.astype(str) == sel_day]

# ─── KPI ──────────────────────────────────────────────────────────────────────

today = date.today()
n_done   = int((view["狀態"] == "✅ 完成").sum())
n_wip    = int((view["狀態"] == "🔧 組裝中").sum())
n_orphan = int((view["狀態"] == "⚠ 缺 Start").sum())
n_today  = int((view["狀態"].eq("✅ 完成") &
                (view["結束時間"].dt.date == today)).sum())
avg_all  = view.loc[view["有效"], "工時(分)"].mean()

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("完成台數", f"{n_done} 台")
m2.metric("組裝中", f"{n_wip} 台", help="已刷 Start、尚未刷 End")
m3.metric("今日完成", f"{n_today} 台")
m4.metric("平均工時", "—" if pd.isna(avg_all) else f"{avg_all:.1f} 分",
          help=f"僅計有效完成台（排除跨日與 >{gap_min} 分）")
m5.metric("缺 Start 異常", f"{n_orphan} 筆")

# ─── 一、彙總：料號 / 工單 ────────────────────────────────────────────────────

valid = view[view["有效"]]
summary = (
    view.groupby(["成品料號", "工單號碼"])
    .agg(**{
        "完成台數":  ("狀態", lambda s: (s == "✅ 完成").sum()),
        "組裝中":    ("狀態", lambda s: (s == "🔧 組裝中").sum()),
        "有效樣本":  ("有效", "sum"),
    })
    .join(valid.groupby(["成品料號", "工單號碼"])["工時(分)"]
          .agg(**{"平均工時(分)": "mean", "最快(分)": "min", "最慢(分)": "max"}))
    .reset_index()
)
for c in ["平均工時(分)", "最快(分)", "最慢(分)"]:
    summary[c] = summary[c].astype(float).round(1)

st.subheader("📋 產量與平均組裝工時")
st.caption("單台工時 = 同序號 End − Start；平均僅計有效完成台（排除跨日與超過異常門檻者）")
st.dataframe(summary, use_container_width=True, hide_index=True)

buf_s = io.BytesIO()
summary.to_excel(buf_s, index=False, engine="openpyxl")
buf_s.seek(0)
st.download_button("⬇ 匯出彙總表 (Excel)", data=buf_s,
                   file_name="assembly_summary.xlsx",
                   mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# ─── 二、單台明細 ─────────────────────────────────────────────────────────────

st.divider()
st.subheader("🔩 單台組裝明細")

detail = view.sort_values("開始時間", ascending=False).copy()
detail["備註"] = ""
detail.loc[detail["跨日"], "備註"] = "跨日（不計入平均）"
detail.loc[done & (detail["工時(分)"] > gap_min) & ~detail["跨日"], "備註"] = \
    f"超過 {gap_min} 分（不計入平均）"
detail.loc[(detail["Start筆數"] > 1) | (detail["End筆數"] > 1), "備註"] += " 重複刷入取最後一筆"

show = detail[["成品料號", "工單號碼", "序號", "狀態",
               "開始時間", "結束時間", "工時(分)", "備註"]].copy()
for c in ["開始時間", "結束時間"]:
    show[c] = show[c].dt.strftime("%Y-%m-%d %H:%M:%S")
show["工時(分)"] = pd.to_numeric(show["工時(分)"], errors="coerce").round(1)
st.dataframe(show, use_container_width=True, hide_index=True)

buf_d = io.BytesIO()
show.to_excel(buf_d, index=False, engine="openpyxl")
buf_d.seek(0)
st.download_button("⬇ 匯出單台明細 (Excel)", data=buf_d,
                   file_name="assembly_detail.xlsx",
                   mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# ─── 異常清單 ─────────────────────────────────────────────────────────────────

abn = view[view["狀態"] != "✅ 完成"]
if not abn.empty:
    with st.expander(f"⚠ 未完成／異常清單（{len(abn)} 筆）"):
        ab = abn[["成品料號", "工單號碼", "序號", "狀態", "開始時間", "結束時間"]].copy()
        for c in ["開始時間", "結束時間"]:
            ab[c] = ab[c].dt.strftime("%Y-%m-%d %H:%M:%S")
        st.dataframe(ab.fillna("—"), use_container_width=True, hide_index=True)
