import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import io, os, sys
from datetime import date, timedelta, datetime
from streamlit_autorefresh import st_autorefresh

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from utils.shared import render_sidebar
from db import queries as wh_db

st.set_page_config(page_title="倉儲備料看板", page_icon="🏭",
                   layout="wide", initial_sidebar_state="expanded")

# 每 20 分鐘自動刷新一次（1200000 ms）
st_autorefresh(interval=20 * 60 * 1000, key="wh_autorefresh")

st.markdown("""
<style>
/* ══ 倉儲看板：珍珠白 × 香檳金 ══ */
.stApp { background:#F7F5EF !important; }
[data-testid="stHeader"]  { background:transparent !important; }
[data-testid="stSidebar"] { background:#fdfbf6 !important; }
.block-container { padding:0.5rem 1.4rem 2rem !important; max-width:100% !important; }
#MainMenu, footer, [data-testid="stToolbar"] { visibility:hidden; }
[data-testid="stSidebar"], [data-testid="collapsedControl"] { display:none !important; }
.block-container { padding-left:1.4rem !important; }
::-webkit-scrollbar { width:6px; }
::-webkit-scrollbar-track { background:#EDE5CF; }
::-webkit-scrollbar-thumb { background:#C9A45C; border-radius:4px; }
.js-plotly-plot .plotly .bg { fill:transparent !important; }
html, body, [class*="css"] {
    font-size:18px !important;
    font-family:"Arial,標楷體,DFKai-SB,serif","微軟正黑體",sans-serif !important;
}
p { color:#1D2B3A !important; }
label { color:#6B7280 !important; }
div[data-testid="stButton"] > button {
    background:#C9A45C !important;
    border:none !important; color:#ffffff !important;
    font-size:15px !important; font-weight:700 !important;
    border-radius:8px !important; padding:7px 16px !important;
    box-shadow:0 2px 10px rgba(201,164,92,0.35) !important;
}
div[data-testid="stButton"] > button:hover {
    background:#b8922a !important;
}
</style>
""", unsafe_allow_html=True)

TODAY = date.today()
NOW   = datetime.now()

# ── 台灣國定假日（依行政院人事行政總處公告，請每年更新）──
TW_HOLIDAYS = {
    # 2026
    date(2026,  1,  1),  # 元旦
    date(2026,  1, 27),  # 春節補假
    date(2026,  1, 28),  # 除夕
    date(2026,  1, 29),  # 春節
    date(2026,  1, 30),  # 春節
    date(2026,  1, 31),  # 春節
    date(2026,  2,  1),  # 春節
    date(2026,  2,  2),  # 春節
    date(2026,  2, 28),  # 和平紀念日
    date(2026,  4,  4),  # 兒童節
    date(2026,  4,  5),  # 清明節
    date(2026,  6, 19),  # 端午節
    date(2026,  6, 20),  # 端午節補假
    date(2026,  9, 26),  # 中秋節
    date(2026, 10, 10),  # 國慶日
}

# ══════════════════════════════════════════════════════
# 手動上傳解析（NAS 離線 / 雲端使用）
# ══════════════════════════════════════════════════════
def _parse_upload(file_bytes):
    """直接從上傳 Excel 解析為 (diao, inbound)，格式同 queries.load_wh()。"""
    xls = pd.ExcelFile(io.BytesIO(file_bytes))

    def _hdf(sheet):
        df = pd.read_excel(xls, sheet_name=sheet, header=None)
        df.columns = df.iloc[0]
        return df.iloc[1:].reset_index(drop=True)

    diao = _hdf("調撥單")
    for c in ["開單日", "需求日", "備料日", "完成日"]:
        if c in diao.columns:
            diao[c] = pd.to_datetime(diao[c], errors="coerce")
    for c in ["需求筆數", "完成筆數"]:
        if c in diao.columns:
            diao[c] = pd.to_numeric(diao[c], errors="coerce").fillna(0)

    inbound = _hdf("入庫單據")
    for c in ["驗畢日期", "接單日期", "預計完成日", "完成日", "取單日"]:
        if c in inbound.columns:
            inbound[c] = pd.to_datetime(inbound[c], errors="coerce")
    if "筆數" in inbound.columns:
        inbound["筆數"] = pd.to_numeric(inbound["筆數"], errors="coerce").fillna(0)

    return diao, inbound

# ── 判斷資料來源 ──────────────────────────────────────
_has_upload = "wh_upload_bytes" in st.session_state

if _has_upload:
    db_ready  = True
    src_mtime = st.session_state.get("wh_upload_ts")
    src_name  = st.session_state.get("wh_upload_name", "手動上傳")
    sched_df  = pd.DataFrame()
else:
    # ══════════════════════════════════════════════════════
    # 資料來源：SQLite（由 db/import_to_db.py 從 NAS 匯入）
    # ══════════════════════════════════════════════════════
    @st.cache_data(ttl=20*60, show_spinner=False)
    def load_sched(_mtime_key):
        try:
            return wh_db.load_sched()
        except Exception:
            return pd.DataFrame()

    db_ready  = wh_db.db_exists()
    src_mtime = wh_db.db_mtime() if db_ready else None
    src_name  = wh_db.source_filename() if db_ready else None
    sched_df  = load_sched(str(src_mtime)) if db_ready else pd.DataFrame()

