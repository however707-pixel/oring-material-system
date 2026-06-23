import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import math
from datetime import datetime
import io
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from utils.shared import ensure_calamine, inject_css, render_header, render_sidebar, PRIORITY_WHS
from utils.i18n import t

# =========================
# 0. 初始化
# =========================
ensure_calamine()
if "lang" not in st.session_state:
    st.session_state["lang"] = "zh"

# =========================
# 1. 頁面設定
# =========================
st.set_page_config(page_title="資材管理決策系統", page_icon="📦", layout="wide", initial_sidebar_state="expanded")
inject_css()

render_header(
    title=t("header_title"),
    subtitle=t("header_subtitle"),
    badge=t("header_badge"),
)

# =========================
# 2. 數據核心處理
# =========================
@st.cache_data
def load_and_pivot_data(file_bytes, file_name, analysis_date, end_date):
    try:
        needed_cols = ['品號', '庫別', '庫別名稱', '日期', '異動別', '異動數量', '預計結存', 'SPQ']

        if file_name.lower().endswith(('.xlsx', '.xls')):
            try:
                df = pd.read_excel(io.BytesIO(file_bytes), usecols=needed_cols, engine='calamine')
            except Exception:
                df = pd.read_excel(io.BytesIO(file_bytes), usecols=needed_cols, engine='openpyxl')
        else:
            df = None
            last_error = None
            for enc in ['utf-8-sig', 'utf-8', 'cp950', 'big5', 'gb2312']:
                try:
                    df = pd.read_csv(io.BytesIO(file_bytes), encoding=enc, usecols=needed_cols)
                    break
                except (UnicodeDecodeError, ValueError, Exception) as e:
                    last_error = e
                    continue
            if df is None:
                st.error(f"無法判斷 CSV 編碼。（錯誤：{last_error}）")
                return None, None, None

        df.columns = df.columns.str.strip()
        missing = [c for c in needed_cols if c not in df.columns]
        if missing:
            st.error(f"檔案缺少必要欄位：{missing}")
            st.write("目前偵測到的欄位：", df.columns.tolist())
            return None, None, None

        df['異動數量'] = pd.to_numeric(df['異動數量'], errors='coerce').fillna(0)
        df['預計結存'] = pd.to_numeric(df['預計結存'], errors='coerce').fillna(0)
        df['SPQ']     = pd.to_numeric(df['SPQ'],     errors='coerce').fillna(1).clip(lower=1)
        df['日期_str'] = df['日期'].astype(str).str.strip()
        df['日期_parsed'] = pd.to_datetime(df['日期'], errors='coerce')

        wh_map = (
            df[df['庫別名稱'].notna() & df['庫別'].notna()]
            .groupby('庫別')['庫別名稱']
            .first()
            .to_dict()
        )
        for v in df['庫別名稱'].dropna().unique():
            if v not in wh_map:
                wh_map[v] = v

        is_init_row = df['日期_str'] == '庫存可用量:'
        df_init = df[is_init_row & (df['庫別'].notna())].copy()
        df_init['庫別名稱_正確'] = df_init['庫別'].map(wh_map).fillna(df_init['庫別'])
        init_stock = df_init.groupby(['品號', '庫別名稱_正確'])['異動數量'].sum()
        init_stock.index.names = ['品號', '庫別名稱']

        df_move = df[df['日期_parsed'].notna() & df['庫別名稱'].notna()].copy()

        base_dt = pd.to_datetime(analysis_date)
        end_dt  = pd.to_datetime(end_date)
        in_mask = (df_move['日期_parsed'] >= base_dt) & (df_move['日期_parsed'] <= end_dt)
        df_period = df_move[in_mask].copy()

        if df_period.empty and init_stock.empty:
            st.warning("所選日期區間內沒有資料，請確認基準日與資料日期範圍是否吻合。")
            return None, None, None

        last_in_period = df_period.groupby(['品號', '庫別名稱'])['預計結存'].last()
        incoming = (
            df_period[df_period['異動別'] == '預計進貨']
            .groupby(['品號', '庫別名稱'])['異動數量']
            .sum()
        )
        before_period = df_move[df_move['日期_parsed'] < base_dt]
        last_before = before_period.groupby(['品號', '庫別名稱'])['預計結存'].last()

        real_avail = (
            last_in_period - incoming.reindex(last_in_period.index).fillna(0)
        ).combine_first(last_before).combine_first(init_stock)

        pivot_df = real_avail.unstack().fillna(0)
        spq_map = df_move.groupby('品號')['SPQ'].last()
        shortage_filter = pivot_df.lt(0).any(axis=1)
        final_pivot = pivot_df[shortage_filter].copy()

        return final_pivot, spq_map, df_period

    except Exception as e:
        st.error(f"分析失敗（未預期錯誤）：{e}")
        import traceback
        st.text(traceback.format_exc())
        return None, None, None


