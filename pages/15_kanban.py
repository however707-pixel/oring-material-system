import streamlit as st
import pandas as pd
import re
from datetime import date, timedelta, datetime
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from utils.shared import inject_css, render_sidebar

st.set_page_config(page_title="工單進度看板", page_icon="📺", layout="wide")

inject_css()
render_sidebar()


# ════════════════════════════════════════════════════════════════════
# 共用常數 & 函式（與 10_scheduling.py 一致）
# ════════════════════════════════════════════════════════════════════
TODAY    = date.today()
NOW      = datetime.now()
REF_YEAR = TODAY.year
MIN_BUFFER = 10

TAIWAN_HOLIDAYS = {
    date(2026, 1, 1), date(2026, 1, 2),
    date(2026, 2, 16), date(2026, 2, 17), date(2026, 2, 18),
    date(2026, 2, 19), date(2026, 2, 20),
    date(2026, 3, 2), date(2026, 4, 3), date(2026, 4, 6),
    date(2026, 5, 1), date(2026, 6, 19), date(2026, 9, 25),
    date(2026, 10, 9),
}

def count_workdays(start, end):
    if not start or not end or start >= end:
        return 0
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
        if (TODAY - dt).days > 180:
            dt = date(REF_YEAR + 1, m, d)
        return dt
    except Exception:
        return None

def parse_ship_date(raw):
    if pd.isna(raw): return None, ''
    s = str(raw).strip()
    if s in ('', 'nan', 'None', 'TBD', '試產', '00:00:00'):
        return None, s if s not in ('nan', 'None', '00:00:00') else ''
    if hasattr(raw, 'date'):
        d = raw.date(); return d, d.strftime('%Y-%m-%d')
    try:
        d = pd.to_datetime(s).date(); return d, d.strftime('%Y-%m-%d')
    except Exception:
        pass
    found = re.findall(r'(\d{1,2})/(\d{1,2})', s)
    dates = [parse_date_str(f'{m}/{d}') for m, d in found]
    dates = [d for d in dates if d]
    if dates:
        return min(dates), s
    return None, s

def parse_material_status(text):
    if pd.isna(text) or not str(text).strip():
        return None, [], [], []
    lines = str(text).strip().split('\n')
    all_dates, delayed, iqc, future = [], [], [], []
    for line in lines:
        line = line.strip()
        if not line: continue
        mat_no = line.split('*')[0].strip() if '*' in line else line[:50]
        is_iqc = bool(re.search(r'IQC', line, re.IGNORECASE))
        date_strs = re.findall(r'\((\d{1,2}/\d{1,2})\)', line)
        mat_dates = [parse_date_str(s) for s in date_strs]
        mat_dates = [d for d in mat_dates if d]
        if mat_dates:
            latest = max(mat_dates)
            all_dates.append(latest)
            if is_iqc:
                iqc.append((mat_no, latest))
            elif latest < TODAY:
                iqc.append((mat_no, latest)) if False else delayed.append((mat_no, latest, (TODAY - latest).days))
            else:
                future.append((mat_no, latest, (latest - TODAY).days))
        else:
            if is_iqc:
                iqc.append((mat_no, None))
    return (max(all_dates) if all_dates else None), delayed, iqc, future

