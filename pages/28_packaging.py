import io
import os
import re
import sys
from datetime import datetime, date

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from utils.shared import inject_css, render_header, render_sidebar
from utils.warroom_data import TAKT_TRIM, add_standard_hours, trim_mean

st.set_page_config(page_title="包裝 製程時間分析", page_icon="📦", layout="wide")
inject_css()
render_header(title="包裝 製程時間分析", subtitle="Packaging Cycle Time Analysis · Process Station", badge="製程站 PS")
render_sidebar()

# ─── NAS 掃描 ─────────────────────────────────────────────────────────────────
# 目錄層級：料號 / 工單 / Start|End / 序號_YYYYMMDDHHMMSS_Start(End).txt
# 與組裝同一套檔名時間戳邏輯與配對方式；差別在單台工時只認「頭尾」：
# 包裝每一台都會刷 End，只有 Start 代表那台還在包裝中，不是缺資料，
# 故不套用組裝那條「節拍（頭頭）× 人數」的補值（add_standard_hours use_takt=False）。

LOG_ROOT = "//192.168.2.34/Oring_Share/Soft_Test/Log_file/OringPackage"

_FNAME_RE = re.compile(r"^([^_]+)_(\d{14})_")

KEY = ["成品料號", "工單號碼", "序號"]


def _clean_pno(name: str) -> str:
    """料號資料夾名稱含 # 補位字元，顯示時去除"""
    return re.sub(r"#+", "", name)


