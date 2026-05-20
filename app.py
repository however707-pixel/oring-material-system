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

# 語言切換（側邊欄頂部）
with st.sidebar:
    col_zh, col_en = st.columns(2)
    with col_zh:
        if st.button("🇹🇼 中文", key="btn_zh",
                     type="primary" if st.session_state["lang"] == "zh" else "secondary",
                     use_container_width=True):
            st.session_state["lang"] = "zh"
            st.rerun()
    with col_en:
        if st.button("🇺🇸 EN", key="btn_en",
                     type="primary" if st.session_state["lang"] == "en" else "secondary",
                     use_container_width=True):
            st.session_state["lang"] = "en"
            st.rerun()

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
    """
    期初庫存取得方式（三層）：

    ① 「庫存可用量」行：日期欄='庫存可用量:'，異動別=NaN
       → 「庫別」欄（代碼欄）有正確的倉別名稱（含完全沒有異動的倉）
       → 異動數量欄 = 該倉期初庫存
       → 用「庫別」→「庫別名稱」對照表轉換成中文倉名

    ② 區間內有異動但「庫存可用量」行找不到的倉
       → 用區間內第一筆預計結存 ± 異動數量反推

    ③ 可用量 = 區間末預計結存 - 區間內預計進貨累計
       → 無區間異動的倉，直接用期初庫存

    SPQ 調撥規則：
    - min(可用,缺料) >= SPQ → floor(min/SPQ)*SPQ
    - min(可用,缺料) <  SPQ → 直接給 min(可用,缺料)
    """
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

        # ── 數值轉換 ────────────────────────────────────────────────────────────
        df['異動數量'] = pd.to_numeric(df['異動數量'], errors='coerce').fillna(0)
        df['預計結存'] = pd.to_numeric(df['預計結存'], errors='coerce').fillna(0)
        df['SPQ']     = pd.to_numeric(df['SPQ'],     errors='coerce').fillna(1).clip(lower=1)
        df['日期_str'] = df['日期'].astype(str).str.strip()
        df['日期_parsed'] = pd.to_datetime(df['日期'], errors='coerce')

        # ── 建立「庫別代碼 → 庫別名稱」對照表 ───────────────────────────────────
        wh_map = (
            df[df['庫別名稱'].notna() & df['庫別'].notna()]
            .groupby('庫別')['庫別名稱']
            .first()
            .to_dict()
        )
        for v in df['庫別名稱'].dropna().unique():
            if v not in wh_map:
                wh_map[v] = v

        # ── 期初庫存：從「庫存可用量」行取得 ─────────────────────────────────────
        is_init_row = df['日期_str'] == '庫存可用量:'
        df_init = df[is_init_row & (df['庫別'].notna())].copy()
        df_init['庫別名稱_正確'] = df_init['庫別'].map(wh_map).fillna(df_init['庫別'])
        init_stock = df_init.groupby(['品號', '庫別名稱_正確'])['異動數量'].sum()
        init_stock.index.names = ['品號', '庫別名稱']

        # ── 真實異動行 ────────────────────────────────────────────────────────────
        df_move = df[df['日期_parsed'].notna() & df['庫別名稱'].notna()].copy()

        # ── 分析區間 ──────────────────────────────────────────────────────────────
        base_dt = pd.to_datetime(analysis_date)
        end_dt  = pd.to_datetime(end_date)
        in_mask = (df_move['日期_parsed'] >= base_dt) & (df_move['日期_parsed'] <= end_dt)
        df_period = df_move[in_mask].copy()

        if df_period.empty and init_stock.empty:
            st.warning("所選日期區間內沒有資料，請確認基準日與資料日期範圍是否吻合。")
            return None, None, None

        # ── 區間末預計結存 ────────────────────────────────────────────────────────
        last_in_period = df_period.groupby(['品號', '庫別名稱'])['預計結存'].last()

        # ── 區間內預計進貨累計 ────────────────────────────────────────────────────
        incoming = (
            df_period[df_period['異動別'] == '預計進貨']
            .groupby(['品號', '庫別名稱'])['異動數量']
            .sum()
        )

        # ── 基準日前最後結存 ──────────────────────────────────────────────────────
        before_period = df_move[df_move['日期_parsed'] < base_dt]
        last_before = before_period.groupby(['品號', '庫別名稱'])['預計結存'].last()

        # ── 真實可用量 ────────────────────────────────────────────────────────────
        real_avail = (
            last_in_period - incoming.reindex(last_in_period.index).fillna(0)
        ).combine_first(last_before).combine_first(init_stock)

        # ── 樞紐矩陣 ──────────────────────────────────────────────────────────────
        pivot_df = real_avail.unstack().fillna(0)

        # ── SPQ 對應表 ────────────────────────────────────────────────────────────
        spq_map = df_move.groupby('品號')['SPQ'].last()

        # ── 只保留有缺料（負數）的品號 ────────────────────────────────────────────
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

