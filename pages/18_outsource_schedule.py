import streamlit as st
import pandas as pd
import io
import sys
import os
from datetime import datetime, date

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from utils.shared import inject_css, render_header, render_sidebar, render_sd_loader, read_source

st.set_page_config(page_title="委外工單排程", page_icon="🏭", layout="wide",
                   initial_sidebar_state="expanded")
inject_css()

render_header(
    title="委外工單排程",
    subtitle="Outsourcing Work Order Scheduling · Production Control · ORing Industrial Networking",
    badge="Production Management System",
)
render_sidebar()

# ── 委外單別對照表（製令編號前4碼）────────────────────────────────────────────
OUTSOURCE_TYPE_MAP = {
    '5143': '託外打樣製令',
    '5144': '託外試產製令',
    '5145': '託外量產製令',
    '5220': '託外重工製令',
    'MO01': '熱銷備庫製令（託外）',
}

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

with st.expander("📖 操作說明　－　點此展開", expanded=False):
    st.markdown("""
<div style="line-height:2; font-size:0.93rem; color:#1e293b;">

**Step 1** — 左側上傳鼎新 ERP 匯出的 **製令明細表**（需含「加工廠商」「廠商名稱」「預計開工」欄位）

**Step 2** — 供需表會自動從 NAS 載入（無需手動上傳），用於取得目前庫存與用料需求

**Step 3** — 系統自動篩選 `5143 / 5144 / 5145 / 5220 / MO01` 開頭的委外工單，並依加工廠商分組

**Step 4** — 查看每張委外工單在「預計開工日」是否能取得足夠物料

</div>
""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════════
# 供需表解析（與「區間工單缺料明細」相同邏輯）
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
        src_order = val(row, "備註")  # 「備註」欄存放的就是製令編號，是 BOM 對應工單的真正鍵
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
def parse_wo_detail(file_bytes):
    """解析鼎新 ERP「製令明細表」：自動定位表頭列（含『製令編號』），
    篩出委外單別，回傳整理後的 DataFrame。"""
    raw = pd.read_excel(io.BytesIO(file_bytes), header=None, engine="openpyxl", dtype=str)

    header_row = None
    for i in range(min(20, len(raw))):
        if raw.iloc[i].astype(str).str.strip().eq("製令編號").any():
            header_row = i
            break
    if header_row is None:
        return pd.DataFrame()

    data = raw.iloc[header_row + 1:].copy()
    data.columns = [str(c).strip() for c in raw.iloc[header_row]]
    data = data.reset_index(drop=True)

    if "製令編號" not in data.columns:
        return pd.DataFrame()

    data["製令編號"] = data["製令編號"].astype(str).str.strip()
    data = data[data["製令編號"].notna() & (data["製令編號"] != "") & (data["製令編號"] != "nan")]
    data = data[~data["製令編號"].str.contains("合計", na=False)]

    data["單別"] = data["製令編號"].str.split("-").str[0].str.upper()
    data = data[data["單別"].isin(OUTSOURCE_TYPE_MAP.keys())].copy()
    data["單別名稱"] = data["單別"].map(OUTSOURCE_TYPE_MAP)

    for col in ["預計產量", "已生產量", "已領套數", "未生產量"]:
        if col in data.columns:
            data[col] = pd.to_numeric(data[col], errors="coerce").fillna(0).astype(int)

    for col in ["預計開工", "預計完工"]:
        if col in data.columns:
            data[col] = pd.to_datetime(data[col], errors="coerce")

    data["廠商名稱"] = data.get("廠商名稱", "").fillna("").astype(str).str.strip()
    data["廠商名稱"] = data["廠商名稱"].replace("", "（未指定）")
    data["加工廠商"] = data.get("加工廠商", "").fillna("").astype(str).str.strip()

    return data.reset_index(drop=True)


# ═══════════════════════════════════════════════════════════════════════════════
# BOM 比對邏輯（與「區間工單缺料明細」相同）
# ═══════════════════════════════════════════════════════════════════════════════

def get_bom_for_product(product_pno, bom_map, mo_no="", all_order_nos=None):
    if mo_no:
        direct = bom_map.get(f"__mo__{mo_no}", [])
        if direct:
            return direct, False

    all_entries = []
    for key, entries in bom_map.items():
        if key.startswith("__mo__"):
            continue
        if product_pno in key or key in product_pno:
            all_entries.extend(entries)

    if not all_entries:
        return [], False

    src_orders = {e.get("來源訂單", "") for e in all_entries}
    if len(src_orders) == 1:
        return all_entries, False

    if mo_no:
        filtered = [e for e in all_entries if e.get("來源訂單") == mo_no]
        if filtered:
            return filtered, False

    if all_order_nos:
        claimed_src = {e.get("來源訂單", "") for e in all_entries
                       if e.get("來源訂單", "") in all_order_nos}
        if claimed_src:
            unclaimed = [e for e in all_entries if e.get("來源訂單", "") not in claimed_src]
            if unclaimed:
                return unclaimed, False
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
            return tmpl, True

    return all_entries, True


def build_vendor_wh_candidates(stocks):
    """掃供需表所有庫別，找出『XX代工倉』，回傳 [(庫別代號, [廠商短名,...]), ...]。"""
    all_codes = set()
    for pno_stocks in stocks.values():
        all_codes.update(pno_stocks.keys())
    candidates = []
    for code in all_codes:
        if code.endswith("代工倉"):
            names = [n for n in code[:-len("代工倉")].split("/") if n]
            if names:
                candidates.append((code, names))
    return candidates


def match_vendor_wh_code(vendor_name, candidates):
    """依『廠商名稱』比對出對應的代工倉庫別代號。回傳 (庫別代號 or None, 是否為共用倉)。"""
    for code, names in candidates:
        if any(n in vendor_name for n in names):
            return code, len(names) > 1
    return None, False


def analyze_bom(bom_entries, stocks, wh_map, incoming_map, is_template=False,
                 vendor_wh_code=None, vendor_shared=False):
    part_demand = {}
    for e in bom_entries:
        pno = e["品號"]
        entry_wh_code = e.get("庫別代號")
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
        pno_stocks   = stocks.get(pno, {})
        bal          = info["結存"]
        cur_stock    = sum(pno_stocks.values()) if pno_stocks else 0.0
        vendor_stock = pno_stocks.get(vendor_wh_code, 0.0) if vendor_wh_code else 0.0
        other_stock  = cur_stock - vendor_stock

        if is_template:
            if cur_stock >= needed:
                is_short, shortage_qty = False, 0.0
            else:
                is_short = True
                if bal is not None and bal < 0:
                    shortage_qty = min(needed, -bal)
                else:
                    shortage_qty = max(needed - cur_stock, 0.0)
        elif bal is not None:
            is_short     = bal < 0
            shortage_qty = min(needed, -bal) if is_short else 0.0
        else:
            is_short     = cur_stock < needed
            shortage_qty = max(needed - cur_stock, 0.0) if is_short else 0.0

        if is_short:
            incoming = incoming_map.get(pno, [])
            if incoming:
                nxt = sorted(incoming, key=lambda x: x["日期"])[0]
                reason = "🚚 料未到（有在途）"
                detail = f"預計 {nxt['日期']} 進 {int(nxt['數量'])} 件"
            else:
                reason, detail = "❌ 料未到（無在途）", "尚無採購紀錄"
        else:
            reason, detail = "✅ 齊料", ""

        vendor_stock_disp = f"{int(vendor_stock)}（共用倉）" if vendor_shared else int(vendor_stock)

        rows.append({
            "料號":       pno,
            "需求數量":   int(needed),
            "目前庫存":   int(cur_stock),
            "委外廠庫存": vendor_stock_disp,
            "不含委外廠庫存": int(other_stock),
            "缺料數量":   int(shortage_qty),
            "狀態":       reason,
            "說明":       detail,
        })

    return rows


# ═══════════════════════════════════════════════════════════════════════════════
# UI
# ═══════════════════════════════════════════════════════════════════════════════

with st.sidebar:
    st.divider()
    st.markdown("### 📂 上傳資料檔案")
    f_supply = render_sd_loader(key="outsource_schedule", label="供需表（分倉）")
    f_wo     = st.file_uploader("製令明細表", type=["xlsx", "xls"], key="f_wo_outsource")

if not (f_supply and f_wo):
    st.info("👈 請先在左側上傳「製令明細表」，並確認供需表已自動載入")
    st.stop()

with st.spinner("解析資料中，請稍候..."):
    stocks, wh_map, bom_map, incoming_map = parse_supply(read_source(f_supply))
    wo_df = parse_wo_detail(f_wo.read())

if wo_df.empty:
    st.warning("製令明細表中找不到 5143 / 5144 / 5145 / 5220 / MO01 開頭的委外工單。")
    st.stop()

st.success(f"資料已載入 ✓　委外工單筆數：{len(wo_df):,}　供需料號：{len(stocks):,}")

# ── 查詢條件 ──────────────────────────────────────────────────────────────────
st.divider()
st.markdown("### 🔍 查詢條件")

valid_dates = wo_df["預計開工"].dropna()
default_start = valid_dates.min().date() if not valid_dates.empty else date(2026, 1, 1)
default_end   = valid_dates.max().date() if not valid_dates.empty else date(2026, 12, 31)

c1, c2, c3, c4 = st.columns([2, 2, 2, 2])
with c1:
    date_start = st.date_input("📅 預計開工（起）", default_start, format="YYYY/MM/DD")
with c2:
    date_end = st.date_input("📅 預計開工（迄）", default_end, format="YYYY/MM/DD")
with c3:
    vendor_filter = st.multiselect("委外廠商篩選（不選=全部）", sorted(wo_df["廠商名稱"].unique().tolist()))
with c4:
    type_filter = st.multiselect("單別篩選（不選=全部）",
                                  sorted(wo_df["單別"].unique().tolist(),
                                         key=lambda x: list(OUTSOURCE_TYPE_MAP).index(x)))

mask = wo_df["預計開工"].notna() & (wo_df["預計開工"].dt.date >= date_start) & (wo_df["預計開工"].dt.date <= date_end)
if vendor_filter:
    mask &= wo_df["廠商名稱"].isin(vendor_filter)
if type_filter:
    mask &= wo_df["單別"].isin(type_filter)
wo_filtered = wo_df[mask].copy()

if wo_filtered.empty:
    st.warning("所選條件下沒有符合的委外工單。")
    st.stop()

st.info(f"找到 **{len(wo_filtered)}** 張委外工單，開始比對物料...")

# ── 批次比對 BOM ──────────────────────────────────────────────────────────────
all_order_nos = set(wo_filtered["製令編號"].tolist())
vendor_wh_candidates = build_vendor_wh_candidates(stocks)

detail_rows = []
summary_rows = []
no_bom_count = 0

progress = st.progress(0)
for idx, (_, wo) in enumerate(wo_filtered.iterrows()):
    progress.progress((idx + 1) / len(wo_filtered), text=f"分析中 {wo['製令編號']}...")

    bom_entries, is_template = get_bom_for_product(
        wo["產品品號"], bom_map, mo_no=wo["製令編號"], all_order_nos=all_order_nos,
    )
    vendor_wh_code, vendor_shared = match_vendor_wh_code(wo["廠商名稱"], vendor_wh_candidates)

    base_info = {
        "委外廠商":   wo["廠商名稱"],
        "加工廠商代號": wo["加工廠商"],
        "單別":       wo["單別"],
        "單別名稱":   wo["單別名稱"],
        "製令編號":   wo["製令編號"],
        "產品品號":   wo["產品品號"],
        "品名":       wo.get("品名", ""),
        "預計開工":   wo["預計開工"].strftime("%Y/%m/%d") if pd.notna(wo["預計開工"]) else "",
        "預計完工":   wo["預計完工"].strftime("%Y/%m/%d") if pd.notna(wo["預計完工"]) else "",
        "預計產量":   wo.get("預計產量", 0),
        "未生產量":   wo.get("未生產量", 0),
    }

    if not bom_entries:
        no_bom_count += 1
        summary_rows.append({**base_info, "是否可滿足開工日": "❔ 無BOM資料", "缺料料項數": None})
        continue

    parts = analyze_bom(bom_entries, stocks, wh_map, incoming_map, is_template=is_template,
                         vendor_wh_code=vendor_wh_code, vendor_shared=vendor_shared)
    for p in parts:
        detail_rows.append({**base_info, **p})

    short_cnt = sum(1 for p in parts if p["狀態"] != "✅ 齊料")
    summary_rows.append({
        **base_info,
        "是否可滿足開工日": "✅ 可滿足" if short_cnt == 0 else f"❌ 不可滿足（缺 {short_cnt} 項）",
        "缺料料項數": short_cnt,
    })

progress.empty()

df_summary = pd.DataFrame(summary_rows)
df_detail  = pd.DataFrame(detail_rows)

if no_bom_count:
    st.caption(f"⚠️ {no_bom_count} 張工單在供需表中找不到對應 BOM（顯示為「無BOM資料」）。")

# ── 統計卡片 ──────────────────────────────────────────────────────────────────
st.divider()
total_wo = len(df_summary)
ok_wo    = (df_summary["是否可滿足開工日"] == "✅ 可滿足").sum()
short_wo = df_summary["是否可滿足開工日"].str.startswith("❌").sum()
nobom_wo = df_summary["是否可滿足開工日"].str.startswith("❔").sum()

m1, m2, m3, m4 = st.columns(4)
m1.metric("📋 委外工單數", f"{total_wo} 張")
m2.metric("✅ 可滿足開工日", f"{ok_wo} 張")
m3.metric("❌ 不可滿足", f"{short_wo} 張")
m4.metric("❔ 無BOM資料", f"{nobom_wo} 張")

st.caption("依委外廠商分布：　" + "　｜　".join(
    f"**{v}** {c} 張" for v, c in df_summary["委外廠商"].value_counts().items()
))

st.divider()

# ── 工單彙總表（依廠商分頁）────────────────────────────────────────────────────
st.markdown("#### 📋 委外工單彙總")

def highlight_summary(row):
    s = row["是否可滿足開工日"]
    if s.startswith("✅"): bg = "background-color:#f0fdf4; color:#15803d;"
    elif s.startswith("❌"): bg = "background-color:#fff1f2; color:#dc2626;"
    else: bg = "background-color:#f1f5f9; color:#64748b;"
    return [bg] * len(row)

summary_cols = ["委外廠商", "單別", "單別名稱", "製令編號", "產品品號", "品名",
                "預計開工", "預計完工", "預計產量", "未生產量", "是否可滿足開工日", "缺料料項數"]

vendors = sorted(df_summary["委外廠商"].unique().tolist())
tab_labels = ["📋 全部廠商"] + [f"{v}（{(df_summary['委外廠商']==v).sum()}）" for v in vendors]
tabs = st.tabs(tab_labels)

with tabs[0]:
    st.dataframe(
        df_summary[summary_cols].style.apply(highlight_summary, axis=1),
        use_container_width=True, height=520, hide_index=True,
    )

for i, v in enumerate(vendors, 1):
    with tabs[i]:
        sub = df_summary[df_summary["委外廠商"] == v][summary_cols]
        st.dataframe(
            sub.style.apply(highlight_summary, axis=1),
            use_container_width=True, height=min(520, 60 + len(sub) * 38), hide_index=True,
        )

# ── 料號明細表 ────────────────────────────────────────────────────────────────
st.divider()
st.markdown("#### 🔎 料號缺料明細")

view_opt = st.selectbox("顯示模式", ["全部料號", "僅缺料料號"])
df_detail_show = df_detail.copy()
if view_opt == "僅缺料料號" and not df_detail_show.empty:
    df_detail_show = df_detail_show[df_detail_show["狀態"] != "✅ 齊料"]

detail_cols = ["委外廠商", "單別", "製令編號", "產品品號", "品名", "預計開工",
               "料號", "需求數量", "目前庫存", "委外廠庫存", "不含委外廠庫存",
               "缺料數量", "狀態", "說明"]

if df_detail_show.empty:
    st.success("✅ 沒有缺料料號。" if view_opt == "僅缺料料號" else "目前沒有料號明細資料。")
else:
    def highlight_detail(row):
        if row["狀態"] == "✅ 齊料":
            return ["background-color:#f0fdf4; color:#15803d;"] * len(row)
        return ["background-color:#fff1f2; color:#dc2626;"] * len(row)

    st.dataframe(
        df_detail_show[detail_cols].style.apply(highlight_detail, axis=1),
        use_container_width=True, height=520, hide_index=True,
    )

# ── 匯出 ──────────────────────────────────────────────────────────────────────
st.divider()
buf = io.BytesIO()
with pd.ExcelWriter(buf, engine="openpyxl") as writer:
    df_summary[summary_cols].to_excel(writer, sheet_name="工單彙總", index=False)
    if not df_detail.empty:
        df_detail[detail_cols].to_excel(writer, sheet_name="料號明細", index=False)
buf.seek(0)
st.download_button(
    label="⬇️ 匯出委外工單排程（Excel）",
    data=buf,
    file_name=f"委外工單排程_{date_start}~{date_end}_{datetime.today().strftime('%Y%m%d')}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)
