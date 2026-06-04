import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import glob, os, sys
from datetime import date, timedelta, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from utils.shared import render_sidebar

st.set_page_config(page_title="倉儲備料看板", page_icon="🏭",
                   layout="wide", initial_sidebar_state="expanded")

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
    font-family:"Microsoft JhengHei","微軟正黑體",sans-serif !important;
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

# ══════════════════════════════════════════════════════
# NAS 設定（固定路徑，自動載入）
# ══════════════════════════════════════════════════════
_NAS_DIR    = r"\\192.168.2.34\MO_Storage\ORing MO\ORing-MO 工作\資材部\每日調撥與送燒ic(NEW)\3月-6月進貨資料表\調件備料統計表"
_FILE_PFX   = "調件備料統計"

def find_latest_wh():
    try:
        # 先找直接在資料夾內的檔案
        files = [
            os.path.join(_NAS_DIR, f)
            for f in os.listdir(_NAS_DIR)
            if not f.startswith('~$') and _FILE_PFX in f
            and f.lower().endswith(('.xlsx','.xls'))
        ]
        if not files:
            # 遞迴搜尋子資料夾
            files = glob.glob(os.path.join(_NAS_DIR, f"**/*{_FILE_PFX}*.xlsx"), recursive=True)
        if not files: return None, None
        files.sort(key=os.path.getmtime, reverse=True)
        f = files[0]
        mtime = pd.Timestamp(os.path.getmtime(f), unit='s').tz_localize('UTC').tz_convert('Asia/Taipei')
        return f, mtime
    except Exception:
        return None, None

# 自動抓 NAS；NAS 離線才需要手動上傳
src_file, src_mtime = find_latest_wh()

# ══════════════════════════════════════════════════════
# HEADER
# ══════════════════════════════════════════════════════
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

# ── NAS 狀態列 + 離線時顯示上傳按鈕 ──────────────────
if src_file:
    fname = os.path.basename(src_file) if isinstance(src_file, str) else src_file.name
    ts_str = src_mtime.strftime('%m/%d %H:%M') if src_mtime else ""
    c_info, c_btn = st.columns([5, 1])
    with c_info:
        st.markdown(
            f'<div style="background:#ffffff;border:1px solid #b2dfdb;'
            f'border-radius:8px;padding:8px 16px;font-size:13px;color:#15803d">'
            f'✅ &nbsp;NAS 已連線，自動載入最新檔案 &nbsp;·&nbsp; '
            f'<b style="color:#2E9D70">{fname}</b>'
            f'<span style="color:#6B7280;margin-left:8px">（{ts_str}）</span></div>',
            unsafe_allow_html=True
        )
    with c_btn:
        if st.button("🔄 重新偵測", key="wh_refresh", use_container_width=True):
            st.cache_data.clear()
            st.rerun()
else:
    st.markdown(
        '<div style="background:rgba(239,68,68,0.1);border:1px solid rgba(239,68,68,0.4);'
        'border-radius:8px;padding:10px 16px;margin-bottom:8px;color:#fca5a5;font-size:14px">'
        '⚠️ &nbsp;NAS 離線，請手動上傳「調件備料統計」Excel 檔</div>',
        unsafe_allow_html=True
    )
    uploaded = st.file_uploader(
        "上傳 調件備料統計 Excel", type=["xlsx","xls"], key="wh_upload",
        label_visibility="collapsed"
    )
    if uploaded:
        src_file  = uploaded
        src_mtime = pd.Timestamp.now()

if src_file is None:
    st.stop()

