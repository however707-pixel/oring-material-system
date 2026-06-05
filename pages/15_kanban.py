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
/* ══ 工單看板：科技冰川白 ══ */
.stApp { background:#F4F8FB !important; }
[data-testid="stHeader"]  { background:transparent !important; }
[data-testid="stSidebar"] { background:#ffffff !important; }
.block-container { padding:0.5rem 1.2rem 2rem !important; max-width:100% !important; }
#MainMenu, footer, [data-testid="stToolbar"] { visibility:hidden; }
::-webkit-scrollbar { width:6px; }
::-webkit-scrollbar-track { background:#B9DDF5; }
::-webkit-scrollbar-thumb { background:#2A9DF4; border-radius:4px; }
.js-plotly-plot .plotly .bg { fill:transparent !important; }
html, body, [class*="css"] {
    font-size:18px !important;
    font-family:"Microsoft JhengHei","微軟正黑體",sans-serif !important;
}
/* 只限制段落與標籤，不蓋掉 div 的 inline 顏色 */
p { color:#123A5C !important; }
label { color:#607080 !important; }
/* 一般藍色按鈕 */
div[data-testid="stButton"] > button[kind="primary"] {
    width:100%; background:#2A9DF4 !important;
    border:none !important; color:#ffffff !important;
    font-size:15px !important; font-weight:700 !important;
    border-radius:8px !important; padding:7px 16px !important;
    margin-top:8px !important;
    box-shadow:0 2px 10px rgba(42,157,244,0.30) !important;
}
div[data-testid="stButton"] > button[kind="primary"]:hover { background:#1a8ad4 !important; }
div[data-testid="stButton"] > button[kind="secondary"] {
    background:#ffffff !important; color:#2A9DF4 !important;
    border:1px solid #B9DDF5 !important;
    border-radius:8px !important; font-size:15px !important;
    padding:7px 16px !important; margin-top:8px !important;
    box-shadow:none !important; width:100% !important;
}
div[data-testid="stButton"] > button[kind="secondary"]:hover {
    background:#F4F8FB !important;
}
/* 三週大卡片：按鈕是欄位第一個子元素，用:first-child定位到右上角 */
[data-testid="stHorizontalBlock"] > [data-testid="column"] {
    position:relative !important;
}
[data-testid="stHorizontalBlock"] > [data-testid="column"] > div:first-child {
    position:absolute !important;
    top:12px !important; right:12px !important;
    width:auto !important; z-index:20 !important;
    margin:0 !important; padding:0 !important;
}
[data-testid="stHorizontalBlock"] > [data-testid="column"] > div:first-child button {
    all:unset !important;
    cursor:pointer !important; font-size:14px !important;
    color:#94a3b8 !important; padding:3px 9px !important;
    background:#ffffff !important; border:1px solid #e2e8f0 !important;
    border-radius:5px !important; line-height:1.3 !important;
}
[data-testid="stHorizontalBlock"] > [data-testid="column"] > div:first-child button:hover {
    color:#2A9DF4 !important; border-color:#B9DDF5 !important;
}
/* ▼ 按鈕在卡片標題右側：secondary 小白按鈕 */
[data-testid="column"]:has(.wk-col-marker) [data-testid="stButton"] > button {
    all:unset !important; cursor:pointer !important;
    font-size:14px !important; color:#94a3b8 !important;
    padding:3px 8px !important; background:#ffffff !important;
    border:1px solid #e2e8f0 !important; border-radius:5px !important;
    line-height:1.3 !important; white-space:nowrap !important;
}
[data-testid="column"]:has(.wk-col-marker) [data-testid="stButton"] > button:hover {
    color:#2A9DF4 !important; border-color:#B9DDF5 !important;
}
.wk-arrow-btn { display:none !important; }
</style>
""", unsafe_allow_html=True)

render_sidebar()

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
        else: mat_status=f'齊料 {rate:.0%}'
        if ship_date:
            wdays_to_ship=count_workdays(TODAY-timedelta(days=1),ship_date)
            is_urgent=(wdays_to_ship<=10)
        else: wdays_to_ship=None; is_urgent=False
        rows.append({'工單':wo,'成品料號':product,'預計產量':qty,
            '出貨日':ship_date,'出貨日_顯示':ship_label,
            '料況狀態':mat_status,'重點提示':hint,'整體料齊率':rate,
            '預計齊料日': qi_date,
            '距出貨工作天':wdays_to_ship,'急件':is_urgent,
            '_delayed':delayed,'_iqc':iqc,'_future':future})
    return pd.DataFrame(rows)

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
    f'<div style="background:linear-gradient(90deg,#0f2356 0%,#1e3a8a 50%,#0f2356 100%);'
    f'border:none;border-radius:14px;padding:18px 28px;margin-bottom:20px;'
    f'box-shadow:0 4px 20px rgba(15,35,86,0.25);'
    f'display:grid;grid-template-columns:1fr auto 1fr;align-items:center;gap:16px">'

    f'<div style="text-align:left">'
    f'<div style="color:#B9DDF5;font-size:15px;font-weight:600;letter-spacing:1px;margin-bottom:4px">'
    f'ORing &nbsp;·&nbsp; 生管 PC</div>'
    f'<div style="color:#e0eefa;font-size:14px">'
    f'🕐 {NOW.strftime("%H:%M")} &nbsp;｜&nbsp; 每 20 分鐘自動更新</div>'
    f'<div style="color:#b9ddf5;font-size:13px;margin-top:2px">資料：{data_ts}</div>'
    f'</div>'

    f'<div style="text-align:center">'
    f'<div style="color:#ffffff;font-size:42px;font-weight:900;line-height:1.15;letter-spacing:1px">'
    f'生產出貨即時監控</div>'
    f'<div style="color:#2A9DF4;font-size:14px;font-weight:500;letter-spacing:4px;margin-top:6px">'
    f'PRODUCTION &amp; SHIPPING LIVE MONITOR</div>'
    f'</div>'

    f'<div style="text-align:right">'
    f'<div style="color:#ffffff;font-size:32px;font-weight:900">{TODAY.strftime("%Y / %m / %d")}</div>'
    f'<div style="color:#2A9DF4;font-size:18px;font-weight:700;margin-top:2px">（週{wday}）</div>'
    f'</div>'

    f'</div>',
    unsafe_allow_html=True
)

if df is None:
    st.markdown(
        f'<div style="background:rgba(239,68,68,0.1);border:1px solid rgba(239,68,68,0.5);'
        f'border-radius:10px;padding:20px;text-align:center;color:#fca5a5;font-size:18px">'
        f'⚠️ &nbsp; 無法讀取資料，請確認網路磁碟已連線<br>'
        f'<span style="font-size:14px;color:#607080">{BASE_DIR}</span></div>',
        unsafe_allow_html=True
    )
    st.stop()

# ══════════════════════════════════════════════════════
# 計算週統計
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

weeks = []
for i in range(5):
    ws = wk_mon + timedelta(weeks=i)
    we = ws + timedelta(days=4)
    sub = exp_df[(exp_df["出貨日"]>=ws)&(exp_df["出貨日"]<=we)].copy()
    # 找缺料工單（回到原始 df 避免展開重複）
    sub_orig = df[df["出貨日"].notna()].copy()
    sub_orig = sub_orig[(sub_orig["出貨日"]>=ws)&(sub_orig["出貨日"]<=we)]
    tq  = int(sub["預計產量"].dropna().sum())
    rq  = int(sub[sub["料況狀態"]=="已齊料"]["預計產量"].dropna().sum())
    n   = len(sub_orig.drop_duplicates("工單"))
    n_ready = int((sub_orig.drop_duplicates("工單")["料況狀態"]=="已齊料").sum())
    n_short = n - n_ready
    wdays_left = count_workdays(TODAY-timedelta(days=1), we)
    label = f"W{ws.isocalendar()[1]}"
    short_rows = sub_orig[sub_orig["料況狀態"]!="已齊料"].drop_duplicates("工單")
    weeks.append(dict(
        idx=i, label=label, start=ws, end=we,
        n=n, tq=tq, rq=rq, lq=tq-rq,
        n_ready=n_ready, n_short=n_short,
        wdays_left=wdays_left, cap=wdays_left*DAILY_CAP,
        short_rows=short_rows,
    ))

# ══════════════════════════════════════════════════════
# SECTION 1：5週 KPI 卡片 + 點擊明細
# ══════════════════════════════════════════════════════
st.markdown(
    '<div style="color:#123A5C;font-size:16px;font-weight:800;letter-spacing:0.3px;'
    'margin-bottom:12px">📦 出貨工單概況（今日 ~ +4週）</div>',
    unsafe_allow_html=True
)

if "sel_week" not in st.session_state:
    st.session_state["sel_week"] = None

kpi_cols = st.columns(5)
for i, (col, wk) in enumerate(zip(kpi_cols, weeks)):
    n_ready=wk["n_ready"]; n_short=wk["n_short"]; n=wk["n"]; tq=wk["tq"]
    pct=int(n_ready/n*100) if n else 0
    if n==0:         ac,bc_="##94a3b8","#e2e8f0"
    elif n_short==0: ac,bc_="#16A085","#b2dfdb"
    else:            ac,bc_="#E74C5B","#fecdd3"
    bar_r=pct; bar_s=100-pct
    is_sel = (st.session_state["sel_week"]==i)
    sel_ring = f"outline:2px solid {ac};outline-offset:2px;" if is_sel else ""

    with col:
        st.markdown(
            f'<div style="background:#ffffff;'
            f'border:1px solid {bc_};border-top:3px solid {ac};'
            f'border-radius:12px;padding:18px 14px;{sel_ring}'
            f'box-shadow:0 2px 12px rgba(18,58,92,0.08);text-align:center">'
            f'<div style="color:#607080;font-size:15px;letter-spacing:0.5px;margin-bottom:8px">'
            f'{wk["label"]} &nbsp; {wk["start"].strftime("%m/%d")}~{wk["end"].strftime("%m/%d")}</div>'
            f'<div style="color:#123A5C;font-size:68px;font-weight:900;line-height:1">{n}</div>'
            f'<div style="color:#607080;font-size:15px;margin-top:4px;margin-bottom:14px">'
            f'張工單 &nbsp;／&nbsp; {tq:,} pcs</div>'
            f'<div style="display:flex;justify-content:center;gap:14px;margin-bottom:12px">'
            f'<div><div style="color:#16A085;font-size:42px;font-weight:900">{n_ready}</div>'
            f'<div style="color:#607080;font-size:14px">已齊料</div></div>'
            f'<div style="color:#B9DDF5;font-size:26px;line-height:2">｜</div>'
            f'<div><div style="color:#E74C5B;font-size:42px;font-weight:900">{n_short}</div>'
            f'<div style="color:#607080;font-size:14px">缺料</div></div>'
            f'</div>'
            f'<div style="background:#EEF2F7;border-radius:3px;height:5px;overflow:hidden">'
            f'<div style="display:flex;height:100%">'
            f'<div style="width:{bar_r}%;background:linear-gradient(90deg,#16A085,#1abc9c)"></div>'
            f'<div style="width:{bar_s}%;background:#fecdd3"></div>'
            f'</div></div></div>',
            unsafe_allow_html=True
        )
        # 所有週都顯示按鈕（不只缺料）
        if n > 0:
            _total = weeks[i]["n"]
            if is_sel:
                btn_label = "▲ 收起明細"
            elif n_short > 0:
                btn_label = f"📋 查看 {_total} 張工單（含 {n_short} 缺料）"
            else:
                btn_label = f"📋 查看 {_total} 張工單明細"
            if st.button(btn_label, key=f"wk_btn_{i}"):
                st.session_state["sel_week"] = None if is_sel else i
                st.rerun()

# ── 工單明細展開區（點擊KPI方塊後展開，顯示該週全部工單 + 到料日）────
sel = st.session_state.get("sel_week")
if sel is not None:
    wk = weeks[sel]
    _ws = wk["start"]; _we = wk["end"]
    # 取該週所有出貨工單（不限缺料）
    all_rows = df[
        df["出貨日"].notna() &
        (df["出貨日"] >= _ws) &
        (df["出貨日"] <= _we)
    ].drop_duplicates("工單").sort_values("出貨日").copy()

    st.markdown(
        f'<div style="background:#f8faff;'
        f'border:1px solid #B9DDF5;border-left:4px solid #2A9DF4;'
        f'border-radius:12px;padding:14px 18px;margin:10px 0 6px;'
        f'box-shadow:0 2px 10px rgba(18,58,92,0.08)">'
        f'<div style="color:#123A5C;font-size:16px;font-weight:800;margin-bottom:0">'
        f'📋 &nbsp;{wk["label"]}（{_ws.strftime("%m/%d")}~{_we.strftime("%m/%d")}）'
        f'&nbsp; 工單明細 &nbsp;— 共 {len(all_rows)} 張</div>'
        f'</div>',
        unsafe_allow_html=True
    )

    if all_rows.empty:
        st.info("該週無出貨工單")
    else:
        _base_cols = ["工單","成品料號","預計產量","出貨日_顯示","料況狀態","重點提示"]
        if "預計齊料日" in all_rows.columns:
            disp = all_rows[_base_cols[:5] + ["預計齊料日"] + [_base_cols[5]]].copy()
            disp.columns = ["工單","成品料號","預計產量","出貨日","料況狀態","到料日","重點提示"]
            disp["到料日"] = disp["到料日"].apply(
                lambda v: v.strftime('%m/%d') if pd.notna(v) and hasattr(v,'strftime') else "—"
            )
        else:
            disp = all_rows[_base_cols].copy()
            disp.columns = ["工單","成品料號","預計產量","出貨日","料況狀態","重點提示"]
            disp.insert(5, "到料日", "—")
        def _sr(r):
            if r["料況狀態"]=="已齊料":    return ["background:#f0fdf9;color:#15803d"]*len(r)
            elif r["料況狀態"]=="完全缺料": return ["background:#fff1f2;color:#be123c"]*len(r)
            else:                           return ["background:#fffbeb;color:#b45309"]*len(r)
        st.dataframe(disp.style.apply(_sr,axis=1),
                     use_container_width=True, hide_index=True,
                     height=min(500, 50+len(disp)*38))

    for _, row in all_rows[all_rows["料況狀態"]!="已齊料"].sort_values("出貨日").iterrows():
        ship_d = row["出貨日"].strftime('%m/%d') if pd.notna(row["出貨日"]) else "未定"
        qty    = int(row["預計產量"]) if pd.notna(row["預計產量"]) else "?"
        hint   = row.get("重點提示","") or ""
        wdays  = row.get("距出貨工作天")
        wday_s = f"剩 {int(wdays)} 工作天" if pd.notna(wdays) else ""
        is_urg = bool(row.get("急件", False))
        urg_tag = "🚨" if is_urg else "📦"

        # 進料明細
        delayed = row.get("_delayed", [])
        iqc     = row.get("_iqc", [])
        future  = row.get("_future", [])

        mat_lines = []
        for mat, arr_d, dl in sorted(delayed, key=lambda x: x[1]):
            mat_lines.append(f'<span style="color:#E74C5B;font-weight:600">● {mat} &nbsp; 逾期 {dl} 天（承諾 {arr_d.strftime("%m/%d")}）</span>')
        for mat, arr_d in iqc:
            d_s = arr_d.strftime('%m/%d') if arr_d else "未知"
            mat_lines.append(f'<span style="color:#d97706;font-weight:600">● {mat} &nbsp; IQC 驗收中（{d_s}）</span>')
        for mat, arr_d, dt in sorted(future, key=lambda x: x[1]):
            mat_lines.append(f'<span style="color:#2A9DF4;font-weight:600">● {mat} &nbsp; 預計 {arr_d.strftime("%m/%d")} 到料（距今 +{dt} 天）</span>')
        mat_html = "<br>".join(mat_lines) if mat_lines else f'<span style="color:#607080">— 無進料明細資訊 —</span>'

        urg_border = "#E74C5B" if is_urg else "#fecdd3"
        urg_bg     = "#fff8f8" if is_urg else "#ffffff"
        st.markdown(
            f'<div style="background:{urg_bg};border:1px solid {urg_border};'
            f'border-left:4px solid #E74C5B;border-radius:8px;padding:12px 16px;margin-bottom:10px;'
            f'box-shadow:0 1px 6px rgba(231,76,91,0.08)">'
            f'<div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px">'
            f'<div>'
            f'<span style="color:#123A5C;font-size:17px;font-weight:800">{urg_tag} {row["工單"]}</span>'
            f'<span style="color:#607080;font-size:15px;margin-left:10px">{row["成品料號"]} × {qty}</span>'
            f'</div>'
            f'<div style="text-align:right">'
            f'<span style="background:#fff1f2;color:#E74C5B;border:1px solid #fecdd3;'
            f'border-radius:4px;padding:2px 10px;font-size:14px;font-weight:700">{row["料況狀態"]}</span>'
            f'<span style="color:#d97706;font-size:14px;margin-left:8px">出貨 {ship_d} &nbsp;{wday_s}</span>'
            f'</div></div>'
            + (f'<div style="color:#607080;font-size:13px;margin-bottom:8px">💬 {hint}</div>' if hint else '')
            + f'<div style="border-top:1px solid #EEF2F7;padding-top:8px;'
            f'font-size:14px;line-height:2">{mat_html}</div>'
            f'</div>',
            unsafe_allow_html=True
        )

    st.markdown('</div>', unsafe_allow_html=True)

st.markdown("<div style='margin-top:20px'></div>", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════
# SECTION 3：4週出貨量趨勢圖
# ══════════════════════════════════════════════════════
st.markdown(
    '<div style="color:#123A5C;font-size:18px;font-weight:800;letter-spacing:0.3px;'
    'margin-bottom:10px">📊 4週出貨量趨勢（pcs）</div>',
    unsafe_allow_html=True
)
labels  = [f'{w["label"]}  {w["start"].strftime("%m/%d")}~{w["end"].strftime("%m/%d")}' for w in weeks]
rq_vals = [w["rq"] for w in weeks]
lq_vals = [w["lq"] for w in weeks]

fig = go.Figure()
fig.add_trace(go.Bar(
    name="已齊料 pcs", x=labels, y=rq_vals,
    marker=dict(color="#16A085", opacity=0.85,
                line=dict(color="#0e7a62", width=1)),
))
fig.add_trace(go.Bar(
    name="缺料 pcs", x=labels, y=lq_vals,
    marker=dict(color="#E74C5B", opacity=0.80,
                line=dict(color="#c0303e", width=1)),
))

# 頂部標籤（每個長條上方）
annotations = []
for i, (rq, lq) in enumerate(zip(rq_vals, lq_vals)):
    total = rq + lq
    if total > 0:
        annotations.append(dict(
            x=labels[i], y=total,
            text=f"<b>共 {total:,}</b><br><span style='font-size:13px'>齊 {rq:,} ｜ 缺 {lq:,}</span>",
            xanchor="center", yanchor="bottom",
            showarrow=False,
            font=dict(size=15, color="#123A5C", family="Microsoft JhengHei"),
            bgcolor="rgba(244,248,251,0.9)",
            bordercolor="#B9DDF5", borderwidth=1, borderpad=5,
        ))

fig.update_layout(
    barmode="stack",
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(color="#607080", family="Microsoft JhengHei", size=15),
    annotations=annotations,
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
                font=dict(color="#607080", size=15), bgcolor="rgba(244,248,251,0.8)"),
    xaxis=dict(showgrid=False, tickfont=dict(color="#607080", size=15)),
    yaxis=dict(showgrid=True, gridcolor="#EEF2F7",
               tickfont=dict(color="#607080", size=14), zeroline=False),
    margin=dict(l=20, r=20, t=80, b=20), height=420,
)
st.plotly_chart(fig, use_container_width=True,
                config=dict(staticPlot=True))   # ← 固定，不能拖動

# ══════════════════════════════════════════════════════
# SECTION 5：本月出貨排程月曆（含預計開工日）
# ══════════════════════════════════════════════════════
import math, calendar as _cal

st.markdown("<div style='margin-top:28px'></div>", unsafe_allow_html=True)
st.markdown(
    f'<div style="color:#123A5C;font-size:18px;font-weight:800;margin-bottom:14px">'
    f'📅 本月出貨排程月曆（{TODAY.year}年 {TODAY.month}月）</div>',
    unsafe_allow_html=True
)

IQC_WH_DAYS = 1.5   # IQC + 倉庫最少 1.5 工作日

def workday_subtract(d, n_days):
    """從 d 往前推 n_days 個工作天（含小數，取 ceil）"""
    nd = math.ceil(n_days)
    cur = d
    for _ in range(nd):
        cur -= timedelta(days=1)
        while cur.weekday() >= 5 or cur in TAIWAN_HOLIDAYS:
            cur -= timedelta(days=1)
    return cur

# 篩選本月有出貨日的工單（用 exp_df 避免多出貨日加總，不 drop_duplicates）
def _is_this_month(v):
    try: return pd.notna(v) and v.year == TODAY.year and v.month == TODAY.month
    except: return False

_this_month = exp_df[
    exp_df["出貨日"].apply(_is_this_month)
].copy()   # 不 drop_duplicates：同工單不同出貨日各自計算

# 計算製造天數 = ceil(預計產量 / 日產能)
def _mfg_days(qty):
    try:
        q = float(qty)
        return max(1, math.ceil(q / DAILY_CAP))
    except Exception:
        return 1

SPECIAL_CAP = {"9084": 150}   # 品名含特定字串時的日產能

def _mfg_days_by_pno(row):
    qty = row.get("預計產量", 0)
    pno = str(row.get("成品料號", ""))
    # 特殊品項日產能
    cap = DAILY_CAP
    for keyword, special_cap in SPECIAL_CAP.items():
        if keyword in pno:
            cap = special_cap
            break
    try:
        return max(1, math.ceil(float(qty) / cap))
    except Exception:
        return 1

_this_month["製造天數"] = _this_month.apply(_mfg_days_by_pno, axis=1)

def _to_date(v):
    if hasattr(v, 'date'): return v.date()
    return v

def workday_add(d, n):
    """從 d 往後推 n 個工作天"""
    cur = d
    count = 0
    while count < n:
        cur += timedelta(days=1)
        if cur.weekday() < 5 and cur not in TAIWAN_HOLIDAYS:
            count += 1
    return cur

def _calc_start(r):
    ship  = _to_date(r["出貨日"])
    mfg   = r["製造天數"]
    # 最晚必須開工（倒推）
    deadline_start = workday_subtract(ship, mfg + IQC_WH_DAYS)
    # 齊料日 + 1 工作天（最早可開工）
    qi = r.get("預計齊料日", None) if "預計齊料日" in r.index else None
    if pd.notna(qi) and qi is not None:
        qi_d = _to_date(qi)
        earliest_start = workday_add(qi_d, 1)
    else:
        earliest_start = deadline_start
    # 最終開工日 = 最早可開工（不超過最晚必須開工就用最早，否則用最晚並標警示）
    return earliest_start, deadline_start

_this_month[["預計開工日","最晚開工日"]] = _this_month.apply(
    lambda r: pd.Series(_calc_start(r)), axis=1
)
# 若 預計開工日 > 最晚開工日 → 趕不上出貨（警示）
_this_month["趕不上"] = _this_month["預計開工日"] > _this_month["最晚開工日"]

if _this_month.empty:
    st.info("本月無出貨工單")
else:
    _year, _month = TODAY.year, TODAY.month
    _first = date(_year, _month, 1)
    _last  = date(_year, _month, _cal.monthrange(_year, _month)[1])

    # 分別收集開工事件 & 出貨事件
    _ev_start = {}   # 開工月曆
    _ev_ship  = {}   # 出貨月曆

    for _, r in _this_month.iterrows():
        ship_d  = _to_date(r["出貨日"])
        start_d = r["預計開工日"]
        late    = bool(r.get("趕不上", False))
        pno     = str(r.get("成品料號","")).strip()
        qty     = int(r["預計產量"]) if pd.notna(r["預計產量"]) else 0
        mfg     = int(r["製造天數"])
        finish_d = workday_add(start_d, mfg)

        # 出貨月曆
        if ship_d.month == _month:
            _ev_ship.setdefault(ship_d, []).append(
                f'<div style="background:#fff3cd;border-left:3px solid #d97706;'
                f'border-radius:3px;padding:4px 6px;margin-bottom:4px;line-height:1.5">'
                f'<span style="color:#333;font-size:15px;font-weight:600">{pno or "—"}</span><br>'
                f'<span style="color:#888;font-size:14px">{qty:,} pcs</span></div>'
            )
        # 開工月曆
        if start_d.month == _month:
            if late:
                _bg, _bc = "#fdecea","#E74C5B"
                warn = "⚠️ 趕不上出貨"
            else:
                _bg, _bc = "#e8f4fd","#2A9DF4"
                warn = ""
            _ev_start.setdefault(start_d, []).append(
                f'<div style="background:{_bg};border-left:3px solid {_bc};'
                f'border-radius:3px;padding:4px 6px;margin-bottom:4px;line-height:1.6">'
                f'<span style="color:#333;font-size:15px;font-weight:600">{pno or "—"}</span><br>'
                f'<span style="color:#888;font-size:14px">{qty:,} pcs｜{mfg}天</span><br>'
                f'<span style="color:{_bc};font-size:13px">完工：{finish_d.strftime("%m/%d")}'
                f'{" "+warn if warn else ""}</span></div>'
            )

    # ── HTML 月曆產生函式 ─────────────────────────────────────
    day_names = ["一","二","三","四","五","六","日"]
    th_style = ('style="background:#EEF2F7;color:#607080;font-size:15px;font-weight:700;'
                'text-align:center;padding:10px 4px;border:1px solid #dde8f3"')
    html = (f'<table style="width:100%;border-collapse:collapse;'
            f'font-family:Microsoft JhengHei;table-layout:fixed">'
            f'<tr>' + "".join(f"<th {th_style}>{d}</th>" for d in day_names) + "</tr>")

    def _build_cal(events_dict):
        """依 events_dict 建立月曆 HTML"""
        h = (f'<table style="width:100%;border-collapse:collapse;'
             f'font-family:Microsoft JhengHei;table-layout:fixed">'
             f'<tr>' + "".join(f"<th {th_style}>{d}</th>" for d in day_names) + "</tr>")
        d = _first - timedelta(days=_first.weekday())
        while d <= _last:
            h += "<tr>"
            for di in range(7):
                day = d + timedelta(days=di)
                in_m = (day.month == _month)
                is_t = (day == TODAY)
                is_w = (day.weekday() >= 5)
                cbg  = "#f8f8f8" if not in_m else ("#dbeafe" if is_t else ("#fff7ed" if is_w else "#ffffff"))
                nc   = "#cccccc" if not in_m else ("#c0392b" if is_w else ("#1d4ed8" if is_t else "#334155"))
                evts = events_dict.get(day, []) if in_m else []
                h += (f'<td style="background:{cbg};border:1px solid #e2e8f0;'
                      f'vertical-align:top;padding:8px 6px;min-height:120px">'
                      f'<div style="font-size:16px;font-weight:800;color:{nc};margin-bottom:6px">'
                      f'{day.day if in_m else ""}</div>' + "".join(evts) + '</td>')
            h += "</tr>"
            d += timedelta(weeks=1)
        return h + "</table>"

    tab_start, tab_ship = st.tabs(["▶ 開工排程", "🚢 出貨排程"])
    with tab_start:
        st.markdown(_build_cal(_ev_start), unsafe_allow_html=True)
        st.markdown(
            f'<div style="font-size:13px;color:#607080;margin-top:8px">'
            f'藍色 = 正常開工｜紅色 = 齊料太晚趕不上出貨<br>'
            f'開工日 = 齊料日+1工作天，完工日 = 開工日+製造天數（{DAILY_CAP}pcs/天，9084品項150pcs/天）'
            f'</div>', unsafe_allow_html=True)
    with tab_ship:
        st.markdown(_build_cal(_ev_ship), unsafe_allow_html=True)
        st.markdown(
            f'<div style="font-size:13px;color:#607080;margin-top:8px">'
            f'出貨日｜IQC+倉庫緩衝 = {IQC_WH_DAYS} 工作天'
            f'</div>',
        unsafe_allow_html=True
    )

st.markdown(
    f'<div style="text-align:center;color:#1e3a5f;font-size:12px;margin-top:24px;letter-spacing:1px">'
    f'DATA · {src_path.replace(r"\\192.168.2.34\MO_Storage","NAS") if src_path else "—"}'
    f' &nbsp;｜&nbsp; NEXT REFRESH · {next_ref} min</div>',
    unsafe_allow_html=True
)