def parse_file(path):
    df = pd.read_excel(path, sheet_name='LIST', header=0)
    rows = []
    for _, r in df.iterrows():
        wo      = str(r.iloc[1]).strip() if pd.notna(r.iloc[1]) else ''
        product = str(r.iloc[2]).strip() if pd.notna(r.iloc[2]) else ''
        qty     = r.iloc[3]
        rate    = float(r.iloc[5]) if pd.notna(r.iloc[5]) else 0.0
        hint    = str(r.iloc[8]).strip() if pd.notna(r.iloc[8]) else ''
        mat_text = r.iloc[11]
        if not wo or wo == 'nan': continue

        ship_date, ship_label = parse_ship_date(r.iloc[12])
        latest_mat, delayed, iqc, future = parse_material_status(mat_text)

        hint_qi = any(k in hint for k in ('已發料','已齊料','已發放','齊料'))
        qi_date = latest_mat
        if qi_date is None and hint_qi:
            m = re.search(r'(\d{1,2})/(\d{1,2})', hint)
            qi_date = parse_date_str(f'{m.group(1)}/{m.group(2)}') if m else TODAY

        if rate >= 1.0 or hint_qi:
            mat_status = '已齊料'; qi_date = qi_date or TODAY
        elif rate == 0.0:
            mat_status = '完全缺料'
        else:
            mat_status = f'缺料 {rate:.0%}'

        buffer_days = count_workdays(qi_date, ship_date) if ship_date and qi_date else None
        target_gap  = buffer_days - MIN_BUFFER if buffer_days is not None else None

        if ship_date:
            wdays_to_ship = count_workdays(TODAY - timedelta(days=1), ship_date)
            is_urgent = wdays_to_ship <= 10
        else:
            wdays_to_ship = None; is_urgent = False

        rows.append({
            '工單': wo, '成品料號': product, '預計產量': qty,
            '出貨日': ship_date, '出貨日_顯示': ship_label,
            '整體料齊率': rate, '料況狀態': mat_status,
            '重點提示': hint,
            '預計齊料日': qi_date, '緩衝天數': buffer_days, '達標差距': target_gap,
            '距出貨工作天': wdays_to_ship, '急件': is_urgent,
            '_delayed': delayed, '_iqc': iqc, '_future': future,
        })
    return pd.DataFrame(rows)

# ── 自動載入最新檔案 ────────────────────────────────────────────────────────
BASE_DIR  = r"\\192.168.2.34\MO_Storage\ORing MO\ORing-MO 工作\早會資料夾"
FILE_NAME = "簡版-工單缺料狀況.xlsx"

def find_latest():
    try:
        import glob
        files = glob.glob(os.path.join(BASE_DIR, "**", FILE_NAME), recursive=True)
        if not files: return None, None
        files.sort(key=os.path.getmtime, reverse=True)
        f = files[0]
        mtime = pd.Timestamp(os.path.getmtime(f), unit='s').tz_localize('UTC').tz_convert('Asia/Taipei')
        return f, mtime
    except Exception:
        return None, None

@st.cache_data(ttl=20*60, show_spinner=False)
def load_data():
    try:
        path, mtime = find_latest()
        if path is None: return None, None, None
        return parse_file(path), path, mtime
    except Exception:
        return None, None, None

try:
    df, src_path, src_mtime = load_data()
except Exception:
    df, src_path, src_mtime = None, None, None

# ════════════════════════════════════════════════════════════════════
# 看板 Header
# ════════════════════════════════════════════════════════════════════
wday_names = ["一", "二", "三", "四", "五", "六", "日"]
wday = wday_names[TODAY.weekday()]
next_refresh_min = 20 - (NOW.minute % 20)

st.markdown(f"""
<div style="background:linear-gradient(135deg,#1e3a8a,#1d4ed8);
     border-radius:12px;padding:16px 28px;margin-bottom:20px;
     display:flex;justify-content:space-between;align-items:center">
  <div>
    <div style="color:#93c5fd;font-size:13px;font-weight:600;letter-spacing:1px">ORing 生管 PC</div>
    <div style="color:white;font-size:26px;font-weight:900;margin-top:2px">📺 工單進度看板</div>
  </div>
  <div style="text-align:right">
    <div style="color:white;font-size:32px;font-weight:800">{TODAY.strftime('%Y / %m / %d')}（週{wday}）</div>
    <div style="color:#93c5fd;font-size:13px;margin-top:4px">
      🕐 {NOW.strftime('%H:%M')} &nbsp;｜&nbsp;
      每 20 分鐘自動更新 &nbsp;｜&nbsp;
      {"資料：" + src_mtime.strftime('%m/%d %H:%M') if src_mtime else "⚠️ 無法連線"}
    </div>
  </div>
</div>
""", unsafe_allow_html=True)

