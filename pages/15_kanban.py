import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import re
from datetime import date, timedelta, datetime
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from utils.shared import render_sidebar

st.set_page_config(page_title="工單進度看板", page_icon="📺",
                   layout="wide", initial_sidebar_state="collapsed")

st.markdown("""
<style>
.stApp { background:linear-gradient(160deg,#020918 0%,#061228 55%,#0a1a35 100%) !important; }
[data-testid="stHeader"]  { background:transparent !important; }
[data-testid="stSidebar"] { background:#050e22 !important; }
.block-container { padding:0.6rem 1.2rem 2rem !important; max-width:100% !important; }
#MainMenu, footer, [data-testid="stToolbar"] { visibility:hidden; }
::-webkit-scrollbar { width:5px; }
::-webkit-scrollbar-track { background:#020918; }
::-webkit-scrollbar-thumb { background:#1e3a8a; border-radius:3px; }
/* plotly 圖表背景透明 */
.js-plotly-plot .plotly .bg { fill:transparent !important; }
</style>
""", unsafe_allow_html=True)

render_sidebar()

# ══════════════════════════════════════════════════════
# 常數 & 函式
# ══════════════════════════════════════════════════════
TODAY    = date.today()
NOW      = datetime.now()
REF_YEAR = TODAY.year
DAILY_CAP   = 200
MIN_BUFFER  = 10

TAIWAN_HOLIDAYS = {
    date(2026,1,1), date(2026,1,2),
    date(2026,2,16), date(2026,2,17), date(2026,2,18),
    date(2026,2,19), date(2026,2,20),
    date(2026,3,2),  date(2026,4,3),  date(2026,4,6),
    date(2026,5,1),  date(2026,6,19), date(2026,9,25),
    date(2026,10,9),
}

def count_workdays(start, end):
    if not start or not end or start >= end: return 0
    count, cur = 0, start
    while cur < end:
        cur += timedelta(days=1)
        if cur.weekday() < 5 and cur not in TAIWAN_HOLIDAYS: count += 1
    return count

def parse_date_str(s):
    try:
        m, d = map(int, s.split('/'))
        dt = date(REF_YEAR, m, d)
        if (TODAY - dt).days > 180: dt = date(REF_YEAR+1, m, d)
        return dt
    except Exception: return None

def parse_ship_date(raw):
    if pd.isna(raw): return None, ''
    s = str(raw).strip()
    if s in ('','nan','None','TBD','試產','00:00:00'):
        return None, s if s not in ('nan','None','00:00:00') else ''
    if hasattr(raw,'date'): d=raw.date(); return d, d.strftime('%Y-%m-%d')
    try: d=pd.to_datetime(s).date(); return d, d.strftime('%Y-%m-%d')
    except Exception: pass
    found = re.findall(r'(\d{1,2})/(\d{1,2})', s)
    dates = [parse_date_str(f'{m}/{d}') for m,d in found]
    dates = [d for d in dates if d]
    return (min(dates), s) if dates else (None, s)

def parse_material_status(text):
    if pd.isna(text) or not str(text).strip(): return None,[],[],[]
    lines = str(text).strip().split('\n')
    all_dates, delayed, iqc, future = [],[],[],[]
    for line in lines:
        line = line.strip()
        if not line: continue
        mat_no = line.split('*')[0].strip() if '*' in line else line[:50]
        is_iqc = bool(re.search(r'IQC', line, re.IGNORECASE))
        date_strs = re.findall(r'\((\d{1,2}/\d{1,2})\)', line)
        mat_dates = [parse_date_str(s) for s in date_strs]
        mat_dates = [d for d in mat_dates if d]
        if mat_dates:
            latest = max(mat_dates); all_dates.append(latest)
            if is_iqc:      iqc.append((mat_no, latest))
            elif latest < TODAY: delayed.append((mat_no, latest, (TODAY-latest).days))
            else:           future.append((mat_no, latest, (latest-TODAY).days))
        elif is_iqc: iqc.append((mat_no, None))
    return (max(all_dates) if all_dates else None), delayed, iqc, future

