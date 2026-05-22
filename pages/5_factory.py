import streamlit as st
import pandas as pd
import math
import io
import sys
import os
from datetime import datetime
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from utils.shared import ensure_calamine, inject_css, render_header, render_sidebar

ensure_calamine()

st.set_page_config(page_title="廠內配料表", page_icon="🏭", layout="wide", initial_sidebar_state="expanded")
inject_css()
render_header(
    title="廠內配料表",
    subtitle="Factory Internal Material Allocation &nbsp;·&nbsp; ORing Industrial Networking",
    badge="Material Control · MC",
    show_logo=False,
)
render_sidebar()

VALID_SRC = {'電子倉', '機構倉', '半成品倉', '成品倉'}

# 廠內排程.xlsx 欄位位置（0-indexed，第1列為欄名，跳過）
#   A(0)=料號  B(1)=品名  F(5)=工單單號  H(7)=需求數量
COL_PNO    = 0   # A: 料號
COL_NAME   = 1   # B: 品名
COL_WO     = 5   # F: 工單單號
COL_DEMAND = 7   # H: 需求數量

# =========================
# Sidebar 設定
# =========================
with st.sidebar:
    st.divider()
    st.markdown("### ⚙️ 設定")

    shortage_file = st.file_uploader("📂 上傳廠內排程表（工單缺料）", type=["xlsx", "xls", "csv"])
    sd_file       = st.file_uploader("📂 上傳供需表",                  type=["xlsx", "xls", "csv"])

    st.markdown("**📅 分析區間**")
    date_start = st.date_input("起始日", datetime(2026, 5, 1),  format="YYYY/MM/DD")
    date_end   = st.date_input("結束日", datetime(2026, 5, 31), format="YYYY/MM/DD")

    if date_end < date_start:
        st.error("⚠️ 結束日不可早於起始日！")

    days = (date_end - date_start).days + 1
    st.caption(f"共 **{days}** 天（{date_start} ～ {date_end}）")

    st.divider()
    st.info(
        "💡 **配料邏輯**\n\n"
        "1️⃣ 從廠內排程表取得工單需求量（H欄）\n\n"
        "2️⃣ 從供需表計算四個倉庫存：\n"
        "　　電子倉／機構倉／半成品倉／成品倉\n\n"
        "3️⃣ 四倉庫存 ≥ 需求量 → **✅ 齊料**\n\n"
        "4️⃣ 四倉庫存 < 需求量 → 缺料，顯示\n"
        "　　供需表中的**預計進貨日＋數量**"
    )

# =========================
# 主畫面 - 空狀態
# =========================
if not shortage_file or not sd_file:
    st.info("👈 請在左側上傳「廠內排程表」及「供需表」開始分析")
    st.markdown("""
    <div style="background:#f0fdf4;border:1.5px dashed #86efac;border-radius:12px;padding:20px 24px;margin-top:16px;">
    <b style="color:#15803d;font-size:1rem;">📋 操作步驟</b>
    <ol style="color:#374151;margin-top:10px;line-height:2.2;">
      <li>ERP → 製令系統 → 匯出 <b>廠內排程表（工單缺料明細）</b>，上傳至左側</li>
      <li>ERP → 供需管理 → 匯出 <b>供需表（分倉）</b>，上傳至左側</li>
      <li>設定<b>分析區間</b>（起始日 ～ 結束日）</li>
    </ol>
    <br>
    <b style="color:#15803d;">🎯 判斷邏輯</b>
    <table style="margin-top:8px;width:100%;border-collapse:collapse;font-size:0.88rem;">
      <tr style="background:#dcfce7;">
        <td style="padding:6px 10px;">✅ 齊料</td>
        <td style="padding:6px 10px;">電子倉＋機構倉＋半成品倉＋成品倉 的庫存 ≥ 工單需求量</td>
      </tr>
      <tr>
        <td style="padding:6px 10px;">🔴 缺料</td>
        <td style="padding:6px 10px;">四倉庫存 &lt; 工單需求量，顯示缺料量及供需表中的預計進貨日期與數量</td>
      </tr>
    </table>
    </div>
    """, unsafe_allow_html=True)
    st.stop()