# ══════════════════════════════════════════════════════
# HEADER
# ══════════════════════════════════════════════════════
st.markdown(
    '<div style="margin-bottom:6px">'
    '<a href="/" target="_self" style="color:#C9A45C;text-decoration:none;'
    'font-size:13px;font-weight:600;opacity:0.85">← 返回主頁</a></div>',
    unsafe_allow_html=True
)

wday_names = ["一","二","三","四","五","六","日"]
wday   = wday_names[TODAY.weekday()]
data_ts = src_mtime.strftime('%m/%d %H:%M') if src_mtime else "⚠️ 離線"

st.markdown(
    f'<div style="background:linear-gradient(90deg,#1D2B3A 0%,#253444 50%,#1D2B3A 100%);'
    f'border:none;border-bottom:3px solid #C9A45C;border-radius:14px;padding:18px 28px;margin-bottom:18px;'
    f'box-shadow:0 4px 20px rgba(29,43,58,0.18);'
    f'display:grid;grid-template-columns:1fr auto 1fr;align-items:center;gap:16px">'
    f'<div>'
    f'<div style="color:#C9A45C;font-size:13px;font-weight:600;letter-spacing:1.5px">ORing &nbsp;·&nbsp; 倉管 WD</div>'
    f'<div style="color:#a8916a;font-size:13px;margin-top:4px">'
    f'🕐 {NOW.strftime("%H:%M")} &nbsp;｜&nbsp; 資料：{data_ts}</div>'
    f'</div>'
    f'<div style="text-align:center">'
    f'<div style="color:#ffffff;font-size:38px;font-weight:900;line-height:1.15;letter-spacing:0.5px">'
    f'倉儲備料即時看板</div>'
    f'<div style="color:#C9A45C;font-size:13px;font-weight:400;letter-spacing:4px;margin-top:5px">'
    f'WAREHOUSE MATERIAL PREP DASHBOARD</div>'
    f'</div>'
    f'<div style="text-align:right">'
    f'<div style="color:#ffffff;font-size:30px;font-weight:900">{TODAY.strftime("%Y / %m / %d")}</div>'
    f'<div style="color:#C9A45C;font-size:18px;font-weight:700;margin-top:2px">（週{wday}）</div>'
    f'</div></div>',
    unsafe_allow_html=True
)

# ── 資料庫狀態列 ─────────────────────────────────────
if db_ready:
    ts_str = src_mtime.strftime('%m/%d %H:%M') if src_mtime else "手動上傳"
    _mode_badge = (
        f'<span style="color:#C9A45C;margin-left:16px;font-size:12px">📂 手動上傳模式</span>'
        if _has_upload else
        f'<span style="color:#C9A45C;margin-left:16px;font-size:12px">🔄 每 20 分鐘自動更新</span>'
    )
    _clear_hint = (
        '<span style="color:#94a3b8;margin-left:12px;font-size:11px">（重新整理頁面可清除上傳）</span>'
        if _has_upload else ""
    )
    st.markdown(
        f'<div style="background:#ffffff;border:1px solid #b2dfdb;'
        f'border-radius:8px;padding:8px 16px;font-size:13px;color:#2E9D70;margin-bottom:4px">'
        f'✅ &nbsp;資料已載入 &nbsp;·&nbsp; '
        f'<b style="color:#2E9D70">{src_name or "wh_dashboard.db"}</b>'
        f'<span style="color:#6B7280;margin-left:8px">（{ts_str}）</span>'
        f'{_mode_badge}{_clear_hint}'
        f'</div>',
        unsafe_allow_html=True
    )
    if _has_upload:
        with st.expander("📂 重新上傳或切換回 NAS 模式"):
            _reup = st.file_uploader(
                "重新上傳「調件備料統計表.xlsx」",
                type=["xlsx", "xls"],
                key="wh_reupload",
            )
            if _reup is not None:
                st.session_state["wh_upload_bytes"] = _reup.read()
                st.session_state["wh_upload_name"]  = _reup.name
                st.session_state["wh_upload_ts"]    = pd.Timestamp.now()
                st.rerun()
            if st.button("🗑 清除上傳，切換回 NAS / 資料庫模式", use_container_width=True):
                st.session_state.pop("wh_upload_bytes", None)
                st.session_state.pop("wh_upload_name", None)
                st.session_state.pop("wh_upload_ts", None)
                st.rerun()
