import streamlit as st
import pandas as pd
import io
import sys
import os
from datetime import date
import plotly.graph_objects as go
from plotly.subplots import make_subplots

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
    "已結案":     "#bbf7d0",
    "生產中":     "#bfdbfe",
    "完工日未到": "#fef08a",
    "待扣帳":     "#fde68a",
    "待調撥":     "#ddd6fe",
    "缺料":       "#fed7aa",
    "齊料未生產": "#fecaca",
}

STATUS_EMOJI = {
    "試產工單":   "🧪",
    "已結案":     "✅",
    "生產中":     "⚙️",
    "完工日未到": "📅",
    "待扣帳":     "🟡",
    "待調撥":     "🔀",
    "缺料":       "⚠️",
    "齊料未生產": "🔴",
}

# ── 生產方 → 供需表庫別名稱 對照表 ────────────────────────────────────────────
VENDOR_WH_MAP = {
    "廠內": ["機構倉", "包材倉", "成品倉", "電子倉"],
    "國智": ["修研/華盈/國智代工倉"],
    "唐佑": ["唐佑代工倉"],
    "正文": ["正文代工倉"],
    "秦宏": ["秦宏代工倉"],
    "貫崑": ["貫崑代工倉"],
}
# 廠內倉別（向後相容用）
INNER_WH_NAMES = VENDOR_WH_MAP["廠內"]

def get_vendor_stock(mat_no, vendor, stock_by_wh):
    """
    依生產方查詢對應倉別庫存（stock_by_wh key = 庫別名稱）。
    優先查 VENDOR_WH_MAP；未登記廠商則用庫別名稱包含廠商名稱做模糊比對。
    回傳 None 表示供需表中無此品號資料。
    """
    if not stock_by_wh or mat_no not in stock_by_wh:
        return None
    wh_map  = stock_by_wh[mat_no]          # {庫別名稱: qty}
    wh_list = VENDOR_WH_MAP.get(vendor)    # 精確對照

    if wh_list is not None:
        # 有明確對照 → 加總指定倉別
        return sum(wh_map.get(wh, 0) for wh in wh_list)
    else:
        # 未登記廠商 → 模糊比對庫別名稱
        matched = [qty for wh, qty in wh_map.items()
                   if vendor and (vendor in wh or wh in vendor)]
        return sum(matched) if matched else None

