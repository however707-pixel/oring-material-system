import glob
import io
import os
import sys
from datetime import date, datetime, timedelta

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from utils.shared import ensure_calamine, inject_css, render_header, render_sidebar, read_source
from utils import wo_material_trace as wmt

st.set_page_config(page_title="全工單料況追蹤", page_icon="📋", layout="wide",
                   initial_sidebar_state="expanded")
ensure_calamine()
inject_css()
render_header(
    title="全工單料況追蹤",
    subtitle="All Work Order Material Tracking · V2→V4 缺料總表流程程式化",
    badge="PMC",
)
render_sidebar()

# ═══════════════════════════════════════════════════════════════════════════════
# 完全比照使用者現行「供需表(分倉)V2 → 分倉整理V3 → 缺料總表V4」xlsm 流程：
#   時間軸=庫存＋需求（未來供給不進結存）、庫群組雙缺口（總缺/工單缺）、
#   供給池 CF(y齊)優先配對、半成品/需燒錄配子製令、包材標籤 P/L OK。
# 詳細規則見 utils/wo_material_trace.py 檔頭說明。
# ═══════════════════════════════════════════════════════════════════════════════
REPORTS = [
    ("mo",  "MOCR19",  "生產進度表（工單主檔）"),
    ("lrp", "LRPMR05", "品號供需明細表（供需/時間軸）"),
    ("pur", "PURR28",  "採購預計進貨表（y齊 交期回覆）"),
]
DL_DIR = os.path.join(os.path.expanduser("~"), "Downloads")
NAS_DIR = r"\\192.168.2.34\MO_Storage\ORing MO\ORing-MO 工作\資材部\每日調撥與送燒ic(NEW)\@2026缺料資訊"
NAS_FC_DIR = (r"\\192.168.2.34\MO_Storage\ORing MO\ORing-MO 鼎新系統報表"
              r"\LRPMR05庫存供需表(分倉)-每日(AM4-00抓取)(Ian提供)-2020")

ST_ORDER = ["needPO", "無子製令", "TBC", "CF", "待調撥", "P/L OK", "庫存"]
ST_CSS = {
    "needPO":  "background-color:#fee2e2;color:#991b1b;font-weight:bold;",
    "無子製令": "background-color:#fee2e2;color:#991b1b;font-weight:bold;",
    "TBC":     "background-color:#fef9c3;color:#854d0e;",
    "CF":      "background-color:#dbeafe;color:#1d4ed8;",
    "待調撥":   "background-color:#f3e8ff;color:#7e22ce;",
    "P/L OK":  "background-color:#f1f5f9;color:#64748b;",
    "庫存":     "background-color:#f0fdf4;color:#15803d;",
}


def _latest_download(prefix: str):
    try:
        files = glob.glob(os.path.join(DL_DIR, prefix + "*.xls*"))
        return max(files, key=os.path.getmtime) if files else None
    except Exception:
        return None


def _latest_nas(prefix: str):
    """NAS「@2026缺料資訊」內該報表的最新檔（排程每日約 17:00 存入新檔）。"""
    try:
        files = [os.path.join(NAS_DIR, f) for f in os.listdir(NAS_DIR)
                 if f.startswith(prefix) and f.lower().endswith((".xlsx", ".xls", ".xlsm"))]
        return max(files, key=os.path.getmtime) if files else None
    except Exception:
        return None


@st.cache_data(show_spinner=False)
def _read_path_cached(path: str, mtime: float) -> bytes:
    return read_source(path)


def _src_bytes(s):
    """路徑來源以 (路徑, mtime) 快取，NAS 每日換新檔自動失效；上傳檔直接讀。"""
    if isinstance(s, str):
        try:
            return _read_path_cached(s, os.path.getmtime(s))
        except OSError:
            return read_source(s)
    return read_source(s)


