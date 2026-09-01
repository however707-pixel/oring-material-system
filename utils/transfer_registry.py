r"""
@新版-加工廠互調料彙整表（新版互調料登記表）解析工具

NAS 路徑：
  \\192.168.2.34\MO_Storage\ORing MO\ORing-MO 工作\資材部\
  每日調撥與送燒ic(NEW)\生管互調料通知\@新版互調料表

活頁簿結構（依「規則」工作表 + 實際檔案）：
  規則 / 待備料 / 待轉倉 / 待進料 / 已完成 五張表。
  「已完成」不抓（已結案），其餘三張＝尚未完成的登記，全部撈出來。

欄位（實際檔案 A～U，比「規則」多了 R:U14廠內無人機倉、U:備註）：
  A 開單日   B 單號及領料單號  C 通知日   D 填表日期  E 填表人   F 預計進貨日
  G 品號     H 轉出倉別
  I~R 各廠調入數量：國智 / 唐佑 / 秦宏 / R06 / 廠內 / 貫崑 / R05 / 正文 /
                    國智(無人機) / U14廠內無人機倉
  S 最終完成日  T 調撥異常待確認（公式，符合條件顯示「急料」）  U 備註

  ※ 數量欄＝「調入」的廠別，H 欄＝轉出來源倉。
    例：H=電子倉、J(唐佑)=1000 → 電子倉調 1000 給唐佑。

逾期規則（規則工作表第 2 節，嚴格大於）：
  待備料：最終完成日 距今 > 3 天
  待轉倉：通知日     距今 > 7 天
  待進料：預計進貨日 距今 > 2 天
"""
import os as _os
import warnings as _warnings

import pandas as pd

# ── NAS 來源 ─────────────────────────────────────────────────────────────────
NAS_REG_DIR = ("//192.168.2.34/MO_Storage/ORing MO/ORing-MO 工作/資材部/"
               "每日調撥與送燒ic(NEW)/生管互調料通知/@新版互調料表")
NAS_REG_PFX = "@新版-加工廠互調料"        # 彙/滙 兩種寫法都吃得到

# 「已完成」「規則」不抓
PENDING_SHEETS = ["待備料", "待轉倉", "待進料"]
DONE_SHEET     = "已完成"

# 調入廠別欄（依表頭名稱比對，不靠欄位位置）
DEST_COLS = ['國智', '唐佑', '秦宏', 'R06', '廠內', '貫崑', 'R05', '正文',
             '國智(無人機)', 'U14廠內無人機倉']

# 逾期判斷：狀態 → (依據欄, 天數門檻)
OVERDUE_RULE = {'待備料': ('最終完成日', 3),
                '待轉倉': ('通知日',     7),
                '待進料': ('預計進貨日', 2)}

DATE_COLS = ['開單日', '通知日', '填表日期', '預計進貨日', '最終完成日']

OUT_COLS = ['狀態', '廠別', '品號', '數量', '轉出倉別', '單號及領料單號',
            '開單日', '通知日', '填表日期', '預計進貨日', '最終完成日',
            '填表人', '急料', '逾期', '逾期天數', '備註']


def _to_date(s):
    # 表內混雜日期、'X'、'202608/27' 等寫法，一律 coerce；忽略格式推斷警告
    with _warnings.catch_warnings():
        _warnings.simplefilter('ignore')
        return pd.to_datetime(s, errors='coerce')


def _clean_pn(s):
    return s.fillna('').astype(str).str.strip()


