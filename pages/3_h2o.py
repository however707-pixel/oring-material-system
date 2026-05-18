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

st.set_page_config(page_title="H2O缺料試算表", page_icon="💧", layout="wide")
inject_css()
render_header(
    title="H2O 缺料試算表",
    subtitle="H2O Shortage Outsource Analysis &nbsp;·&nbsp; ORing Industrial Networking",
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
        "從供需表中，找出 H2O 缺料料號\n"
        "在設定區間內，各委外廠預計領用量：\n\n"
        f"- 🔵 **唐佑** → `{TANG}`\n"
        f"- 🟢 **國智** → `{KUO}`"
    )

# =========================
# 主畫面
# =========================
if not h2o_file or not sd_file:
    st.markdown("""
    <div style="text-align:center; padding:80px 0; color:#94a3b8;">
        <div style="font-size:3.5rem; margin-bottom:16px;">💧</div>
        <div style="font-size:1.1rem; font-weight:700; color:#64748b; margin-bottom:8px;">H2O 缺料試算表</div>
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

    # SPQ map（從供需表 K 欄）
    spq_map = {}
    if 'SPQ' in sd.columns:
        spq_map = (sd[sd['SPQ'].notna()][['品號','SPQ']]
                   .drop_duplicates('品號')
                   .set_index('品號')['SPQ']
                   .to_dict())

    def apply_spq(qty, spq):
        s = int(spq) if spq and spq > 0 else 1
        if qty <= 0: return 0
        if qty >= s: return math.floor(qty / s) * s
        return int(qty)  # 不足一個 SPQ 給實際量

    parts    = h2o['料號'].dropna().unique()
    sd_range = sd[
        (sd['日期'] >= start) &
        (sd['日期'] <= end) &
        (sd['異動別'] == '預計領用')
    ]

    rows = []
    for pno in parts:
        h_row    = h2o[h2o['料號']==pno].iloc[0]
        shortage = h_row.get('正的是缺料', 0) or 0
        spq      = spq_map.get(pno, 1)

        t_raw = sd_range[(sd_range['品號']==pno) & (sd_range['庫別名稱']==TANG)]['異動數量'].sum()
        k_raw = sd_range[(sd_range['品號']==pno) & (sd_range['庫別名稱']==KUO )]['異動數量'].sum()

        t_qty = apply_spq(t_raw, spq)
        k_qty = apply_spq(k_raw, spq)

        cust_pn = ''
        for col in h_row.index:
            if 'Customer' in str(col) or 'P/N' in str(col):
                cust_pn = h_row[col]
                break

        rows.append({
            '料號':            pno,
            'SPQ':             int(spq) if spq else 1,
            '缺料量':          int(shortage) if shortage > 0 else None,
            '唐佑代工倉 領用量': t_qty if t_qty else None,
            '國智代工倉 領用量': k_qty if k_qty else None,
            '合計委外領用':    int(t_qty + k_qty) if (t_qty+k_qty) else None,
            'Customer P/N':   cust_pn,
        })

    df_out = pd.DataFrame(rows)
    has_any = df_out[df_out['合計委外領用'].notna()]

# =========================
# 統計卡片
# =========================
col1, col2, col3, col4 = st.columns(4)
col1.metric("H2O 料號總數",   f"{len(df_out)} 個")
col2.metric("有委外領用料號", f"{len(has_any)} 個")
col3.metric("唐佑總領用量",   f"{int(df_out['唐佑代工倉 領用量'].fillna(0).sum()):,}")
col4.metric("國智總領用量",   f"{int(df_out['國智代工倉 領用量'].fillna(0).sum()):,}")

st.divider()

# =========================
# 資料表
# =========================
st.markdown(f"#### 💧 H2O 委外領用試算　{date_start} ～ {date_end}")

# 顯示用：空值換成 "-"
df_display = df_out.copy()
for col in ['缺料量','唐佑代工倉 領用量','國智代工倉 領用量','合計委外領用']:
    df_display[col] = df_display[col].fillna('-')

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
    ws.title = 'H2O委外領用試算'
    thin   = Side(style='thin', color='FFCCCCCC')
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    ws.merge_cells('A1:G1')
    c = ws['A1']
    c.value = f'H2O 缺料委外領用試算　{start.strftime("%Y/%m/%d")} ～ {end.strftime("%Y/%m/%d")}'
    c.font  = Font(name='Arial', bold=True, size=12, color='FFFFFFFF')
    c.fill  = PatternFill('solid', start_color='FF0F2460')
    c.alignment = Alignment(horizontal='center', vertical='center')
    ws.row_dimensions[1].height = 24

    # 欄順序：料號, SPQ, 缺料量, 唐佑, 國智, 合計, Customer P/N
    headers   = ['料號', 'SPQ', '缺料量', '唐佑代工倉\n領用量', '國智代工倉\n領用量', '合計委外領用', 'Customer P/N']
    hdr_color = ['FFD9E8FF','FFF2F2F2','FFD9E8FF','FFDCE6F1','FFE2EFDA','FFFFF2CC','FFF2F2F2']
    col_order = ['料號','SPQ','缺料量','唐佑代工倉 領用量','國智代工倉 領用量','合計委外領用','Customer P/N']
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
            cell.alignment = Alignment(horizontal='left' if c_i in (1,7) else 'center', vertical='center')
            if c_i == 3 and val and isinstance(val,(int,float)) and val > 0:
                cell.fill = PatternFill('solid', start_color='FFFCE4D6')
            elif c_i == 4 and val:
                cell.fill = PatternFill('solid', start_color='FFDCE6F1')
                cell.font = Font(name='Arial', size=9, bold=True, color='FF1E3A8A')
            elif c_i == 5 and val:
                cell.fill = PatternFill('solid', start_color='FFE2EFDA')
                cell.font = Font(name='Arial', size=9, bold=True, color='FF15803D')
            elif c_i == 6 and val:
                cell.fill = PatternFill('solid', start_color='FFFFFF99')

    ws.column_dimensions['A'].width = 28
    ws.column_dimensions['B'].width = 8
    ws.column_dimensions['C'].width = 12
    ws.column_dimensions['D'].width = 14
    ws.column_dimensions['E'].width = 14
    ws.column_dimensions['F'].width = 14
    ws.column_dimensions['G'].width = 28
    ws.freeze_panes = 'A3'

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf

buf = build_excel(df_out, start, end)
st.download_button(
    label="⬇️ 匯出試算結果（Excel）",
    data=buf,
    file_name=f"H2O委外領用試算_{date_start.strftime('%Y%m%d')}_{date_end.strftime('%Y%m%d')}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)