@st.cache_data(ttl=600, show_spinner=False)
def scan_package(root: str):
    """掃描 NAS 包裝 Log 樹。回傳 (DataFrame, 錯誤訊息或 None)"""
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
| **單台工時** | **頭尾工時＝End − Start**。包裝每台都會刷 End，故**只認這一條**；<br>只有 Start 的那幾台代表**還在包裝中**，不補值、不計入平均 |
| **工單平均** | 對該工單的單台工時**去頭 {TAKT_TRIM:.0%}、去尾 {TAKT_TRIM:.0%}，只算中間 {1 - 2 * TAKT_TRIM:.0%}**，濾掉換線／等料／休息造成的極端值 |
| **狀態分類** | ✅ 完成＝有 Start 有 End；📦 包裝中＝有 Start 無 End（**還在生產中**，或 End 早於 Start）；⚠ 缺 Start＝只有 End |
| **排除條件** | ① **尚未刷 End**（包裝中）　② **跨日**　③ 工時 ≤ 0 或 > **異常門檻**<br>此三類不計入平均，但仍列於明細供追查 |
""", unsafe_allow_html=True)

# ─── 控制列 ───────────────────────────────────────────────────────────────────

c_btn, c_gap, _ = st.columns([1.2, 1.2, 3.6])
with c_btn:
    st.markdown("<div style='height:1.75rem'></div>", unsafe_allow_html=True)
    if st.button("🔄 重新掃描 NAS", use_container_width=True):
        scan_package.clear()
        st.rerun()
with c_gap:
    gap_min = st.number_input("異常工時門檻 (分)", min_value=5, max_value=1440, value=120,
                              help="單台工時超過此分鐘數視為異常（換線／等料／休息／忘了刷），不計入平均")

with st.spinner("掃描 NAS 包裝 Log 中…"):
    df_raw, err = scan_package(LOG_ROOT)

if err:
    st.error(err)
    st.stop()
if df_raw.empty:
    st.warning("OringPackage 資料夾中沒有可解析的 Log。")
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
        return "📦 包裝中"
    return "✅ 完成"

pair["狀態"] = pair.apply(_status, axis=1)
done = pair["狀態"] == "✅ 完成"
pair.loc[~done, "工時(分)"] = pd.NA

# ─── 單台標準工時 ─────────────────────────────────────────────────────────────
# use_takt=False：只認頭尾工時；只有 Start 的那台＝還在包裝中，不用節拍補值
pair = add_standard_hours(pair, gap_min, use_takt=False)

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
n_wip    = int((view["狀態"] == "📦 包裝中").sum())
n_orphan = int((view["狀態"] == "⚠ 缺 Start").sum())
n_today  = int((view["狀態"].eq("✅ 完成") &
                (view["結束時間"].dt.date == today)).sum())
ok_view  = view[view["工時有效"]]
std_all  = trim_mean(ok_view["標準工時(分)"])
n_valid  = len(ok_view)

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("完成台數", f"{n_done} 台")
m2.metric("包裝中", f"{n_wip} 台", help="已刷 Start、尚未刷 End，代表還在生產中，不計入平均")
m3.metric("今日完成", f"{n_today} 台")
m4.metric("標準工時", "—" if pd.isna(std_all) else f"{std_all:.1f} 分",
          help=f"單台取頭尾工時 End − Start，再去頭 {TAKT_TRIM:.0%}、去尾 {TAKT_TRIM:.0%} "
               f"取中間 {1 - 2 * TAKT_TRIM:.0%} 平均。有效樣本 {n_valid} 台")
m5.metric("缺 Start 異常", f"{n_orphan} 筆")

# ─── 一、彙總：料號 / 工單 ────────────────────────────────────────────────────

GRP = ["成品料號", "工單號碼"]
summary = (
    view.groupby(GRP)
    .agg(**{
        "完成台數":  ("狀態", lambda s: (s == "✅ 完成").sum()),
        "包裝中":    ("狀態", lambda s: (s == "📦 包裝中").sum()),
        "有效樣本":  ("工時有效", "sum"),
    })
    .join(ok_view.groupby(GRP)["標準工時(分)"]
          .agg(**{"標準工時(分)": trim_mean}))
    .reset_index()
)
summary["標準工時(分)"] = summary["標準工時(分)"].astype(float).round(1)
summary = summary[GRP + ["完成台數", "包裝中", "有效樣本", "標準工時(分)"]]

st.subheader("📋 產量與包裝標準工時")
st.caption(f"單台取值：頭尾工時（End − Start）；只有 Start 的視為還在包裝中，不計入。"
           f"工單平均再去頭 {TAKT_TRIM:.0%}、去尾 {TAKT_TRIM:.0%}，只算中間 {1 - 2 * TAKT_TRIM:.0%}。")
st.dataframe(summary, use_container_width=True, hide_index=True)

buf_s = io.BytesIO()
summary.to_excel(buf_s, index=False, engine="openpyxl")
buf_s.seek(0)
st.download_button("⬇ 匯出彙總表 (Excel)", data=buf_s,
                   file_name="packaging_summary.xlsx",
                   mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# ─── 二、單台明細 ─────────────────────────────────────────────────────────────

st.divider()
st.subheader("📦 單台包裝明細")

detail = view.sort_values("開始時間", ascending=False).copy()
detail["備註"] = ""
has_start = detail["開始時間"].notna()
detail.loc[has_start & (detail["狀態"] == "📦 包裝中"), "備註"] = "尚未刷 End，包裝中"
detail.loc[has_start & ~detail["工時有效"] & (detail["狀態"] == "✅ 完成"), "備註"] = \
    f"工時異常：跨日或 >{gap_min} 分"
detail.loc[(detail["Start筆數"] > 1) | (detail["End筆數"] > 1), "備註"] += " 重複刷入取最後一筆"

show = detail[["成品料號", "工單號碼", "序號", "狀態", "開始時間", "結束時間",
               "標準工時(分)", "備註"]].copy()
for c in ["開始時間", "結束時間"]:
    show[c] = show[c].dt.strftime("%Y-%m-%d %H:%M:%S")
show["標準工時(分)"] = pd.to_numeric(show["標準工時(分)"], errors="coerce").round(1)
st.caption("「標準工時(分)」＝該台 End − Start；空白代表尚未刷 End（包裝中）或該筆工時被判為異常。")
st.dataframe(show, use_container_width=True, hide_index=True)

buf_d = io.BytesIO()
show.to_excel(buf_d, index=False, engine="openpyxl")
buf_d.seek(0)
st.download_button("⬇ 匯出單台明細 (Excel)", data=buf_d,
                   file_name="packaging_detail.xlsx",
                   mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# ─── 異常清單 ─────────────────────────────────────────────────────────────────

abn = view[view["狀態"] != "✅ 完成"]
if not abn.empty:
    with st.expander(f"⚠ 未完成／異常清單（{len(abn)} 筆）"):
        ab = abn[["成品料號", "工單號碼", "序號", "狀態", "開始時間", "結束時間"]].copy()
        for c in ["開始時間", "結束時間"]:
            ab[c] = ab[c].dt.strftime("%Y-%m-%d %H:%M:%S")
        st.dataframe(ab.fillna("—"), use_container_width=True, hide_index=True)