else:
    st.markdown(
        '<div style="background:rgba(239,68,68,0.1);border:1px solid rgba(239,68,68,0.4);'
        'border-radius:8px;padding:10px 16px;margin-bottom:8px;color:#ef4444;font-size:14px">'
        '⚠️ &nbsp;NAS 離線或尚未建立資料庫。請上傳「調件備料統計表.xlsx」以繼續。</div>',
        unsafe_allow_html=True
    )
    with st.expander("📂 上傳「調件備料統計表.xlsx」", expanded=True):
        _up = st.file_uploader(
            "上傳調件備料統計表（含「調撥單」與「入庫單據」工作表）",
            type=["xlsx", "xls"],
            key="wh_inline_upload",
        )
        if _up is not None:
            st.session_state["wh_upload_bytes"] = _up.read()
            st.session_state["wh_upload_name"]  = _up.name
            st.session_state["wh_upload_ts"]    = pd.Timestamp.now()
            st.rerun()
    st.stop()

# ══════════════════════════════════════════════════════
# 讀取資料（SQLite 或手動上傳）
# ══════════════════════════════════════════════════════
if _has_upload:
    with st.spinner("解析上傳檔案中…"):
        try:
            diao, inbound = _parse_upload(st.session_state["wh_upload_bytes"])
        except Exception as e:
            st.error(f"解析失敗：{e}\n\n請確認檔案包含「調撥單」與「入庫單據」工作表。")
            st.stop()
else:
    @st.cache_data(ttl=5*60, show_spinner=False)
    def load_wh(_mtime_key):
        return wh_db.load_wh()

    with st.spinner("載入資料中…"):
        diao, inbound = load_wh(str(src_mtime))

# ══════════════════════════════════════════════════════
# 計算 KPI（顯示前一工作日數值）
# ══════════════════════════════════════════════════════
def _prev_workday(d):
    """回傳 d 的前一個工作日（跳過週六、週日及國定假日）"""
    prev = d - timedelta(days=1)
    while prev.weekday() >= 5 or prev in TW_HOLIDAYS:
        prev -= timedelta(days=1)
    return prev

YESTERDAY = _prev_workday(TODAY)

# ── 備料（調撥單）──────────────────────────────────────
# 已完成：K欄（完成日）= 昨日 且 M欄（狀態）= 已完成 → 加總 G欄（需求筆數）
b_done_rows = diao[
    diao['完成日'].notna() &
    (diao['完成日'].dt.date == YESTERDAY) &
    (diao['狀態'] == '已完成')
]
b_done = int(b_done_rows['需求筆數'].sum())

# 已完成拆分：E欄（需求單位）含「生產加工」或「廠內」→ 廠內，其餘 → 委外
_inhouse_mask = b_done_rows['需求單位'].astype(str).str.contains('生產加工|廠內', na=False)
b_done_inhouse  = int(b_done_rows[_inhouse_mask]['需求筆數'].sum())
b_done_outsource = b_done - b_done_inhouse

# 待完成：F欄（需求日）有值 且 <= 昨日 且 K欄（完成日）空白 → 加總 G欄
b_pend_rows = diao[
    diao['需求日'].notna() &
    (diao['需求日'].dt.date <= YESTERDAY) &
    diao['完成日'].isna()
]
b_pend = int(b_pend_rows['需求筆數'].sum())

# 待完成拆分：E欄（需求單位）含「生產加工」或「廠內」→ 廠內，其餘 → 委外
_pend_inhouse_mask = b_pend_rows['需求單位'].astype(str).str.contains('生產加工|廠內', na=False)
b_pend_inhouse   = int(b_pend_rows[_pend_inhouse_mask]['需求筆數'].sum())
b_pend_outsource = b_pend - b_pend_inhouse

b_total = b_done + b_pend
b_rate  = b_done / b_total if b_total else 0

# ── 入庫 ────────────────────────────────────────────────
# 已完成：調撥單 M欄=上架 且 K欄=昨日 → 加總 H欄（完成筆數）
ib_done_rows = diao[
    (diao['狀態'] == '上架') &
    diao['完成日'].notna() &
    (diao['完成日'].dt.date == YESTERDAY)
]
i_done = int(ib_done_rows['完成筆數'].sum())

# 待完成：入庫單據 I欄（完成日）空白 → 加總 G欄（筆數）
ib_pend_rows = inbound[inbound['完成日'].isna()]
i_pend = int(ib_pend_rows['筆數'].sum())

i_total = i_done + i_pend
i_rate  = i_done / i_total if i_total else 0

# ── 前日最高績效：備料 / 入庫 分開計算 ────────────────
# 備料最高
b_by_person = (
    b_done_rows.groupby('備料人員')['需求筆數'].sum()
    .reset_index().rename(columns={'備料人員':'人員','需求筆數':'筆數'})
)
b_total_done = int(b_by_person['筆數'].sum())
if not b_by_person.empty and b_total_done > 0:
    top_b_row  = b_by_person.loc[b_by_person['筆數'].idxmax()]
    top_b_name = str(top_b_row['人員'])
    top_b_cnt  = int(top_b_row['筆數'])
    top_b_pct  = round(top_b_cnt / b_total_done * 100, 1)
else:
    top_b_name = "—"; top_b_cnt = 0; top_b_pct = 0.0

