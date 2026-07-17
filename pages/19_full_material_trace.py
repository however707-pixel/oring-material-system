import streamlit as st
import pandas as pd
import io
import sys
import os
import re
from datetime import date
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from utils.shared import inject_css, render_header, render_sidebar, render_sd_loader, read_source

st.set_page_config(page_title="全廠料況追蹤", page_icon="🏭", layout="wide",
                   initial_sidebar_state="expanded")
inject_css()

render_header(
    title="全廠料況追蹤",
    subtitle="Plant-wide Material Trace · 組裝 → 板階 → 料況 · ORing Industrial Networking",
    badge="Production Control",
)
render_sidebar()

# ── 品號前綴定義（依鼎新編碼規則：9- 為組裝成品、5-70- 為板階半成品）──────────────
ASSY_PREFIX  = "9-"
BOARD_PREFIX = "5-70-"

# ── 出貨日來源：排程系統使用的「簡版-工單缺料狀況.xlsx」（工單 → 產銷出貨日）─────────
SCHED_BASE  = r"\\192.168.2.34\MO_Storage\ORing MO\ORing-MO 工作\早會資料夾"
SCHED_FILE  = "簡版-工單缺料狀況.xlsx"
SCHED_CACHE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "data", "kanban_latest.xlsx")
_REF_YEAR = date.today().year


def _find_latest_sched():
    """遞迴搜尋 NAS 早會資料夾，回傳最新的排程檔路徑（不可達回 None）。"""
    import glob
    try:
        files = glob.glob(os.path.join(SCHED_BASE, "**", SCHED_FILE), recursive=True)
        if not files:
            return None
        files.sort(key=os.path.getmtime, reverse=True)
        return files[0]
    except Exception:
        return None


def _ship_value(raw) -> str:
    """把排程出貨日欄轉成顯示字串：日期→YYYY/MM/DD；TBD/試產→原文；空白→空字串。"""
    if pd.isna(raw):
        return ""
    if hasattr(raw, "date"):              # datetime / Timestamp
        try:
            return raw.date().strftime("%Y/%m/%d")
        except Exception:
            pass
    s = str(raw).strip()
    if s in ("", "nan", "None", "00:00:00"):
        return ""
    try:
        return pd.to_datetime(s).date().strftime("%Y/%m/%d")
    except Exception:
        pass
    # 文字含多個 M/D（如「6/15-國智*750，6/29...」）→ 取最早一個
    found = re.findall(r"(\d{1,2})/(\d{1,2})", s)
    dts = []
    for m_, d_ in found:
        try:
            dt = date(_REF_YEAR, int(m_), int(d_))
            if (date.today() - dt).days > 180:   # 跨年判斷
                dt = date(_REF_YEAR + 1, int(m_), int(d_))
            dts.append(dt)
        except Exception:
            continue
    if dts:
        return min(dts).strftime("%Y/%m/%d")
    return s                               # 保留 TBD / 試產 等原文


@st.cache_data(show_spinner=False)
def build_ship_map(sched_bytes):
    """讀排程檔 LIST 分頁，建立 {工單: 出貨日字串}。B欄=工單、M欄=產銷出貨日。"""
    df = pd.read_excel(io.BytesIO(sched_bytes), sheet_name="LIST", header=0)
    m = {}
    for _, r in df.iterrows():
        if len(r) <= 12 or pd.isna(r.iloc[1]):
            continue
        wo = str(r.iloc[1]).strip()
        if wo and wo != "nan":
            m[wo] = _ship_value(r.iloc[12])
    return m


