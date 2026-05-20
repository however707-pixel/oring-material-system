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
    "完工日未到": "#fef08a",
    "待發料":     "#fde68a",
    "缺料":       "#fed7aa",
    "齊料未生產": "#fecaca",
}

STATUS_EMOJI = {
    "試產工單":   "🧪",
    "已生產":     "✅",
    "生產中":     "⚙️",
    "完工日未到": "📅",
    "待發料":     "🟡",
    "缺料":       "⚠️",
    "齊料未生產": "🔴",
}

# ── 分類邏輯 ──────────────────────────────────────────────────────────────────
def get_shortage_reason(group, iqc_set=None, stock_by_wh=None, prod_wh=None):
    """
    stock_by_wh : {品號: {庫別: 可用量}}  來自供需表(分倉)
    prod_wh     : 工單生產庫別代號（生產進度表 生產庫別 欄）
    """
    reasons = set()
    iqc_set    = iqc_set    or set()
    stock_by_wh = stock_by_wh or {}

    for _, row in group.iterrows():
        short   = float(row.get("欠料數量", 0) or 0)
        overdue = float(row.get("逾期未入", 0) or 0)
        mat_no  = str(row.get("材料品號", "") or "")

        # ── 供需表(分倉) 有資料 → 用分倉庫存判斷 ──────────────────────────
        if stock_by_wh and mat_no in stock_by_wh:
            wh_map     = stock_by_wh[mat_no]          # {庫別: qty}
            total_avail = sum(wh_map.values())

            # 找生產倉庫存（先精確比對，再包含比對）
            prod_stock = wh_map.get(prod_wh, None)
            if prod_stock is None and prod_wh:
                for wh, qty in wh_map.items():
                    if prod_wh in wh or wh in prod_wh:
                        prod_stock = qty
                        break
            prod_stock = prod_stock or 0

            if prod_stock >= short and prod_stock > 0:
                reasons.add("倉庫未補料")          # 生產倉就有，沒補料
            elif total_avail >= short and total_avail > 0:
                reasons.add("需調撥")              # 其他倉有，需要調撥
            elif total_avail > 0:
                reasons.add("庫存不足")            # 有料但全倉加起來不夠
            else:
                if mat_no in iqc_set:
                    reasons.add("IQC 檢驗中")
                elif overdue > 0:
                    reasons.add("料沒進（逾期）")
                else:
                    reasons.add("料沒進")

        # ── 沒有供需表 → 用欠料表現有庫存判斷（舊邏輯）────────────────────
        else:
            inv = float(row.get("現有庫存", 0) or 0)
            if inv >= short and inv > 0:
                reasons.add("倉庫未補料")
            elif inv > 0:
                reasons.add("庫存不足")
            else:
                if mat_no in iqc_set:
                    reasons.add("IQC 檢驗中")
                elif overdue > 0:
                    reasons.add("料沒進（逾期）")
                else:
                    reasons.add("料沒進")

    return "、".join(sorted(reasons))

def classify_wo(no, status, end_str, shortage_map, today):
    if str(no).startswith("FF"):
        return "試產工單", ""
    if status in ("已完工", "指定完工"):
        return "已生產", ""
    if status in ("已領料", "生產中"):
        return "生產中", ""
    if status == "未生產":
        try:
            end = pd.to_datetime(end_str).date()
        except Exception:
            end = None
        if end and end > today:
            return "未生產", "完工日未到"
        if str(no) in shortage_map:
            return "未生產", f"缺料（{shortage_map[str(no)]}）"
        return "未生產", "齊料未生產"
    return "其他", ""