# 入庫最高
i_by_person = (
    ib_done_rows.groupby('備料人員')['完成筆數'].sum()
    .reset_index().rename(columns={'備料人員':'人員','完成筆數':'筆數'})
) if not ib_done_rows.empty else pd.DataFrame(columns=['人員','筆數'])
i_total_done = int(i_by_person['筆數'].sum()) if not i_by_person.empty else 0
if not i_by_person.empty and i_total_done > 0:
    top_i_row  = i_by_person.loc[i_by_person['筆數'].idxmax()]
    top_i_name = str(top_i_row['人員'])
    top_i_cnt  = int(top_i_row['筆數'])
    top_i_pct  = round(top_i_cnt / i_total_done * 100, 1)
else:
    top_i_name = "—"; top_i_cnt = 0; top_i_pct = 0.0

# ══════════════════════════════════════════════════════
# SECTION 1：早會 KPI 三卡片
# ══════════════════════════════════════════════════════
st.markdown(
    f'<div style="color:#6B7280;font-size:16px;font-weight:700;letter-spacing:1px;margin-bottom:12px">'
    f'📊 前日進度概況（{YESTERDAY.strftime("%m/%d")}）</div>',
    unsafe_allow_html=True
)

def _kpi_card(title, done, pend, rate, icon, daily_target=None,
              done_breakdown=None, pend_breakdown=None):
    total = done + pend
    pct   = int(rate * 100)

    # 廠內／委外拆分小標籤（例：廠內 180・委外 79）
    def _bd_label(bd):
        if not bd: return ""
        in_cnt, out_cnt = bd
        return (
            f'<div style="color:#9CA3AF;font-size:12px;margin-top:4px;white-space:nowrap">'
            f'廠內 {in_cnt:,}・委外 {out_cnt:,}</div>'
        )
    done_breakdown_html = _bd_label(done_breakdown)
    pend_breakdown_html = _bd_label(pend_breakdown)

    if rate >= 0.8:   status_txt,status_c = "達標",    "#2E9D70"
    elif rate >= 0.5: status_txt,status_c = "持續推進", "#d97706"
    else:             status_txt,status_c = "進度落後", "#B23A48"

    # Q3 目標比較區塊
    q3_block = ""
    if daily_target:
        diff     = done - daily_target
        diff_c   = "#2E9D70" if diff >= 0 else "#B23A48"
        diff_sym = "▲" if diff >= 0 else "▼"
        diff_lbl = "達標" if diff >= 0 else "未達標"
        bar_pct  = min(int(done / daily_target * 100), 100)
        q3_block = (
            f'<div style="margin-top:14px;border-top:1px dashed #E6D8B8;padding-top:10px">'
            f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">'
            f'<span style="color:#6B7280;font-size:13px;font-weight:600">🎯 第3季每日指標：{daily_target:,} 筆</span>'
            f'<span style="color:{diff_c};font-size:13px;font-weight:700">'
            f'{diff_sym} {abs(diff)} &nbsp;{diff_lbl}</span>'
            f'</div>'
            f'<div style="display:flex;align-items:center;gap:10px">'
            f'<div style="flex:1;background:#f5ede0;border-radius:4px;height:7px;overflow:hidden">'
            f'<div style="width:{bar_pct}%;height:100%;'
            f'background:{"linear-gradient(90deg,#2E9D70,#3bb892)" if diff>=0 else "linear-gradient(90deg,#B23A48,#e05a6a)"}"></div>'
            f'</div>'
            f'<span style="color:{diff_c};font-size:13px;font-weight:700;min-width:36px">{bar_pct}%</span>'
            f'</div></div>'
        )

    return (
        f'<div style="background:#FFFFFF;'
        f'border:1px solid #E6D8B8;border-top:3px solid #C9A45C;'
        f'border-radius:14px;padding:22px 24px;'
        f'box-shadow:0 2px 16px rgba(29,43,58,0.08);height:100%">'
        f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">'
        f'<div style="color:#1D2B3A;font-size:15px;font-weight:700;letter-spacing:1px">{icon} {title}</div>'
        f'<div style="background:#fafaf5;border:1px solid #E6D8B8;border-radius:20px;'
        f'padding:3px 12px;color:{status_c};font-size:13px;font-weight:600">{status_txt}</div>'
        f'</div>'
        f'<div style="display:flex;gap:0;margin-bottom:18px">'
        f'<div style="flex:1;text-align:center;border-right:1px solid #EDE5CF">'
        f'<div style="color:#2E9D70;font-size:54px;font-weight:900;line-height:1">{done:,}</div>'
        f'<div style="color:#6B7280;font-size:14px;margin-top:6px">已完成</div>'
        f'{done_breakdown_html}</div>'
        f'<div style="flex:1;text-align:center;border-right:1px solid #EDE5CF">'
        f'<div style="color:#B23A48;font-size:54px;font-weight:900;line-height:1">{pend:,}</div>'
        f'<div style="color:#6B7280;font-size:14px;margin-top:6px">待完成</div>'
        f'{pend_breakdown_html}</div>'
        f'<div style="flex:1;text-align:center">'
        f'<div style="color:#C9A45C;font-size:54px;font-weight:900;line-height:1">{pct}%</div>'
        f'<div style="color:#6B7280;font-size:14px;margin-top:6px">完成率</div></div>'
        f'</div>'
        f'<div style="background:#f5ede0;border-radius:4px;height:8px;overflow:hidden">'
        f'<div style="display:flex;height:100%">'
        f'<div style="width:{pct}%;background:linear-gradient(90deg,#2E9D70,#3bb892)"></div>'
        f'<div style="width:{100-pct}%;background:#f5c6cc"></div>'
        f'</div></div>'
        f'<div style="color:#6B7280;font-size:13px;margin-top:6px;text-align:right">'
        f'目標總筆數：{total:,}</div>'
        f'{q3_block}</div>'
    )