# ═══════════════════════════════════════════════════════════════════════════════
# 解析分倉供需表（單一來源檔）
#   只取兩種異動：預計領用（需求/領料）、預計生產（工單入庫）
#   品號為區塊式（子列空白）→ 先 ffill
#   備註欄 = 製令編號（領用＝消耗它的工單；生產＝生產它的工單）
# ═══════════════════════════════════════════════════════════════════════════════
@st.cache_data(show_spinner=False)
def parse_ledger(file_bytes):
    try:
        df = pd.read_excel(io.BytesIO(file_bytes), header=0, engine="openpyxl", dtype=str)
    except Exception:
        df = pd.read_excel(io.BytesIO(file_bytes), header=0, dtype=str)
    df.columns = [str(c).strip() for c in df.columns]

    need = ["品號", "庫別名稱", "日期", "異動別", "異動數量", "預計結存", "備註"]
    missing = [c for c in need if c not in df.columns]
    if missing:
        return None, f"檔案缺少必要欄位：{missing}（請確認上傳的是『供需表（分倉）』）"

    df["品號_ff"] = df["品號"].ffill()
    df["dt_parsed"] = pd.to_datetime(df["日期"], errors="coerce")

    def _num(s):
        try:
            return float(s) if pd.notna(s) and str(s).strip() != "" else 0.0
        except Exception:
            return 0.0

    rows = []
    for r in df.itertuples(index=False):
        pno = getattr(r, "品號_ff")
        trans = getattr(r, "異動別")
        dt = getattr(r, "dt_parsed")
        if pd.isna(pno) or pd.isna(trans) or pd.isna(dt):
            continue
        trans = str(trans).strip()
        if trans not in ("預計領用", "預計生產"):
            continue
        rows.append((
            str(pno).strip(),
            "" if pd.isna(getattr(r, "庫別名稱")) else str(getattr(r, "庫別名稱")).strip(),
            dt,
            trans,
            _num(getattr(r, "異動數量")),
            _num(getattr(r, "預計結存")),
            "" if pd.isna(getattr(r, "備註")) else str(getattr(r, "備註")).strip(),
        ))

    led = pd.DataFrame(rows, columns=["品號", "庫別名稱", "日期", "異動別",
                                      "異動數量", "預計結存", "備註"])
    if led.empty:
        return None, "檔案中找不到任何『預計領用 / 預計生產』資料列。"
    return led, None


def _assembly_core(pno: str):
    """9-{CORE}-00_XXB31 → CORE"""
    m = re.match(r"^9-(.+?)-00(?:_|-|$)", pno)
    return m.group(1) if m else None


def _board_core(pno: str):
    """5-70-{CORE}-{suffix} → CORE（去掉最後一段料階碼）"""
    if not pno.startswith(BOARD_PREFIX):
        return None
    rest = pno[len(BOARD_PREFIX):]
    return rest.rsplit("-", 1)[0] if "-" in rest else rest


@st.cache_data(show_spinner=False)
def build_index(led):
    """由帳冊建立查詢索引。"""
    prod_by_board = defaultdict(list)     # 板階品號 -> [(date, wo)]  跨庫別、依日期排序
    comp_by_wo    = defaultdict(list)     # 工單 -> [(料件品號, 庫別, qty, bal)]
    consume_board = []                    # 板階「預計領用」（= 上階工單消耗板階）
    produced_cnt  = defaultdict(lambda: defaultdict(int))   # wo -> {品號: 次數}

    for r in led.itertuples(index=False):
        pno, wh, dt, trans, qty, bal, wo = (
            r.品號, r.庫別名稱, r.日期, r.異動別, r.異動數量, r.預計結存, r.備註
        )
        if trans == "預計生產":
            if wo:
                produced_cnt[wo][pno] += 1
            if pno.startswith(BOARD_PREFIX):
                prod_by_board[pno].append((dt, wo))
        else:  # 預計領用
            if wo:
                comp_by_wo[wo].append((pno, wh, qty, bal))
            if pno.startswith(BOARD_PREFIX):
                consume_board.append({"board": pno, "wh": wh, "date": dt,
                                      "qty": qty, "bal": bal, "wo": wo})

    produced_by = {wo: max(items.items(), key=lambda x: x[1])[0]
                   for wo, items in produced_cnt.items()}
    for k in prod_by_board:
        prod_by_board[k].sort(key=lambda x: x[0])

    core_to_assy = {}
    for pno in led["品號"].unique():
        c = _assembly_core(pno)
        if c:
            core_to_assy[c] = pno

    return dict(prod_by_board=prod_by_board, comp_by_wo=comp_by_wo,
                consume_board=consume_board, produced_by=produced_by,
                core_to_assy=core_to_assy)


