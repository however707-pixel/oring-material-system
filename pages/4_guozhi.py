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

    h2o_file = st.file_uploader("📂 上傳國智缺料表（W11）", type=["xlsx", "xls", "csv"])
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
        <div style="font-size:0.85rem;">請從左側上傳 <b>國智缺料表</b> 及 <b>供需表</b> 開始分析</div>
    </div>""", unsafe_allow_html=True)
    st.stop()

with st.spinner("分析中，請稍候..."):
    # 讀國智缺料表（第3行為欄位標題，前2行為說明列）
    try:
        if h2o_file.name.endswith('.csv'):
            gz = None
            for enc in ['utf-8-sig', 'cp950', 'big5']:
                try:
                    gz = pd.read_csv(h2o_file, header=0, encoding=enc)
                    break
                except Exception:
                    h2o_file.seek(0)
            if gz is None:
                st.error("國智缺料表 CSV 無法讀取，請確認編碼。")
                st.stop()
        else:
            # W11 缺料表：第2張工作表，第3列為標題（header=2），A欄='品號'
            try:
                gz = pd.read_excel(h2o_file, sheet_name=1, header=2, engine='calamine')
            except Exception:
                h2o_file.seek(0)
                gz = pd.read_excel(h2o_file, sheet_name=1, header=2, engine='openpyxl')
    except Exception as e:
        st.error(f"國智缺料表讀取失敗：{e}")
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
    if '品號' not in gz.columns:
        st.error(f"國智缺料表找不到「品號」欄位，偵測到的欄位：{gz.columns.tolist()}")
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
            # 扣除所有預計進貨（不限起始日，未實際入庫不算可用）
            incoming = dated[
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

        # 有日期資料的列：建立 代碼→名稱 對照
        dated_part = part_sd[part_sd['日期'].notna() & part_sd['庫別名稱'].notna()]
        code_name = (dated_part[['庫別','庫別名稱']]
                     .drop_duplicates('庫別')
                     .set_index('庫別')['庫別名稱']
                     .to_dict())
        code_name = {c: n for c, n in code_name.items() if len(str(c)) <= 12}
        names_with_dated = set(code_name.values())
        dated_codes      = set(code_name.keys())

        # 只有初始列的倉（無日期、無倉名、不在有交易的倉之中）
        init_rows = part_sd[part_sd['日期'].isna() & part_sd['庫別名稱'].isna()]
        init_only = {}
        for wh_k in init_rows['庫別'].dropna().unique():
            ws = str(wh_k)
            if ws in dated_codes or ws in names_with_dated: continue
            if len(ws) > 12: continue
            qty = init_rows[init_rows['庫別']==wh_k]['異動數量'].dropna()
            if not qty.empty and qty.iloc[0] > 0:
                init_only[ws] = qty.iloc[0]

        # Step 1: 電子倉優先（有交易→代碼查；無交易→初始列直讀）
        e_code = next((c for c, n in code_name.items() if n == '電子倉'), None)
        e_avail = get_avail(df_sd, pno, e_code, excl) if e_code else init_only.get('電子倉', 0)
        if e_avail > 0:
            result.append(f"電子倉（{int(e_avail):,}）")
            remaining -= min(e_avail, remaining)

        if remaining <= 0:
            return '、'.join(result)

        # Step 2: 有交易的其他倉
        for wh_code, wh_name in code_name.items():
            if e_code and wh_code == e_code: continue
            if wh_name in excl: continue
            avail = get_avail(df_sd, pno, wh_code, excl)
            if avail > 0:
                result.append(f"{wh_name}（{int(avail):,}）")
                remaining -= avail
                if remaining <= 0: break

        # Step 3: 只有初始列的其他倉
        for wh_name, avail in init_only.items():
            if wh_name == '電子倉': continue
            if wh_name in excl: continue
            if avail > 0:
                result.append(f"{wh_name}（{int(avail):,}）")
                remaining -= avail
                if remaining <= 0: break

        return '、'.join(result) if result else ''

    def src_avail_excl(pno, excl_names):
        """排除指定倉名後，所有可用來源倉的可用量加總（與 source_wh 相同識別邏輯）"""
        excl = set(excl_names)
        part_sd = sd[sd['品號']==pno]
        total = 0

        dated_part = part_sd[part_sd['日期'].notna() & part_sd['庫別名稱'].notna()]
        code_name = (dated_part[['庫別','庫別名稱']]
                     .drop_duplicates('庫別')
                     .set_index('庫別')['庫別名稱']
                     .to_dict())
        code_name = {c: n for c, n in code_name.items() if len(str(c)) <= 12}
        names_with_dated = set(code_name.values())
        dated_codes      = set(code_name.keys())

        for wh_code, wh_name in code_name.items():
            if wh_name in excl: continue
            total += get_avail(sd, pno, wh_code, excl)

        init_rows = part_sd[part_sd['日期'].isna() & part_sd['庫別名稱'].isna()]
        for wh_k in init_rows['庫別'].dropna().unique():
            ws = str(wh_k)
            if ws in dated_codes or ws in names_with_dated: continue
            if ws in excl: continue
            if len(ws) > 12: continue
            qty = init_rows[init_rows['庫別']==wh_k]['異動數量'].dropna()
            if not qty.empty and float(qty.iloc[0]) > 0:
                total += float(qty.iloc[0])

        return int(total)

    def first_deficit_date(pno, wh_name):
        sub = sd[(sd['品號']==pno) & (sd['庫別名稱']==wh_name) &
                 (sd['日期'] >= start) & (sd['日期'] <= end) &
                 sd['預計結存'].notna() & (sd['預計結存'] < 0)]
        if sub.empty: return None
        return sub.sort_values('日期').iloc[0]['日期']

    parts = gz['品號'].dropna().unique()

    rows = []
    for pno in parts:
        gz_row  = gz[gz['品號']==pno].iloc[0]
        spq     = spq_map.get(pno, 1)
        spq_int = int(spq) if spq and spq > 0 else 1

        k_deficit = end_deficit(sd, pno, KUO)
        k_qty     = apply_spq(k_deficit, spq)

        if k_qty <= 0:
            continue  # 只顯示國智有缺料的料號

        # ── 來源可用量 ──
        _src_total = src_avail_excl(pno, {KUO})

        # 來源充足：不需強制SPQ進位，給實際可用量（上限為SPQ進位值）
        if _src_total >= k_deficit:
            k_qty = min(_src_total, k_qty)

        src = source_wh(sd, pno, set(), k_qty)

        # ── 庫存不足判斷 ──
        shortage = _src_total < k_deficit
        k_alloc  = min(_src_total, k_qty) if shortage else k_qty

        if shortage:
            k_qty_str = f"⚠️ {int(k_alloc):,}  （需 {int(k_deficit):,}）"
            short_note = (
                f"⚠️ 庫存不足（需 {int(k_deficit):,}，可用 {int(_src_total):,}）\n"
                f"► 國智代工倉 → 僅可配 {int(k_alloc):,}，尚缺 {int(k_deficit - k_alloc):,}"
            )
        else:
            d = int(k_deficit)
            k_qty_str  = f"{k_qty:,}  (原缺 {d:,})" if k_qty != d else k_qty
            short_note = ''

        # B欄 = 客戶料號
        cust_pn = str(gz_row.get('客戶料號', '') or '') if pd.notna(gz_row.get('客戶料號', '')) else ''

        rows.append({
            '品號':               pno,
            'SPQ':                spq_int,
            '國智代工倉 缺料量':   k_qty_str,
            '_國智qty':           k_qty,
            '_shortage':          shortage,
            '可調撥來源倉（倉代碼/可用量）': src,
            '⚠️ 配料說明':        short_note,
            '客戶料號':            cust_pn,
        })

    df_out = pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=['品號','SPQ','國智代工倉 缺料量','_國智qty','_shortage',
                 '可調撥來源倉（倉代碼/可用量）','⚠️ 配料說明','客戶料號']
    )

# =========================
# 統計卡片
# =========================
short_warn = df_out[df_out['_shortage'] == True] if len(df_out) else pd.DataFrame()
col1, col2, col3, col4 = st.columns(4)
col1.metric("缺料表料號總數",    f"{len(gz['品號'].dropna().unique())} 個")
col2.metric("國智有缺料料號",   f"{len(df_out)} 個")
col3.metric("國智總缺料量",     f"{int(df_out['_國智qty'].sum()):,}" if len(df_out) else "0")
col4.metric("⚠️ 庫存不足料號",  f"{len(short_warn)} 個",
            delta=None if len(short_warn)==0 else "需確認配料",
            delta_color="inverse")

st.divider()

# =========================
# 資料表
# =========================
st.markdown(f"#### 🏭 國智配料表（區間末結存）　{date_start} ～ {date_end}")

if df_out.empty:
    st.success("✅ 區間內國智代工倉無缺料！")
else:
    # 庫存不足警告橫幅
    if len(short_warn) > 0:
        pno_list = '、'.join(short_warn['品號'].tolist())
        st.warning(
            f"**⚠️ 以下 {len(short_warn)} 個料號庫存不足，請確認配料：**\n\n{pno_list}",
            icon="⚠️",
        )

    display_cols = ['品號','SPQ','國智代工倉 缺料量','可調撥來源倉（倉代碼/可用量）','⚠️ 配料說明','客戶料號']
    df_display = df_out[display_cols].copy()

    _shortage_pnos = set(short_warn['品號'].tolist()) if len(short_warn) else set()

    def _row_style(row):
        pno = row.get('品號', '')
        if pno in _shortage_pnos:
            return ['background-color: #fef2f2; color: #991b1b; font-weight:600;'] * len(row)
        src_val = str(row.get('可調撥來源倉（倉代碼/可用量）', ''))
        if '、' in src_val:
            return ['background-color: #fff7ed; color: #9a3412; font-weight:600;'] * len(row)
        return [''] * len(row)

    st.dataframe(
        df_display.style.apply(_row_style, axis=1),
        use_container_width=True,
        height=520,
        hide_index=True,
        column_config={
            '⚠️ 配料說明': st.column_config.TextColumn(width='large'),
        }
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

        headers   = ['品號', 'SPQ', '國智代工倉\n缺料量', '可調撥來源倉\n（倉代碼/可用量）', '配料說明\n（庫存不足時）', '客戶料號']
        hdr_color = ['FFD9E8FF', 'FFF2F2F2', 'FFE2EFDA', 'FFF5E6FF', 'FFFCE4D6', 'FFF2F2F2']
        col_order = ['品號', 'SPQ', '國智代工倉 缺料量', '可調撥來源倉（倉代碼/可用量）', '⚠️ 配料說明', '客戶料號']
        for i, (h, hc) in enumerate(zip(headers, hdr_color), 1):
            cell = ws.cell(row=2, column=i, value=h)
            cell.font  = Font(name='Arial', bold=True, size=9)
            cell.fill  = PatternFill('solid', start_color=hc)
            cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
            cell.border = border
        ws.row_dimensions[2].height = 32

        for r_i, row_dict in enumerate(df.to_dict('records'), 3):
            is_short = bool(row_dict.get('_shortage', False))
            vals = [row_dict.get(c) for c in col_order]
            for c_i, val in enumerate(vals, 1):
                cell = ws.cell(row=r_i, column=c_i, value=val)
                cell.font   = Font(name='Arial', size=9,
                                   bold=is_short,
                                   color='FF991B1B' if is_short else 'FF000000')
                cell.border = border
                cell.alignment = Alignment(
                    horizontal='left' if c_i in (1, 4, 5, 6) else 'center',
                    vertical='center',
                    wrap_text=(c_i == 5),
                )
                if is_short:
                    cell.fill = PatternFill('solid', start_color='FFFCE4EC')
                elif c_i == 3 and val:
                    cell.fill = PatternFill('solid', start_color='FFE2EFDA')
                    cell.font = Font(name='Arial', size=9, bold=True, color='FF15803D')
                elif c_i == 4 and val:
                    cell.fill = PatternFill('solid', start_color='FFFFF0CC')

        col_widths = [28, 8, 16, 36, 40, 28]
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