def parse_file(path):
    df = pd.read_excel(path, sheet_name='LIST', header=0)
    rows = []
    for _, r in df.iterrows():
        wo=str(r.iloc[1]).strip() if pd.notna(r.iloc[1]) else ''
        product=str(r.iloc[2]).strip() if pd.notna(r.iloc[2]) else ''
        qty=r.iloc[3]; rate=float(r.iloc[5]) if pd.notna(r.iloc[5]) else 0.0
        hint=str(r.iloc[8]).strip() if pd.notna(r.iloc[8]) else ''
        mat_text=r.iloc[11]
        if not wo or wo=='nan': continue
        ship_date, ship_label = parse_ship_date(r.iloc[12])
        latest_mat, delayed, iqc, future = parse_material_status(mat_text)
        hint_qi = any(k in hint for k in ('已發料','已齊料','已發放','齊料'))
        qi_date = latest_mat
        if qi_date is None and hint_qi:
            m=re.search(r'(\d{1,2})/(\d{1,2})',hint)
            qi_date=parse_date_str(f'{m.group(1)}/{m.group(2)}') if m else TODAY
        if rate>=1.0 or hint_qi: mat_status='已齊料'; qi_date=qi_date or TODAY
        elif rate==0.0: mat_status='完全缺料'
        else: mat_status=f'缺料 {rate:.0%}'
        if ship_date:
            wdays_to_ship=count_workdays(TODAY-timedelta(days=1),ship_date)
            is_urgent=(wdays_to_ship<=10)
        else: wdays_to_ship=None; is_urgent=False
        rows.append({'工單':wo,'成品料號':product,'預計產量':qty,
            '出貨日':ship_date,'出貨日_顯示':ship_label,
            '料況狀態':mat_status,'重點提示':hint,'整體料齊率':rate,
            '距出貨工作天':wdays_to_ship,'急件':is_urgent,
            '_delayed':delayed,'_iqc':iqc,'_future':future})
    return pd.DataFrame(rows)

# ── 自動載入 ──────────────────────────────────────────
BASE_DIR  = r"\\192.168.2.34\MO_Storage\ORing MO\ORing-MO 工作\早會資料夾"
FILE_NAME = "簡版-工單缺料狀況.xlsx"

def find_latest():
    try:
        import glob
        files=glob.glob(os.path.join(BASE_DIR,"**",FILE_NAME),recursive=True)
        if not files: return None,None
        files.sort(key=os.path.getmtime,reverse=True)
        f=files[0]
        mtime=pd.Timestamp(os.path.getmtime(f),unit='s').tz_localize('UTC').tz_convert('Asia/Taipei')
        return f,mtime
    except Exception: return None,None

@st.cache_data(ttl=20*60, show_spinner=False)
def load_data():
    try:
        path,mtime=find_latest()
        if path is None: return None,None,None
        return parse_file(path),path,mtime
    except Exception: return None,None,None

try:    df, src_path, src_mtime = load_data()
except: df, src_path, src_mtime = None, None, None

# ══════════════════════════════════════════════════════
# HEADER
# ══════════════════════════════════════════════════════
wday_names=["一","二","三","四","五","六","日"]
wday=wday_names[TODAY.weekday()]
next_ref=20-(NOW.minute%20)
data_ts=src_mtime.strftime('%m/%d %H:%M') if src_mtime else "⚠️ 離線"

