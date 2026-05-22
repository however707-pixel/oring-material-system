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

# =========================
# 廠內排程.xlsx 欄位位置（0-indexed）
#   A(0)=料號  B(1)=品名  C(2)=規格  D(3)=單位
#   E(4)=組裝數量  F(5)=工單單號  G(6)=flag
#   H(7)=需求數量  I(8)=現有庫存  J(9)=預計入庫
#   K(10)~M(12)=組裝相關  N(13)=工單開工日
# =========================
COL_PNO    = 0   # A: 料號
COL_NAME   = 1   # B: 品名
COL_WO     = 5   # F: 工單單號
COL_DEMAND = 7   # H: 需求數量
COL_STOCK  = 8   # I: 現有庫存
COL_WODATE = 13  # N: 工單開工日

# =========================
# Sidebar 設定
# =========================
with st.sidebar:
    st.divider()
    st.markdown("### ⚙️ 設定")

    shortage_file = st.file_uploader("📂 上傳廠內排程表（工單缺料）", type=["xlsx", "xls", "csv"])
    sd_file       = st.file_uploader("📂 上傳供需表",                  type=["xlsx", "xls", "csv"])
    transfer_file = st.file_uploader("📂 上傳互調料滙整表（選填）",    type=["xlsx", "xls", "xlsm"])

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
        "從廠內排程表（工單缺料）取得：\n"
        "- **H欄**：工單需求數量\n"
        "- **I欄**：現有庫存\n"
        "- **缺料量** = H - I（當 H > I）\n\n"
        "從供需表查預計進貨：\n"
        "- **G欄**：預計進貨日期\n"
        "- **H欄**：異動別＝'預計進貨'\n"
        "- **I欄**：進貨數量"
    )

# =========================
# 主畫面
# =========================
if not shortage_file or not sd_file:
    st.info("👈 請在左側上傳「廠內排程表」及「供需表」開始分析")
    st.markdown("""
    <div style="background:#f0fdf4;border:1.5px dashed #86efac;border-radius:12px;padding:20px 24px;margin-top:16px;">
    <b style="color:#15803d;font-size:1rem;">📋 操作步驟</b>
    <ol style="color:#374151;margin-top:10px;line-height:2.2;">
      <li>ERP → 製令/生管系統 → 匯出 <b>廠內排程表（工單缺料明細）</b>，上傳至左側</li>
      <li>ERP → 供需管理 → 匯出 <b>供需表（分倉）</b>，上傳至左側</li>
      <li>（選填）上傳<b>互調料彙整表</b>，追蹤已調撥進度</li>
      <li>設定<b>分析區間</b>（起始日 ～ 結束日）</li>
      <li>系統自動計算缺料量並對應供需表中的預計進貨日</li>
    </ol>
    <br>
    <b style="color:#15803d;">🎯 缺料量計算邏輯</b>
    <table style="margin-top:8px;width:100%;border-collapse:collapse;font-size:0.88rem;">
      <tr style="background:#dcfce7;"><td style="padding:5px 10px;"><b>缺料量</b></td>
          <td style="padding:5px 10px;">= 工單需求合計（H欄）- 現有庫存（I欄），最低為 0</td></tr>
      <tr><td style="padding:5px 10px;"><b>預計進貨日</b></td>
          <td style="padding:5px 10px;">從供需表查「異動別＝預計進貨」的日期與數量</td></tr>
      <tr style="background:#dcfce7;"><td style="padding:5px 10px;"><b>可調撥倉</b></td>
          <td style="padding:5px 10px;">電子倉／機構倉／半成品倉／成品倉現有可用量</td></tr>
    </table>
    </div>
    """, unsafe_allow_html=True)
    st.stop()