# ── 分類邏輯 ──────────────────────────────────────────────────────────────────
def get_shortage_reason(group, iqc_set=None, stock_by_wh=None, vendor=None,
                         wo_no=None, wo_supply=None):
    """
    stock_by_wh : {品號: {庫別: 可用量}}  來自供需表 庫存可用量 列（廠內用）
    vendor      : 生產方（廠內 / 廠商名稱）
    wo_no       : 製令編號
    wo_supply   : {(品號, 製令編號): (預計結存, 欠料量)}  來自供需表 備註=工單號 列（委外用）
    """
    reasons = set()
    iqc_set     = iqc_set     or set()
    stock_by_wh = stock_by_wh or {}
    vendor      = vendor      or "廠內"
    wo_supply   = wo_supply   or {}

    for _, row in group.iterrows():
        short   = float(row.get("欠料數量", 0) or 0)
        overdue = float(row.get("逾期未入", 0) or 0)
        mat_no  = str(row.get("材料品號", "") or "")

        # 欠料量 <= 0 表示已無缺料，略過此列
        if short <= 0:
            continue

        # ── 委外工單：用供需表「備註=工單號」的預計結存判斷 ─────────────────
        if vendor != "廠內" and wo_no:
            if (mat_no, wo_no) in wo_supply:
                balance  = wo_supply[(mat_no, wo_no)][0]  # 預計結存（用完本工單後）
                qty_used = wo_supply[(mat_no, wo_no)][1]  # 異動數量（本工單用量，正數）
                avail_before = balance + qty_used          # 本工單用料前的可用量 = 預計結存 + 異動數量
                if avail_before >= short:
                    pass  # 料已分配足夠，不算缺料，此材料略過
                elif balance >= 0:
                    reasons.add("需調撥")      # 分配量不足但源頭還有料 → 待調撥
                else:
                    reasons.add("庫存不足")    # 源頭倉也不夠 → 真缺料
            else:
                # 供需表找不到此工單的分配紀錄
                # → 改查委外倉自身庫存（庫存可用量），再看廠內是否有料可轉
                vendor_stock = get_vendor_stock(mat_no, vendor, stock_by_wh) or 0
                if vendor_stock >= short and vendor_stock > 0:
                    # 委外倉自己有料，ERP 欠料記錄可能是舊的或待沖帳
                    reasons.add("倉庫未補料")
                elif stock_by_wh and mat_no in stock_by_wh:
                    wh_map      = stock_by_wh[mat_no]
                    total_avail = sum(wh_map.values())
                    if total_avail >= short and total_avail > 0:
                        reasons.add("需調撥")   # 廠內有料，需發料到委外倉
                    elif total_avail > 0:
                        reasons.add("庫存不足")
                    else:
                        if mat_no in iqc_set:
                            reasons.add("IQC 檢驗中")
                        elif overdue > 0:
                            reasons.add("料沒進（逾期）")
                        else:
                            reasons.add("料沒進")
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
            continue

        # ── 廠內：用供需表 庫存可用量 判斷 ─────────────────────────────────
        if stock_by_wh and mat_no in stock_by_wh:
            wh_map      = stock_by_wh[mat_no]
            total_avail = sum(wh_map.values())
            prod_stock  = get_vendor_stock(mat_no, vendor, stock_by_wh) or 0

            if prod_stock >= short and prod_stock > 0:
                reasons.add("倉庫未補料")          # 製造倉就有，沒補料
            elif total_avail >= short and total_avail > 0:
                reasons.add("需調撥")              # 其他倉有，需調撥
            elif total_avail > 0:
                reasons.add("庫存不足")            # 有料但全倉不夠
            else:
                if mat_no in iqc_set:
                    reasons.add("IQC 檢驗中")
                elif overdue > 0:
                    reasons.add("料沒進（逾期）")
                else:
                    reasons.add("料沒進")

        # ── 無供需表 → 用欠料表現有庫存判斷（舊邏輯）──────────────────────
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
        return "已結案", ""
    if status in ("已領料", "生產中"):
        return "生產中", ""
    if status == "未生產":
        try:
            end = pd.to_datetime(end_str).date()
        except Exception:
            end = None
        if end and end > today:
            # 完工日未到 → 直接依缺料狀況歸入齊料未生產或缺料
            if str(no) in shortage_map:
                return "未生產", f"缺料（{shortage_map[str(no)]}）"
            return "未生產", "齊料未生產"
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

    # 讀取供需表(分倉)
    stock_by_wh = {}   # {品號: {庫別: 可用量}}（廠內，來自庫存可用量列）
    wo_supply   = {}   # {(品號, 製令編號): (預計結存, 欠料量)}（委外，來自備註=工單號列）
    if stock_bytes:
        df_stock = pd.read_excel(io.BytesIO(stock_bytes), dtype=str)
        df_stock.columns = df_stock.columns.str.strip()

        # 建立 庫別代碼 → 庫別名稱 對照表（從有庫別名稱的列取得）
        _has_name = df_stock["庫別名稱"].notna() & (df_stock["庫別名稱"].str.strip() != "")
        code_to_name = {}
        for _, _r in df_stock[_has_name].iterrows():
            _code = str(_r.get("庫別", "") or "").strip()
            _name = str(_r.get("庫別名稱", "") or "").strip()
            if _code and _name:
                code_to_name[_code] = _name

        # 廠內倉別現有庫存（庫存可用量列）
        # 庫存可用量列的庫別名稱欄為空，改從 code_to_name 轉換成名稱，與 VENDOR_WH_MAP 一致
        df_avail = df_stock[df_stock["日期"] == "庫存可用量:"].copy()
        df_avail["異動數量"] = pd.to_numeric(df_avail["異動數量"], errors="coerce").fillna(0)
        for _, sr in df_avail.iterrows():
            pno  = str(sr.get("品號", "") or "").strip()
            code = str(sr.get("庫別", "") or "").strip()
            qty  = float(sr["異動數量"])
            wh   = code_to_name.get(code, code)   # 代碼轉名稱，找不到就用代碼
            if pno and wh:
                stock_by_wh.setdefault(pno, {})[wh] = \
                    stock_by_wh.get(pno, {}).get(wh, 0) + qty

        # 委外工單供應鏈餘量（備註=工單號 + 庫別名稱=代工倉 + 預計領用）
        mask = (
            df_stock["異動別"].str.strip() == "預計領用"
        ) & df_stock["備註"].notna() & (df_stock["備註"].str.strip() != "") \
          & df_stock["庫別名稱"].notna() & (df_stock["庫別名稱"].str.strip() != "")
        df_wo = df_stock[mask].copy()
        df_wo["_bal"] = pd.to_numeric(df_wo["預計結存"], errors="coerce")
        df_wo["_qty"] = pd.to_numeric(df_wo["異動數量"], errors="coerce").fillna(0)
        for _, sr in df_wo.iterrows():
            pno    = str(sr.get("品號", "") or "").strip()
            wo_key = str(sr.get("備註", "") or "").strip()
            bal    = sr["_bal"]
            qty    = sr["_qty"]
            if pno and wo_key and not pd.isna(bal):
                key = (pno, wo_key)
                # 保留最小餘量（最保守估計）
                if key not in wo_supply or float(bal) < wo_supply[key][0]:
                    wo_supply[key] = (float(bal), float(qty))

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

        # 先算生產方（廠內 / 廠商名稱），供倉庫查詢使用
        vendor_raw   = str(r.get("廠商名稱", "") or "").strip()
        vendor       = "" if vendor_raw.lower() in ("nan", "none", "") else vendor_raw
        vendor_label = vendor if vendor else "廠內"

        # 計算缺料原因（廠內→庫存可用量判斷；委外→供需表備註=工單號的預計結存判斷）
        if wo_no in shortage_groups:
            reason_str = get_shortage_reason(
                shortage_groups[wo_no], iqc_set, stock_by_wh, vendor_label,
                wo_no=wo_no, wo_supply=wo_supply
            )
        else:
            reason_str = ""

        shortage_map_local = {wo_no: reason_str} if reason_str else {}
        cat, reason = classify_wo(wo_no, status, r.get("完工日", ""), shortage_map_local, today)
        label = reason if reason else cat

        # 製造倉有料但未發料 → 獨立為「待扣帳」
        if label == "缺料（倉庫未補料）":
            cat   = "待扣帳"
            label = "待扣帳"
        # 全公司總庫存夠，只是不在製造倉 → 獨立為「待調撥」
        elif label == "缺料（需調撥）":
            cat   = "待調撥"
            label = "待調撥"

        rows.append({
            "製令編號":   wo_no,
            "品號":       r.get("產品品號", ""),
            "品名":       r.get("品名", ""),
            "開工日":     r.get("開工日", ""),
            "預計交期":   r.get("完工日", ""),
            "預計產量":   r.get("預計產量", ""),
            "已生產量":   r.get("已生產量", ""),
            "未生產量":   r.get("未生產量", ""),
            "生產方":     vendor_label,
            "ERP狀態":    status,
            "分類":       cat,
            "狀態說明":   label,
        })
    return pd.DataFrame(rows), stock_by_wh, df_sht, wo_supply

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
    if st.button("🔄 清除快取・重新分析", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

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
    <ol style="color:#374151;margin-top:10px;line-height:2.2;">
      <li>ERP → 製令/託外管理系統 → <b>生產進度表</b> → 匯出 Excel，上傳至左側</li>
      <li>ERP → 製令/託外管理系統 → <b>*製令欠料狀況表</b> → 匯出 Excel，上傳至左側</li>
      <li>（選填）ERP → 品管系統 → <b>IQC 待驗表</b> → 匯出 Excel，上傳至左側<br>
          <span style="color:#6b7280;font-size:0.85rem;">↳ 上傳後可辨識「IQC 檢驗中」缺料原因</span></li>
      <li>（選填）每日更新的 <b>供需表－分倉</b> → 上傳至左側<br>
          <span style="color:#6b7280;font-size:0.85rem;">↳ 上傳後可顯示製造倉庫存、判斷待扣帳 / 待調撥 / 真缺料</span></li>
    </ol>
    <br>
    <b style="color:#15803d;">🎯 分類邏輯</b>
    <table style="margin-top:8px;width:100%;border-collapse:collapse;font-size:0.88rem;">
      <tr style="background:#dcfce7;"><td style="padding:5px 10px;">🧪 試產工單</td><td style="padding:5px 10px;">工單號以 FF 開頭</td></tr>
      <tr><td style="padding:5px 10px;">✅ 已結案</td><td style="padding:5px 10px;">已完工 / 指定完工</td></tr>
      <tr style="background:#dcfce7;"><td style="padding:5px 10px;">⚙️ 生產中</td><td style="padding:5px 10px;">已領料 / 生產中</td></tr>
      <tr><td style="padding:5px 10px;">📅 完工日未到｜齊料</td><td style="padding:5px 10px;">完工日尚未到，料已齊全，正常排程中</td></tr>
      <tr style="background:#dcfce7;"><td style="padding:5px 10px;">📅 完工日未到｜缺料</td><td style="padding:5px 10px;">完工日尚未到，但目前已有缺料，需提前處理</td></tr>
      <tr><td style="padding:5px 10px;">🟡 待扣帳</td><td style="padding:5px 10px;">製造倉庫存充足，倉庫尚未補發至生產線</td></tr>
      <tr><td style="padding:5px 10px;">🔀 待調撥</td><td style="padding:5px 10px;">製造倉無料，但全公司總庫存充足，需從其他倉調撥</td></tr>
      <tr style="background:#dcfce7;"><td style="padding:5px 10px;">⚠️ 缺料</td><td style="padding:5px 10px;">庫存不足 / IQC檢驗中 / 料沒進（真正缺料）</td></tr>
      <tr style="background:#dcfce7;"><td style="padding:5px 10px;">🔴 齊料未生產</td><td style="padding:5px 10px;">完工日已過，料齊但尚未開工</td></tr>
    </table>
    </div>
    """, unsafe_allow_html=True)
    st.stop()

# ── 資料處理 ──────────────────────────────────────────────────────────────────
with st.spinner("分析中..."):
    df, stock_by_wh, df_sht, wo_supply = process(
        prod_file.read(),
        short_file.read(),
        date.today().isoformat(),
        iqc_file.read() if iqc_file else None,
        stock_file.read() if stock_file else None,
    )

# ── 舊快取格式相容處理 ───────────────────────────────────────────────────────
# 「已生產」→「已結案」
df["分類"]   = df["分類"].replace("已生產", "已結案")
df["狀態說明"] = df["狀態說明"].replace("已生產", "已結案")

# 舊格式：分類="完工日未到" → 改歸入齊料未生產或缺料
_old_future_short = (df["分類"] == "完工日未到") & df["狀態說明"].str.contains("缺料", na=False)
_old_future_ok    = (df["分類"] == "完工日未到") & ~df["狀態說明"].str.contains("缺料", na=False)
df.loc[_old_future_short, "分類"] = "未生產"
# 狀態說明去掉前綴"完工日未到｜"
df.loc[_old_future_short, "狀態說明"] = df.loc[_old_future_short, "狀態說明"].str.replace("完工日未到｜", "", regex=False)
df.loc[_old_future_ok, "分類"]   = "未生產"
df.loc[_old_future_ok, "狀態說明"] = "齊料未生產"
# 舊格式：分類="未生產" + 狀態說明="完工日未到" → 齊料未生產
_old_future2 = (df["分類"] == "未生產") & (df["狀態說明"] == "完工日未到")
df.loc[_old_future2, "狀態說明"] = "齊料未生產"

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

# 各分類計數（先算好，加總才準確）
cnt_done     = int(v_counts.get("已結案",   0))
cnt_wip      = int(v_counts.get("生產中",   0))
cnt_held     = int(v_counts.get("待扣帳",   0))
cnt_transfer = int(v_counts.get("待調撥",   0))
cnt_short    = int(df_view["狀態說明"].str.contains("缺料", na=False).sum())
cnt_trial    = int(v_counts.get("試產工單", 0))
cnt_ready    = int((df_view["狀態說明"] == "齊料未生產").sum())

# 總數 = df_view 全部（含未分類到小格的工單）
cnt_total  = len(df_view)

# 生產方統計（從 df_view 算，其他 = 非廠內/國智/唐佑）
_n_inner   = int((df_view["生產方"] == "廠內").sum())
_n_guozhi  = int((df_view["生產方"] == "國智").sum())
_n_tangyou = int((df_view["生產方"] == "唐佑").sum())
_n_other   = cnt_total - _n_inner - _n_guozhi - _n_tangyou

col_total, col1, col2, col3, col4, col5, col6, col7 = st.columns([2,1,1,1,1,1,1,1])

# 總筆數大格
col_total.markdown(
    f'<div style="background:#f1f5f9;border-radius:10px;padding:14px 16px;text-align:center;'
    f'border:1px solid rgba(0,0,0,0.09);box-shadow:0 2px 8px rgba(0,0,0,0.06);height:100%;">'
    f'<div style="font-size:0.78rem;color:#475569;font-weight:600;">📋 工單總數（篩選後）</div>'
    f'<div style="font-size:2rem;font-weight:900;color:#1e293b;line-height:1.3;">{cnt_total:,}</div>'
    f'<div style="font-size:0.72rem;color:#64748b;margin-top:6px;line-height:2;">'
    f'廠內 <b>{_n_inner}</b> &nbsp;｜&nbsp; 國智 <b>{_n_guozhi}</b>'
    f'&nbsp;｜&nbsp; 唐佑 <b>{_n_tangyou}</b> &nbsp;｜&nbsp; 其他 <b>{_n_other}</b>'
    f'</div>'
    f'</div>', unsafe_allow_html=True
)

metrics = [
    (col1, "✅ 已結案",     cnt_done,     "#bbf7d0"),
    (col2, "⚙️ 生產中",    cnt_wip,      "#bfdbfe"),
    (col3, "🟡 待扣帳",    cnt_held,     "#fde68a"),
    (col4, "🔀 待調撥",    cnt_transfer, "#ddd6fe"),
    (col5, "🧪 試產工單",  cnt_trial,    "#e5e7eb"),
    (col6, "🔴 齊料未生產", cnt_ready,   "#fecaca"),
    (col7, "⚠️ 缺料",      cnt_short,    "#fed7aa"),
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

# ── CEO 5D 儀表板 ─────────────────────────────────────────────────────────────
st.divider()

# 顏色工具
def _hex_darken(hx, f=0.60):
    hx = hx.lstrip('#')
    r,g,b = int(hx[0:2],16), int(hx[2:4],16), int(hx[4:6],16)
    return f"#{max(0,int(r*f)):02x}{max(0,int(g*f)):02x}{max(0,int(b*f)):02x}"

def _hex_lighten(hx, f=1.40):
    hx = hx.lstrip('#')
    r,g,b = int(hx[0:2],16), int(hx[2:4],16), int(hx[4:6],16)
    return f"#{min(255,int(r*f)):02x}{min(255,int(g*f)):02x}{min(255,int(b*f)):02x}"

# CSS：圖表容器卡片化
st.markdown("""
<style>
[data-testid="stPlotlyChart"] > div {
    border-radius: 0 !important;
    box-shadow: none !important;
    overflow: visible !important;
}
.ceo-card {
    background: white;
    border-radius: 18px;
    border: 1px solid #e2e8f0;
    box-shadow: 0 8px 36px rgba(0,0,0,0.13), 0 2px 8px rgba(0,0,0,0.07);
    padding: 16px 20px 8px 20px;
    margin-bottom: 12px;
}
.ceo-card-title {
    font-size: 0.88rem;
    font-weight: 800;
    margin-bottom: 4px;
    letter-spacing: 0.02em;
}
</style>
""", unsafe_allow_html=True)

# ── 5D 標題列 ─────────────────────────────────────────────────────────────────
def _dim_b(code, icon, title, desc, bg, tc):
    return (
        f'<div style="background:{bg};border-radius:10px;padding:9px 14px;'
        f'border:1px solid rgba(0,0,0,0.07);min-width:100px;flex-shrink:0;">'
        f'<div style="font-size:0.76rem;font-weight:800;color:{tc};">{icon} {code} {title}</div>'
        f'<div style="font-size:0.65rem;color:#64748b;margin-top:3px;line-height:1.45;">{desc}</div>'
        f'</div>'
    )

st.markdown(f"""
<div style="background:white;border-radius:16px;padding:20px 28px;margin-bottom:14px;
     box-shadow:0 4px 24px rgba(0,0,0,0.10);border:1px solid #e2e8f0;">
  <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:14px;">
    <div>
      <div style="font-size:2rem;font-weight:900;color:#1e293b;line-height:1.15;">
        工單&nbsp;<span style="color:#3b82f6;font-style:italic;">5D</span>&nbsp;總覽
      </div>
      <div style="color:#64748b;font-size:0.83rem;margin-top:6px;">
        總工單數 <b style="color:#1e293b;">{cnt_total}</b>
        &nbsp;｜&nbsp; 資料更新：{date.today().strftime('%Y/%m/%d %H:%M')}
      </div>
    </div>
    <div style="display:flex;gap:10px;flex-wrap:wrap;">
      {_dim_b("D1","📅","時間維度","掌握工單時間趨勢<br>與處理效率","#dbeafe","#1d4ed8")}
      {_dim_b("D2","📍","空間維度","按廠內/國智/唐佑/<br>其他分析分布","#dcfce7","#15803d")}
      {_dim_b("D3","✅","狀態維度","追蹤工單狀態分布<br>與轉換效率","#f0fdf4","#166534")}
      {_dim_b("D4","🔖","類型維度","分析試產工單與缺料<br>佔比與影響","#fef9c3","#854d0e")}
      {_dim_b("D5","💰","價值維度","統計完成率與未完成<br>之業務價值","#fee2e2","#991b1b")}
    </div>
  </div>
</div>
""", unsafe_allow_html=True)

# ── CEO 簡化 5 大類 ───────────────────────────────────────────────────────────
_tot_s = cnt_total if cnt_total > 0 else 1
_C5L = ["已結案",   "生產中",            "齊料待生產",                "試產工單",  "需處理"]
_C5V = [cnt_done,   cnt_wip + cnt_held,  cnt_ready,      cnt_trial,   cnt_short + cnt_transfer]
_C5C = ["#16a34a",  "#2563eb",           "#ea580c",                   "#6b7280",   "#dc2626"]
_C5E = ["✅",       "⚙️",               "📦",                        "🧪",        "⚠️"]
_C5P = [0.03,       0.03,                0.08,                        0.03,        0.22]   # 大 pull = 更立體

_c5nz = [(l,v,c,e,p) for l,v,c,e,p in zip(_C5L,_C5V,_C5C,_C5E,_C5P) if v > 0]
_c5l,_c5v,_c5c,_c5e,_c5p = zip(*_c5nz) if _c5nz else ([],[],[],[],[])

# 生產方 × 5 大類 cross table
_cat5_map = {
    "已結案":    "已結案",   "生產中":    "生產中",
    "待扣帳":    "生產中",   "待調撥":    "需處理",
    "試產工單":  "試產工單", "齊料未生產":"齊料待生產",
}
df_view["_c5cat"] = df_view["分類"].map(_cat5_map).fillna("需處理")
df_view["_vg"]    = df_view["生產方"].apply(lambda v: v if v in ("廠內","國智","唐佑") else "其他")

_vorder = ["廠內","國智","唐佑","其他"]
_cross5 = df_view.groupby(["_vg","_c5cat"]).size().unstack(fill_value=0)
for _s in _C5L:
    if _s not in _cross5.columns: _cross5[_s] = 0
_cross5 = _cross5.reindex(columns=_C5L, fill_value=0)
_cross5 = _cross5.reindex([v for v in _vorder if v in _cross5.index])
_vens5  = list(_cross5.index)

# ── 左圖 D1：超大立體甜甜圈 ──────────────────────────────────────────────────
fig_d1 = go.Figure()

# 第一層：底部陰影（深色偏移，製造厚度感）
fig_d1.add_trace(go.Pie(
    labels=list(_c5l), values=list(_c5v),
    hole=0.50, pull=[p + 0.025 for p in _c5p],
    marker=dict(colors=["rgba(15,23,42,0.18)"]*len(_c5v),
                line=dict(color="rgba(0,0,0,0)", width=0)),
    textinfo="none", hoverinfo="skip", showlegend=False,
    direction="clockwise", sort=True, rotation=96,
    domain=dict(x=[0,1], y=[0,1]),
))

# 第二層：中間高光（白色細環，增加厚度感）
fig_d1.add_trace(go.Pie(
    labels=list(_c5l), values=list(_c5v),
    hole=0.55, pull=[p + 0.01 for p in _c5p],
    marker=dict(colors=["rgba(255,255,255,0.35)"]*len(_c5v),
                line=dict(color="rgba(0,0,0,0)", width=0)),
    textinfo="none", hoverinfo="skip", showlegend=False,
    direction="clockwise", sort=True, rotation=91,
    domain=dict(x=[0,1], y=[0,1]),
))

# 第三層：主體（彩色 + 外側標籤；標籤用換行分兩行，避免擁擠）
_d1_labels = [f"{e} {l}<br>{v} ({v/_tot_s*100:.1f}%)" for l,v,e in zip(_c5l,_c5v,_c5e)]

fig_d1.add_trace(go.Pie(
    labels=_d1_labels,
    values=list(_c5v),
    hole=0.62,
    pull=list(_c5p),
    marker=dict(
        colors=list(_c5c),
        line=dict(color="white", width=4),
    ),
    textinfo="label",
    textposition="outside",
    automargin=True,
    outsidetextfont=dict(size=12.5, color="#1e293b", family="Arial"),
    hovertemplate="<b>%{label}</b><extra></extra>",
    direction="clockwise",
    sort=True,
    rotation=90,
    domain=dict(x=[0,1], y=[0,1]),
))

fig_d1.update_layout(
    annotations=[dict(
        text=f"<b>{cnt_total}</b><br>工單總數",
        x=0.5, y=0.5, xref="paper", yref="paper",
        showarrow=False,
        font=dict(size=30, color="#0f172a", family="Arial Black"),
        align="center",
    )],
    showlegend=False,
    height=620,
    # margin 儘量小，讓 automargin 自動為 callout 標籤留空間
    margin=dict(t=16, b=16, l=16, r=16),
    paper_bgcolor="white",
    font=dict(family="Arial, sans-serif"),
)

# ── 右圖 D2~D4：3D 立體直條圖（前面板 + 右側面板模擬立體）─────────────────────
# 說明：barmode="overlay"，手動計算堆疊 base
# 每個類別 = 前面板（正常顏色）+ 右側面板（深色，模擬側面深度）
_BW  = 0.45   # 主柱寬度
_SW  = 0.12   # 側面板寬度
_n_v = len(_vens5)
_xf  = list(range(_n_v))                        # 前面板 x 座標（整數）
_xs  = [i + _BW/2 + _SW/2 for i in range(_n_v)] # 側面板 x 座標（右偏）

_c5cm = dict(zip(_C5L, _C5C))
_c5tc = {"已結案":"white","生產中":"white","齊料待生產":"white",
          "試產工單":"#1e293b","需處理":"white"}

fig_d4 = go.Figure()
_run_base = [0.0] * _n_v   # 手動記錄堆疊高度

for _s in _C5L:
    _vals = [float(_cross5.loc[v,_s]) if v in _cross5.index else 0.0 for v in _vens5]
    if sum(_vals) == 0:
        continue
    _c  = _c5cm[_s]
    _dc = _hex_darken(_c, 0.60)       # 深色 → 右側面板
    _lc = _hex_lighten(_c, 1.35)      # 淺色 → 頂部高光
    _tc = _c5tc.get(_s, "white")
    _base = _run_base.copy()

    # ① 前面板（正色，無內部文字—數字太擠改只顯示頂部總計）
    fig_d4.add_trace(go.Bar(
        name=_s,
        x=_xf, y=_vals, base=_base,
        width=_BW,
        marker=dict(color=_c, line=dict(color="rgba(255,255,255,0.55)", width=1.5)),
        hovertemplate=f"<b>{_s}</b>: %{{y:.0f}} 張<extra></extra>",
    ))

    # ② 右側面板（深色，無 legend，無 hover）
    fig_d4.add_trace(go.Bar(
        name="", x=_xs, y=_vals, base=_base,
        width=_SW,
        marker=dict(color=_dc, opacity=0.88, line=dict(width=0)),
        showlegend=False, hoverinfo="skip",
    ))

    # ③ 頂部高光薄板（淺色，增加厚度感）
    _top_h = [max(v * 0.04, 0.8) if v >= 1 else 0.0 for v in _vals]
    _top_x = [i + _SW / 2 for i in range(_n_v)]   # 覆蓋前 + 側
    fig_d4.add_trace(go.Bar(
        name="", x=_top_x, y=_top_h,
        base=[b + v for b, v in zip(_base, _vals)],
        width=_BW + _SW,
        marker=dict(color=_lc, opacity=0.85, line=dict(width=0)),
        showlegend=False, hoverinfo="skip",
    ))

    _run_base = [b + v for b, v in zip(_run_base, _vals)]

# 柱頂總計標籤
_ven_icons = {"廠內":"🏭","國智":"🏗️","唐佑":"🏢","其他":"🏬"}
for i, _ven in enumerate(_vens5):
    _tot = int(round(_run_base[i]))
    if _tot > 0:
        fig_d4.add_annotation(
            x=i, y=_run_base[i] + max(_run_base) * 0.04,
            text=f"<b>{_tot}</b>",
            showarrow=False, yanchor="bottom",
            font=dict(size=15, color="#0f172a", family="Arial Black"),
        )

_max_y = max(_run_base) if _run_base else 1
fig_d4.update_layout(
    barmode="overlay",
    height=620,
    margin=dict(t=30, b=100, l=30, r=30),
    paper_bgcolor="white",
    plot_bgcolor="rgba(241,245,249,0.85)",
    font=dict(family="Arial, sans-serif", size=13),
    legend=dict(
        orientation="h", x=0.5, y=-0.20, xanchor="center",
        font=dict(size=12.5, color="#374151"),
        bgcolor="rgba(255,255,255,0.95)",
        bordercolor="#e2e8f0", borderwidth=1,
        itemsizing="constant",
    ),
    xaxis=dict(
        tickmode="array",
        tickvals=_xf,
        ticktext=[f"{_ven_icons.get(v,'🏭')} {v}" for v in _vens5],
        tickfont=dict(size=14, color="#1e293b", family="Arial Black"),
        showgrid=False, zeroline=False,
        range=[-0.55, _n_v - 0.45 + _SW + 0.2],
    ),
    yaxis=dict(
        showgrid=True, gridcolor="#e2e8f0", gridwidth=1,
        zeroline=True, zerolinecolor="#cbd5e1",
        tickfont=dict(size=11, color="#64748b"),
        range=[0, _max_y * 1.16],
    ),
    bargap=0.0,
    bargroupgap=0.0,
)

# ── 兩欄佈局 ──────────────────────────────────────────────────────────────────
_cL, _cR = st.columns([1, 1.1])

with _cL:
    st.markdown(
        '<div class="ceo-card">'
        '<div class="ceo-card-title" style="color:#1d4ed8;">📅 D1 時間維度 ｜ 工單狀態總覽</div>',
        unsafe_allow_html=True)
    st.plotly_chart(fig_d1, use_container_width=True)
    st.markdown('</div>', unsafe_allow_html=True)

with _cR:
    st.markdown(
        '<div class="ceo-card">'
        '<div class="ceo-card-title" style="color:#15803d;">'
        '🗺️ D2~D4 空間 × 狀態 × 類型 分析（單位：工單數）</div>',
        unsafe_allow_html=True)
    st.plotly_chart(fig_d4, use_container_width=True)
    st.markdown('</div>', unsafe_allow_html=True)

# ── D5 績效 KPI 列 ────────────────────────────────────────────────────────────
def _kpi(icon, color, val, pct, label, bg, border):
    return (
        f'<div style="background:{bg};border:2px solid {border};border-radius:14px;'
        f'padding:16px 14px;text-align:center;flex:1;min-width:110px;">'
        f'<div style="font-size:1.9rem;line-height:1;">{icon}</div>'
        f'<div style="font-size:1.55rem;font-weight:900;color:{color};margin-top:6px;line-height:1.1;">'
        f'{pct:.1f}%</div>'
        f'<div style="font-size:0.72rem;color:#475569;margin-top:5px;font-weight:700;line-height:1.5;">'
        f'{label}</div>'
        f'</div>'
    )

_kpis = "".join([
    _kpi("✅","#16a34a", cnt_done,              cnt_done/             _tot_s*100, "完成率<br>已結案比例",   "#f0fdf4","#86efac"),
    _kpi("⚙️","#2563eb", cnt_wip+cnt_held,       (cnt_wip+cnt_held)/   _tot_s*100, "進行中<br>生產中工單",   "#eff6ff","#93c5fd"),
    _kpi("📦","#ea580c", cnt_ready,   cnt_ready/_tot_s*100,"齊料待生產<br>未開工",   "#fff7ed","#fdba74"),
    _kpi("🧪","#6b7280", cnt_trial,              cnt_trial/            _tot_s*100, "試產工單<br>試產比例",   "#f8fafc","#cbd5e1"),
    _kpi("⚠️","#dc2626", cnt_short+cnt_transfer, (cnt_short+cnt_transfer)/_tot_s*100,"需處理<br>缺料工單", "#fef2f2","#fca5a5"),
])

st.markdown(f"""
<div style="background:white;border-radius:16px;padding:18px 22px 16px;
     box-shadow:0 6px 28px rgba(0,0,0,0.10);border:1px solid #e2e8f0;">
  <div style="font-size:0.84rem;font-weight:800;color:#991b1b;margin-bottom:14px;letter-spacing:0.02em;">
    💰 D5 價值維度 ｜ 績效指標
  </div>
  <div style="display:flex;gap:12px;flex-wrap:wrap;">
    {_kpis}
  </div>
</div>
""", unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

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

    if "缺料" in str(wo_status) or wo_status in ("待扣帳", "待調撥"):
        detail_rows = df_sht[df_sht["製令編號"] == wo_no].copy()
        if not detail_rows.empty:
            # 取得此工單的生產方
            wo_full     = df[df["製令編號"] == wo_no]
            vendor_sel  = wo_full["生產方"].iloc[0] if not wo_full.empty else "廠內"

            banner_color = "#fff7ed" if "缺料" in str(wo_status) else "#fefce8"
            border_color = "#fb923c" if "缺料" in str(wo_status) else "#facc15"
            icon = "⚠️" if "缺料" in str(wo_status) else "🟡"
            wh_names = VENDOR_WH_MAP.get(vendor_sel, [])
            wh_hint  = f"（{' + '.join(wh_names)}）" if wh_names else ""
            st.markdown(f"""
            <div style="background:{banner_color};border:1.5px solid {border_color};border-radius:10px;
                        padding:12px 18px;margin:8px 0 4px;">
            <b style="color:#c2410c;">{icon} 欠料明細｜工單：{wo_no}
            ｜生產方：{vendor_sel} {wh_hint}</b>
            </div>""", unsafe_allow_html=True)

            detail_show_cols = [c for c in ["材料品號","品名","規格","欠料數量","現有庫存","逾期未入"] if c in detail_rows.columns]
            detail_display = detail_rows[detail_show_cols].reset_index(drop=True)

            # 數值欄轉換
            for nc in ["欠料數量", "現有庫存", "逾期未入"]:
                if nc in detail_display.columns:
                    detail_display[nc] = pd.to_numeric(detail_display[nc], errors="coerce").fillna(0)

            # 加入「製造倉庫存」欄
            # 委外：用 wo_supply 預計結存 - 欠料量 = 供應鏈在本工單前的可用量
            # 廠內：用 stock_by_wh 庫存可用量
            def get_prod_wh_stock(mat_no):
                mat_no = str(mat_no).strip()
                if vendor_sel != "廠內" and wo_supply:
                    supply = wo_supply.get((mat_no, wo_no))
                    if supply is not None:
                        # 預計結存 + 異動數量 = 本工單用料前的可用量
                        return supply[0] + supply[1]
                return get_vendor_stock(mat_no, vendor_sel, stock_by_wh)

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