@st.cache_data(show_spinner=False)
def process(prod_bytes, short_bytes, today_str, iqc_bytes=None, stock_bytes=None):
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

    # 讀取供需表(分倉) → {品號: {庫別: 可用量}}
    stock_by_wh = {}
    if stock_bytes:
        df_stock = pd.read_excel(io.BytesIO(stock_bytes), dtype=str)
        df_stock.columns = df_stock.columns.str.strip()
        df_avail = df_stock[df_stock["日期"] == "庫存可用量:"].copy()
        df_avail["異動數量"] = pd.to_numeric(df_avail["異動數量"], errors="coerce").fillna(0)
        for _, sr in df_avail.iterrows():
            pno = str(sr.get("品號", "") or "").strip()
            wh  = str(sr.get("庫別", "") or "").strip()
            qty = float(sr["異動數量"])
            if pno and wh:
                stock_by_wh.setdefault(pno, {})[wh] = \
                    stock_by_wh.get(pno, {}).get(wh, 0) + qty

    # 建立欠料群組 {製令編號: DataFrame}
    shortage_groups = {str(k): g for k, g in df_sht.groupby("製令編號")}

    # 建立工單生產庫別對照 {製令編號: 生產庫別}
    prod_wh_map = {}
    if "生產庫別" in df_prod.columns:
        for _, r in df_prod[["製令編號", "生產庫別"]].dropna().iterrows():
            prod_wh_map[str(r["製令編號"])] = str(r["生產庫別"]).strip()

    # 分類
    rows = []
    for _, r in df_prod.iterrows():
        wo_no  = str(r.get("製令編號", "") or "")
        status = str(r.get("製令狀態", "") or "")
        prod_wh = prod_wh_map.get(wo_no, "")

        # 計算缺料原因（有供需表就用分倉，否則用欠料表現有庫存）
        if wo_no in shortage_groups:
            reason_str = get_shortage_reason(
                shortage_groups[wo_no], iqc_set, stock_by_wh, prod_wh
            )
        else:
            reason_str = ""

        shortage_map_local = {wo_no: reason_str} if reason_str else {}
        cat, reason = classify_wo(wo_no, status, r.get("完工日", ""), shortage_map_local, today)
        label = reason if reason else cat

        # 庫存充足但未發料 → 從「缺料」獨立為「待發料」
        if label == "缺料（倉庫未補料）":
            cat   = "待發料"
            label = "待發料"

        vendor_raw = str(r.get("廠商名稱", "") or "").strip()
        vendor = "" if vendor_raw.lower() in ("nan", "none", "") else vendor_raw
        rows.append({
            "製令編號":   wo_no,
            "品號":       r.get("產品品號", ""),
            "品名":       r.get("品名", ""),
            "開工日":     r.get("開工日", ""),
            "預計交期":   r.get("完工日", ""),
            "預計產量":   r.get("預計產量", ""),
            "已生產量":   r.get("已生產量", ""),
            "未生產量":   r.get("未生產量", ""),
            "生產方":     vendor if vendor else "廠內",
            "生產庫別":   prod_wh,
            "ERP狀態":    status,
            "分類":       cat,
            "狀態說明":   label,
        })
    return pd.DataFrame(rows), stock_by_wh, df_sht

