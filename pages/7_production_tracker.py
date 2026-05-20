import streamlit as st
import pandas as pd
import io
import sys
import os
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from utils.shared import inject_css, render_header, render_sidebar
from utils.i18n import t

if "lang" not in st.session_state:
    st.session_state["lang"] = "zh"

st.set_page_config(page_title="生產進度表", page_icon="🏭", layout="wide", initial_sidebar_state="expanded")
inject_css()

with st.sidebar:
    col_zh, col_en = st.columns(2)
    with col_zh:
        if st.button("🇹🇼 中文", key="btn_zh",
                     type="primary" if st.session_state["lang"] == "zh" else "secondary",
                     use_container_width=True):
            st.session_state["lang"] = "zh"
            st.rerun()
    with col_en:
        if st.button("🇺🇸 EN", key="btn_en",
                     type="primary" if st.session_state["lang"] == "en" else "secondary",
                     use_container_width=True):
            st.session_state["lang"] = "en"
            st.rerun()

render_header(
    title="生產進度表",
    subtitle="Production Status Tracker · Production Control · ORing Industrial Networking",
    badge="Production Management System",
)
render_sidebar()

# ── 分類色票 ──────────────────────────────────────────────────────────────────
STATUS_COLOR = {
    "試產工單":   "#e5e7eb",
    "已生產":     "#bbf7d0",
    "生產中":     "#bfdbfe",
    "開工日未到": "#fef08a",
    "缺料":       "#fed7aa",
    "齊料未生產": "#fecaca",
}

STATUS_EMOJI = {
    "試產工單":   "🧪",
    "已生產":     "✅",
    "生產中":     "⚙️",
    "開工日未到": "📅",
    "缺料":       "⚠️",
    "齊料未生產": "🔴",
}

# ── 分類邏輯 ──────────────────────────────────────────────────────────────────
def get_shortage_reason(group, iqc_set=None):
    reasons = set()
    iqc_set = iqc_set or set()
    for _, row in group.iterrows():
        inv     = float(row.get("現有庫存", 0) or 0)
        short   = float(row.get("欠料數量", 0) or 0)
        overdue = float(row.get("逾期未入", 0) or 0)
        mat_no  = str(row.get("材料品號", "") or "")
        if inv >= short and inv > 0:
            reasons.add("倉庫未補料")
        elif inv > 0:
            reasons.add("庫存不足")
        else:
            # 庫存為零：先查 IQC
            if mat_no in iqc_set:
                reasons.add("IQC 檢驗中")
            elif overdue > 0:
                reasons.add("料沒進（逾期）")
            else:
                reasons.add("料沒進")
    return "、".join(sorted(reasons))

def classify_wo(no, status, start_str, shortage_map, today):
    if str(no).startswith("FF"):
        return "試產工單", ""
    if status in ("已完工", "指定完工"):
        return "已生產", ""
    if status in ("已領料", "生產中"):
        return "生產中", ""
    if status == "未生產":
        try:
            start = pd.to_datetime(start_str).date()
        except Exception:
            start = None
        if start and start > today:
            return "未生產", "開工日未到"
        if str(no) in shortage_map:
            return "未生產", f"缺料（{shortage_map[str(no)]}）"
        return "未生產", "齊料未生產"
    return "其他", ""

