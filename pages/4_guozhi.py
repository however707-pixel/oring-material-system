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

st.set_page_config(page_title="國智配料表", page_icon="🏭", layout="wide", initial_sidebar_state="expanded")
inject_css()
render_header(
    title="國智配料表",
    subtitle="Kuo Zhi Material Allocation List &nbsp;·&nbsp; ORing Industrial Networking",
    badge="Material Control · MC",
    show_logo=False,
)
render_sidebar()

TANG = '唐佑代工倉'
KUO  = '修研/華盈/國智代工倉'

# =========================
# Sidebar 設定
# =========================
with st.sidebar:
    st.divider()
    st.markdown("### ⚙️ 設定")

    h2o_file = st.file_uploader("📂 上傳 H2O 缺料明細", type=["xlsx", "xls", "csv"])
    sd_file  = st.file_uploader("📂 上傳供需表",         type=["xlsx", "xls", "csv"])

    st.markdown("**📅 分析區間**")
    date_start = st.date_input("起始日", datetime(2026, 5, 1),  format="YYYY/MM/DD")
    date_end   = st.date_input("結束日", datetime(2026, 5, 31), format="YYYY/MM/DD")

    if date_end < date_start:
        st.error("⚠️ 結束日不可早於起始日！")

    days = (date_end - date_start).days + 1
    st.caption(f"共 **{days}** 天（{date_start} ～ {date_end}）")

    st.divider()
    st.info(
        "💡 **分析邏輯**\n\n"
        "從供需表中，找出料號在設定\n"
        "區間內，國智委外廠預計領用量：\n\n"
        f"- 🟢 **國智** → `{KUO}`"
    )

# =========================
# 主畫面
# =========================
if not h2o_file or not sd_file:
    st.markdown("""
    <div style="text-align:center; padding:80px 0; color:#94a3b8;">
        <div style="font-size:3.5rem; margin-bottom:16px;">🏭</div>
        <div style="font-size:1.1rem; font-weight:700; color:#64748b; margin-bottom:8px;">國智配料表</div>
        <div style="font-size:0.85rem;">請從左側上傳 <b>H2O 缺料明細</b> 及 <b>供需表</b> 開始分析</div>
    </div>""", unsafe_allow_html=True)
    st.stop()

