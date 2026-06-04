import streamlit as st
import pandas as pd
import re
from datetime import date, timedelta, datetime
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from utils.shared import render_sidebar

st.set_page_config(page_title="工單進度看板", page_icon="📺",
                   layout="wide", initial_sidebar_state="collapsed")

# ══════════════════════════════════════════════════════
# 暗色科技風 CSS
# ══════════════════════════════════════════════════════
st.markdown("""
<style>
.stApp {
    background: linear-gradient(160deg, #020918 0%, #061228 55%, #0a1a35 100%) !important;
}
[data-testid="stHeader"]  { background: transparent !important; }
[data-testid="stSidebar"] { background: #050e22 !important; }
.block-container { padding: 0.6rem 1.2rem 2rem !important; max-width:100% !important; }
#MainMenu, footer, [data-testid="stToolbar"] { visibility: hidden; }

/* scrollbar */
::-webkit-scrollbar { width:5px; }
::-webkit-scrollbar-track { background:#020918; }
::-webkit-scrollbar-thumb { background:#1e3a8a; border-radius:3px; }

/* Streamlit default widget overrides */
.stAlert { background: rgba(30,58,138,0.25) !important;
           border:1px solid rgba(59,130,246,0.4) !important; color:#93c5fd !important; }
p { color:#cbd5e1; }
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
    date(2026,3,2), date(2026,4,3), date(2026,4,6),
    date(2026,5,1), date(2026,6,19), date(2026,9,25),
    date(2026,10,9),
}

def count_workdays(start, end):
    if not start or not end or start >= end: return 0
    count, cur = 0, start
    while cur < end:
        cur += timedelta(days=1)
        if cur.weekday() < 5 and cur not in TAIWAN_HOLIDAYS:
            count += 1
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
            if is_iqc:   iqc.append((mat_no, latest))
            elif latest < TODAY: delayed.append((mat_no, latest, (TODAY-latest).days))
            else: future.append((mat_no, latest, (latest-TODAY).days))
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
        buffer_days = count_workdays(qi_date,ship_date) if ship_date and qi_date else None
        target_gap  = buffer_days-MIN_BUFFER if buffer_days is not None else None
        if ship_date:
            wdays_to_ship=count_workdays(TODAY-timedelta(days=1),ship_date)
            is_urgent=wdays_to_ship<=10
        else: wdays_to_ship=None; is_urgent=False
        rows.append({'工單':wo,'成品料號':product,'預計產量':qty,
            '出貨日':ship_date,'出貨日_顯示':ship_label,
            '整體料齊率':rate,'料況狀態':mat_status,'重點提示':hint,
            '預計齊料日':qi_date,'緩衝天數':buffer_days,'達標差距':target_gap,
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
        if not files: return None, None
        files.sort(key=os.path.getmtime,reverse=True)
        f=files[0]
        mtime=pd.Timestamp(os.path.getmtime(f),unit='s').tz_localize('UTC').tz_convert('Asia/Taipei')
        return f, mtime
    except Exception: return None, None

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
# HEADER 看板標題列
# ══════════════════════════════════════════════════════
wday_names = ["一","二","三","四","五","六","日"]
wday = wday_names[TODAY.weekday()]
next_ref = 20-(NOW.minute%20)
data_ts  = src_mtime.strftime('%m/%d %H:%M') if src_mtime else "⚠️ 離線"

st.markdown(f"""
<div style="
  background: linear-gradient(90deg,#0d1f4e 0%,#0f2d6b 40%,#0d1f4e 100%);
  border:1px solid rgba(56,189,248,0.35);
  border-radius:14px; padding:14px 28px; margin-bottom:18px;
  box-shadow:0 0 30px rgba(14,165,233,0.15);
  display:flex; justify-content:space-between; align-items:center;">
  <div>
    <div style="color:#38bdf8;font-size:12px;font-weight:700;letter-spacing:2px;
                text-transform:uppercase">ORing &nbsp;·&nbsp; 生管 PC</div>
    <div style="color:#f0f9ff;font-size:26px;font-weight:900;margin-top:3px;
                text-shadow:0 0 20px rgba(56,189,248,0.6)">📺 &nbsp;工單進度看板</div>
  </div>
  <div style="text-align:center">
    <div style="color:#7dd3fc;font-size:12px;letter-spacing:1px">PRODUCTION SCHEDULING MONITOR</div>
    <div style="color:#f0f9ff;font-size:11px;margin-top:4px;color:#94a3b8">
      🕐 {NOW.strftime('%H:%M')} &nbsp;｜&nbsp; 每 20 分鐘自動更新
      &nbsp;｜&nbsp; 資料：{data_ts}
    </div>
  </div>
  <div style="text-align:right">
    <div style="color:#f0f9ff;font-size:30px;font-weight:900;
                text-shadow:0 0 20px rgba(56,189,248,0.5)">
      {TODAY.strftime('%Y / %m / %d')}
    </div>
    <div style="color:#38bdf8;font-size:16px;font-weight:700;margin-top:2px">（週{wday}）</div>
  </div>
</div>
""", unsafe_allow_html=True)

if df is None:
    st.markdown(f"""
<div style="background:rgba(239,68,68,0.1);border:1px solid rgba(239,68,68,0.5);
     border-radius:10px;padding:20px;text-align:center;color:#fca5a5;font-size:16px">
  ⚠️ &nbsp; 無法讀取資料，請確認網路磁碟已連線<br>
  <span style="font-size:13px;color:#94a3b8;margin-top:6px;display:block">{BASE_DIR}</span>
</div>""", unsafe_allow_html=True)
    st.stop()

# ── 計算週統計 ────────────────────────────────────────
_wd=TODAY.weekday()
wk_mon=TODAY-timedelta(days=_wd); wk_fri=wk_mon+timedelta(days=4)
nwk_mon=wk_mon+timedelta(days=7); nwk_fri=nwk_mon+timedelta(days=4)

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

def _week_stats(src,start,end):
    sub=src[(src["出貨日"]>=start)&(src["出貨日"]<=end)].copy()
    tq=int(sub["預計產量"].dropna().sum())
    rq=int(sub[sub["料況狀態"]=="已齊料"]["預計產量"].dropna().sum())
    lq=tq-rq
    lack_sub=sub[sub["料況狀態"]!="已齊料"]
    mat_dates=lack_sub["預計齊料日"].dropna()
    lm=max(mat_dates) if not mat_dates.empty else None
    return dict(n=len(sub),total_qty=tq,ready_qty=rq,lack_qty=lq,latest_mat=lm,sub=sub)

ws=_week_stats(exp_df,wk_mon,wk_fri)
nws=_week_stats(exp_df,nwk_mon,nwk_fri)
today_df=exp_df[exp_df["出貨日"]==TODAY].copy()

wdays_this=count_workdays(TODAY-timedelta(days=1),wk_fri)
wdays_next=count_workdays(TODAY-timedelta(days=1),nwk_fri)
cap_this=wdays_this*DAILY_CAP
cap_next=wdays_next*DAILY_CAP

# ══════════════════════════════════════════════════════
# 本週 / 下週 大卡片
# ══════════════════════════════════════════════════════
def _dark_week_card(label, start, end, stats, wdays_left, cap_left):
    tq,rq,lq=stats["total_qty"],stats["ready_qty"],stats["lack_qty"]
    lm=stats["latest_mat"]
    n=stats["n"]
    pct=int(rq/tq*100) if tq else 0
    need_days=round(tq/DAILY_CAP,1) if tq else 0
    lm_s=lm.strftime('%m/%d') if lm and hasattr(lm,'strftime') else "—"

    if tq==0:
        status_txt="無出貨工單"
        accent="#475569"; glow="rgba(71,85,105,0.3)"
        icon_html="<span style='font-size:20px'>⬜</span>"
        badge_bg="rgba(71,85,105,0.2)"; badge_c="#94a3b8"
    elif lq==0:
        status_txt="全數已齊料，可如期出貨"
        accent="#22d3ee"; glow="rgba(34,211,238,0.25)"
        icon_html="<span style='font-size:20px'>✅</span>"
        badge_bg="rgba(34,211,238,0.15)"; badge_c="#67e8f9"
    elif cap_left>=lq:
        status_txt=f"仍缺料 {lq:,} pcs，產能尚足"
        accent="#fbbf24"; glow="rgba(251,191,36,0.25)"
        icon_html="<span style='font-size:20px'>⚠️</span>"
        badge_bg="rgba(251,191,36,0.15)"; badge_c="#fde68a"
    else:
        status_txt=f"缺料 {lq:,} pcs，產能不足！"
        accent="#f87171"; glow="rgba(248,113,113,0.3)"
        icon_html="<span style='font-size:20px'>🔴</span>"
        badge_bg="rgba(248,113,113,0.15)"; badge_c="#fca5a5"

    bar_ready=f"width:{pct}%;background:linear-gradient(90deg,#22d3ee,#06b6d4)"
    bar_lack =f"width:{100-pct}%;background:rgba(248,113,113,0.4)"

    return f"""
<div style="
  background:linear-gradient(135deg,rgba(13,28,65,0.95),rgba(8,18,45,0.95));
  border:1px solid {accent};
  border-radius:16px; padding:22px 26px;
  box-shadow:0 0 28px {glow}, inset 0 1px 0 rgba(255,255,255,0.05);
  position:relative; overflow:hidden; height:100%;">

  <!-- 角落光效 -->
  <div style="position:absolute;top:-40px;right:-40px;width:120px;height:120px;
    background:radial-gradient(circle,{glow} 0%,transparent 70%);pointer-events:none"></div>

  <!-- 標題 -->
  <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:14px">
    <div>
      <div style="color:#94a3b8;font-size:11px;letter-spacing:2px;text-transform:uppercase;margin-bottom:4px">
        {label}
      </div>
      <div style="color:#cbd5e1;font-size:13px">
        {start.strftime('%m/%d')} ~ {end.strftime('%m/%d')}
      </div>
    </div>
    <div style="background:{badge_bg};border:1px solid {accent};border-radius:8px;
                padding:6px 14px;font-size:14px;font-weight:800;color:{badge_c}">
      {icon_html} &nbsp;{status_txt}
    </div>
  </div>

  <!-- 數字區 -->
  <div style="display:flex;gap:0;margin-bottom:18px">
    {''.join([
      f"""<div style="flex:1;text-align:center;border-right:1px solid rgba(255,255,255,0.07);padding:0 8px">
        <div style="font-size:38px;font-weight:900;color:{accent};line-height:1.1;
                    text-shadow:0 0 20px {glow}">{v}</div>
        <div style="font-size:11px;color:#64748b;margin-top:4px;letter-spacing:0.5px">{lb}</div>
      </div>"""
      for v,lb in [
        (n, "出貨筆數"),
        (f"{tq:,}", "總量 pcs"),
        (f"<span style='color:#4ade80'>{rq:,}</span>", "已齊料 pcs"),
        (f"<span style='color:#f87171'>{lq:,}</span>", "缺料 pcs"),
        (f"{need_days}", f"需生產天數<br><span style='font-size:10px'>({DAILY_CAP}pcs/天)</span>"),
      ]
    ])}
  </div>

  <!-- 進度條 -->
  <div style="font-size:12px;color:#64748b;margin-bottom:6px;display:flex;justify-content:space-between">
    <span>齊料進度 <b style="color:{accent}">{pct}%</b></span>
    <span>剩餘產能 <b style="color:#7dd3fc">{cap_left:,} pcs</b>（{wdays_left} 工作天）
      {"&nbsp;｜&nbsp; 最晚齊料 <b style='color:#f87171'>" + lm_s + "</b>" if lm else ""}
    </span>
  </div>
  <div style="background:rgba(255,255,255,0.06);border-radius:4px;height:8px;overflow:hidden;
              box-shadow:inset 0 1px 3px rgba(0,0,0,0.5)">
    <div style="display:flex;height:100%">
      <div style="{bar_ready};border-radius:4px 0 0 4px;box-shadow:0 0 10px rgba(34,211,238,0.6)"></div>
      <div style="{bar_lack};border-radius:0 4px 4px 0"></div>
    </div>
  </div>
</div>"""

c1,c2=st.columns(2)
c1.markdown(_dark_week_card("本週出貨",wk_mon,wk_fri,ws,wdays_this,cap_this),unsafe_allow_html=True)
c2.markdown(_dark_week_card("下週出貨",nwk_mon,nwk_fri,nws,wdays_next,cap_next),unsafe_allow_html=True)

st.markdown("<div style='margin-top:18px'></div>", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════
# 今日出貨 ＋ 今日來料（左右分欄）
# ══════════════════════════════════════════════════════
col_left,col_right=st.columns(2)

# ── 左：今日出貨工單 ─────────────────────────────────
with col_left:
    st.markdown(f"""
<div style="background:linear-gradient(90deg,rgba(30,58,138,0.8),rgba(14,40,100,0.5));
     border:1px solid rgba(59,130,246,0.5);border-radius:10px;
     padding:10px 18px;margin-bottom:12px;
     box-shadow:0 0 16px rgba(59,130,246,0.15)">
  <span style="color:#93c5fd;font-size:15px;font-weight:800">📦 今日出貨工單</span>
  <span style="background:rgba(59,130,246,0.25);color:#7dd3fc;border-radius:20px;
               padding:2px 10px;font-size:12px;margin-left:10px;font-weight:700">
    {TODAY.strftime('%m/%d')} &nbsp; 共 {len(today_df)} 筆
  </span>
</div>""", unsafe_allow_html=True)

    if today_df.empty:
        st.markdown("""
<div style="background:rgba(15,23,42,0.6);border:1px solid rgba(51,65,85,0.5);
     border-radius:8px;padding:18px;text-align:center;color:#475569">
  — 今日無出貨工單 —
</div>""", unsafe_allow_html=True)
    else:
        for _,row in today_df.iterrows():
            is_ready=row["料況狀態"]=="已齊料"
            is_none =row["料況狀態"]=="完全缺料"
            if is_ready:   ac,bg,bc="#22d3ee","rgba(6,78,59,0.25)","rgba(34,211,238,0.4)"
            elif is_none:  ac,bg,bc="#f87171","rgba(127,29,29,0.25)","rgba(248,113,113,0.4)"
            else:          ac,bg,bc="#fbbf24","rgba(120,53,15,0.25)","rgba(251,191,36,0.4)"
            qi=(row["預計齊料日"].strftime('%m/%d')
                if pd.notna(row["預計齊料日"]) and hasattr(row["預計齊料日"],'strftime') else "—")
            qty=int(row["預計產量"]) if pd.notna(row["預計產量"]) else "?"
            hint=row.get("重點提示","") or ""
            st.markdown(f"""
<div style="background:{bg};border:1px solid {bc};border-left:4px solid {ac};
     border-radius:8px;padding:12px 16px;margin-bottom:8px;
     box-shadow:0 0 10px rgba(0,0,0,0.3)">
  <div style="display:flex;justify-content:space-between;align-items:center">
    <div style="font-size:14px;font-weight:800;color:#f1f5f9">{row['工單']}
      <span style="color:#94a3b8;font-size:12px;font-weight:400;margin-left:8px">{row['成品料號']}</span>
      <span style="background:rgba(255,255,255,0.1);border-radius:4px;padding:1px 8px;
                   margin-left:6px;font-size:12px;color:#cbd5e1">× {qty}</span>
    </div>
    <span style="background:rgba(0,0,0,0.3);color:{ac};border:1px solid {ac};
                 border-radius:6px;padding:2px 10px;font-weight:700;font-size:12px">
      {row['料況狀態']}
    </span>
  </div>
  <div style="font-size:12px;color:#64748b;margin-top:6px">
    最後到料日 <b style="color:#94a3b8">{qi}</b>
    {"　｜　💬 <span style='color:#cbd5e1'>" + hint + "</span>" if hint else ""}
  </div>
</div>""", unsafe_allow_html=True)

# ── 右：今日 + 明日 來料 ──────────────────────────────
with col_right:
    TOMORROW=TODAY+timedelta(days=1)
    mat_rows=[]
    for _,row in df.iterrows():
        if row["料況狀態"]=="已齊料": continue
        wo=row["工單"]; product=row["成品料號"]
        ship_str=row.get("出貨日_顯示","") or "未定"
        is_urg=bool(row.get("急件",False))
        for mat,arr_d,_ in row["_future"]:
            mat_rows.append({"到料日":arr_d,"料號":mat,"工單":wo,
                             "成品料號":product,"出貨日":ship_str,"急件":is_urg})
        for mat,arr_d,dl in row["_delayed"]:
            mat_rows.append({"到料日":arr_d,"料號":mat,"工單":wo,
                             "成品料號":product,"出貨日":ship_str,
                             "急件":is_urg,"_overdue":True,"_days_late":dl})
    mat_df_k=pd.DataFrame(mat_rows) if mat_rows else pd.DataFrame()

    for day_label,day_date in [("今日",TODAY),("明日",TOMORROW)]:
        sub=mat_df_k[mat_df_k["到料日"]==day_date] if not mat_df_k.empty else pd.DataFrame()
        n_urg=int(sub["急件"].sum()) if not sub.empty and "急件" in sub.columns else 0
        is_today=(day_label=="今日")
        hdr_ac="#38bdf8" if is_today else "#818cf8"
        hdr_glow="rgba(56,189,248,0.15)" if is_today else "rgba(129,140,248,0.15)"
        urg_tag=f"""<span style="background:rgba(249,115,22,0.2);color:#fb923c;
          border-radius:20px;padding:1px 10px;font-size:11px;margin-left:8px">
          🚨 急件 {n_urg}</span>""" if n_urg else ""

        st.markdown(f"""
<div style="background:linear-gradient(90deg,rgba(15,23,42,0.9),rgba(20,30,55,0.6));
     border:1px solid rgba(56,189,248,0.3);border-left:4px solid {hdr_ac};
     border-radius:10px;padding:9px 16px;margin-bottom:8px;
     box-shadow:0 0 14px {hdr_glow}">
  <span style="font-size:14px;font-weight:800;color:{hdr_ac}">
    🚚 {day_label}預計來料（{day_date.strftime('%m/%d')}）
  </span>
  <span style="color:#475569;font-size:12px;margin-left:8px">{len(sub)} 項</span>
  {urg_tag}
</div>""", unsafe_allow_html=True)

        if sub.empty:
            st.markdown("""<div style="color:#334155;font-size:13px;padding:4px 16px;
                margin-bottom:12px">— 無預計來料 —</div>""", unsafe_allow_html=True)
        else:
            for _,mr in sub.iterrows():
                is_urg_r=bool(mr.get("急件",False))
                is_ovd=bool(mr.get("_overdue",False))
                if is_ovd:  row_ac,row_bg="#f87171","rgba(127,29,29,0.25)"
                elif is_urg_r: row_ac,row_bg="#fb923c","rgba(124,45,18,0.25)"
                else:       row_ac,row_bg="#22d3ee","rgba(8,47,73,0.25)"
                badge="🔴 逾期" if is_ovd else ("🚨 急件" if is_urg_r else "🔵")
                _dl=mr.get("_days_late",0)
                _dl=0 if(_dl is None or(isinstance(_dl,float) and pd.isna(_dl))) else int(_dl)
                ovd_note=f"<span style='color:#f87171;font-size:11px'> 逾期 {_dl} 天</span>" if is_ovd else ""
                st.markdown(f"""
<div style="border:1px solid rgba({
  '248,113,113' if is_ovd else '251,146,60' if is_urg_r else '34,211,238'
  },0.3);border-radius:6px;padding:8px 12px;margin-bottom:5px;background:{row_bg}">
  <div style="font-size:13px;color:#e2e8f0">
    {badge} <b style="color:{row_ac}">{mr['料號']}</b>
    <span style="color:#475569;font-size:11px;margin-left:8px">{mr['工單']} / {mr['成品料號']}</span>
    {ovd_note}
  </div>
  <div style="font-size:11px;color:#334155;margin-top:2px">出貨日：{mr['出貨日']}</div>
</div>""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════
# 急件缺料工單
# ══════════════════════════════════════════════════════
st.markdown("<div style='margin-top:16px'></div>", unsafe_allow_html=True)
st.markdown("""
<div style="background:linear-gradient(90deg,rgba(127,29,29,0.7),rgba(80,10,10,0.4));
     border:1px solid rgba(239,68,68,0.5);border-radius:10px;padding:10px 18px;margin-bottom:14px;
     box-shadow:0 0 20px rgba(239,68,68,0.15)">
  <span style="color:#fca5a5;font-size:15px;font-weight:800;
               text-shadow:0 0 10px rgba(239,68,68,0.5)">
    🚨 &nbsp;急件缺料工單（兩週內 · 出貨剩 ≤10 工作天）
  </span>
</div>""", unsafe_allow_html=True)

both_weeks=pd.concat([ws["sub"],nws["sub"]],ignore_index=True).drop_duplicates(subset=["工單"])
urgent_lack=both_weeks[
    (both_weeks["料況狀態"]!="已齊料")&(both_weeks["急件"]==True)
].sort_values("出貨日")

if urgent_lack.empty:
    st.markdown("""
<div style="background:rgba(6,78,59,0.2);border:1px solid rgba(34,211,238,0.3);
     border-radius:10px;padding:16px;text-align:center;
     color:#6ee7b7;font-size:15px;font-weight:700">
  ✅ &nbsp; 目前兩週內無急件缺料工單
</div>""", unsafe_allow_html=True)
else:
    cols_per_row=3
    rows_list=list(urgent_lack.iterrows())
    for i in range(0,len(rows_list),cols_per_row):
        chunk=rows_list[i:i+cols_per_row]
        cols=st.columns(cols_per_row)
        for j,(_,row) in enumerate(chunk):
            with cols[j]:
                ship_d=row["出貨日"].strftime('%m/%d') if pd.notna(row["出貨日"]) else "未定"
                wdays=row.get("距出貨工作天")
                wday_s=f"{int(wdays)} 工作天" if pd.notna(wdays) else "—"
                qi=(row["預計齊料日"].strftime('%m/%d')
                    if pd.notna(row["預計齊料日"]) and hasattr(row["預計齊料日"],'strftime') else "—")
                qty=int(row["預計產量"]) if pd.notna(row["預計產量"]) else "?"
                hint=row.get("重點提示","") or ""
                st.markdown(f"""
<div style="background:linear-gradient(135deg,rgba(127,29,29,0.3),rgba(50,10,10,0.4));
     border:1px solid rgba(239,68,68,0.5);border-top:3px solid #f87171;
     border-radius:10px;padding:14px 16px;margin-bottom:8px;
     box-shadow:0 0 16px rgba(239,68,68,0.15)">
  <div style="font-size:14px;font-weight:800;color:#fca5a5;margin-bottom:4px">{row['工單']}</div>
  <div style="font-size:12px;color:#64748b;margin-bottom:10px">{row['成品料號']} &nbsp;×&nbsp; {qty}</div>
  <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:8px">
    <span style="background:rgba(239,68,68,0.2);color:#f87171;border:1px solid rgba(239,68,68,0.4);
                 border-radius:6px;padding:2px 10px;font-size:12px;font-weight:700">
      {row['料況狀態']}
    </span>
    <span style="background:rgba(251,191,36,0.15);color:#fbbf24;border:1px solid rgba(251,191,36,0.3);
                 border-radius:6px;padding:2px 10px;font-size:12px">
      出貨 {ship_d}（剩 {wday_s}）
    </span>
  </div>
  <div style="font-size:12px;color:#475569">
    最後到料日 <b style="color:#94a3b8">{qi}</b>
    {"　💬 <span style='color:#94a3b8'>" + hint + "</span>" if hint else ""}
  </div>
</div>""", unsafe_allow_html=True)

# ── 頁尾 ──────────────────────────────────────────────
st.markdown(f"""
<div style="text-align:center;color:#1e3a5f;font-size:11px;margin-top:30px;letter-spacing:1px">
  DATA · {src_path.replace(r'\\192.168.2.34\MO_Storage','NAS') if src_path else '—'}
  &nbsp;｜&nbsp; NEXT REFRESH · {next_ref} min
</div>""", unsafe_allow_html=True)