st.markdown(
    f'<div style="background:linear-gradient(90deg,#0d1f4e 0%,#0f2d6b 40%,#0d1f4e 100%);'
    f'border:1px solid rgba(56,189,248,0.35);border-radius:14px;padding:14px 28px;margin-bottom:18px;'
    f'box-shadow:0 0 30px rgba(14,165,233,0.15);'
    f'display:flex;justify-content:space-between;align-items:center">'
    f'<div>'
    f'<div style="color:#38bdf8;font-size:12px;font-weight:700;letter-spacing:2px">ORing &nbsp;·&nbsp; 生管 PC</div>'
    f'<div style="color:#f0f9ff;font-size:26px;font-weight:900;margin-top:3px;'
    f'text-shadow:0 0 20px rgba(56,189,248,0.6)">📺 &nbsp;工單進度看板</div>'
    f'</div>'
    f'<div style="text-align:center">'
    f'<div style="color:#7dd3fc;font-size:12px;letter-spacing:1px">PRODUCTION SCHEDULING MONITOR</div>'
    f'<div style="color:#94a3b8;font-size:11px;margin-top:4px">'
    f'🕐 {NOW.strftime("%H:%M")} &nbsp;｜&nbsp; 每 20 分鐘自動更新 &nbsp;｜&nbsp; 資料：{data_ts}'
    f'</div></div>'
    f'<div style="text-align:right">'
    f'<div style="color:#f0f9ff;font-size:30px;font-weight:900;text-shadow:0 0 20px rgba(56,189,248,0.5)">'
    f'{TODAY.strftime("%Y / %m / %d")}</div>'
    f'<div style="color:#38bdf8;font-size:16px;font-weight:700;margin-top:2px">（週{wday}）</div>'
    f'</div></div>',
    unsafe_allow_html=True
)

if df is None:
    st.markdown(
        f'<div style="background:rgba(239,68,68,0.1);border:1px solid rgba(239,68,68,0.5);'
        f'border-radius:10px;padding:20px;text-align:center;color:#fca5a5;font-size:16px">'
        f'⚠️ &nbsp; 無法讀取資料，請確認網路磁碟已連線<br>'
        f'<span style="font-size:13px;color:#94a3b8">{BASE_DIR}</span></div>',
        unsafe_allow_html=True
    )
    st.stop()

# ══════════════════════════════════════════════════════
# 計算週統計（今日 + 4 週）
# ══════════════════════════════════════════════════════
_wd=TODAY.weekday()
wk_mon=TODAY-timedelta(days=_wd)

def _expand_ship(src):
    records=[]
    for _,row in src.iterrows():
        label=str(row.get("出貨日_顯示","") or "")
        pairs=re.findall(r'(\d{1,2}/\d{1,2})[^*\n,，]*\*\s*(\d+)',label)
        if len(pairs)>1:
            for ds,qs in pairs:
                d=parse_date_str(ds)
                if d:
                    nr=row.copy(); nr["出貨日"]=d; nr["預計產量"]=int(qs)
                    records.append(nr)
        else: records.append(row)
    return pd.DataFrame(records) if records else src.copy()

exp_df=_expand_ship(df[df["出貨日"].notna()].copy())

# 今日 + 4 週區間
weeks = []
for i in range(5):
    ws = wk_mon + timedelta(weeks=i)
    we = ws + timedelta(days=4)
    sub = exp_df[(exp_df["出貨日"]>=ws)&(exp_df["出貨日"]<=we)].copy()
    tq  = int(sub["預計產量"].dropna().sum())
    rq  = int(sub[sub["料況狀態"]=="已齊料"]["預計產量"].dropna().sum())
    n   = len(sub)
    n_ready  = int((sub["料況狀態"]=="已齊料").sum())
    n_short  = n - n_ready
    wdays_left = count_workdays(TODAY-timedelta(days=1), we)
    label = ("本週" if i==0 else "下週" if i==1 else f"+{i}週")
    weeks.append(dict(
        label=label, start=ws, end=we,
        n=n, tq=tq, rq=rq, lq=tq-rq,
        n_ready=n_ready, n_short=n_short,
        wdays_left=wdays_left, cap=wdays_left*DAILY_CAP,
    ))

# ══════════════════════════════════════════════════════
# SECTION 1：4週出貨工單 KPI 卡片列
# ══════════════════════════════════════════════════════
st.markdown(
    '<div style="color:#38bdf8;font-size:12px;font-weight:700;letter-spacing:2px;'
    'text-transform:uppercase;margin-bottom:10px">📦 出貨工單概況（今日 ~ 4週）</div>',
    unsafe_allow_html=True
)