# ══════════════════════════════════════════════════════
# 讀取資料
# ══════════════════════════════════════════════════════
@st.cache_data(ttl=5*60, show_spinner=False)
def load_wh(file_key):
    xls = pd.ExcelFile(src_file) if isinstance(src_file, str) else pd.ExcelFile(src_file)

    # 調撥單
    diao = pd.read_excel(xls, sheet_name='調撥單', header=None)
    diao.columns = diao.iloc[0]; diao = diao.iloc[1:].reset_index(drop=True)
    for c in ['需求日','完成日','開單日','備料日']:
        if c in diao.columns:
            diao[c] = pd.to_datetime(diao[c], errors='coerce')
    for c in ['需求筆數','完成筆數']:
        if c in diao.columns:
            diao[c] = pd.to_numeric(diao[c], errors='coerce').fillna(0)

    # 入庫單據
    inbound = pd.read_excel(xls, sheet_name='入庫單據', header=None)
    inbound.columns = inbound.iloc[0]; inbound = inbound.iloc[1:].reset_index(drop=True)
    for c in ['驗畢日期','接單日期','預計完成日','完成日','取單日']:
        if c in inbound.columns:
            inbound[c] = pd.to_datetime(inbound[c], errors='coerce')
    if '筆數' in inbound.columns:
        inbound['筆數'] = pd.to_numeric(inbound['筆數'], errors='coerce').fillna(0)
    else:
        inbound['筆數'] = 0

    # 工時效率-每日
    eff = pd.read_excel(xls, sheet_name='工時效率計算-每日', header=None)
    # 結構：row0=備料/入庫 大標, row1=欄名, row2+= 資料
    eff_cols_biao = eff.iloc[1, :5].tolist()    # 備料欄
    eff_cols_in   = eff.iloc[1, 8:12].tolist()  # 入庫欄
    eff_biao = eff.iloc[2:, :5].copy()
    eff_biao.columns = eff_cols_biao
    eff_biao = eff_biao.rename(columns={eff_cols_biao[0]:'日期',eff_cols_biao[2]:'備料筆數',eff_cols_biao[3]:'平均筆數'})
    eff_biao['日期'] = pd.to_datetime(eff_biao['日期'], errors='coerce')
    eff_biao['備料筆數'] = pd.to_numeric(eff_biao.get('備料筆數',0), errors='coerce').fillna(0)

    eff_in = eff.iloc[2:, 8:12].copy()
    eff_in.columns = eff_cols_in
    eff_in = eff_in.rename(columns={eff_cols_in[0]:'日期',eff_cols_in[2]:'入庫筆數'})
    eff_in['日期'] = pd.to_datetime(eff_in['日期'], errors='coerce')
    eff_in['入庫筆數'] = pd.to_numeric(eff_in.get('入庫筆數',0), errors='coerce').fillna(0)

    # 錯料追蹤
    err_df = pd.read_excel(xls, sheet_name='錯料歸還追蹤', header=None)
    err_df.columns = err_df.iloc[0]; err_df = err_df.iloc[1:].reset_index(drop=True)
    for c in ['通知日期','結案日期']:
        if c in err_df.columns:
            err_df[c] = pd.to_datetime(err_df[c], errors='coerce')

    return diao, inbound, eff_biao, eff_in, err_df

file_key = getattr(src_file, 'name', str(src_file))
with st.spinner("載入資料中…"):
    diao, inbound, eff_biao, eff_in, err_df = load_wh(file_key)

# ══════════════════════════════════════════════════════
# 計算 KPI（顯示前一日數值）
# ══════════════════════════════════════════════════════
YESTERDAY = TODAY - timedelta(days=1)

# ── 備料（調撥單）──────────────────────────────────────
# 已完成：K欄（完成日）= 昨日 且 M欄（狀態）= 已完成 → 加總 G欄（需求筆數）
b_done_rows = diao[
    diao['完成日'].notna() &
    (diao['完成日'].dt.date == YESTERDAY) &
    (diao['狀態'] == '已完成')
]
b_done = int(b_done_rows['需求筆數'].sum())

# 待完成：F欄（需求日）有值 且 <= 昨日 且 K欄（完成日）空白 → 加總 G欄
b_pend_rows = diao[
    diao['需求日'].notna() &
    (diao['需求日'].dt.date <= YESTERDAY) &
    diao['完成日'].isna()
]
b_pend = int(b_pend_rows['需求筆數'].sum())

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

def _kpi_card(title, done, pend, rate, accent, glow, icon):
    total = done + pend
    pct   = int(rate * 100)
    if rate >= 0.8:   status = "🟢 進度良好"
    elif rate >= 0.5: status = "🟡 持續推進"
    else:             status = "🔴 進度落後"
    return (
        f'<div style="background:#FFFFFF;'
        f'border:1px solid {accent};border-radius:16px;padding:22px 24px;'
        f'box-shadow:0 0 28px {glow};height:100%">'
        f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px">'
        f'<div style="color:#a8c4e0;font-size:14px;font-weight:700;letter-spacing:2px">{icon} {title}</div>'
        f'<div style="color:#6B7280;font-size:13px">{status}</div></div>'
        f'<div style="display:flex;gap:0;margin-bottom:18px">'
        f'<div style="flex:1;text-align:center;border-right:1px solid #EDE5CF">'
        f'<div style="color:#2E9D70;font-size:56px;font-weight:900;line-height:1;'
        f'text-shadow:0 0 20px rgba(74,222,128,0.5)">{done:,}</div>'
        f'<div style="color:#6B7280;font-size:14px;margin-top:6px">已完成</div></div>'
        f'<div style="flex:1;text-align:center;border-right:1px solid #EDE5CF">'
        f'<div style="color:#B23A48;font-size:56px;font-weight:900;line-height:1;'
        f'text-shadow:0 0 20px rgba(248,113,113,0.4)">{pend:,}</div>'
        f'<div style="color:#6B7280;font-size:14px;margin-top:6px">待完成</div></div>'
        f'<div style="flex:1;text-align:center">'
        f'<div style="color:{accent};font-size:56px;font-weight:900;line-height:1;'
        f'text-shadow:0 0 20px {glow}">{pct}%</div>'
        f'<div style="color:#6B7280;font-size:14px;margin-top:6px">完成率</div></div>'
        f'</div>'
        f'<div style="background:#EDE5CF;border-radius:4px;height:8px;overflow:hidden">'
        f'<div style="display:flex;height:100%">'
        f'<div style="width:{pct}%;background:linear-gradient(90deg,#4ade80,#22c55e);'
        f'box-shadow:0 0 8px rgba(74,222,128,0.6)"></div>'
        f'<div style="width:{100-pct}%;background:#fecdd3"></div>'
        f'</div></div>'
        f'<div style="color:#6B7280;font-size:13px;margin-top:6px;text-align:right">'
        f'目標總筆數：{total:,}</div></div>'
    )

