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
    # ── 2026 台灣國定假日 ──────────────────────────────────
    date(2026, 1, 1),   # 元旦
    date(2026, 1, 2),   # 彈性放假
    # 春節
    date(2026, 2, 16),  # 除夕（彈性放假）
    date(2026, 2, 17),  # 春節初一
    date(2026, 2, 18),  # 春節初二
    date(2026, 2, 19),  # 春節初三
    date(2026, 2, 20),  # 春節初四
    # 228（2/28週六，3/2週一補假）
    date(2026, 3, 2),
    # 兒童節（4/4週六，4/3週五補假）
    date(2026, 4, 3),
    # 清明節（4/5週日，4/6週一補假）
    date(2026, 4, 6),
    # 勞動節
    date(2026, 5, 1),
    # 端午節（農曆5/5 ≈ 6/19 週五）
    date(2026, 6, 19),
    # 中秋節（農曆8/15 ≈ 9/25 週五）
    date(2026, 9, 25),
    # 國慶日（10/10週六，10/9週五補假）
    date(2026, 10, 9),
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

    # 出貨月曆事件
    _ev_ship   = {}
    # 開工月曆：每天顯示「當天正在生產的所有工單」（跨越整個生產期）
    _ev_start  = {}   # date → list of html
    _daily_pcs = {}   # date → 當天總pcs

    def _daily_cap_for(pno_str):
        for k, c in SPECIAL_CAP.items():
            if k in pno_str: return c
        return DAILY_CAP

    def _next_workday(d):
        d2 = d + timedelta(days=1)
        while d2.weekday() >= 5 or d2 in TAIWAN_HOLIDAYS:
            d2 += timedelta(days=1)
        return d2

    for _, r in _this_month.iterrows():
        ship_d  = _to_date(r["出貨日"])
        start_d = r["預計開工日"]
        late    = bool(r.get("趕不上", False))
        pno     = str(r.get("成品料號","")).strip()
        qty     = int(r["預計產量"]) if pd.notna(r["預計產量"]) else 0
        mfg     = int(r["製造天數"])
        finish_d = workday_add(start_d, mfg)
        daily_rate = qty / mfg if mfg > 0 else 0

        # 出貨月曆
        if ship_d.month == _month:
            _ev_ship.setdefault(ship_d, []).append(
                f'<div style="background:#fff3cd;border-left:3px solid #d97706;'
                f'border-radius:3px;padding:4px 6px;margin-bottom:4px;line-height:1.5">'
                f'<span style="color:#333;font-size:15px;font-weight:600">{pno or "—"}</span><br>'
                f'<span style="color:#888;font-size:14px">{qty:,} pcs</span></div>'
            )

        # 開工月曆：遍歷每個生產工作天
        _bc  = "#E74C5B" if late else "#2A9DF4"
        _bg  = "#fdecea" if late else "#e8f4fd"
        warn = " ⚠️趕不上" if late else ""
        short_pno = (pno[-18:] if len(pno)>18 else pno) or "—"
        _d_ptr = start_d
        for _di in range(mfg):
            _daily_pcs[_d_ptr] = _daily_pcs.get(_d_ptr, 0) + daily_rate
            if _d_ptr.month == _month:
                is_first = (_di == 0)
                is_last  = (_di == mfg - 1)
                if is_first and is_last:
                    # 只有一天：完整顯示
                    _ev_start.setdefault(_d_ptr, []).append(
                        f'<div style="background:{_bg};border-left:4px solid {_bc};'
                        f'border-radius:4px;padding:4px 7px;margin-bottom:3px;line-height:1.5">'
                        f'<b style="color:{_bc};font-size:13px">▶ 開工 ✓完工{warn}</b><br>'
                        f'<span style="color:#333;font-size:14px;font-weight:700">{short_pno}</span><br>'
                        f'<span style="color:#888;font-size:13px">{int(daily_rate):,} pcs/天</span></div>'
                    )
                elif is_first:
                    # 第一天：完整資訊
                    _ev_start.setdefault(_d_ptr, []).append(
                        f'<div style="background:{_bg};border-left:4px solid {_bc};'
                        f'border-radius:4px 4px 0 0;padding:4px 7px;margin-bottom:0;line-height:1.5">'
                        f'<b style="color:{_bc};font-size:13px">▶ 開工{warn}  → 共{mfg}天</b><br>'
                        f'<span style="color:#333;font-size:14px;font-weight:700">{short_pno}</span><br>'
                        f'<span style="color:#888;font-size:13px">{int(daily_rate):,} pcs/天｜共{qty:,}pcs</span></div>'
                    )
                elif is_last:
                    # 最後一天：完工標記
                    _ev_start.setdefault(_d_ptr, []).append(
                        f'<div style="background:{_bg};border-left:4px solid {_bc};'
                        f'border-radius:0 0 4px 4px;padding:3px 7px;margin-bottom:3px;line-height:1.4">'
                        f'<span style="color:#888;font-size:12px">↳ {short_pno}</span>'
                        f'<b style="color:{_bc};font-size:12px;float:right">✓完工</b></div>'
                    )
                else:
                    # 中間天：細條繼續
                    _ev_start.setdefault(_d_ptr, []).append(
                        f'<div style="background:{_bg};border-left:4px solid {_bc};'
                        f'padding:2px 7px;margin-bottom:0;line-height:1.3">'
                        f'<span style="color:#888;font-size:12px">→ {short_pno} '
                        f'{int(daily_rate):,}pcs</span></div>'
                    )
            _d_ptr = _next_workday(_d_ptr)

    # ── HTML 月曆產生函式 ─────────────────────────────────────
    day_names = ["一","二","三","四","五","六","日"]
    th_style = ('style="background:#EEF2F7;color:#607080;font-size:15px;font-weight:700;'
                'text-align:center;padding:10px 4px;border:1px solid #dde8f3"')
    html = (f'<table style="width:100%;border-collapse:collapse;'
            f'font-family:Microsoft JhengHei;table-layout:fixed">'
            f'<tr>' + "".join(f"<th {th_style}>{d}</th>" for d in day_names) + "</tr>")

    # ── 出貨月曆（格子式）────────────────────────────────────
    def _build_ship_cal(events_dict):
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
                      f'vertical-align:top;padding:8px 6px;min-height:100px">'
                      f'<div style="font-size:16px;font-weight:800;color:{nc};margin-bottom:6px">'
                      f'{day.day if in_m else ""}</div>' + "".join(evts) + '</td>')
            h += "</tr>"
            d += timedelta(weeks=1)
        return h + "</table>"

    # ── 稼動率色條 ─────────────────────────────────────────
    def _util_bar(day):
        pcs = _daily_pcs.get(day, 0)
        if pcs == 0: return ""
        pct_real = pcs / DAILY_CAP * 100
        bar_w    = min(100, pct_real)
        if pct_real >= 120:  bar_c, lbl = "#E74C5B", f"🔴 {int(pct_real)}%（超載）"
        elif pct_real >= 100: bar_c, lbl = "#f97316", f"🟠 {int(pct_real)}%（滿載）"
        elif pct_real >= 80:  bar_c, lbl = "#d97706", f"🟡 {int(pct_real)}%"
        else:                 bar_c, lbl = "#16A085", f"🟢 {int(pct_real)}%"
        return (f'<div style="background:#eee;border-radius:3px;height:7px;'
                f'margin-bottom:3px;overflow:hidden">'
                f'<div style="width:{bar_w:.0f}%;height:100%;background:{bar_c}"></div></div>'
                f'<div style="font-size:11px;color:{bar_c};font-weight:700;margin-bottom:4px">'
                f'{lbl} / {int(pcs)}pcs</div>')

    # ── Gantt 橫條月曆：每張工單是一條連續長方形 ──────────────
    def _build_gantt_cal():
        """Gantt式月曆：工單跨幾天就顯示一條連續橫條"""
        # 先算每張工單的最後生產日（start + mfg-1 working days）
        wo_records = []
        for _, r in _this_month.iterrows():
            s    = r["預計開工日"]
            mfg  = int(r["製造天數"])
            late = bool(r.get("趕不上", False))
            pno  = str(r.get("成品料號","")).strip()
            qty  = int(r["預計產量"]) if pd.notna(r["預計產量"]) else 0
            dr   = qty / mfg if mfg > 0 else 0
            # 最後生產日
            last = s
            for _ in range(mfg - 1):
                last = _next_workday(last)
            bc = "#E74C5B" if late else "#2A9DF4"
            bg = "#fca5a5" if late else "#bfdbfe"
            wo_records.append(dict(start=s, last=last, mfg=mfg, pno=pno,
                                   qty=qty, dr=dr, bc=bc, bg=bg, late=late))

        h = (f'<table style="width:100%;border-collapse:collapse;'
             f'font-family:Microsoft JhengHei;table-layout:fixed;border:1px solid #e2e8f0">')

        # 表頭
        h += '<tr>' + "".join(
            f'<th style="background:#EEF2F7;color:#607080;font-size:15px;font-weight:700;'
            f'text-align:center;padding:10px 4px;border:1px solid #dde8f3">{d}</th>'
            for d in day_names) + '</tr>'

        # 品名縮短：取有意義的機種碼（去除 # 及 9-XX- 前綴）
        def _short_model(pno):
            if not pno: return "—"
            parts = pno.split('-')
            # 格式 9-XX-MODEL####-VER_SUFFIX
            if len(parts) >= 3:
                model = parts[2].rstrip('#')          # 去尾部 #
                suffix = parts[-1] if len(parts) > 3 else ""
                return f"{model}-{suffix}" if suffix and suffix != model else model
            return pno

        week_start = _first - timedelta(days=_first.weekday())
        while week_start <= _last:
            week_end = week_start + timedelta(days=6)

            # ── 日期數字列 ────────────────────────────────
            h += '<tr>'
            for di in range(7):
                day   = week_start + timedelta(days=di)
                in_m  = (day.month == _month)
                is_t  = (day == TODAY)
                is_off= (day.weekday() >= 5) or (day in TAIWAN_HOLIDAYS)
                is_h  = (day in TAIWAN_HOLIDAYS)
                cbg   = "#f0f0f0" if not in_m else ("#dbeafe" if is_t else ("#fff0e6" if is_off else "#f9fbff"))
                nc    = "#bbb" if not in_m else ("#c0392b" if is_off else ("#1d4ed8" if is_t else "#1e293b"))
                off_tag = '<span style="font-size:10px;color:#c0392b;padding:1px 4px;'
                off_tag += 'background:#fee;border-radius:3px;margin-left:2px">假</span>' if is_h and in_m else ""
                util  = _util_bar(day) if in_m and not is_off else ""
                h += (f'<td style="background:{cbg};border:1px solid #e8ecf0;padding:8px 8px 4px">'
                      f'<div style="display:flex;align-items:center;margin-bottom:3px">'
                      f'<span style="font-size:18px;font-weight:900;color:{nc}">'
                      f'{day.day if in_m else ""}</span>{off_tag}</div>'
                      f'{util}</td>')
            h += '</tr>'

            # ── Gantt 工單橫條 ────────────────────────────
            week_wos = [w for w in wo_records
                        if w["start"] <= week_end and w["last"] >= week_start]
            for wo in sorted(week_wos, key=lambda x: x["start"]):
                eff_s = max(wo["start"], week_start)
                eff_e = min(wo["last"],  week_end)
                pre   = (eff_s - week_start).days
                span  = (eff_e - eff_s).days + 1
                suf   = 7 - pre - span
                is_fst= (wo["start"] >= week_start)
                is_lst= (wo["last"]  <= week_end)
                model = _short_model(wo["pno"])
                bc, bg = wo["bc"], wo["bg"]
                warn_tag = (' <span style="background:#E74C5B;color:#fff;font-size:10px;'
                            'padding:1px 5px;border-radius:3px">⚠ 趕不上</span>'
                            if wo["late"] else "")
                # 標記
                badge_l = (f'<span style="font-size:11px;font-weight:600;color:{bc};'
                           f'opacity:0.9">{"▶ 開工" if is_fst else "→ 繼續"}{warn_tag}</span>')
                badge_r = (f'<span style="font-size:11px;font-weight:600;color:{bc}">✓ 完工</span>'
                           if is_lst else '')
                bar_content = (
                    f'<div style="display:flex;justify-content:space-between;'
                    f'align-items:center;margin-bottom:3px">{badge_l}{badge_r}</div>'
                    f'<div style="font-size:15px;font-weight:800;color:#1a2e4a;'
                    f'letter-spacing:0.2px;line-height:1.3;word-break:break-all">{model}</div>'
                    f'<div style="font-size:12px;color:#607080;margin-top:3px">'
                    f'{int(wo["dr"]):,} pcs/天　共 <b style="color:#1a2e4a">{wo["qty"]:,}</b> pcs'
                    f'　{wo["mfg"]}天</div>'
                )
                h += '<tr>'
                if pre > 0:
                    h += (f'<td colspan="{pre}" style="background:#f9fbff;'
                          f'border:1px solid #e8ecf0"></td>')
                h += (f'<td colspan="{span}" style="'
                      f'background:linear-gradient(135deg,{bg},{bg}cc);'
                      f'border:1.5px solid {bc};border-left:4px solid {bc};'
                      f'border-radius:6px;padding:8px 12px;vertical-align:middle">'
                      f'{bar_content}</td>')
                if suf > 0:
                    h += (f'<td colspan="{suf}" style="background:#f9fbff;'
                          f'border:1px solid #e8ecf0"></td>')
                h += '</tr>'
            # 週間隔
            h += (f'<tr><td colspan="7" style="height:6px;background:#EEF2F7;'
                  f'border:none"></td></tr>')
            week_start += timedelta(weeks=1)

        return h + "</table>"

    # ── 週/月稼動率彙整表 ──────────────────────────────────
    def _week_util_rows():
        rows_html = ""
        d = _first - timedelta(days=_first.weekday())
        _mo_pcs = 0; _mo_cap = 0
        while d.month <= _month:
            wend = d + timedelta(days=4)
            w_pcs = sum(_daily_pcs.get(d+timedelta(days=i), 0) for i in range(5)
                        if (d+timedelta(days=i)).month == _month)
            w_wd  = sum(1 for i in range(5)
                        if (d+timedelta(days=i)).month == _month
                        and (d+timedelta(days=i)).weekday() < 5)
            w_cap  = w_wd * DAILY_CAP
            w_rate = int(w_pcs / w_cap * 100) if w_cap else 0
            if w_wd > 0:
                wlbl = f"W{d.isocalendar()[1]}（{d.strftime('%m/%d')}~{wend.strftime('%m/%d')}）"
                rc = "#E74C5B" if w_rate>=100 else ("#d97706" if w_rate>=80 else "#16A085")
                rows_html += (f'<tr><td style="padding:6px 10px;border:1px solid #e2e8f0">{wlbl}</td>'
                              f'<td style="text-align:right;padding:6px 10px;border:1px solid #e2e8f0">{int(w_pcs):,}</td>'
                              f'<td style="text-align:right;padding:6px 10px;border:1px solid #e2e8f0">{w_cap:,}</td>'
                              f'<td style="text-align:right;padding:6px 10px;border:1px solid #e2e8f0;'
                              f'color:{rc};font-weight:700">{w_rate}%</td></tr>')
                _mo_pcs += w_pcs; _mo_cap += w_cap
            d += timedelta(weeks=1)
        mo_rate = int(_mo_pcs / _mo_cap * 100) if _mo_cap else 0
        rc = "#E74C5B" if mo_rate>=100 else ("#d97706" if mo_rate>=80 else "#16A085")
        rows_html += (f'<tr style="background:#f8faff;font-weight:800">'
                      f'<td style="padding:6px 10px;border:1px solid #e2e8f0">📅 本月合計</td>'
                      f'<td style="text-align:right;padding:6px 10px;border:1px solid #e2e8f0">{int(_mo_pcs):,}</td>'
                      f'<td style="text-align:right;padding:6px 10px;border:1px solid #e2e8f0">{_mo_cap:,}</td>'
                      f'<td style="text-align:right;padding:6px 10px;border:1px solid #e2e8f0;'
                      f'color:{rc};font-weight:900">{mo_rate}%</td></tr>')
        return rows_html

    tab_start, tab_ship = st.tabs(["▶ 開工排程", "🚢 出貨排程"])
    with tab_start:
        # 週/月稼動率彙整
        st.markdown(
            f'<table style="width:100%;border-collapse:collapse;font-family:Microsoft JhengHei;'
            f'font-size:14px;margin-bottom:16px">'
            f'<tr style="background:#EEF2F7;font-weight:700">'
            f'<th style="text-align:left;padding:8px 10px;border:1px solid #e2e8f0">週次</th>'
            f'<th style="text-align:right;padding:8px 10px;border:1px solid #e2e8f0">排程產量(pcs)</th>'
            f'<th style="text-align:right;padding:8px 10px;border:1px solid #e2e8f0">最大產能(pcs)</th>'
            f'<th style="text-align:right;padding:8px 10px;border:1px solid #e2e8f0">稼動率</th></tr>'
            + _week_util_rows() + '</table>',
            unsafe_allow_html=True
        )
        # Gantt 橫條月曆
        st.markdown(_build_gantt_cal(), unsafe_allow_html=True)
        st.markdown(
            f'<div style="font-size:13px;color:#607080;margin-top:8px">'
            f'🟢&lt;80% 正常｜🟡 80~99% 接近滿載｜🔴≥100% 超載<br>'
            f'稼動率 = 當日排程產量 ÷ {DAILY_CAP} pcs（9084品項 150 pcs/天）'
            f'</div>', unsafe_allow_html=True)
    with tab_ship:
        st.markdown(_build_ship_cal(_ev_ship), unsafe_allow_html=True)
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