def _latest_fenchang():
    """NAS 供需表(分倉)-YYYYMMDD.xlsx（每日 AM4:00 抓取）最新一份。"""
    try:
        files = [os.path.join(NAS_FC_DIR, f) for f in os.listdir(NAS_FC_DIR)
                 if f.startswith("供需表(分倉)") and f.lower().endswith(".xlsx")]
        return max(files, key=os.path.getmtime) if files else None
    except Exception:
        return None


@st.cache_data(show_spinner=False)
def _wh_stock(path: str, mtime: float) -> pd.DataFrame:
    """由供需表(分倉)「庫存可用量:」列取各倉目前庫存，回傳 品號 × 各倉 寬表。

    該列的庫別欄混雜代碼(R01/S07…)與名稱(電子倉…)，用檔內 庫別→庫別名稱
    對照正規化；對照不到的（威力-在途倉、外部可用倉…）保留原字。全零倉不列。
    """
    df = pd.read_excel(io.BytesIO(read_source(path)), engine=wmt.ENGINE,
                       usecols=["品號", "庫別", "庫別名稱", "日期", "異動數量"])
    wh_map = (df[df["庫別名稱"].notna() & df["庫別"].notna()]
              .groupby("庫別")["庫別名稱"].agg(lambda s: s.mode().iat[0]))
    init = df[df["日期"].astype(str).str.strip() == "庫存可用量:"].copy()
    init["倉"] = init["庫別"].map(wh_map).fillna(init["庫別"])
    init["異動數量"] = pd.to_numeric(init["異動數量"], errors="coerce").fillna(0)
    wide = init.pivot_table(index="品號", columns="倉", values="異動數量",
                            aggfunc="sum", fill_value=0)
    wide = wide.loc[:, wide.sum() != 0]
    order = list(dict.fromkeys(
        [n for n in wh_map.values if n in wide.columns] +
        [c for c in sorted(wide.columns) if c not in set(wh_map.values)]))
    return wide.reindex(columns=order).reset_index()


@st.cache_data(show_spinner=False)
def _build(mo_bytes: bytes, lrp_bytes: bytes, pur_bytes: bytes):
    """V4 全流程。（邏輯 v2：工單缺剔除在途倉庫存，docstring 兼快取版本戳）"""
    mo  = wmt.parse_mo(io.BytesIO(mo_bytes))
    lrp = wmt.parse_lrp(io.BytesIO(lrp_bytes))
    pur = wmt.parse_pur(io.BytesIO(pur_bytes))
    out_df, wo_df, unmapped = wmt.build_v4(mo, lrp, pur)
    made = {
        k: wmt.report_date(pd.read_excel(io.BytesIO(b), header=None, nrows=3,
                                         engine=wmt.ENGINE))
        for k, b in (("mo", mo_bytes), ("lrp", lrp_bytes), ("pur", pur_bytes))
    }
    return out_df, wo_df, unmapped, made


@st.cache_data(show_spinner=False)
def _excel_bytes(out_csv: bytes, wo_csv: bytes) -> bytes:
    out = pd.read_csv(io.BytesIO(out_csv))
    wo = pd.read_csv(io.BytesIO(wo_csv))
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        wo.to_excel(xw, index=False, sheet_name="工單彙總")
        out.to_excel(xw, index=False, sheet_name="輸出表")
    buf.seek(0)
    return buf.getvalue()


def _fmt_date(v):
    return v.strftime("%Y/%m/%d") if pd.notna(v) else ""