@st.cache_data(show_spinner=False)
def process(prod_bytes, short_bytes, today_str, iqc_bytes=None):
    today = date.fromisoformat(today_str)

    # 讀取生產進度表
    df_prod = pd.read_excel(io.BytesIO(prod_bytes), dtype=str)
    df_prod.columns = [c.replace(" ", "").replace("　", "") for c in df_prod.columns]

    # 讀取欠料表
    df_sht = pd.read_excel(io.BytesIO(short_bytes), dtype=str)
    df_sht.columns = df_sht.columns.str.strip()
    df_sht = df_sht[df_sht["製令編號"].notna() & (df_sht["製令編號"] != "小計:")]
    for col in ["欠料數量", "現有庫存", "逾期未入"]:
        df_sht[col] = pd.to_numeric(df_sht[col], errors="coerce").fillna(0)

    # 讀取 IQC 待驗表
    iqc_set = set()
    if iqc_bytes:
        df_iqc = pd.read_excel(io.BytesIO(iqc_bytes), dtype=str)
        df_iqc.columns = df_iqc.columns.str.strip()
        if "檢驗狀態" in df_iqc.columns and "品號" in df_iqc.columns:
            iqc_set = set(
                df_iqc[df_iqc["檢驗狀態"] == "待驗"]["品號"].dropna().tolist()
            )

    shortage_map = {
        str(k): get_shortage_reason(g, iqc_set)
        for k, g in df_sht.groupby("製令編號")
    }

    # 分類
    rows = []
    for _, r in df_prod.iterrows():
        cat, reason = classify_wo(
            r.get("製令編號", ""), r.get("製令狀態", ""),
            r.get("開工日", ""), shortage_map, today
        )
        label = reason if reason else cat
        vendor = str(r.get("廠商名稱", "") or "").strip()
        rows.append({
            "製令編號":   r.get("製令編號", ""),
            "品號":       r.get("產品品號", ""),
            "品名":       r.get("品名", ""),
            "開工日":     r.get("開工日", ""),
            "預計交期":   r.get("完工日", ""),
            "預計產量":   r.get("預計產量", ""),
            "已生產量":   r.get("已生產量", ""),
            "未生產量":   r.get("未生產量", ""),
            "生產方":     vendor if vendor else "廠內",
            "ERP狀態":    r.get("製令狀態", ""),
            "分類":       cat,
            "狀態說明":   label,
        })
    return pd.DataFrame(rows), shortage_map, df_sht

# ── Sidebar 上傳區 ────────────────────────────────────────────────────────────
with st.sidebar:
    st.divider()
    st.markdown("### 📂 上傳資料")
    prod_file  = st.file_uploader("生產進度表（ERP匯出）", type=["xlsx", "xls"], key="prod")
    short_file = st.file_uploader("製令欠料表（ERP匯出）",  type=["xlsx", "xls"], key="short")
    iqc_file   = st.file_uploader("IQC 待驗表（ERP匯出）", type=["xlsx", "xls"], key="iqc")
    st.caption("從 ERP → 製令/託外管理系統 匯出後上傳")

    st.divider()
    st.markdown("### 📅 日期區間篩選")
    date_field = st.radio("依哪個日期篩選", ["預計交期", "開工日"], horizontal=True)
    date_start = st.date_input("起", value=None, format="YYYY/MM/DD", key="d_start")
    date_end   = st.date_input("迄", value=None, format="YYYY/MM/DD", key="d_end")
    if date_start and date_end and date_end < date_start:
        st.error("⚠️ 結束日不可早於起始日")

# ── 主畫面 ────────────────────────────────────────────────────────────────────
if not prod_file or not short_file:
    st.info("👈 請在左側上傳「生產進度表」及「製令欠料表」兩份 Excel 檔案")

    st.markdown("""
    <div style="background:#f0fdf4;border:1.5px dashed #86efac;border-radius:12px;padding:20px 24px;margin-top:16px;">
    <b style="color:#15803d;font-size:1rem;">📋 操作步驟</b>
    <ol style="color:#374151;margin-top:10px;line-height:2;">
      <li>進入 ERP → 製令/託外管理系統 → <b>生產進度表</b>，匯出 Excel</li>
      <li>進入 ERP → 製令/託外管理系統 → <b>*製令欠料狀況表</b>，匯出 Excel</li>
      <li>將兩份檔案上傳至左側</li>
    </ol>
    <br>
    <b style="color:#15803d;">🎯 分類邏輯</b>
    <table style="margin-top:8px;width:100%;border-collapse:collapse;font-size:0.88rem;">
      <tr style="background:#dcfce7;"><td style="padding:5px 10px;">🧪 試產工單</td><td style="padding:5px 10px;">工單號以 FF 開頭</td></tr>
      <tr><td style="padding:5px 10px;">✅ 已生產</td><td style="padding:5px 10px;">已完工 / 指定完工</td></tr>
      <tr style="background:#dcfce7;"><td style="padding:5px 10px;">⚙️ 生產中</td><td style="padding:5px 10px;">已領料 / 生產中</td></tr>
      <tr><td style="padding:5px 10px;">📅 開工日未到</td><td style="padding:5px 10px;">未生產且開工日尚未到</td></tr>
      <tr style="background:#dcfce7;"><td style="padding:5px 10px;">⚠️ 缺料</td><td style="padding:5px 10px;">欠料表中有缺料記錄（含原因）</td></tr>
      <tr><td style="padding:5px 10px;">🔴 齊料未生產</td><td style="padding:5px 10px;">開工日已過，料齊但尚未開工</td></tr>
    </table>
    </div>
    """, unsafe_allow_html=True)
    st.stop()