# =========================
# 3. 結果顯示函數
# =========================
def render_results(matrix, spq_map, analysis_date, end_date, days_range, wh_filter_mode, wh_filter_target):
    mode_filter = t("mode_filter")
    st.markdown(
        f'<div class="status-card">'
        f'<h3>{t("matrix_title")}</h3>'
        f'{t("period_label")}：<b>{analysis_date}</b> ～ <b>{end_date}</b>（{t("days_label")} <b>{days_range}</b> {t("days_unit")}）｜'
        f'{t("item_label")}：<b>{len(matrix)}</b> {t("item_unit")}｜'
        f'{t("wh_label")}：<b>{len(matrix.columns)}</b> {t("wh_unit")}'
        f'</div>',
        unsafe_allow_html=True
    )

    def style_cell(v):
        if v < 0:
            return 'background-color: #fee2e2; color: #dc2626; font-weight: bold;'
        if v > 0:
            return 'background-color: #f0fdf4; color: #16a34a;'
        return 'color: #94a3b8;'

    search_q = st.text_input(t("search_ph"), placeholder=t("search_hint"))

    display_matrix = matrix
    if wh_filter_mode == mode_filter and wh_filter_target:
        if wh_filter_target in matrix.columns:
            display_matrix = matrix[matrix[wh_filter_target] < 0]
            if display_matrix.empty:
                st.warning(f"「{wh_filter_target}」目前沒有缺料品號。")
            else:
                st.info(f"顯示在「{wh_filter_target}」缺料的品號，共 {len(display_matrix)} 個")
        else:
            st.warning(f"找不到倉別「{wh_filter_target}」。可用倉別：{', '.join(matrix.columns.tolist())}")

    if search_q:
        display_matrix = display_matrix[
            display_matrix.index.astype(str).str.contains(search_q, na=False)
        ]
        if display_matrix.empty:
            st.warning(f"找不到包含「{search_q}」的品號。")

    st.write(t("legend"))
    st.dataframe(
        display_matrix.style.map(style_cell).format("{:.0f}"),
        use_container_width=True,
        height=600
    )

    xlsx_buf = io.BytesIO()
    display_matrix.reset_index().to_excel(xlsx_buf, index=False, engine='openpyxl')
    xlsx_buf.seek(0)
    st.download_button(
        label=t("export_matrix"),
        data=xlsx_buf,
        file_name=f"transfer_matrix_{analysis_date}~{end_date}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

    st.divider()
    st.subheader(t("rec_title"))
    st.caption(t("rec_caption"))

    rec_wh_filter = (
        wh_filter_target
        if (wh_filter_mode == mode_filter and wh_filter_target and wh_filter_target in matrix.columns)
        else None
    )

    recommendations = []
    for p_no in display_matrix.index:
        row = display_matrix.loc[p_no]
        spq = max(float(spq_map.get(p_no, 1)), 1.0)
        short_whs = (
            [rec_wh_filter]
            if rec_wh_filter and rec_wh_filter in row.index and row[rec_wh_filter] < 0
            else row[row < 0].index.tolist()
        )
        stock_whs = row[row > 0].index.tolist()
        if not (short_whs and stock_whs):
            continue
        for s_wh in short_whs:
            priority_candidates = [w for w in PRIORITY_WHS if w in stock_whs]
            fallback_candidates = [w for w in stock_whs if w not in PRIORITY_WHS]
            best_source = (
                row[priority_candidates].idxmax() if priority_candidates
                else row[fallback_candidates].idxmax()
            )
            avail = float(row[best_source])
            need  = float(abs(row[s_wh]))
            ceiled = math.ceil(need / spq) * spq
            if avail >= ceiled:
                transfer_qty, feasibility = int(ceiled), t("full_cover")
            elif avail >= spq:
                transfer_qty, feasibility = int(math.floor(avail / spq) * spq), t("partial")
            else:
                transfer_qty, feasibility = int(avail), t("partial_spq")
            recommendations.append({
                t("col_pno"): p_no, t("col_spq"): int(spq),
                t("col_short_wh"): s_wh, t("col_short_qty"): int(need),
                t("col_src_wh"): best_source, t("col_src_avail"): int(avail),
                t("col_xfer_qty"): transfer_qty, t("col_feasible"): feasibility
            })

    if recommendations:
        rec_df = pd.DataFrame(recommendations)
        st.dataframe(rec_df, use_container_width=True)
        rec_buf = io.BytesIO()
        rec_df.to_excel(rec_buf, index=False, engine='openpyxl')
        rec_buf.seek(0)
        st.download_button(
            label=t("export_rec"),
            data=rec_buf,
            file_name=f"transfer_rec_{analysis_date}~{end_date}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    else:
        st.info(t("no_rec"))


# =========================
# 4. Sidebar 控制面板
# =========================
render_sidebar()

uploaded_file    = None
wh_filter_mode   = t("mode_all")
wh_filter_target = None
analysis_date    = datetime(2026, 5, 1).date()
end_date         = datetime(2026, 5, 31).date()
days_range       = (end_date - analysis_date).days + 1

# =========================
# 5. 主畫面
# =========================
if uploaded_file is not None:
    file_bytes = uploaded_file.read()
    with st.spinner(t("spinner")):
        matrix, spq_map, raw_period = load_and_pivot_data(
            file_bytes, uploaded_file.name, analysis_date, end_date
        )
    if matrix is not None and not matrix.empty:
        priority_cols = [c for c in PRIORITY_WHS if c in matrix.columns]
        other_cols    = [c for c in matrix.columns if c not in PRIORITY_WHS]
        matrix = matrix[priority_cols + other_cols]
        st.session_state["wh_columns"] = matrix.columns.tolist()
        render_results(matrix, spq_map, analysis_date, end_date, days_range, wh_filter_mode, wh_filter_target)
    elif matrix is not None and matrix.empty:
        st.success(t("no_shortage"))
else:
    _flow_html = """
<div class="arch-root"><style>
@property --angle { syntax:'<angle>'; initial-value:0deg; inherits:false; }
.arch-root *, .arch-root *::before, .arch-root *::after { box-sizing:border-box; }
.arch-root * { margin:0; padding:0; }
.arch-root { font-family:"Segoe UI","Microsoft JhengHei",Arial,sans-serif;
       color:#d6e0f0; min-width:0;
       background:
         radial-gradient(900px 480px at 18% -8%, rgba(56,189,248,.20), transparent 60%),
         radial-gradient(820px 460px at 88% 0%, rgba(99,102,241,.18), transparent 60%),
         radial-gradient(700px 520px at 50% 120%, rgba(59,130,246,.14), transparent 55%),
         linear-gradient(160deg,#0f1a30 0%,#16223d 55%,#0e1729 100%);
       padding:22px 18px 18px; position:relative; overflow:hidden; border-radius:16px; }
/* 科技格線背景（加強） */
.arch-root::before { content:""; position:absolute; inset:0; z-index:0; pointer-events:none;
  background-image:
    linear-gradient(rgba(96,165,250,.10) 1px, transparent 1px),
    linear-gradient(90deg, rgba(96,165,250,.10) 1px, transparent 1px);
  background-size:38px 38px;
  -webkit-mask-image:radial-gradient(ellipse 100% 88% at 50% 35%, #000 70%, transparent 100%);
  mask-image:radial-gradient(ellipse 100% 88% at 50% 35%, #000 70%, transparent 100%); }
.arch-root { display:block; }
.arch-root > * { position:relative; z-index:1; }

/* ══ 標題 ══ */
.arch-title { text-align:center; margin-bottom:20px; }
.arch-title h2 {
  font-size:38px; font-weight:800; letter-spacing:0.16em;
  background:linear-gradient(100deg,#7dd3fc 0%,#38bdf8 45%,#818cf8 100%);
  -webkit-background-clip:text; -webkit-text-fill-color:transparent; background-clip:text;
  filter:drop-shadow(0 0 18px rgba(56,189,248,.50)); }
.arch-title .sub { font-size:14px; color:#9fb2d4; margin-top:8px; font-weight:500;
  letter-spacing:0.20em; font-family:"Consolas","SF Mono",monospace; }
.arch-title .sep { margin:0 10px; color:#60a5fa; }
.arch-title .divider { width:110px; height:2px; margin:12px auto 0;
  background:linear-gradient(90deg,transparent,#38bdf8,#818cf8,transparent);
  box-shadow:0 0 14px rgba(56,189,248,.9); border-radius:2px; }

/* ══ 三欄主佈局 ══ */
.arch-main { display:flex; gap:12px; align-items:stretch; }

/* ══ 側欄 ══ */
.side-col { width:190px; flex-shrink:0; display:flex; flex-direction:column; gap:8px; }
.side-box { border-radius:13px; padding:13px 15px; flex:1;
            background:rgba(20,32,58,.6); border:1px solid rgba(96,165,250,.28);
            -webkit-backdrop-filter:blur(8px); backdrop-filter:blur(8px);
            box-shadow:0 4px 18px rgba(0,0,0,.4); }
.side-box .sb-title {
  font-size:15px; font-weight:800; margin-bottom:8px; color:#e8eefb;
  display:flex; align-items:center; gap:5px; }
.side-box ul { list-style:none; padding:0; }
.side-box ul li { font-size:13px; color:#a9b8d6; padding:3px 0;
  display:flex; align-items:flex-start; gap:4px; line-height:1.55; }
.side-box ul li::before { content:'▸'; font-size:10px; margin-top:3px; flex-shrink:0; color:#60a5fa; }

.who-box    { border-color:rgba(56,189,248,.35); }
.who-box    .sb-title { color:#7dd3fc; }
.who-box    ul li::before { color:#38bdf8; }
.input-box  { border-color:rgba(96,165,250,.35); }
.input-box  .sb-title { color:#93c5fd; }
.input-box  ul li::before { color:#60a5fa; }
.how-box    { border-color:rgba(129,140,248,.35); }
.how-box    .sb-title { color:#a5b4fc; }
.how-box    ul li::before { color:#818cf8; }
.with-box   { border-color:rgba(56,189,248,.35); }
.with-box   .sb-title { color:#7dd3fc; }
.with-box   ul li::before { color:#38bdf8; }
.output-box { border-color:rgba(96,165,250,.35); }
.output-box .sb-title { color:#93c5fd; }
.output-box ul li::before { color:#60a5fa; }
.kpi-box    { border-color:rgba(129,140,248,.35); }
.kpi-box    .sb-title { color:#a5b4fc; }
.kpi-box    ul li::before { color:#818cf8; }

/* ══ 中央區域 ══ */
.oval-center {
  position:relative; overflow:hidden;
  flex:1; min-width:0;
  background:linear-gradient(160deg, rgba(26,38,66,.85), rgba(17,26,48,.92));
  border:1px solid rgba(96,165,250,.30); border-radius:24px;
  padding:24px 28px 26px;
  display:flex; flex-direction:column; gap:18px;
  -webkit-backdrop-filter:blur(10px); backdrop-filter:blur(10px);
  box-shadow:0 0 0 1px rgba(56,189,248,.06),
             0 18px 50px rgba(0,0,0,.50),
             inset 0 1px 0 rgba(148,163,184,.12); }
/* 邊框跑馬燈 */
.oval-center::after { content:""; position:absolute; inset:0; border-radius:24px; padding:1.5px;
  background:conic-gradient(from var(--angle),
    transparent 0deg, transparent 200deg,
    #38bdf8 280deg, #bfe3ff 320deg, #38bdf8 345deg, transparent 360deg);
  -webkit-mask:linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0);
  -webkit-mask-composite:xor;
  mask:linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0); mask-composite:exclude;
  animation:angleRun 4s linear infinite; pointer-events:none; z-index:3; }
@keyframes angleRun { to { --angle:360deg; } }
/* 掃描線 */
.oval-center::before { content:""; position:absolute; left:8px; right:8px; top:0; height:150px;
  background:linear-gradient(180deg, transparent, rgba(96,165,250,.10) 70%, rgba(147,197,253,.20));
  pointer-events:none; z-index:4; mix-blend-mode:screen;
  animation:scanMove 4.8s linear infinite; }
@keyframes scanMove { 0%{transform:translateY(-150px);opacity:0;} 12%{opacity:1;} 88%{opacity:1;} 100%{transform:translateY(620px);opacity:0;} }
.oval-hdr,.dept-row { position:relative; z-index:2; }

/* ── 頂部 ── */
.oval-hdr { text-align:center; padding-bottom:4px; }
.oval-hdr .ov-icon { font-size:40px; display:block; margin-bottom:6px;
  filter:drop-shadow(0 0 14px rgba(56,189,248,.7)); }
.oval-hdr .ov-title {
  font-size:28px; font-weight:800; letter-spacing:0.12em;
  background:linear-gradient(100deg,#7dd3fc,#38bdf8,#93c5fd);
  -webkit-background-clip:text; -webkit-text-fill-color:transparent; background-clip:text;
  filter:drop-shadow(0 0 12px rgba(56,189,248,.45)); }

/* ── 三部門卡片 ── */
.dept-row { display:flex; gap:12px; align-items:stretch; }
.dept-sep { display:flex; align-items:center; justify-content:center;
  font-size:24px; color:#60a5fa; flex-shrink:0; width:24px;
  font-weight:900; text-shadow:0 0 14px rgba(96,165,250,.95);
  animation:flowPulse 2.4s ease-in-out infinite; }
@keyframes flowPulse { 0%,100%{opacity:.35;transform:translateX(0);} 50%{opacity:1;transform:translateX(3px);} }
.dept { flex:1; min-width:160px; border-radius:14px; overflow:hidden;
  display:flex; flex-direction:column;
  background:rgba(15,24,46,.6); border:1px solid rgba(148,163,184,.14);
  box-shadow:0 8px 24px rgba(0,0,0,.40); transition:transform .2s, box-shadow .2s; }
.dept:hover { transform:translateY(-3px); }
.dept .dhdr { padding:16px 10px 13px; text-align:center; color:#f1f5f9; }
.dept .dhdr .di { font-size:30px; display:block; margin-bottom:5px;
  filter:drop-shadow(0 0 9px currentColor); }
.dept .dhdr .dn { font-size:20px; font-weight:800; letter-spacing:0.05em; white-space:nowrap; }
.dept .dhdr .ds { font-size:11.5px; opacity:.85; margin-top:3px; white-space:nowrap;
  letter-spacing:0.12em; font-family:"Consolas",monospace; }
.dept-pc .dhdr { background:linear-gradient(160deg,#0c4a6e,#0369a1,#0ea5e9); }
.dept-mc .dhdr { background:linear-gradient(160deg,#1e3a8a,#1d4ed8,#3b82f6); }
.dept-wh .dhdr { background:linear-gradient(160deg,#312e81,#4338ca,#6366f1); }
.dept-pc { box-shadow:0 8px 24px rgba(0,0,0,.40), inset 0 0 0 1px rgba(56,189,248,.20); }
.dept-mc { box-shadow:0 8px 24px rgba(0,0,0,.40), inset 0 0 0 1px rgba(96,165,250,.20); }
.dept-wh { box-shadow:0 8px 24px rgba(0,0,0,.40), inset 0 0 0 1px rgba(129,140,248,.20); }
.dept-pc:hover { box-shadow:0 12px 30px rgba(0,0,0,.5), 0 0 24px rgba(56,189,248,.40); }
.dept-mc:hover { box-shadow:0 12px 30px rgba(0,0,0,.5), 0 0 24px rgba(96,165,250,.40); }
.dept-wh:hover { box-shadow:0 12px 30px rgba(0,0,0,.5), 0 0 24px rgba(129,140,248,.40); }
.dept .dbody { flex:1; padding:13px 13px 14px; display:flex; flex-direction:column; gap:6px;
  background:linear-gradient(180deg, rgba(20,32,58,.5), rgba(13,20,40,.7)); }
.ti { font-size:14.5px; color:#d6e0f0; padding:5px 7px; border-radius:6px;
  display:flex; align-items:center; gap:7px; line-height:1.5; font-weight:500;
  border-left:2px solid transparent; transition:background .15s; }
.ti:hover { background:rgba(148,163,184,.07); }
.ti::before { content:'✓'; font-weight:900; font-size:13px; flex-shrink:0;
  filter:drop-shadow(0 0 5px currentColor); }
.dept-pc .ti { border-left-color:rgba(56,189,248,.45); }
.dept-mc .ti { border-left-color:rgba(96,165,250,.45); }
.dept-wh .ti { border-left-color:rgba(129,140,248,.45); }
.dept-pc .ti::before { color:#38bdf8; }
.dept-mc .ti::before { color:#60a5fa; }
.dept-wh .ti::before { color:#818cf8; }
/* 可點擊的流程項目（保持 ✓ 樣式，但變成連結） */
a.ti { color:#d6e0f0; text-decoration:none; cursor:pointer; }
a.ti:hover { background:rgba(96,165,250,.14); box-shadow:0 0 12px rgba(96,165,250,.22);
  transform:translateX(2px); }
a.tl { font-size:14px; padding:7px 10px; border-radius:8px; font-weight:700;
  display:flex; align-items:center; gap:7px; text-decoration:none;
  transition:all .18s; line-height:1.4; margin-top:2px; }
a.tl:hover { transform:translateX(3px); }
a.tl::before { content:'▶'; font-size:9px; flex-shrink:0; }
.dept-pc a.tl { color:#bae6fd; background:rgba(56,189,248,.10); border:1px solid rgba(56,189,248,.45); }
.dept-pc a.tl:hover { box-shadow:0 0 16px rgba(56,189,248,.50); background:rgba(56,189,248,.20); }
.dept-pc a.tl::before { color:#38bdf8; }
.dept-mc a.tl { color:#bfdbfe; background:rgba(96,165,250,.10); border:1px solid rgba(96,165,250,.45); }
.dept-mc a.tl:hover { box-shadow:0 0 16px rgba(96,165,250,.50); background:rgba(96,165,250,.20); }
.dept-mc a.tl::before { color:#60a5fa; }
.dept-wh a.tl { color:#c7d2fe; background:rgba(129,140,248,.10); border:1px solid rgba(129,140,248,.45); }
.dept-wh a.tl:hover { box-shadow:0 0 16px rgba(129,140,248,.50); background:rgba(129,140,248,.20); }
.dept-wh a.tl::before { color:#818cf8; }

.oval-hdr .ov-flow {
  display:inline-block; margin-top:12px; font-size:13.5px; font-weight:600;
  color:#bae6fd; background:rgba(56,189,248,.08);
  border:1px solid rgba(56,189,248,.38); border-radius:20px; padding:7px 22px;
  letter-spacing:0.04em; box-shadow:inset 0 0 18px rgba(56,189,248,.18); }

/* ══ 底部標語 ══ */
.arch-tagline {
  margin-top:18px; text-align:center; padding:16px 28px;
  background:linear-gradient(135deg, rgba(8,47,73,.85), rgba(30,58,138,.88), rgba(49,46,129,.85));
  border:1px solid rgba(96,165,250,.32); border-radius:14px;
  color:#eaf1ff; font-size:16.5px; font-weight:700; letter-spacing:0.18em;
  box-shadow:0 0 30px rgba(56,189,248,.18), inset 0 1px 0 rgba(148,163,184,.12); }

/* ══ 上傳提示 ══ */
.upload-hint {
  margin-top:12px; text-align:center; padding:13px 20px;
  background:rgba(20,32,58,.5); border:1px dashed rgba(96,165,250,.45);
  border-radius:12px; font-size:14px; color:#a9b8d6; font-weight:500;
  letter-spacing:0.03em; }
</style>

<div class="arch-title">
  <h2>物料作業流程管理架構</h2>
  <div class="sub">Material Flow Management Architecture
    <span class="sep">|</span> PC 生管 &times; MC 物管 &times; WH 倉管</div>
  <div class="divider"></div>
</div>

<div class="arch-main">

  <!-- ══ 中央橢圓 ══ -->
  <div class="oval-center">
    <div class="oval-hdr">
      <span class="ov-icon"><svg width="78" height="78" viewBox="0 0 100 100" fill="none" xmlns="http://www.w3.org/2000/svg">
        <defs>
          <radialGradient id="coreOrb" cx="38%" cy="32%" r="78%">
            <stop offset="0%" stop-color="#e2f6ff"/>
            <stop offset="32%" stop-color="#5cc6f5"/>
            <stop offset="72%" stop-color="#2563eb"/>
            <stop offset="100%" stop-color="#16235e"/>
          </radialGradient>
          <linearGradient id="coreRing" x1="0" y1="0" x2="100" y2="100" gradientUnits="userSpaceOnUse">
            <stop offset="0%" stop-color="#7dd3fc"/>
            <stop offset="50%" stop-color="#38bdf8"/>
            <stop offset="100%" stop-color="#818cf8"/>
          </linearGradient>
          <radialGradient id="coreAmb" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stop-color="#38bdf8" stop-opacity="0.55"/>
            <stop offset="100%" stop-color="#38bdf8" stop-opacity="0"/>
          </radialGradient>
          <filter id="coreGlow" x="-60%" y="-60%" width="220%" height="220%">
            <feGaussianBlur stdDeviation="1.5" result="b"/>
            <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
          </filter>
        </defs>
        <circle cx="50" cy="50" r="44" fill="url(#coreAmb)"/>
        <g filter="url(#coreGlow)">
          <g>
            <ellipse cx="50" cy="50" rx="41" ry="15" stroke="url(#coreRing)" stroke-width="2.2" opacity="0.9"/>
            <ellipse cx="50" cy="50" rx="41" ry="15" stroke="url(#coreRing)" stroke-width="2.2" opacity="0.75" transform="rotate(60 50 50)"/>
            <ellipse cx="50" cy="50" rx="41" ry="15" stroke="url(#coreRing)" stroke-width="2.2" opacity="0.75" transform="rotate(120 50 50)"/>
            <animateTransform attributeName="transform" type="rotate" from="0 50 50" to="360 50 50" dur="16s" repeatCount="indefinite"/>
          </g>
        </g>
        <g>
          <circle cx="91" cy="50" r="3.4" fill="#7dd3fc"/>
          <circle cx="9" cy="50" r="2.6" fill="#a5b4fc"/>
          <animateTransform attributeName="transform" type="rotate" from="0 50 50" to="360 50 50" dur="9s" repeatCount="indefinite"/>
        </g>
        <circle cx="50" cy="50" r="15.5" fill="url(#coreOrb)"/>
        <circle cx="50" cy="50" r="15.5" fill="none" stroke="#bfe3ff" stroke-width="0.8" opacity="0.65"/>
        <ellipse cx="45" cy="44" rx="6" ry="4" fill="#ffffff" opacity="0.5"/>
      </svg></span>
      <div class="ov-flow">物料需求 &rarr; 採購/調撥 &rarr; 入庫/IQC &rarr; 備料/領料 &rarr; 出貨/成本回報</div>
    </div>

    <!-- 三部門卡片 -->
    <div class="dept-row">
      <div class="dept dept-pc">
        <div class="dhdr">
          <span class="di">📊</span>
          <div class="dn">生管 PC</div>
          <div class="ds">Production Control</div>
        </div>
        <div class="dbody">
          <a href="/monthly_cost" target="_self" class="tl">每月成本計算表</a>
          <a href="/kanban"       target="_self" class="tl">工單進度看板</a>
          <a href="/scheduling"   target="_self" class="tl">排程系統</a>
          <a href="/outsource_schedule" target="_self" class="tl">委外工單排程</a>
          <a href="/loss_rate"    target="_self" class="tl">耗損率分析</a>
        </div>
      </div>
      <div class="dept-sep">&rarr;</div>
      <div class="dept dept-mc">
        <div class="dhdr">
          <span class="di">📦</span>
          <div class="dn">物管 MC</div>
          <div class="ds">Material Control</div>
        </div>
        <div class="dbody">
          <a href="/h2o"     target="_self" class="tl">唐佑配料表</a>
          <a href="/guozhi"  target="_self" class="tl">國智配料表</a>
          <a href="/factory" target="_self" class="tl">廠內配料表</a>
        </div>
      </div>
      <div class="dept-sep">&rarr;</div>
      <div class="dept dept-wh">
        <div class="dhdr">
          <span class="di">🏬</span>
          <div class="dn">倉管 WH</div>
          <div class="ds">Warehouse Management</div>
        </div>
        <div class="dbody">
          <a href="/daily_inbound" target="_self" class="tl">每日入庫筆數</a>
          <a href="/daily_picking" target="_self" class="tl">每日備料筆數</a>
          <a href="/wh_staff"      target="_self" class="tl">倉儲人員編製</a>
          <a href="/wh_dashboard"  target="_self" class="tl">倉儲備料看板</a>
        </div>
      </div>
    </div>
  </div>


</div>

<div class="arch-tagline">🛡&nbsp;&nbsp; 精準協同 &nbsp;·&nbsp; 流程透明 &nbsp;·&nbsp; 數據驅動 &nbsp;·&nbsp; 持續改善</div>
<div class="upload-hint">__UPLOAD_HINT__</div>
</div>
"""
    st.markdown(
        "\n".join(
            _l for _l in
            _flow_html.replace("__UPLOAD_HINT__", t("upload_hint")).splitlines()
            if _l.strip()
        ),
        unsafe_allow_html=True,
    )