# ── 邏輯說明卡 ─────────────────────────────────────────────────────────────────
st.markdown("---")
st.markdown("#### 運算邏輯　（V2→V3→V4 缺料總表流程，全自動）")
g1, g2, g3, g4 = st.columns(4)
with g1:
    st.markdown("""
<div style="background:#fff7ed;border-left:4px solid #f59e0b;border-radius:6px;padding:12px 14px">
<div style="font-size:13px;font-weight:700;color:#b45309;margin-bottom:6px">① 清洗＋庫群組（V3）</div>
<div style="font-size:12px;color:#374151;line-height:1.6">
刪 9*（留 9-71*）、需燒錄品項<br>
庫別歸群：<b>1寶橋</b>／各代工倉／7不能用
</div></div>""", unsafe_allow_html=True)
with g2:
    st.markdown("""
<div style="background:#fff1f2;border-left:4px solid #ef4444;border-radius:6px;padding:12px 14px">
<div style="font-size:13px;font-weight:700;color:#b91c1c;margin-bottom:6px">② 雙缺口（V4）</div>
<div style="font-size:12px;color:#374151;line-height:1.6">
結存＝庫存−需求（在途不抵）<br>
<b>總缺</b>=全品號｜<b>工單缺</b>=庫群×品號<br>
工單缺<b>不計在途倉</b>｜總夠群缺 → <b>待調撥</b>
</div></div>""", unsafe_allow_html=True)
with g3:
    st.markdown("""
<div style="background:#eff6ff;border-left:4px solid #3b82f6;border-radius:6px;padding:12px 14px">
<div style="font-size:13px;font-weight:700;color:#1d4ed8;margin-bottom:6px">③ 供給配對（V4）</div>
<div style="font-size:12px;color:#374151;line-height:1.6">
採購/委外單（3310/3320/52xx）<br>
<b>CF＝採購 y齊 回覆優先</b>，再依日期<br>
5-* 半成品／需燒錄 → 配<b>子製令</b>
</div></div>""", unsafe_allow_html=True)
with g4:
    st.markdown("""
<div style="background:#f0fdf4;border-left:4px solid #22c55e;border-radius:6px;padding:12px 14px">
<div style="font-size:13px;font-weight:700;color:#15803d;margin-bottom:6px">④ 工單彙總（疊加）</div>
<div style="font-size:12px;color:#374151;line-height:1.6">
每張工單：各狀態項數、<b>齊料日</b>＝<br>
CF/TBC 列最大料齊日，比對<b>開、完工日</b>
</div></div>""", unsafe_allow_html=True)
st.caption(
    "final status：庫存（現有量足）｜待調撥（總量夠、該庫群缺，廠內調撥）｜CF（在途且採購已回 y齊）｜"
    "TBC（在途未確認交期）｜needPO（缺且未開單，料齊日 9999/9/9）｜P/L OK（包材/標籤 1901~1907，不擋料）｜"
    "無子製令（半成品缺且查無在製工單）。與原 xlsm 差異：無子製令獨立列示（原誤標 CF）、"
    "子製令依完工日序配（原依開單序）、全量運算無 70,000 列公式上限、"
    "工單缺不計各「-在途倉」庫存（貨未到不算群內可用；總缺照計）。"
)

# ── 側欄：三檔載入 ─────────────────────────────────────────────────────────────
srcs = {}
fc_path = _latest_fenchang()
with st.sidebar:
    st.divider()
    st.markdown("### 📂 資料來源（三檔）")
    st.caption("自動抓取 NAS「@2026缺料資訊」最新檔（每日約 17:00 更新）；"
               "可手動上傳覆蓋，NAS 離線時改抓 Downloads")
    for key, prefix, label in REPORTS:
        up = st.file_uploader(f"{prefix}｜{label}", type=["xlsx", "xls"], key=f"up_{key}")
        if up is not None:
            srcs[key] = up
            st.success(f"⬆️ 使用上傳檔：{up.name}")
            continue
        p = _latest_nas(prefix)
        if p:
            mt = datetime.fromtimestamp(os.path.getmtime(p)).strftime("%m/%d %H:%M")
            srcs[key] = p
            st.success(f"✅ NAS：{os.path.basename(p)[:24]}…（{mt}）")
            continue
        p = _latest_download(prefix)
        if p:
            mt = datetime.fromtimestamp(os.path.getmtime(p)).strftime("%m/%d %H:%M")
            srcs[key] = p
            st.info(f"📂 NAS 離線，改用 Downloads：{os.path.basename(p)[:20]}…（{mt}）")
        else:
            st.warning(f"⚠️ NAS 與 Downloads 均無 {prefix}* 檔，請上傳")
    if fc_path:
        _fc_mt = datetime.fromtimestamp(os.path.getmtime(fc_path)).strftime("%m/%d %H:%M")
        st.success(f"✅ 各倉庫存：{os.path.basename(fc_path)}（{_fc_mt}）")
    else:
        st.warning("⚠️ NAS 供需表(分倉) 讀不到，各倉庫存欄位停用")
    st.button("🔄 重新偵測 NAS 最新檔", use_container_width=True)