with st.spinner("分析中，請稍候..."):

    # ── 讀廠內排程表（用位置讀欄，避免中文亂碼）──────────────────────────────
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
                st.error("廠內排程表 CSV 無法讀取，請確認編碼。")
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

    # 跳過第 1 列（欄位名稱列），取資料列
    sf = sf_raw.iloc[1:].reset_index(drop=True).copy()

    # 最少需要 H、I 兩欄（第 8、9 欄，索引 7、8）
    if sf.shape[1] <= COL_STOCK:
        st.error(
            f"廠內排程表欄位數不足（需至少 {COL_STOCK+1} 欄，偵測到 {sf.shape[1]} 欄）\n"
            f"請確認上傳的是「廠內排程表（工單缺料）」。"
        )
        st.stop()

    # 統一欄位名稱
    sf['_pno']    = sf.iloc[:, COL_PNO].astype(str).str.strip()
    sf['_name']   = sf.iloc[:, COL_NAME].astype(str).str.strip() if sf.shape[1] > COL_NAME else ''
    sf['_wo']     = sf.iloc[:, COL_WO].astype(str).str.strip()   if sf.shape[1] > COL_WO   else ''
    sf['_demand'] = pd.to_numeric(sf.iloc[:, COL_DEMAND], errors='coerce').fillna(0)
    sf['_stock']  = pd.to_numeric(sf.iloc[:, COL_STOCK],  errors='coerce').fillna(0)
    sf['_wodate'] = sf.iloc[:, COL_WODATE].astype(str).str.strip() if sf.shape[1] > COL_WODATE else ''

    # 過濾空白、無效料號
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

    # 供需表欄位檢查
    for col in ['品號', '庫別名稱', '日期', '異動別', '異動數量']:
        if col not in sd.columns:
            st.error(f"供需表找不到「{col}」欄位，請確認檔案格式。")
            st.stop()

    end = pd.Timestamp(date_end)

    # ── 讀互調料滙整表（選填）────────────────────────────────────────────────
    pending_map = {}
    if transfer_file is not None:
        try:
            tf_raw = pd.read_excel(transfer_file, sheet_name=0, header=None, engine='openpyxl')
            tf = tf_raw.iloc[1:].copy()
            tf_h = tf[7].astype(str).str.strip()
            tf_j = pd.to_numeric(tf[9], errors='coerce').fillna(0)
            tf_df = pd.DataFrame({'料號': tf_h, 'J': tf_j})
            tf_df = tf_df[tf_df['料號'].notna() & (tf_df['料號'] != '') & (tf_df['料號'] != 'nan')]
            pending_map = tf_df.groupby('料號')['J'].sum().to_dict()
        except Exception as e:
            st.warning(f"互調料滙整表讀取失敗（略過）：{e}")

    has_transfer = bool(pending_map)

    # SPQ
    spq_map = {}
    if 'SPQ' in sd.columns:
        spq_map = (sd[sd['SPQ'].notna()][['品號', 'SPQ']]
                   .drop_duplicates('品號')
                   .set_index('品號')['SPQ']
                   .to_dict())

    # ── Helper 函數 ──────────────────────────────────────────────────────────

    def apply_spq(qty, spq):
        s = int(spq) if spq and spq > 0 else 1
        if qty <= 0: return 0
        return math.ceil(qty / s) * s

    def get_avail(pno, wh_code, excl):
        """計算指定倉可用量（扣除預計進貨及預計生產）"""
        w = sd[(sd['品號'] == pno) & (sd['庫別'] == wh_code)]
        if w.empty: return 0
        wh_name = w['庫別名稱'].dropna().iloc[0] if w['庫別名稱'].dropna().shape[0] > 0 else ''
        if wh_name in excl: return 0
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
            if not qty.empty: return max(0, qty.iloc[0])
            qty = init_rows['預計結存'].dropna()
            if not qty.empty: return max(0, qty.iloc[0])
        return 0

    def avail_4wh(pno):
        """只計算 VALID_SRC（電子倉/機構倉/半成品倉/成品倉）的可用量"""
        part_sd = sd[sd['品號'] == pno]
        total = 0.0
        dated_part = part_sd[part_sd['日期'].notna() & part_sd['庫別名稱'].notna()]
        code_name = (dated_part[['庫別', '庫別名稱']]
                     .drop_duplicates('庫別')
                     .set_index('庫別')['庫別名稱']
                     .to_dict())
        code_name = {c: n for c, n in code_name.items() if len(str(c)) <= 12}
        names_with_dated = set(code_name.values())
        dated_codes      = set(code_name.keys())
        for wh_code, wh_name in code_name.items():
            if wh_name not in VALID_SRC: continue
            total += get_avail(pno, wh_code, set())
        init_rows = part_sd[part_sd['日期'].isna() & part_sd['庫別名稱'].isna()]
        for wh_k in init_rows['庫別'].dropna().unique():
            ws = str(wh_k)
            if ws in dated_codes or ws in names_with_dated: continue
            if ws not in VALID_SRC: continue
            if len(ws) > 12: continue
            qty = init_rows[init_rows['庫別'] == wh_k]['異動數量'].dropna()
            if not qty.empty and float(qty.iloc[0]) > 0:
                total += float(qty.iloc[0])
        return int(total)

    def source_wh(pno, need_qty):
        """顯示用：列出各倉現有庫存（電子倉優先）"""
        part_sd = sd[sd['品號'] == pno]
        result  = []
        remaining = need_qty
        dated_part = part_sd[part_sd['日期'].notna() & part_sd['庫別名稱'].notna()]
        code_name  = (dated_part[['庫別', '庫別名稱']]
                      .drop_duplicates('庫別')
                      .set_index('庫別')['庫別名稱']
                      .to_dict())
        code_name  = {c: n for c, n in code_name.items() if len(str(c)) <= 12}
        dated_codes      = set(code_name.keys())
        names_with_dated = set(code_name.values())
        init_rows = part_sd[part_sd['日期'].isna() & part_sd['庫別名稱'].isna()]
        init_only = {}
        for wh_k in init_rows['庫別'].dropna().unique():
            ws = str(wh_k)
            if ws in dated_codes or ws in names_with_dated: continue
            if len(ws) > 12: continue
            qty = init_rows[init_rows['庫別'] == wh_k]['異動數量'].dropna()
            if not qty.empty and qty.iloc[0] > 0:
                init_only[ws] = qty.iloc[0]
        e_code  = next((c for c, n in code_name.items() if n == '電子倉'), None)
        e_avail = get_avail(pno, e_code, set()) if e_code else init_only.get('電子倉', 0)
        if e_avail > 0:
            result.append(f"電子倉（{int(e_avail):,}）")
            remaining -= min(e_avail, remaining)
        if remaining <= 0: return '、'.join(result)
        for wh_code, wh_name in code_name.items():
            if e_code and wh_code == e_code: continue
            avail = get_avail(pno, wh_code, set())
            if avail > 0:
                result.append(f"{wh_name}（{int(avail):,}）")
                remaining -= avail
                if remaining <= 0: break
        for wh_name, avail in init_only.items():
            if wh_name == '電子倉': continue
            if avail > 0:
                result.append(f"{wh_name}（{int(avail):,}）")
                remaining -= avail
                if remaining <= 0: break
        return '、'.join(result) if result else ''

    def get_incoming(pno):
        """取得所有預計進貨（不限分析區間），每筆格式：MM/DD(數量)"""
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

    # ── 主分析：以料號匯總，計算缺料量 ─────────────────────────────────────
    #  缺料量 = max(0, 各工單需求合計 - 現有庫存)
    #  （庫存對同一料號的所有工單是共用的，只扣一次）
    rows = []

    for pno, grp in sf.groupby('_pno'):
        pno_str      = str(pno).strip()
        total_demand = int(grp['_demand'].sum())
        stock        = int(grp['_stock'].iloc[0])      # 同一料號庫存相同，取第一筆
        f_deficit    = max(0, total_demand - stock)

        if f_deficit <= 0:
            continue

        # 品名（取第一筆）
        part_name = str(grp['_name'].iloc[0]) if '_name' in grp.columns else ''
        if part_name in ('', 'nan', 'None'): part_name = ''

        # 最早工單開工日
        earliest_wo_date = ''
        if '_wodate' in grp.columns:
            dates = grp['_wodate'].dropna().tolist()
            valid_dates = [d for d in dates if d not in ('', 'nan', 'None', 'NaT')]
            if valid_dates:
                try:
                    parsed = pd.to_datetime(valid_dates, errors='coerce').dropna()
                    if len(parsed):
                        earliest_wo_date = parsed.min().strftime('%Y/%m/%d')
                except Exception:
                    earliest_wo_date = valid_dates[0]

        # 涉及工單（去重，取前 5 個）
        wos = grp['_wo'].dropna().unique().tolist()
        wos = [w for w in wos if w not in ('', 'nan', 'None')]
        wo_str = '、'.join(wos[:5]) + ('…' if len(wos) > 5 else '')

        # 待調撥量
        f_pending = int(pending_map.get(pno_str, 0) or 0)

        # 淨需求 & 四倉可用
        f_net       = max(0, f_deficit - f_pending)
        avail_4w    = avail_4wh(pno) if f_net > 0 else 0
        net_avail_4w = max(0, avail_4w - f_pending)

        # 三段 SPQ 配料邏輯
        spq       = spq_map.get(pno, 1)
        spq_int   = int(spq) if spq and spq > 0 else 1
        f_spq_net = apply_spq(f_net, spq)
        f_alloc   = f_net
        short_note = ''
        shortage   = (f_net > 0 and net_avail_4w < f_net)

        if shortage:
            f_alloc    = min(f_net, net_avail_4w)
            short_note = (
                f"⚠️ 庫存不足（需 {int(f_net):,}，四倉可用 {int(net_avail_4w):,}，尚缺 {int(f_net - f_alloc):,}）"
            )
        elif net_avail_4w >= f_spq_net:
            f_alloc = f_spq_net

        # 缺料量顯示字串
        f_qty = apply_spq(f_deficit, spq)
        if shortage:
            f_qty_str = f"⚠️ {int(f_alloc):,}  （需 {int(f_net):,}）"
        else:
            d = int(f_deficit)
            f_qty_str = f"{f_qty:,}  (原缺 {d:,})" if f_qty != d else f_qty

        # 實際應調撥量
        f_actual = (0 if f_pending >= f_deficit else f_alloc) if f_deficit > 0 else None

        # 可調撥來源倉（顯示用，所有倉）
        src = source_wh(pno, f_qty) if f_qty > 0 else ''

        # 預計進貨（從供需表查）
        incoming = get_incoming(pno)

        rows.append({
            '料號':                            pno,
            '品名':                            part_name,
            'SPQ':                             spq_int,
            '需求數量':                        total_demand,
            '現有庫存':                        stock,
            '缺料量':                          f_qty_str,
            '待調撥量':                        f_pending if (has_transfer and f_deficit > 0) else None,
            '實際應調撥量':                    f_actual  if has_transfer else None,
            '預計進貨日（含數量）':             incoming,
            '最早工單開工日':                  earliest_wo_date,
            '工單單號':                        wo_str,
            '_qty':                            f_qty,
            '_shortage':                       shortage,
            '可調撥來源倉（倉代碼/可用量）':   src,
            '⚠️ 配料說明':                     short_note,
        })

    df_out = pd.DataFrame(rows) if rows else pd.DataFrame()