# 首頁不顯示上傳供需表與顯示模式，預設值供邏輯使用
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
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: transparent; padding: 8px 4px; }

  /* ── 標題 ── */
  .board-title { text-align: center; margin-bottom: 32px; }
  .board-title h2 {
    font-size: 20px; font-weight: 800; color: #1e293b;
    letter-spacing: 0.08em; text-transform: uppercase; margin-bottom: 5px;
    text-shadow: 0 2px 4px rgba(0,0,0,0.08);
  }
  .board-title p { font-size: 13px; color: #64748b; letter-spacing: 0.04em; }

  /* ── Grid ── */
  .flow-grid {
    display: grid;
    grid-template-columns: 1fr 48px 1fr 48px 1fr;
    gap: 0; align-items: start;
  }
  .dept-col { display: flex; flex-direction: column; gap: 0; }

  /* ── 部門 Header（3D card）── */
  .dept-header {
    border-radius: 14px 14px 0 0;
    padding: 18px 0 15px;
    text-align: center;
    position: relative; overflow: hidden;
  }
  .dept-header::after {
    content:''; position:absolute; top:0; left:0; right:0;
    height:1px; background:rgba(255,255,255,0.35);
  }
  .dept-header .dept-icon { font-size: 28px; display: block; margin-bottom: 7px;
    filter: drop-shadow(0 2px 4px rgba(0,0,0,0.25)); }
  .dept-header .dept-name {
    font-size: 18px; font-weight: 800; letter-spacing: 0.04em;
    text-shadow: 0 2px 6px rgba(0,0,0,0.3);
  }
  .dept-header .dept-sub {
    font-size: 11px; margin-top: 3px; opacity: 0.85; letter-spacing: 0.05em;
  }

  .dept-pc .dept-header {
    background: linear-gradient(160deg, #166534, #15803d, #16a34a);
    color: #fff;
    box-shadow: 0 -4px 0 0 #14532d inset, 0 6px 20px rgba(21,128,61,0.4);
  }
  .dept-mc .dept-header {
    background: linear-gradient(160deg, #1e3a8a, #1d4ed8, #2563eb);
    color: #fff;
    box-shadow: 0 -4px 0 0 #1e3a8a inset, 0 6px 20px rgba(29,78,216,0.4);
  }
  .dept-wh .dept-header {
    background: linear-gradient(160deg, #4c1d95, #6d28d9, #7c3aed);
    color: #fff;
    box-shadow: 0 -4px 0 0 #3b0764 inset, 0 6px 20px rgba(109,40,217,0.4);
  }

  /* ── 部門 Body ── */
  .dept-body {
    border-left: 2px solid; border-right: 2px solid; border-bottom: 2px solid;
    border-radius: 0 0 14px 14px; padding: 16px 14px 22px;
    display: flex; flex-direction: column; gap: 10px;
    box-shadow: 0 8px 24px rgba(0,0,0,0.08);
  }
  .dept-pc .dept-body { border-color: #15803d; background: linear-gradient(180deg,#f0fdf4,#dcfce7); }
  .dept-mc .dept-body { border-color: #1d4ed8; background: linear-gradient(180deg,#eff6ff,#dbeafe); }
  .dept-wh .dept-body { border-color: #6d28d9; background: linear-gradient(180deg,#f5f3ff,#ede9fe); }

  /* ── Step Card（3D）── */
  .step-card {
    border-radius: 10px; padding: 11px 14px; cursor: default;
    transition: transform 0.18s cubic-bezier(.34,1.56,.64,1), box-shadow 0.18s;
    position: relative;
  }
  .step-card:hover {
    transform: translateY(-3px) scale(1.01);
    box-shadow: 0 8px 24px rgba(0,0,0,0.14) !important;
  }
  .dept-pc .step-card {
    background: #fff; border: 1px solid #bbf7d0;
    box-shadow: 0 3px 8px rgba(21,128,61,0.1), 0 1px 2px rgba(0,0,0,0.05);
  }
  .dept-mc .step-card {
    background: #fff; border: 1px solid #bfdbfe;
    box-shadow: 0 3px 8px rgba(29,78,216,0.1), 0 1px 2px rgba(0,0,0,0.05);
  }
  .dept-wh .step-card {
    background: #fff; border: 1px solid #ddd6fe;
    box-shadow: 0 3px 8px rgba(109,40,217,0.1), 0 1px 2px rgba(0,0,0,0.05);
  }

  .step-num {
    font-size: 11px; font-weight: 800; letter-spacing: 0.1em;
    text-transform: uppercase; margin-bottom: 4px;
  }
  .dept-pc .step-num { color: #15803d; }
  .dept-mc .step-num { color: #1d4ed8; }
  .dept-wh .step-num { color: #6d28d9; }

  .step-name { font-size: 15px; font-weight: 700; color: #1e293b; }
  .step-sub  { font-size: 11.5px; color: #64748b; margin-top: 3px; }
  .step-arrow {
    display: flex; align-items: center; justify-content: center;
    margin: 1px 0; font-size: 16px;
  }
  .dept-pc .step-arrow { color: #16a34a; }
  .dept-mc .step-arrow { color: #2563eb; }
  .dept-wh .step-arrow { color: #7c3aed; }

  /* ── 連線箭頭 ── */
  .conn-col {
    display: flex; flex-direction: column; align-items: center;
    justify-content: center; padding-top: 72px; gap: 0;
  }
  .conn-row { display: flex; align-items: center; justify-content: center; height: 63px; }
  .conn-wrap { display: flex; flex-direction: column; align-items: center; }
  .conn-arrow {
    width: 40px; height: 2px;
    background: linear-gradient(90deg, #94a3b8, #cbd5e1);
    position: relative; border-radius: 1px;
  }
  .conn-arrow::after {
    content: ''; position: absolute; right: -1px; top: -5px;
    border-left: 9px solid #94a3b8;
    border-top: 6px solid transparent;
    border-bottom: 6px solid transparent;
  }
  .conn-label {
    font-size: 10px; color: #64748b; text-align: center;
    margin-top: 3px; letter-spacing: 0.04em; white-space: nowrap; font-weight: 600;
  }

  /* ── Legend ── */
  .legend {
    display: flex; gap: 24px; justify-content: center;
    margin-top: 26px; flex-wrap: wrap;
  }
  .legend-item { display: flex; align-items: center; gap: 7px; font-size: 12px; color: #64748b; font-weight: 500; }
  .legend-dot { width: 12px; height: 12px; border-radius: 50%; box-shadow: 0 2px 4px rgba(0,0,0,0.2); }
  .legend-line { width: 28px; height: 2px; background: #94a3b8; position: relative; }
  .legend-line::after {
    content:''; position:absolute; right:-1px; top:-4px;
    border-left:7px solid #94a3b8; border-top:5px solid transparent; border-bottom:5px solid transparent;
  }

  /* ── Upload hint ── */
  .upload-hint {
    margin-top: 26px; text-align: center; padding: 16px 24px;
    background: linear-gradient(135deg,#f0f7ff,#f8faff);
    border: 1.5px dashed #93c5fd; border-radius: 12px;
    box-shadow: 0 2px 12px rgba(29,78,216,0.08);
  }
  .upload-hint p { font-size: 13px; color: #64748b; }
  .upload-hint strong { color: #1d4ed8; }
</style>
</head>
<body>

<div class="board-title">
  <h2>__BOARD_TITLE__</h2>
  <p>__BOARD_SUB__</p>
</div>

<div class="flow-grid">

  <!-- PC 生管 -->
  <div class="dept-col dept-pc">
    <div class="dept-header">
      <span class="dept-icon">🏗</span>
      <div class="dept-name">生管 PC</div>
      <div class="dept-sub">Production Control</div>
    </div>
    <div class="dept-body">
      <div class="step-card"><div class="step-num">01 · 接單</div><div class="step-name">客戶訂單確認</div><div class="step-sub">Sales Order Received</div></div>
      <div class="step-arrow">↓</div>
      <div class="step-card"><div class="step-num">02 · 規劃</div><div class="step-name">生產排程規劃</div><div class="step-sub">Production Scheduling</div></div>
      <div class="step-arrow">↓</div>
      <div class="step-card"><div class="step-num">03 · 開單</div><div class="step-name">工單發佈</div><div class="step-sub">Work Order Issued</div></div>
      <div class="step-arrow">↓</div>
      <div class="step-card"><div class="step-num">04 · 追蹤</div><div class="step-name">生產進度追蹤</div><div class="step-sub">Progress Monitoring</div></div>
      <div class="step-arrow">↓</div>
      <div class="step-card"><div class="step-num">05 · 完工</div><div class="step-name">完工確認回報</div><div class="step-sub">Completion Reporting</div></div>
    </div>
  </div>

  <!-- 連線 PC→MC -->
  <div class="conn-col">
    <div class="conn-wrap">
      <div class="conn-row"><div><div class="conn-arrow"></div><div class="conn-label">需求<br>觸發</div></div></div>
      <div class="conn-row" style="height:63px"></div>
      <div class="conn-row"><div><div class="conn-arrow"></div><div class="conn-label">工單<br>下達</div></div></div>
      <div class="conn-row" style="height:63px"></div>
      <div class="conn-row"><div><div class="conn-arrow"></div><div class="conn-label">進度<br>確認</div></div></div>
    </div>
  </div>

  <!-- MC 物管 -->
  <div class="dept-col dept-mc">
    <div class="dept-header">
      <span class="dept-icon">📦</span>
      <div class="dept-name">物管 MC</div>
      <div class="dept-sub">Material Control</div>
    </div>
    <div class="dept-body">
      <div class="step-card"><div class="step-num">01 · 分析</div><div class="step-name">需求與缺料分析</div><div class="step-sub">Demand Analysis</div></div>
      <div class="step-arrow">↓</div>
      <div class="step-card"><div class="step-num">02 · 採購</div><div class="step-name">採購 / 調撥決策</div><div class="step-sub">Purchase / Transfer</div></div>
      <div class="step-arrow">↓</div>
      <div class="step-card"><div class="step-num">03 · 委外</div><div class="step-name">委外調撥確認</div><div class="step-sub">Outsource Confirmation</div></div>
      <div class="step-arrow">↓</div>
      <div class="step-card"><div class="step-num">04 · 追料</div><div class="step-name">料件到貨追蹤</div><div class="step-sub">Material Tracking</div></div>
      <div class="step-arrow">↓</div>
      <div class="step-card"><div class="step-num">05 · 配料</div><div class="step-name">工單配料發料</div><div class="step-sub">Material Kitting</div></div>
    </div>
  </div>

  <!-- 連線 MC→WH -->
  <div class="conn-col">
    <div class="conn-wrap">
      <div class="conn-row" style="height:63px"></div>
      <div class="conn-row"><div><div class="conn-arrow"></div><div class="conn-label">入庫<br>請求</div></div></div>
      <div class="conn-row" style="height:63px"></div>
      <div class="conn-row"><div><div class="conn-arrow"></div><div class="conn-label">備料<br>需求</div></div></div>
      <div class="conn-row"><div><div class="conn-arrow"></div><div class="conn-label">發料<br>指令</div></div></div>
    </div>
  </div>

  <!-- WH 倉管 -->
  <div class="dept-col dept-wh">
    <div class="dept-header">
      <span class="dept-icon">🏬</span>
      <div class="dept-name">倉管 WH</div>
      <div class="dept-sub">Warehouse Management</div>
    </div>
    <div class="dept-body">
      <div class="step-card"><div class="step-num">01 · 驗收</div><div class="step-name">入庫驗收 / IQC</div><div class="step-sub">Goods Receipt &amp; QC</div></div>
      <div class="step-arrow">↓</div>
      <div class="step-card"><div class="step-num">02 · 上架</div><div class="step-name">儲位上架管理</div><div class="step-sub">Putaway &amp; Slotting</div></div>
      <div class="step-arrow">↓</div>
      <div class="step-card"><div class="step-num">03 · 備料</div><div class="step-name">備料 / 領料揀取</div><div class="step-sub">Pick &amp; Preparation</div></div>
      <div class="step-arrow">↓</div>
      <div class="step-card"><div class="step-num">04 · 包裝</div><div class="step-name">出貨包裝作業</div><div class="step-sub">Packing &amp; Shipping</div></div>
      <div class="step-arrow">↓</div>
      <div class="step-card"><div class="step-num">05 · 出貨</div><div class="step-name">出貨確認 / 交運</div><div class="step-sub">Shipment Confirmation</div></div>
    </div>
  </div>

</div>

<div class="legend">
  <div class="legend-item"><div class="legend-dot" style="background:#15803d"></div> 生管 PC</div>
  <div class="legend-item"><div class="legend-dot" style="background:#1d4ed8"></div> 物管 MC</div>
  <div class="legend-item"><div class="legend-dot" style="background:#6d28d9"></div> 倉管 WH</div>
  <div class="legend-item"><div class="legend-line"></div> 跨部門協作</div>
</div>

<div class="upload-hint">
  <p>__UPLOAD_HINT__</p>
</div>

</body>
</html>
"""
    components.html(
        _flow_html
        .replace("__BOARD_TITLE__", t("board_title"))
        .replace("__BOARD_SUB__",   t("board_sub"))
        .replace("__UPLOAD_HINT__", t("upload_hint")),
        height=820, scrolling=False
    )

    with st.expander(t("fmt_title")):
        st.markdown(t("fmt_body"))
        st.caption(t("fmt_support"))