# ── Sidebar 上傳區 ────────────────────────────────────────────────────────────
with st.sidebar:
    st.divider()
    st.markdown("### 📂 上傳資料")
    prod_file  = st.file_uploader("生產進度表（ERP匯出）", type=["xlsx", "xls"], key="prod")
    short_file = st.file_uploader("製令欠料表（ERP匯出）",  type=["xlsx", "xls"], key="short")
    iqc_file   = st.file_uploader("IQC 待驗表（ERP匯出）", type=["xlsx", "xls"], key="iqc")
    stock_file = st.file_uploader("供需表-分倉（每日更新）", type=["xlsx", "xls"], key="stock")
    st.caption("從 ERP → 製令/託外管理系統 匯出後上傳")

    st.divider()
    st.markdown("### 📅 日期區間篩選")
    date_field = st.radio("依哪個日期篩選", ["完工日", "開工日"], horizontal=True)
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
      <tr><td style="padding:5px 10px;">📅 完工日未到</td><td style="padding:5px 10px;">未生產且完工日（預計交期）尚未到</td></tr>
      <tr style="background:#dcfce7;"><td style="padding:5px 10px;">🟡 待發料</td><td style="padding:5px 10px;">庫存充足但倉庫尚未補發至生產線</td></tr>
      <tr><td style="padding:5px 10px;">⚠️ 缺料</td><td style="padding:5px 10px;">庫存不足 / 需調撥 / IQC檢驗中 / 料沒進</td></tr>
      <tr style="background:#dcfce7;"><td style="padding:5px 10px;">🔴 齊料未生產</td><td style="padding:5px 10px;">完工日已過，料齊但尚未開工</td></tr>
    </table>
    </div>
    """, unsafe_allow_html=True)
    st.stop()

# ── 資料處理 ──────────────────────────────────────────────────────────────────
with st.spinner("分析中..."):
    df, stock_by_wh, df_sht = process(
        prod_file.read(),
        short_file.read(),
        date.today().isoformat(),
        iqc_file.read() if iqc_file else None,
        stock_file.read() if stock_file else None,
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
    col_name = "預計交期" if date_field == "完工日" else "開工日"
    dt_series = pd.to_datetime(df_view[col_name], errors="coerce")
    if date_start:
        df_view = df_view[dt_series >= pd.to_datetime(date_start)]
        dt_series = pd.to_datetime(df_view[col_name], errors="coerce")
    if date_end:
        df_view = df_view[dt_series <= pd.to_datetime(date_end)]

# ── 彙總指標（依篩選後結果計算）────────────────────────────────────────────
total = len(df)
v_counts = df_view["分類"].value_counts()

col1, col2, col3, col4, col5, col6, col7 = st.columns(7)
metrics = [
    (col1, "✅ 已生產",     v_counts.get("已生產", 0),     "#bbf7d0"),
    (col2, "⚙️ 生產中",    v_counts.get("生產中", 0),     "#bfdbfe"),
    (col3, "📅 完工日未到", (df_view["狀態說明"] == "完工日未到").sum(), "#fef08a"),
    (col4, "🟡 待發料",    v_counts.get("待發料", 0),     "#fde68a"),
    (col5, "⚠️ 缺料",      df_view["狀態說明"].str.contains("缺料", na=False).sum(), "#fed7aa"),
    (col6, "🔴 齊料未生產", (df_view["狀態說明"] == "齊料未生產").sum(), "#fecaca"),
    (col7, "🧪 試產工單",  v_counts.get("試產工單", 0),   "#e5e7eb"),
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

    if "缺料" in str(wo_status) or wo_status == "待發料":
        detail_rows = df_sht[df_sht["製令編號"] == wo_no].copy()
        if not detail_rows.empty:
            # 取得此工單的生產庫別
            wo_full = df[df["製令編號"] == wo_no]
            prod_wh_sel = wo_full["生產庫別"].iloc[0] if not wo_full.empty else ""

            banner_color = "#fff7ed" if "缺料" in str(wo_status) else "#fefce8"
            border_color = "#fb923c" if "缺料" in str(wo_status) else "#facc15"
            icon = "⚠️" if "缺料" in str(wo_status) else "🟡"
            st.markdown(f"""
            <div style="background:{banner_color};border:1.5px solid {border_color};border-radius:10px;
                        padding:12px 18px;margin:8px 0 4px;">
            <b style="color:#c2410c;">{icon} 欠料明細｜工單：{wo_no}
            {"｜製造倉：" + prod_wh_sel if prod_wh_sel else ""}</b>
            </div>""", unsafe_allow_html=True)

            detail_show_cols = [c for c in ["材料品號","品名","規格","欠料數量","現有庫存","逾期未入"] if c in detail_rows.columns]
            detail_display = detail_rows[detail_show_cols].reset_index(drop=True)

            # 數值欄轉換
            for nc in ["欠料數量", "現有庫存", "逾期未入"]:
                if nc in detail_display.columns:
                    detail_display[nc] = pd.to_numeric(detail_display[nc], errors="coerce").fillna(0)

            # 加入「製造倉庫存」欄（從供需表-分倉查詢）
            def get_prod_wh_stock(mat_no):
                mat_no = str(mat_no).strip()
                if stock_by_wh and mat_no in stock_by_wh:
                    wh_map = stock_by_wh[mat_no]
                    qty = wh_map.get(prod_wh_sel, None)
                    if qty is None and prod_wh_sel:
                        for wh, q in wh_map.items():
                            if prod_wh_sel in wh or wh in prod_wh_sel:
                                qty = q
                                break
                    return float(qty) if qty is not None else 0.0
                return None  # 無供需表資料

            if "材料品號" in detail_display.columns:
                detail_display.insert(
                    detail_display.columns.get_loc("現有庫存"),
                    "製造倉庫存",
                    detail_display["材料品號"].apply(get_prod_wh_stock)
                )

            # 反紅邏輯：製造倉庫存 < 欠料數量（無供需表時退回用現有庫存）
            def highlight_insufficient(row):
                short      = float(row.get("欠料數量", 0) or 0)
                prod_stock = row.get("製造倉庫存")
                total_inv  = float(row.get("現有庫存",  0) or 0)
                check_val  = float(prod_stock) if prod_stock is not None else total_inv
                if check_val < short:
                    return ["background-color:#fecaca; color:#991b1b"] * len(row)
                return [""] * len(row)

            st.dataframe(
                detail_display.style.apply(highlight_insufficient, axis=1),
                use_container_width=True,
                column_config={
                    "材料品號":   st.column_config.TextColumn(width="medium"),
                    "品名":       st.column_config.TextColumn(width="large"),
                    "規格":       st.column_config.TextColumn(width="large"),
                    "欠料數量":   st.column_config.NumberColumn(width="small", format="%.0f"),
                    "製造倉庫存": st.column_config.NumberColumn(width="small", format="%.0f"),
                    "現有庫存":   st.column_config.NumberColumn(width="small", format="%.0f"),
                    "逾期未入":   st.column_config.NumberColumn(width="small", format="%.0f"),
                },
            )
            st.caption("🔴 紅色列 = 製造倉庫存不足欠料量｜現有庫存 = 全公司總庫存｜製造倉庫存來自供需表-分倉")
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
