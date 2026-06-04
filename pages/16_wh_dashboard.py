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

def _kpi_card(title, done, pend, rate, icon):
    total = done + pend
    pct   = int(rate * 100)
    if rate >= 0.8:   status_txt,status_c = "達標",    "#2E9D70"
    elif rate >= 0.5: status_txt,status_c = "持續推進", "#d97706"
    else:             status_txt,status_c = "進度落後", "#B23A48"
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
        f'<div style="color:#6B7280;font-size:14px;margin-top:6px">已完成</div></div>'
        f'<div style="flex:1;text-align:center;border-right:1px solid #EDE5CF">'
        f'<div style="color:#B23A48;font-size:54px;font-weight:900;line-height:1">{pend:,}</div>'
        f'<div style="color:#6B7280;font-size:14px;margin-top:6px">待完成</div></div>'
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
        f'目標總筆數：{total:,}</div></div>'
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
        + _half("🏭 入庫", top_i_name, top_i_cnt, top_i_pct, "#B23A48", "#B23A48")
        + f'</div></div>'
    )

c1, c2, c3 = st.columns(3)
c1.markdown(_kpi_card("備料", b_done, b_pend, b_rate, "📦"), unsafe_allow_html=True)
c2.markdown(_kpi_card("入庫", i_done, i_pend, i_rate, "🏭"), unsafe_allow_html=True)
c3.markdown(_top_person_card(), unsafe_allow_html=True)