def trace(idx, date_start, date_end):
    """核心：組裝開工日 → 板階結存正負 → 對應板階工單 → 板階料況。"""
    prod_by_board = idx["prod_by_board"]
    comp_by_wo    = idx["comp_by_wo"]
    produced_by   = idx["produced_by"]
    core_to_assy  = idx["core_to_assy"]

    results = []
    for c in idx["consume_board"]:
        open_d = c["date"].date()
        if not (date_start <= open_d <= date_end):
            continue
        parent_wo = c["wo"]
        if not parent_wo:
            continue

        # 排除「板階生產的領用」（如重工、委外發料）——這類消耗者本身生產的是 5- 半成品，
        # 並非組裝成品；組裝工單生產的是 9- 成品或在供需表中查無生產對象。
        pp = produced_by.get(parent_wo, "")
        if pp.startswith("5-"):
            continue

        board = c["board"]
        wh    = c["wh"]
        bal   = c["bal"]
        need  = c["qty"]

        assy_pno = pp if pp.startswith(ASSY_PREFIX) else (
            core_to_assy.get(_board_core(board), "") )

        # ── 找對應板階工單（同板階品號的「預計生產」，跨庫別、依日期）──────────────
        #    板階多在 半成品倉 生產，卻可能在各代工倉被領用，故生產不限定同庫別。
        lst = prod_by_board.get(board, [])
        sat_wo, sat_date = "", None
        if bal < 0:
            # 板階結存負 → 板階生產比組裝慢 → 抓開工日「之後」最近一張板階工單
            for dt_, wo_ in lst:
                if dt_.date() > open_d:
                    sat_wo, sat_date = wo_, dt_
                    break
        else:
            # 板階結存正 → 板階生產比組裝快 → 抓開工日「(含)之前」最近一張板階工單
            for dt_, wo_ in lst:
                if dt_.date() <= open_d:
                    sat_wo, sat_date = wo_, dt_
                else:
                    break

        # ── 板階料況（該板階工單領用的料件是否缺料）──────────────────────────
        agg = {}
        for cp, cwh, cq, cb in comp_by_wo.get(sat_wo, []):
            if cp == board:
                continue          # 排除板階自身（委外發料列）
            if cp not in agg or cb < agg[cp][2]:
                agg[cp] = (cwh, cq, cb)
        short = [(cp, v[0], v[1], v[2], min(v[1], -v[2]))
                 for cp, v in agg.items() if v[2] < 0]
        short.sort(key=lambda x: x[3])      # 結存最負者排前
        total_comp = len(agg)

        if not sat_wo:
            # 找不到對應板階工單時，由結存正負判讀：
            #   負 → 短缺且開工日後無在製可補（最需關注）
            #   正 → 由現有庫存（庫存可用量）滿足，無需在製工單
            status = "⛔ 短缺無在製" if bal < 0 else "📦 現貨滿足"
        elif total_comp == 0:
            status = "ℹ️ 委外板階(料況不明)"
        elif short:
            status = f"⚠️ 缺料 {len(short)} 項"
        else:
            status = "✅ 齊料"

        results.append({
            "組裝工單":   parent_wo,
            "組裝品號":   assy_pno or "—",
            "開工日":     open_d,
            "板階品號":   board,
            "板階庫別":   wh,
            "板階需求量": int(round(need)),
            "板階結存":   int(round(bal)),
            "結存判斷":   "負｜板階生產比組裝慢" if bal < 0 else "正｜板階生產比組裝快",
            "對應板階工單": sat_wo or "—",
            "板階完工日": sat_date.date() if sat_date is not None else None,
            "板階料況":   status,
            "_short":     short,
            "_total":     total_comp,
        })

    return results


# ═══════════════════════════════════════════════════════════════════════════════
# 邏輯說明卡
# ═══════════════════════════════════════════════════════════════════════════════
st.markdown("---")
st.markdown("#### 追蹤邏輯說明　（單一來源：供需表（分倉））")

