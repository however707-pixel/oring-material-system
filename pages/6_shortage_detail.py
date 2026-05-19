import streamlit as st
import pandas as pd
import io
import sys
import os
from datetime import datetime, date

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from utils.shared import inject_css, render_header, render_sidebar
from utils.i18n import t

# ── 初始化 ────────────────────────────────────────────────────────────────────
if "lang" not in st.session_state:
    st.session_state["lang"] = "zh"

st.set_page_config(page_title="區間工單缺料明細", page_icon="📊", layout="wide",
                   initial_sidebar_state="expanded")
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
    title="區間工單缺料明細",
    subtitle="Period Work Order Shortage Detail · Production Control · ORing Industrial Networking",
    badge="Production Management System",
)
render_sidebar()

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
.metric-chip {
    padding: 4px 12px; border-radius: 20px; font-size: 0.82rem; font-weight: 600;
    display: inline-block;
}
.chip-green  { background:#dcfce7; color:#15803d; }
.chip-red    { background:#fee2e2; color:#dc2626; }
.chip-yellow { background:#fef9c3; color:#b45309; }
.chip-blue   { background:#dbeafe; color:#1d4ed8; }
.chip-gray   { background:#f1f5f9; color:#64748b; }
</style>
""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════════
# 資料解析（與工單進度表相同邏輯）
# ═══════════════════════════════════════════════════════════════════════════════

@st.cache_data(show_spinner=False)
def parse_supply(file_bytes):
    try:
        df = pd.read_excel(io.BytesIO(file_bytes), header=0, engine="openpyxl", dtype=str)
    except Exception:
        df = pd.read_excel(io.BytesIO(file_bytes), header=0, dtype=str)

    cols = list(df.columns)
    IDX = {name: i for i, name in enumerate(cols)}

    def val(row, key):
        v = row.iloc[IDX[key]] if key in IDX else None
        return None if pd.isna(v) else str(v).strip()

    stocks = {}
    wh_map = {}
    bom_map = {}
    incoming_map = {}
    current_pno = None

    for _, row in df.iterrows():
        pno_raw = val(row, "品號")
        if pno_raw:
            current_pno = pno_raw
        if not current_pno:
            continue

        wh_code   = val(row, "庫別")
        wh_name   = val(row, "庫別名稱")
        date_val  = val(row, "日期")
        trans     = val(row, "異動別")
        qty_raw   = val(row, "異動數量")
        bal_raw   = val(row, "預計結存")
        src_order = val(row, "來源訂單")
        prod_name = val(row, "產品名稱")

        try:    qty = float(qty_raw) if qty_raw else 0.0
        except: qty = 0.0
        try:    balance = float(bal_raw) if bal_raw else 0.0
        except: balance = 0.0

        if wh_code and wh_name and wh_code != wh_name:
            wh_map[wh_code] = wh_name

        if date_val == "庫存可用量:":
            if wh_code and wh_code not in ("小計:", "合計:"):
                stocks.setdefault(current_pno, {})[wh_code] = qty

        elif trans == "預計領用":
            try:
                dt_str = pd.to_datetime(date_val).strftime("%Y/%m/%d")
            except Exception:
                dt_str = str(date_val)
            entry = {
                "品號":     current_pno,
                "需求數量": qty,
                "庫別代號": wh_code,
                "庫別名稱": wh_name,
                "結存":     balance,
                "來源訂單": src_order or "",
                "日期":     dt_str,
            }
            if prod_name:
                bom_map.setdefault(prod_name, []).append(entry)
            if src_order:
                bom_map.setdefault(f"__mo__{src_order}", []).append(entry)

        elif trans == "預計進貨":
            try:
                dt_str = pd.to_datetime(date_val).strftime("%Y/%m/%d")
            except Exception:
                dt_str = str(date_val)
            incoming_map.setdefault(current_pno, []).append({
                "日期": dt_str, "數量": qty,
                "庫別名稱": wh_name or wh_code or "",
            })

    return stocks, wh_map, bom_map, incoming_map


@st.cache_data(show_spinner=False)
def parse_wo(file_bytes):
    try:
        df = pd.read_excel(io.BytesIO(file_bytes), header=0, engine="openpyxl", dtype=str)
    except Exception:
        df = pd.read_excel(io.BytesIO(file_bytes), header=0, dtype=str)
    df.columns = [str(c).strip() for c in df.columns]
    df = df.fillna("")
    result = {}
    for _, row in df.iterrows():
        mo = str(row.get("製令編號", "")).strip()
        if mo:
            result[mo] = {k: str(v).strip() for k, v in row.items()}
    return result


@st.cache_data(show_spinner=False)
def parse_qc(file_bytes):
    try:
        df = pd.read_excel(io.BytesIO(file_bytes), header=0, engine="openpyxl", dtype=str)
    except Exception:
        df = pd.read_excel(io.BytesIO(file_bytes), header=0, dtype=str)
    df.columns = [str(c).strip() for c in df.columns]
    df = df.fillna("")
    result = {}
    for _, row in df.iterrows():
        pno = str(row.get("品號", "")).strip()
        status = str(row.get("檢驗狀態", "")).strip()
        if pno and status == "待驗":
            try:    qty = float(str(row.get("進貨數量", "0")))
            except: qty = 0.0
            result[pno] = result.get(pno, 0.0) + qty
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# 核心邏輯（與工單進度表相同）
# ═══════════════════════════════════════════════════════════════════════════════

def get_bom_for_product(product_pno, bom_map, wo_order_no="", mo_no="", all_order_nos=None):
    # 策略0：製令編號直接查找
    if mo_no:
        direct = bom_map.get(f"__mo__{mo_no}", [])
        if direct:
            return direct, False  # (entries, is_template)

    all_entries = []
    for key, entries in bom_map.items():
        if key.startswith("__mo__"):
            continue
        if product_pno in key or key in product_pno:
            all_entries.extend(entries)

    if not all_entries:
        return [], False

    # 策略1：訂單單號精準匹配
    if wo_order_no:
        filtered = [e for e in all_entries if e.get("來源訂單") == wo_order_no]
        if filtered:
            return filtered, False

    # 策略2：只有一個來源訂單群組
    src_orders = {e.get("來源訂單", "") for e in all_entries}
    if len(src_orders) == 1:
        return all_entries, False

    # 策略3：製令編號作為來源訂單
    if mo_no:
        filtered = [e for e in all_entries if e.get("來源訂單") == mo_no]
        if filtered:
            return filtered, False

    # 策略4：排除其他工單已認領的來源訂單
    if all_order_nos:
        claimed_src = {e.get("來源訂單", "") for e in all_entries
                       if e.get("來源訂單", "") in all_order_nos}
        if claimed_src:
            unclaimed = [e for e in all_entries if e.get("來源訂單", "") not in claimed_src]
            if unclaimed:
                return unclaimed, False
            # 全部被認領 → 取最早群組，結存取最小值（模板模式）
            first_src = sorted(claimed_src)[0]
            min_bal = {}
            for e in all_entries:
                pno = e["品號"]
                bal = e.get("結存")
                if bal is not None:
                    if pno not in min_bal or bal < min_bal[pno]:
                        min_bal[pno] = bal
            tmpl = [dict(e, 結存=min_bal.get(e["品號"], e.get("結存")))
                    for e in all_entries if e.get("來源訂單", "") == first_src]
            return tmpl, True  # is_template=True

    return all_entries, True


def analyze_bom(bom_entries, stocks, wh_map, qc_map, incoming_map, wo_wh_code,
                is_template=False):
    part_demand = {}
    for e in bom_entries:
        pno           = e["品號"]
        entry_wh_code = e.get("庫別代號") or wo_wh_code
        entry_wh_name = e.get("庫別名稱") or wh_map.get(entry_wh_code, entry_wh_code)
        if pno not in part_demand:
            part_demand[pno] = {"需求數量": 0.0, "庫別代號": entry_wh_code,
                                "庫別名稱": entry_wh_name, "結存": None}
        part_demand[pno]["需求數量"] += e["需求數量"]
        bal = e.get("結存")
        if bal is not None:
            prev = part_demand[pno]["結存"]
            part_demand[pno]["結存"] = bal if prev is None else min(prev, bal)

    rows = []
    for pno, info in part_demand.items():
        needed       = info["需求數量"]
        prod_wh_code = info["庫別代號"]
        prod_wh_name = info["庫別名稱"] or wh_map.get(prod_wh_code, prod_wh_code)
        pno_stocks   = stocks.get(pno, {})
        bal          = info["結存"]

        if is_template:
            total_stock = sum(pno_stocks.values()) if pno_stocks else 0.0
            prod_stock  = total_stock
            if total_stock >= needed:
                is_short, shortage_qty = False, 0.0
            else:
                is_short = True
                if bal is not None and bal < 0:
                    shortage_qty = min(needed, -bal)
                else:
                    shortage_qty = max(needed - total_stock, 0.0)
        elif bal is not None:
            prod_stock   = pno_stocks.get(prod_wh_code, 0.0)
            is_short     = bal < 0
            shortage_qty = min(needed, -bal) if is_short else 0.0
        else:
            prod_stock   = pno_stocks.get(prod_wh_code, 0.0)
            is_short     = prod_stock < needed
            shortage_qty = max(needed - prod_stock, 0.0) if is_short else 0.0

        other_wh = {} if is_template else {
            wh_map.get(k, k): v for k, v in pno_stocks.items()
            if k != prod_wh_code and v > 0
        }

        if is_short:
            qc_qty = qc_map.get(pno, 0.0)
            if qc_qty > 0:
                reason, detail = "⏳ 在IQC待驗", f"待驗 {int(qc_qty)} 件"
            elif other_wh:
                wh_str = "、".join(f"{k}({int(v)})" for k, v in other_wh.items())
                reason, detail = "📦 在其他倉庫", wh_str
            else:
                incoming = incoming_map.get(pno, [])
                if incoming:
                    nxt = sorted(incoming, key=lambda x: x["日期"])[0]
                    reason = "🚚 料未到（有在途）"
                    detail = f"預計 {nxt['日期']} 進 {int(nxt['數量'])} 件"
                else:
                    reason, detail = "❌ 料未到（無在途）", "尚無採購紀錄"
        else:
            reason, detail = "✅ 齊料", ""

        rows.append({
            "料號":      pno,
            "生產區庫別": prod_wh_name,
            "需求數量":   int(needed),
            "生產區庫存": int(prod_stock),
            "缺料數量":   int(shortage_qty),
            "狀態":      reason,
            "說明":      detail,
        })

    return rows


# ═══════════════════════════════════════════════════════════════════════════════
# UI
# ═══════════════════════════════════════════════════════════════════════════════

with st.sidebar:
    st.divider()
    st.markdown("### 📂 上傳資料檔案")
    f_supply = st.file_uploader("供需表（分倉）", type=["xlsx", "xls"], key="f_supply")
    f_wo     = st.file_uploader("工單表",         type=["xlsx", "xls"], key="f_wo")
    f_qc     = st.file_uploader("QC表",           type=["xlsx", "xls"], key="f_qc")

# ── 檔案檢查 ──────────────────────────────────────────────────────────────────
if not (f_supply and f_wo and f_qc):
    st.info("👈 請先在左側上傳三個 Excel 檔案：供需表、工單表、QC表")
    st.markdown("""
    | 檔案 | 用途 |
    |------|------|
    | **供需表（分倉）** | BOM 料號清單 + 各倉庫存量 |
    | **工單表** | 工單資訊、開工日、生產庫別、廠商 |
    | **QC表** | 料件是否在 IQC 待驗中 |
    """)
    st.stop()

# ── 載入資料 ──────────────────────────────────────────────────────────────────
with st.spinner("載入資料中，請稍候..."):
    stocks, wh_map, bom_map, incoming_map = parse_supply(f_supply.read())
    wo_dict = parse_wo(f_wo.read())
    qc_map  = parse_qc(f_qc.read())

st.success(f"資料已載入 ✓　工單筆數：{len(wo_dict):,}　供需料號：{len(stocks):,}　QC待驗：{len(qc_map):,} 項")

# ── 查詢條件 ──────────────────────────────────────────────────────────────────
st.divider()
st.markdown("### 🔍 查詢條件")

c1, c2, c3, c4 = st.columns([2, 2, 2, 1])
with c1:
    date_start = st.date_input("📅 開工日（起）", date(2026, 5, 1), format="YYYY/MM/DD")
with c2:
    date_end   = st.date_input("📅 開工日（迄）", date(2026, 5, 31), format="YYYY/MM/DD")
with c3:
    # 取得所有製令狀態選項
    all_statuses = sorted({v.get("製令狀態", "") for v in wo_dict.values() if v.get("製令狀態", "")})
    status_filter = st.multiselect("製令狀態篩選（不選=全部）", all_statuses)
with c4:
    st.markdown("<br>", unsafe_allow_html=True)
    run_btn = st.button("🚀 執行分析", type="primary", use_container_width=True)

if date_end < date_start:
    st.error("⚠️ 結束日不可早於起始日")
    st.stop()

if not run_btn:
    st.stop()

# ── 篩選工單 ──────────────────────────────────────────────────────────────────
filtered_wos = []
for mo, wo in wo_dict.items():
    open_raw = wo.get("開 工 日", "")
    try:
        open_dt = pd.to_datetime(open_raw).date()
    except Exception:
        continue
    if not (date_start <= open_dt <= date_end):
        continue
    if status_filter and wo.get("製令狀態", "") not in status_filter:
        continue
    filtered_wos.append((mo, wo))

if not filtered_wos:
    st.warning(f"所選區間（{date_start} ～ {date_end}）沒有符合條件的工單。")
    st.stop()

st.info(f"找到 **{len(filtered_wos)}** 張工單，開始分析 BOM 料況...")

# ── 批次分析 ──────────────────────────────────────────────────────────────────
all_order_nos = {v.get("訂單單號", "") for v in wo_dict.values()
                 if v.get("訂單單號", "").strip()}

all_rows = []
no_bom_wos = []

progress_bar = st.progress(0)
for idx, (mo_input, wo) in enumerate(filtered_wos):
    progress_bar.progress((idx + 1) / len(filtered_wos), text=f"分析中 {mo_input}...")

    product_pno  = wo.get("產品品號", "")
    product_name = wo.get("品          名", wo.get("品名", ""))
    wo_status    = wo.get("製令狀態", "")
    wo_qty       = wo.get("預計產量", "")
    wo_open_date = wo.get("開 工 日", "")
    wo_done_date = wo.get("完 工 日", "")
    wo_wh_name   = wo.get("生產庫別名稱", "")
    wo_wh_code   = wo.get("生產庫別", "")
    wo_factory   = wo.get("廠商名稱", "")
    wo_urgent    = wo.get("急料", "N")

    bom_entries, is_template = get_bom_for_product(
        product_pno, bom_map,
        wo_order_no=wo.get("訂單單號", ""),
        mo_no=mo_input,
        all_order_nos=all_order_nos,
    )

    if not bom_entries:
        no_bom_wos.append(mo_input)
        continue

    result_rows = analyze_bom(
        bom_entries, stocks, wh_map, qc_map, incoming_map, wo_wh_code,
        is_template=is_template
    )

    for r in result_rows:
        all_rows.append({
            "製令編號":  mo_input,
            "成品品號":  product_pno,
            "品名":      product_name,
            "開工日":    wo_open_date,
            "完工日":    wo_done_date,
            "預計產量":  wo_qty,
            "製令狀態":  wo_status,
            "廠商":      wo_factory or "廠內",
            "生產庫別":  wo_wh_name,
            "急料":      wo_urgent,
            **r,          # 料號, 生產區庫別, 需求數量, 生產區庫存, 缺料數量, 狀態, 說明
        })

progress_bar.empty()

if not all_rows:
    st.warning("所有工單均未在供需表中找到 BOM 資料。")
    st.stop()

df_all = pd.DataFrame(all_rows)

# ── 提示找不到 BOM 的工單 ────────────────────────────────────────────────────
if no_bom_wos:
    with st.expander(f"⚠️ {len(no_bom_wos)} 張工單未在供需表找到 BOM（已略過）", expanded=False):
        st.write(no_bom_wos)

# ── 匯總指標 ──────────────────────────────────────────────────────────────────
st.divider()
total_parts  = len(df_all)
total_wos    = df_all["製令編號"].nunique()
short_df     = df_all[~df_all["狀態"].str.startswith("✅")]
ok_cnt       = (df_all["狀態"].str.startswith("✅")).sum()
iqc_cnt      = (df_all["狀態"].str.startswith("⏳")).sum()
otherwh_cnt  = (df_all["狀態"].str.startswith("📦")).sum()
incoming_cnt = (df_all["狀態"].str.startswith("🚚")).sum()
noin_cnt     = (df_all["狀態"].str.startswith("❌")).sum()
short_wo_cnt = short_df["製令編號"].nunique()

m1, m2, m3, m4, m5, m6 = st.columns(6)
m1.metric("工單數", total_wos)
m2.metric("缺料工單數", short_wo_cnt)
m3.metric("✅ 齊料", ok_cnt)
m4.metric("⏳ 在IQC", iqc_cnt)
m5.metric("📦 在其他倉", otherwh_cnt)
m6.metric("❌ 料未到", noin_cnt + incoming_cnt,
          delta=f"有在途 {incoming_cnt}" if incoming_cnt else None,
          delta_color="off")

st.divider()

# ── 篩選控制 ──────────────────────────────────────────────────────────────────
fc1, fc2, fc3 = st.columns([2, 2, 3])
with fc1:
    view_opt = st.selectbox("顯示模式",
        ["全部料號", "僅缺料料號", "在IQC待驗", "在其他倉庫", "料未到（有在途）", "料未到（無在途）"])
with fc2:
    wo_filter = st.selectbox("篩選工單", ["全部"] + sorted(df_all["製令編號"].unique().tolist()))
with fc3:
    search_pno = st.text_input("搜尋料號", placeholder="輸入料號關鍵字")

df_show = df_all.copy()
if view_opt == "僅缺料料號":
    df_show = df_show[~df_show["狀態"].str.startswith("✅")]
elif view_opt == "在IQC待驗":
    df_show = df_show[df_show["狀態"].str.startswith("⏳")]
elif view_opt == "在其他倉庫":
    df_show = df_show[df_show["狀態"].str.startswith("📦")]
elif view_opt == "料未到（有在途）":
    df_show = df_show[df_show["狀態"].str.startswith("🚚")]
elif view_opt == "料未到（無在途）":
    df_show = df_show[df_show["狀態"].str.startswith("❌")]

if wo_filter != "全部":
    df_show = df_show[df_show["製令編號"] == wo_filter]
if search_pno:
    df_show = df_show[df_show["料號"].str.contains(search_pno, na=False)]

# ── 表格顯示 ──────────────────────────────────────────────────────────────────
def highlight_row(row):
    s = row["狀態"]
    if s.startswith("✅"):   bg = "background-color:#f0fdf4; color:#15803d;"
    elif s.startswith("⏳"): bg = "background-color:#fefce8; color:#b45309;"
    elif s.startswith("📦"): bg = "background-color:#eff6ff; color:#1d4ed8;"
    elif s.startswith("🚚"): bg = "background-color:#fff7ed; color:#c2410c;"
    else:                     bg = "background-color:#fff1f2; color:#dc2626;"
    return [bg] * len(row)

st.dataframe(
    df_show.style.apply(highlight_row, axis=1),
    use_container_width=True,
    height=600,
    column_config={
        "製令編號":  st.column_config.TextColumn("製令編號",  width=180),
        "成品品號":  st.column_config.TextColumn("成品品號",  width=200),
        "品名":      st.column_config.TextColumn("品名",      width=160),
        "開工日":    st.column_config.TextColumn("開工日",    width=100),
        "完工日":    st.column_config.TextColumn("完工日",    width=100),
        "預計產量":  st.column_config.TextColumn("預計產量",  width=80),
        "製令狀態":  st.column_config.TextColumn("製令狀態",  width=80),
        "廠商":      st.column_config.TextColumn("廠商",      width=100),
        "生產庫別":  st.column_config.TextColumn("生產庫別",  width=160),
        "急料":      st.column_config.TextColumn("急料",      width=60),
        "料號":      st.column_config.TextColumn("料號",      width=220),
        "生產區庫別":st.column_config.TextColumn("生產區庫別",width=140),
        "需求數量":  st.column_config.NumberColumn("需求數量", format="%d"),
        "生產區庫存":st.column_config.NumberColumn("生產區庫存",format="%d"),
        "缺料數量":  st.column_config.NumberColumn("缺料數量", format="%d"),
        "狀態":      st.column_config.TextColumn("狀態",      width=180),
        "說明":      st.column_config.TextColumn("說明",      width=240),
    }
)

st.caption(f"顯示 {len(df_show):,} 筆 / 共 {len(df_all):,} 筆")

# ── 匯出 ──────────────────────────────────────────────────────────────────────
buf = io.BytesIO()
df_all.to_excel(buf, index=False, engine="openpyxl")
buf.seek(0)
st.download_button(
    label="⬇️ 匯出完整缺料明細（Excel）",
    data=buf,
    file_name=f"區間缺料明細_{date_start}~{date_end}_{datetime.today().strftime('%Y%m%d')}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)