def parse_registry(src, today=None):
    """
    讀新版互調料登記表，回傳 (tidy DataFrame, 警告訊息 list)。

    src：檔案路徑 或 Streamlit UploadedFile。
    一列登記若同時填了多個廠別數量，會拆成多列（一廠一列）。
    「已完成」工作表不讀；範例列（單號=範例）自動略過。
    """
    warns = []
    today = pd.Timestamp(today).normalize() if today is not None \
        else pd.Timestamp.today().normalize()

    try:
        xl = pd.ExcelFile(src)
    except Exception as e:
        return pd.DataFrame(columns=OUT_COLS), [f"互調料登記表讀取失敗：{e}"]

    frames = []
    for sh in PENDING_SHEETS:
        if sh not in xl.sheet_names:
            warns.append(f"找不到「{sh}」工作表，已略過")
            continue
        try:
            df = pd.read_excel(xl, sheet_name=sh, header=0)
        except Exception as e:
            warns.append(f"「{sh}」讀取失敗：{e}")
            continue
        if df.empty:
            continue

        df.columns = [str(c).strip() for c in df.columns]
        if '品號' not in df.columns:
            warns.append(f"「{sh}」找不到「品號」欄，已略過")
            continue

        for c in DATE_COLS:
            if c not in df.columns:
                df[c] = pd.NaT
            else:
                df[c] = _to_date(df[c])
        for c in ['單號及領料單號', '轉出倉別', '填表人', '備註', '調撥異常待確認']:
            if c not in df.columns:
                df[c] = ''
            else:
                df[c] = df[c].fillna('').astype(str).str.strip()

        df['品號'] = _clean_pn(df['品號'])

        # 範例列 / 空品號不算
        df = df[(df['品號'] != '') & (df['品號'] != 'nan')]
        df = df[~df['單號及領料單號'].str.contains('範例', na=False)]
        df = df[df['品號'] != '111111111111']
        if df.empty:
            continue

        dests = [c for c in DEST_COLS if c in df.columns]
        if not dests:
            warns.append(f"「{sh}」找不到任何廠別數量欄，已略過")
            continue

        # 寬轉長：一廠一列，只留有數量的
        long = df.melt(
            id_vars=['品號', '單號及領料單號', '轉出倉別', '填表人', '備註',
                     '調撥異常待確認'] + DATE_COLS,
            value_vars=dests, var_name='廠別', value_name='數量',
        )
        long['數量'] = pd.to_numeric(long['數量'], errors='coerce')
        long = long[long['數量'].notna() & (long['數量'] > 0)]
        if long.empty:
            continue

        long['狀態'] = sh
        long['急料'] = long['調撥異常待確認'].str.contains('急', na=False)

        # 逾期：依規則工作表，嚴格大於，未來日期與非日期不算
        base_col, limit = OVERDUE_RULE.get(sh, (None, None))
        if base_col and base_col in long.columns:
            gap = (today - long[base_col]).dt.days
            long['逾期天數'] = gap.where(gap > limit)
        else:
            long['逾期天數'] = pd.NA
        long['逾期'] = long['逾期天數'].notna()

        frames.append(long)

    if not frames:
        return pd.DataFrame(columns=OUT_COLS), warns

    out = pd.concat(frames, ignore_index=True)
    out['數量'] = out['數量'].astype(float)
    out = out[OUT_COLS]
    order = {s: i for i, s in enumerate(PENDING_SHEETS)}
    out = out.sort_values(
        ['狀態', '逾期', '開單日'],
        key=lambda s: s.map(order) if s.name == '狀態' else s,
        ascending=[True, False, True],
    ).reset_index(drop=True)
    return out, warns


def pending_map(reg_df, dest):
    """指定廠別（如 '唐佑' / '國智'）→ {品號: 未完成登記總量}"""
    if reg_df is None or reg_df.empty:
        return {}
    sub = reg_df[reg_df['廠別'] == dest]
    if sub.empty:
        return {}
    return sub.groupby('品號')['數量'].sum().to_dict()


def status_map(reg_df, dest):
    """指定廠別 → {品號: '待備料 1,000｜待進料 800'}（逾期加 ⏰）"""
    if reg_df is None or reg_df.empty:
        return {}
    sub = reg_df[reg_df['廠別'] == dest]
    if sub.empty:
        return {}
    out = {}
    for pno, g in sub.groupby('品號'):
        parts = []
        for sh in PENDING_SHEETS:
            gg = g[g['狀態'] == sh]
            if gg.empty:
                continue
            tag = '⏰' if gg['逾期'].any() else ''
            parts.append(f"{tag}{sh} {int(gg['數量'].sum()):,}")
        out[pno] = '｜'.join(parts)
    return out