if df is None:
    st.error(f"⚠️ 無法讀取資料，請確認網路磁碟已連線：{BASE_DIR}")
    st.stop()

# ════════════════════════════════════════════════════════════════════
# 本週範圍
# ════════════════════════════════════════════════════════════════════
_wd     = TODAY.weekday()
wk_mon  = TODAY - timedelta(days=_wd)
wk_fri  = wk_mon + timedelta(days=4)
nwk_mon = wk_mon + timedelta(days=7)
nwk_fri = nwk_mon + timedelta(days=4)

def _expand_ship(src):
    records = []
    for _, row in src.iterrows():
        label = str(row.get("出貨日_顯示", "") or "")
        pairs = re.findall(r'(\d{1,2}/\d{1,2})[^*\n,，]*\*\s*(\d+)', label)
        if len(pairs) > 1:
            for ds, qs in pairs:
                d = parse_date_str(ds)
                if d:
                    nr = row.copy(); nr["出貨日"] = d; nr["預計產量"] = int(qs)
                    records.append(nr)
        else:
            records.append(row)
    return pd.DataFrame(records) if records else src.copy()

exp_df = _expand_ship(df[df["出貨日"].notna()].copy())

def _week_stats(src, start, end):
    sub = src[(src["出貨日"] >= start) & (src["出貨日"] <= end)].copy()
    tq  = int(sub["預計產量"].dropna().sum())
    rq  = int(sub[sub["料況狀態"] == "已齊料"]["預計產量"].dropna().sum())
    lq  = tq - rq
    lack_sub = sub[sub["料況狀態"] != "已齊料"]
    mat_dates = lack_sub["預計齊料日"].dropna()
    latest_mat = max(mat_dates) if not mat_dates.empty else None
    return dict(n=len(sub), total_qty=tq, ready_qty=rq, lack_qty=lq,
                latest_mat=latest_mat, sub=sub)

ws  = _week_stats(exp_df, wk_mon, wk_fri)
nws = _week_stats(exp_df, nwk_mon, nwk_fri)

# 今日出貨
today_df = exp_df[exp_df["出貨日"] == TODAY].copy()

# ════════════════════════════════════════════════════════════════════
# 區塊 1：本週 / 下週 出貨達成概況（大卡片）
# ════════════════════════════════════════════════════════════════════
def _big_card(label, date_range_str, stats, wdays_left, cap_left):
    tq, rq, lq = stats["total_qty"], stats["ready_qty"], stats["lack_qty"]
    lm = stats["latest_mat"]
    if tq == 0:
        icon, bg, tc, bc, msg = "⬜","#f1f5f9","#64748b","#cbd5e1","無出貨工單"
    elif lq == 0:
        icon, bg, tc, bc, msg = "✅","#f0fdf4","#15803d","#22c55e","全數已齊料，可如期出貨"
    elif cap_left >= lq:
        icon, bg, tc, bc, msg = "⚠️","#fefce8","#92400e","#eab308",f"缺料 {lq:,} pcs，產能尚足"
    else:
        icon, bg, tc, bc, msg = "🔴","#fff1f2","#b91c1c","#ef4444",f"缺料 {lq:,} pcs，產能不足，風險！"

    pct  = int(rq/tq*100) if tq else 0
    lm_s = lm.strftime('%m/%d') if lm and hasattr(lm,'strftime') else "—"

    return f"""
<div style="border:3px solid {bc};border-radius:14px;padding:20px 24px;background:{bg}">
  <div style="font-size:14px;font-weight:700;color:#64748b">{label}
    <span style="font-weight:400">{date_range_str}</span>
  </div>
  <div style="font-size:22px;font-weight:900;color:{tc};margin:4px 0">{icon} {msg}</div>
  <div style="display:flex;gap:28px;margin:14px 0 10px">
    <div><div style="font-size:36px;font-weight:900;color:{tc}">{stats['n']}</div>
         <div style="font-size:12px;color:#64748b">出貨筆數</div></div>
    <div><div style="font-size:36px;font-weight:900;color:{tc}">{tq:,}</div>
         <div style="font-size:12px;color:#64748b">總量 pcs</div></div>
    <div><div style="font-size:36px;font-weight:900;color:#15803d">{rq:,}</div>
         <div style="font-size:12px;color:#64748b">已齊料 pcs</div></div>
    <div><div style="font-size:36px;font-weight:900;color:#dc2626">{lq:,}</div>
         <div style="font-size:12px;color:#64748b">缺料 pcs</div></div>
    <div><div style="font-size:36px;font-weight:900;color:{tc}">{round(tq/150,1) if tq else 0}</div>
         <div style="font-size:12px;color:#64748b">需生產天數<br><small>(150pcs/天)</small></div></div>
  </div>
  <div style="font-size:12px;color:#64748b;margin-bottom:5px">
    齊料進度 {pct}% &nbsp;｜&nbsp; 剩餘產能 {cap_left:,} pcs（{wdays_left} 工作天）
    {"&nbsp;｜&nbsp; 最晚齊料日 <b style='color:#dc2626'>" + lm_s + "</b>" if lm else ""}
  </div>
  <div style="background:#e2e8f0;border-radius:6px;height:16px;overflow:hidden">
    <div style="display:flex;height:100%">
      <div style="width:{pct}%;background:#22c55e"></div>
      <div style="width:{100-pct}%;background:#f87171"></div>
    </div>
  </div>
</div>"""