missing = [f"{pfx}（{lab}）" for k, pfx, lab in REPORTS if k not in srcs]
if missing:
    st.info("👈 請於左側備齊三份報表：" + "、".join(missing))
    st.stop()

with st.spinner("執行 V2→V4 全流程運算中（首次約 10 秒，之後走快取）..."):
    try:
        out_df, wo_df, unmapped, made = _build(
            _src_bytes(srcs["mo"]), _src_bytes(srcs["lrp"]), _src_bytes(srcs["pur"]))
    except ValueError as e:
        st.error(f"❌ {e}")
        st.stop()

# ── 各倉目前庫存欄（供需表(分倉) 最新快照，接在輸出表後面）───────────────────
STOCK_COLS = []
fc_note = ""
if fc_path:
    try:
        _stock = _wh_stock(fc_path, os.path.getmtime(fc_path))
        STOCK_COLS = [c for c in _stock.columns if c != "品號"]
        out_df = out_df.merge(_stock, on="品號", how="left")
        out_df[STOCK_COLS] = out_df[STOCK_COLS].fillna(0)
        fc_note = ("　｜　各倉庫存快照：" +
                   os.path.basename(fc_path).replace("供需表(分倉)-", "").replace(".xlsx", ""))
    except Exception as _e:
        STOCK_COLS = []
        st.warning(f"⚠️ 供需表(分倉) 解析失敗，各倉庫存欄位停用：{_e}")

st.success(
    f"運算完成 ✓　工單 {len(wo_df):,} 張　輸出表（領用列）{len(out_df):,} 列　｜　製表日期："
    f"進度表 {made['mo'] or '—'}、供需表 {made['lrp'] or '—'}、採購表 {made['pur'] or '—'}"
    + fc_note
)
if unmapped:
    st.warning(f"⚠️ 有庫別不在對照表，已各自成群：{', '.join(unmapped[:12])}"
               f"{'…' if len(unmapped) > 12 else ''}（如需併入寶橋/代工群請告知）")

tab_wo, tab_out = st.tabs(["📊 工單彙總（齊料 vs 開完工）", "📄 輸出表（V4 口徑・逐筆領用）"])