with st.spinner("分析中，請稍候..."):

    # ── 讀廠內排程表（位置讀欄，避免中文亂碼）────────────────────────────────
    try:
        if shortage_file.name.lower().endswith('.csv'):
            sf_raw = None
            for enc in ['utf-8-sig', 'cp950', 'big5']:
                try:
                    sf_raw = pd.read_csv(shortage_file, header=None, encoding=enc)
                    break
                except Exception:
                    shortage_file.seek(0)
            if sf_raw is None:
                st.error("廠內排程表 CSV 無法讀取。")
                st.stop()
        else:
            try:
                sf_raw = pd.read_excel(shortage_file, sheet_name=0, header=None, engine='calamine')
            except Exception:
                shortage_file.seek(0)
                sf_raw = pd.read_excel(shortage_file, sheet_name=0, header=None, engine='openpyxl')
    except Exception as e:
        st.error(f"廠內排程表讀取失敗：{e}")
        st.stop()

    # 跳過第1列（欄名列）
    sf = sf_raw.iloc[1:].reset_index(drop=True).copy()

    if sf.shape[1] <= COL_DEMAND:
        st.error(f"廠內排程表欄位數不足（需至少 {COL_DEMAND+1} 欄，偵測到 {sf.shape[1]} 欄）")
        st.stop()

    sf['_pno']    = sf.iloc[:, COL_PNO].astype(str).str.strip()
    sf['_name']   = sf.iloc[:, COL_NAME].astype(str).str.strip() if sf.shape[1] > COL_NAME else ''
    sf['_wo']     = sf.iloc[:, COL_WO].astype(str).str.strip()   if sf.shape[1] > COL_WO   else ''
    sf['_demand'] = pd.to_numeric(sf.iloc[:, COL_DEMAND], errors='coerce').fillna(0)

    sf = sf[sf['_pno'].notna() & (sf['_pno'] != '') & (sf['_pno'] != 'nan')].copy()

    # ── 讀供需表 ──────────────────────────────────────────────────────────────
    try:
        if sd_file.name.lower().endswith('.csv'):
            sd = None
            for enc in ['utf-8-sig', 'cp950', 'big5']:
                try:
                    sd = pd.read_csv(sd_file, header=0, encoding=enc)
                    break
                except Exception:
                    sd_file.seek(0)
            if sd is None:
                st.error("供需表 CSV 無法讀取。")
                st.stop()
        else:
            try:
                sd = pd.read_excel(sd_file, sheet_name=0, header=0, engine='calamine')
            except Exception:
                sd_file.seek(0)
                sd = pd.read_excel(sd_file, sheet_name=0, header=0, engine='openpyxl')
        sd['日期'] = pd.to_datetime(sd['日期'], errors='coerce')
    except Exception as e:
        st.error(f"供需表讀取失敗：{e}")
        st.stop()

    for col in ['品號', '庫別名稱', '日期', '異動別', '異動數量']:
        if col not in sd.columns:
            st.error(f"供需表找不到「{col}」欄位，請確認檔案格式。")
            st.stop()

    end = pd.Timestamp(date_end)

    # ── Helper 函數 ──────────────────────────────────────────────────────────

    def get_avail(pno, wh_code):
        """計算指定倉可用量（扣除預計進貨及預計生產）"""
        w = sd[(sd['品號'] == pno) & (sd['庫別'] == wh_code)]
        if w.empty: return 0
        dated = w[w['日期'].notna() & w['預計結存'].notna()]
        in_range = dated[dated['日期'] <= end]
        if not in_range.empty:
            last_bal   = in_range.sort_values('日期').iloc[-1]['預計結存']
            planned_in = dated[
                (dated['日期'] <= end) &
                (dated['異動別'].isin(['預計進貨', '預計生產']))
            ]['異動數量'].sum()
            return max(0, last_bal - planned_in)
        init_rows = w[w['日期'].isna()]
        if not init_rows.empty:
            qty = init_rows['異動數量'].dropna()
            if not qty.empty: return max(0, float(qty.iloc[0]))
        return 0

    def avail_4wh(pno):
        """只計算四個有效倉別（電子倉/機構倉/半成品倉/成品倉）的可用量合計"""
        part_sd    = sd[sd['品號'] == pno]
        dated_part = part_sd[part_sd['日期'].notna() & part_sd['庫別名稱'].notna()]
        code_name  = (dated_part[['庫別', '庫別名稱']]
                      .drop_duplicates('庫別')
                      .set_index('庫別')['庫別名稱']
                      .to_dict())
        code_name  = {c: n for c, n in code_name.items() if len(str(c)) <= 12}
        names_with_dated = set(code_name.values())
        dated_codes      = set(code_name.keys())
        total = 0.0
        for wh_code, wh_name in code_name.items():
            if wh_name not in VALID_SRC: continue
            total += get_avail(pno, wh_code)
        # 只有期初行、無日期行（補充）
        init_rows = part_sd[part_sd['日期'].isna() & part_sd['庫別名稱'].isna()]
        for wh_k in init_rows['庫別'].dropna().unique():
            ws = str(wh_k)
            if ws in dated_codes or ws in names_with_dated: continue
            if ws not in VALID_SRC or len(ws) > 12: continue
            qty = init_rows[init_rows['庫別'] == wh_k]['異動數量'].dropna()
            if not qty.empty and float(qty.iloc[0]) > 0:
                total += float(qty.iloc[0])
        return int(total)

    def get_incoming(pno):
        """從供需表抓預計進貨：不限分析區間，格式 MM/DD(數量)"""
        sub = sd[
            (sd['品號'] == pno) &
            (sd['異動別'] == '預計進貨') &
            (sd['日期'].notna())
        ].sort_values('日期')
        if sub.empty: return None
        return '、'.join(
            f"{row['日期'].strftime('%m/%d')}({int(row['異動數量'])})"
            for _, row in sub.iterrows()
        )

    # ── 主分析 ────────────────────────────────────────────────────────────────
    # 同一料號可能出現在多張工單 → 合計需求，庫存只扣一次
    rows = []

    for pno, grp in sf.groupby('_pno'):
        pno_str      = str(pno).strip()
        total_demand = int(grp['_demand'].sum())

        if total_demand <= 0:
            continue

        # 品名
        part_name = str(grp['_name'].iloc[0])
        if part_name in ('', 'nan', 'None'): part_name = ''

        # 涉及的工單（最多顯示5筆）
        wos = [w for w in grp['_wo'].dropna().unique()
               if w not in ('', 'nan', 'None')]
        wo_str = '、'.join(wos[:5]) + ('…' if len(wos) > 5 else '')

        # 四倉可用庫存（供需表）
        avail = avail_4wh(pno_str)

        # 判斷齊料 / 缺料
        if avail >= total_demand:
            # ✅ 齊料
            rows.append({
                '工單單號':           wo_str,
                '料號':               pno,
                '品名':               part_name,
                '工單需求量':         total_demand,
                '四倉可用庫存':       avail,
                '缺料量':             0,
                '狀態':               '✅ 齊料',
                '預計進貨日（含數量）': '',
                '_is_short':          False,
            })
        else:
            # 🔴 缺料 → 抓預計進貨
            shortage   = total_demand - avail
            incoming   = get_incoming(pno_str)
            rows.append({
                '工單單號':           wo_str,
                '料號':               pno,
                '品名':               part_name,
                '工單需求量':         total_demand,
                '四倉可用庫存':       avail,
                '缺料量':             shortage,
                '狀態':               f'🔴 缺料 {shortage:,}',
                '預計進貨日（含數量）': incoming or '—（供需表無預計進貨）',
                '_is_short':          True,
            })

    df_out = pd.DataFrame(rows) if rows else pd.DataFrame()