kpi_cols = st.columns(5)
for i, (col, wk) in enumerate(zip(kpi_cols, weeks)):
    n_ready = wk["n_ready"]; n_short = wk["n_short"]; n = wk["n"]
    tq = wk["tq"]
    pct = int(n_ready/n*100) if n else 0
    # 狀態色
    if n==0:         ac,gc="#475569","rgba(71,85,105,0.2)"
    elif n_short==0: ac,gc="#22d3ee","rgba(34,211,238,0.15)"
    else:            ac,gc="#f87171","rgba(248,113,113,0.15)"
    bar_w_r = pct
    bar_w_s = 100-pct

    col.markdown(
        f'<div style="background:linear-gradient(135deg,rgba(13,28,65,0.9),rgba(8,18,45,0.9));'
        f'border:1px solid {ac};border-radius:12px;padding:16px 14px;'
        f'box-shadow:0 0 18px {gc};text-align:center;height:100%">'
        f'<div style="color:#94a3b8;font-size:11px;letter-spacing:1.5px;margin-bottom:8px">'
        f'{wk["label"]}&nbsp; {wk["start"].strftime("%m/%d")}~{wk["end"].strftime("%m/%d")}</div>'
        # 總筆數
        f'<div style="color:{ac};font-size:44px;font-weight:900;line-height:1;'
        f'text-shadow:0 0 20px {gc}">{n}</div>'
        f'<div style="color:#64748b;font-size:11px;margin-top:2px;margin-bottom:12px">張工單 &nbsp;／&nbsp; {tq:,} pcs</div>'
        # 齊料/缺料
        f'<div style="display:flex;justify-content:center;gap:10px;margin-bottom:10px">'
        f'<div style="text-align:center">'
        f'<div style="color:#4ade80;font-size:24px;font-weight:800">{n_ready}</div>'
        f'<div style="color:#374151;font-size:10px">已齊料</div></div>'
        f'<div style="color:#1e3a5f;font-size:22px;line-height:2">｜</div>'
        f'<div style="text-align:center">'
        f'<div style="color:#f87171;font-size:24px;font-weight:800">{n_short}</div>'
        f'<div style="color:#374151;font-size:10px">缺料</div></div>'
        f'</div>'
        # 進度條
        f'<div style="background:rgba(255,255,255,0.05);border-radius:3px;height:5px;overflow:hidden">'
        f'<div style="display:flex;height:100%">'
        f'<div style="width:{bar_w_r}%;background:#22d3ee;box-shadow:0 0 6px rgba(34,211,238,0.8)"></div>'
        f'<div style="width:{bar_w_s}%;background:rgba(248,113,113,0.5)"></div>'
        f'</div></div></div>',
        unsafe_allow_html=True
    )