# ── 統計卡片 ──────────────────────────────────────────────────────────────────
total_parts   = sf['_pno'].nunique()
short_warn    = df_out[df_out['_shortage'] == True] if len(df_out) else pd.DataFrame()

col1, col2, col3, col4 = st.columns(4)
col1.metric("工單料號總數",    f"{total_parts} 個")
col2.metric("缺料料號",        f"{len(df_out)} 個")
col3.metric("缺料量合計",      f"{int(df_out['_qty'].sum()):,}" if len(df_out) else "0")
col4.metric("⚠️ 庫存不足料號", f"{len(short_warn)} 個",
            delta=None if len(short_warn) == 0 else "需確認配料",
            delta_color="inverse")

st.divider()

# ── 資料表 ────────────────────────────────────────────────────────────────────
st.markdown(f"#### 🏭 廠內配料表　{date_start} ～ {date_end}")

if df_out.empty:
    st.success("✅ 所有工單料件均無缺料！")
else:
    if len(short_warn) > 0:
        pno_list = '、'.join(short_warn['料號'].tolist())
        st.warning(
            f"**⚠️ 以下 {len(short_warn)} 個料號四倉庫存不足，請確認配料：**\n\n{pno_list}",
            icon="⚠️",
        )

    # 顯示欄位
    if has_transfer:
        display_cols = ['料號', '品名', 'SPQ', '需求數量', '現有庫存', '缺料量',
                        '待調撥量', '實際應調撥量',
                        '預計進貨日（含數量）', '最早工單開工日', '工單單號',
                        '可調撥來源倉（倉代碼/可用量）', '⚠️ 配料說明']
    else:
        display_cols = ['料號', '品名', 'SPQ', '需求數量', '現有庫存', '缺料量',
                        '預計進貨日（含數量）', '最早工單開工日', '工單單號',
                        '可調撥來源倉（倉代碼/可用量）', '⚠️ 配料說明']

    df_display = df_out[[c for c in display_cols if c in df_out.columns]].copy()
    _shortage_pnos = set(short_warn['料號'].tolist()) if len(short_warn) else set()

    def _row_style(row):
        pno = row.get('料號', '')
        if pno in _shortage_pnos:
            return ['background-color: #fef2f2; color: #991b1b; font-weight:600;'] * len(row)
        return [''] * len(row)

    st.dataframe(
        df_display.style.apply(_row_style, axis=1),
        use_container_width=True,
        height=540,
        hide_index=True,
        column_config={
            '⚠️ 配料說明':          st.column_config.TextColumn(width='large'),
            '預計進貨日（含數量）':  st.column_config.TextColumn(width='medium'),
            '可調撥來源倉（倉代碼/可用量）': st.column_config.TextColumn(width='large'),
            '品名':                  st.column_config.TextColumn(width='medium'),
        }
    )

    # ── 匯出 Excel ────────────────────────────────────────────────────────────
    def build_excel(df, start_dt, end_dt, with_transfer=False):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = '廠內配料表'
        thin   = Side(style='thin', color='FFCCCCCC')
        border = Border(left=thin, right=thin, top=thin, bottom=thin)

        if with_transfer:
            headers = ['料號', '品名', 'SPQ', '需求數量', '現有庫存', '缺料量',
                       '待調撥量', '實際應調撥量',
                       '預計進貨日\n（含數量）', '最早工單\n開工日', '工單單號',
                       '可調撥來源倉\n（倉代碼/可用量）', '配料說明']
            col_keys = ['料號', '品名', 'SPQ', '需求數量', '現有庫存', '缺料量',
                        '待調撥量', '實際應調撥量',
                        '預計進貨日（含數量）', '最早工單開工日', '工單單號',
                        '可調撥來源倉（倉代碼/可用量）', '⚠️ 配料說明']
            hdr_color  = ['FFD9E8FF', 'FFF5F5F5', 'FFF2F2F2', 'FFE8F4FD', 'FFE8F4FD',
                          'FFD9E8FF', 'FFB8D4EE', 'FFA0C4E8',
                          'FFE8F4FD', 'FFFFF0CC', 'FFF5E6FF',
                          'FFF5E6FF', 'FFFCE4D6']
            col_widths = [30, 26, 7, 10, 10, 14, 12, 14, 22, 14, 28, 36, 40]
            left_cols  = {1, 2, 9, 10, 11, 12, 13}
            note_col, src_col = 13, 12
        else:
            headers = ['料號', '品名', 'SPQ', '需求數量', '現有庫存', '缺料量',
                       '預計進貨日\n（含數量）', '最早工單\n開工日', '工單單號',
                       '可調撥來源倉\n（倉代碼/可用量）', '配料說明']
            col_keys = ['料號', '品名', 'SPQ', '需求數量', '現有庫存', '缺料量',
                        '預計進貨日（含數量）', '最早工單開工日', '工單單號',
                        '可調撥來源倉（倉代碼/可用量）', '⚠️ 配料說明']
            hdr_color  = ['FFD9E8FF', 'FFF5F5F5', 'FFF2F2F2', 'FFE8F4FD', 'FFE8F4FD',
                          'FFD9E8FF', 'FFE8F4FD', 'FFFFF0CC', 'FFF5E6FF',
                          'FFF5E6FF', 'FFFCE4D6']
            col_widths = [30, 26, 7, 10, 10, 14, 22, 14, 28, 36, 40]
            left_cols  = {1, 2, 7, 8, 9, 10, 11}
            note_col, src_col = 11, 10

        total_cols = len(headers)
        merge_end = chr(64 + total_cols)
        ws.merge_cells(f'A1:{merge_end}1')
        c = ws['A1']
        c.value = f'廠內配料表　{start_dt.strftime("%Y/%m/%d")} ～ {end_dt.strftime("%Y/%m/%d")}'
        c.font      = Font(name='Arial', bold=True, size=12, color='FFFFFFFF')
        c.fill      = PatternFill('solid', start_color='FF374151')
        c.alignment = Alignment(horizontal='center', vertical='center')
        ws.row_dimensions[1].height = 24

        for i, (h, hc) in enumerate(zip(headers, hdr_color), 1):
            cell = ws.cell(row=2, column=i, value=h)
            cell.font      = Font(name='Arial', bold=True, size=9)
            cell.fill      = PatternFill('solid', start_color=hc)
            cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
            cell.border    = border
        ws.row_dimensions[2].height = 32

        for r_i, row_dict in enumerate(df.to_dict('records'), 3):
            is_short = bool(row_dict.get('_shortage', False))
            for c_i, key in enumerate(col_keys, 1):
                val  = row_dict.get(key)
                cell = ws.cell(row=r_i, column=c_i, value=val)
                cell.font   = Font(name='Arial', size=9,
                                   bold=is_short,
                                   color='FF991B1B' if is_short else 'FF000000')
                cell.border = border
                cell.alignment = Alignment(
                    horizontal='left' if c_i in left_cols else 'center',
                    vertical='center',
                    wrap_text=(c_i in {note_col, src_col}),
                )
                if is_short:
                    cell.fill = PatternFill('solid', start_color='FFFCE4EC')
                elif c_i == 6 and val:          # 缺料量
                    cell.fill = PatternFill('solid', start_color='FFD9E8FF')
                    cell.font = Font(name='Arial', size=9, bold=True, color='FF1E3A8A')
                elif c_i == src_col and val:
                    cell.fill = PatternFill('solid', start_color='FFFFF0CC')
                elif c_i == note_col and val:
                    cell.fill = PatternFill('solid', start_color='FFFDE8D0')
                    cell.font = Font(name='Arial', size=8, bold=True, color='FFC0392B')
                    ws.row_dimensions[r_i].height = 48

        for i, w in enumerate(col_widths, 1):
            ws.column_dimensions[chr(64 + i)].width = w
        ws.freeze_panes = 'A3'

        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        return buf

    buf = build_excel(df_out, date_start, date_end, with_transfer=has_transfer)
    st.download_button(
        label="⬇️ 匯出廠內配料表（Excel）",
        data=buf,
        file_name=f"廠內配料表_{date_start.strftime('%Y%m%d')}_{date_end.strftime('%Y%m%d')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