# 第三卡片：備料最高 / 入庫最高 分開顯示
def _top_person_card():
    def _half(label, name, cnt, pct, num_c, bar_c):
        bar_w = min(int(pct), 100)
        return (
            f'<div style="flex:1;padding:14px 16px;'
            f'background:#fdfaf5;border-radius:10px;border:1px solid #EDE5CF">'
            f'<div style="color:#6B7280;font-size:13px;letter-spacing:0.5px;margin-bottom:8px">{label}</div>'
            f'<div style="color:#1D2B3A;font-size:30px;font-weight:900;line-height:1">{name}</div>'
            f'<div style="display:flex;align-items:baseline;gap:8px;margin-top:10px">'
            f'<span style="color:{num_c};font-size:38px;font-weight:900">{cnt:,}</span>'
            f'<span style="color:#6B7280;font-size:14px">筆</span>'
            f'<span style="color:#C9A45C;font-size:17px;font-weight:700;margin-left:4px">{pct}%</span>'
            f'</div>'
            f'<div style="color:#6B7280;font-size:12px;margin-top:4px">佔當日該項目總量</div>'
            f'<div style="background:#EDE5CF;border-radius:3px;height:5px;overflow:hidden;margin-top:8px">'
            f'<div style="width:{bar_w}%;height:100%;background:{bar_c}"></div></div>'
            f'</div>'
        )

    return (
        f'<div style="background:#FFFFFF;'
        f'border:1px solid #E6D8B8;border-top:3px solid #C9A45C;'
        f'border-radius:14px;padding:20px 22px;'
        f'box-shadow:0 2px 16px rgba(29,43,58,0.08);height:100%">'
        f'<div style="color:#1D2B3A;font-size:15px;font-weight:700;letter-spacing:1px;margin-bottom:14px">'
        f'🏆 前日最高績效</div>'
        f'<div style="display:flex;gap:10px">'
        + _half("📦 備料", top_b_name, top_b_cnt, top_b_pct, "#2E9D70", "#2E9D70")
        + _half("🏭 上架", top_i_name, top_i_cnt, top_i_pct, "#B23A48", "#B23A48")
        + f'</div></div>'
    )

c1, c2, c3 = st.columns(3)
c1.markdown(_kpi_card("備料", b_done, b_pend, b_rate, "📦", daily_target=200,
                      done_breakdown=(b_done_inhouse, b_done_outsource),
                      pend_breakdown=(b_pend_inhouse, b_pend_outsource)), unsafe_allow_html=True)
c2.markdown(_kpi_card("上架", i_done, i_pend, i_rate, "🏭", daily_target=100), unsafe_allow_html=True)
c3.markdown(_top_person_card(), unsafe_allow_html=True)