# 第三卡片：備料最高 / 入庫最高 分開顯示
def _top_person_card():
    ac = "#fbbf24"; glow = "rgba(251,191,36,0.25)"

    def _half(label, name, cnt, pct, color, bar_color):
        bar_w = min(int(pct), 100)
        return (
            f'<div style="flex:1;padding:14px 16px;'
            f'background:rgba(255,255,255,0.03);border-radius:10px">'
            f'<div style="color:#6B7280;font-size:12px;letter-spacing:1px;margin-bottom:8px">{label}</div>'
            f'<div style="color:{color};font-size:32px;font-weight:900;line-height:1;'
            f'text-shadow:0 0 18px {color}66">{name}</div>'
            f'<div style="display:flex;align-items:baseline;gap:8px;margin-top:10px">'
            f'<span style="color:{color};font-size:40px;font-weight:900">{cnt:,}</span>'
            f'<span style="color:#6B7280;font-size:14px">筆</span>'
            f'<span style="color:{ac};font-size:18px;font-weight:700;margin-left:6px">{pct}%</span>'
            f'</div>'
            f'<div style="color:#6B7280;font-size:12px;margin-top:4px">佔當日該項目總量</div>'
            f'<div style="background:#EDE5CF;border-radius:3px;height:5px;overflow:hidden;margin-top:8px">'
            f'<div style="width:{bar_w}%;height:100%;background:{bar_color};'
            f'box-shadow:0 0 6px {bar_color}99"></div></div>'
            f'</div>'
        )

    return (
        f'<div style="background:#FFFFFF;'
        f'border:1px solid {ac};border-radius:16px;padding:20px 22px;'
        f'box-shadow:0 0 28px {glow};height:100%">'
        f'<div style="color:#a8c4e0;font-size:14px;font-weight:700;letter-spacing:2px;margin-bottom:14px">'
        f'🏆 前日最高績效</div>'
        f'<div style="display:flex;gap:10px">'
        + _half("📦 備料", top_b_name, top_b_cnt, top_b_pct, "#22d3ee", "#22d3ee")
        + _half("🏭 入庫", top_i_name, top_i_cnt, top_i_pct, "#818cf8", "#818cf8")
        + f'</div></div>'
    )

c1, c2, c3 = st.columns(3)
c1.markdown(_kpi_card("備料", b_done, b_pend, b_rate,
    "#22d3ee","rgba(34,211,238,0.25)","📦"), unsafe_allow_html=True)
c2.markdown(_kpi_card("入庫", i_done, i_pend, i_rate,
    "#818cf8","rgba(129,140,248,0.25)","🏭"), unsafe_allow_html=True)
c3.markdown(_top_person_card(), unsafe_allow_html=True)