wdays_this = count_workdays(TODAY - timedelta(days=1), wk_fri)
wdays_next = count_workdays(TODAY - timedelta(days=1), nwk_fri)

c1, c2 = st.columns(2)
c1.markdown(_big_card("本週出貨", f"{wk_mon.strftime('%m/%d')} ~ {wk_fri.strftime('%m/%d')}",
                      ws, wdays_this, wdays_this * 150), unsafe_allow_html=True)
c2.markdown(_big_card("下週出貨", f"{nwk_mon.strftime('%m/%d')} ~ {nwk_fri.strftime('%m/%d')}",
                      nws, wdays_next, wdays_next * 150), unsafe_allow_html=True)

st.markdown("<div style='margin-top:18px'></div>", unsafe_allow_html=True)

# ════════════════════════════════════════════════════════════════════
# 區塊 2：今日出貨工單 + 今日/明日 來料
# ════════════════════════════════════════════════════════════════════
col_left, col_right = st.columns([1, 1])

# ── 左：今日出貨工單 ────────────────────────────────────────────────
with col_left:
    st.markdown(f"""
<div style="background:#1e3a8a;border-radius:10px;padding:10px 16px;margin-bottom:12px">
  <span style="color:white;font-size:16px;font-weight:800">📦 今日出貨工單</span>
  <span style="color:#93c5fd;font-size:13px;margin-left:8px">{TODAY.strftime('%m/%d')}　共 {len(today_df)} 筆</span>
</div>""", unsafe_allow_html=True)

    if today_df.empty:
        st.info("今日無出貨工單")
    else:
        for _, row in today_df.iterrows():
            is_ready = row["料況狀態"] == "已齊料"
            is_none  = row["料況狀態"] == "完全缺料"
            bg = "#f0fdf4" if is_ready else ("#fff1f2" if is_none else "#fefce8")
            bc = "#22c55e" if is_ready else ("#ef4444" if is_none else "#eab308")
            tc = "#15803d" if is_ready else ("#b91c1c" if is_none else "#92400e")
            qi = (row["預計齊料日"].strftime('%m/%d')
                  if pd.notna(row["預計齊料日"]) and hasattr(row["預計齊料日"],'strftime') else "—")
            qty = int(row["預計產量"]) if pd.notna(row["預計產量"]) else "?"
            hint = row.get("重點提示","") or ""

            st.markdown(f"""
<div style="border:1px solid {bc};border-left:5px solid {bc};border-radius:8px;
     padding:10px 14px;margin-bottom:8px;background:{bg}">
  <div style="display:flex;justify-content:space-between;align-items:center">
    <div style="font-size:15px;font-weight:800">{row['工單']}
      <span style="color:#64748b;font-size:13px;font-weight:400;margin-left:8px">{row['成品料號']}</span>
      <span style="background:#f1f5f9;border-radius:4px;padding:1px 8px;margin-left:6px;font-size:13px">× {qty}</span>
    </div>
    <span style="background:{bg};color:{tc};border:1px solid {bc};border-radius:6px;
                 padding:2px 10px;font-weight:700;font-size:13px">{row['料況狀態']}</span>
  </div>
  <div style="font-size:12px;color:#475569;margin-top:5px">
    最後到料日 <b>{qi}</b>
    {"　｜　💬 " + hint if hint else ""}
  </div>
</div>""", unsafe_allow_html=True)