st.markdown("<div style='margin-top:20px'></div>", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════
# SECTION 2：人員今日完成筆數 + 入庫延遲警示
# ══════════════════════════════════════════════════════
col_person, col_alert = st.columns([3, 2])

with col_person:
    st.markdown(
        '<div style="color:#1D2B3A;font-size:16px;font-weight:800;letter-spacing:0.3px;margin-bottom:12px">'
        '📦 預計出貨量（5週 pcs）</div>',
        unsafe_allow_html=True
    )
    if sched_df.empty:
        st.markdown(
            '<div style="background:#fdfaf5;border:1px solid #E6D8B8;border-radius:8px;'
            'padding:20px;text-align:center;color:#6B7280">— 無法讀取排程資料 —</div>',
            unsafe_allow_html=True
        )
    else:
        # 計算5週數據（同工單看板邏輯）
        _wd_s  = TODAY.weekday()
        _wmon  = TODAY - timedelta(days=_wd_s)
        _slabs, _srq, _slq = [], [], []
        for _wi in range(5):
            _ws = _wmon + timedelta(weeks=_wi)
            _we = _ws + timedelta(days=4)
            _wn = _ws.isocalendar()[1]
            _sub = sched_df[
                sched_df['出貨日'].notna() &
                (sched_df['出貨日'] >= _ws) &
                (sched_df['出貨日'] <= _we)
            ]
            _tq = int(_sub['預計產量'].dropna().sum())
            _rq = int(_sub[_sub['料況狀態']=='已齊料']['預計產量'].dropna().sum())
            _slabs.append(f"W{_wn}<br>{_ws.strftime('%m/%d')}~{_we.strftime('%m/%d')}")
            _srq.append(_rq)
            _slq.append(_tq - _rq)

        fig_ship = go.Figure()
        fig_ship.add_trace(go.Bar(
            name="已齊料 pcs", x=_slabs, y=_srq,
            marker=dict(color="rgba(46,157,112,0.80)", line=dict(color="#2E9D70", width=1.5)),
        ))
        fig_ship.add_trace(go.Bar(
            name="缺料 pcs", x=_slabs, y=_slq,
            marker=dict(color="rgba(178,58,72,0.70)", line=dict(color="#B23A48", width=1.5)),
        ))
        # 頂部標籤
        _annots = []
        for _i, (_rq2, _lq2) in enumerate(zip(_srq, _slq)):
            _tot = _rq2 + _lq2
            if _tot > 0:
                _annots.append(dict(
                    x=_slabs[_i], y=_tot,
                    text=f"<b>共 {_tot:,}</b><br><span style='font-size:12px'>齊 {_rq2:,} ｜ 缺 {_lq2:,}</span>",
                    xanchor="center", yanchor="bottom", showarrow=False,
                    font=dict(size=13, color="#1D2B3A", family="Arial,標楷體,DFKai-SB,serif"),
                    bgcolor="rgba(253,250,245,0.9)",
                    bordercolor="#E6D8B8", borderwidth=1, borderpad=4,
                ))
        fig_ship.update_layout(
            barmode="stack",
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            annotations=_annots,
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
                        font=dict(color="#1D2B3A", size=13), bgcolor="rgba(255,255,255,0.8)"),
            xaxis=dict(showgrid=False, tickfont=dict(color="#1D2B3A", size=13,
                       family="Arial,標楷體,DFKai-SB,serif")),
            yaxis=dict(showgrid=True, gridcolor="#EDE5CF",
                       tickfont=dict(color="#6B7280", size=12), zeroline=False),
            margin=dict(l=10, r=10, t=60, b=10), height=320,
            font=dict(family="Arial,標楷體,DFKai-SB,serif"),
        )
        st.plotly_chart(fig_ship, use_container_width=True,
                        config=dict(staticPlot=True))

with col_alert:
    # ── 今日即時訊息 ────────────────────────────────────
    today_b_rows = diao[
        (diao['狀態'] == '已完成') &
        diao['完成日'].notna() &
        (diao['完成日'].dt.date == TODAY)
    ]
    today_i_rows = diao[
        (diao['狀態'] == '上架') &
        diao['完成日'].notna() &
        (diao['完成日'].dt.date == TODAY)
    ]
    today_b_cnt = int(today_b_rows['需求筆數'].sum())
    today_i_cnt = int(today_i_rows['完成筆數'].sum())

    # 今日新增：開單日 = 今日（不論狀態）
    today_new_rows = diao[
        diao['開單日'].notna() &
        (diao['開單日'].dt.date == TODAY)
    ]
    today_new_cnt = int(today_new_rows['需求筆數'].sum())

    st.markdown(
        f'<div style="background:#FFFFFF;'
        f'border:1px solid #E6D8B8;border-top:3px solid #C9A45C;'
        f'border-radius:12px;padding:16px 18px;height:100%;'
        f'box-shadow:0 2px 14px rgba(29,43,58,0.08)">'
        f'<div style="color:#1D2B3A;font-size:15px;font-weight:700;letter-spacing:0.5px;margin-bottom:14px">'
        f'⚡ 今日即時進度（{TODAY.strftime("%m/%d")} {NOW.strftime("%H:%M")} 止）</div>'
        f'<div style="display:flex;gap:0">'
        f'<div style="flex:1;text-align:center;border-right:1px solid #EDE5CF;padding:10px 0">'
        f'<div style="color:#2E9D70;font-size:52px;font-weight:900;line-height:1">{today_b_cnt:,}</div>'
        f'<div style="color:#6B7280;font-size:14px;margin-top:6px">📦 備料完成</div></div>'
        f'<div style="flex:1;text-align:center;border-right:1px solid #EDE5CF;padding:10px 0">'
        f'<div style="color:#B23A48;font-size:52px;font-weight:900;line-height:1">{today_i_cnt:,}</div>'
        f'<div style="color:#6B7280;font-size:14px;margin-top:6px">🏭 上架完成</div></div>'
        f'<div style="flex:1;text-align:center;padding:10px 0">'
        f'<div style="color:#3B82F6;font-size:52px;font-weight:900;line-height:1">{today_new_cnt:,}</div>'
        f'<div style="color:#6B7280;font-size:14px;margin-top:6px">➕ 今日新增</div></div>'
        f'</div>'
        f'<div style="margin-top:14px;border-top:1px solid #EDE5CF;padding-top:12px">'
        f'<div style="color:#6B7280;font-size:13px;margin-bottom:8px">今日備料人員</div>',
        unsafe_allow_html=True
    )
    if not today_b_rows.empty:
        by_p = today_b_rows.groupby('備料人員')['需求筆數'].sum().sort_values(ascending=False)
        for person, cnt in by_p.items():
            st.markdown(
                f'<div style="display:flex;justify-content:space-between;padding:5px 0;'
                f'border-bottom:1px solid #f5ede0">'
                f'<span style="color:#1D2B3A;font-size:14px">{person}</span>'
                f'<span style="color:#C9A45C;font-size:14px;font-weight:700">{int(cnt)} 筆</span>'
                f'</div>',
                unsafe_allow_html=True
            )
    else:
        st.markdown('<div style="color:#6B7280;font-size:13px">— 今日尚無備料完成記錄 —</div>',
                    unsafe_allow_html=True)
    st.markdown('</div></div>', unsafe_allow_html=True)