# ── 資料處理 ──────────────────────────────────────────────────────────────────
with st.spinner("分析中..."):
    df, shortage_map, df_sht = process(
        prod_file.read(),
        short_file.read(),
        date.today().isoformat(),
        iqc_file.read() if iqc_file else None,
    )

# ── 篩選列 ────────────────────────────────────────────────────────────────────
fc1, fc2, fc3, fc4 = st.columns([2, 2, 2, 3])
with fc1:
    status_opts = ["全部"] + sorted(df["狀態說明"].dropna().unique().tolist())
    sel_status = st.selectbox("篩選狀態", status_opts)
with fc2:
    erp_opts = ["全部"] + sorted(df["ERP狀態"].dropna().unique().tolist())
    sel_erp = st.selectbox("篩選 ERP 狀態", erp_opts)
with fc3:
    vendor_opts = ["全部"] + sorted(df["生產方"].dropna().unique().tolist())
    sel_vendor = st.selectbox("篩選生產方", vendor_opts)
with fc4:
    keyword = st.text_input("搜尋工單號 / 品號 / 品名", placeholder="輸入關鍵字...")

df_view = df.copy()
if sel_status != "全部":
    df_view = df_view[df_view["狀態說明"] == sel_status]
if sel_erp != "全部":
    df_view = df_view[df_view["ERP狀態"] == sel_erp]
if sel_vendor != "全部":
    df_view = df_view[df_view["生產方"] == sel_vendor]
if keyword:
    mask = (
        df_view["製令編號"].str.contains(keyword, na=False) |
        df_view["品號"].str.contains(keyword, na=False) |
        df_view["品名"].str.contains(keyword, na=False)
    )
    df_view = df_view[mask]

# 日期區間篩選
if date_start or date_end:
    col_name = "預計交期" if date_field == "預計交期" else "開工日"
    dt_series = pd.to_datetime(df_view[col_name], errors="coerce")
    if date_start:
        df_view = df_view[dt_series >= pd.to_datetime(date_start)]
        dt_series = pd.to_datetime(df_view[col_name], errors="coerce")
    if date_end:
        df_view = df_view[dt_series <= pd.to_datetime(date_end)]

# ── 彙總指標（依篩選後結果計算）────────────────────────────────────────────
total = len(df)
v_counts = df_view["分類"].value_counts()

col1, col2, col3, col4, col5, col6 = st.columns(6)
metrics = [
    (col1, "✅ 已生產",     v_counts.get("已生產", 0),     "#bbf7d0"),
    (col2, "⚙️ 生產中",    v_counts.get("生產中", 0),     "#bfdbfe"),
    (col3, "📅 開工日未到", (df_view["狀態說明"] == "開工日未到").sum(), "#fef08a"),
    (col4, "⚠️ 缺料",      df_view["狀態說明"].str.contains("缺料", na=False).sum(), "#fed7aa"),
    (col5, "🔴 齊料未生產", (df_view["狀態說明"] == "齊料未生產").sum(), "#fecaca"),
    (col6, "🧪 試產工單",  v_counts.get("試產工單", 0),   "#e5e7eb"),
]
for col, label, cnt, bg in metrics:
    col.markdown(
        f'<div style="background:{bg};border-radius:10px;padding:14px 10px;text-align:center;'
        f'border:1px solid rgba(0,0,0,0.07);box-shadow:0 2px 8px rgba(0,0,0,0.06);">'
        f'<div style="font-size:0.78rem;color:#475569;font-weight:600;">{label}</div>'
        f'<div style="font-size:1.8rem;font-weight:900;color:#1e293b;line-height:1.3;">{cnt}</div>'
        f'</div>', unsafe_allow_html=True
    )

st.markdown("<br>", unsafe_allow_html=True)
st.caption(f"顯示 {len(df_view):,} 筆 / 共 {total:,} 筆工單")

# ── 資料表 ────────────────────────────────────────────────────────────────────
display_cols = ["製令編號", "品號", "品名", "生產方", "開工日", "預計交期", "預計產量", "已生產量", "未生產量", "ERP狀態", "狀態說明"]