g1, g2, g3, g4 = st.columns(4)
with g1:
    st.markdown("""
<div style="background:#eff6ff;border-left:4px solid #3b82f6;border-radius:6px;padding:12px 14px">
<div style="font-size:13px;font-weight:700;color:#1d4ed8;margin-bottom:6px">① 組裝開工日</div>
<div style="font-size:12px;color:#374151;line-height:1.6">
組裝成品 <code>9-</code> 工單於板階 <code>5-70-</code> 的<br>
<b>預計領用</b>日期＝該組裝<b>開工日</b>
</div></div>""", unsafe_allow_html=True)
with g2:
    st.markdown("""
<div style="background:#fff1f2;border-left:4px solid #ef4444;border-radius:6px;padding:12px 14px">
<div style="font-size:13px;font-weight:700;color:#b91c1c;margin-bottom:6px">②a 板階結存「負」</div>
<div style="font-size:12px;color:#374151;line-height:1.6">
板階生產比組裝<b>慢</b> → 抓開工日<br>
<b>之後</b>最接近的板階工單（預計生產）
</div></div>""", unsafe_allow_html=True)
with g3:
    st.markdown("""
<div style="background:#f0fdf4;border-left:4px solid #22c55e;border-radius:6px;padding:12px 14px">
<div style="font-size:13px;font-weight:700;color:#15803d;margin-bottom:6px">②b 板階結存「正」</div>
<div style="font-size:12px;color:#374151;line-height:1.6">
板階生產比組裝<b>快</b> → 抓開工日<br>
<b>(含)之前</b>最接近的板階工單
</div></div>""", unsafe_allow_html=True)
with g4:
    st.markdown("""
<div style="background:#fefce8;border-left:4px solid #eab308;border-radius:6px;padding:12px 14px">
<div style="font-size:13px;font-weight:700;color:#854d0e;margin-bottom:6px">③ 板階料況</div>
<div style="font-size:12px;color:#374151;line-height:1.6">
再看該板階工單領用的料件<br>
<b>預計結存 &lt; 0 → 缺料</b>
</div></div>""", unsafe_allow_html=True)

st.caption(
    "板階料況：✅ 齊料｜⚠️ 缺料（板階工單有料件結存 < 0）｜"
    "📦 現貨滿足（結存正、無在製工單，由庫存滿足）｜"
    "⛔ 短缺無在製（結存負、開工日後查無板階工單，無在製可補）｜"
    "ℹ️ 委外板階（有對應工單，但供需表未列其領用料件）"
)

# ── 載入分倉報表（NAS 自動 / 手動上傳）─────────────────────────────────────────
with st.sidebar:
    st.divider()
    st.markdown("### 📂 資料來源")
    f_supply = render_sd_loader(key="full_trace", label="供需表（分倉）")

    st.markdown("### 📅 出貨日來源（選填）")
    st.caption("取自排程系統的「簡版-工單缺料狀況」，依組裝工單帶出產銷出貨日")
    _sched_up = st.file_uploader("排程檔（選填覆蓋）", type=["xlsx", "xls"], key="ft_sched_up")
    sched_src = None
    if _sched_up is not None:
        sched_src = _sched_up
    else:
        _nas_sched = _find_latest_sched()
        if _nas_sched:
            sched_src = _nas_sched
            st.success(f"✅ NAS 排程檔：{os.path.basename(_nas_sched)}")
        elif os.path.exists(SCHED_CACHE):
            sched_src = SCHED_CACHE
            st.info("💾 使用本機快取（kanban_latest）")
        else:
            st.warning("⚠️ 查無排程檔，出貨日欄將留空")

if not f_supply:
    st.info("👈 請在左側確認／上傳『供需表（分倉）』，本功能僅需這一個檔案。")
    st.stop()

ship_map = {}
if sched_src is not None:
    try:
        ship_map = build_ship_map(read_source(sched_src))
    except Exception as e:
        st.warning(f"⚠️ 排程檔讀取失敗，出貨日將留空：{e}")

with st.spinner("讀取供需表中..."):
    led, err = parse_ledger(read_source(f_supply))
if err:
    st.error(err)
    st.stop()
idx = build_index(led)

st.success(
    f"資料已載入 ✓　帳冊列數：{len(led):,}　"
    f"板階品號（5-70-）：{led[led['品號'].str.startswith(BOARD_PREFIX)]['品號'].nunique():,}　"
    f"板階消耗事件：{len(idx['consume_board']):,}"
)