with st.spinner("分析中，請稍候..."):
    # 讀 H2O 缺料檔
    try:
        if h2o_file.name.endswith('.csv'):
            for enc in ['utf-8-sig', 'cp950', 'big5']:
                try:
                    h2o = pd.read_csv(h2o_file, header=0, encoding=enc)
                    break
                except Exception:
                    h2o_file.seek(0)
        else:
            h2o = pd.read_excel(h2o_file, sheet_name=0, header=0)
    except Exception as e:
        st.error(f"H2O 缺料明細讀取失敗：{e}")
        st.stop()

    # 讀供需表
    try:
        if sd_file.name.endswith('.csv'):
            for enc in ['utf-8-sig', 'cp950', 'big5']:
                try:
                    sd = pd.read_csv(sd_file, header=0, encoding=enc)
                    break
                except Exception:
                    sd_file.seek(0)
        else:
            sd = pd.read_excel(sd_file, sheet_name=0, header=0)
        sd['日期'] = pd.to_datetime(sd['日期'], errors='coerce')
    except Exception as e:
        st.error(f"供需表讀取失敗：{e}")
        st.stop()

    # 欄位檢查
    if '料號' not in h2o.columns:
        st.error("H2O 缺料明細找不到「料號」欄位，請確認檔案格式。")
        st.stop()
    for col in ['品號', '庫別名稱', '日期', '異動別', '異動數量']:
        if col not in sd.columns:
            st.error(f"供需表找不到「{col}」欄位，請確認檔案格式。")
            st.stop()

    start = pd.Timestamp(date_start)
    end   = pd.Timestamp(date_end)

    spq_map = {}
    if 'SPQ' in sd.columns:
        spq_map = (sd[sd['SPQ'].notna()][['品號','SPQ']]
                   .drop_duplicates('品號')
                   .set_index('品號')['SPQ']
                   .to_dict())

    def apply_spq(qty, spq):
        s = int(spq) if spq and spq > 0 else 1
        if qty <= 0: return 0
        return math.ceil(qty / s) * s

    def end_deficit(df_sd, pno, wh_name):
        sub = df_sd[(df_sd['品號']==pno) & (df_sd['庫別名稱']==wh_name) &
                    (df_sd['日期'] <= end) & df_sd['預計結存'].notna()]
        if sub.empty: return 0
        last_bal = sub.sort_values('日期').iloc[-1]['預計結存']
        return max(0, -last_bal)

    def get_avail(df_sd, pno, wh_code, excl):
        w = df_sd[(df_sd['品號']==pno) & (df_sd['庫別']==wh_code)]
        if w.empty: return 0
        wh_name = w['庫別名稱'].dropna().iloc[0] if w['庫別名稱'].dropna().shape[0]>0 else ''
        if wh_name in excl: return 0
        dated = w[w['日期'].notna() & w['預計結存'].notna()]
        in_range = dated[dated['日期'] <= end]
        if not in_range.empty:
            last_bal = in_range.sort_values('日期').iloc[-1]['預計結存']
            incoming = dated[
                (dated['日期'] >= start) &
                (dated['日期'] <= end) &
                (dated['異動別'] == '預計進貨')
            ]['異動數量'].sum()
            return max(0, last_bal - incoming)
        init_rows = w[w['日期'].isna()]
        if not init_rows.empty:
            qty = init_rows['異動數量'].dropna()
            if not qty.empty:
                return max(0, qty.iloc[0])
            qty = init_rows['預計結存'].dropna()
            if not qty.empty:
                return max(0, qty.iloc[0])
        return 0

    def source_wh(df_sd, pno, exclude_names, need_qty):
        excl = set(exclude_names)
        part_sd = df_sd[df_sd['品號']==pno]
        result = []
        remaining = need_qty
        e_avail = get_avail(df_sd, pno, '電子倉', excl)
        if e_avail > 0:
            use = min(e_avail, remaining)
            result.append(f"電子倉（{int(e_avail):,}）")
            remaining -= use
        if remaining <= 0:
            return '、'.join(result)
        for wh_code in part_sd['庫別'].dropna().unique():
            if wh_code in excl or wh_code == '電子倉': continue
            if len(str(wh_code)) > 12: continue
            wh_name = part_sd[part_sd['庫別']==wh_code]['庫別名稱'].dropna()
            if not wh_name.empty and wh_name.iloc[0] in excl: continue
            avail = get_avail(df_sd, pno, wh_code, excl)
            if avail > 0:
                result.append(f"{wh_code}（{int(avail):,}）")
                remaining -= avail
                if remaining <= 0: break
        return '、'.join(result) if result else ''

    parts = h2o['料號'].dropna().unique()

    rows = []
    for pno in parts:
        h_row    = h2o[h2o['料號']==pno].iloc[0]
        shortage = h_row.get('正的是缺料', 0) or 0
        spq      = spq_map.get(pno, 1)

        k_deficit = end_deficit(sd, pno, KUO)
        k_qty = apply_spq(k_deficit, spq)

        if k_qty <= 0:
            continue  # 只顯示國智有缺料的料號

        src = source_wh(sd, pno, set(), k_qty)

        cust_pn = ''
        for col in h_row.index:
            if 'Customer' in str(col) or 'P/N' in str(col):
                cust_pn = h_row[col]
                break

        rows.append({
            '料號':              pno,
            'SPQ':               int(spq) if spq else 1,
            '缺料量':            int(shortage) if shortage > 0 else None,
            '國智代工倉 缺料量':  k_qty,
            '可調撥來源倉（倉代碼/可用量）': src,
            'Customer P/N':     cust_pn,
        })

    df_out = pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=['料號','SPQ','缺料量','國智代工倉 缺料量','可調撥來源倉（倉代碼/可用量）','Customer P/N']
    )