col_cfg = {
    "製令編號": st.column_config.TextColumn(width="medium"),
    "品號":     st.column_config.TextColumn(width="medium"),
    "品名":     st.column_config.TextColumn(width="large"),
    "生產方":   st.column_config.TextColumn(width="small"),
    "開工日":   st.column_config.TextColumn(width="small"),
    "預計交期": st.column_config.TextColumn(width="small"),
    "預計產量": st.column_config.TextColumn(width="small"),
    "已生產量": st.column_config.TextColumn(width="small"),
    "未生產量": st.column_config.TextColumn(width="small"),
    "ERP狀態":  st.column_config.TextColumn(width="small"),
    "狀態說明": st.column_config.TextColumn(width="medium"),
}

selected = st.dataframe(
    df_view[display_cols].reset_index(drop=True),
    use_container_width=True,
    height=520,
    column_config=col_cfg,
    on_select="rerun",
    selection_mode="single-row",
)

# ── 缺料明細展開 ──────────────────────────────────────────────────────────────
sel_rows = selected.selection.rows if selected and selected.selection else []
if sel_rows:
    sel_idx = sel_rows[0]
    sel_wo  = df_view[display_cols].reset_index(drop=True).iloc[sel_idx]
    wo_no   = sel_wo["製令編號"]
    wo_status = sel_wo["狀態說明"]

    if "缺料" in str(wo_status):
        detail_rows = df_sht[df_sht["製令編號"] == wo_no].copy()
        if not detail_rows.empty:
            st.markdown(f"""
            <div style="background:#fff7ed;border:1.5px solid #fb923c;border-radius:10px;
                        padding:12px 18px;margin:8px 0 4px;">
            <b style="color:#c2410c;">⚠️ 缺料明細｜工單：{wo_no}</b>
            </div>""", unsafe_allow_html=True)
            detail_show_cols = [c for c in ["材料品號","品名","規格","欠料數量","現有庫存","逾期未入"] if c in detail_rows.columns]
            detail_display = detail_rows[detail_show_cols].reset_index(drop=True)

            # 數值欄轉換
            for nc in ["欠料數量", "現有庫存", "逾期未入"]:
                if nc in detail_display.columns:
                    detail_display[nc] = pd.to_numeric(detail_display[nc], errors="coerce").fillna(0)

            # 無法補足（庫存 < 欠料量）→ 整列反紅
            def highlight_insufficient(row):
                inv   = float(row.get("現有庫存", 0) or 0)
                short = float(row.get("欠料數量",  0) or 0)
                if inv < short:
                    return ["background-color:#fecaca; color:#991b1b"] * len(row)
                return [""] * len(row)

            st.dataframe(
                detail_display.style.apply(highlight_insufficient, axis=1),
                use_container_width=True,
                column_config={
                    "材料品號": st.column_config.TextColumn(width="medium"),
                    "品名":     st.column_config.TextColumn(width="large"),
                    "規格":     st.column_config.TextColumn(width="large"),
                    "欠料數量": st.column_config.NumberColumn(width="small"),
                    "現有庫存": st.column_config.NumberColumn(width="small"),
                    "逾期未入": st.column_config.NumberColumn(width="small"),
                },
            )
            st.caption("🔴 紅色列 = 現有庫存不足以補齊欠料量")
    else:
        st.info(f"工單 {wo_no} 無缺料明細（狀態：{wo_status}）")

# ── 下載 ──────────────────────────────────────────────────────────────────────
st.divider()
dc1, dc2 = st.columns(2)

with dc1:
    buf = io.BytesIO()
    df_view[display_cols].to_excel(buf, index=False, engine="openpyxl")
    buf.seek(0)
    st.download_button(
        "⬇️ 下載目前篩選結果",
        data=buf,
        file_name=f"生產進度追蹤_{date.today()}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )

with dc2:
    df_short_view = df_view[df_view["狀態說明"].str.contains("缺料", na=False)]
    if not df_short_view.empty:
        wo_list = df_short_view["製令編號"].tolist()
        detail = df_sht[df_sht["製令編號"].isin(wo_list)].copy()
        buf2 = io.BytesIO()
        detail.to_excel(buf2, index=False, engine="openpyxl")
        buf2.seek(0)
        st.download_button(
            "⬇️ 下載缺料工單欠料明細",
            data=buf2,
            file_name=f"缺料明細_{date.today()}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
