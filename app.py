import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import math
from datetime import datetime
import base64
import io
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from utils.shared import ensure_calamine, inject_css, render_header, render_sidebar, PRIORITY_WHS, _logo_b64
from utils.i18n import t

# 開場動畫人物（去背 PNG 切成 頭/身體/手臂 三層紙偶，boy_character.png 為完整原圖備用）
_BOY_PARTS_DIR = os.path.join(os.path.dirname(__file__), "utils")

def _boy_part_b64(fname: str) -> str:
    p = os.path.join(_BOY_PARTS_DIR, fname)
    if os.path.exists(p):
        with open(p, "rb") as _f:
            return base64.b64encode(_f.read()).decode()
    return ""

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
.dept-pmc .dhdr { background:linear-gradient(160deg,#78350f,#b45309,#f59e0b); }
.dept-pc .dhdr { background:linear-gradient(160deg,#0c4a6e,#0369a1,#0ea5e9); }
.dept-mc .dhdr { background:linear-gradient(160deg,#1e3a8a,#1d4ed8,#3b82f6); }
.dept-wh .dhdr { background:linear-gradient(160deg,#312e81,#4338ca,#6366f1); }
.dept-ps .dhdr { background:linear-gradient(160deg,#115e59,#0f766e,#14b8a6); }
.dept-pmc { box-shadow:0 8px 24px rgba(0,0,0,.40), inset 0 0 0 1px rgba(245,158,11,.20); }
.dept-pc { box-shadow:0 8px 24px rgba(0,0,0,.40), inset 0 0 0 1px rgba(56,189,248,.20); }
.dept-mc { box-shadow:0 8px 24px rgba(0,0,0,.40), inset 0 0 0 1px rgba(96,165,250,.20); }
.dept-wh { box-shadow:0 8px 24px rgba(0,0,0,.40), inset 0 0 0 1px rgba(129,140,248,.20); }
.dept-ps { box-shadow:0 8px 24px rgba(0,0,0,.40), inset 0 0 0 1px rgba(45,212,191,.20); }
.dept-pmc:hover { box-shadow:0 12px 30px rgba(0,0,0,.5), 0 0 24px rgba(245,158,11,.40); }
.dept-pc:hover { box-shadow:0 12px 30px rgba(0,0,0,.5), 0 0 24px rgba(56,189,248,.40); }
.dept-mc:hover { box-shadow:0 12px 30px rgba(0,0,0,.5), 0 0 24px rgba(96,165,250,.40); }
.dept-wh:hover { box-shadow:0 12px 30px rgba(0,0,0,.5), 0 0 24px rgba(129,140,248,.40); }
.dept-ps:hover { box-shadow:0 12px 30px rgba(0,0,0,.5), 0 0 24px rgba(45,212,191,.40); }
.dept .dbody { flex:1; padding:13px 13px 14px; display:flex; flex-direction:column; gap:6px;
  background:linear-gradient(180deg, rgba(20,32,58,.5), rgba(13,20,40,.7)); }
.ti { font-size:14.5px; color:#d6e0f0; padding:5px 7px; border-radius:6px;
  display:flex; align-items:center; gap:7px; line-height:1.5; font-weight:500;
  border-left:2px solid transparent; transition:background .15s; }
.ti:hover { background:rgba(148,163,184,.07); }
.ti::before { content:'✓'; font-weight:900; font-size:13px; flex-shrink:0;
  filter:drop-shadow(0 0 5px currentColor); }
.dept-pmc .ti { border-left-color:rgba(245,158,11,.45); }
.dept-pc .ti { border-left-color:rgba(56,189,248,.45); }
.dept-mc .ti { border-left-color:rgba(96,165,250,.45); }
.dept-wh .ti { border-left-color:rgba(129,140,248,.45); }
.dept-ps .ti { border-left-color:rgba(45,212,191,.45); }
.dept-pmc .ti::before { color:#f59e0b; }
.dept-pc .ti::before { color:#38bdf8; }
.dept-mc .ti::before { color:#60a5fa; }
.dept-wh .ti::before { color:#818cf8; }
.dept-ps .ti::before { color:#2dd4bf; }
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
.dept-ps a.tl { color:#99f6e4; background:rgba(45,212,191,.10); border:1px solid rgba(45,212,191,.45); cursor:pointer; }
.dept-ps a.tl:hover { box-shadow:0 0 16px rgba(45,212,191,.50); background:rgba(45,212,191,.20); }
.dept-ps a.tl::before { color:#2dd4bf; }
.dept-pmc a.tl { color:#fde68a; background:rgba(245,158,11,.10); border:1px solid rgba(245,158,11,.45); }
.dept-pmc a.tl:hover { box-shadow:0 0 16px rgba(245,158,11,.50); background:rgba(245,158,11,.20); }
.dept-pmc a.tl::before { color:#f59e0b; }

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

/* ══ 開場動畫（兩幕）：
   第一幕 0~5.6s  中央亮色傳送門 → 人物探頭 → 跳出歡呼（仿任意門登場，深色 AI 背景故圈圈用亮色系）
   第二幕 3.2s 起 無人機空投（由右至左，5 枚載出 5 個主題，整體較原版延後 3.05s） ══ */
.intro-sky { position:absolute; inset:0; z-index:6; pointer-events:none; overflow:hidden; }
/* 飛行層：蓋在整個畫面最上層，中上方由右至左飛越 */
.intro-fly { position:absolute; inset:0; z-index:8; pointer-events:none; overflow:hidden; }
.intro-fly .drone { position:absolute; top:0; left:-520px; width:22%; min-width:330px; max-width:440px;
  will-change:left,top; animation:droneFly 9.3s linear 3.2s both; }
/* 航線：先沿底部由左飛到右出畫面，再從中上方由右至左折返轟炸 */
@keyframes droneFly {
  0%   { left:-520px; top:calc(100% - 330px); }
  35%  { left:calc(100% + 140px); top:calc(100% - 330px); }
  38%  { left:calc(100% + 140px); top:0; }
  100% { left:-520px; top:0; } }
/* 去程面向右（鏡像），折返時在畫面外轉向 */
.intro-fly .drone-flip { animation:droneFlip 9.3s linear 3.2s both; }
@keyframes droneFlip {
  0%, 36.2% { transform:scaleX(-1); }
  37%, 100% { transform:scaleX(1); } }
/* LOGO 與機身編號反向補正，鏡像時不變成反字 */
.intro-fly .logo-keep { transform-box:fill-box; transform-origin:center; animation:droneFlip 9.3s linear 3.2s both; }
.intro-fly .drone-inner { position:relative; animation:droneBob 1.5s ease-in-out infinite alternate; }
.intro-fly .drone svg { display:block; width:100%; height:auto;
  filter:drop-shadow(0 26px 38px rgba(2,8,20,.6)); }
@keyframes droneBob { from { transform:translateY(0) rotate(.6deg); } to { transform:translateY(7px) rotate(-.9deg); } }
/* 機尾速度線（尾流） */
.intro-fly .jet, .intro-fly .jet::before, .intro-fly .jet::after { content:""; position:absolute; height:3px;
  border-radius:3px; background:linear-gradient(90deg, rgba(147,232,255,.95), rgba(147,232,255,0)); }
.intro-fly .jet { right:-118px; top:46%; width:110px; animation:jetFlicker .3s linear infinite; }
.intro-fly .jet::before { left:14px; top:-20px; width:74px; }
.intro-fly .jet::after { left:22px; top:20px; width:64px; }
@keyframes jetFlicker { 0%,100% { opacity:.95; } 50% { opacity:.3; } }
.intro-sky .strike { position:absolute; top:64px; width:0; }
.intro-sky .bomb { position:absolute; left:-11px; top:0; width:22px; opacity:0;
  animation:bombDrop .5s cubic-bezier(.5,.05,.85,.5) var(--d) backwards; }
.intro-sky .bomb svg { display:block; width:100%; height:auto; }
.intro-sky .bomb::before { content:""; position:absolute; left:50%; top:-26px; width:2px; height:24px;
  transform:translateX(-50%); border-radius:2px;
  background:linear-gradient(180deg, transparent, rgba(103,232,249,.9)); }
@keyframes bombDrop {
  0% { transform:translateY(0) rotate(-8deg); opacity:0; }
  12% { opacity:1; }
  100% { transform:translateY(132px) rotate(6deg); opacity:1; } }
.intro-sky .tgt { position:absolute; left:-19px; top:150px; width:38px; height:38px; border-radius:50%;
  border:1.6px dashed rgba(125,211,252,.95); opacity:0;
  box-shadow:0 0 14px rgba(56,189,248,.55), inset 0 0 10px rgba(56,189,248,.30);
  animation:tgtLock .8s linear calc(var(--d) - .28s) backwards; }
@keyframes tgtLock {
  0% { opacity:0; transform:scale(1.9) rotate(0deg); }
  25% { opacity:.95; transform:scale(1) rotate(45deg); }
  85% { opacity:.95; transform:scale(1) rotate(150deg); }
  100% { opacity:0; transform:scale(.75) rotate(180deg); } }
.intro-sky .boom-fl, .intro-sky .boom-r1, .intro-sky .boom-r2, .intro-sky .boom-sp {
  position:absolute; border-radius:50%; opacity:0; }
.intro-sky .boom-fl { left:-45px; top:124px; width:90px; height:90px;
  background:radial-gradient(circle, #ffffff 0%, rgba(125,211,252,.95) 28%, rgba(56,189,248,.45) 55%, transparent 72%);
  animation:boomFlash .5s ease-out calc(var(--d) + .48s) backwards; }
@keyframes boomFlash {
  0% { opacity:0; transform:scale(.15); }
  12% { opacity:1; transform:scale(.55); }
  100% { opacity:0; transform:scale(1.7); } }
.intro-sky .boom-r1 { left:-40px; top:129px; width:80px; height:80px; border:2.5px solid #7dd3fc;
  box-shadow:0 0 20px rgba(56,189,248,.9), inset 0 0 12px rgba(56,189,248,.5);
  animation:boomRing .6s cubic-bezier(.2,.7,.3,1) calc(var(--d) + .5s) backwards; }
.intro-sky .boom-r2 { left:-40px; top:129px; width:80px; height:80px; border:2px solid #d8b4fe;
  animation:boomRing .68s cubic-bezier(.2,.7,.3,1) calc(var(--d) + .58s) backwards; }
@keyframes boomRing {
  0% { opacity:0; transform:scale(.15); }
  15% { opacity:1; }
  100% { opacity:0; transform:scale(2.3); } }
.intro-sky .boom-sp { left:-36px; top:133px; width:72px; height:72px;
  border:3px dotted rgba(186,230,253,.95);
  animation:boomSpark .7s ease-out calc(var(--d) + .5s) backwards; }
@keyframes boomSpark {
  0% { opacity:0; transform:scale(.25) rotate(0deg); }
  15% { opacity:1; }
  100% { opacity:0; transform:scale(2.8) rotate(65deg); } }
/* ══ 第一幕：傳送門 ＋ 人物 ══ */
.intro-portal { position:absolute; inset:0; z-index:7; pointer-events:none;
  display:flex; align-items:center; justify-content:center;
  animation:portalStageOut .4s ease-in 5.55s forwards,
            stagePush 5.3s cubic-bezier(.3,.6,.4,1) .25s both; }
@keyframes portalStageOut { from { opacity:1; } to { opacity:0; visibility:hidden; } }
/* 鏡頭語言：整幕緩慢推鏡 + 電影暗角 */
@keyframes stagePush { from { transform:scale(1); } to { transform:scale(1.05); } }
.intro-portal::before { content:""; position:absolute; inset:0; pointer-events:none;
  background:radial-gradient(ellipse at 50% 46%, transparent 52%, rgba(3,7,16,.46) 100%); }
.pt-stage { position:relative; width:360px; height:470px;
  animation:stageShake .3s linear 3.08s; }
/* 著地震動（衝擊感） */
@keyframes stageShake { 0%,100% { transform:translate(0,0); } 30% { transform:translate(2.5px,3.5px); }
  55% { transform:translate(-2.5px,-2.5px); } 80% { transform:translate(1.5px,2px); } }
/* 傳送門圓環：原片圈內是黑洞，深色背景下改為亮色雙層霓虹圈＋亮色能量霧 */
.pt-ring { position:absolute; left:50%; top:158px; width:264px; height:264px;
  transform:translate(-50%,-50%); border-radius:50%;
  animation:portalIn .65s cubic-bezier(.2,1.3,.4,1) .25s both,
            ringCharge .3s ease-in 2.15s,
            portalOut .55s cubic-bezier(.6,0,.8,.4) 4.75s forwards; }
/* 人物躍出前的蓄能閃光 */
@keyframes ringCharge {
  0% { transform:translate(-50%,-50%) scale(1); filter:brightness(1); }
  55% { transform:translate(-50%,-50%) scale(1.06); filter:brightness(2.1); }
  100% { transform:translate(-50%,-50%) scale(1); filter:brightness(1); } }
@keyframes portalIn {
  0% { transform:translate(-50%,-50%) scale(.06); opacity:0; filter:brightness(3); }
  60% { opacity:1; }
  78% { transform:translate(-50%,-50%) scale(1.07); }
  100% { transform:translate(-50%,-50%) scale(1); opacity:1; filter:brightness(1); } }
@keyframes portalOut {
  0% { transform:translate(-50%,-50%) scale(1); opacity:1; }
  35% { transform:translate(-50%,-50%) scale(1.12); filter:brightness(2.2); }
  100% { transform:translate(-50%,-50%) scale(.05); opacity:0; } }
.pt-ring i { position:absolute; border-radius:50%; }
/* 外圈：青→白→粉紫 旋轉霓虹 */
.pt-r1 { inset:0; padding:7px;
  background:conic-gradient(from var(--angle), #22d3ee 0deg, #a5f3fc 70deg, #ffffff 105deg,
    #f0abfc 170deg, #c084fc 230deg, #38bdf8 300deg, #22d3ee 360deg);
  -webkit-mask:linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0);
  -webkit-mask-composite:xor;
  mask:linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0); mask-composite:exclude;
  animation:angleRun 2.4s linear infinite;
  filter:drop-shadow(0 0 16px rgba(103,232,249,.9)) drop-shadow(0 0 44px rgba(192,132,252,.55)); }
/* 內圈：反向細光絲 */
.pt-r2 { inset:14px; padding:3.5px; opacity:.95;
  background:conic-gradient(from var(--angle), rgba(240,171,252,0) 0deg, #f0abfc 60deg, #ffffff 90deg,
    rgba(125,211,252,0) 150deg, #7dd3fc 250deg, rgba(255,255,255,0) 330deg);
  -webkit-mask:linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0);
  -webkit-mask-composite:xor;
  mask:linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0); mask-composite:exclude;
  animation:angleRun 1.7s linear infinite reverse; }
/* 粒子點環 */
.pt-r3 { inset:-14px; border:3px dotted rgba(255,255,255,.85); opacity:.8;
  box-shadow:0 0 18px rgba(165,243,252,.5); animation:ptSpin 8s linear infinite; }
@keyframes ptSpin { to { transform:rotate(360deg); } }
/* 圈內亮色能量霧 */
.pt-core { inset:16px;
  background:radial-gradient(circle at 50% 42%, rgba(224,242,254,.5) 0%, rgba(125,211,252,.30) 34%,
    rgba(139,92,246,.20) 62%, rgba(15,26,48,0) 78%);
  animation:corePulse 1.6s ease-in-out infinite alternate; }
@keyframes corePulse { from { opacity:.75; } to { opacity:1; } }
/* 圈內能量漩渦（反向旋轉的青紫光絲） */
.pt-swirl { inset:16px; opacity:.8; filter:blur(2px);
  background:conic-gradient(from var(--angle), rgba(125,211,252,.30) 0deg, transparent 90deg,
    rgba(192,132,252,.25) 160deg, transparent 240deg, rgba(165,243,252,.28) 320deg, transparent 360deg);
  animation:angleRun 3.6s linear infinite reverse; }
/* 傳送門放射光芒（緩轉的體積光束） */
.pt-rays { position:absolute; left:50%; top:158px; width:520px; height:520px; margin:-260px 0 0 -260px;
  border-radius:50%; pointer-events:none; opacity:0;
  background:conic-gradient(from 0deg,
    transparent 0deg, rgba(125,211,252,.14) 8deg, transparent 22deg,
    transparent 60deg, rgba(192,132,252,.12) 70deg, transparent 84deg,
    transparent 130deg, rgba(125,211,252,.16) 142deg, transparent 158deg,
    transparent 200deg, rgba(165,243,252,.12) 212deg, transparent 228deg,
    transparent 268deg, rgba(192,132,252,.14) 280deg, transparent 296deg,
    transparent 336deg, rgba(125,211,252,.12) 348deg, transparent 360deg);
  -webkit-mask-image:radial-gradient(circle, transparent 22%, #000 34%, transparent 72%);
  mask-image:radial-gradient(circle, transparent 22%, #000 34%, transparent 72%);
  animation:raysIn .8s ease-out .45s both, raysSpin 14s linear .45s infinite, raysOut .5s ease-in 4.75s forwards; }
@keyframes raysIn { from { opacity:0; } to { opacity:1; } }
@keyframes raysSpin { from { transform:rotate(0deg); } to { transform:rotate(360deg); } }
@keyframes raysOut { to { opacity:0; } }
/* 探頭：裁在圓環內，由下往上冒出來左右張望 */
/* （用 margin 置中，縮放 keyframes 不可帶 translate，否則會偏移） */
.pt-clip { position:absolute; left:50%; top:158px; width:236px; height:236px;
  margin:-118px 0 0 -118px; border-radius:50%; overflow:hidden;
  animation:clipIn .65s cubic-bezier(.2,1.3,.4,1) .25s both,
            clipOut .55s cubic-bezier(.6,0,.8,.4) 4.75s forwards; }
@keyframes clipIn {
  0% { transform:scale(.06); opacity:0; }
  60% { opacity:1; }
  78% { transform:scale(1.07); }
  100% { transform:scale(1); opacity:1; } }
@keyframes clipOut {
  0% { transform:scale(1); opacity:1; }
  35% { transform:scale(1.12); }
  100% { transform:scale(.05); opacity:0; } }
.boy-peek { position:absolute; left:50%; bottom:-8px; width:170px; margin-left:-85px;
  animation:peekRise .8s cubic-bezier(.25,1.2,.4,1) 1.15s both, peekHide .22s ease-in 2.3s forwards; }
@keyframes peekRise { from { transform:translateY(392px); } to { transform:translateY(164px); } }
@keyframes peekHide { to { opacity:0; transform:translateY(200px); } }
.boy-peek .bp-sway { transform-origin:50% 92%; animation:peekSway 1.15s ease-in-out 1.6s infinite alternate; }
@keyframes peekSway { from { transform:rotate(-2.8deg) translateY(3px); } to { transform:rotate(2.8deg) translateY(-5px); } }
/* 三層紙偶：身體為基準，頭與手臂絕對疊放、各自繞關節擺動（如同無人機的部件動畫）
   rig 整體掛「降飽和調色＋青紫霓虹環境光」，讓角色吃到場景光、融入深色 AI 背景 */
.boy-rig { position:relative;
  filter:saturate(.93) brightness(.97)
         drop-shadow(-7px 2px 14px rgba(56,189,248,.42))
         drop-shadow(7px 2px 14px rgba(168,85,247,.34)); }
.boy-rig img { display:block; width:100%; height:auto; }
.boy-rig .b-head, .boy-rig .b-arm { position:absolute; left:0; top:0; }
.boy-rig .b-body { transform-origin:50% 72%; animation:bodyBreath 1.7s ease-in-out infinite alternate; }
.boy-rig .b-head { transform-origin:52.5% 38.4%; animation:headTilt 1.4s ease-in-out infinite alternate; }
.boy-rig .b-arm { transform-origin:42% 48.7%; animation:armWave .5s ease-in-out infinite alternate; }
.boy-jump .b-arm { animation-duration:.42s; }
@keyframes bodyBreath { from { transform:scaleY(1); } to { transform:scaleY(1.014); } }
@keyframes headTilt { from { transform:rotate(-3.2deg); } to { transform:rotate(2.6deg); } }
@keyframes armWave { from { transform:rotate(-9deg); } to { transform:rotate(8deg); } }
/* 跳出：躍出圈外劃出拋物線 → 著地擠壓回彈（squash & stretch）→ 歡呼 → 蹲身上躍退場 */
.boy-jump { position:absolute; left:50%; top:80px; width:180px; margin-left:-90px; opacity:0;
  transform-origin:50% 97%; perspective:700px;
  filter:drop-shadow(0 16px 22px rgba(2,8,20,.6));
  animation:boyJump 1.05s linear 2.35s both,
            boyExit .6s cubic-bezier(.55,-.25,.85,.5) 4.95s forwards; }
/* 全息地板倒影（僅落地後的主角色，探頭不套用） */
.boy-jump .boy-rig { -webkit-box-reflect:below 3px linear-gradient(transparent 62%, rgba(0,0,0,.20)); }
/* 出場物質化：數位閃爍＋青粉色差殘影 */
@keyframes bjGlitch {
  0% { opacity:.4; filter:drop-shadow(3px 0 0 rgba(34,211,238,.8)) drop-shadow(-3px 0 0 rgba(244,114,182,.6)) brightness(1.7); }
  50% { opacity:1; filter:drop-shadow(2px 0 0 rgba(34,211,238,.5)) drop-shadow(-2px 0 0 rgba(244,114,182,.4)) brightness(1.25); }
  100% { opacity:1; filter:none; } }
/* 全息掃描光帶：materialize 時由腳掃到頭 */
.scan-bar { position:absolute; left:6%; width:88%; top:0; height:30px; border-radius:50%;
  pointer-events:none; opacity:0; z-index:3;
  background:linear-gradient(180deg, transparent, rgba(165,243,252,.75) 45%, rgba(255,255,255,.9) 50%,
    rgba(165,243,252,.75) 55%, transparent);
  filter:blur(1px) drop-shadow(0 0 12px rgba(125,211,252,.9));
  animation:scanUp .55s cubic-bezier(.3,.2,.4,1) 2.4s backwards; }
@keyframes scanUp {
  0% { opacity:0; transform:translateY(400px) scaleX(.6); }
  15% { opacity:1; }
  85% { opacity:.9; }
  100% { opacity:0; transform:translateY(-8px) scaleX(1); } }
@keyframes boyJump {
  0%  { opacity:0; transform:translateY(-64px) scale(.42) rotate(1deg); }
  10% { opacity:1; }
  34% { transform:translateY(-88px) scale(.86) rotate(3deg); }
  62% { transform:translateY(34px) scale(1) rotate(-1.5deg); }
  70% { transform:translateY(30px) scaleX(1.09) scaleY(.88) rotate(0deg); }
  81% { transform:translateY(20px) scaleX(.96) scaleY(1.05); }
  90% { transform:translateY(30px) scaleX(1.03) scaleY(.985); }
  100% { opacity:1; transform:translateY(30px) scale(1); } }
@keyframes boyExit {
  0% { opacity:1; transform:translateY(30px) scale(1); }
  30% { opacity:1; transform:translateY(38px) scaleX(1.05) scaleY(.94); }
  100% { opacity:0; transform:translateY(-78px) scale(1.12) rotate(-3deg); } }
.boy-jump .bj-cheer { transform-origin:50% 84%;
  animation:bjGlitch .32s steps(3,end) 2.35s backwards,
            boyCheer .7s ease-in-out 3.5s 2 alternate; }
/* 歡呼帶輕微 3D 側轉（配合外層 perspective 產生立體感） */
@keyframes boyCheer { from { transform:rotate(-4deg) rotateY(-6deg) translateY(0) scale(1); }
  to { transform:rotate(3.5deg) rotateY(5deg) translateY(-13px) scale(1.015); } }
/* 著地光圈：全息平台，把角色「放」在場景地面上 */
.land-pad { position:absolute; left:50%; top:512px; width:216px; height:50px; margin-left:-108px;
  border-radius:50%; opacity:0; pointer-events:none;
  background:radial-gradient(ellipse at center, rgba(125,211,252,.42) 0%, rgba(56,189,248,.18) 45%, transparent 70%);
  border:1.5px solid rgba(165,243,252,.5);
  box-shadow:0 0 26px rgba(56,189,248,.4), inset 0 0 18px rgba(56,189,248,.3);
  animation:padIn .45s cubic-bezier(.2,1.3,.4,1) 3.05s both,
            padPulse 1.3s ease-in-out 3.5s infinite alternate,
            padOut .4s ease-in 4.95s forwards; }
@keyframes padIn { 0% { opacity:0; transform:scale(.15,.4); } 60% { opacity:1; transform:scale(1.12,1.05); } 100% { opacity:.95; transform:scale(1,1); } }
@keyframes padPulse { from { opacity:.95; } to { opacity:.55; } }
@keyframes padOut { to { opacity:0; transform:scale(.25,.4); } }
/* 著地衝擊環：貼地橢圓擴散（透視地面的立體暗示） */
.land-burst { position:absolute; left:50%; top:537px; width:150px; height:150px; margin:-75px 0 0 -75px;
  border-radius:50%; border:2.5px solid rgba(125,211,252,.9); opacity:0; pointer-events:none;
  box-shadow:0 0 18px rgba(56,189,248,.8), inset 0 0 12px rgba(56,189,248,.4);
  animation:groundRing .55s cubic-bezier(.2,.7,.3,1) 3.06s backwards; }
@keyframes groundRing {
  0% { opacity:0; transform:scale(.15,.06); }
  20% { opacity:1; }
  100% { opacity:0; transform:scale(1.9,.62); } }
/* 跳出瞬間的爆閃光圈（沿用 boomRing / boomSpark 節奏） */
.pt-burst, .pt-burst2 { position:absolute; left:50%; top:158px; width:150px; height:150px;
  margin:-75px 0 0 -75px; border-radius:50%; opacity:0; }
.pt-burst { border:3px solid #f0abfc;
  box-shadow:0 0 24px rgba(240,171,252,.9), inset 0 0 14px rgba(240,171,252,.6);
  animation:boomRing .62s cubic-bezier(.2,.7,.3,1) 2.42s backwards; }
.pt-burst2 { border:2.5px dotted #a5f3fc; animation:boomSpark .7s ease-out 2.5s backwards; }
/* 四角星星（原片跳出後滿場星星） */
.pt-stage .spk { position:absolute; line-height:1; opacity:0; z-index:2;
  text-shadow:0 0 12px currentColor; animation:spkTw 1.15s ease-in-out var(--sd) 2 backwards; }
@keyframes spkTw {
  0% { opacity:0; transform:scale(.2) rotate(0deg); }
  45% { opacity:1; transform:scale(1.15) rotate(24deg); }
  100% { opacity:0; transform:scale(.3) rotate(45deg); } }
/* 卡片被炸出來（fill:backwards → 動畫結束後恢復原樣式，hover 不受影響） */
.arch-root .dept { animation:cardIn .55s cubic-bezier(.25,1.25,.4,1) var(--reveal,0s) backwards; }
@keyframes cardIn {
  0% { opacity:0; transform:translateY(-18px) scale(.68); filter:brightness(2.6) saturate(1.5); }
  55% { opacity:1; filter:brightness(1.4); }
  100% { opacity:1; transform:translateY(0) scale(1); filter:brightness(1); } }
.arch-root .dept-sep { animation:flowPulse 2.4s ease-in-out infinite, sepIn .5s ease-out 12.1s backwards; }
@keyframes sepIn { from { opacity:0; } to { opacity:.55; } }
.arch-root .arch-title { animation:riseIn .7s ease-out .05s backwards; }
/* 中央面板標頭等人物退場後再現身，把第一幕舞台留給傳送門 */
.arch-root .oval-hdr { animation:riseIn .7s ease-out 5.65s backwards; }
.arch-root .arch-tagline { animation:riseIn .6s ease-out 12.2s backwards; }
.arch-root .upload-hint { animation:riseIn .6s ease-out 12.35s backwards; }
@keyframes riseIn { from { opacity:0; transform:translateY(14px); } to { opacity:1; transform:translateY(0); } }
/* 爆炸震波：整個中央面板微震 5 次（對應 5 次落彈時間點，隨空投整體延後 3.05s） */
.arch-root .oval-center { animation:quake 10s linear 3.05s both; }
@keyframes quake {
  0%, 54.5%, 56.4%, 61.5%, 63.4%, 68.5%, 70.4%, 75.5%, 77.4%, 82.5%, 84.4%, 100% { transform:translate(0,0); }
  55%, 62%, 69%, 76%, 83% { transform:translate(3px,4px); }
  55.7%, 62.7%, 69.7%, 76.7%, 83.7% { transform:translate(-3px,-3px); } }
@media (prefers-reduced-motion: reduce) {
  .intro-sky, .intro-fly, .intro-portal { display:none; }
  .arch-root .dept, .arch-root .dept-sep, .arch-root .arch-title, .arch-root .oval-hdr,
  .arch-root .arch-tagline, .arch-root .upload-hint, .arch-root .oval-center {
    animation:none !important; opacity:1 !important; } }
</style>

<div class="arch-title">
  <h2>__FLOW_TITLE__</h2>
  <div class="sub">__FLOW_SUB__</div>
  <div class="divider"></div>
</div>

<div class="intro-fly">
  <div class="drone"><div class="drone-flip"><div class="drone-inner">
    <span class="jet"></span>
    <svg viewBox="0 0 624 420" xmlns="http://www.w3.org/2000/svg">
      <defs>
        <linearGradient id="avFus" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="#ffffff"/>
          <stop offset="28%" stop-color="#e9eff8"/>
          <stop offset="62%" stop-color="#c3cfe0"/>
          <stop offset="100%" stop-color="#8fa0b8"/>
        </linearGradient>
        <linearGradient id="avKeel" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="#0e1624" stop-opacity="0"/>
          <stop offset="100%" stop-color="#04070c"/>
        </linearGradient>
        <linearGradient id="avMetal" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="#b9c7da"/>
          <stop offset="100%" stop-color="#5a6c85"/>
        </linearGradient>
        <linearGradient id="avCanopy" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="#d8f6ff"/>
          <stop offset="35%" stop-color="#6cc4f0"/>
          <stop offset="75%" stop-color="#1e6fb8"/>
          <stop offset="100%" stop-color="#0a3a70"/>
        </linearGradient>
        <linearGradient id="avAccent" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stop-color="#22d3ee"/>
          <stop offset="50%" stop-color="#60a5fa"/>
          <stop offset="100%" stop-color="#a78bfa"/>
        </linearGradient>
        <linearGradient id="avBeam" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="#cfeaff" stop-opacity=".55"/>
          <stop offset="100%" stop-color="#cfeaff" stop-opacity="0"/>
        </linearGradient>
        <filter id="avGlow" x="-60%" y="-60%" width="220%" height="220%">
          <feGaussianBlur stdDeviation="2.2" result="b"/>
          <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
        </filter>
        <clipPath id="avFusClip">
          <path d="M18 232 L96 192 L160 162 Q215 148 275 146 L410 150 L462 138 L516 148 L518 190 L478 222 L410 248 L255 266 L120 254 L54 242 Z"/>
        </clipPath>
        <clipPath id="avCnClip">
          <path d="M118 184 L158 152 L234 144 L258 164 L180 180 Z"/>
        </clipPath>
        <clipPath id="avLogoClip"><rect x="336" y="201" width="92" height="34" rx="7"/></clipPath>
      </defs>
      <!-- 機首探照燈光錐 -->
      <path d="M34 232 L-10 360 L98 346 Z" fill="url(#avBeam)" opacity=".14">
        <animateTransform attributeName="transform" type="rotate" values="-5 34 232;6 34 232;-5 34 232" dur="2.6s" repeatCount="indefinite"/>
      </path>
      <!-- 遠側尾翼與機翼（景深） -->
      <path d="M462 150 L484 82 L498 86 L486 148 Z" fill="#7b8daa"/>
      <path d="M300 252 L426 238 L464 260 L344 274 Z" fill="#6d7f9c"/>
      <!-- 頂部雙涵道升力風扇 + 塔架 -->
      <path d="M138 50 L132 178 L168 172 L162 50 Z" fill="url(#avMetal)" stroke="#6d7f9a" stroke-width="1"/>
      <path d="M358 50 L354 166 L390 166 L382 50 Z" fill="url(#avMetal)" stroke="#6d7f9a" stroke-width="1"/>
      <rect x="150" y="100" width="220" height="7" rx="3.5" fill="#4a5b73" stroke="#6d7f9a" stroke-width=".8"/>
      <rect x="86" y="14" width="128" height="38" rx="19" fill="url(#avMetal)" stroke="#8ca1bf" stroke-width="1.4"/>
      <ellipse cx="150" cy="33" rx="52" ry="9" fill="#06090f" stroke="#0d1524" stroke-width="2"/>
      <ellipse cx="150" cy="33" rx="43" ry="6" fill="none" stroke="#8fd8ff" stroke-width="2" stroke-dasharray="12 14" opacity=".95">
        <animate attributeName="stroke-dashoffset" from="0" to="-52" dur=".2s" repeatCount="indefinite"/>
      </ellipse>
      <ellipse cx="150" cy="33" rx="8" ry="2.6" fill="#b9cbe4"/>
      <rect x="94" y="48" width="112" height="3.5" rx="1.75" fill="#22d3ee" opacity=".85">
        <animate attributeName="opacity" values=".85;.35;.85" dur=".9s" repeatCount="indefinite"/>
      </rect>
      <rect x="306" y="14" width="128" height="38" rx="19" fill="url(#avMetal)" stroke="#8ca1bf" stroke-width="1.4"/>
      <ellipse cx="370" cy="33" rx="52" ry="9" fill="#06090f" stroke="#0d1524" stroke-width="2"/>
      <ellipse cx="370" cy="33" rx="43" ry="6" fill="none" stroke="#8fd8ff" stroke-width="2" stroke-dasharray="12 14" opacity=".95">
        <animate attributeName="stroke-dashoffset" from="0" to="-52" dur=".19s" repeatCount="indefinite"/>
      </ellipse>
      <ellipse cx="370" cy="33" rx="8" ry="2.6" fill="#b9cbe4"/>
      <rect x="314" y="48" width="112" height="3.5" rx="1.75" fill="#22d3ee" opacity=".85">
        <animate attributeName="opacity" values=".35;.85;.35" dur=".9s" repeatCount="indefinite"/>
      </rect>
      <!-- 機身主體 -->
      <path d="M18 232 L96 192 L160 162 Q215 148 275 146 L410 150 L462 138 L516 148 L518 190 L478 222 L410 248 L255 266 L120 254 L54 242 Z"
        fill="url(#avFus)" stroke="#9db1cb" stroke-width="1.5" stroke-linejoin="round"/>
      <rect x="0" y="205" width="624" height="100" fill="url(#avKeel)" opacity=".45" clip-path="url(#avFusClip)"/>
      <path d="M96 192 L160 162 Q215 148 275 146 L410 150 L462 138" fill="none" stroke="#e6f1ff" stroke-width="2" opacity=".4"/>
      <path d="M18 232 L96 192" fill="none" stroke="#cfe0f5" stroke-width="1.6" opacity=".35"/>
      <!-- 蒙皮面板線與散熱口 -->
      <g stroke="#5f7089" stroke-width="1" fill="none" opacity=".85">
        <path d="M190 158 L198 260"/>
        <path d="M300 148 L306 264"/>
        <path d="M380 152 L386 254"/>
        <path d="M96 214 L470 192" opacity=".5"/>
        <path d="M76 216 L96 211" stroke-width="1.4"/>
        <path d="M76 222 L100 217" stroke-width="1.4"/>
        <path d="M76 228 L104 223" stroke-width="1.4"/>
      </g>
      <!-- 能量流光帶 -->
      <path d="M44 226 L476 200" fill="none" stroke="url(#avAccent)" stroke-width="3" stroke-dasharray="26 12" opacity=".9" filter="url(#avGlow)">
        <animate attributeName="stroke-dashoffset" from="0" to="-76" dur="1.1s" repeatCount="indefinite"/>
      </path>
      <!-- 進氣口 / 引擎艙 / 噴嘴 -->
      <path d="M400 176 L446 166 L446 180 L400 188 Z" fill="#05080d" stroke="#22d3ee" stroke-width=".8" opacity=".9"/>
      <path d="M506 166 L544 174 L544 210 L500 216 Z" fill="url(#avMetal)" stroke="#4d6285" stroke-width="1.2"/>
      <path d="M544 176 L558 180 L558 204 L544 208 Z" fill="#0a0f18" stroke="#223349" stroke-width="1"/>
      <!-- 電漿尾焰 -->
      <path d="M556 178 C592 180 610 192 618 192 C610 192 592 204 556 206 Z" fill="#22d3ee" opacity=".3">
        <animate attributeName="opacity" values=".3;.15;.3" dur=".22s" repeatCount="indefinite"/>
      </path>
      <path d="M556 182 C586 184 600 192 606 192 C600 192 586 200 556 202 Z" fill="#7dd3fc" opacity=".55">
        <animate attributeName="opacity" values=".55;.3;.55" dur=".18s" repeatCount="indefinite"/>
      </path>
      <path d="M556 186 C578 187 590 192 594 192 C590 192 578 197 556 198 Z" fill="#ecfeff" opacity=".95">
        <animate attributeName="opacity" values=".95;.6;.95" dur=".15s" repeatCount="indefinite"/>
      </path>
      <circle cx="572" cy="192" r="2.6" fill="#ffffff" opacity=".85"/>
      <circle cx="586" cy="192" r="2" fill="#ffffff" opacity=".7"/>
      <!-- 近側尾翼 -->
      <path d="M446 152 L470 88 L488 92 L474 156 Z" fill="url(#avFus)" stroke="#9db1cb" stroke-width="1.3"/>
      <circle cx="480" cy="88" r="2.8" fill="#ffffff" filter="url(#avGlow)">
        <animate attributeName="opacity" values="0;1;0;0;0" dur="1.3s" repeatCount="indefinite"/>
      </circle>
      <!-- 座艙罩（HUD 掃描光） -->
      <path d="M118 184 L158 152 L234 144 L258 164 L180 180 Z" fill="url(#avCanopy)" stroke="#a8e4ff" stroke-width="1.6"/>
      <g clip-path="url(#avCnClip)">
        <path d="M150 166 L208 158" stroke="#e8fcff" stroke-width="1" opacity=".75" fill="none"/>
        <path d="M146 172 L214 163" stroke="#e8fcff" stroke-width="1" opacity=".5" fill="none"/>
        <rect x="120" y="144" width="4" height="40" fill="#ffffff" opacity=".4">
          <animate attributeName="x" values="120;250;120" dur="2.4s" repeatCount="indefinite"/>
        </rect>
      </g>
      <path d="M200 148 L212 178" stroke="#7fb0d8" stroke-width="1.4" fill="none"/>
      <path d="M158 152 L234 144" stroke="#ffffff" stroke-width="2" opacity=".6" fill="none"/>
      <!-- 近側短翼 -->
      <path d="M334 244 L412 234 L434 250 L352 260 Z" fill="url(#avMetal)" stroke="#6d7f9a" stroke-width="1"/>
      <!-- 投彈艙（開啟中） -->
      <rect x="210" y="248" width="100" height="16" rx="5" fill="#0b1220" stroke="#6d7f9a" stroke-width="1"/>
      <rect x="215" y="252" width="90" height="8" rx="3" fill="#67e8f9" opacity=".85">
        <animate attributeName="opacity" values="1;.35;1" dur=".6s" repeatCount="indefinite"/>
      </rect>
      <path d="M210 262 L192 300 L200 303 L220 264 Z" fill="url(#avMetal)" stroke="#6d7f9a" stroke-width="1"/>
      <path d="M310 262 L328 300 L320 303 L300 264 Z" fill="url(#avMetal)" stroke="#6d7f9a" stroke-width="1"/>
      <!-- 起落架艙鼓包 -->
      <ellipse cx="150" cy="252" rx="17" ry="6" fill="#4d5f78"/>
      <ellipse cx="396" cy="244" rx="17" ry="6" fill="#4d5f78"/>
      <!-- 機首感測器與燈 -->
      <ellipse cx="44" cy="224" rx="11" ry="5.5" fill="#0e1626" stroke="#223349" stroke-width="1"/>
      <circle cx="34" cy="222" r="2.8" fill="#67e8f9" filter="url(#avGlow)">
        <animate attributeName="opacity" values="1;.4;1" dur=".9s" repeatCount="indefinite"/>
      </circle>
      <circle cx="24" cy="214" r="3" fill="#ff5b5b" filter="url(#avGlow)">
        <animate attributeName="opacity" values="1;.15;1" dur="1s" repeatCount="indefinite"/>
      </circle>
      <circle cx="516" cy="152" r="3" fill="#4ade80" filter="url(#avGlow)">
        <animate attributeName="opacity" values=".15;1;.15" dur="1s" repeatCount="indefinite"/>
      </circle>
      <!-- 天線與機身編號 -->
      <path d="M320 146 L328 118" stroke="#4d6285" stroke-width="2" fill="none"/>
      <circle cx="328" cy="116" r="2" fill="#9adcff"/>
      <g class="logo-keep"><text x="104" y="208" font-family="Consolas, Arial, sans-serif" font-size="13" fill="#45596f" letter-spacing="3" opacity=".95">UCAV-05</text></g>
      <!-- 公司 LOGO 塗裝 -->
      <g class="logo-keep">
        <rect x="330" y="196" width="104" height="44" rx="9" fill="#ffffff" stroke="#7dd3fc" stroke-width="1.6" filter="url(#avGlow)"/>
        <image href="data:image/png;base64,__ORING_LOGO__" x="336" y="201" width="92" height="34" preserveAspectRatio="xMidYMid meet" clip-path="url(#avLogoClip)"/>
      </g>
    </svg>
  </div></div></div>
</div>
<div class="arch-main">

  <!-- ══ 中央橢圓 ══ -->
  <div class="oval-center">
    <!-- ══ 開場第二幕：無人機空投動畫層 ══ -->
    <div class="intro-sky">
      <div class="strike" style="left:89.7%;--d:8.05s">
        <i class="tgt"></i>
        <span class="bomb"><svg viewBox="0 0 26 46" xmlns="http://www.w3.org/2000/svg"><path d="M8 9 L3 1 L11 6 Z" fill="#3c547f"/><path d="M18 9 L23 1 L15 6 Z" fill="#3c547f"/><rect x="10" y="1.5" width="6" height="9" rx="2" fill="#2b3d5e"/><ellipse cx="13" cy="25" rx="8.6" ry="15" fill="#24344e" stroke="#4a659a" stroke-width="1.2"/><rect x="4.8" y="20.5" width="16.4" height="4.2" rx="2.1" fill="#67e8f9" opacity=".85"/><circle cx="13" cy="38.5" r="3" fill="#a5f3fc"><animate attributeName="opacity" values="1;.35;1" dur=".28s" repeatCount="indefinite"/></circle></svg></span>
        <i class="boom-fl"></i><i class="boom-r1"></i><i class="boom-r2"></i><i class="boom-sp"></i>
      </div>
      <div class="strike" style="left:69.9%;--d:8.75s">
        <i class="tgt"></i>
        <span class="bomb"><svg viewBox="0 0 26 46" xmlns="http://www.w3.org/2000/svg"><path d="M8 9 L3 1 L11 6 Z" fill="#3c547f"/><path d="M18 9 L23 1 L15 6 Z" fill="#3c547f"/><rect x="10" y="1.5" width="6" height="9" rx="2" fill="#2b3d5e"/><ellipse cx="13" cy="25" rx="8.6" ry="15" fill="#24344e" stroke="#4a659a" stroke-width="1.2"/><rect x="4.8" y="20.5" width="16.4" height="4.2" rx="2.1" fill="#67e8f9" opacity=".85"/><circle cx="13" cy="38.5" r="3" fill="#a5f3fc"><animate attributeName="opacity" values="1;.35;1" dur=".28s" repeatCount="indefinite"/></circle></svg></span>
        <i class="boom-fl"></i><i class="boom-r1"></i><i class="boom-r2"></i><i class="boom-sp"></i>
      </div>
      <div class="strike" style="left:50%;--d:9.45s">
        <i class="tgt"></i>
        <span class="bomb"><svg viewBox="0 0 26 46" xmlns="http://www.w3.org/2000/svg"><path d="M8 9 L3 1 L11 6 Z" fill="#3c547f"/><path d="M18 9 L23 1 L15 6 Z" fill="#3c547f"/><rect x="10" y="1.5" width="6" height="9" rx="2" fill="#2b3d5e"/><ellipse cx="13" cy="25" rx="8.6" ry="15" fill="#24344e" stroke="#4a659a" stroke-width="1.2"/><rect x="4.8" y="20.5" width="16.4" height="4.2" rx="2.1" fill="#67e8f9" opacity=".85"/><circle cx="13" cy="38.5" r="3" fill="#a5f3fc"><animate attributeName="opacity" values="1;.35;1" dur=".28s" repeatCount="indefinite"/></circle></svg></span>
        <i class="boom-fl"></i><i class="boom-r1"></i><i class="boom-r2"></i><i class="boom-sp"></i>
      </div>
      <div class="strike" style="left:30.1%;--d:10.15s">
        <i class="tgt"></i>
        <span class="bomb"><svg viewBox="0 0 26 46" xmlns="http://www.w3.org/2000/svg"><path d="M8 9 L3 1 L11 6 Z" fill="#3c547f"/><path d="M18 9 L23 1 L15 6 Z" fill="#3c547f"/><rect x="10" y="1.5" width="6" height="9" rx="2" fill="#2b3d5e"/><ellipse cx="13" cy="25" rx="8.6" ry="15" fill="#24344e" stroke="#4a659a" stroke-width="1.2"/><rect x="4.8" y="20.5" width="16.4" height="4.2" rx="2.1" fill="#67e8f9" opacity=".85"/><circle cx="13" cy="38.5" r="3" fill="#a5f3fc"><animate attributeName="opacity" values="1;.35;1" dur=".28s" repeatCount="indefinite"/></circle></svg></span>
        <i class="boom-fl"></i><i class="boom-r1"></i><i class="boom-r2"></i><i class="boom-sp"></i>
      </div>
      <div class="strike" style="left:10.3%;--d:10.85s">
        <i class="tgt"></i>
        <span class="bomb"><svg viewBox="0 0 26 46" xmlns="http://www.w3.org/2000/svg"><path d="M8 9 L3 1 L11 6 Z" fill="#3c547f"/><path d="M18 9 L23 1 L15 6 Z" fill="#3c547f"/><rect x="10" y="1.5" width="6" height="9" rx="2" fill="#2b3d5e"/><ellipse cx="13" cy="25" rx="8.6" ry="15" fill="#24344e" stroke="#4a659a" stroke-width="1.2"/><rect x="4.8" y="20.5" width="16.4" height="4.2" rx="2.1" fill="#67e8f9" opacity=".85"/><circle cx="13" cy="38.5" r="3" fill="#a5f3fc"><animate attributeName="opacity" values="1;.35;1" dur=".28s" repeatCount="indefinite"/></circle></svg></span>
        <i class="boom-fl"></i><i class="boom-r1"></i><i class="boom-r2"></i><i class="boom-sp"></i>
      </div>
    </div>
    <!-- ══ 開場第一幕：亮色傳送門 ＋ 人物跳出 ══ -->
    <div class="intro-portal"><div class="pt-stage">
      <i class="pt-rays"></i>
      <div class="pt-ring"><i class="pt-core"></i><i class="pt-swirl"></i><i class="pt-r1"></i><i class="pt-r2"></i><i class="pt-r3"></i></div>
      <div class="pt-clip"><div class="boy-peek"><div class="bp-sway">
        <div class="boy-rig">
          <img class="b-body" src="data:image/png;base64,__BOY_BODY__" alt=""/>
          <img class="b-arm" src="data:image/png;base64,__BOY_ARM__" alt=""/>
          <img class="b-head" src="data:image/png;base64,__BOY_HEAD__" alt=""/>
        </div>
      </div></div></div>
      <i class="pt-burst"></i><i class="pt-burst2"></i>
      <i class="land-pad"></i>
      <i class="land-burst"></i>
      <div class="boy-jump"><div class="bj-cheer">
        <i class="scan-bar"></i>
        <div class="boy-rig">
          <img class="b-body" src="data:image/png;base64,__BOY_BODY__" alt=""/>
          <img class="b-arm" src="data:image/png;base64,__BOY_ARM__" alt=""/>
          <img class="b-head" src="data:image/png;base64,__BOY_HEAD__" alt=""/>
        </div>
      </div></div>
      <span class="spk" style="left:4%; top:14%; color:#f9a8d4; font-size:26px; --sd:2.45s">&#10022;</span>
      <span class="spk" style="left:84%; top:10%; color:#a5f3fc; font-size:20px; --sd:2.6s">&#10022;</span>
      <span class="spk" style="left:90%; top:52%; color:#fde68a; font-size:24px; --sd:2.95s">&#10022;</span>
      <span class="spk" style="left:0%; top:58%; color:#c4b5fd; font-size:18px; --sd:3.3s">&#10022;</span>
      <span class="spk" style="left:12%; top:84%; color:#a5f3fc; font-size:22px; --sd:3.6s">&#10022;</span>
      <span class="spk" style="left:80%; top:82%; color:#f9a8d4; font-size:16px; --sd:3.9s">&#10022;</span>
      <span class="spk" style="left:46%; top:0%; color:#ffffff; font-size:18px; --sd:4.1s">&#10022;</span>
      <span class="spk" style="left:68%; top:30%; color:#fde68a; font-size:14px; --sd:3.1s">&#10022;</span>
      <span class="spk" style="left:24%; top:32%; color:#ffffff; font-size:15px; --sd:2.5s">&#10022;</span>
      <span class="spk" style="left:56%; top:66%; color:#c4b5fd; font-size:20px; --sd:4.3s">&#10022;</span>
      <span class="spk" style="left:24%; top:50%; color:#a5f3fc; font-size:15px; --sd:3.55s">&#10022;</span>
      <span class="spk" style="left:31%; top:44%; color:#ffffff; font-size:13px; --sd:4.15s">&#10022;</span>
      <span class="spk" style="left:52.5%; top:32%; color:#ffffff; font-size:13px; --sd:3.75s">&#10022;</span>
      <span class="spk" style="left:48.5%; top:35%; color:#ffffff; font-size:11px; --sd:4.4s">&#10022;</span>
    </div></div>
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
      <div class="ov-flow">__FLOW_CHAIN__</div>
    </div>

    <!-- 三部門卡片 -->
    <div class="dept-row">
      <div class="dept dept-pmc" style="--reveal:11.5s">
        <div class="dhdr">
          <span class="di">📑</span>
          <div class="dn">PMC</div>
          <div class="ds">Production Material Control</div>
        </div>
        <div class="dbody">
          <a href="/pmc_order_tracking" target="_self" class="tl">__L_PMC_ORDER__</a>
          <a href="/wo_material_trace" target="_self" class="tl">__L_WO_TRACE__</a>
          <a href="/tangyou_shortage_reply" target="_self" class="tl">__L_TANGYOU_REPLY__</a>
        </div>
      </div>
      <div class="dept-sep">&rarr;</div>
      <div class="dept dept-pc" style="--reveal:10.8s">
        <div class="dhdr">
          <span class="di">📊</span>
          <div class="dn">__DEPT_PC__</div>
          <div class="ds">Production Control</div>
        </div>
        <div class="dbody">
          <a href="/full_material_trace" target="_self" class="tl">__L_FULL_TRACE__</a>
          <a href="/monthly_cost" target="_self" class="tl">__L_MONTHLY_COST__</a>
          <a href="/kanban"       target="_self" class="tl">__L_KANBAN__</a>
          <a href="/scheduling"   target="_self" class="tl">__L_SCHEDULING__</a>
          <a href="/outsource_schedule" target="_self" class="tl">__L_OUTSOURCE_SCH__</a>
          <a href="/loss_rate"    target="_self" class="tl">__L_LOSS_RATE__</a>
        </div>
      </div>
      <div class="dept-sep">&rarr;</div>
      <div class="dept dept-mc" style="--reveal:10.1s">
        <div class="dhdr">
          <span class="di">📦</span>
          <div class="dn">__DEPT_MC__</div>
          <div class="ds">Material Control</div>
        </div>
        <div class="dbody">
          <a href="/h2o"     target="_self" class="tl">__L_H2O__</a>
          <a href="/guozhi"  target="_self" class="tl">__L_GUOZHI__</a>
          <a href="/factory" target="_self" class="tl">__L_FACTORY__</a>
        </div>
      </div>
      <div class="dept-sep">&rarr;</div>
      <div class="dept dept-wh" style="--reveal:9.4s">
        <div class="dhdr">
          <span class="di">🏬</span>
          <div class="dn">__DEPT_WH__</div>
          <div class="ds">Warehouse Management</div>
        </div>
        <div class="dbody">
          <a href="/daily_inbound" target="_self" class="tl">__L_DAILY_INBOUND__</a>
          <a href="/daily_picking" target="_self" class="tl">__L_DAILY_PICKING__</a>
          <a href="/wh_staff"      target="_self" class="tl">__L_WH_STAFF__</a>
          <a href="/wh_dashboard"  target="_self" class="tl">__L_WH_DASHBOARD__</a>
        </div>
      </div>
      <div class="dept-sep">&rarr;</div>
      <div class="dept dept-ps" style="--reveal:8.7s">
        <div class="dhdr">
          <span class="di">🛠</span>
          <div class="dn">__DEPT_PS__</div>
          <div class="ds">__DEPT_PS_SUB__</div>
        </div>
        <div class="dbody">
          <a href="/assembly" target="_self" class="tl">__L_ASSEMBLY__</a>
          <a href="/test_station" target="_self" class="tl">__L_TEST__</a>
          <a class="tl">__L_PACKAGING__</a>
          <a href="/total_worktime" target="_self" class="tl">__L_WORKTIME__</a>
        </div>
      </div>
    </div>
  </div>


</div>

<div class="arch-tagline">__FLOW_TAGLINE__</div>
<div class="upload-hint">__UPLOAD_HINT__</div>
</div>
"""
    _flow_tokens = {
        "__UPLOAD_HINT__": t("upload_hint"),
        "__ORING_LOGO__": _logo_b64(),
        "__BOY_BODY__": _boy_part_b64("boy_body.png"),
        "__BOY_ARM__": _boy_part_b64("boy_arm.png"),
        "__BOY_HEAD__": _boy_part_b64("boy_head.png"),
        "__FLOW_TITLE__": t("flow_title"),
        "__FLOW_SUB__": t("flow_sub"),
        "__FLOW_CHAIN__": t("flow_chain"),
        "__FLOW_TAGLINE__": t("flow_tagline"),
        "__DEPT_PC__": t("dept_pc"),
        "__DEPT_MC__": t("dept_mc"),
        "__DEPT_WH__": t("dept_wh"),
        "__DEPT_PS__": t("dept_ps"),
        "__DEPT_PS_SUB__": t("dept_ps_sub"),
        "__L_PMC_ORDER__": t("link_pmc_order"),
        "__L_WO_TRACE__": t("link_wo_trace"),
        "__L_TANGYOU_REPLY__": t("link_tangyou_reply"),
        "__L_FULL_TRACE__": t("link_full_trace"),
        "__L_MONTHLY_COST__": t("link_monthly_cost"),
        "__L_KANBAN__": t("link_kanban"),
        "__L_SCHEDULING__": t("link_scheduling"),
        "__L_OUTSOURCE_SCH__": t("link_outsource_schedule"),
        "__L_LOSS_RATE__": t("link_loss_rate"),
        "__L_H2O__": t("link_h2o"),
        "__L_GUOZHI__": t("link_guozhi"),
        "__L_FACTORY__": t("link_factory"),
        "__L_DAILY_INBOUND__": t("link_daily_inbound"),
        "__L_DAILY_PICKING__": t("link_daily_picking"),
        "__L_WH_STAFF__": t("link_wh_staff"),
        "__L_WH_DASHBOARD__": t("link_wh_dashboard"),
        "__L_ASSEMBLY__": t("link_assembly"),
        "__L_TEST__": t("link_test_station"),
        "__L_PACKAGING__": t("link_packaging"),
        "__L_WORKTIME__": t("link_total_worktime"),
    }
    for _tk, _tv in _flow_tokens.items():
        _flow_html = _flow_html.replace(_tk, _tv)
    st.markdown(
        "\n".join(_l for _l in _flow_html.splitlines() if _l.strip()),
        unsafe_allow_html=True,
    )