st.markdown("<div style='margin-top:20px'></div>", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════
# SECTION 2：本週/下週 大卡片 + 今日來料
# ══════════════════════════════════════════════════════
card_l, card_r, card_mat = st.columns([2, 2, 1])

def _big_card(wk):
    tq=wk["tq"]; rq=wk["rq"]; lq=wk["lq"]
    n=wk["n"]; pct=int(rq/tq*100) if tq else 0
    cap=wk["cap"]; wdays=wk["wdays_left"]
    need_days=round(tq/DAILY_CAP,1) if tq else 0
    if tq==0:      ac,gc,icon,msg="#475569","rgba(71,85,105,0.3)","⬜","無出貨工單"
    elif lq==0:    ac,gc,icon,msg="#22d3ee","rgba(34,211,238,0.25)","✅","全數已齊料，可如期出貨"
    elif cap>=lq:  ac,gc,icon,msg="#fbbf24","rgba(251,191,36,0.25)","⚠️",f"缺料 {lq:,} pcs，產能尚足"
    else:          ac,gc,icon,msg="#f87171","rgba(248,113,113,0.3)","🔴",f"缺料 {lq:,} pcs，產能不足！"
    lm_s=""
    lm=None
    # 不用顯示lm細節在大看板上

    return (
        f'<div style="background:linear-gradient(135deg,rgba(13,28,65,0.95),rgba(8,18,45,0.95));'
        f'border:1px solid {ac};border-radius:16px;padding:20px 22px;'
        f'box-shadow:0 0 28px {gc};height:100%">'
        f'<div style="color:#94a3b8;font-size:11px;letter-spacing:2px;margin-bottom:4px">{wk["label"]}'
        f'&nbsp; {wk["start"].strftime("%m/%d")} ~ {wk["end"].strftime("%m/%d")}</div>'
        f'<div style="color:{ac};font-size:17px;font-weight:800;margin-bottom:14px">{icon} {msg}</div>'
        f'<div style="display:flex;gap:0;margin-bottom:14px">'
        + "".join([
            f'<div style="flex:1;text-align:center;border-right:1px solid rgba(255,255,255,0.07)">'
            f'<div style="font-size:32px;font-weight:900;color:{vc};text-shadow:0 0 16px {gc}">{v}</div>'
            f'<div style="font-size:10px;color:#64748b;margin-top:2px">{lb}</div></div>'
            for v,vc,lb in [
                (str(n), ac, "出貨筆數"),
                (f"{tq:,}", ac, "總量 pcs"),
                (f"{rq:,}", "#4ade80", "已齊料 pcs"),
                (f"{lq:,}", "#f87171", "缺料 pcs"),
                (str(need_days), ac, f"需天數({DAILY_CAP}/天)"),
            ]
        ]) +
        f'</div>'
        f'<div style="font-size:11px;color:#64748b;margin-bottom:5px">'
        f'齊料進度 <b style="color:{ac}">{pct}%</b>'
        f' &nbsp;｜&nbsp; 剩餘產能 <b style="color:#7dd3fc">{cap:,} pcs</b>（{wdays} 工作天）</div>'
        f'<div style="background:rgba(255,255,255,0.06);border-radius:4px;height:7px;overflow:hidden">'
        f'<div style="display:flex;height:100%">'
        f'<div style="width:{pct}%;background:linear-gradient(90deg,#22d3ee,#06b6d4);'
        f'box-shadow:0 0 8px rgba(34,211,238,0.6)"></div>'
        f'<div style="width:{100-pct}%;background:rgba(248,113,113,0.4)"></div>'
        f'</div></div></div>'
    )

with card_l:
    st.markdown(_big_card(weeks[0]), unsafe_allow_html=True)
with card_r:
    st.markdown(_big_card(weeks[1]), unsafe_allow_html=True)

# ── 今日來料概況 ──────────────────────────────────────
with card_mat:
    # 收集今日來料
    today_mat_rows=[]
    for _,row in df.iterrows():
        if row["料況狀態"]=="已齊料": continue
        is_urg=bool(row.get("急件",False))
        for _,arr_d,_ in row["_future"]:
            if arr_d==TODAY: today_mat_rows.append({"急件":is_urg,"狀態":"待進料"})
        for _,arr_d,dl in row["_delayed"]:
            if arr_d==TODAY: today_mat_rows.append({"急件":is_urg,"狀態":"逾期"})

    total_mat = len(today_mat_rows)
    urg_mat   = sum(1 for r in today_mat_rows if r["急件"])
    norm_mat  = total_mat - urg_mat
    ovd_mat   = sum(1 for r in today_mat_rows if r["狀態"]=="逾期")

    st.markdown(
        '<div style="background:linear-gradient(135deg,rgba(13,28,65,0.95),rgba(8,18,45,0.95));'
        'border:1px solid rgba(56,189,248,0.4);border-radius:16px;padding:20px 18px;'
        'box-shadow:0 0 20px rgba(56,189,248,0.12);height:100%;text-align:center">'
        '<div style="color:#38bdf8;font-size:11px;letter-spacing:2px;margin-bottom:12px">'
        f'🚚 今日預計來料（{TODAY.strftime("%m/%d")}）</div>'
        # 總數
        f'<div style="color:#38bdf8;font-size:52px;font-weight:900;line-height:1;'
        f'text-shadow:0 0 24px rgba(56,189,248,0.6)">{total_mat}</div>'
        f'<div style="color:#64748b;font-size:11px;margin-top:4px;margin-bottom:16px">項料號</div>'
        # 急件/不急件
        f'<div style="display:flex;gap:0">'
        f'<div style="flex:1;text-align:center;border-right:1px solid rgba(255,255,255,0.07)">'
        f'<div style="color:#fb923c;font-size:28px;font-weight:900;'
        f'text-shadow:0 0 14px rgba(249,115,22,0.5)">{urg_mat}</div>'
        f'<div style="color:#374151;font-size:10px;margin-top:2px">🚨 急件</div></div>'
        f'<div style="flex:1;text-align:center">'
        f'<div style="color:#4ade80;font-size:28px;font-weight:900;'
        f'text-shadow:0 0 14px rgba(74,222,128,0.4)">{norm_mat}</div>'
        f'<div style="color:#374151;font-size:10px;margin-top:2px">📦 不急件</div></div>'
        f'</div>'
        # 逾期
        + (f'<div style="margin-top:12px;background:rgba(248,113,113,0.1);border:1px solid rgba(248,113,113,0.3);'
           f'border-radius:6px;padding:6px;color:#f87171;font-size:12px;font-weight:700">'
           f'🔴 逾期未到 {ovd_mat} 項</div>' if ovd_mat else
           f'<div style="margin-top:12px;background:rgba(34,211,238,0.08);border:1px solid rgba(34,211,238,0.2);'
           f'border-radius:6px;padding:6px;color:#22d3ee;font-size:12px">'
           f'✅ 無逾期項目</div>') +
        f'</div>',
        unsafe_allow_html=True
    )

st.markdown("<div style='margin-top:20px'></div>", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════
# SECTION 3：4週出貨 Bar Chart（pcs）
# ══════════════════════════════════════════════════════
st.markdown(
    '<div style="color:#38bdf8;font-size:12px;font-weight:700;letter-spacing:2px;'
    'margin-bottom:10px">📊 4週出貨量趨勢（pcs）</div>',
    unsafe_allow_html=True
)

labels  = [f'{w["label"]}<br>{w["start"].strftime("%m/%d")}~{w["end"].strftime("%m/%d")}' for w in weeks]
rq_vals = [w["rq"] for w in weeks]
lq_vals = [w["lq"] for w in weeks]

fig = go.Figure()
fig.add_trace(go.Bar(
    name="已齊料 pcs", x=labels, y=rq_vals,
    marker=dict(color="rgba(34,211,238,0.7)", line=dict(color="#22d3ee", width=1.5)),
    text=[f"{v:,}" for v in rq_vals], textposition="inside",
    textfont=dict(color="white", size=12, family="Arial Black"),
))
fig.add_trace(go.Bar(
    name="缺料 pcs", x=labels, y=lq_vals,
    marker=dict(color="rgba(248,113,113,0.6)", line=dict(color="#f87171", width=1.5)),
    text=[f"{v:,}" if v else "" for v in lq_vals], textposition="inside",
    textfont=dict(color="white", size=12, family="Arial Black"),
))
fig.update_layout(
    barmode="stack",
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(color="#94a3b8", family="Arial"),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
                font=dict(color="#cbd5e1"), bgcolor="rgba(0,0,0,0)"),
    xaxis=dict(showgrid=False, tickfont=dict(color="#64748b", size=11)),
    yaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.05)",
               tickfont=dict(color="#64748b"), zeroline=False),
    margin=dict(l=20, r=20, t=20, b=20),
    height=260,
)
st.plotly_chart(fig, use_container_width=True)