st.markdown("<div style='margin-top:20px'></div>", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════
# SECTION 2：人員今日完成筆數 + 入庫延遲警示
# ══════════════════════════════════════════════════════
col_person, col_alert = st.columns([3, 2])

with col_person:
    st.markdown(
        f'<div style="color:#6B7280;font-size:16px;font-weight:700;letter-spacing:1px;margin-bottom:12px">'
        f'👤 人員前日完成筆數（備料 · {YESTERDAY.strftime("%m/%d")}）</div>',
        unsafe_allow_html=True
    )
    person_today = (
        b_done_rows.groupby('備料人員')['需求筆數'].sum()
        .sort_values(ascending=False)
        .reset_index()
    )
    person_today.columns = ['人員', '完成筆數']
    person_today = person_today[person_today['人員'].notna()]

    if person_today.empty:
        st.markdown(
            '<div style="background:rgba(15,23,42,0.6);border:1px solid rgba(51,65,85,0.4);'
            'border-radius:8px;padding:20px;text-align:center;color:#6B7280">— 今日尚無完成記錄 —</div>',
            unsafe_allow_html=True
        )
    else:
        max_val = person_today['完成筆數'].max()
        fig_p = go.Figure(go.Bar(
            x=person_today['完成筆數'],
            y=person_today['人員'],
            orientation='h',
            marker=dict(
                color=[f"rgba(34,211,238,{0.4 + 0.6*(v/max_val):.2f})" for v in person_today['完成筆數']],
                line=dict(color="#2E9D70", width=1),
            ),
            text=person_today['完成筆數'].astype(int).astype(str) + " 筆",
            textposition="outside",
            textfont=dict(color="#cbd5e1", size=14),
        ))
        fig_p.update_layout(
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            xaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.05)",
                      tickfont=dict(color="#64748b", size=13), zeroline=False),
            yaxis=dict(showgrid=False, tickfont=dict(color="#94a3b8", size=14)),
            margin=dict(l=10, r=60, t=10, b=10),
            height=max(200, len(person_today) * 48),
            font=dict(color="#94a3b8"),
        )
        st.plotly_chart(fig_p, use_container_width=True)

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

    st.markdown(
        f'<div style="background:#FFFFFF;'
        f'border:1px solid rgba(56,189,248,0.4);border-radius:12px;padding:16px 18px;height:100%">'
        f'<div style="color:#6B7280;font-size:16px;font-weight:700;letter-spacing:1px;margin-bottom:12px">'
        f'⚡ 今日即時進度（{TODAY.strftime("%m/%d")} {NOW.strftime("%H:%M")} 止）</div>'
        f'<div style="display:flex;gap:0">'
        f'<div style="flex:1;text-align:center;border-right:1px solid #EDE5CF;padding:10px 0">'
        f'<div style="color:#2E9D70;font-size:52px;font-weight:900;line-height:1;'
        f'text-shadow:0 0 20px rgba(34,211,238,0.6)">{today_b_cnt:,}</div>'
        f'<div style="color:#6B7280;font-size:14px;margin-top:6px">📦 備料完成</div></div>'
        f'<div style="flex:1;text-align:center;padding:10px 0">'
        f'<div style="color:#5b7fa6;font-size:52px;font-weight:900;line-height:1;'
        f'text-shadow:0 0 20px rgba(129,140,248,0.6)">{today_i_cnt:,}</div>'
        f'<div style="color:#6B7280;font-size:14px;margin-top:6px">🏭 入庫完成</div></div>'
        f'</div>'
        f'<div style="margin-top:14px;border-top:1px solid #f0e8d8;padding-top:12px">'
        f'<div style="color:#6B7280;font-size:13px;margin-bottom:6px">今日備料人員</div>',
        unsafe_allow_html=True
    )
    if not today_b_rows.empty:
        by_p = today_b_rows.groupby('備料人員')['需求筆數'].sum().sort_values(ascending=False)
        for person, cnt in by_p.items():
            st.markdown(
                f'<div style="display:flex;justify-content:space-between;padding:3px 0;'
                f'border-bottom:1px solid rgba(255,255,255,0.04)">'
                f'<span style="color:#a8c4e0;font-size:13px">{person}</span>'
                f'<span style="color:#2E9D70;font-size:14px;font-weight:700">{int(cnt)} 筆</span>'
                f'</div>',
                unsafe_allow_html=True
            )
    else:
        st.markdown('<div style="color:#6B7280;font-size:13px">— 今日尚無備料完成記錄 —</div>',
                    unsafe_allow_html=True)
    st.markdown('</div></div>', unsafe_allow_html=True)