# ── 統計卡片 ──────────────────────────────────────────────────────────────────
total_pno   = sf['_pno'].nunique()
n_ok        = len(df_out[df_out['_is_short'] == False]) if len(df_out) else 0
n_short     = len(df_out[df_out['_is_short'] == True])  if len(df_out) else 0

col1, col2, col3, col4 = st.columns(4)
col1.metric("工單料號總數",  f"{total_pno} 個")
col2.metric("✅ 齊料",       f"{n_ok} 個")
col3.metric("🔴 缺料",       f"{n_short} 個",
            delta=None if n_short == 0 else "需確認進貨日",
            delta_color="inverse")
col4.metric("缺料量合計",
            f"{int(df_out[df_out['_is_short']==True]['缺料量'].sum()):,}" if n_short > 0 else "0")

st.divider()
st.markdown(f"#### 🏭 廠內配料表　{date_start} ～ {date_end}")

if df_out.empty:
    st.success("✅ 沒有工單需求資料，請確認廠內排程表內容。")
else:
    if n_short > 0:
        pno_list = '、'.join(df_out[df_out['_is_short']==True]['料號'].tolist())
        st.warning(f"**🔴 以下 {n_short} 個料號庫存不足：** {pno_list}", icon="⚠️")

    display_cols = ['工單單號', '料號', '品名', '工單需求量',
                    '四倉可用庫存', '缺料量', '狀態', '預計進貨日（含數量）']
    df_display = df_out[[c for c in display_cols if c in df_out.columns]].copy()

    def _row_style(row):
        if row.get('_is_short', False) if '_is_short' in row.index else False:
            return ['background-color:#fef2f2; color:#991b1b; font-weight:600;'] * len(row)
        return ['background-color:#f0fdf4;'] * len(row)

    # 用 df_out 的 _is_short 對應樣式
    _short_mask = df_out['_is_short'].values

    def _row_style2(row):
        idx = row.name
        if idx < len(_short_mask) and _short_mask[idx]:
            return ['background-color:#fef2f2; color:#991b1b; font-weight:600;'] * len(row)
        return ['background-color:#f0fdf4;'] * len(row)

    st.dataframe(
        df_display.style.apply(_row_style2, axis=1),
        use_container_width=True,
        height=560,
        hide_index=True,
        column_config={
            '預計進貨日（含數量）': st.column_config.TextColumn(width='large'),
            '品名':               st.column_config.TextColumn(width='medium'),
            '工單單號':           st.column_config.TextColumn(width='medium'),
            '狀態':               st.column_config.TextColumn(width='small'),
        }
    )

    # ── 匯出 Excel ────────────────────────────────────────────────────────────
    def build_excel(df, df_meta, start_dt, end_dt):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = '廠內配料表'
        thin   = Side(style='thin', color='FFCCCCCC')
        border = Border(left=thin, right=thin, top=thin, bottom=thin)

        headers    = ['工單單號', '料號', '品名', '工單需求量',
                      '四倉可用庫存', '缺料量', '狀態', '預計進貨日（含數量）']
        col_widths = [28, 32, 28, 12, 14, 12, 14, 40]
        hdr_colors = ['FFF2F2F2', 'FFD9E8FF', 'FFF5F5F5', 'FFE8F4FD',
                      'FFE8F4FD', 'FFFCE4D6', 'FFF2F2F2', 'FFE8F4FD']
        left_cols  = {1, 2, 3, 8}

        total_cols = len(headers)
        merge_end  = chr(64 + total_cols)
        ws.merge_cells(f'A1:{merge_end}1')
        c = ws['A1']
        c.value     = f'廠內配料表　{start_dt.strftime("%Y/%m/%d")} ～ {end_dt.strftime("%Y/%m/%d")}'
        c.font      = Font(name='Arial', bold=True, size=12, color='FFFFFFFF')
        c.fill      = PatternFill('solid', start_color='FF374151')
        c.alignment = Alignment(horizontal='center', vertical='center')
        ws.row_dimensions[1].height = 24

        for i, (h, hc) in enumerate(zip(headers, hdr_colors), 1):
            cell = ws.cell(row=2, column=i, value=h)
            cell.font      = Font(name='Arial', bold=True, size=9)
            cell.fill      = PatternFill('solid', start_color=hc)
            cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
            cell.border    = border
        ws.row_dimensions[2].height = 28

        for r_i, (row_dict, is_short) in enumerate(
                zip(df.to_dict('records'), df_meta['_is_short'].values), 3):
            for c_i, key in enumerate(headers, 1):
                val  = row_dict.get(key)
                cell = ws.cell(row=r_i, column=c_i, value=val)
                cell.border = border
                cell.alignment = Alignment(
                    horizontal='left' if c_i in left_cols else 'center',
                    vertical='center',
                    wrap_text=(c_i == 8),
                )
                if is_short:
                    cell.fill = PatternFill('solid', start_color='FFFCE4EC')
                    cell.font = Font(name='Arial', size=9, bold=True, color='FF991B1B')
                    if c_i == 8:
                        ws.row_dimensions[r_i].height = 42
                else:
                    cell.fill = PatternFill('solid', start_color='FFF0FDF4')
                    cell.font = Font(name='Arial', size=9, color='FF15803D')

        for i, w in enumerate(col_widths, 1):
            ws.column_dimensions[chr(64 + i)].width = w
        ws.freeze_panes = 'A3'

        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        return buf

    buf = build_excel(df_display, df_out, date_start, date_end)
    st.download_button(
        label="⬇️ 匯出廠內配料表（Excel）",
        data=buf,
        file_name=f"廠內配料表_{date_start.strftime('%Y%m%d')}_{date_end.strftime('%Y%m%d')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