# ═══════════════════════════════════════════════════════════════════════════════
# Tab 1：工單彙總
# ═══════════════════════════════════════════════════════════════════════════════
with tab_wo:
    c1, c2, c3, c4 = st.columns([2, 2, 1.4, 2.6])
    with c1:
        d_start = st.date_input("📅 開工日（起）", date.today(), format="YYYY/MM/DD")
    with c2:
        d_end = st.date_input("📅 開工日（迄）", date.today() + timedelta(days=60),
                              format="YYYY/MM/DD")
    with c3:
        all_dates = st.checkbox("不限開工日", value=False)
    with c4:
        # 由戰情室下鑽帶入的工單號（/wo_material_trace?wo=XXX），預填進搜尋框
        try:
            _wo_q = st.query_params.get("wo", "") or ""
        except Exception:
            _wo_q = ""
        kw = st.text_input("搜尋 製令 / 品號 / 訂單 / 客戶", value=_wo_q,
                           placeholder="輸入關鍵字")
    f1, f2, f3 = st.columns([2.2, 2, 1.8])
    with f1:
        view = st.selectbox("料況", ["全部", "⛔ 缺料無單", "🕐 待確認交期", "🚚 在途中",
                                     "🔁 待調撥", "✅ 齊料", "📦 無領用需求", "🔥 齊料晚於開工"])
    with f2:
        vend_sel = st.multiselect("加工廠商", sorted(wo_df["廠商"].unique()), placeholder="全部")
    with f3:
        status_sel = st.multiselect("製令狀態", sorted(wo_df["狀態"].unique()), placeholder="全部")

    df = wo_df.copy()
    # 有輸入關鍵字＝定點查找 → 不受開工日區間限制，避免「查不到」
    if not all_dates and not kw.strip():
        if d_end < d_start:
            st.error("⚠️ 結束日不可早於起始日")
            st.stop()
        df = df[df["開工日"].notna() &
                (df["開工日"].dt.date >= d_start) & (df["開工日"].dt.date <= d_end)]
    elif kw.strip() and not all_dates:
        st.caption("🔎 已輸入關鍵字：搜尋範圍為全部工單（不受開工日區間限制）")
    if view.startswith("🔥"):
        df = df[pd.to_numeric(df["齊料-開工(天)"], errors="coerce") > 0]
    elif view != "全部":
        df = df[df["料況"].str.startswith(view.split(" ")[0])]
    if vend_sel:
        df = df[df["廠商"].isin(vend_sel)]
    if status_sel:
        df = df[df["狀態"].isin(status_sel)]
    if kw.strip():
        k = kw.strip()
        df = df[df["製令編號"].str.contains(k, case=False, na=False) |
                df["產品品號"].str.contains(k, case=False, na=False) |
                df["品名"].str.contains(k, case=False, na=False) |
                df["訂單單號"].str.contains(k, case=False, na=False) |
                df["客戶名稱"].str.contains(k, case=False, na=False)]
    df = df.sort_values(["開工日", "製令編號"], na_position="last")

    n_dead = df["料況"].str.startswith("⛔").sum()
    n_tbc  = df["料況"].str.startswith("🕐").sum()
    n_cf   = df["料況"].str.startswith("🚚").sum()
    n_tr   = df["料況"].str.startswith("🔁").sum()
    n_ok   = df["料況"].str.startswith("✅").sum()
    n_late = (pd.to_numeric(df["齊料-開工(天)"], errors="coerce") > 0).sum()
    k1, k2, k3, k4, k5, k6, k7 = st.columns(7)
    k1.metric("工單數", f"{len(df):,}")
    k2.metric("⛔ 缺料無單", int(n_dead), help="至少一項 needPO / 無子製令，須請購或開單")
    k3.metric("🕐 待確認交期", int(n_tbc), help="有 TBC 在途（採購未回 y齊），齊料日僅供參考")
    k4.metric("🚚 在途中", int(n_cf), help="缺口全數有 CF（y齊）在途")
    k5.metric("🔁 待調撥", int(n_tr), help="缺口僅在庫群、總量足夠，廠內調撥即可")
    k6.metric("✅ 齊料", int(n_ok))
    k7.metric("🔥 齊料晚於開工", int(n_late))

    show = df.copy()
    for c in ("開工日", "完工日", "齊料日", "採購註記齊料"):
        show[c] = show[c].map(_fmt_date)
    show["預計產量"] = show["預計產量"].map(lambda v: f"{v:,.0f}")
    DISPLAY = ["製令編號", "狀態", "產品品號", "品名", "預計產量", "廠商",
               "開工日", "完工日", "齊料日", "齊料-開工(天)", "料況", "用料項數",
               "庫存OK", "待調撥", "CF在途", "TBC", "needPO", "P/L",
               "採購註記齊料", "訂單單號", "客戶名稱"]

    def _hl(row):
        s = row["料況"]
        if s.startswith("✅"):
            css = "background-color:#f0fdf4;color:#15803d;"
        elif s.startswith("🚚"):
            css = "background-color:#dbeafe;color:#1d4ed8;"
        elif s.startswith("🕐"):
            css = "background-color:#fef9c3;color:#854d0e;"
        elif s.startswith("🔁"):
            css = "background-color:#f3e8ff;color:#7e22ce;"
        elif s.startswith("⛔"):
            css = "background-color:#fee2e2;color:#991b1b;font-weight:bold;"
        else:
            css = "background-color:#f8fafc;color:#475569;"
        return [css] * len(row)

    st.dataframe(
        show[DISPLAY].style.apply(_hl, axis=1),
        use_container_width=True, height=430, hide_index=True,
        column_config={
            "製令編號": st.column_config.TextColumn(width=150),
            "產品品號": st.column_config.TextColumn(width=200),
            "品名":     st.column_config.TextColumn(width=170),
            "齊料-開工(天)": st.column_config.TextColumn(
                help="齊料日 − 開工日；正數=料比開工晚到"),
            "採購註記齊料": st.column_config.TextColumn(
                help="採購在 PURR28 備註手寫的 y齊 日期（對照用）"),
        },
    )
    st.caption(f"顯示 {len(show):,} 張 / 全部 {len(wo_df):,} 張工單")

    # ── 單一工單明細 ─────────────────────────────────────────────────────────
    st.divider()
    st.markdown("### 📋 工單用料明細")
    if df.empty:
        st.warning("目前篩選條件下沒有工單。")
    else:
        opts = df["製令編號"] + "｜" + df["產品品號"].str.slice(0, 24) + "｜" + df["料況"]
        pick = st.selectbox("選擇工單", opts.tolist())
        wo_pick = pick.split("｜")[0]
        r = df[df["製令編號"] == wo_pick].iloc[0]
        i1, i2, i3, i4, i5 = st.columns(5)
        i1.metric("開工日", _fmt_date(r["開工日"]) or "—")
        i2.metric("完工日", _fmt_date(r["完工日"]) or "—")
        i3.metric("齊料日", _fmt_date(r["齊料日"]) or
                  ("—" if r["料況"].startswith(("✅", "📦", "🔁")) else "無法估"))
        i4.metric("齊料-開工", f"{r['齊料-開工(天)']} 天" if r["齊料-開工(天)"] != "" else "—")
        i5.metric("缺口/用料", f"{int(r['CF在途'] + r['TBC'] + r['needPO'])} / {int(r['用料項數'])} 項")

        d = out_df[out_df["工單"] == wo_pick].copy()
        if d.empty:
            st.info("供需表中沒有此工單的領用列（多為已領料完畢）。")
        else:
            only_gap = st.toggle("只看有缺口的料（隱藏 庫存/P.L）", value=True)
            if only_gap:
                d = d[~d["final status"].isin(["庫存", "P/L OK"])]
            d["_o"] = d["final status"].map({s: i for i, s in enumerate(ST_ORDER)})
            d = d.sort_values(["_o", "料齊日"])
            dd = d.copy()
            dd["需求日"] = dd["需求日"].map(_fmt_date)
            dd["料齊日"] = dd["料齊日"].map(_fmt_date)
            for c in ["異動數量", "工單缺", "總缺"] + STOCK_COLS:
                dd[c] = dd[c].map(lambda v: f"{v:,.0f}")
            DET = ["品號", "品名", "庫", "需求日", "異動數量", "工單缺", "總缺",
                   "final status", "料齊日", "對應單據", "交期回覆"] + STOCK_COLS

            def _hd(row):
                return [ST_CSS.get(row["final status"], "")] * len(row)

            st.dataframe(
                dd[DET].style.apply(_hd, axis=1),
                use_container_width=True, height=380, hide_index=True,
                column_config={
                    "品號": st.column_config.TextColumn(width=200),
                    "交期回覆": st.column_config.TextColumn(
                        width=240, help="對應採購單在 PURR28 的備註（y齊 註記）"),
                },
            )
            st.caption(f"共 {len(dd):,} 列")