# ── 右：今日 + 明日 來料 ─────────────────────────────────────────
with col_right:
    TOMORROW = TODAY + timedelta(days=1)

    # 展開所有缺料工單的進料明細
    mat_rows = []
    for _, row in df.iterrows():
        if row["料況狀態"] == "已齊料": continue
        wo = row["工單"]; product = row["成品料號"]
        ship_d = row["出貨日"]; ship_str = row.get("出貨日_顯示","") or "未定"
        is_urg = bool(row.get("急件", False))

        for mat, arr_d, _ in row["_future"]:
            mat_rows.append({"到料日": arr_d, "料號": mat, "工單": wo,
                             "成品料號": product, "出貨日": ship_str, "急件": is_urg})
        for mat, arr_d, dl in row["_delayed"]:
            mat_rows.append({"到料日": arr_d, "料號": mat, "工單": wo,
                             "成品料號": product, "出貨日": ship_str,
                             "急件": is_urg, "_overdue": True, "_days_late": dl})

    mat_df_k = pd.DataFrame(mat_rows) if mat_rows else pd.DataFrame()

    for day_label, day_date in [("今日", TODAY), ("明日", TOMORROW)]:
        sub = mat_df_k[mat_df_k["到料日"] == day_date] if not mat_df_k.empty else pd.DataFrame()
        n_urg = int(sub["急件"].sum()) if not sub.empty and "急件" in sub.columns else 0
        is_past = day_date < TODAY
        hdr_bg = "#fff1f2" if is_past else ("#eff6ff" if day_label=="今日" else "#f8fafc")
        hdr_bc = "#ef4444" if is_past else ("#3b82f6" if day_label=="今日" else "#94a3b8")
        urg_tag = f"<span style='background:#fff7ed;color:#c2410c;border-radius:4px;padding:1px 8px;font-size:12px;margin-left:6px'>🚨 急件 {n_urg} 項</span>" if n_urg else ""

        st.markdown(f"""
<div style="background:{hdr_bg};border-left:5px solid {hdr_bc};border-radius:8px;
     padding:9px 14px;margin-bottom:6px">
  <span style="font-size:15px;font-weight:800;color:{hdr_bc}">
    🚚 {day_label}預計來料（{day_date.strftime('%m/%d')}）
  </span>
  <span style="font-size:12px;color:#64748b;margin-left:8px">{len(sub)} 項</span>
  {urg_tag}
</div>""", unsafe_allow_html=True)

        if sub.empty:
            st.markdown("<div style='color:#64748b;font-size:13px;padding:4px 14px;margin-bottom:10px'>— 無預計來料 —</div>",
                        unsafe_allow_html=True)
        else:
            for _, mr in sub.iterrows():
                is_urg_r  = bool(mr.get("急件", False))
                is_ovd    = bool(mr.get("_overdue", False))
                row_bg    = "#fff1f2" if is_ovd else ("#fff7ed" if is_urg_r else "#f8fafc")
                row_bc    = "#ef4444" if is_ovd else ("#f97316" if is_urg_r else "#e2e8f0")
                badge     = ("🔴 逾期" if is_ovd else ("🚨 急件" if is_urg_r else "🔵"))
                _dl       = mr.get("_days_late", 0)
                _dl       = 0 if (_dl is None or (isinstance(_dl, float) and pd.isna(_dl))) else int(_dl)
                ovd_note  = f" <span style='color:#dc2626;font-size:11px'>逾期 {_dl} 天</span>" if is_ovd else ""
                st.markdown(f"""
<div style="border:1px solid {row_bc};border-radius:6px;padding:7px 12px;
     margin-bottom:5px;background:{row_bg}">
  <div style="font-size:13px">
    {badge} <b>{mr['料號']}</b>
    <span style="color:#64748b;margin-left:8px">{mr['工單']} / {mr['成品料號']}</span>
    {ovd_note}
  </div>
  <div style="font-size:11px;color:#94a3b8;margin-top:2px">出貨日：{mr['出貨日']}</div>
</div>""", unsafe_allow_html=True)