# ══════════════════════════════════════════════════════
# SECTION 4：急件缺料工單（僅數字摘要 + 小清單）
# ══════════════════════════════════════════════════════
_wd=TODAY.weekday()
wk_mon0=TODAY-timedelta(days=_wd); wk_fri0=wk_mon0+timedelta(days=4)
nwk_mon0=wk_mon0+timedelta(days=7); nwk_fri0=nwk_mon0+timedelta(days=4)
both_sub = exp_df[(exp_df["出貨日"]>=wk_mon0)&(exp_df["出貨日"]<=nwk_fri0)].copy()
both_sub = both_sub.drop_duplicates(subset=["工單"])
urgent_lack = both_sub[(both_sub["料況狀態"]!="已齊料")&(both_sub["急件"]==True)]

st.markdown(
    f'<div style="background:linear-gradient(90deg,rgba(127,29,29,0.5),rgba(50,10,10,0.3));'
    f'border:1px solid rgba(239,68,68,0.4);border-radius:10px;padding:10px 18px;margin-bottom:14px;'
    f'box-shadow:0 0 16px rgba(239,68,68,0.1);display:flex;align-items:center;gap:20px">'
    f'<span style="color:#fca5a5;font-size:15px;font-weight:800">'
    f'🚨 &nbsp;兩週內急件缺料</span>'
    f'<span style="color:#f87171;font-size:32px;font-weight:900;'
    f'text-shadow:0 0 16px rgba(239,68,68,0.5)">{len(urgent_lack)}</span>'
    f'<span style="color:#64748b;font-size:13px">張工單（出貨剩 ≤10 工作天且尚未齊料）</span>'
    f'</div>',
    unsafe_allow_html=True
)