# ═══════════════════════════════════════════════════════════════════════════════
# Tab 2：輸出表（V4）
# ═══════════════════════════════════════════════════════════════════════════════
with tab_out:
    o1, o2, o3, o4 = st.columns([2, 2, 2, 2])
    with o1:
        st_sel = st.multiselect("final status", ST_ORDER, placeholder="全部")
    with o2:
        gr_sel = st.multiselect("庫（群組）", sorted(out_df["庫"].unique()), placeholder="全部")
    with o3:
        kw2 = st.text_input("搜尋 品號 / 品名 / 工單 / 單據", placeholder="輸入關鍵字")
    with o4:
        top_n = st.number_input("最多顯示列數", 500, 20000, 3000, step=500)

    o = out_df.copy()
    if st_sel:
        o = o[o["final status"].isin(st_sel)]
    if gr_sel:
        o = o[o["庫"].isin(gr_sel)]
    if kw2.strip():
        k = kw2.strip()
        o = o[o["品號"].str.contains(k, case=False, na=False) |
              o["品名"].str.contains(k, case=False, na=False) |
              o["工單"].str.contains(k, case=False, na=False) |
              o["對應單據"].str.contains(k, case=False, na=False)]
    # V4 慣例：料齊日降冪（needPO 9999/9/9 排最前）
    o = o.sort_values("料齊日", ascending=False, na_position="last")

    st.caption("final status 分佈（目前篩選）：" + "　".join(
        f"{s} {c:,}" for s, c in o["final status"].value_counts().items()))

    oo = o.head(int(top_n)).copy()
    oo["需求日"] = oo["需求日"].map(_fmt_date)
    oo["料齊日"] = oo["料齊日"].map(_fmt_date)
    for c in ["異動數量", "工單缺", "總缺"] + STOCK_COLS:
        oo[c] = oo[c].map(lambda v: f"{v:,.0f}")
    OUT_COLS = ["庫", "品號", "品名", "需求日", "異動數量", "工單", "工單缺", "總缺",
                "包材/標籤", "料齊日", "對應單據", "final status", "交期回覆"] + STOCK_COLS

    def _ho(row):
        return [ST_CSS.get(row["final status"], "")] * len(row)

    st.dataframe(
        oo[OUT_COLS].style.apply(_ho, axis=1),
        use_container_width=True, height=520, hide_index=True,
        column_config={
            "品號": st.column_config.TextColumn(width=200),
            "工單": st.column_config.TextColumn(width=150),
            "交期回覆": st.column_config.TextColumn(width=220),
        },
    )
    st.caption(f"顯示 {len(oo):,} / 篩選後 {len(o):,} / 全部 {len(out_df):,} 列"
               "（匯出 Excel 為全量，不受顯示上限影響）")

# ── 匯出 ──────────────────────────────────────────────────────────────────────
st.divider()
exp_out = out_df.copy()
exp_out["需求日"] = exp_out["需求日"].map(_fmt_date)
exp_out["料齊日"] = exp_out["料齊日"].map(_fmt_date)
exp_wo = wo_df.copy()
for c in ("開工日", "完工日", "齊料日", "採購註記齊料"):
    exp_wo[c] = exp_wo[c].map(_fmt_date)
xls = _excel_bytes(exp_out.to_csv(index=False).encode("utf-8-sig"),
                   exp_wo.to_csv(index=False).encode("utf-8-sig"))
st.download_button(
    "⬇️ 匯出 Excel（工單彙總＋輸出表 全量）",
    data=xls,
    file_name=f"全工單料況_{date.today():%Y%m%d}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)
