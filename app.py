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

/* ══════════ 白晝科技底：與 /warroom 同一套色票 ══════════ */
.arch-root {
  font-family:"Segoe UI","Microsoft JhengHei",Arial,sans-serif;
  color:#0E2233; min-width:0; position:relative; overflow:hidden;
  border-radius:18px; padding:24px 20px 22px; min-height:900px;
  background:
    radial-gradient(1400px 900px at 20% 4%, #F7FBFF 0%, rgba(247,251,255,0) 58%),
    linear-gradient(158deg,#EAF3FC 0%,#D6E8F8 36%,#C4DBF2 68%,#D8EAF8 100%);
  box-shadow:0 0 0 1px rgba(150,205,245,.55), 0 28px 64px -26px rgba(16,60,110,.45); }
.arch-root > * { position:relative; z-index:2; }

/* ── 環境光暈（warroom 的 stApp::before） ── */
.arch-root::before { content:""; position:absolute; inset:0; z-index:0; pointer-events:none;
  background:
    radial-gradient(620px 520px at 8% 12%,  rgba(94,159,228,.40), transparent 62%),
    radial-gradient(560px 480px at 92% 8%,  rgba(63,184,220,.34), transparent 62%),
    radial-gradient(700px 520px at 68% 96%, rgba(127,169,238,.32), transparent 64%); }
/* ── 淡格線 ── */
.arch-root::after { content:""; position:absolute; inset:0; z-index:0; pointer-events:none;
  background-image:
    linear-gradient(rgba(90,150,215,.13) 1px, transparent 1px),
    linear-gradient(90deg, rgba(90,150,215,.13) 1px, transparent 1px);
  background-size:44px 44px;
  -webkit-mask-image:radial-gradient(ellipse 100% 88% at 50% 30%, #000 62%, transparent 100%);
  mask-image:radial-gradient(ellipse 100% 88% at 50% 30%, #000 62%, transparent 100%); }

/* ══════════ 3D 場景：天花燈 / 光束 / 玻璃牆 / 地球 / 地板 ══════════ */
.ar-scene { position:absolute; inset:0; z-index:1; pointer-events:none; overflow:hidden;
  border-radius:18px; perspective:2200px; perspective-origin:50% 42%; }
.ar-scene .ceil { position:absolute; left:50%; top:-250px; width:1180px; height:410px; margin-left:-590px;
  border-radius:50%; border:3px solid rgba(255,255,255,.95);
  background:radial-gradient(60% 78% at 50% 100%, rgba(255,255,255,.85), rgba(255,255,255,0) 70%);
  box-shadow:0 34px 70px -18px rgba(120,190,255,.72), inset 0 -26px 50px rgba(255,255,255,.9); }
.ar-scene .ceil2 { position:absolute; left:50%; top:-190px; width:860px; height:290px; margin-left:-430px;
  border-radius:50%; border:2px solid rgba(255,255,255,.8);
  box-shadow:0 22px 54px -16px rgba(140,200,255,.55); }
.ar-scene .ray { position:absolute; border-radius:50%; filter:blur(26px); }
.ar-scene .r1 { left:-14%; top:50%; width:82%; height:54px; transform:rotate(-7deg);
  background:linear-gradient(90deg,rgba(255,255,255,0),rgba(186,226,255,.95),rgba(255,255,255,0)); }
.ar-scene .r2 { left:-16%; top:60%; width:70%; height:34px; transform:rotate(-4deg);
  background:linear-gradient(90deg,rgba(255,255,255,0),rgba(150,205,250,.78),rgba(255,255,255,0)); }
.ar-scene .r3 { right:-14%; top:70%; width:64%; height:26px; transform:rotate(8deg);
  background:linear-gradient(90deg,rgba(255,255,255,0),rgba(206,236,255,.9),rgba(255,255,255,0)); }

.ar-scene .wall { position:absolute; right:-40px; top:64px; width:620px; height:430px;
  transform:rotateY(-19deg) rotateX(2deg); transform-origin:100% 50%; opacity:.92; }
.ar-scene .wall.lft { right:auto; left:-40px; transform:rotateY(19deg) rotateX(2deg); transform-origin:0 50%; }
.ar-scene .wp { position:absolute; border-radius:14px; border:1px solid rgba(255,255,255,.85);
  background:linear-gradient(150deg,rgba(226,242,255,.5),rgba(196,224,250,.28));
  box-shadow:0 20px 46px -18px rgba(20,70,130,.38), inset 0 1px 0 rgba(255,255,255,.9); }
.ar-scene .wl { position:absolute; height:5px; border-radius:99px; background:rgba(90,150,215,.34); }
.ar-scene .wb { position:absolute; bottom:10px; border-radius:3px 3px 0 0; }

.ar-scene .globe { position:absolute; right:13%; top:44px; width:236px; height:236px; opacity:.9;
  filter:drop-shadow(0 26px 44px rgba(20,80,150,.38));
  animation:arFloat 26s ease-in-out infinite alternate; }
@keyframes arFloat { from { transform:translateY(0); } to { transform:translateY(15px); } }

.ar-scene .floor { position:absolute; left:0; right:0; bottom:0; height:30%;
  background:linear-gradient(180deg,rgba(255,255,255,0) 0%,rgba(240,249,255,.72) 26%,
             rgba(214,236,252,.92) 62%,rgba(196,225,247,1) 100%); }
.ar-scene .grid { position:absolute; left:-20%; right:-20%; bottom:0; height:27%; opacity:.4;
  transform:perspective(520px) rotateX(64deg); transform-origin:bottom center;
  background-image:linear-gradient(90deg, rgba(90,150,215,.5) 1px, transparent 1px),
                   linear-gradient(0deg,  rgba(90,150,215,.4) 1px, transparent 1px);
  background-size:70px 46px;
  -webkit-mask-image:linear-gradient(180deg,transparent 0%,#000 55%,transparent 100%);
  mask-image:linear-gradient(180deg,transparent 0%,#000 55%,transparent 100%); }
.ar-scene .pod { position:absolute; left:50%; bottom:-160px; width:1120px; height:300px; margin-left:-560px;
  border-radius:50%; border:2px solid rgba(255,255,255,.9);
  background:radial-gradient(closest-side,rgba(255,255,255,.9),rgba(226,243,255,.42) 70%,rgba(226,243,255,0));
  box-shadow:0 -16px 46px -12px rgba(130,195,255,.55); }
.ar-scene .pod2 { position:absolute; left:50%; bottom:-190px; width:1380px; height:340px; margin-left:-690px;
  border-radius:50%; border:2px solid rgba(255,255,255,.66); }
.ar-scene .mirror { position:absolute; left:0; right:0; bottom:0; height:23%;
  background:linear-gradient(180deg, rgba(255,255,255,.45) 0%, rgba(196,224,248,.26) 34%,
             rgba(150,196,236,.36) 100%);
  -webkit-mask-image:linear-gradient(180deg,#000 0%,rgba(0,0,0,.35) 62%,transparent 100%);
  mask-image:linear-gradient(180deg,#000 0%,rgba(0,0,0,.35) 62%,transparent 100%); }
.ar-scene .topfade { position:absolute; left:0; right:0; top:0; height:22%;
  background:linear-gradient(180deg, rgba(24,66,116,.20) 0%, rgba(24,66,116,0) 100%); }
.ar-scene .vig { position:absolute; inset:0;
  background:radial-gradient(120% 90% at 50% 42%, rgba(255,255,255,0) 44%,
             rgba(28,72,124,.14) 76%, rgba(16,48,92,.30) 100%); }

/* ── 產業影像浮窗（牆上螢幕） ── */
.ar-scene .holo { position:absolute; top:18px; width:168px; height:94px; border-radius:13px;
  overflow:hidden; border:1px solid rgba(255,255,255,.95);
  box-shadow:0 0 0 1px rgba(158,208,244,.55), 0 18px 34px -12px rgba(16,60,110,.42);
  animation:holoBob 6.5s ease-in-out infinite alternate; }
.ar-scene .holo-l { left:14px; }
.ar-scene .holo-r { right:14px; animation-delay:1.4s; }
@keyframes holoBob { from { transform:translateY(0); } to { transform:translateY(7px); } }
.ar-scene .holo img { position:absolute; inset:0; width:100%; height:100%; object-fit:cover; opacity:0;
  animation:holoFade 18s ease-in-out var(--hd,0s) infinite; }
.ar-scene .holo-l img:nth-child(1) { --hd:0s; }
.ar-scene .holo-l img:nth-child(2) { --hd:6s; }
.ar-scene .holo-l img:nth-child(3) { --hd:12s; }
.ar-scene .holo-r img:nth-child(1) { --hd:-9s; }
.ar-scene .holo-r img:nth-child(2) { --hd:-3s; }
.ar-scene .holo-r img:nth-child(3) { --hd:-15s; }
@keyframes holoFade { 0% { opacity:0; } 4% { opacity:1; } 33% { opacity:1; } 40% { opacity:0; } 100% { opacity:0; } }
.ar-scene .holo::after { content:""; position:absolute; top:-12%; bottom:-12%; left:-55%; width:38%;
  z-index:2; transform:skewX(-18deg);
  background:linear-gradient(105deg, transparent, rgba(255,255,255,.55) 50%, transparent);
  animation:holoSheen 7s ease-in-out 2.5s infinite; }
@keyframes holoSheen { 0% { transform:translateX(0) skewX(-18deg); }
  38%, 100% { transform:translateX(480%) skewX(-18deg); } }
@media (max-width:1360px) { .ar-scene .holo { display:none; } }

/* ══════════ 標題 ══════════ */
.arch-title { text-align:center; margin-bottom:18px; padding:0 194px; }
.arch-title h2 { font-size:40px; font-weight:800; letter-spacing:.10em; line-height:1.15;
  background:linear-gradient(96deg,#082D5A,#1668C6 46%,#0B6E96);
  -webkit-background-clip:text; -webkit-text-fill-color:transparent; background-clip:text;
  animation:titleIn .9s cubic-bezier(.2,.8,.3,1) .05s both; }
@keyframes titleIn { from { letter-spacing:.34em; opacity:0; filter:blur(5px); }
  to { letter-spacing:.10em; opacity:1; filter:blur(0); } }
.arch-title .sub { font-size:13px; color:#2C4A5E; margin-top:9px; font-weight:600;
  letter-spacing:.12em; line-height:1.7; font-family:"Consolas","SF Mono",monospace; }
.arch-title .sep { margin:0 10px; color:#1668C6; }
.arch-title .divider { width:118px; height:3px; margin:13px auto 0; border-radius:3px;
  background:linear-gradient(90deg,transparent,#3FA0E8,#1668C6,transparent); }
/* 影像浮窗收起來之後，標題不用再讓位 */
@media (max-width:1360px) { .arch-title { padding:0 12px; } }

/* ══════════ 中央玻璃大框（warroom .big） ══════════ */
.arch-main { display:block; }
.oval-center { position:relative; overflow:hidden; border-radius:24px; padding:20px 24px 22px;
  background:linear-gradient(152deg,rgba(255,255,255,.58) 0%,rgba(226,243,255,.42) 52%,rgba(255,255,255,.5) 100%);
  border:1px solid rgba(255,255,255,.98);
  -webkit-backdrop-filter:blur(16px) saturate(165%); backdrop-filter:blur(16px) saturate(165%);
  box-shadow:inset 0 1px 0 rgba(255,255,255,1), 0 0 0 1px rgba(150,205,245,.4),
             0 0 34px rgba(146,203,247,.42), 0 3px 0 rgba(196,226,250,.72),
             0 6px 0 rgba(166,206,240,.48), 0 20px 30px -12px rgba(16,60,110,.32),
             0 52px 72px -30px rgba(16,60,110,.44);
  animation:riseIn .7s ease-out .15s backwards; }
/* 邊框跑馬燈（改亮藍） */
.oval-center::after { content:""; position:absolute; inset:0; border-radius:24px; padding:1.6px;
  background:conic-gradient(from var(--angle),
    transparent 0deg, transparent 200deg,
    rgba(22,104,198,.85) 280deg, #7FC6F4 320deg, rgba(22,104,198,.85) 345deg, transparent 360deg);
  -webkit-mask:linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0);
  -webkit-mask-composite:xor;
  mask:linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0); mask-composite:exclude;
  animation:angleRun 5s linear infinite; pointer-events:none; z-index:6; }
@keyframes angleRun { to { --angle:360deg; } }
.oval-center .hudc { position:absolute; width:26px; height:26px; z-index:5; pointer-events:none;
  border:2px solid rgba(22,104,198,.45);
  animation:riseIn .6s ease-out .5s backwards, hudPulse 3.2s ease-in-out 1s infinite alternate; }
.oval-center .hudc.tl { left:11px; top:11px; border-right:none; border-bottom:none; border-radius:8px 0 0 0; }
.oval-center .hudc.tr { right:11px; top:11px; border-left:none; border-bottom:none; border-radius:0 8px 0 0; }
.oval-center .hudc.bl { left:11px; bottom:11px; border-right:none; border-top:none; border-radius:0 0 0 8px; }
.oval-center .hudc.br { right:11px; bottom:11px; border-left:none; border-top:none; border-radius:0 0 8px 0; }
@keyframes hudPulse { from { opacity:.35; } to { opacity:.9; } }

/* ── 頂部：核心圖示 + 流程膠囊 ── */
.oval-hdr { text-align:center; padding-bottom:2px; animation:riseIn .7s ease-out .3s backwards; }
.oval-hdr .ov-icon { display:block; margin-bottom:2px;
  filter:drop-shadow(0 10px 18px rgba(30,110,190,.35)); }
.oval-hdr .ov-flow { display:inline-block; margin-top:8px; font-size:14px; font-weight:800;
  color:#0C4187; letter-spacing:.04em; border-radius:20px; padding:9px 24px;
  background:linear-gradient(150deg,rgba(255,255,255,.9),rgba(228,244,255,.7));
  border:1px solid rgba(255,255,255,1);
  box-shadow:inset 0 1px 0 rgba(255,255,255,1), 0 0 0 1px rgba(158,208,244,.55),
             0 2px 0 rgba(198,228,250,.95), 0 5px 0 rgba(166,206,240,.55),
             0 12px 20px -6px rgba(16,60,110,.28); }

/* ══════════ 5 塊主題 · 3D 旋轉輪播 ══════════ */
.car-wrap { position:relative; margin-top:14px; }
.car-wrap .dsr { position:absolute; top:0; left:0; width:1px; height:1px;
  opacity:0; border:0; padding:0; margin:0; -webkit-appearance:none; appearance:none; }

/* --s = 相對中央的槽位（-2..2，帶正負決定左右）；--a = |--s|，管後退量與景深
   兩個都用 @property 註冊，值一變 transform/opacity/filter 會跟著重算，
   所以整段動畫只要動這兩個數字，不必為每張卡各寫一組 keyframes。 */
@property --s { syntax:'<number>'; initial-value:0; inherits:false; }
@property --a { syntax:'<number>'; initial-value:0; inherits:false; }
@property --o { syntax:'<number>'; initial-value:1; inherits:false; }

.car-stage { position:relative; height:526px; perspective:1250px; perspective-origin:50% 44%;
  z-index:2;
  --cw:clamp(272px, 22.5vw, 344px); }  /* 卡片寬：跟著視窗縮放 */
/* 中央卡在地板上的投影：讓卡片像站在房間裡，而不是貼在畫面上 */
.car-stage::after { content:""; position:absolute; left:50%; bottom:48px; z-index:0;
  width:calc(var(--cw) * .84); height:30px; margin-left:calc(var(--cw) * -.42);
  border-radius:50%; pointer-events:none;
  background:radial-gradient(closest-side, rgba(20,64,116,.30), rgba(20,64,116,.10) 62%, transparent);
  filter:blur(7px); }
.car-ring { position:absolute; left:50%; top:0; width:var(--cw); height:462px;
  margin-left:calc(var(--cw) / -2); transform-style:preserve-3d; }

.dept { position:absolute; inset:0;
  border-radius:20px; overflow:hidden; display:flex; flex-direction:column;
  transform:translateX(calc(var(--s) * 71%))
            translateZ(calc(var(--a) * -152px))
            rotateY(calc(var(--s) * -38deg))
            scale(calc(1 - var(--a) * .05));
  opacity:var(--o);
  filter:blur(calc(var(--a) * .8px)) saturate(calc(1 - var(--a) * .18))
         brightness(calc(1 - var(--a) * .05));
  background:linear-gradient(150deg,rgba(255,255,255,.93),rgba(232,246,255,.8));
  border:1px solid rgba(255,255,255,.96);
  box-shadow:inset 0 1px 0 rgba(255,255,255,1), 0 0 0 1px rgba(158,208,244,.4),
             0 14px 24px -14px rgba(16,60,110,.42), 0 40px 60px -32px rgba(16,60,110,.5);
  transition:--s .62s cubic-bezier(.42,.02,.2,1), --a .62s cubic-bezier(.42,.02,.2,1),
             --o .62s cubic-bezier(.42,.02,.2,1);
  animation:slotRun 30s cubic-bezier(.5,.02,.24,1) calc(var(--i) * 6s - 30s) infinite; }
/* 一圈 30s：每張正面停 4.8s，換場 1.2s；滑到 ±2 時 opacity 已為 0，
   所以從最左直接繞回最右的那一下看不見。 */
@keyframes slotRun {
  0%,  16% { --s:0;  --a:0; --o:1; }
  20%, 36% { --s:-1; --a:1; --o:.74; }
  40%, 56% { --s:-2; --a:2; --o:0; }
  60%, 76% { --s:2;  --a:2; --o:0; }
  80%, 96% { --s:1;  --a:1; --o:.74; }
  100%     { --s:0;  --a:0; --o:1; } }
/* 滑到卡片上就停住，方便點連結 */
.car-wrap:hover .dept,
.car-wrap:hover .rl { animation-play-state:paused; }

.dept .dhdr { padding:17px 12px 14px; text-align:center; color:#fff; position:relative; flex:none; }
.dept .dhdr::before { content:""; position:absolute; left:0; right:0; top:0; height:1px;
  background:linear-gradient(90deg, transparent, rgba(255,255,255,.75), transparent); }
.dept .dhdr .di { font-size:32px; display:block; margin-bottom:5px;
  filter:drop-shadow(0 3px 6px rgba(8,32,60,.35)); }
.dept .dhdr .dn { font-size:22px; font-weight:800; letter-spacing:.08em; white-space:nowrap;
  text-shadow:0 2px 8px rgba(6,26,52,.35); }
.dept .dhdr .ds { font-size:11px; opacity:.94; margin-top:4px; white-space:nowrap;
  letter-spacing:.16em; font-family:"Consolas",monospace; text-transform:uppercase; }
.dept-pmc .dhdr { background:linear-gradient(160deg,#B45309,#D97706,#F59E0B); }
.dept-pc  .dhdr { background:linear-gradient(160deg,#075985,#0369A1,#0EA5E9); }
.dept-mc  .dhdr { background:linear-gradient(160deg,#1E3A8A,#1D4ED8,#3B82F6); }
.dept-wh  .dhdr { background:linear-gradient(160deg,#3730A3,#4338CA,#6366F1); }
.dept-ps  .dhdr { background:linear-gradient(160deg,#115E59,#0F766E,#14B8A6); }

.dept .dbody { flex:1; padding:14px 14px 16px; display:flex; flex-direction:column; gap:8px;
  justify-content:center; overflow:auto;
  background:linear-gradient(180deg, rgba(255,255,255,.62), rgba(236,246,255,.9)); }
.dept .dbody::-webkit-scrollbar { width:6px; }
.dept .dbody::-webkit-scrollbar-thumb { background:rgba(26,100,196,.3); border-radius:3px; }
a.tl { font-size:15px; padding:11px 13px; border-radius:13px; font-weight:800; color:#152B3E;
  display:flex; align-items:center; gap:9px; text-decoration:none; letter-spacing:.02em;
  line-height:1.3; transition:transform .18s ease, box-shadow .18s ease;
  background:linear-gradient(150deg,rgba(255,255,255,.9),rgba(228,244,255,.66));
  border:1px solid rgba(255,255,255,1);
  box-shadow:inset 0 1px 0 rgba(255,255,255,1), 0 0 0 1px rgba(158,208,244,.5),
             0 2px 0 rgba(198,228,250,.95), 0 4px 0 rgba(166,206,240,.55),
             0 9px 15px -6px rgba(16,60,110,.28); }
a.tl:hover { transform:translateY(-3px);
  box-shadow:inset 0 1px 0 rgba(255,255,255,1), 0 0 0 1px rgba(120,190,240,.75),
             0 2px 0 rgba(198,228,250,.95), 0 7px 0 rgba(166,206,240,.6),
             0 18px 26px -8px rgba(16,60,110,.4); }
a.tl::before { content:"▶"; font-size:9px; flex:none; }
.dept-pmc a.tl::before { color:#D97706; }
.dept-pc  a.tl::before { color:#0369A1; }
.dept-mc  a.tl::before { color:#2563EB; }
.dept-wh  a.tl::before { color:#4F46E5; }
.dept-ps  a.tl::before { color:#0D9488; }

/* ── 底部流程軌（同時是輪播選擇器） ── */
.car-rail { display:flex; align-items:stretch; justify-content:center; gap:6px;
  margin-top:16px; flex-wrap:wrap; position:relative; z-index:3;
  animation:riseIn .6s ease-out .55s backwards; }
.car-rail .ra { display:flex; align-items:center; color:#1668C6; font-size:19px; font-weight:900;
  opacity:.5; flex:none; }
.rl { cursor:pointer; user-select:none; flex:0 0 158px; text-align:center;
  border-radius:14px; padding:9px 8px 10px; text-decoration:none;
  transition:transform .18s ease, box-shadow .18s ease, background .18s ease;
  background:linear-gradient(150deg,rgba(255,255,255,.78),rgba(228,244,255,.56));
  border:1px solid rgba(255,255,255,1);
  box-shadow:inset 0 1px 0 rgba(255,255,255,1), 0 0 0 1px rgba(158,208,244,.45),
             0 2px 0 rgba(198,228,250,.9), 0 4px 0 rgba(166,206,240,.5),
             0 10px 16px -7px rgba(16,60,110,.26);
  animation:railHi 30s linear calc(var(--i) * 6s - 30s) infinite; }
.rl b { display:block; font-size:15px; font-weight:800; color:#152B3E; line-height:1.2; }
.rl small { display:block; font-size:11px; font-weight:700; color:#2B4557; margin-top:3px;
  font-family:"Consolas",monospace; letter-spacing:.08em; }
.rl i { display:block; width:26px; height:4px; border-radius:99px; margin:6px auto 0; opacity:.35;
  background:currentColor; transition:opacity .2s ease, width .2s ease; }
.rl:hover { transform:translateY(-3px); }
.rl-pmc { color:#D97706; } .rl-pc { color:#0369A1; } .rl-mc { color:#2563EB; }
.rl-wh  { color:#4F46E5; } .rl-ps { color:#0D9488; }
@keyframes railHi {
  0%,  17% { background:linear-gradient(150deg,rgba(255,255,255,.98),rgba(222,240,255,.92));
             box-shadow:inset 0 1px 0 rgba(255,255,255,1), 0 0 0 2px currentColor,
                        0 3px 0 rgba(198,228,250,.95), 0 6px 0 rgba(166,206,240,.6),
                        0 16px 24px -8px rgba(16,60,110,.4);
             transform:translateY(-3px); }
  21%, 95% { background:linear-gradient(150deg,rgba(255,255,255,.78),rgba(228,244,255,.56));
             box-shadow:inset 0 1px 0 rgba(255,255,255,1), 0 0 0 1px rgba(158,208,244,.45),
                        0 2px 0 rgba(198,228,250,.9), 0 4px 0 rgba(166,206,240,.5),
                        0 10px 16px -7px rgba(16,60,110,.26);
             transform:translateY(0); }
  100%     { background:linear-gradient(150deg,rgba(255,255,255,.98),rgba(222,240,255,.92));
             box-shadow:inset 0 1px 0 rgba(255,255,255,1), 0 0 0 2px currentColor,
                        0 3px 0 rgba(198,228,250,.95), 0 6px 0 rgba(166,206,240,.6),
                        0 16px 24px -8px rgba(16,60,110,.4);
             transform:translateY(-3px); } }

/* ── 手動選片：勾到哪一格就停在哪一格 ── */
.car-wrap:has(.dsr-m:checked) .dept,
.car-wrap:has(.dsr-m:checked) .rl { animation:none; }
.car-wrap:has(.dsr-m:checked) .rl { transform:none;
  background:linear-gradient(150deg,rgba(255,255,255,.78),rgba(228,244,255,.56));
  box-shadow:inset 0 1px 0 rgba(255,255,255,1), 0 0 0 1px rgba(158,208,244,.45),
             0 2px 0 rgba(198,228,250,.9), 0 4px 0 rgba(166,206,240,.5),
             0 10px 16px -7px rgba(16,60,110,.26); }
.car-wrap:has(#ds1:checked) .dept-pmc{--s:0;--a:0;--o:1} .car-wrap:has(#ds1:checked) .dept-pc{--s:1;--a:1;--o:.74} .car-wrap:has(#ds1:checked) .dept-mc{--s:2;--a:2;--o:0} .car-wrap:has(#ds1:checked) .dept-wh{--s:-2;--a:2;--o:0} .car-wrap:has(#ds1:checked) .dept-ps{--s:-1;--a:1;--o:.74}
.car-wrap:has(#ds2:checked) .dept-pmc{--s:-1;--a:1;--o:.74} .car-wrap:has(#ds2:checked) .dept-pc{--s:0;--a:0;--o:1} .car-wrap:has(#ds2:checked) .dept-mc{--s:1;--a:1;--o:.74} .car-wrap:has(#ds2:checked) .dept-wh{--s:2;--a:2;--o:0} .car-wrap:has(#ds2:checked) .dept-ps{--s:-2;--a:2;--o:0}
.car-wrap:has(#ds3:checked) .dept-pmc{--s:-2;--a:2;--o:0} .car-wrap:has(#ds3:checked) .dept-pc{--s:-1;--a:1;--o:.74} .car-wrap:has(#ds3:checked) .dept-mc{--s:0;--a:0;--o:1} .car-wrap:has(#ds3:checked) .dept-wh{--s:1;--a:1;--o:.74} .car-wrap:has(#ds3:checked) .dept-ps{--s:2;--a:2;--o:0}
.car-wrap:has(#ds4:checked) .dept-pmc{--s:2;--a:2;--o:0} .car-wrap:has(#ds4:checked) .dept-pc{--s:-2;--a:2;--o:0} .car-wrap:has(#ds4:checked) .dept-mc{--s:-1;--a:1;--o:.74} .car-wrap:has(#ds4:checked) .dept-wh{--s:0;--a:0;--o:1} .car-wrap:has(#ds4:checked) .dept-ps{--s:1;--a:1;--o:.74}
.car-wrap:has(#ds5:checked) .dept-pmc{--s:1;--a:1;--o:.74} .car-wrap:has(#ds5:checked) .dept-pc{--s:2;--a:2;--o:0} .car-wrap:has(#ds5:checked) .dept-mc{--s:-2;--a:2;--o:0} .car-wrap:has(#ds5:checked) .dept-wh{--s:-1;--a:1;--o:.74} .car-wrap:has(#ds5:checked) .dept-ps{--s:0;--a:0;--o:1}
.car-wrap:has(#ds1:checked) .rl-pmc, .car-wrap:has(#ds2:checked) .rl-pc,
.car-wrap:has(#ds3:checked) .rl-mc,  .car-wrap:has(#ds4:checked) .rl-wh,
.car-wrap:has(#ds5:checked) .rl-ps {
  transform:translateY(-3px);
  background:linear-gradient(150deg,rgba(255,255,255,.98),rgba(222,240,255,.92));
  box-shadow:inset 0 1px 0 rgba(255,255,255,1), 0 0 0 2px currentColor,
             0 3px 0 rgba(198,228,250,.95), 0 6px 0 rgba(166,206,240,.6),
             0 16px 24px -8px rgba(16,60,110,.4); }
.car-wrap:has(#ds1:checked) .rl-pmc i, .car-wrap:has(#ds2:checked) .rl-pc i,
.car-wrap:has(#ds3:checked) .rl-mc i,  .car-wrap:has(#ds4:checked) .rl-wh i,
.car-wrap:has(#ds5:checked) .rl-ps i { opacity:1; width:46px; }

/* ── 自動／手動提示 ── */
.car-tip { margin-top:11px; text-align:center; font-size:12.5px; color:#2B4557; font-weight:600;
  letter-spacing:.06em; position:relative; z-index:3;
  animation:riseIn .6s ease-out .65s backwards; }
.car-tip .auto-btn { cursor:pointer; user-select:none; display:inline-flex; align-items:center; gap:6px;
  font-weight:800; color:#0C4187; border-radius:99px; padding:5px 14px; margin-right:8px;
  background:linear-gradient(150deg,rgba(255,255,255,.9),rgba(228,244,255,.66));
  border:1px solid rgba(255,255,255,1);
  box-shadow:0 0 0 1px rgba(158,208,244,.5), 0 2px 0 rgba(198,228,250,.9),
             0 8px 14px -6px rgba(16,60,110,.28);
  transition:transform .16s ease; }
.car-tip .auto-btn:hover { transform:translateY(-2px); }
.car-wrap:has(#dsAuto:checked) .car-tip .auto-btn { color:#fff;
  background:linear-gradient(150deg,#2C86D8,#1668C6);
  box-shadow:0 0 0 1px rgba(22,104,198,.6), 0 2px 0 rgba(150,200,240,.85),
             0 10px 16px -6px rgba(16,60,110,.42); }

/* ══════════ 底部標語 / 提示 ══════════ */
.arch-tagline { margin-top:18px; text-align:center; padding:16px 28px; border-radius:16px;
  background:linear-gradient(150deg,rgba(255,255,255,.86),rgba(226,243,255,.66));
  border:1px solid rgba(255,255,255,1);
  color:#0E2233; font-size:16.5px; font-weight:800; letter-spacing:.16em;
  box-shadow:inset 0 1px 0 rgba(255,255,255,1), 0 0 0 1px rgba(158,208,244,.5),
             0 3px 0 rgba(198,228,250,.9), 0 6px 0 rgba(166,206,240,.5),
             0 18px 28px -12px rgba(16,60,110,.32);
  animation:riseIn .6s ease-out .75s backwards; }
.upload-hint { margin-top:12px; text-align:center; padding:13px 20px; border-radius:13px;
  background:rgba(255,255,255,.55); border:1px dashed rgba(90,150,215,.55);
  font-size:14px; color:#2B4557; font-weight:600; letter-spacing:.03em;
  animation:riseIn .6s ease-out .85s backwards; }

@keyframes riseIn { from { opacity:0; transform:translateY(14px); } to { opacity:1; transform:translateY(0); } }

/* ══════════ 窄螢幕 ══════════ */
@media (max-width:1180px) {
  .rl { flex:0 0 132px; }
  .arch-title h2 { font-size:32px; }
}

@media (prefers-reduced-motion: reduce) {
  .dept, .rl, .ar-scene .globe, .ar-scene .holo, .ar-scene .holo img,
  .ar-scene .holo::after, .oval-center::after, .oval-center .hudc {
    animation:none !important; }
  /* 動畫關掉時要給定槽位，否則五張會疊在正中央 */
  .dept-pmc{--s:0;--a:0;--o:1} .dept-pc{--s:1;--a:1;--o:.74} .dept-mc{--s:2;--a:2;--o:0}
  .dept-wh{--s:-2;--a:2;--o:0} .dept-ps{--s:-1;--a:1;--o:.74}
  .dept { transition:none !important; }
}
</style>

<!-- ══ 白晝科技場景 ══ -->
<div class="ar-scene" aria-hidden="true">
  <i class="ceil"></i><i class="ceil2"></i>
  <i class="ray r1"></i><i class="ray r2"></i><i class="ray r3"></i>
  <div class="wall">
    <div class="wp" style="left:0;top:16px;width:150px;height:112px">
      <div class="wl" style="left:14px;top:18px;width:92px"></div>
      <div class="wl" style="left:14px;top:34px;width:62px;opacity:.6"></div>
      <div class="wl" style="left:14px;top:50px;width:80px;opacity:.45"></div>
    </div>
    <div class="wp" style="left:0;top:152px;width:150px;height:100px">
      <div class="wl" style="left:14px;top:18px;width:74px"></div>
      <div class="wl" style="left:14px;top:34px;width:100px;opacity:.55"></div>
    </div>
    <div class="wp" style="left:172px;top:176px;width:206px;height:126px">
      <div class="wb" style="left:16px;width:16px;height:40px;background:#A8D6F4"></div>
      <div class="wb" style="left:39px;width:16px;height:62px;background:#93CBF1"></div>
      <div class="wb" style="left:62px;width:16px;height:47px;background:#B4DDF6"></div>
      <div class="wb" style="left:85px;width:16px;height:83px;background:#86C4EE"></div>
      <div class="wb" style="left:108px;width:16px;height:56px;background:#A0D2F3"></div>
      <div class="wb" style="left:131px;width:16px;height:72px;background:#8CC7EF"></div>
      <div class="wb" style="left:154px;width:16px;height:37px;background:#BCE2F8"></div>
    </div>
    <div class="wp" style="left:172px;top:22px;width:92px;height:92px">
      <svg viewBox="0 0 150 150" style="position:absolute;inset:0;width:100%;height:100%">
        <circle cx="75" cy="75" r="44" fill="none" stroke="rgba(150,205,240,.6)" stroke-width="18"/>
        <circle cx="75" cy="75" r="44" fill="none" stroke="#7FBCEC" stroke-width="18"
                stroke-dasharray="160 116" stroke-linecap="round" transform="rotate(-90 75 75)"/>
      </svg>
    </div>
  </div>
  <div class="wall lft">
    <div class="wp" style="right:0;top:34px;width:150px;height:104px">
      <div class="wl" style="left:14px;top:18px;width:88px"></div>
      <div class="wl" style="left:14px;top:34px;width:58px;opacity:.6"></div>
      <div class="wl" style="left:14px;top:50px;width:74px;opacity:.45"></div>
    </div>
    <div class="wp" style="right:0;top:186px;width:214px;height:118px">
      <svg viewBox="0 0 380 184" style="position:absolute;inset:0;width:100%;height:100%">
        <path d="M0,140 C60,120 90,60 150,72 C210,84 240,30 300,44 C340,54 360,96 380,88 L380,184 L0,184 Z"
              fill="rgba(150,205,240,.34)"/>
        <path d="M0,160 C70,148 100,104 160,112 C220,120 250,74 310,86 C348,94 364,124 380,118 L380,184 L0,184 Z"
              fill="rgba(120,185,232,.32)"/>
      </svg>
    </div>
  </div>
  <svg class="globe" viewBox="0 0 400 400">
    <defs>
      <radialGradient id="args" cx="34%" cy="26%" r="78%">
        <stop offset="0%" stop-color="#F4FAFF"/><stop offset="46%" stop-color="#BCDFF7"/>
        <stop offset="100%" stop-color="#6BAADE"/></radialGradient>
      <radialGradient id="argf" cx="34%" cy="26%" r="76%">
        <stop offset="0%" stop-color="#fff" stop-opacity="1"/>
        <stop offset="62%" stop-color="#fff" stop-opacity=".7"/>
        <stop offset="100%" stop-color="#fff" stop-opacity=".12"/></radialGradient>
      <mask id="argm"><circle cx="200" cy="200" r="150" fill="url(#argf)"/></mask>
      <pattern id="argd" width="10" height="10" patternUnits="userSpaceOnUse">
        <circle cx="2.2" cy="2.2" r="1.8" fill="#3E90D8"/></pattern>
    </defs>
    <circle cx="200" cy="200" r="184" fill="none" stroke="rgba(140,200,245,.5)" stroke-width="1.5"/>
    <circle cx="200" cy="200" r="168" fill="rgba(150,210,250,.2)"/>
    <circle cx="200" cy="200" r="150" fill="url(#args)"/>
    <g mask="url(#argm)"><circle cx="200" cy="200" r="150" fill="url(#argd)" opacity=".9"/></g>
    <g fill="none" stroke="rgba(38,110,180,.32)" stroke-width="1.4">
      <ellipse cx="200" cy="200" rx="150" ry="52"/><ellipse cx="200" cy="200" rx="150" ry="104"/>
      <ellipse cx="200" cy="200" rx="52" ry="150"/><ellipse cx="200" cy="200" rx="104" ry="150"/>
      <circle cx="200" cy="200" r="150"/></g>
    <path d="M64 132 A150 150 0 0 1 176 54" fill="none" stroke="rgba(255,255,255,.95)"
          stroke-width="6" stroke-linecap="round"/>
    <circle cx="200" cy="200" r="150" fill="none" stroke="rgba(70,150,215,.5)" stroke-width="2"/>
  </svg>
  <i class="floor"></i><i class="grid"></i><i class="pod"></i><i class="pod2"></i>
  <i class="mirror"></i><i class="topfade"></i><i class="vig"></i>
  <span class="holo holo-l">
    <img src="data:image/jpeg;base64,__APP_IMG_FACTORY__" alt=""/>
    <img src="data:image/jpeg;base64,__APP_IMG_POWER__" alt=""/>
    <img src="data:image/jpeg;base64,__APP_IMG_TRAIN__" alt=""/>
  </span>
  <span class="holo holo-r">
    <img src="data:image/jpeg;base64,__APP_IMG_R_AUTO__" alt=""/>
    <img src="data:image/jpeg;base64,__APP_IMG_R_SWITCH__" alt=""/>
    <img src="data:image/jpeg;base64,__APP_IMG_R_ROAD__" alt=""/>
  </span>
</div>

<div class="arch-title">
  <h2>__FLOW_TITLE__</h2>
  <div class="sub">__FLOW_SUB__</div>
  <div class="divider"></div>
</div>

<div class="arch-main">
  <div class="oval-center">
    <i class="hudc tl"></i><i class="hudc tr"></i><i class="hudc bl"></i><i class="hudc br"></i>

    <div class="oval-hdr">
      <span class="ov-icon"><svg width="70" height="70" viewBox="0 0 100 100" fill="none" xmlns="http://www.w3.org/2000/svg">
        <defs>
          <radialGradient id="coreOrb" cx="38%" cy="32%" r="78%">
            <stop offset="0%" stop-color="#ffffff"/>
            <stop offset="32%" stop-color="#7FC6F4"/>
            <stop offset="72%" stop-color="#1668C6"/>
            <stop offset="100%" stop-color="#0B3F86"/>
          </radialGradient>
          <linearGradient id="coreRing" x1="0" y1="0" x2="100" y2="100" gradientUnits="userSpaceOnUse">
            <stop offset="0%" stop-color="#3FA0E8"/>
            <stop offset="50%" stop-color="#1668C6"/>
            <stop offset="100%" stop-color="#5B8BE0"/>
          </linearGradient>
          <radialGradient id="coreAmb" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stop-color="#7FC6F4" stop-opacity="0.45"/>
            <stop offset="100%" stop-color="#7FC6F4" stop-opacity="0"/>
          </radialGradient>
        </defs>
        <circle cx="50" cy="50" r="44" fill="url(#coreAmb)"/>
        <g>
          <ellipse cx="50" cy="50" rx="41" ry="15" stroke="url(#coreRing)" stroke-width="2.2" opacity="0.9"/>
          <ellipse cx="50" cy="50" rx="41" ry="15" stroke="url(#coreRing)" stroke-width="2.2" opacity="0.75" transform="rotate(60 50 50)"/>
          <ellipse cx="50" cy="50" rx="41" ry="15" stroke="url(#coreRing)" stroke-width="2.2" opacity="0.75" transform="rotate(120 50 50)"/>
          <animateTransform attributeName="transform" type="rotate" from="0 50 50" to="360 50 50" dur="16s" repeatCount="indefinite"/>
        </g>
        <g>
          <circle cx="91" cy="50" r="3.4" fill="#1668C6"/>
          <circle cx="9" cy="50" r="2.6" fill="#5B8BE0"/>
          <animateTransform attributeName="transform" type="rotate" from="0 50 50" to="360 50 50" dur="9s" repeatCount="indefinite"/>
        </g>
        <circle cx="50" cy="50" r="15.5" fill="url(#coreOrb)"/>
        <circle cx="50" cy="50" r="15.5" fill="none" stroke="#ffffff" stroke-width="1" opacity="0.85"/>
        <ellipse cx="45" cy="44" rx="6" ry="4" fill="#ffffff" opacity="0.55"/>
      </svg></span>
      <div class="ov-flow">__FLOW_CHAIN__</div>
    </div>

    <!-- ══ 5 塊主題 · 3D 旋轉輪播 ══ -->
    <div class="car-wrap">
      <input type="radio" name="deptsel" id="dsAuto" class="dsr" checked>
      <input type="radio" name="deptsel" id="ds1" class="dsr dsr-m">
      <input type="radio" name="deptsel" id="ds2" class="dsr dsr-m">
      <input type="radio" name="deptsel" id="ds3" class="dsr dsr-m">
      <input type="radio" name="deptsel" id="ds4" class="dsr dsr-m">
      <input type="radio" name="deptsel" id="ds5" class="dsr dsr-m">

      <div class="car-stage">
        <div class="car-ring">
          <div class="dept dept-pmc" style="--i:0">
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
          <div class="dept dept-pc" style="--i:1">
            <div class="dhdr">
              <span class="di">📊</span>
              <div class="dn">__DEPT_PC__</div>
              <div class="ds">Production Control</div>
            </div>
            <div class="dbody">
              <a href="/full_material_trace" target="_self" class="tl">__L_FULL_TRACE__</a>
              <a href="/monthly_cost" target="_self" class="tl">__L_MONTHLY_COST__</a>
              <a href="/kanban" target="_self" class="tl">__L_KANBAN__</a>
              <a href="/scheduling" target="_self" class="tl">__L_SCHEDULING__</a>
              <a href="/outsource_schedule" target="_self" class="tl">__L_OUTSOURCE_SCH__</a>
              <a href="/loss_rate" target="_self" class="tl">__L_LOSS_RATE__</a>
            </div>
          </div>
          <div class="dept dept-mc" style="--i:2">
            <div class="dhdr">
              <span class="di">📦</span>
              <div class="dn">__DEPT_MC__</div>
              <div class="ds">Material Control</div>
            </div>
            <div class="dbody">
              <a href="/h2o" target="_self" class="tl">__L_H2O__</a>
              <a href="/guozhi" target="_self" class="tl">__L_GUOZHI__</a>
              <a href="/factory" target="_self" class="tl">__L_FACTORY__</a>
            </div>
          </div>
          <div class="dept dept-wh" style="--i:3">
            <div class="dhdr">
              <span class="di">🏬</span>
              <div class="dn">__DEPT_WH__</div>
              <div class="ds">Warehouse Management</div>
            </div>
            <div class="dbody">
              <a href="/daily_inbound" target="_self" class="tl">__L_DAILY_INBOUND__</a>
              <a href="/daily_picking" target="_self" class="tl">__L_DAILY_PICKING__</a>
              <a href="/wh_staff" target="_self" class="tl">__L_WH_STAFF__</a>
              <a href="/wh_dashboard" target="_self" class="tl">__L_WH_DASHBOARD__</a>
            </div>
          </div>
          <div class="dept dept-ps" style="--i:4">
            <div class="dhdr">
              <span class="di">🛠</span>
              <div class="dn">__DEPT_PS__</div>
              <div class="ds">__DEPT_PS_SUB__</div>
            </div>
            <div class="dbody">
              <a href="/assembly" target="_self" class="tl">__L_ASSEMBLY__</a>
              <a href="/test_station" target="_self" class="tl">__L_TEST__</a>
              <a href="/packaging" target="_self" class="tl">__L_PACKAGING__</a>
              <a href="/total_worktime" target="_self" class="tl">__L_WORKTIME__</a>
            </div>
          </div>
        </div>
      </div>

      <div class="car-rail">
        <label for="ds1" class="rl rl-pmc" style="--i:0"><b>PMC</b><small>PROD. MATERIAL</small><i></i></label>
        <span class="ra">&rarr;</span>
        <label for="ds2" class="rl rl-pc" style="--i:1"><b>__DEPT_PC__</b><small>PRODUCTION CTRL</small><i></i></label>
        <span class="ra">&rarr;</span>
        <label for="ds3" class="rl rl-mc" style="--i:2"><b>__DEPT_MC__</b><small>MATERIAL CTRL</small><i></i></label>
        <span class="ra">&rarr;</span>
        <label for="ds4" class="rl rl-wh" style="--i:3"><b>__DEPT_WH__</b><small>WAREHOUSE</small><i></i></label>
        <span class="ra">&rarr;</span>
        <label for="ds5" class="rl rl-ps" style="--i:4"><b>__DEPT_PS__</b><small>PROCESS STATION</small><i></i></label>
      </div>

      <div class="car-tip">
        <label for="dsAuto" class="auto-btn">&#8635; 自動輪播</label>
        點下方流程格可停在該部門 &middot; 滑鼠移到卡片上會自動暫停
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
        "__APP_IMG_FACTORY__": _boy_part_b64("app_factory.jpg"),
        "__APP_IMG_POWER__": _boy_part_b64("app_power.jpg"),
        "__APP_IMG_TRAIN__": _boy_part_b64("app_train.jpg"),
        "__APP_IMG_R_AUTO__": _boy_part_b64("app_r_auto.jpg"),
        "__APP_IMG_R_SWITCH__": _boy_part_b64("app_r_switch.jpg"),
        "__APP_IMG_R_ROAD__": _boy_part_b64("app_r_road.jpg"),
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