# ── 查詢條件 ──────────────────────────────────────────────────────────────────
st.divider()
st.markdown("### 🔍 查詢條件（依組裝開工日）")
c1, c2, c3 = st.columns([2, 2, 1])
with c1:
    date_start = st.date_input("📅 組裝開工日（起）", date(2026, 6, 1), format="YYYY/MM/DD")
with c2:
    date_end = st.date_input("📅 組裝開工日（迄）", date(2026, 6, 30), format="YYYY/MM/DD")
with c3:
    st.markdown("<br>", unsafe_allow_html=True)
    run = st.button("🚀 執行追蹤", type="primary", use_container_width=True)

if date_end < date_start:
    st.error("⚠️ 結束日不可早於起始日")
    st.stop()
if not run:
    st.stop()

with st.spinner("追蹤組裝 → 板階 → 料況中..."):
    results = trace(idx, date_start, date_end)

if not results:
    st.warning(f"所選區間（{date_start} ～ {date_end}）內沒有組裝工單領用板階的紀錄。")
    st.stop()

df_all = pd.DataFrame(results)

# ── 併入排程系統出貨日（依組裝工單）────────────────────────────────────────────
df_all["出貨日"] = df_all["組裝工單"].map(lambda w: ship_map.get(w, ""))
_ship_hit = int((df_all["出貨日"] != "").sum())

# ── KPI ───────────────────────────────────────────────────────────────────────
st.divider()
total_rows = len(df_all)
assy_cnt   = df_all["組裝工單"].nunique()
short_cnt  = (df_all["板階料況"].str.startswith("⚠️")).sum()
ok_cnt     = (df_all["板階料況"].str.startswith("✅")).sum()
stock_cnt  = (df_all["板階料況"].str.startswith("📦")).sum()
crit_cnt   = (df_all["板階料況"].str.startswith("⛔")).sum()
subcon_cnt = (df_all["板階料況"].str.startswith("ℹ️")).sum()

k1, k2, k3, k4, k5, k6 = st.columns(6)
k1.metric("組裝工單數", assy_cnt)
k2.metric("追蹤筆數", total_rows)
k3.metric("⚠️ 板階缺料", int(short_cnt))
k4.metric("✅ 板階齊料", int(ok_cnt))
k5.metric("📦 現貨滿足", int(stock_cnt),
          help="板階結存為正且無對應在製工單，由現有庫存滿足")
k6.metric("⛔ 短缺無在製", int(crit_cnt),
          help="板階結存為負且開工日後查無板階工單——無在製可補，最需關注")
if subcon_cnt:
    st.caption(f"另有 ℹ️ 委外板階（料況不明）{int(subcon_cnt)} 筆：已對應到委外板階工單，"
               f"但供需表未列其領用料件。")
if ship_map:
    st.caption(f"📅 出貨日取自排程系統，{_ship_hit:,}/{total_rows:,} 筆對應到出貨日"
               f"（排程檔未列的工單留空）。")
else:
    st.caption("📅 未載入排程檔，出貨日欄留空（可於左側上傳『簡版-工單缺料狀況』）。")

# ── 篩選 ──────────────────────────────────────────────────────────────────────
st.divider()
STATUS_OPTS = {
    "⚠️ 缺料": "⚠️", "✅ 齊料": "✅", "📦 現貨滿足": "📦",
    "⛔ 短缺無在製": "⛔", "ℹ️ 委外板階(料況不明)": "ℹ️",
}
fc1, fc2, fc3 = st.columns([2, 2, 3])
with fc1:
    view = st.selectbox("板階料況", ["全部"] + list(STATUS_OPTS.keys()))
with fc2:
    bal_view = st.selectbox("結存判斷", ["全部", "負（生產較慢）", "正（生產較快）"])
with fc3:
    kw = st.text_input("搜尋組裝工單 / 組裝品號 / 板階品號", placeholder="輸入關鍵字")

df_show = df_all.copy()
if view != "全部":
    df_show = df_show[df_show["板階料況"].str.startswith(STATUS_OPTS[view])]
