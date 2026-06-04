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
.stApp { background:linear-gradient(160deg,#020918 0%,#061228 55%,#0a1a35 100%) !important; }
[data-testid="stHeader"]  { background:transparent !important; }
[data-testid="stSidebar"] { background:#050e22 !important; }
.block-container { padding:0.6rem 1.4rem 2rem !important; max-width:100% !important; }
#MainMenu, footer, [data-testid="stToolbar"] { visibility:hidden; }
/* 隱藏側邊欄與展開按鈕，全畫面看板 */
[data-testid="stSidebar"], [data-testid="collapsedControl"] { display:none !important; }
.block-container { padding-left:1.4rem !important; }
::-webkit-scrollbar { width:5px; }
::-webkit-scrollbar-track { background:#020918; }
::-webkit-scrollbar-thumb { background:#1e3a8a; border-radius:3px; }
.js-plotly-plot .plotly .bg { fill:transparent !important; }
html, body, [class*="css"] { font-size:16px !important; }
div[data-testid="stSidebarContent"] label { color:#94a3b8 !important; }
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
    f'<div style="background:linear-gradient(90deg,#0d1f4e 0%,#0f2d6b 40%,#0d1f4e 100%);'
    f'border:1px solid rgba(56,189,248,0.35);border-radius:14px;padding:16px 28px;margin-bottom:18px;'
    f'box-shadow:0 0 30px rgba(14,165,233,0.15);'
    f'display:grid;grid-template-columns:1fr auto 1fr;align-items:center;gap:16px">'
    f'<div>'
    f'<div style="color:#38bdf8;font-size:13px;font-weight:700;letter-spacing:2px">ORing &nbsp;·&nbsp; 倉管 WD</div>'
    f'<div style="color:#94a3b8;font-size:13px;margin-top:4px">'
    f'🕐 {NOW.strftime("%H:%M")} &nbsp;｜&nbsp; 資料：{data_ts}</div>'
    f'</div>'
    f'<div style="text-align:center">'
    f'<div style="color:#f0f9ff;font-size:38px;font-weight:900;line-height:1.15;'
    f'text-shadow:0 0 30px rgba(56,189,248,0.7);letter-spacing:2px">倉儲備料即時看板</div>'
    f'<div style="color:#38bdf8;font-size:15px;font-weight:600;letter-spacing:4px;margin-top:4px;'
    f'text-shadow:0 0 12px rgba(56,189,248,0.5)">WAREHOUSE MATERIAL PREP DASHBOARD</div>'
    f'</div>'
    f'<div style="text-align:right">'
    f'<div style="color:#f0f9ff;font-size:30px;font-weight:900;'
    f'text-shadow:0 0 20px rgba(56,189,248,0.5)">{TODAY.strftime("%Y / %m / %d")}</div>'
    f'<div style="color:#38bdf8;font-size:18px;font-weight:700;margin-top:2px">（週{wday}）</div>'
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
            f'<div style="background:rgba(6,78,59,0.2);border:1px solid rgba(34,211,238,0.3);'
            f'border-radius:8px;padding:8px 16px;font-size:13px;color:#6ee7b7">'
            f'✅ &nbsp;NAS 已連線，自動載入最新檔案 &nbsp;·&nbsp; '
            f'<b style="color:#22d3ee">{fname}</b>'
            f'<span style="color:#475569;margin-left:8px">（{ts_str}）</span></div>',
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
    f'<div style="color:#38bdf8;font-size:14px;font-weight:700;letter-spacing:2px;margin-bottom:12px">'
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
        f'<div style="background:linear-gradient(135deg,rgba(13,28,65,0.95),rgba(8,18,45,0.95));'
        f'border:1px solid {accent};border-radius:16px;padding:22px 24px;'
        f'box-shadow:0 0 28px {glow};height:100%">'
        f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px">'
        f'<div style="color:#94a3b8;font-size:14px;font-weight:700;letter-spacing:2px">{icon} {title}</div>'
        f'<div style="color:#64748b;font-size:13px">{status}</div></div>'
        f'<div style="display:flex;gap:0;margin-bottom:18px">'
        f'<div style="flex:1;text-align:center;border-right:1px solid rgba(255,255,255,0.07)">'
        f'<div style="color:#4ade80;font-size:56px;font-weight:900;line-height:1;'
        f'text-shadow:0 0 20px rgba(74,222,128,0.5)">{done:,}</div>'
        f'<div style="color:#374151;font-size:14px;margin-top:6px">已完成</div></div>'
        f'<div style="flex:1;text-align:center;border-right:1px solid rgba(255,255,255,0.07)">'
        f'<div style="color:#f87171;font-size:56px;font-weight:900;line-height:1;'
        f'text-shadow:0 0 20px rgba(248,113,113,0.4)">{pend:,}</div>'
        f'<div style="color:#374151;font-size:14px;margin-top:6px">待完成</div></div>'
        f'<div style="flex:1;text-align:center">'
        f'<div style="color:{accent};font-size:56px;font-weight:900;line-height:1;'
        f'text-shadow:0 0 20px {glow}">{pct}%</div>'
        f'<div style="color:#374151;font-size:14px;margin-top:6px">完成率</div></div>'
        f'</div>'
        f'<div style="background:rgba(255,255,255,0.05);border-radius:4px;height:8px;overflow:hidden">'
        f'<div style="display:flex;height:100%">'
        f'<div style="width:{pct}%;background:linear-gradient(90deg,#4ade80,#22c55e);'
        f'box-shadow:0 0 8px rgba(74,222,128,0.6)"></div>'
        f'<div style="width:{100-pct}%;background:rgba(248,113,113,0.4)"></div>'
        f'</div></div>'
        f'<div style="color:#374151;font-size:13px;margin-top:6px;text-align:right">'
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
            f'<div style="color:#64748b;font-size:12px;letter-spacing:1px;margin-bottom:8px">{label}</div>'
            f'<div style="color:{color};font-size:32px;font-weight:900;line-height:1;'
            f'text-shadow:0 0 18px {color}66">{name}</div>'
            f'<div style="display:flex;align-items:baseline;gap:8px;margin-top:10px">'
            f'<span style="color:{color};font-size:40px;font-weight:900">{cnt:,}</span>'
            f'<span style="color:#374151;font-size:14px">筆</span>'
            f'<span style="color:{ac};font-size:18px;font-weight:700;margin-left:6px">{pct}%</span>'
            f'</div>'
            f'<div style="color:#374151;font-size:12px;margin-top:4px">佔當日該項目總量</div>'
            f'<div style="background:rgba(255,255,255,0.05);border-radius:3px;height:5px;overflow:hidden;margin-top:8px">'
            f'<div style="width:{bar_w}%;height:100%;background:{bar_color};'
            f'box-shadow:0 0 6px {bar_color}99"></div></div>'
            f'</div>'
        )

    return (
        f'<div style="background:linear-gradient(135deg,rgba(13,28,65,0.95),rgba(8,18,45,0.95));'
        f'border:1px solid {ac};border-radius:16px;padding:20px 22px;'
        f'box-shadow:0 0 28px {glow};height:100%">'
        f'<div style="color:#94a3b8;font-size:14px;font-weight:700;letter-spacing:2px;margin-bottom:14px">'
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
        f'<div style="color:#38bdf8;font-size:14px;font-weight:700;letter-spacing:2px;margin-bottom:12px">'
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
            'border-radius:8px;padding:20px;text-align:center;color:#475569">— 今日尚無完成記錄 —</div>',
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
                line=dict(color="#22d3ee", width=1),
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
    st.markdown(
        '<div style="color:#f87171;font-size:14px;font-weight:700;letter-spacing:2px;margin-bottom:12px">'
        '⚠️ 入庫單延遲警示</div>',
        unsafe_allow_html=True
    )
    overdue_ib = inbound[
        inbound['完成日'].isna() &
        inbound['預計完成日'].notna() &
        (inbound['預計完成日'].dt.date < TODAY)
    ].copy()
    overdue_ib['逾期天數'] = (pd.Timestamp(TODAY) - overdue_ib['預計完成日']).dt.days

    if overdue_ib.empty:
        st.markdown(
            '<div style="background:rgba(6,78,59,0.2);border:1px solid rgba(34,211,238,0.3);'
            'border-radius:8px;padding:16px;text-align:center;color:#6ee7b7;font-size:15px">'
            '✅ 目前無逾期入庫單</div>',
            unsafe_allow_html=True
        )
    else:
        st.markdown(
            f'<div style="background:rgba(127,29,29,0.2);border:1px solid rgba(239,68,68,0.3);'
            f'border-radius:8px;padding:8px 14px;margin-bottom:8px;color:#fca5a5;font-size:13px">'
            f'共 <b style="font-size:20px;color:#f87171">{len(overdue_ib)}</b> 筆入庫單逾期未完成</div>',
            unsafe_allow_html=True
        )
        for _, row in overdue_ib.sort_values('逾期天數', ascending=False).head(8).iterrows():
            days = int(row['逾期天數'])
            no   = str(row.get('編號', row.get('單號', '—')))
            staff = str(row.get('入庫人員', '—'))
            pred = row['預計完成日'].strftime('%m/%d') if pd.notna(row['預計完成日']) else '—'
            sev  = "#ef4444" if days >= 5 else "#f97316"
            st.markdown(
                f'<div style="background:rgba(8,15,40,0.7);border:1px solid rgba(239,68,68,0.25);'
                f'border-left:4px solid {sev};border-radius:6px;padding:8px 12px;margin-bottom:5px">'
                f'<div style="display:flex;justify-content:space-between;align-items:center">'
                f'<span style="color:#fca5a5;font-size:13px;font-weight:700">{no}</span>'
                f'<span style="color:{sev};font-size:13px;font-weight:800">逾期 {days} 天</span>'
                f'</div>'
                f'<div style="color:#475569;font-size:12px;margin-top:3px">'
                f'預計完成 {pred} &nbsp;｜&nbsp; 負責：{staff}</div>'
                f'</div>',
                unsafe_allow_html=True
            )

st.markdown("<div style='margin-top:20px'></div>", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════
# SECTION 3：每日趨勢折線圖
# ══════════════════════════════════════════════════════
st.markdown(
    '<div style="color:#38bdf8;font-size:14px;font-weight:700;letter-spacing:2px;margin-bottom:10px">'
    '📈 每日備料 / 入庫完成筆數趨勢（近30日）</div>',
    unsafe_allow_html=True
)

cutoff = pd.Timestamp(TODAY - timedelta(days=30))
eff_b_recent = eff_biao[eff_biao['日期'] >= cutoff].dropna(subset=['日期']).sort_values('日期')
eff_i_recent = eff_in[eff_in['日期'] >= cutoff].dropna(subset=['日期']).sort_values('日期')

fig_trend = go.Figure()
if not eff_b_recent.empty:
    fig_trend.add_trace(go.Scatter(
        x=eff_b_recent['日期'], y=eff_b_recent['備料筆數'],
        name="備料完成筆數",
        line=dict(color="#22d3ee", width=2.5),
        mode="lines+markers",
        marker=dict(size=6, color="#22d3ee"),
        fill="tozeroy", fillcolor="rgba(34,211,238,0.06)"
    ))
if not eff_i_recent.empty:
    fig_trend.add_trace(go.Scatter(
        x=eff_i_recent['日期'], y=eff_i_recent['入庫筆數'],
        name="入庫完成筆數",
        line=dict(color="#818cf8", width=2.5),
        mode="lines+markers",
        marker=dict(size=6, color="#818cf8"),
        fill="tozeroy", fillcolor="rgba(129,140,248,0.06)"
    ))
fig_trend.update_layout(
    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    font=dict(color="#94a3b8", size=13),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
                font=dict(color="#cbd5e1", size=13), bgcolor="rgba(0,0,0,0)"),
    xaxis=dict(showgrid=False, tickfont=dict(color="#64748b", size=12),
               tickformat="%m/%d"),
    yaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.05)",
               tickfont=dict(color="#64748b", size=12), zeroline=False),
    margin=dict(l=20, r=20, t=30, b=20),
    height=260,
)
st.plotly_chart(fig_trend, use_container_width=True)

# ══════════════════════════════════════════════════════
# SECTION 4：錯料追蹤（未結案）
# ══════════════════════════════════════════════════════
open_err = err_df[err_df['結案日期'].isna()].copy() if '結案日期' in err_df.columns else pd.DataFrame()

if not open_err.empty:
    st.markdown("<div style='margin-top:10px'></div>", unsafe_allow_html=True)
    st.markdown(
        f'<div style="background:linear-gradient(90deg,rgba(120,53,15,0.5),rgba(80,30,5,0.3));'
        f'border:1px solid rgba(251,191,36,0.4);border-radius:10px;padding:10px 18px;margin-bottom:12px;'
        f'box-shadow:0 0 14px rgba(251,191,36,0.1)">'
        f'<span style="color:#fde68a;font-size:15px;font-weight:800">'
        f'🔶 &nbsp;錯料歸還追蹤（未結案）&nbsp; — 共 {len(open_err)} 筆</span>'
        f'</div>',
        unsafe_allow_html=True
    )
    cols_e = st.columns(min(4, len(open_err)))
    for i, (_, row) in enumerate(open_err.iterrows()):
        if i >= 8: break
        with cols_e[i % 4]:
            pno  = str(row.get('料號','—'))
            qty  = row.get('數量','—')
            noti = row['通知日期'].strftime('%m/%d') if pd.notna(row.get('通知日期')) else '—'
            note = str(row.get('備註','')) or ''
            st.markdown(
                f'<div style="background:rgba(8,15,40,0.7);border:1px solid rgba(251,191,36,0.25);'
                f'border-left:4px solid #fbbf24;border-radius:6px;padding:10px 12px;margin-bottom:8px">'
                f'<div style="color:#fde68a;font-size:13px;font-weight:700;margin-bottom:4px">{pno}</div>'
                f'<div style="color:#94a3b8;font-size:12px">數量：{qty}</div>'
                f'<div style="color:#475569;font-size:12px">通知日：{noti}</div>'
                + (f'<div style="color:#64748b;font-size:11px;margin-top:4px">{note[:40]}</div>' if note else '')
                + f'</div>',
                unsafe_allow_html=True
            )

# 頁尾
st.markdown(
    f'<div style="text-align:center;color:#1e3a5f;font-size:11px;margin-top:24px;letter-spacing:1px">'
    f'DATA · {os.path.basename(str(src_file)) if isinstance(src_file,str) else getattr(src_file,"name","上傳檔案")}'
    f' &nbsp;｜&nbsp; {NOW.strftime("%H:%M")} 更新</div>',
    unsafe_allow_html=True
)