st.markdown("<div style='margin-top:20px'></div>", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════
# SECTION 2：人員今日完成筆數 + 入庫延遲警示
# ══════════════════════════════════════════════════════
col_person, col_alert = st.columns([3, 2])

with col_person:
    st.markdown(
        f'<div style="color:#1D2B3A;font-size:16px;font-weight:800;letter-spacing:0.3px;margin-bottom:12px">'
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
            '<div style="background:#fdfaf5;border:1px solid #E6D8B8;'
            'border-radius:8px;padding:20px;text-align:center;color:#6B7280">— 今日尚無完成記錄 —</div>',
            unsafe_allow_html=True
        )
    else:
        max_val = person_today['完成筆數'].max()
        max_val = person_today['完成筆數'].max()
        fig_p = go.Figure(go.Bar(
            x=person_today['完成筆數'],
            y=person_today['人員'],
            orientation='h',
            marker=dict(
                color=[f"rgba(46,157,112,{0.45 + 0.55*(v/max_val):.2f})" for v in person_today['完成筆數']],
                line=dict(color="#2E9D70", width=1),
            ),
            text=person_today['完成筆數'].astype(int).astype(str) + " 筆",
            textposition="outside",
            textfont=dict(color="#1D2B3A", size=14,
                          family="Microsoft JhengHei"),
            cliponaxis=False,
        ))
        fig_p.update_layout(
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            xaxis=dict(
                showgrid=True, gridcolor="#EDE5CF",
                tickfont=dict(color="#6B7280", size=13),
                zeroline=False, dtick=20,
                range=[0, max_val * 1.25],
                automargin=True,
            ),
            yaxis=dict(showgrid=False, tickfont=dict(color="#1D2B3A", size=14,
                       family="Microsoft JhengHei")),
            margin=dict(l=10, r=20, t=10, b=10),
            height=max(200, len(person_today) * 52),
            font=dict(color="#6B7280", family="Microsoft JhengHei"),
        )
        st.plotly_chart(fig_p, use_container_width=True,
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
        f'<div style="flex:1;text-align:center;padding:10px 0">'
        f'<div style="color:#B23A48;font-size:52px;font-weight:900;line-height:1">{today_i_cnt:,}</div>'
        f'<div style="color:#6B7280;font-size:14px;margin-top:6px">🏭 入庫完成</div></div>'
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
st.markdown(
    '<div style="color:#1D2B3A;font-size:16px;font-weight:800;letter-spacing:0.3px;margin-bottom:14px">'
    '📅 近5週完成筆數</div>', unsafe_allow_html=True
)

# 計算本週一 & 各週數據
_wd0 = TODAY.weekday()
this_mon = TODAY - timedelta(days=_wd0)

week_short = []   # 短標籤（表格用）
week_labels = []  # 長標籤（圖表用）
week_b, week_i = [], []

for w in range(4, -1, -1):
    wk_start = this_mon - timedelta(weeks=w)
    wk_end   = wk_start + timedelta(days=6)
    lbl = "本週" if w==0 else ("上週" if w==1 else f"-{w}週")
    mask = (diao['完成日'].notna() &
            (diao['完成日'].dt.date >= wk_start) &
            (diao['完成日'].dt.date <= wk_end))
    week_short.append(f"{lbl}\n{wk_start.strftime('%m/%d')}")
    week_labels.append(f"{lbl}<br>{wk_start.strftime('%m/%d')}~{wk_end.strftime('%m/%d')}")
    week_b.append(int(diao[mask & (diao['狀態']=='已完成')]['需求筆數'].sum()))
    week_i.append(int(diao[mask & (diao['狀態']=='上架')]['完成筆數'].sum()))

def _bar_chart(labels, values, color_fill, color_line, height=240):
    fig = go.Figure(go.Bar(
        x=labels, y=values,
        marker=dict(color=color_fill, line=dict(color=color_line, width=1.5)),
        text=[f"{v:,}" if v else "0" for v in values],
        textposition="outside",
        textfont=dict(color=color_line, size=14, family="Microsoft JhengHei"),
    ))
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
        xaxis=dict(showgrid=False, tickfont=dict(color="#1D2B3A", size=13,
                   family="Microsoft JhengHei")),
        yaxis=dict(showgrid=True, gridcolor="#EDE5CF",
                   tickfont=dict(color="#6B7280", size=12), zeroline=False),
        margin=dict(l=10, r=10, t=36, b=10), height=height,
    )
    return fig

def _mini_table(row_label, labels, values, val_color):
    """HTML 小表格，一行標題 + 一行數值"""
    th_style = (f'style="background:#1D2B3A;color:#ffffff;padding:8px 14px;'
                f'font-size:14px;font-weight:700;text-align:center;'
                f'border:1px solid #E6D8B8;font-family:Microsoft JhengHei"')
    td_label_style = (f'style="background:#fdfaf5;color:#1D2B3A;padding:8px 14px;'
                      f'font-size:13px;font-weight:700;border:1px solid #E6D8B8;'
                      f'text-align:center;font-family:Microsoft JhengHei"')
    td_val_style = (f'style="background:#ffffff;color:{val_color};padding:8px 14px;'
                    f'font-size:15px;font-weight:900;border:1px solid #E6D8B8;'
                    f'text-align:center;font-family:Microsoft JhengHei"')
    ths = "".join(f"<th {th_style}>{l}</th>" for l in labels)
    tds = "".join(f"<td {td_val_style}>{v:,}</td>" for v in values)
    return (
        f'<div style="overflow-x:auto;margin-top:6px">'
        f'<table style="width:100%;border-collapse:collapse;border-radius:8px;overflow:hidden">'
        f'<tr><th {td_label_style}>{row_label}</th>{ths}</tr>'
        f'<tr><td {td_label_style}>完成筆數</td>{tds}</tr>'
        f'</table></div>'
    )

col_w1, col_w2 = st.columns(2)

with col_w1:
    st.markdown('<div style="color:#2E9D70;font-size:15px;font-weight:700;margin-bottom:4px">📦 備料</div>',
                unsafe_allow_html=True)
    st.plotly_chart(_bar_chart(week_labels, week_b,
                               "rgba(46,157,112,0.75)", "#2E9D70"),
                    use_container_width=True, config=dict(staticPlot=True))
    st.markdown(_mini_table("近5週", week_short, week_b, "#2E9D70"),
                unsafe_allow_html=True)

with col_w2:
    st.markdown('<div style="color:#B23A48;font-size:15px;font-weight:700;margin-bottom:4px">🏭 入庫</div>',
                unsafe_allow_html=True)
    st.plotly_chart(_bar_chart(week_labels, week_i,
                               "rgba(178,58,72,0.70)", "#B23A48"),
                    use_container_width=True, config=dict(staticPlot=True))
    st.markdown(_mini_table("近5週", week_short, week_i, "#B23A48"),
                unsafe_allow_html=True)

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

col_m1, col_m2 = st.columns(2)

with col_m1:
    st.markdown('<div style="color:#2E9D70;font-size:15px;font-weight:700;margin-bottom:4px">📦 備料</div>',
                unsafe_allow_html=True)
    st.plotly_chart(_bar_chart(month_labels_long, month_b,
                               "rgba(46,157,112,0.75)", "#2E9D70", height=260),
                    use_container_width=True, config=dict(staticPlot=True))
    st.markdown(_mini_table(f"{TODAY.year}", month_labels_short, month_b, "#2E9D70"),
                unsafe_allow_html=True)

with col_m2:
    st.markdown('<div style="color:#B23A48;font-size:15px;font-weight:700;margin-bottom:4px">🏭 入庫</div>',
                unsafe_allow_html=True)
    st.plotly_chart(_bar_chart(month_labels_long, month_i,
                               "rgba(178,58,72,0.70)", "#B23A48", height=260),
                    use_container_width=True, config=dict(staticPlot=True))
    st.markdown(_mini_table(f"{TODAY.year}", month_labels_short, month_i, "#B23A48"),
                unsafe_allow_html=True)

# 頁尾
st.markdown(
    f'<div style="text-align:center;color:#1e3a5f;font-size:11px;margin-top:24px;letter-spacing:1px">'
    f'DATA · {os.path.basename(str(src_file)) if isinstance(src_file,str) else getattr(src_file,"name","上傳檔案")}'
    f' &nbsp;｜&nbsp; {NOW.strftime("%H:%M")} 更新</div>',
    unsafe_allow_html=True
)
