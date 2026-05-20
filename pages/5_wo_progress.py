import streamlit as st
import pandas as pd
import io
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from utils.shared import inject_css, render_header, render_sidebar
from utils.i18n import t

# ── 初始化 ────────────────────────────────────────────────────────────────────
if "lang" not in st.session_state:
    st.session_state["lang"] = "zh"

st.set_page_config(page_title="工單進度表", page_icon="📋", layout="wide", initial_sidebar_state="expanded")
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
    title="工單進度表",
    subtitle="Work Order BOM Material Status · Production Control · ORing Industrial Networking",
    badge="Production Management System",
)
render_sidebar()

# ── CSS 補充 ──────────────────────────────────────────────────────────────────
st.markdown("""
<style>
.wo-card {
    padding: 16px 22px; border-radius: 12px; background: #fff;
    border: 1px solid #e2e8f0; border-left: 4px solid #15803d;
    margin-bottom: 18px;
    box-shadow: 0 4px 20px rgba(21,128,61,0.08), 0 1px 4px rgba(0,0,0,0.04);
}
.wo-card h3 { color: #1e293b; margin: 0 0 8px 0; font-size: 1rem; }
.metric-row { display: flex; gap: 16px; flex-wrap: wrap; margin-top: 10px; }
.metric-chip {
    padding: 4px 12px; border-radius: 20px; font-size: 0.82rem; font-weight: 600;
}
.chip-green  { background:#dcfce7; color:#15803d; }
.chip-red    { background:#fee2e2; color:#dc2626; }
.chip-yellow { background:#fef9c3; color:#b45309; }
.chip-blue   { background:#dbeafe; color:#1d4ed8; }
.chip-gray   { background:#f1f5f9; color:#64748b; }
</style>
""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════════
# 資料解析函數
# ═══════════════════════════════════════════════════════════════════════════════

@st.cache_data(show_spinner=False)
def parse_supply(file_bytes):
    """
    解析供需表。
    bom_map 結構：{product_pno: [{品號, 需求數量, 庫別代號, 庫別名稱, 結存, 來源訂單, 日期}]}
    stocks   結構：{pno: {wh_code: qty}}
    wh_map   結構：{wh_code: wh_name}
    incoming_map：{pno: [{日期, 數量, 庫別名稱}]}
    """
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

        # 庫別代號→名稱對應
        if wh_code and wh_name and wh_code != wh_name:
            wh_map[wh_code] = wh_name

        # 庫存可用量（期初庫存）
        if date_val == "庫存可用量:":
            if wh_code and wh_code not in ("小計:", "合計:"):
                stocks.setdefault(current_pno, {})[wh_code] = qty

        # 預計領用（BOM 需求）
        elif trans == "預計領用":
            # 解析日期
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
                # 以來源訂單為鍵另存（供製令編號直接查找，不依賴產品名稱欄）
                bom_map.setdefault(f"__mo__{src_order}", []).append(entry)

        # 預計進貨
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
    """解析工單表：回傳 dict {製令編號: row_dict}"""
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
    """解析 QC 表：回傳 {品號: 待驗數量}"""
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
            qty_str = str(row.get("進貨數量", "0"))
            try:
                qty = float(qty_str)
            except Exception:
                qty = 0.0
            result[pno] = result.get(pno, 0.0) + qty
    return result


@st.cache_data(show_spinner=False)
def parse_transfer(file_bytes):
    """解析調撥表：回傳 {品號: [{日期, 轉出, 轉入, 數量}]}"""
    try:
        df = pd.read_excel(io.BytesIO(file_bytes), header=0, engine="openpyxl", dtype=str)
    except Exception:
        df = pd.read_excel(io.BytesIO(file_bytes), header=0, dtype=str)
    df.columns = [str(c).strip() for c in df.columns]
    df = df.fillna("")
    result = {}
    for _, row in df.iterrows():
        pno = str(row.get("品號", "")).strip()
        if not pno:
            continue
        if pno not in result:
            result[pno] = []
        result[pno].append({
            "日期": str(row.get("轉撥日期", "")),
            "轉出": str(row.get("轉出庫別名稱", "")),
            "轉入": str(row.get("轉入庫別名稱", "")),
            "數量": str(row.get("轉撥數量", "")),
        })
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# 主邏輯
# ═══════════════════════════════════════════════════════════════════════════════

def get_bom_for_product(product_pno, bom_map, wo_order_no="", wo_open_date="",
                        mo_no="", all_order_nos=None):
    """
    從 bom_map 找出對應成品品號的 BOM 料號。

    匹配策略（依優先順序）：
    1. 來源訂單 = wo_order_no（工單有訂單單號時精準匹配）
    2. 僅有一個來源訂單群組時，直接回傳（該群組即為本工單的需求）
    3. 來源訂單 = mo_no（製令編號直接出現在供需表來源訂單欄）
    4. 排除其他工單已認領的來源訂單，取剩餘未認領的群組
    5. 多個群組仍無法區分時，顯示全部（並讓用戶知道）
    """
    # 策略0：以製令編號直接查找（供需表有來源訂單=製令編號的行，不依賴產品名稱欄）
    if mo_no:
        direct = bom_map.get(f"__mo__{mo_no}", [])
        if direct:
            return direct

    all_entries = []
    for key, entries in bom_map.items():
        if key.startswith("__mo__"):
            continue  # 跳過製令編號索引，只用產品名稱索引
        if product_pno in key or key in product_pno:
            all_entries.extend(entries)

    if not all_entries:
        return []

    # 策略1：精準以訂單單號匹配來源訂單
    if wo_order_no:
        filtered = [e for e in all_entries if e.get("來源訂單") == wo_order_no]
        if filtered:
            return filtered

    # 策略2：只有一個來源訂單群組，直接用
    src_orders = {e.get("來源訂單", "") for e in all_entries}
    if len(src_orders) == 1:
        return all_entries

    # 策略3：製令編號直接作為來源訂單
    if mo_no:
        filtered = [e for e in all_entries if e.get("來源訂單") == mo_no]
        if filtered:
            return filtered

    # 策略4：排除已被其他工單（含訂單單號）認領的來源訂單，取剩餘群組
    if all_order_nos:
        claimed_src = {e.get("來源訂單", "") for e in all_entries
                       if e.get("來源訂單", "") in all_order_nos}
        if claimed_src:
            unclaimed = [e for e in all_entries if e.get("來源訂單", "") not in claimed_src]
            if unclaimed:
                return unclaimed
            # 全部被認領 → 需求量取最早群組，結存取所有群組最小值（最保守判斷）
            first_src = sorted(claimed_src)[0]
            min_bal = {}
            for e in all_entries:
                pno = e["品號"]
                bal = e.get("結存")
                if bal is not None:
                    if pno not in min_bal or bal < min_bal[pno]:
                        min_bal[pno] = bal
            return [dict(e, 結存=min_bal.get(e["品號"], e.get("結存")))
                    for e in all_entries if e.get("來源訂單", "") == first_src]

    # 策略5：無法判斷，回傳全部（可能含多工單需求，數量偏高）
    return all_entries


def analyze_bom(bom_entries, stocks, wh_map, qc_map, incoming_map, wo_wh_code,
                is_template=False):
    """
    對每個 BOM 料號計算可用性與缺料原因。

    一般模式（工單在供需表中有自己的需求行）：
    - 以「結存」為核心：結存 >= 0 → 齊料，結存 < 0 → 缺料。

    模板模式（is_template=True，工單不在供需表，以他工單 BOM 作為參考）：
    - 結存來自其他工單的供需計劃，不適用於本工單，改用「期初庫存合計」判斷。
    - 期初庫存合計 = 該料號所有倉別的庫存可用量加總。
    """
    part_demand = {}
    for e in bom_entries:
        pno           = e["品號"]
        entry_wh_code = e.get("庫別代號") or wo_wh_code
        entry_wh_name = e.get("庫別名稱") or wh_map.get(entry_wh_code, entry_wh_code)
        if pno not in part_demand:
            part_demand[pno] = {
                "需求數量": 0.0,
                "庫別代號": entry_wh_code,
                "庫別名稱": entry_wh_name,
                "結存":     None,   # 最後一筆結存（代表扣完後餘量）
            }
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
            # 模板模式：先以期初庫存合計判斷是否足夠
            total_stock = sum(pno_stocks.values()) if pno_stocks else 0.0
            prod_stock  = total_stock
            if total_stock >= needed:
                # 庫存合計足夠 → 齊料（不管結存，其他需求消耗的是其他工單的份）
                is_short     = False
                shortage_qty = 0.0
            else:
                # 庫存不足 → 以結存確認實際缺料量（結存已反映期初庫存被前段需求消耗後的餘量）
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

        # 其他倉庫存（排除生產區，用於缺料原因判斷）
        # 模板模式下不判斷「在其他倉庫」：期初庫存在其他倉可能已被計劃消耗，不代表可用
        other_wh = {} if is_template else {
            wh_map.get(k, k): v for k, v in pno_stocks.items()
            if k != prod_wh_code and v > 0
        }

        reason = reason_detail = ""
        if is_short:
            qc_qty = qc_map.get(pno, 0.0)
            if qc_qty > 0:
                reason        = "⏳ 在IQC待驗"
                reason_detail = f"待驗 {int(qc_qty)} 件"
            elif other_wh:
                wh_str        = "、".join(f"{k}({int(v)})" for k, v in other_wh.items())
                reason        = "📦 在其他倉庫"
                reason_detail = wh_str
            else:
                incoming = incoming_map.get(pno, [])
                if incoming:
                    next_in       = sorted(incoming, key=lambda x: x["日期"])[0]
                    reason        = "🚚 料未到（有在途）"
                    reason_detail = f"預計 {next_in['日期']} 進 {int(next_in['數量'])} 件"
                else:
                    reason        = "❌ 料未到（無在途）"
                    reason_detail = "尚無採購紀錄"
        else:
            reason = "✅ 齊料"

        rows.append({
            "品號":      pno,
            "生產區庫別": prod_wh_name,
            "需求數量":   int(needed),
            "生產區庫存": int(prod_stock),
            "缺料數量":   int(shortage_qty),
            "狀態":      reason,
            "說明":      reason_detail,
        })

    return rows


# ═══════════════════════════════════════════════════════════════════════════════
# UI
# ═══════════════════════════════════════════════════════════════════════════════

with st.sidebar:
    st.divider()
    st.markdown("### 📂 上傳資料檔案")
    f_supply   = st.file_uploader("供需表（分倉）", type=["xlsx", "xls"], key="f_supply")
    f_wo       = st.file_uploader("工單表",         type=["xlsx", "xls"], key="f_wo")
    f_qc       = st.file_uploader("QC表",           type=["xlsx", "xls"], key="f_qc")
    f_transfer = st.file_uploader("調撥表",         type=["xlsx", "xls"], key="f_transfer")

# ── 主區域 ────────────────────────────────────────────────────────────────────
all_uploaded = f_supply and f_wo and f_qc and f_transfer

if not all_uploaded:
    st.info("👈 請先在左側上傳四個 Excel 檔案：供需表、工單表、QC表、調撥表")
    st.markdown("""
    <div style="background:#f0fdf4;border:1.5px dashed #86efac;border-radius:12px;padding:20px 24px;margin-top:16px;">
    <b style="color:#15803d;font-size:1rem;">📋 操作步驟</b>
    <ol style="color:#374151;margin-top:10px;line-height:2.2;">
      <li>ERP → 供需管理 → <b>供需表（分倉）</b> → 匯出 Excel，上傳至左側<br>
          <span style="color:#6b7280;font-size:0.85rem;">↳ 包含 BOM 料號、各倉庫存量、預計結存</span></li>
      <li>ERP → 製令/託外管理系統 → <b>工單表（生產進度表）</b> → 匯出 Excel，上傳至左側<br>
          <span style="color:#6b7280;font-size:0.85rem;">↳ 包含製令編號、生產庫別、廠商名稱</span></li>
      <li>ERP → 品管系統 → <b>QC 待驗表</b> → 匯出 Excel，上傳至左側<br>
          <span style="color:#6b7280;font-size:0.85rem;">↳ 用於識別「IQC 檢驗中」缺料原因</span></li>
      <li>人工整理的 <b>加工廠互調料彙整表</b> → 上傳至左側（調撥表）</li>
      <li>在主畫面輸入<b>製令編號</b>，點選「查詢」即可查看該工單 BOM 料況</li>
    </ol>
    <br>
    <b style="color:#15803d;">🎯 分類邏輯</b>
    <table style="margin-top:8px;width:100%;border-collapse:collapse;font-size:0.88rem;">
      <tr style="background:#dcfce7;"><td style="padding:5px 10px;">✅ 充足</td><td style="padding:5px 10px;">生產區庫存 ≥ 需求量，無缺料疑慮</td></tr>
      <tr><td style="padding:5px 10px;">🟡 可調撥</td><td style="padding:5px 10px;">生產區不足，但其他倉有料可轉撥</td></tr>
      <tr style="background:#dcfce7;"><td style="padding:5px 10px;">⚠️ 缺料</td><td style="padding:5px 10px;">全公司庫存不足需求量，需採購或協調</td></tr>
      <tr><td style="padding:5px 10px;">🔬 IQC 待驗</td><td style="padding:5px 10px;">料在品管檢驗中，尚不可領用</td></tr>
      <tr style="background:#dcfce7;"><td style="padding:5px 10px;">🚚 在途</td><td style="padding:5px 10px;">採購訂單尚未到貨，預計近期入庫</td></tr>
    </table>
    </div>
    """, unsafe_allow_html=True)
    st.stop()

# ── 載入資料 ──────────────────────────────────────────────────────────────────
with st.spinner("載入資料中，請稍候..."):
    stocks, wh_map, bom_map, incoming_map = parse_supply(f_supply.read())
    wo_dict = parse_wo(f_wo.read())
    qc_map  = parse_qc(f_qc.read())
    _       = parse_transfer(f_transfer.read())   # 保留供未來擴充

st.success(f"資料已載入 ✓　工單筆數：{len(wo_dict):,}　供需料號：{len(stocks):,}　QC待驗：{len(qc_map):,} 項")

# ── 工單查詢 ──────────────────────────────────────────────────────────────────
st.divider()
col_input, col_btn = st.columns([3, 1])
with col_input:
    mo_input = st.text_input("🔍 輸入工單號（製令編號）", placeholder="例如：5145-20260402006",
                              label_visibility="visible")
with col_btn:
    st.markdown("<br>", unsafe_allow_html=True)
    search = st.button("查詢", type="primary", use_container_width=True)

if not mo_input:
    st.stop()

mo_input = mo_input.strip()
wo = wo_dict.get(mo_input)
if not wo:
    st.error(f"找不到工單：{mo_input}　請確認製令編號是否正確。")
    st.stop()

# ── 工單資訊卡 ────────────────────────────────────────────────────────────────
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

status_chip = {
    "未生產": '<span class="metric-chip chip-gray">未生產</span>',
    "生產中": '<span class="metric-chip chip-blue">生產中</span>',
    "已領料": '<span class="metric-chip chip-yellow">已領料</span>',
    "完工":   '<span class="metric-chip chip-green">完工</span>',
}.get(wo_status, f'<span class="metric-chip chip-gray">{wo_status}</span>')

urgent_chip = '<span class="metric-chip chip-red">🚨 急料</span>' if wo_urgent == "Y" else ""

st.markdown(f"""
<div class="wo-card">
<h3>📋 工單資訊　<code>{mo_input}</code></h3>
<div><b>成品品號：</b>{product_pno}</div>
<div><b>品名：</b>{product_name}</div>
<div class="metric-row">
    {status_chip}
    {urgent_chip}
    <span class="metric-chip chip-gray">數量：{wo_qty}</span>
    <span class="metric-chip chip-gray">開工：{wo_open_date}</span>
    <span class="metric-chip chip-gray">完工：{wo_done_date}</span>
    <span class="metric-chip chip-blue">生產庫別：{wo_wh_name}</span>
    <span class="metric-chip chip-green">廠商：{wo_factory or '廠內'}</span>
</div>
</div>
""", unsafe_allow_html=True)

# ── 取得 BOM 料號 ──────────────────────────────────────────────────────────────
# 所有工單中有訂單單號的集合，用於排除已被其他工單認領的來源訂單
all_order_nos = {v.get("訂單單號", "") for v in wo_dict.values()
                 if v.get("訂單單號", "").strip()}

bom_entries = get_bom_for_product(
    product_pno, bom_map,
    wo_order_no=wo.get("訂單單號", ""),
    wo_open_date=wo.get("開 工 日", ""),
    mo_no=mo_input,
    all_order_nos=all_order_nos,
)

# ── 診斷 expander（幫助確認來源訂單匹配狀況）─────────────────────────────────
with st.expander("🔍 診斷資訊（來源訂單匹配）", expanded=not bool(bom_entries)):
    st.markdown(f"**工單訂單單號：** `{wo.get('訂單單號','（無）')}`")
    st.markdown(f"**工單製令編號：** `{mo_input}`")
    # 找出供需表中此成品的所有來源訂單
    _diag_all = []
    for k, entries in bom_map.items():
        if product_pno in k or k in product_pno:
            _diag_all.extend(entries)
    _diag_src = {}
    for e in _diag_all:
        s = e.get("來源訂單", "（空）") or "（空）"
        _diag_src.setdefault(s, []).append(e.get("品號", ""))
    st.markdown(f"**供需表中找到 {len(_diag_src)} 個來源訂單群組：**")
    # 反查：哪個工單的訂單單號 = 哪個來源訂單
    order_to_wo = {}
    for mo, wrow in wo_dict.items():
        ono = wrow.get("訂單單號", "").strip()
        if ono:
            order_to_wo.setdefault(ono, []).append(mo)
    rows_diag = []
    for src, parts in _diag_src.items():
        claimed_by = "、".join(order_to_wo.get(src, [])) or "—"
        rows_diag.append({"來源訂單": src, "料號數": len(parts), "被哪張工單認領": claimed_by})
    st.dataframe(pd.DataFrame(rows_diag), use_container_width=True, hide_index=True)
    st.markdown(f"**本次回傳 BOM 條目數：** {len(bom_entries)}")

if not bom_entries:
    _any_in_bom = any(product_pno in k or k in product_pno for k in bom_map)
    if _any_in_bom:
        st.warning(
            f"⚠️ 供需表中有成品品號「{product_pno}」的資料，"
            "但其需求行（預計領用）全部對應到其他工單的訂單單號，"
            "本工單的需求尚未展入供需表中，或供需表版本不含此工單。"
        )
    else:
        st.warning(
            f"在供需表中找不到成品品號「{product_pno}」的 BOM 料號。\n\n"
            "可能原因：供需表未含此工單的需求展開，或品號格式不符。"
        )
    st.stop()

# 若回傳的是模板群組（所有來源訂單都屬於其他工單），顯示提示
_entry_srcs = {e.get("來源訂單", "") for e in bom_entries if e.get("來源訂單", "")}
_is_template = bool(_entry_srcs) and _entry_srcs <= all_order_nos
if _is_template:
    st.info(
        "ℹ️ 此工單在供需表中無獨立需求行（可能為庫存補貨單或供需表版本未含此單），"
        "以下 BOM 結構取自同款成品的參考群組，**庫存比較以期初庫存為基準，僅供參考**。"
    )


# ── 分析 BOM ──────────────────────────────────────────────────────────────────
with st.spinner("分析料況中..."):
    result_rows = analyze_bom(bom_entries, stocks, wh_map, qc_map, incoming_map, wo_wh_code,
                              is_template=_is_template)

df_result = pd.DataFrame(result_rows)

# ── 匯總指標 ──────────────────────────────────────────────────────────────────
total = len(df_result)
ok_cnt     = (df_result["狀態"].str.startswith("✅")).sum()
short_cnt  = total - ok_cnt
iqc_cnt    = (df_result["狀態"].str.startswith("⏳")).sum()
otherwh_cnt= (df_result["狀態"].str.startswith("📦")).sum()
incoming_cnt=(df_result["狀態"].str.startswith("🚚")).sum()
noincoming_cnt=(df_result["狀態"].str.startswith("❌")).sum()

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("BOM 料號總數", total)
c2.metric("✅ 齊料", ok_cnt,  delta=None)
c3.metric("⏳ 在IQC", iqc_cnt)
c4.metric("📦 在其他倉", otherwh_cnt)
c5.metric("❌ 料未到", noincoming_cnt + incoming_cnt,
          delta=f"有在途 {incoming_cnt}" if incoming_cnt else None,
          delta_color="off")

st.divider()

# ── 篩選 ──────────────────────────────────────────────────────────────────────
col_filter, col_search = st.columns([2, 3])
with col_filter:
    filter_opt = st.selectbox("篩選狀態", ["全部", "僅缺料", "齊料", "在IQC待驗", "在其他倉庫", "料未到（有在途）", "料未到（無在途）"])
with col_search:
    search_pno = st.text_input("搜尋品號", placeholder="輸入料號關鍵字")

df_show = df_result.copy()
if filter_opt == "僅缺料":
    df_show = df_show[~df_show["狀態"].str.startswith("✅")]
elif filter_opt == "齊料":
    df_show = df_show[df_show["狀態"].str.startswith("✅")]
elif filter_opt == "在IQC待驗":
    df_show = df_show[df_show["狀態"].str.startswith("⏳")]
elif filter_opt == "在其他倉庫":
    df_show = df_show[df_show["狀態"].str.startswith("📦")]
elif filter_opt == "料未到（有在途）":
    df_show = df_show[df_show["狀態"].str.startswith("🚚")]
elif filter_opt == "料未到（無在途）":
    df_show = df_show[df_show["狀態"].str.startswith("❌")]

if search_pno:
    df_show = df_show[df_show["品號"].str.contains(search_pno, na=False)]

# ── 顯示表格 ──────────────────────────────────────────────────────────────────
def highlight_row(row):
    s = row["狀態"]
    if s.startswith("✅"):
        bg = "background-color: #f0fdf4; color: #15803d;"
    elif s.startswith("⏳"):
        bg = "background-color: #fefce8; color: #b45309;"
    elif s.startswith("📦"):
        bg = "background-color: #eff6ff; color: #1d4ed8;"
    elif s.startswith("🚚"):
        bg = "background-color: #fff7ed; color: #c2410c;"
    else:
        bg = "background-color: #fff1f2; color: #dc2626;"
    return [bg] * len(row)

st.dataframe(
    df_show.style.apply(highlight_row, axis=1),
    use_container_width=True,
    height=550,
    column_config={
        "品號":     st.column_config.TextColumn("品號", width=260),
        "生產區庫別": st.column_config.TextColumn("生產區庫別", width=160),
        "需求數量": st.column_config.NumberColumn("需求數量", format="%d"),
        "生產區庫存": st.column_config.NumberColumn("生產區庫存", format="%d"),
        "缺料數量": st.column_config.NumberColumn("缺料數量", format="%d"),
        "狀態":     st.column_config.TextColumn("狀態", width=180),
        "說明":     st.column_config.TextColumn("說明", width=260),
    }
)

# ── 匯出 ──────────────────────────────────────────────────────────────────────
buf = io.BytesIO()
df_result.to_excel(buf, index=False, engine="openpyxl")
buf.seek(0)
st.download_button(
    label="⬇️ 匯出完整料況報告（Excel）",
    data=buf,
    file_name=f"料況_{mo_input}_{datetime.today().strftime('%Y%m%d')}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)