if urgent_lack.empty:
    st.markdown(
        '<div style="background:rgba(6,78,59,0.2);border:1px solid rgba(34,211,238,0.3);'
        'border-radius:10px;padding:14px;text-align:center;color:#6ee7b7;font-size:15px;font-weight:700">'
        '✅ &nbsp; 目前兩週內無急件缺料工單</div>',
        unsafe_allow_html=True
    )
else:
    cols_per=4
    rows_list=list(urgent_lack.iterrows())
    for i in range(0, len(rows_list), cols_per):
        chunk=rows_list[i:i+cols_per]
        cols=st.columns(cols_per)
        for j,(_, row) in enumerate(chunk):
            with cols[j]:
                ship_d=row["出貨日"].strftime('%m/%d') if pd.notna(row["出貨日"]) else "未定"
                wdays=row.get("距出貨工作天")
                wday_s=f"{int(wdays)}天" if pd.notna(wdays) else "—"
                qty=int(row["預計產量"]) if pd.notna(row["預計產量"]) else "?"
                st.markdown(
                    f'<div style="background:linear-gradient(135deg,rgba(127,29,29,0.25),rgba(50,10,10,0.3));'
                    f'border:1px solid rgba(239,68,68,0.4);border-top:3px solid #f87171;'
                    f'border-radius:10px;padding:12px 14px;margin-bottom:8px">'
                    f'<div style="color:#fca5a5;font-size:13px;font-weight:800;margin-bottom:3px">{row["工單"]}</div>'
                    f'<div style="color:#64748b;font-size:11px;margin-bottom:8px">{row["成品料號"]} &nbsp;×&nbsp; {qty}</div>'
                    f'<div style="display:flex;gap:6px;flex-wrap:wrap">'
                    f'<span style="background:rgba(239,68,68,0.2);color:#f87171;border:1px solid rgba(239,68,68,0.3);'
                    f'border-radius:4px;padding:1px 8px;font-size:11px;font-weight:700">{row["料況狀態"]}</span>'
                    f'<span style="background:rgba(251,191,36,0.1);color:#fbbf24;'
                    f'border-radius:4px;padding:1px 8px;font-size:11px">出貨 {ship_d}（剩{wday_s}）</span>'
                    f'</div></div>',
                    unsafe_allow_html=True
                )

# 頁尾
st.markdown(
    f'<div style="text-align:center;color:#1e3a5f;font-size:11px;margin-top:24px;letter-spacing:1px">'
    f'DATA · {src_path.replace(r"\\192.168.2.34\MO_Storage","NAS") if src_path else "—"}'
    f' &nbsp;｜&nbsp; NEXT REFRESH · {next_ref} min</div>',
    unsafe_allow_html=True
)