st.markdown("<div style='margin-top:24px'></div>", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════
# SECTION 3：近5週備料 + 入庫
# ══════════════════════════════════════════════════════
st.markdown(
    '<div style="color:#6B7280;font-size:16px;font-weight:700;letter-spacing:1px;margin-bottom:12px">'
    '📅 近5週備料 / 入庫完成筆數</div>',
    unsafe_allow_html=True
)

# 計算本週一
_wd0 = TODAY.weekday()
this_mon = TODAY - timedelta(days=_wd0)

week_labels, week_b, week_i = [], [], []
for w in range(4, -1, -1):   # 從4週前到本週
    wk_start = this_mon - timedelta(weeks=w)
    wk_end   = wk_start + timedelta(days=6)
    label = "本週" if w == 0 else (f"上週" if w == 1 else f"-{w}週")

    mask = diao['完成日'].notna() & \
           (diao['完成日'].dt.date >= wk_start) & \
           (diao['完成日'].dt.date <= wk_end)
    b_val = int(diao[mask & (diao['狀態'] == '已完成')]['需求筆數'].sum())
    i_val = int(diao[mask & (diao['狀態'] == '上架')]['完成筆數'].sum())

    week_labels.append(f"{label}<br>{wk_start.strftime('%m/%d')}~{wk_end.strftime('%m/%d')}")
    week_b.append(b_val)
    week_i.append(i_val)

fig_week = go.Figure()
fig_week.add_trace(go.Bar(
    name="備料", x=week_labels, y=week_b,
    marker=dict(color="rgba(46,157,112,0.80)", line=dict(color="#2E9D70", width=1.5)),
    text=[f"{v:,}" for v in week_b], textposition="outside",
    textfont=dict(color="#2E9D70", size=13),
))
fig_week.add_trace(go.Bar(
    name="入庫", x=week_labels, y=week_i,
    marker=dict(color="rgba(178,58,72,0.75)", line=dict(color="#B23A48", width=1.5)),
    text=[f"{v:,}" for v in week_i], textposition="outside",
    textfont=dict(color="#B23A48", size=13),
))
fig_week.update_layout(
    barmode="group",
    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    font=dict(color="#94a3b8", size=13),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
                font=dict(color="#cbd5e1", size=13), bgcolor="rgba(0,0,0,0)"),
    xaxis=dict(showgrid=False, tickfont=dict(color="#64748b", size=12)),
    yaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.05)",
               tickfont=dict(color="#64748b", size=12), zeroline=False),
    margin=dict(l=20, r=20, t=40, b=20), height=280,
)
st.plotly_chart(fig_week, use_container_width=True)

st.markdown("<div style='margin-top:8px'></div>", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════
# SECTION 4：1~12月備料 + 入庫
# ══════════════════════════════════════════════════════
st.markdown(
    '<div style="color:#6B7280;font-size:16px;font-weight:700;letter-spacing:1px;margin-bottom:12px">'
    f'📆 年度月份備料 / 入庫完成筆數（{TODAY.year}年）</div>',
    unsafe_allow_html=True
)

month_labels = [f"{m}月" for m in range(1, 13)]
month_b, month_i = [], []

for m in range(1, 13):
    mask = diao['完成日'].notna() & \
           (diao['完成日'].dt.year == TODAY.year) & \
           (diao['完成日'].dt.month == m)
    month_b.append(int(diao[mask & (diao['狀態'] == '已完成')]['需求筆數'].sum()))
    month_i.append(int(diao[mask & (diao['狀態'] == '上架')]['完成筆數'].sum()))

fig_month = go.Figure()
fig_month.add_trace(go.Bar(
    name="備料", x=month_labels, y=month_b,
    marker=dict(color="rgba(46,157,112,0.80)", line=dict(color="#2E9D70", width=1.5)),
    text=[f"{v:,}" if v else "" for v in month_b], textposition="outside",
    textfont=dict(color="#2E9D70", size=12),
))
fig_month.add_trace(go.Bar(
    name="入庫", x=month_labels, y=month_i,
    marker=dict(color="rgba(178,58,72,0.75)", line=dict(color="#B23A48", width=1.5)),
    text=[f"{v:,}" if v else "" for v in month_i], textposition="outside",
    textfont=dict(color="#B23A48", size=12),
))
fig_month.update_layout(
    barmode="group",
    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    font=dict(color="#94a3b8", size=13),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
                font=dict(color="#cbd5e1", size=13), bgcolor="rgba(0,0,0,0)"),
    xaxis=dict(showgrid=False, tickfont=dict(color="#64748b", size=13)),
    yaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.05)",
               tickfont=dict(color="#64748b", size=12), zeroline=False),
    margin=dict(l=20, r=20, t=40, b=20), height=300,
)
st.plotly_chart(fig_month, use_container_width=True)

# 頁尾
st.markdown(
    f'<div style="text-align:center;color:#1e3a5f;font-size:11px;margin-top:24px;letter-spacing:1px">'
    f'DATA · {os.path.basename(str(src_file)) if isinstance(src_file,str) else getattr(src_file,"name","上傳檔案")}'
    f' &nbsp;｜&nbsp; {NOW.strftime("%H:%M")} 更新</div>',
    unsafe_allow_html=True
)