if bal_view.startswith("負"):
    df_show = df_show[df_show["結存判斷"].str.startswith("負")]
elif bal_view.startswith("正"):
    df_show = df_show[df_show["結存判斷"].str.startswith("正")]
if kw.strip():
    k = kw.strip()
    df_show = df_show[
        df_show["組裝工單"].str.contains(k, na=False) |
        df_show["組裝品號"].str.contains(k, na=False) |
        df_show["板階品號"].str.contains(k, na=False)
    ]

# ── 彙總表 ────────────────────────────────────────────────────────────────────
DISPLAY_COLS = ["組裝工單", "組裝品號", "開工日", "出貨日", "板階品號", "板階庫別",
                "板階需求量", "板階結存", "結存判斷", "對應板階工單",
                "板階完工日", "板階料況"]

def hl(row):
    s = row["板階料況"]
    if s.startswith("✅"):
        bg = "background-color:#f0fdf4;color:#15803d;"
    elif s.startswith("📦"):
        bg = "background-color:#eff6ff;color:#1d4ed8;"
    elif s.startswith("⚠️"):
        bg = "background-color:#fff1f2;color:#dc2626;"
    elif s.startswith("⛔"):
        bg = "background-color:#fee2e2;color:#991b1b;font-weight:bold;"
    else:  # ℹ️ 委外板階
        bg = "background-color:#fefce8;color:#854d0e;"
    return [bg] * len(row)

st.dataframe(
    df_show[DISPLAY_COLS].style.apply(hl, axis=1),
    use_container_width=True, height=460, hide_index=True,
    column_config={
        "組裝工單":   st.column_config.TextColumn(width=160),
        "組裝品號":   st.column_config.TextColumn(width=210),
        "出貨日":     st.column_config.TextColumn(width=100),
        "板階品號":   st.column_config.TextColumn(width=230),
        "板階需求量": st.column_config.NumberColumn(format="%d"),
        "板階結存":   st.column_config.NumberColumn(format="%d"),
        "對應板階工單": st.column_config.TextColumn(width=150),
    },
)
st.caption(f"顯示 {len(df_show):,} 筆 / 共 {len(df_all):,} 筆")

# ── 板階缺料明細（可展開）─────────────────────────────────────────────────────
short_rows = df_show[df_show["板階料況"].str.startswith("⚠️")]
if not short_rows.empty:
    st.divider()
    st.markdown(f"### 🔍 板階缺料明細（{len(short_rows)} 張板階工單）")
    for _, r in short_rows.iterrows():
        comp = r["板階完工日"]
        comp_str = comp.strftime("%Y/%m/%d") if comp else "—"
        _ship = r["出貨日"] or "—"
        with st.expander(
            f"⚠️ {r['組裝工單']}　｜　板階 {r['板階品號']}　"
            f"｜　開工 {r['開工日']}　｜　出貨 {_ship}　｜　{r['結存判斷']}（結存 {r['板階結存']:,}）　"
            f"｜　板階工單 {r['對應板階工單']}（完工 {comp_str}）　｜　{r['板階料況']}"
        ):
            sd = pd.DataFrame(
                [{"缺料料件": cp, "庫別": cwh, "需求量": int(round(cq)),
                  "預計結存": int(round(cb)), "缺料數量": int(round(sq))}
                 for cp, cwh, cq, cb, sq in r["_short"]]
            )
            st.dataframe(sd, hide_index=True, use_container_width=True)

# ── 匯出 Excel ────────────────────────────────────────────────────────────────
exp = df_all[DISPLAY_COLS].copy()
exp["板階缺料明細"] = df_all["_short"].apply(
    lambda lst: "；".join(f"{cp}(結存{int(round(cb))}/缺{int(round(sq))})"
                          for cp, cwh, cq, cb, sq in lst) if lst else ""
)
buf = io.BytesIO()
exp.to_excel(buf, index=False, engine="openpyxl")
buf.seek(0)
st.download_button(
    "⬇️ 匯出全廠料況追蹤（Excel）",
    data=buf,
    file_name=f"全廠料況追蹤_{date_start}~{date_end}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)