# =========================
# 統計卡片
# =========================
col1, col2, col3 = st.columns(3)
col1.metric("H2O 料號總數",     f"{len(h2o['料號'].dropna().unique())} 個")
col2.metric("國智有缺料料號",   f"{len(df_out)} 個")
col3.metric("國智總缺料量",     f"{int(df_out['國智代工倉 缺料量'].sum()):,}" if len(df_out) else "0")

st.divider()

# =========================
# 資料表
# =========================
st.markdown(f"#### 🏭 國智配料表（區間末結存）　{date_start} ～ {date_end}")

if df_out.empty:
    st.success("✅ 區間內國智代工倉無缺料！")
else:
    df_display = df_out.copy()
    df_display['缺料量'] = df_display['缺料量'].fillna('-')

    st.dataframe(
        df_display,
        use_container_width=True,
        height=520,
        hide_index=True,
    )

    # =========================
    # 匯出 Excel
    # =========================
    def build_excel(df, start, end):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = '國智配料表'
        thin   = Side(style='thin', color='FFCCCCCC')
        border = Border(left=thin, right=thin, top=thin, bottom=thin)

        ws.merge_cells('A1:F1')
        c = ws['A1']
        c.value = f'國智配料表　{start.strftime("%Y/%m/%d")} ～ {end.strftime("%Y/%m/%d")}'
        c.font  = Font(name='Arial', bold=True, size=12, color='FFFFFFFF')
        c.fill  = PatternFill('solid', start_color='FF15803D')
        c.alignment = Alignment(horizontal='center', vertical='center')
        ws.row_dimensions[1].height = 24

        headers   = ['料號', 'SPQ', '缺料量', '國智代工倉\n缺料量', '可調撥來源倉\n（倉代碼/可用量）', 'Customer P/N']
        hdr_color = ['FFD9E8FF', 'FFF2F2F2', 'FFFCE4D6', 'FFE2EFDA', 'FFF5E6FF', 'FFF2F2F2']
        col_order = ['料號', 'SPQ', '缺料量', '國智代工倉 缺料量', '可調撥來源倉（倉代碼/可用量）', 'Customer P/N']
        for i, (h, hc) in enumerate(zip(headers, hdr_color), 1):
            cell = ws.cell(row=2, column=i, value=h)
            cell.font  = Font(name='Arial', bold=True, size=9)
            cell.fill  = PatternFill('solid', start_color=hc)
            cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
            cell.border = border
        ws.row_dimensions[2].height = 32

        for r_i, row_dict in enumerate(df.to_dict('records'), 3):
            vals = [row_dict.get(c) for c in col_order]
            for c_i, val in enumerate(vals, 1):
                cell = ws.cell(row=r_i, column=c_i, value=val)
                cell.font   = Font(name='Arial', size=9)
                cell.border = border
                cell.alignment = Alignment(
                    horizontal='left' if c_i in (1, 5, 6) else 'center',
                    vertical='center',
                )
                if c_i == 3 and val and isinstance(val, (int, float)) and val > 0:
                    cell.fill = PatternFill('solid', start_color='FFFCE4D6')
                elif c_i == 4 and val:
                    cell.fill = PatternFill('solid', start_color='FFE2EFDA')
                    cell.font = Font(name='Arial', size=9, bold=True, color='FF15803D')
                elif c_i == 5 and val:
                    cell.fill = PatternFill('solid', start_color='FFFFF0CC')

        col_widths = [28, 8, 12, 16, 36, 28]
        for i, w in enumerate(col_widths, 1):
            ws.column_dimensions[chr(64+i)].width = w
        ws.freeze_panes = 'A3'

        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        return buf

    buf = build_excel(df_out, start, end)
    st.download_button(
        label="⬇️ 匯出國智配料表（Excel）",
        data=buf,
        file_name=f"國智配料表_{date_start.strftime('%Y%m%d')}_{date_end.strftime('%Y%m%d')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