# ════════════════════════════════════════════════════════════════════
# 區塊 3：急件缺料工單（兩週內）
# ════════════════════════════════════════════════════════════════════
st.markdown("<div style='margin-top:8px'></div>", unsafe_allow_html=True)
st.markdown("""
<div style="background:#7f1d1d;border-radius:10px;padding:10px 16px;margin-bottom:12px">
  <span style="color:white;font-size:16px;font-weight:800">🚨 急件缺料工單（兩週內，出貨剩 ≤10 工作天）</span>
</div>""", unsafe_allow_html=True)

both_weeks = pd.concat([ws["sub"], nws["sub"]], ignore_index=True).drop_duplicates(subset=["工單"])
urgent_lack = both_weeks[
    (both_weeks["料況狀態"] != "已齊料") & (both_weeks["急件"] == True)
].sort_values("出貨日")

if urgent_lack.empty:
    st.success("✅ 目前兩週內無急件缺料工單")
else:
    cols_per_row = 3
    rows_list = list(urgent_lack.iterrows())
    for i in range(0, len(rows_list), cols_per_row):
        chunk = rows_list[i:i+cols_per_row]
        cols  = st.columns(cols_per_row)
        for j, (_, row) in enumerate(chunk):
            with cols[j]:
                ship_d  = row["出貨日"].strftime('%m/%d') if pd.notna(row["出貨日"]) else "未定"
                wdays   = row.get("距出貨工作天")
                wday_s  = f"{int(wdays)} 工作天" if pd.notna(wdays) else "—"
                qi      = (row["預計齊料日"].strftime('%m/%d')
                           if pd.notna(row["預計齊料日"]) and hasattr(row["預計齊料日"],'strftime') else "—")
                qty     = int(row["預計產量"]) if pd.notna(row["預計產量"]) else "?"
                hint    = row.get("重點提示","") or ""
                st.markdown(f"""
<div style="border:2px solid #ef4444;border-radius:10px;padding:12px 14px;background:#fff1f2">
  <div style="font-size:15px;font-weight:800;color:#b91c1c">{row['工單']}</div>
  <div style="font-size:12px;color:#64748b;margin:2px 0">{row['成品料號']} × {qty}</div>
  <div style="margin-top:8px;font-size:13px">
    <span style="background:#fee2e2;color:#b91c1c;border-radius:4px;padding:1px 8px;font-weight:700">{row['料況狀態']}</span>
    <span style="margin-left:8px;color:#64748b">出貨 <b>{ship_d}</b>（剩 {wday_s}）</span>
  </div>
  <div style="font-size:12px;color:#475569;margin-top:5px">
    最後到料日 <b>{qi}</b>
    {"　💬 " + hint if hint else ""}
  </div>
</div>""", unsafe_allow_html=True)

st.markdown(f"""
<div style="text-align:center;color:#94a3b8;font-size:12px;margin-top:24px">
  資料來源：{src_path.replace(r"\\192.168.2.34\MO_Storage", "網路磁碟") if src_path else "—"}
  &nbsp;｜&nbsp; 下次自動更新約 {next_refresh_min} 分鐘後
</div>""", unsafe_allow_html=True)