st.markdown("<div style='margin-top:24px'></div>", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════
# SECTION 3：近5週 — 備料 / 入庫 各自獨立圖表＋表格
# ══════════════════════════════════════════════════════

def _workdays_in_week(wk_start, wk_end):
    """計算日期區間內的工作日數（排除週六日）"""
    count = 0
    d = wk_start
    while d <= wk_end:
        if d.weekday() < 5:
            count += 1
        d += timedelta(days=1)
    return max(count, 1)

st.markdown(
    '<div style="color:#1D2B3A;font-size:16px;font-weight:800;letter-spacing:0.3px;margin-bottom:14px">'
    '📅 近5週完成筆數</div>', unsafe_allow_html=True
)

# 計算本週一 & 各週數據
_wd0 = TODAY.weekday()
this_mon = TODAY - timedelta(days=_wd0)

week_short   = []   # 短標籤（表格用）
week_labels  = []   # 長標籤（圖表用）
week_b, week_i = [], []
week_workdays = []  # 各週工作日數

for w in range(5, 0, -1):
    wk_start = this_mon - timedelta(weeks=w)
    wk_end   = wk_start + timedelta(days=4)   # Mon~Fri
    wnum = wk_start.isocalendar()[1]
    lbl  = f"W{wnum}"
    mask = (diao['完成日'].notna() &
            (diao['完成日'].dt.date >= wk_start) &
            (diao['完成日'].dt.date <= wk_end))
    wd   = _workdays_in_week(wk_start, min(wk_end, TODAY))  # 本週只算到今天
    week_short.append(f"{lbl}\n{wk_start.strftime('%m/%d')}")
    week_labels.append(f"{lbl}<br>{wk_start.strftime('%m/%d')}~{wk_end.strftime('%m/%d')}")
    week_b.append(int(diao[mask & (diao['狀態']=='已完成')]['需求筆數'].sum()))
    week_i.append(int(diao[mask & (diao['狀態']=='上架')]['完成筆數'].sum()))
    week_workdays.append(wd)

def _bar_chart(labels, values, color_fill, color_line, height=240):
    fig = go.Figure(go.Bar(
        x=labels, y=values,
        marker=dict(color=color_fill, line=dict(color=color_line, width=1.5)),
        text=[f"{v:,}" if v else "0" for v in values],
        textposition="outside",
        textfont=dict(color=color_line, size=14, family="Arial,標楷體,DFKai-SB,serif"),
    ))
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
        xaxis=dict(showgrid=False, tickfont=dict(color="#1D2B3A", size=13,
                   family="Arial,標楷體,DFKai-SB,serif")),
        yaxis=dict(showgrid=True, gridcolor="#EDE5CF",
                   tickfont=dict(color="#6B7280", size=12), zeroline=False),
        margin=dict(l=10, r=10, t=36, b=10), height=height,
    )
    return fig

def _mini_table(row_label, labels, values, val_color, workdays=None):
    """HTML 小表格：完成筆數 + 每日平均"""
    th_style = (f'style="background:#1D2B3A;color:#ffffff;padding:8px 12px;'
                f'font-size:13px;font-weight:700;text-align:center;'
                f'border:1px solid #E6D8B8;font-family:Arial,標楷體,DFKai-SB,serif"')
    td_label = (f'style="background:#fdfaf5;color:#1D2B3A;padding:8px 12px;'
                f'font-size:13px;font-weight:700;border:1px solid #E6D8B8;'
                f'text-align:center;font-family:Arial,標楷體,DFKai-SB,serif;white-space:nowrap"')
    td_val   = (f'style="background:#ffffff;color:{val_color};padding:8px 12px;'
                f'font-size:15px;font-weight:900;border:1px solid #E6D8B8;'
                f'text-align:center;font-family:Arial,標楷體,DFKai-SB,serif"')
    td_avg   = (f'style="background:#fdfaf5;color:#C9A45C;padding:8px 12px;'
                f'font-size:14px;font-weight:700;border:1px solid #E6D8B8;'
                f'text-align:center;font-family:Arial,標楷體,DFKai-SB,serif"')

    ths  = "".join(f"<th {th_style}>{l}</th>" for l in labels)
    tds  = "".join(f"<td {td_val}>{v:,}</td>" for v in values)

    avg_row = ""
    if workdays:
        avgs = [round(v / wd, 1) if wd > 0 else 0
                for v, wd in zip(values, workdays)]
        tda  = "".join(f"<td {td_avg}>{a}</td>" for a in avgs)
        avg_row = f'<tr><td {td_label}>每日平均</td>{tda}</tr>'

    return (
        f'<div style="overflow-x:auto;margin-top:6px">'
        f'<table style="width:100%;border-collapse:collapse;border-radius:8px;overflow:hidden">'
        f'<tr><th {td_label}>{row_label}</th>{ths}</tr>'
        f'<tr><td {td_label}>完成筆數</td>{tds}</tr>'
        f'{avg_row}'
        f'</table></div>'
    )

