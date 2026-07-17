import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import io, os, sys
from datetime import date, timedelta, datetime
from streamlit_autorefresh import st_autorefresh

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from utils.shared import render_sidebar
from utils.leave_mail import fetch_today_leaves
from db import queries as wh_db

st.set_page_config(page_title="倉儲備料看板", page_icon="🏭",
                   layout="wide", initial_sidebar_state="expanded")

# 每 2 分鐘自動刷新；每次刷新會檢查 NAS 是否有新存檔，有就立即匯入（見下方 _auto_sync）
st_autorefresh(interval=2 * 60 * 1000, key="wh_autorefresh")

# ══════════════════════════════════════════════════════
# 設計系統（深色 · 午夜藍 × 香檳金）
# ══════════════════════════════════════════════════════
st.markdown("""
<style>
:root{
  --bg:#0C141D; --card:linear-gradient(160deg,#35506A,#2A3F54); --card2:#3B5167; --hilite:#3E5670;
  --ink:#EAF1F8; --ink2:#D7E1EA; --muted:#9DB0C0; --faint:#8094A6;
  --gold:#D9B36A; --gold-d:#B8922A; --border:#56718B; --line:#33475A; --track:#3D5365;
  --green:#43C08F; --red:#EC6A7C; --amber:#E5B454; --blue:#5AA8F0; --radius:16px;
}
.stApp{ color:#EAF1F8 !important; background:
   radial-gradient(1100px 540px at 100% -10%, #1A2A38 0%, rgba(26,42,56,0) 55%),
   radial-gradient(950px 480px at -8% 0%, #15222E 0%, rgba(21,34,46,0) 50%),
   #0C141D !important; }
[data-testid="stHeader"]{ background:transparent !important; }
.block-container{ padding:0.6rem 1.7rem 2.4rem !important; max-width:1720px !important; }
#MainMenu, footer, [data-testid="stToolbar"]{ visibility:hidden; }
[data-testid="stSidebar"], [data-testid="collapsedControl"]{ display:none !important; }
html, body, [class*="css"]{
  font-family:"微軟正黑體","Microsoft JhengHei","Noto Sans TC",Arial,sans-serif !important;
  -webkit-font-smoothing:antialiased; text-rendering:optimizeLegibility;
}
p{ color:#EAF1F8 !important; margin:0; } label{ color:#9DB0C0 !important; }
::-webkit-scrollbar{ width:8px; height:8px; }
::-webkit-scrollbar-track{ background:transparent; }
::-webkit-scrollbar-thumb{ background:#33485A; border-radius:6px; }
::-webkit-scrollbar-thumb:hover{ background:#D9B36A; }
.js-plotly-plot .plotly .bg{ fill:transparent !important; }

/* 收斂預設間距、列內等高，消除高高低低 */
[data-testid="stVerticalBlock"]{ gap:.55rem; }
[data-testid="stHorizontalBlock"]{ align-items:stretch; gap:18px; }

/* 圖表卡片：近5週／年度月份用 st.columns，直接把欄位做成卡片（外框確實可見） */
[data-testid="stColumn"]{
  background:linear-gradient(160deg,#35506A,#2A3F54) !important; border:1px solid #56718B !important;
  border-top:3px solid #C9A45C !important; border-radius:16px !important;
  box-shadow:0 10px 28px rgba(0,0,0,.5), inset 0 1px 0 rgba(255,255,255,.10) !important;
  padding:14px 18px 16px !important;
}

/* 按鈕 */
div[data-testid="stDownloadButton"] > button, div[data-testid="stButton"] > button{
  background:linear-gradient(180deg,#D4B069,#C9A45C) !important; border:none !important;
  color:#1A1206 !important; font-size:14px !important; font-weight:800 !important;
  border-radius:11px !important; padding:11px 18px !important; letter-spacing:.6px;
  box-shadow:0 4px 16px rgba(201,164,92,.35) !important; transition:.15s ease;
}
div[data-testid="stDownloadButton"] > button:hover, div[data-testid="stButton"] > button:hover{
  background:linear-gradient(180deg,#E0BE78,#D9B36A) !important;
  box-shadow:0 7px 22px rgba(217,179,106,.5) !important; transform:translateY(-1px);
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
    date(2026,  7, 10),  # 颱風停班
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
else:
    # ══════════════════════════════════════════════════════
    # 資料來源：SQLite（由 db/import_to_db.py 從 NAS 匯入）
    # 即時同步：每次刷新檢查 NAS 是否有新存檔，有異動立即匯入
    # （60 秒內最多檢查一次；20 分鐘排程仍保留作為備援）
    # ══════════════════════════════════════════════════════
    from db import import_to_db as wh_sync

    @st.cache_data(ttl=60, show_spinner=False)
    def _auto_sync():
        try:
            return wh_sync.sync_if_newer()
        except Exception as e:
            return False, f"同步失敗：{e}"

    # 匯入成功後 db_mtime() 隨之改變，load_wh 的快取 key 也跟著換，自動改讀新資料
    _did_sync, _sync_msg = _auto_sync()

    db_ready  = wh_db.db_exists()
    src_mtime = wh_db.db_mtime() if db_ready else None
    src_name  = wh_db.source_filename() if db_ready else None

# ══════════════════════════════════════════════════════
# HEADER
# ══════════════════════════════════════════════════════
st.markdown(
    '<div style="margin-bottom:8px;display:flex;justify-content:space-between;align-items:center">'
    '<a href="/" target="_self" style="color:#D9B36A;text-decoration:none;'
    'font-size:13px;font-weight:600;opacity:0.85">← 返回主頁</a>'
    '<a href="/wh_assessment" target="_self" style="color:#1A1206;text-decoration:none;'
    'font-size:13px;font-weight:800;background:linear-gradient(180deg,#D4B069,#C9A45C);'
    'padding:7px 16px;border-radius:9px;box-shadow:0 4px 14px rgba(201,164,92,.35)">'
    '📋 年度倉儲考核依據表</a>'
    '</div>',
    unsafe_allow_html=True
)

wday_names = ["一","二","三","四","五","六","日"]
wday   = wday_names[TODAY.weekday()]
data_ts = src_mtime.strftime('%m/%d %H:%M') if src_mtime else "⚠️ 離線"

st.markdown(
    f'<div style="background:linear-gradient(110deg,#13202C 0%,#22344A 50%,#13202C 100%);'
    f'border:1px solid #56718B;'
    f'border-radius:18px;padding:20px 30px;margin-bottom:14px;position:relative;overflow:hidden;'
    f'box-shadow:0 10px 34px rgba(0,0,0,.40);'
    f'display:grid;grid-template-columns:1fr auto 1fr;align-items:center;gap:16px">'
    f'<div style="position:absolute;left:0;right:0;bottom:0;height:3px;'
    f'background:linear-gradient(90deg,transparent,#C9A45C 28%,#E6C77A 50%,#C9A45C 72%,transparent)"></div>'
    f'<div>'
    f'<div style="color:#D9B36A;font-size:13px;font-weight:700;letter-spacing:2px">ORing &nbsp;·&nbsp; 倉管 WD</div>'
    f'<div style="color:#9fb0c0;font-size:13px;margin-top:5px">'
    f'🕐 {NOW.strftime("%H:%M")} &nbsp;｜&nbsp; 資料：{data_ts}</div>'
    f'</div>'
    f'<div style="text-align:center">'
    f'<div style="color:#ffffff;font-size:36px;font-weight:900;line-height:1.1;letter-spacing:2px">'
    f'倉儲備料即時看板</div>'
    f'<div style="color:#D9B36A;font-size:12px;font-weight:400;letter-spacing:5px;margin-top:6px">'
    f'WAREHOUSE MATERIAL PREP DASHBOARD</div>'
    f'</div>'
    f'<div style="text-align:right">'
    f'<div style="color:#ffffff;font-size:28px;font-weight:900;letter-spacing:1px">{TODAY.strftime("%Y / %m / %d")}</div>'
    f'<div style="color:#D9B36A;font-size:17px;font-weight:700;margin-top:3px">（週{wday}）</div>'
    f'</div></div>',
    unsafe_allow_html=True
)

# ── 資料庫狀態列 ─────────────────────────────────────
if db_ready:
    ts_str = src_mtime.strftime('%m/%d %H:%M') if src_mtime else "手動上傳"
    _mode_badge = (
        '<span style="color:#D9B36A;font-size:12px;font-weight:600">📂 手動上傳模式</span>'
        if _has_upload else
        '<span style="color:#D9B36A;font-size:12px;font-weight:600">🔄 NAS 有新存檔即自動同步</span>'
    )
    _clear_hint = (
        '<span style="color:#8094A6;font-size:11px">（重新整理頁面可清除上傳）</span>'
        if _has_upload else ""
    )
    st.markdown(
        f'<div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;'
        f'background:linear-gradient(160deg,#35506A,#2A3F54);border:1px solid #56718B;border-radius:12px;'
        f'padding:9px 16px;margin-bottom:14px;box-shadow:0 4px 16px rgba(0,0,0,.28)">'
        f'<span style="background:#163A2C;color:#43C08F;font-size:12px;font-weight:700;'
        f'padding:3px 11px;border-radius:20px">✅ 資料已載入</span>'
        f'<span style="color:#EAF1F8;font-size:13px;font-weight:800">{src_name or "wh_dashboard.db"}</span>'
        f'<span style="color:#8094A6;font-size:12px">（{ts_str}）</span>'
        f'<span style="flex:1"></span>{_mode_badge}{_clear_hint}'
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
            if st.button("🗑 清除上傳，切換回 NAS / 資料庫模式", width='stretch'):
                st.session_state.pop("wh_upload_bytes", None)
                st.session_state.pop("wh_upload_name", None)
                st.session_state.pop("wh_upload_ts", None)
                st.rerun()
else:
    st.markdown(
        '<div style="background:rgba(236,106,124,0.12);border:1px solid rgba(236,106,124,0.5);'
        'border-radius:12px;padding:12px 16px;margin-bottom:10px;color:#EC6A7C;font-size:14px">'
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

# ── 每日標準（KPI 卡指標與月標準線共用；月標準 = 日標準 × 22 工作天）──
STD_DAYS = 22
STD_B_Q13, STD_B_Q4 = 250, 300   # 備料 日標準（第1~3季 / 第4季）
STD_I_Q13, STD_I_Q4 = 150, 200   # 上架(入庫) 日標準（第1~3季 / 第4季）
_Q_NUM = (YESTERDAY.month - 1) // 3 + 1   # KPI 卡顯示前一工作日，指標依其所屬季
b_target_day = STD_B_Q4 if _Q_NUM == 4 else STD_B_Q13
i_target_day = STD_I_Q4 if _Q_NUM == 4 else STD_I_Q13

# ── 防呆設定：廠內／委外判定 & 待完成有效狀態 ──────────
# 待完成備料只計入這些狀態，排除空白／已完成等髒資料
# （例：來源誤鍵、需求筆數爆量又無狀態的列，不應灌進待完成）
PENDING_STATUSES = ('待備料', '備料中')

def _inhouse(df):
    """廠內判定：需求單位或單別含 生產加工／廠內／場內（『場』為常見錯字）。"""
    unit = df['需求單位'].astype(str)
    dan  = df['單別'].astype(str)
    return (unit.str.contains('生產加工|廠內|場內', na=False)
            | dan.str.contains('廠內|場內', na=False))

# ── 備料（調撥單）──────────────────────────────────────
# 已完成：K欄（完成日）= 昨日 且 M欄（狀態）= 已完成 → 加總 G欄（需求筆數）
b_done_rows = diao[
    diao['完成日'].notna() &
    (diao['完成日'].dt.date == YESTERDAY) &
    (diao['狀態'] == '已完成')
]
b_done = int(b_done_rows['需求筆數'].sum())

# 已完成拆分：廠內（含「場內」錯字）／委外
_inhouse_mask = _inhouse(b_done_rows)
b_done_inhouse  = int(b_done_rows[_inhouse_mask]['需求筆數'].sum())
b_done_outsource = b_done - b_done_inhouse

# 待完成：需求日有值且<=昨日、完成日空白，且狀態為待備料/備料中
# （狀態防呆：排除空白等髒資料，避免單一爆量列灌爆數字）
_pend_base = (
    diao['需求日'].notna() &
    (diao['需求日'].dt.date <= YESTERDAY) &
    diao['完成日'].isna()
)
b_pend_rows = diao[_pend_base & diao['狀態'].isin(PENDING_STATUSES)]
b_pend = int(b_pend_rows['需求筆數'].sum())

# 待完成拆分：廠內（含「場內」錯字）／委外
_pend_inhouse_mask = _inhouse(b_pend_rows)
b_pend_inhouse   = int(b_pend_rows[_pend_inhouse_mask]['需求筆數'].sum())
b_pend_outsource = b_pend - b_pend_inhouse

b_total = b_done + b_pend
b_rate  = b_done / b_total if b_total else 0

# ── 入庫 ────────────────────────────────────────────────
# 已完成：調撥單 E欄（需求單位）=入庫 且 K欄（完成日）=昨日 → 加總 H欄（完成筆數）
# （改依 E欄 判定，不看 M欄狀態，避免「上架W」等狀態變體漏算）
ib_done_rows = diao[
    diao['需求單位'].astype(str).str.contains('入庫', na=False) &
    diao['完成日'].notna() &
    (diao['完成日'].dt.date == YESTERDAY)
]
i_done = int(ib_done_rows['完成筆數'].sum())

# 待完成：入庫單據 I欄（完成日）空白 → 加總 G欄（筆數）
ib_pend_rows = inbound[inbound['完成日'].isna()]
i_pend = int(ib_pend_rows['筆數'].sum())

# 完成率分母：待完成只計「已逾期」（預計完成日<=昨日；空白視為逾期），
# 未到期單據不算進昨日該完成的量（口徑比照備料卡）；待完成顯示值仍為全部 i_pend
_ib_not_due = (ib_pend_rows['預計完成日'].notna() &
               (ib_pend_rows['預計完成日'].dt.date > YESTERDAY))
i_pend_overdue = int(ib_pend_rows[~_ib_not_due]['筆數'].sum())

i_total = i_done + i_pend_overdue
i_rate  = i_done / i_total if i_total else 0


# ══════════════════════════════════════════════════════
# 共用：區段標題
# ══════════════════════════════════════════════════════
def _sec(icon, title, sub=""):
    sub_html = (f'<span style="color:#8094A6;font-size:13px;font-weight:500;'
                f'margin-left:10px">{sub}</span>') if sub else ""
    st.markdown(
        f'<div style="display:flex;align-items:center;gap:9px;margin:8px 0 12px">'
        f'<span style="width:5px;height:21px;border-radius:3px;'
        f'background:linear-gradient(#D9B36A,#B8922A)"></span>'
        f'<span style="color:#EAF1F8;font-size:17px;font-weight:800;letter-spacing:.5px">{icon} {title}</span>'
        f'{sub_html}</div>',
        unsafe_allow_html=True
    )


# ══════════════════════════════════════════════════════
# SECTION 1：早會 KPI 三卡片（等高 grid）
# ══════════════════════════════════════════════════════
_sec("📊", "前日進度概況", YESTERDAY.strftime("%m/%d"))

def _kpi_card(title, done, pend, rate, icon, daily_target=None,
              done_breakdown=None, pend_breakdown=None):
    total = done + pend
    pct   = int(rate * 100)

    # 廠內／委外拆分小標籤
    def _bd_label(bd):
        if not bd: return ""
        in_cnt, out_cnt = bd
        return (
            f'<div style="color:#8094A6;font-size:12px;margin-top:5px;white-space:nowrap">'
            f'廠內 {in_cnt:,}・委外 {out_cnt:,}</div>'
        )
    done_breakdown_html = _bd_label(done_breakdown)
    pend_breakdown_html = _bd_label(pend_breakdown)

    if rate >= 0.8:   status_txt, status_c = "達標",    "#43C08F"
    elif rate >= 0.5: status_txt, status_c = "持續推進", "#E5B454"
    else:             status_txt, status_c = "進度落後", "#EC6A7C"

    # Q3 目標比較區塊
    q3_block = ""
    if daily_target:
        diff     = done - daily_target
        diff_c   = "#43C08F" if diff >= 0 else "#EC6A7C"
        diff_sym = "▲" if diff >= 0 else "▼"
        diff_lbl = "達標" if diff >= 0 else "未達標"
        bar_pct  = min(int(done / daily_target * 100), 100)
        q3_block = (
            f'<div style="margin-top:14px;border-top:1px dashed #56718B;padding-top:11px">'
            f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:7px">'
            f'<span style="color:#9DB0C0;font-size:13px;font-weight:600">🎯 第{_Q_NUM}季每日指標：{daily_target:,} 筆</span>'
            f'<span style="color:{diff_c};font-size:13px;font-weight:800">{diff_sym} {abs(diff)} &nbsp;{diff_lbl}</span>'
            f'</div>'
            f'<div style="display:flex;align-items:center;gap:10px">'
            f'<div style="flex:1;background:#3D5365;border-radius:5px;height:8px;overflow:hidden">'
            f'<div style="width:{bar_pct}%;height:100%;'
            f'background:{"linear-gradient(90deg,#2E9D70,#43C08F)" if diff>=0 else "linear-gradient(90deg,#B23A48,#EC6A7C)"}"></div>'
            f'</div>'
            f'<span style="color:{diff_c};font-size:13px;font-weight:800;min-width:38px;text-align:right">{bar_pct}%</span>'
            f'</div></div>'
        )

    return (
        f'<div style="background:linear-gradient(160deg,#35506A,#2A3F54);border:1px solid #56718B;border-top:3px solid #C9A45C;'
        f'border-radius:16px;padding:22px 24px;box-shadow:0 10px 28px rgba(0,0,0,.5), inset 0 1px 0 rgba(255,255,255,.10);'
        f'height:100%;display:flex;flex-direction:column;justify-content:space-between">'
        f'<div style="display:flex;justify-content:space-between;align-items:center">'
        f'<div style="color:#EAF1F8;font-size:16px;font-weight:800;letter-spacing:.5px">{icon} {title}</div>'
        f'<div style="background:#3B5167;border:1px solid #56718B;border-radius:20px;'
        f'padding:3px 13px;color:{status_c};font-size:13px;font-weight:700">{status_txt}</div>'
        f'</div>'
        f'<div style="display:flex;gap:12px;margin:18px 0">'
        f'<div style="flex:1;text-align:center;background:#26394D;border:1px solid #46607A;'
        f'border-radius:12px;padding:14px 6px 12px;box-shadow:inset 0 1px 0 rgba(255,255,255,.05)">'
        f'<div style="color:#43C08F;font-size:46px;font-weight:900;line-height:1">{done:,}</div>'
        f'<div style="color:#9DB0C0;font-size:14px;margin-top:6px">已完成</div>{done_breakdown_html}</div>'
        f'<div style="flex:1;text-align:center;background:#26394D;border:1px solid #46607A;'
        f'border-radius:12px;padding:14px 6px 12px;box-shadow:inset 0 1px 0 rgba(255,255,255,.05)">'
        f'<div style="color:#EC6A7C;font-size:46px;font-weight:900;line-height:1">{pend:,}</div>'
        f'<div style="color:#9DB0C0;font-size:14px;margin-top:6px">待完成</div>{pend_breakdown_html}</div>'
        f'<div style="flex:1;text-align:center;background:#26394D;border:1px solid #46607A;'
        f'border-radius:12px;padding:14px 6px 12px;box-shadow:inset 0 1px 0 rgba(255,255,255,.05)">'
        f'<div style="color:#D9B36A;font-size:46px;font-weight:900;line-height:1">{pct}%</div>'
        f'<div style="color:#9DB0C0;font-size:14px;margin-top:6px">完成率</div></div>'
        f'</div>'
        f'<div>'
        f'<div style="background:#3D5365;border-radius:5px;height:9px;overflow:hidden;display:flex">'
        f'<div style="width:{pct}%;background:linear-gradient(90deg,#2E9D70,#43C08F)"></div>'
        f'<div style="width:{100-pct}%;background:#3A2A31"></div>'
        f'</div>'
        f'<div style="color:#9DB0C0;font-size:13px;margin-top:7px;text-align:right">目標總筆數：{total:,}</div>'
        f'{q3_block}</div>'
        f'</div>'
    )

# 第三卡片：本週（週一~週五）每日已完成備料筆數
def _week_prep_card():
    def _tgt(d):                                    # 每日備料目標基準（第4季自動調升）
        return STD_B_Q4 if d.month >= 10 else STD_B_Q13
    mon = TODAY - timedelta(days=TODAY.weekday())   # 本週一
    wlabels = ['一', '二', '三', '四', '五']
    days = [mon + timedelta(days=i) for i in range(5)]
    vals = []
    for d in days:
        if d > TODAY:
            vals.append(None)                        # 未到
        else:
            m = ((diao['狀態'] == '已完成') &
                 diao['完成日'].notna() &
                 (diao['完成日'].dt.date == d))
            vals.append(int(diao[m]['需求筆數'].sum()))
    nums  = [v for v in vals if v is not None]
    total = sum(nums)
    maxc  = max(nums) if nums else 0
    scale = max([maxc] + [_tgt(d) for d in days])     # 比例尺：取最大值與目標的較大者

    rows = ""
    for d, lbl, v in zip(days, wlabels, vals):
        tgt = _tgt(d)
        line_pos = tgt / scale * 100                  # 基準線位置（跨季的週各日可能不同）
        bg = '#3E5670' if d == TODAY else 'transparent'
        if v is None:
            valhtml = '<span style="color:#6E8094;font-size:15px">—</span>'
            barw = 0
            bar_color = 'transparent'
        else:
            met = v >= tgt
            cnt_color = '#43C08F' if met else '#E5B454'      # 達標綠／未達標琥珀
            bar_color = '#43C08F' if met else '#E5B454'
            valhtml = (f'<span style="color:{cnt_color};font-size:23px;font-weight:900">{v:,}</span>'
                       f'<span style="color:#9DB0C0;font-size:12px"> 筆</span>')
            barw = int(v / scale * 100)
        rows += (
            f'<div style="display:flex;align-items:center;gap:14px;padding:9px 8px;'
            f'border-bottom:1px solid #33475A;background:{bg};border-radius:8px">'
            f'<div style="flex:0 0 50px;text-align:center">'
            f'<div style="color:#EAF1F8;font-size:15px;font-weight:800">週{lbl}</div>'
            f'<div style="color:#8094A6;font-size:11px">{d.strftime("%m/%d")}</div></div>'
            f'<div style="flex:1;min-width:0">'
            f'<div style="text-align:right">{valhtml}</div>'
            f'<div style="position:relative;background:#3D5365;border-radius:4px;height:9px;margin-top:5px">'
            f'<div style="width:{barw}%;height:100%;border-radius:4px;background:{bar_color}"></div>'
            f'<div style="position:absolute;top:-3px;bottom:-3px;left:{line_pos:.1f}%;width:2px;'
            f'background:#EC6A7C"></div>'
            f'</div>'
            f'</div></div>'
        )

    return (
        f'<div style="background:linear-gradient(160deg,#35506A,#2A3F54);border:1px solid #56718B;border-top:3px solid #C9A45C;'
        f'border-radius:16px;padding:20px 22px;box-shadow:0 10px 28px rgba(0,0,0,.5), inset 0 1px 0 rgba(255,255,255,.10);'
        f'height:100%;display:flex;flex-direction:column">'
        f'<div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:5px">'
        f'<span style="color:#EAF1F8;font-size:16px;font-weight:800;letter-spacing:.5px">📦 本週備料完成</span>'
        f'<span style="color:#9DB0C0;font-size:12px">週一~週五 共 '
        f'<b style="color:#43C08F">{total:,}</b> 筆</span>'
        f'</div>'
        f'<div style="display:flex;align-items:center;gap:6px;margin-bottom:10px">'
        f'<span style="display:inline-block;width:13px;height:2px;background:#EC6A7C"></span>'
        f'<span style="color:#8094A6;font-size:11px">每日目標基準 {_tgt(TODAY)} 筆</span>'
        f'</div>'
        f'<div style="display:flex;flex-direction:column;justify-content:space-around;flex:1">{rows}</div>'
        f'</div>'
    )

# ══════════════════════════════════════════════════════
# 今日出勤（來源：Outlook「Apollo HR」請假信，10 分鐘快取）
# ══════════════════════════════════════════════════════

@st.cache_data(ttl=600, show_spinner=False)
def _today_leaves_cached(day_key):
    return fetch_today_leaves(holidays=frozenset(TW_HOLIDAYS))

_leaves, _month_lv_hrs, _lv_err = _today_leaves_cached(f"{TODAY.isoformat()}#v3")

# 本月（1日～今天）請假總工時：全天=8、半天=4 小時
_month_lv_txt = (
    f'<span style="color:#5E7186;margin:0 8px">｜</span>'
    f'<span style="color:#9DB0C0;font-size:12.5px;white-space:nowrap">本月請假累計 '
    f'<b style="color:#D9B36A;font-size:14.5px">{_month_lv_hrs:g}</b> 小時'
    f'<span style="color:#5E7186;font-size:11px">（全天8h・半天4h）</span></span>'
)

if _lv_err:
    _att_body = (f'<span style="color:#8094A6;font-size:13px">'
                 f'出勤資料暫無法讀取（{_lv_err}）</span>')
elif not _leaves:
    _att_body = ('<span style="color:#43C08F;font-size:15.5px;font-weight:800;'
                 'letter-spacing:1px">✅ 全員出勤</span>'
                 + _month_lv_txt)
else:
    _chips = "".join(
        f'<span style="display:inline-block;background:rgba(236,106,124,.13);'
        f'border:1px solid rgba(236,106,124,.55);color:#FFC2CB;border-radius:20px;'
        f'padding:4px 14px;margin:3px 8px 3px 0;font-size:13.5px;font-weight:800">'
        f'{r["name"]}'
        f'<span style="color:#EC8A99;font-weight:600">（{r["type"]}・{r["part"]}）</span>'
        f'</span>'
        for r in _leaves
    )
    _n_full = sum(1 for r in _leaves if r["part"] == "全天")
    _n_half = sum(1 for r in _leaves if "半天" in r["part"])
    _n_rest = len(_leaves) - _n_full - _n_half
    _cnt = []
    if _n_full:
        _cnt.append(f"{_n_full} 位休整天")
    if _n_half:
        _cnt.append(f"{_n_half} 位休半天")
    if _n_rest:
        _cnt.append(f"{_n_rest} 位部分請假")
    _att_body = (
        _chips
        + f'<span style="color:#9DB0C0;font-size:12.5px;margin-left:4px">'
          f'今日 {"、".join(_cnt)}，其餘同仁出勤</span>'
        + _month_lv_txt
    )

st.markdown(
    f'<div style="background:linear-gradient(160deg,#35506A,#2A3F54);'
    f'border:1px solid #56718B;border-left:4px solid #C9A45C;border-radius:14px;'
    f'padding:11px 20px;margin-bottom:16px;display:flex;align-items:center;'
    f'gap:14px;flex-wrap:wrap;box-shadow:0 6px 18px rgba(0,0,0,.35)">'
    f'<span style="color:#EAF1F8;font-size:15px;font-weight:800;letter-spacing:1.5px;'
    f'white-space:nowrap">👥 今日出勤</span>'
    f'<span style="display:flex;align-items:center;flex-wrap:wrap;flex:1">{_att_body}</span>'
    f'</div>',
    unsafe_allow_html=True
)

st.markdown(
    '<div style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr));'
    'gap:18px;align-items:stretch">'
    + _kpi_card("備料", b_done, b_pend, b_rate, "📦", daily_target=b_target_day,
                done_breakdown=(b_done_inhouse, b_done_outsource),
                pend_breakdown=(b_pend_inhouse, b_pend_outsource))
    + _kpi_card("上架", i_done, i_pend, i_rate, "🏭", daily_target=i_target_day)
    + _week_prep_card()
    + '</div>',
    unsafe_allow_html=True
)

st.markdown("<div style='margin-top:22px'></div>", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════
# SECTION 2：今日即時進度 ＆ 待完成明細（三欄，與上方三卡對齊）
#   欄1（備料卡下方）＝今日備料　欄2（上架卡下方）＝今日上架＋上架待完成明細
#   欄3（本週卡下方）＝備料待完成明細
# ══════════════════════════════════════════════════════
_sec("⚡", "今日即時進度 ＆ 待完成明細", f"{TODAY.strftime('%m/%d')} {NOW.strftime('%H:%M')} 止")

# ── 今日即時進度資料 ──
today_b_rows = diao[(diao['狀態'] == '已完成') & diao['完成日'].notna() &
                    (diao['完成日'].dt.date == TODAY)]
today_i_rows = diao[(diao['狀態'] == '上架') & diao['完成日'].notna() &
                    (diao['完成日'].dt.date == TODAY)]
today_b_cnt = int(today_b_rows['需求筆數'].sum())
today_i_cnt = int(today_i_rows['完成筆數'].sum())
today_new_rows = diao[diao['開單日'].notna() & (diao['開單日'].dt.date == TODAY)]
today_new_cnt = int(today_new_rows['需求筆數'].sum())

_CARD = ('background:linear-gradient(160deg,#35506A,#2A3F54);border:1px solid #56718B;border-top:3px solid #C9A45C;'
         'border-radius:16px;box-shadow:0 10px 28px rgba(0,0,0,.5), inset 0 1px 0 rgba(255,255,255,.10);'
         'height:100%;display:flex;flex-direction:column;overflow:hidden;')

# ── 待完成明細共用表格樣式 ──
_th = ('style="position:sticky;top:0;background:#3B5167;color:#EAF1F8;padding:10px 12px;'
       'font-size:13px;font-weight:700;text-align:center;border-bottom:2px solid #C9A45C"')
_td = ('style="padding:9px 12px;font-size:14px;color:#D7E1EA;text-align:center;'
       'border-bottom:1px solid #33475A"')
_tdn = ('style="padding:9px 12px;font-size:15px;color:#EC6A7C;font-weight:800;text-align:center;'
        'border-bottom:1px solid #33475A"')

def _date_label(d):
    if pd.isna(d):
        return "—", "#8094A6"
    lbl = f'{d.strftime("%m/%d")}（{"一二三四五六日"[d.weekday()]}）'
    if d < TODAY:    return lbl, "#EC6A7C"   # 逾期
    elif d == TODAY: return lbl, "#D9B36A"   # 今日
    return lbl, "#EAF1F8"                    # 未來排程

def _pend_table(rows, date_col, unit_col, qty_col, date_header, unit_header, max_h=340):
    """依 日期＋單位 彙總的待完成明細表（張數／數量）"""
    by_day = (
        rows.assign(_day=rows[date_col].dt.date)
        .groupby(['_day', unit_col], dropna=False)[qty_col]
        .agg(張數='count', 數量='sum').reset_index()
        .sort_values(['_day', unit_col], na_position='last')
    )
    body, prev = "", None
    for i, (_, r) in enumerate(by_day.iterrows()):
        lbl, c = _date_label(r['_day'])
        show = lbl if lbl != prev else ""
        prev = lbl
        body += (
            f'<tr style="background:{"#3B5167" if i % 2 else "transparent"}">'
            f'<td {_td}><span style="color:{c};font-weight:800">{show}</span></td>'
            f'<td {_td}>{r[unit_col]}</td><td {_td}>{int(r["張數"])}</td>'
            f'<td {_tdn}>{int(r["數量"]):,}</td></tr>'
        )
    return (
        f'<div style="overflow:auto;flex:1;max-height:{max_h}px;border:1px solid #33475A;border-radius:10px">'
        f'<table style="width:100%;border-collapse:collapse">'
        f'<thead><tr><th {_th}>{date_header}</th><th {_th}>{unit_header}</th>'
        f'<th {_th}>張數</th><th {_th}>數量</th></tr></thead>'
        f'<tbody>{body}</tbody></table></div>'
    )

# ── 欄3：備料待完成（含未來需求日；僅列 廠內・唐佑・國智）──
SCHED_UNITS = ("廠內", "唐佑", "國智")

sched_rows = diao[diao['完成日'].isna() & diao['狀態'].isin(PENDING_STATUSES)].copy()
# 「場內」為「廠內」常見錯字，先正規化再歸類
# 需求單位可能空白（半鍵入列）；pandas3 astype(str) 會保留 NaN，先 fillna 再轉字串
sched_rows['需求單位'] = sched_rows['需求單位'].fillna('').astype(str).str.replace('場內', '廠內')

def _canon_unit(u):
    for k in SCHED_UNITS:
        if k in u:
            return k
    return None

sched_rows['單位'] = sched_rows['需求單位'].map(_canon_unit)
sched_rows = sched_rows[sched_rows['單位'].notna()]

has_pend = not sched_rows.empty
if has_pend:
    _pend_detail = sched_rows[
        ["編號", "單別", "單號", "開單日", "單位", "需求日",
         "需求筆數", "備料人員", "狀態", "備註"]
    ].rename(columns={"單位": "需求單位"}).sort_values("需求日")

    sched_total = int(sched_rows['需求筆數'].sum())
    _in_qty  = int(sched_rows[sched_rows['單位'] == '廠內']['需求筆數'].sum())
    _out_qty = sched_total - _in_qty

    pend_body = _pend_table(sched_rows, '需求日', '單位', '需求筆數', '需求日', '需求單位')
    pend_sub = (f'含未來需求日　｜　僅列 廠內・唐佑・國智　｜　'
                f'廠內 {_in_qty:,} · 委外 {_out_qty:,}')
else:
    sched_total = 0
    pend_body = ('<div style="flex:1;display:flex;align-items:center;justify-content:center;'
                 'color:#8094A6;font-size:15px;padding:36px">— 目前沒有待完成備料 —</div>')
    pend_sub = '全部完成 🎉'

pend_card = (
    f'<div style="{_CARD}padding:18px 20px">'
    f'<div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:6px">'
    f'<span style="color:#EAF1F8;font-size:16px;font-weight:800">📦 備料待完成</span>'
    f'<span style="color:#EC6A7C;font-size:20px;font-weight:900">共 {sched_total:,} 筆</span>'
    f'</div>'
    f'<div style="color:#9DB0C0;font-size:13px;margin-bottom:12px">{pend_sub}</div>'
    f'{pend_body}</div>'
)

# ── 共用：大數字統計、每人筆數列表 ──
def _stat(num, label, color):
    return (f'<div style="flex:1;text-align:center;padding:8px 0">'
            f'<div style="color:{color};font-size:46px;font-weight:900;line-height:1">{num:,}</div>'
            f'<div style="color:#9DB0C0;font-size:13px;margin-top:7px">{label}</div></div>')

def _person_list(rows, qty_col, empty_msg):
    if rows.empty:
        return f'<div style="color:#8094A6;font-size:13px;padding:10px 0">{empty_msg}</div>'
    by_p = rows.groupby('備料人員')[qty_col].sum().sort_values(ascending=False)
    return "".join(
        f'<div style="display:flex;justify-content:space-between;padding:8px 2px;'
        f'border-bottom:1px solid #33475A">'
        f'<span style="color:#D7E1EA;font-size:14px">{p}</span>'
        f'<span style="color:#D9B36A;font-size:14px;font-weight:800">{int(c):,} 筆</span></div>'
        for p, c in by_p.items()
    )

# ── 欄1：今日備料 ──
prep_today_card = (
    f'<div style="{_CARD}padding:18px 20px">'
    f'<div style="color:#EAF1F8;font-size:16px;font-weight:800;margin-bottom:14px">'
    f'⚡ 今日備料 <span style="color:#8094A6;font-size:12px;font-weight:500">'
    f'（{TODAY.strftime("%m/%d")} {NOW.strftime("%H:%M")} 止）</span></div>'
    f'<div style="display:flex;background:#3B5167;border:1px solid #33475A;border-radius:12px;padding:6px 0">'
    + _stat(today_b_cnt, "📦 備料完成", "#43C08F")
    + '<div style="width:1px;background:#33475A;margin:6px 0"></div>'
    + _stat(today_new_cnt, "➕ 今日新增", "#5AA8F0")
    + '</div>'
    f'<div style="color:#9DB0C0;font-size:13px;margin:15px 0 4px">今日備料人員</div>'
    f'<div style="overflow:auto;flex:1;max-height:300px">'
    f'{_person_list(today_b_rows, "需求筆數", "— 今日尚無備料完成記錄 —")}</div>'
    f'</div>'
)

# ── 欄2：今日上架 ＋ 上架待完成明細 ──
ib_detail_rows = inbound[inbound['完成日'].isna()].copy()
ib_has = not ib_detail_rows.empty
if ib_has:
    ib_detail_rows['單別'] = ib_detail_rows['單別'].fillna('—').astype(str)
    _ib_detail = ib_detail_rows[
        ["編號", "單別", "單號", "驗畢日期", "接單日期", "預計完成日",
         "取單日", "筆數", "入庫人員", "備註"]
    ].sort_values("預計完成日")
    ib_table = _pend_table(ib_detail_rows, '預計完成日', '單別', '筆數',
                           '預計完成日', '單別', max_h=220)
else:
    ib_table = ('<div style="flex:1;display:flex;align-items:center;justify-content:center;'
                'color:#8094A6;font-size:15px;padding:24px">— 目前沒有待上架單據 —</div>')

putaway_today_card = (
    f'<div style="{_CARD}padding:18px 20px">'
    f'<div style="color:#EAF1F8;font-size:16px;font-weight:800;margin-bottom:14px">'
    f'⚡ 今日上架 <span style="color:#8094A6;font-size:12px;font-weight:500">'
    f'（{TODAY.strftime("%m/%d")} {NOW.strftime("%H:%M")} 止）</span></div>'
    f'<div style="display:flex;background:#3B5167;border:1px solid #33475A;border-radius:12px;padding:6px 0">'
    + _stat(today_i_cnt, "🏭 上架完成", "#43C08F")
    + '<div style="width:1px;background:#33475A;margin:6px 0"></div>'
    + _stat(i_pend, "⏳ 待上架", "#EC6A7C")
    + '</div>'
    f'<div style="color:#9DB0C0;font-size:13px;margin:15px 0 4px">今日上架人員</div>'
    f'<div style="overflow:auto;max-height:120px">'
    f'{_person_list(today_i_rows, "完成筆數", "— 今日尚無上架完成記錄 —")}</div>'
    f'<div style="display:flex;justify-content:space-between;align-items:baseline;margin:15px 0 4px">'
    f'<span style="color:#9DB0C0;font-size:13px">上架待完成明細</span>'
    f'<span style="color:#EC6A7C;font-size:15px;font-weight:900">共 {i_pend:,} 筆</span>'
    f'</div>'
    f'{ib_table}'
    f'</div>'
)

st.markdown(
    '<div style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr));'
    'gap:18px;align-items:stretch">'
    + prep_today_card + putaway_today_card + pend_card + '</div>',
    unsafe_allow_html=True
)

_dl_shown = has_pend or ib_has
if _dl_shown:
    st.markdown("<div style='margin-top:10px'></div>", unsafe_allow_html=True)
if has_pend:
    _pend_buf = io.BytesIO()
    with pd.ExcelWriter(_pend_buf, engine="openpyxl") as _pend_writer:
        _pend_detail.to_excel(_pend_writer, index=False, sheet_name="備料待完成")
    _pend_buf.seek(0)
    st.download_button(
        "⬇️　下載備料待完成明細（Excel）",
        data=_pend_buf,
        file_name=f"備料待完成明細_{TODAY.strftime('%Y%m%d')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        width='stretch',
    )
if ib_has:
    _ib_buf = io.BytesIO()
    with pd.ExcelWriter(_ib_buf, engine="openpyxl") as _ib_writer:
        _ib_detail.to_excel(_ib_writer, index=False, sheet_name="上架待完成")
    _ib_buf.seek(0)
    st.download_button(
        "⬇️　下載上架待完成明細（Excel）",
        data=_ib_buf,
        file_name=f"上架待完成明細_{TODAY.strftime('%Y%m%d')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        width='stretch',
    )

st.markdown("<div style='margin-top:24px'></div>", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════
# 圖表共用工具
# ══════════════════════════════════════════════════════
def _workdays_in_week(wk_start, wk_end):
    """計算日期區間內的工作日數（排除週六日及國定假日/停班日）"""
    count = 0
    d = wk_start
    while d <= wk_end:
        if d.weekday() < 5 and d not in TW_HOLIDAYS:
            count += 1
        d += timedelta(days=1)
    return max(count, 1)

def _bar_chart(labels, values, color_fill, color_line, height=260, trend=True, std=None):
    fig = go.Figure(go.Bar(
        x=labels, y=values,
        marker=dict(color=color_fill, line=dict(color=color_line, width=1.5)),
        text=[f"{v:,}" if v else "0" for v in values],
        textposition="outside",
        textfont=dict(color=color_line, size=14, family="'微軟正黑體',Arial,sans-serif"),
        hoverinfo="skip",
    ))
    # ── 標準線：各期標準量（實線階梯；如 Q4 調升會在該期跳高） ──
    if std is not None:
        fig.add_trace(go.Scatter(
            x=labels, y=std, mode="lines",
            line=dict(color="#7FA3C8", width=3, shape="hv"),
            hoverinfo="skip", showlegend=False, cliponaxis=False,
        ))
        # 各標準段中點加白底數值標籤，箭頭指向標準線
        seg_start = 0
        for i in range(1, len(std) + 1):
            if i == len(std) or std[i] != std[seg_start]:
                mid = (seg_start + i - 1) // 2
                fig.add_annotation(
                    x=labels[mid], y=std[seg_start],
                    text=f"<b>{std[seg_start]:,} 筆</b>",
                    showarrow=True, arrowhead=2, arrowwidth=1.5,
                    arrowcolor="#EAF1F8", ax=0, ay=-28,
                    font=dict(color="#FFFFFF", size=13.5,
                              family="'微軟正黑體',Arial,sans-serif"),
                )
                seg_start = i
    # ── 趨勢曲線：連接各期完成筆數，讓「本週／本月是成長還是下降」一眼可見 ──
    #    空期（未來月份=0）以 None 斷開，避免曲線掉到 0 造成誤判。
    if trend:
        trend_y = [v if v else None for v in values]
        if sum(v is not None for v in trend_y) >= 2:
            fig.add_trace(go.Scatter(
                x=labels, y=trend_y, mode="lines+markers",
                line=dict(color="#F5C542", width=3, shape="spline"),
                marker=dict(color="#F5C542", size=7,
                            line=dict(color="#1B2A3A", width=1.5)),
                connectgaps=False, hoverinfo="skip", showlegend=False,
                cliponaxis=False,
            ))
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        showlegend=False, bargap=0.35,
        xaxis=dict(showgrid=False, tickfont=dict(color="#C7D3DE", size=13,
                   family="'微軟正黑體',Arial,sans-serif")),
        yaxis=dict(showgrid=True, gridcolor="#283845",
                   tickfont=dict(color="#8094A6", size=12), zeroline=False),
        margin=dict(l=10, r=10, t=34, b=10), height=height,
    )
    return fig

# 每日平均專屬識別色（青藍）：與長條綠/紅、趨勢黃、標準線灰藍皆不同，
# 兩張卡共用同一色 → 看到青藍就知道是「每日平均」
_AVG_LINE = "#54C0E8"
_AVG_FILL = "#2C7DA0"   # 實色填滿（不透明）

def _avg_chart(labels, avg, height=180):
    """每日平均獨立圖表：青藍折線＋實色面積，數值以白字直接標在點上（與表格同口徑）"""
    avg_y = [a if a else None for a in avg]        # 無資料期（未來月份）不畫線
    sizes = [7] * len(avg_y)
    for i in range(len(avg_y) - 1, -1, -1):        # 最近一期的點加大強調
        if avg_y[i] is not None:
            sizes[i] = 10
            break
    _vmax = max((a for a in avg if a), default=0)
    fig = go.Figure(go.Scatter(
        x=labels, y=avg_y, mode="lines+markers+text",
        line=dict(color=_AVG_LINE, width=2.5, shape="spline", smoothing=0.6),
        marker=dict(color=_AVG_LINE, size=sizes,
                    line=dict(color="#1B2A3A", width=2)),
        fill="tozeroy", fillcolor=_AVG_FILL,
        text=[f"{a:,.1f}" if a else "" for a in avg],
        textposition="top center",
        textfont=dict(color="#EAF1F8", size=12.5,
                      family="'微軟正黑體',Arial,sans-serif"),
        connectgaps=False, hoverinfo="skip", showlegend=False,
        cliponaxis=False,
    ))
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
        xaxis=dict(showgrid=False, tickfont=dict(color="#C7D3DE", size=13,
                   family="'微軟正黑體',Arial,sans-serif")),
        yaxis=dict(visible=False, range=[0, _vmax * 1.35 or 1]),
        margin=dict(l=10, r=10, t=30, b=10), height=height,
    )
    return fig

def _avgs(vals, wds):
    """每期完成筆數 ÷ 該期工作日數（與表格「每日平均」同口徑）"""
    return [round(v / wd, 1) if wd else 0 for v, wd in zip(vals, wds)]

def _mini_table(row_label, labels, values, val_color, workdays=None):
    """HTML 小表格：完成筆數 + 每日平均"""
    th_lbl = ('style="background:#3B5167;color:#EAF1F8;padding:9px 12px;'
              'font-size:13px;font-weight:800;border:1px solid #33475A;'
              'text-align:center;white-space:nowrap"')
    th     = ('style="background:#3B5167;color:#EAF1F8;padding:9px 12px;'
              'font-size:13px;font-weight:700;text-align:center;border:1px solid #56718B"')
    td_val = (f'style="background:linear-gradient(160deg,#35506A,#2A3F54);color:{val_color};padding:9px 12px;'
              f'font-size:15px;font-weight:900;border:1px solid #33475A;text-align:center"')
    td_avg = ('style="background:#3B5167;color:#D9B36A;padding:8px 12px;'
              'font-size:14px;font-weight:700;border:1px solid #33475A;text-align:center"')

    ths = "".join(f"<th {th}>{l}</th>" for l in labels)
    tds = "".join(f"<td {td_val}>{v:,}</td>" for v in values)

    avg_row = ""
    if workdays:
        avgs = [round(v / wd, 1) if wd > 0 else 0 for v, wd in zip(values, workdays)]
        tda  = "".join(f"<td {td_avg}>{a}</td>" for a in avgs)
        avg_row = f'<tr><td {th_lbl}>每日平均</td>{tda}</tr>'

    return (
        f'<div style="overflow-x:auto;margin-top:10px;border-radius:10px;border:1px solid #33475A">'
        f'<table style="width:100%;border-collapse:collapse">'
        f'<tr><th {th_lbl}>{row_label}</th>{ths}</tr>'
        f'<tr><td {th_lbl}>完成筆數</td>{tds}</tr>'
        f'{avg_row}'
        f'</table></div>'
    )

_CHART_CFG = dict(staticPlot=True, displayModeBar=False)
def _avg_title():
    """每日平均獨立圖表的小標題（色鍵用每日平均專屬青藍色，文字用中性色）"""
    return (
        f'<div style="display:flex;align-items:center;gap:7px;margin:10px 0 0">'
        f'<span style="display:inline-block;width:14px;border-top:3px solid {_AVG_LINE};border-radius:2px"></span>'
        f'<span style="color:#C7D3DE;font-size:13px;font-weight:700">每日平均 '
        f'<span style="color:#5E7186;font-weight:600;font-size:11.5px">筆／天</span></span></div>'
    )
_SUBHEAD_B = '<div style="color:#43C08F;font-size:15px;font-weight:800;margin:2px 0 2px">📦 備料</div>'
_SUBHEAD_I = '<div style="color:#EC6A7C;font-size:15px;font-weight:800;margin:2px 0 2px">🏭 上架</div>'

# ══════════════════════════════════════════════════════
# SECTION 3：近5週 — 備料 / 上架 等高卡片
# ══════════════════════════════════════════════════════
_sec("📅", "近5週完成筆數")

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
    week_b.append(int(diao[mask & (diao['狀態'] == '已完成')]['需求筆數'].sum()))
    week_i.append(int(diao[mask & (diao['狀態'] == '上架')]['完成筆數'].sum()))
    week_workdays.append(wd)

col_w1, col_w2 = st.columns(2)
with col_w1:
    st.markdown(_SUBHEAD_B, unsafe_allow_html=True)
    st.plotly_chart(_bar_chart(week_labels, week_b, "rgba(67,192,143,0.85)", "#43C08F"),
                    width='stretch', config=_CHART_CFG)
    st.markdown(_avg_title(), unsafe_allow_html=True)
    st.plotly_chart(_avg_chart(week_labels, _avgs(week_b, week_workdays)),
                    width='stretch', config=_CHART_CFG)
    st.markdown(_mini_table("近5週", week_short, week_b, "#43C08F",
                            workdays=week_workdays), unsafe_allow_html=True)
with col_w2:
    st.markdown(_SUBHEAD_I, unsafe_allow_html=True)
    st.plotly_chart(_bar_chart(week_labels, week_i, "rgba(236,106,124,0.82)", "#EC6A7C"),
                    width='stretch', config=_CHART_CFG)
    st.markdown(_avg_title(), unsafe_allow_html=True)
    st.plotly_chart(_avg_chart(week_labels, _avgs(week_i, week_workdays)),
                    width='stretch', config=_CHART_CFG)
    st.markdown(_mini_table("近5週", week_short, week_i, "#EC6A7C",
                            workdays=week_workdays), unsafe_allow_html=True)

st.markdown("<div style='margin-top:26px'></div>", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════
# SECTION 4：年度月份 — 備料 / 上架 等高卡片
# ══════════════════════════════════════════════════════
_sec("📆", "年度月份完成筆數", f"{TODAY.year} 年")

month_labels = [f"{m}月" for m in range(1, 13)]
month_b, month_i = [], []

for m in range(1, 13):
    mask = (diao['完成日'].notna() &
            (diao['完成日'].dt.year == TODAY.year) &
            (diao['完成日'].dt.month == m))
    month_b.append(int(diao[mask & (diao['狀態'] == '已完成')]['需求筆數'].sum()))
    month_i.append(int(diao[mask & (diao['狀態'] == '上架')]['完成筆數'].sum()))

# ── 月標準線：日標準 × 22 個工作天換算；第4季（10~12月）調升 ──
month_std_b = [(STD_B_Q4 if m >= 10 else STD_B_Q13) * STD_DAYS for m in range(1, 13)]
month_std_i = [(STD_I_Q4 if m >= 10 else STD_I_Q13) * STD_DAYS for m in range(1, 13)]

def _std_legend(q13_day, q4_day):
    return (
        f'<div style="display:flex;align-items:center;gap:6px;margin:0 0 2px">'
        f'<span style="display:inline-block;width:18px;border-top:3px solid #7FA3C8"></span>'
        f'<span style="color:#8094A6;font-size:11px">月標準線：1~9月 {q13_day*STD_DAYS:,} 筆'
        f'（{q13_day} 筆/天×22天）｜10~12月 {q4_day*STD_DAYS:,} 筆'
        f'（{q4_day} 筆/天×22天）</span></div>'
    )

def _workdays_in_month(year, m):
    from calendar import monthrange
    _, last = monthrange(year, m)
    d0 = date(year, m, 1)
    end = date(year, m, last)
    yday = TODAY - timedelta(days=1)
    if end > yday: end = yday  # 當月只算到昨天（今天尚未過完，不計入分母）
    if end < d0: return 1
    return _workdays_in_week(d0, end)

month_workdays = [_workdays_in_month(TODAY.year, m) for m in range(1, 13)]

col_m1, col_m2 = st.columns(2)
with col_m1:
    st.markdown(_SUBHEAD_B, unsafe_allow_html=True)
    st.markdown(_std_legend(STD_B_Q13, STD_B_Q4), unsafe_allow_html=True)
    st.plotly_chart(_bar_chart(month_labels, month_b, "rgba(67,192,143,0.85)", "#43C08F", height=270,
                               std=month_std_b),
                    width='stretch', config=_CHART_CFG)
    st.markdown(_avg_title(), unsafe_allow_html=True)
    st.plotly_chart(_avg_chart(month_labels, _avgs(month_b, month_workdays)),
                    width='stretch', config=_CHART_CFG)
    st.markdown(_mini_table(f"{TODAY.year}", month_labels, month_b, "#43C08F",
                            workdays=month_workdays), unsafe_allow_html=True)
with col_m2:
    st.markdown(_SUBHEAD_I, unsafe_allow_html=True)
    st.markdown(_std_legend(STD_I_Q13, STD_I_Q4), unsafe_allow_html=True)
    st.plotly_chart(_bar_chart(month_labels, month_i, "rgba(236,106,124,0.82)", "#EC6A7C", height=270,
                               std=month_std_i),
                    width='stretch', config=_CHART_CFG)
    st.markdown(_avg_title(), unsafe_allow_html=True)
    st.plotly_chart(_avg_chart(month_labels, _avgs(month_i, month_workdays)),
                    width='stretch', config=_CHART_CFG)
    st.markdown(_mini_table(f"{TODAY.year}", month_labels, month_i, "#EC6A7C",
                            workdays=month_workdays), unsafe_allow_html=True)

# 頁尾
st.markdown(
    f'<div style="text-align:center;color:#6E8094;font-size:11px;margin-top:26px;letter-spacing:1.5px">'
    f'DATA · {src_name or "wh_dashboard.db"}'
    f' &nbsp;｜&nbsp; {NOW.strftime("%H:%M")} 更新</div>',
    unsafe_allow_html=True
)
