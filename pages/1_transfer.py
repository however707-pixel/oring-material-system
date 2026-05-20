import streamlit as st
import pandas as pd
import math
from datetime import datetime
import io
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
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
st.set_page_config(page_title="工單調撥決策看板", page_icon="📊", layout="wide", initial_sidebar_state="expanded")
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
    title="工單調撥決策看板",
    subtitle="Work Order Transfer Decision Board &nbsp;·&nbsp; ORing Industrial Networking",
    badge="Material Control · MC",
    show_logo=False,
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

with st.sidebar:
    st.divider()
    st.markdown(f"### {t('settings')}")

    uploaded_file = st.file_uploader(t("upload_label"), type=["csv", "xlsx", "xls"])

    analysis_date = st.date_input(t("date_start"), datetime(2026, 5, 1), format="YYYY/MM/DD")
    end_date      = st.date_input(t("date_end"),   datetime(2026, 5, 31), format="YYYY/MM/DD")
    if end_date < analysis_date:
        st.error(t("date_err"))
        end_date = analysis_date

    days_range = (end_date - analysis_date).days + 1
    st.caption(f"📆 {t('date_caption')} **{days_range}** {t('date_caption2')}（{analysis_date} ～ {end_date}）")

    st.divider()

    mode_all    = t("mode_all")
    mode_filter = t("mode_filter")
    wh_filter_mode = st.radio(t("mode_label"), [mode_all, mode_filter], index=0)
    wh_filter_target = None
    if wh_filter_mode == mode_filter:
        wh_cols = st.session_state.get("wh_columns", [])
        if wh_cols:
            wh_filter_target = st.selectbox(t("wh_select"), wh_cols)
        else:
            st.caption(t("wh_hint"))

    st.divider()
    st.info(t("info_body"))
    st.caption(t("fmt_support"))

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
    st.info("👈 請在左側上傳「供需表」開始分析")
    st.markdown("""
    <div style="background:#f0fdf4;border:1.5px dashed #86efac;border-radius:12px;padding:20px 24px;margin-top:16px;">
    <b style="color:#15803d;font-size:1rem;">📋 操作步驟</b>
    <ol style="color:#374151;margin-top:10px;line-height:2.2;">
      <li>ERP → 供需管理 → <b>供需表（分倉）</b> → 匯出 Excel，上傳至左側</li>
      <li>設定<b>分析起始日</b>與<b>結束日</b>（預設為當月）</li>
      <li>系統自動展開各工單 BOM，對應各倉庫存量並計算缺料</li>
      <li>可點選任一料號列，查看各倉詳細調撥建議</li>
      <li>點擊「⬇️ 下載調撥建議」匯出 Excel 供物管執行</li>
    </ol>
    <br>
    <b style="color:#15803d;">🎯 分類邏輯</b>
    <table style="margin-top:8px;width:100%;border-collapse:collapse;font-size:0.88rem;">
      <tr style="background:#dcfce7;"><td style="padding:5px 10px;">🟢 充足</td><td style="padding:5px 10px;">預計結存 ≥ 0，庫存足夠應付本期需求</td></tr>
      <tr><td style="padding:5px 10px;">🔴 缺料</td><td style="padding:5px 10px;">預計結存 &lt; 0，總需求超過可用庫存</td></tr>
      <tr style="background:#dcfce7;"><td style="padding:5px 10px;">🟡 可調撥</td><td style="padding:5px 10px;">製造倉不足，但其他倉尚有庫存可轉撥</td></tr>
      <tr><td style="padding:5px 10px;">⬜ 無資料</td><td style="padding:5px 10px;">供需表中未找到此料號，無法判斷庫存狀況</td></tr>
    </table>
    <br>
    <span style="color:#6b7280;font-size:0.82rem;">💡 欄位顏色說明：紅底 = 缺料倉別；數字為預計結存量，負數表示缺料</span>
    </div>
    """, unsafe_allow_html=True)
    with st.expander(t("fmt_title")):
        st.markdown(t("fmt_body"))
        st.caption(t("fmt_support"))