col_w1, col_w2 = st.columns(2)

with col_w1:
    st.markdown('<div style="color:#2E9D70;font-size:15px;font-weight:700;margin-bottom:4px">📦 備料</div>',
                unsafe_allow_html=True)
    st.plotly_chart(_bar_chart(week_labels, week_b,
                               "rgba(46,157,112,0.75)", "#2E9D70"),
                    use_container_width=True, config=dict(staticPlot=True))
    st.markdown(_mini_table("近5週", week_short, week_b, "#2E9D70",
                            workdays=week_workdays), unsafe_allow_html=True)

with col_w2:
    st.markdown('<div style="color:#B23A48;font-size:15px;font-weight:700;margin-bottom:4px">🏭 上架</div>',
                unsafe_allow_html=True)
    st.plotly_chart(_bar_chart(week_labels, week_i,
                               "rgba(178,58,72,0.70)", "#B23A48"),
                    use_container_width=True, config=dict(staticPlot=True))
    st.markdown(_mini_table("近5週", week_short, week_i, "#B23A48",
                            workdays=week_workdays), unsafe_allow_html=True)

st.markdown("<div style='margin-top:28px'></div>", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════
# SECTION 4：年度月份 — 備料 / 入庫 各自獨立圖表＋表格
# ══════════════════════════════════════════════════════
st.markdown(
    f'<div style="color:#1D2B3A;font-size:16px;font-weight:800;letter-spacing:0.3px;margin-bottom:14px">'
    f'📆 年度月份完成筆數（{TODAY.year}年）</div>', unsafe_allow_html=True
)

month_labels_long  = [f"{m}月" for m in range(1, 13)]
month_labels_short = [f"{m}月" for m in range(1, 13)]
month_b, month_i = [], []

for m in range(1, 13):
    mask = (diao['完成日'].notna() &
            (diao['完成日'].dt.year == TODAY.year) &
            (diao['完成日'].dt.month == m))
    month_b.append(int(diao[mask & (diao['狀態']=='已完成')]['需求筆數'].sum()))
    month_i.append(int(diao[mask & (diao['狀態']=='上架')]['完成筆數'].sum()))

# 各月工作日數
def _workdays_in_month(year, m):
    from calendar import monthrange
    _, last = monthrange(year, m)
    d0 = date(year, m, 1)
    end = date(year, m, last)
    if end > TODAY: end = TODAY  # 當月只算到今天
    if end < d0: return 1
    return _workdays_in_week(d0, end)

month_workdays = [_workdays_in_month(TODAY.year, m) for m in range(1, 13)]

col_m1, col_m2 = st.columns(2)

with col_m1:
    st.markdown('<div style="color:#2E9D70;font-size:15px;font-weight:700;margin-bottom:4px">📦 備料</div>',
                unsafe_allow_html=True)
    st.plotly_chart(_bar_chart(month_labels_long, month_b,
                               "rgba(46,157,112,0.75)", "#2E9D70", height=260),
                    use_container_width=True, config=dict(staticPlot=True))
    st.markdown(_mini_table(f"{TODAY.year}", month_labels_short, month_b, "#2E9D70",
                            workdays=month_workdays), unsafe_allow_html=True)

with col_m2:
    st.markdown('<div style="color:#B23A48;font-size:15px;font-weight:700;margin-bottom:4px">🏭 上架</div>',
                unsafe_allow_html=True)
    st.plotly_chart(_bar_chart(month_labels_long, month_i,
                               "rgba(178,58,72,0.70)", "#B23A48", height=260),
                    use_container_width=True, config=dict(staticPlot=True))
    st.markdown(_mini_table(f"{TODAY.year}", month_labels_short, month_i, "#B23A48",
                            workdays=month_workdays), unsafe_allow_html=True)

# 頁尾
st.markdown(
    f'<div style="text-align:center;color:#1e3a5f;font-size:11px;margin-top:24px;letter-spacing:1px">'
    f'DATA · {src_name or "wh_dashboard.db"}'
    f' &nbsp;｜&nbsp; {NOW.strftime("%H:%M")} 更新</div>',
    unsafe_allow_html=True
)
