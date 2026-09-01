import importlib
import io
import os
import sys
from datetime import date

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from utils.shared import ensure_calamine, inject_css, render_header, render_sidebar
from utils import full_process_data as fpd
from utils import full_process_ui as ui

# Streamlit 對「被 page 匯入的模組」熱重載不可靠：頁面檔改了會生效，但
# utils/full_process_data.py 改了常常還留在 sys.modules 裡（畫面數字不會動，
# 而且 DATA_VERSION 可能已經是新的，更難察覺）。這裡自己盯檔案時間重載，
# 並把 mtime 當快取鍵的一部分，改完存檔重新整理就一定吃到新版。
_FPD_MTIME = int(os.path.getmtime(fpd.__file__))
if getattr(fpd, "_loaded_mtime", None) != _FPD_MTIME:
    importlib.reload(fpd)
    fpd._loaded_mtime = _FPD_MTIME
_UI_MTIME = int(os.path.getmtime(ui.__file__))
if getattr(ui, "_loaded_mtime", None) != _UI_MTIME:
    importlib.reload(ui)
    ui._loaded_mtime = _UI_MTIME

st.set_page_config(page_title="全製程", page_icon="⚙️", layout="wide",
                   initial_sidebar_state="expanded")
ensure_calamine()
inject_css()
render_header(
    title="全製程",
    subtitle="Full Process · 一張工單一列 · 母子串連 · 趕不趕得上產銷出貨日",
    badge="全流程",
)
render_sidebar()

# ═══════════════════════════════════════════════════════════════════════════════
# 這一頁要回答的六件事（使用者定義的口徑）：
#   ① 這張訂單，工單開了沒？沒開是「不用開」（庫存／外購）還是「忘了開」？
#   ② 母子工單串連：一張工單一列，母單帶三張子單就是四列，母在上、子縮排在下。
#   ③ 整套子單完工 + 母單，換算起來趕不趕得上產銷出貨日？趕不上卡在哪一張單、
#      缺什麼料、有沒有庫存、什麼時候進貨、要不要請採購拉進貨？
#   ④ 鋼板／載具到該做的那個委外倉了沒？（成品階 9-* 與外購品不需要）
#   ⑤ 廠內與各委外廠每月產能有沒有超出，各多少量？
#   ⑥ 每個月顯示：出貨日掛在該月的（母＋子），以及沒壓出貨日、但最終齊料日
#      掛在該月的母單 —— 這就是該月的基本產能。
#
# 換算公式（使用者定義）：子單齊料日 +1 週＝回廠日，回廠日 +2 週＝完工日；
# 落點碰到假日往後挪到工作日。母單要等所有子單回來，所以整條鏈的預計完工
# ＝ max(自己推算完工, 所有子單的鏈完工)。
#
# 所有天數皆為工作天（扣週末與國定假日，見 utils/workdays.py）。
# 資料來源與關聯鍵見 utils/full_process_data.py 檔頭。
# ═══════════════════════════════════════════════════════════════════════════════

TODAY = date.today()

CAPACITY = fpd.CAPACITY          # 每月上限：國智3萬／唐佑1.5萬／其他1萬／廠內9千

SOURCE_MAP = [
    ("訂單", "交期、數量、客戶", "產銷統計表（mosadexcel）"),
    ("產銷回覆", "庫存／外購／新單／出貨日", "產銷統計表 V2 月報版 X 欄"),
    ("工單", "開工、完工、加工廠、子母單", "ERP：MOCR10"),
    ("料況", "缺什麼料／庫存／進貨日／齊料日", "供需表(分倉) ＋ 調撥單"),
    ("治具", "鋼板／載具在哪一家", "PE 生產治工具一覽表"),
    ("產能", "現場進度、月產能上限", "寶橋廠排程 ＋ 月產能上限"),
]
KEY_COL = "訂單·訂單單號"
ADJ_COL = "工單·調整開工日 ✏️"
DIFF_COL = "工單·差異(工作天)"

# ─── 資料：跟全螢幕版共用同一份快取，兩頁的數字才不會對不起來 ───────────────
load_data, source_status = ui.load_data, ui.source_status

# ─── 畫面元件一律走共用模組（一般版與全螢幕版共用同一套規則）───────────────
esc, tip, pn_html, fuzzy_mask = ui.esc, ui.tip, ui.pn_html, ui.fuzzy_mask
_norm_date, _wd, _md, _days = ui.norm_date, ui.wd, ui.md, ui.days
LIGHT, SORT_FIELDS, NCOL = ui.LIGHT, ui.SORT_FIELDS, ui.NCOL
CAP_WARN, WO_DAYS, RED_WD, YEL_WD = ui.CAP_WARN, ui.WO_DAYS, ui.RED_WD, ui.YEL_WD
_ROW_DEFECTS = []

# ─── 資料來源 ────────────────────────────────────────────────────────────────
_FINGERPRINT = ui.data_mtime()   # 內容雜湊，見 ui.data_mtime 說明
_src = source_status(fpd.DATA_VERSION, _FINGERPRINT)
_ok = sum(1 for _l, _n, _d, _g in _src if _g)
with st.expander("📂 資料來源　{}/{} 個檔案讀取正常".format(_ok, len(_src)),
                 expanded=(_ok < len(_src))):
    a, b = st.columns(2)
    a.caption("欄位群組 → 來源")
    a.dataframe(pd.DataFrame([{"群組": g, "內容": c, "來源": s} for g, c, s in SOURCE_MAP]),
                hide_index=True, use_container_width=True)
    b.caption("實際讀到的檔案")
    b.dataframe(pd.DataFrame([{"來源": l, "檔案": n, "日期": d} for l, n, d, _g in _src]),
                hide_index=True, use_container_width=True)
    st.caption("快取 10 分鐘　·　資料版本 v{}　·　齊料日 +1 週＝回廠、+2 週＝完工"
               "（碰假日往後挪到工作日）".format(fpd.DATA_VERSION))

# ─── 控制列 ──────────────────────────────────────────────────────────────────
c1, c2, c3, c4 = st.columns([1, 1.6, 2.4, 0.9])
if c4.button("🔄 重新讀取", use_container_width=True,
             help="清掉 10 分鐘快取，重新讀 NAS。來源檔換檔或口徑改版後按這個。"):
    st.cache_data.clear()
    st.rerun()
_year = c1.selectbox("年度", [TODAY.year, TODAY.year - 1, TODAY.year + 1], index=0,
                     help="只顯示該年度（交期年；交期空白時看開工年）。"
                          "ERP 有大量 2020~2025 未結案的殭屍單，不濾會整個洗版。")
_view_mode = c2.radio("看什麼", ["全部", "只看趕不上的", "只看卡料的", "只看沒開工單的"],
                      horizontal=True,
                      help="「趕不上」＝整條鏈的預計完工晚於產銷出貨日。"
                           "篩選後母子還是綁在一起，不會出現孤兒子單。")
kw = c3.text_input("關鍵字（料號／工單／客戶）", "",
                   help="命中任何一張單就把整個母子家族帶出來。")

df = load_data(_year, fpd.DATA_VERSION, _FINGERPRINT)
if df.empty:
    st.error("讀不到資料。請確認 NAS 路徑可連線。", icon="🚫")
    st.stop()

# 快取有可能是舊結構（模組熱重載沒跟上時會發生），欄位對不上就直接 KeyError 掛掉。
# 與其讓使用者看到 traceback，不如自己檢查、自動清快取重建一次。
_NEED_COLS = [
    "訂單·料號", "訂單·數量", "訂單·交期", "訂單·訂單日", "訂單·有出貨需求",
    "訂單·產銷回覆", "訂單·出貨判定", "訂單·V2出貨日", "訂單·需生產", "訂單·外購品",
    "工單·工單號", "工單·開單狀態", "工單·母工單", "工單·階層", "工單·子單數",
    "工單·子單號", "工單·子單明細",
    "工單·開工日", "工單·完工日", "工單·加工廠", "工單·廠商原名",
    "料況·齊套狀態", "料況·缺料件數", "料況·缺料庫存", "料況·成品庫存",
    "料況·最終齊料日", "料況·齊料來源", "料況·缺料明細", "料況·缺料項目",
    "排程·回廠日", "排程·推算完工",
    "鏈·預計完工", "鏈·目標出貨日", "鏈·出貨日來源", "鏈·結論", "鏈·寬裕工作天",
    "鏈·卡點", "鏈·卡料", "鏈·採購動作", "鏈·根工單", "鏈·層深",
    "月份·歸屬", "月份·來源",
    "治具·鋼板", "治具·載具", "治具·明細", "治具·到廠",
    "產能·排產狀況", "產能·已完工", "產能·廠內進度", "產能·產線WIP",
]
_missing = [c for c in _NEED_COLS if c not in df.columns]
if _missing:
    if not st.session_state.get("_fp_reloaded"):
        st.session_state["_fp_reloaded"] = True
        st.cache_data.clear()
        st.rerun()
    st.error("資料結構與頁面不符，缺少欄位：{}。已試過自動重建仍失敗，"
             "請按「🔄 重新讀取」，或回報這個訊息。".format("、".join(_missing[:8])),
             icon="🚫")
    st.stop()
st.session_state["_fp_reloaded"] = False

if "fp_adj" not in st.session_state:
    st.session_state["fp_adj"] = {}
ADJ = st.session_state["fp_adj"]

f1, f2, f3 = st.columns([1.6, 1.1, 1.2])
_facs = sorted(df["工單·加工廠"].unique())
fac_sel = f1.multiselect("加工廠", _facs, default=_facs,
                         help="注意：成品母單與板階子單常在不同廠（例如母單廠內、"
                              "子單唐佑），篩掉其中一邊會讓母子看起來斷掉 —— "
                              "所以篩完還是會把缺席的母單補回來。")
_hide_stale = f2.checkbox("隱藏舊工單", value=True,
                          help="交期在本年度、但開工日停在 {} 年以前的工單。"
                               "ERP 沒結案也沒更新排程，留著會報出「逾 1600 多天」這種數字。"
                               .format(_year - 1))
_fin_from = f3.date_input("完工日 ≥", value=date(TODAY.year, TODAY.month, 1),
                          help="完工日早於這一天的工單全部拉掉。預設本月 1 日。"
                               "還沒發單、沒有完工日的列不受影響（那些是待開工單，仍要處理）。")

# ─── 調整開工日（原開工日保留不動）───────────────────────────────────────────
df[ADJ_COL] = [ADJ.get(k) for k in df[KEY_COL]]
df["_start"] = [a or s for a, s in zip(df[ADJ_COL], df["工單·開工日"])]
df[DIFF_COL] = [_wd(s, a) if (a and s) else None
                for a, s in zip(df[ADJ_COL], df["工單·開工日"])]


# ─── 篩選 ────────────────────────────────────────────────────────────────────
view = df[df["工單·加工廠"].isin(fac_sel)].copy()

# 殭屍工單：交期在本年度、開工日卻停在前年以前（ERP 沒結案也沒更新排程）。
_stale_floor = date(_year - 1, 1, 1)
_stale_mask = [bool(s) and s < _stale_floor for s in view["工單·開工日"]]
_stale_n = sum(_stale_mask)
if _hide_stale and _stale_n:
    view = view[[not x for x in _stale_mask]]

# 完工日早於指定日期的一律拉掉（沒有完工日的＝還沒發單，留著）
_fin_cut = _norm_date(_fin_from)
if _fin_cut:
    _fin_mask = [(f is None) or (f >= _fin_cut) for f in view["工單·完工日"]]
    _fin_drop = len(_fin_mask) - sum(_fin_mask)
    view = view[_fin_mask]
else:
    _fin_drop = 0

if _view_mode == "只看趕不上的":
    _pick = view["鏈·結論"].astype(str).str.startswith("❌")
elif _view_mode == "只看卡料的":
    _pick = view["料況·缺料件數"] > 0
elif _view_mode == "只看沒開工單的":
    _pick = view["工單·開單狀態"] == "未開立"
else:
    _pick = pd.Series(True, index=view.index)

if kw.strip():
    _pick = _pick & fuzzy_mask(view, kw)

# 命中一張就把整個母子家族帶出來（查母單要看得到子單，查子單也要看得到母單）
_fam = set(view.loc[_pick, "鏈·根工單"])
view = view[_pick | view["鏈·根工單"].isin(_fam)]

if view.empty:
    st.info("目前篩選條件下沒有資料。", icon="🔍")
    st.stop()

_PRESENT_WO = set(view["工單·工單號"])

# 產能負載：加工廠 × 歸屬月份。用整份資料算，不跟著畫面篩選變 ——
# 產線的負荷是實體的，畫面上篩掉幾張工單不會讓產能空出來。
# 逐張的累計（依產銷出貨日排隊）在資料層算好了，見 fpd.capacity_queue。
FAC_LOAD = df.groupby(["工單·加工廠", "月份·歸屬"])["產能·計入量"].sum().to_dict()
_DONE_N = int(df["產能·已完工"].sum())

_noprod = (~view["訂單·需生產"]) & (view["工單·工單號"] == "")
_np_view = view[_noprod].copy()
_prod_view_all = view[~_noprod].copy()

# ─── KPI ─────────────────────────────────────────────────────────────────────
# KPI 一律只算「要生產的」那包；不用生產的另外掛在最後一格，點下去看下方獨立區塊。
_pv = _prod_view_all
_w = _pv[_pv["工單·工單號"] != ""]
k = st.columns(7)
k[0].metric("工單列數", "{:,}".format(len(_w)),
            help="一張工單一列；母單與板階子單各自算一列。只算要生產的。")
k[1].metric("❌ 趕不上", "{:,}".format(int(_pv["鏈·結論"].astype(str).str.startswith("❌").sum())),
            help="整條鏈（母＋所有子單）的預計完工晚於產銷出貨日。")
k[2].metric("✅ 來得及", "{:,}".format(int(_pv["鏈·結論"].astype(str).str.startswith("✅").sum())))
k[3].metric("未開工單", "{:,}".format(int((_pv["工單·開單狀態"] == "未開立").sum())),
            help="有訂單、產銷也說要生產，但 ERP 查不到工單 ＝ 忘了開。")
k[4].metric("缺料工單", "{:,}".format(int((_pv["料況·缺料件數"] > 0).sum())))
k[5].metric("🔺 要催採購", "{:,}".format(int(_pv["鏈·採購動作"].astype(str)
                                            .str.startswith("🔺").sum())),
            help="缺料的最晚進貨日晚於產銷出貨日，或根本沒有進貨排程。")
k[6].metric("➖ 不用生產", "{:,}".format(len(_np_view)),
            help="產銷回覆「庫存」或「外購」，而且沒有工單 —— 不經製程，"
                 "已從每月排程整包移到下方「不用生產」區塊，不佔產能。")

_notes = []
if _stale_n:
    _notes.append("{}開工日早於 {} 年的舊工單 {:,} 筆"
                  .format("已隱藏" if _hide_stale else "含", _year - 1, _stale_n))
if _fin_drop:
    _notes.append("已拉掉完工日早於 {:%Y/%m/%d} 的 {:,} 筆".format(_fin_cut, _fin_drop))
if _notes:
    st.caption("　·　".join(_notes) + "。沒有完工日的（未發單）不受完工日條件影響。")


# ─── 樣式與圖例 ─────────────────────────────────────────────────────────────
st.markdown(ui.TABLE_CSS, unsafe_allow_html=True)
st.markdown(ui.legend_html("　一張工單一列，母單在上、板階子單縮排在下　·　天數皆為工作天"),
            unsafe_allow_html=True)

_sort = str(st.query_params.get("sort") or "出貨日")
if _sort not in SORT_FIELDS:
    _sort = "出貨日"
_desc = str(st.query_params.get("desc") or "0") == "1"

# ─── 缺料明細分頁（點表格裡的缺料格子帶 ?wo= 進來）──────────────────────────
_sel_wo = str(st.query_params.get("wo") or "").strip()
# 備援入口：Streamlit 的 HTML 淨化偶爾會把某個 <a> 的 href 剝掉（實測 1,350 個
# 連結裡約 2 個），那格就點不動。這裡提供不依賴連結的查法，直接打製令號。
_wq = st.text_input("🔎 直接查工單缺料明細（輸入製令號，表格裡的缺料格也可以點）",
                    value=_sel_wo, key="wo_lookup",
                    placeholder="例如 5145-20260410009").strip()
if _wq != _sel_wo:
    if _wq:
        st.query_params["wo"] = _wq
    else:
        st.query_params.pop("wo", None)
    st.rerun()
if _sel_wo:
    _sub = view[view["工單·工單號"] == _sel_wo]
    if not len(_sub):
        _sub = df[df["工單·工單號"] == _sel_wo]
    st.markdown('<div style="margin:6px 0 4px;font-size:0.95rem;font-weight:800;'
                'color:#b91c1c;">🔎 缺料明細 ｜ {}</div>'.format(esc(_sel_wo)),
                unsafe_allow_html=True)
    if not len(_sub):
        st.info("這張工單不在目前的年度／篩選範圍內。", icon="🔍")
    else:
        _r = _sub.iloc[0]
        st.caption("{}　·　{}　·　開工 {}　·　齊料 {}　·　回廠 {}　·　完工 {}　·　{}"
                   .format(_r["訂單·料號"], _r["工單·加工廠"], _md(_r["_start"]),
                           _md(_r["料況·最終齊料日"]), _md(_r["排程·回廠日"]),
                           _md(_r["排程·推算完工"]), _r["料況·齊套狀態"]))
        _items = _r["料況·缺料項目"] or []
        if not _items:
            st.success("這張工單目前沒有缺料。", icon="✅")
        else:
            st.dataframe(pd.DataFrame([{
                "品號": x["品號"], "品名": str(x.get("品名") or "")[:26],
                "庫別": "{} {}".format(x.get("庫別") or "", x.get("庫別名稱") or "").strip(),
                "需求量": int(x["需求量"]), "配到": int(x.get("配到", 0)),
                "缺量": int(x.get("缺量", 0)),
                "前面工單先佔": int(x.get("先前佔用", 0)),
                "全倉庫存": int(x.get("全倉", 0) or 0),
                "預計進貨日": x.get("進貨日"),
                "進貨量": (int(x["進貨量"]) if x.get("進貨量") else None),
                "進貨廠商": x.get("進貨廠商") or "",
                "需求日": x.get("需求日"),
            } for x in _items]), hide_index=True, use_container_width=True)
            st.caption("「配到」是依開工日排隊後這張工單實際分到的量；「前面工單先佔」是"
                       "同一個倉、開工日更早的工單已經吃掉的量。缺量＝需求−配到。"
                       "　·　{}".format(_r["鏈·採購動作"]))
    if st.button("✕ 關閉明細", key="close_drill"):
        st.query_params.clear()
        st.rerun()
    st.divider()

# ─── 不用生產：整包獨立，不進每月排程 ───────────────────────────────────────
# 使用者要求：主表只看要生產的、進度在哪；產銷回覆庫存／外購的另外做一包。
if len(_np_view):
    _n_stock = int((_np_view["訂單·出貨判定"] == "庫存").sum())
    _n_buy = len(_np_view) - _n_stock
    with st.expander("➖ 不用生產 {} 筆　·　數量 {:,}　（庫存直接出 {} 筆／外購買進賣出 {} 筆）"
                     "　—— 不經製程、不用工單、不用治具、不佔產能"
                     .format(len(_np_view), int(_np_view["訂單·數量"].sum()),
                             _n_stock, _n_buy), expanded=False):
        _npt = _np_view[[KEY_COL, "訂單·客戶", "訂單·料號", "訂單·品名", "訂單·數量",
                         "訂單·交期", "訂單·V2出貨日", "訂單·出貨判定",
                         "訂單·產銷回覆"]].copy()
        _npt["類別"] = ["庫存直接出" if x == "庫存" else "外購" for x in _npt["訂單·出貨判定"]]
        _npt = _npt.sort_values(["類別", "訂單·V2出貨日", "訂單·交期"], na_position="last")
        _cat = st.radio("看哪一類", ["全部", "庫存直接出", "外購"], horizontal=True,
                        key="np_cat",
                        help="庫存＝倉庫有帳，直接出貨；外購＝買進賣出，連製程都沒有。")
        _show = _npt if _cat == "全部" else _npt[_npt["類別"] == _cat]
        st.dataframe(_show, hide_index=True, use_container_width=True,
                     column_config={
                         "訂單·交期": st.column_config.DateColumn(format="YYYY/MM/DD",
                                                                width="small"),
                         "訂單·V2出貨日": st.column_config.DateColumn("產銷回覆出貨日",
                                                                   format="YYYY/MM/DD",
                                                                   width="small"),
                         "訂單·數量": st.column_config.NumberColumn(format="%d", width="small"),
                         "訂單·品名": st.column_config.TextColumn(width="medium"),
                         "訂單·產銷回覆": st.column_config.TextColumn(width="medium"),
                     })
        _b1 = int((_np_view["訂單·出貨判定"] == "外購·庫存").sum())
        _b2 = int((_np_view["訂單·出貨判定"] == "外購·待定").sum())
        _b3 = int((_np_view["訂單·出貨判定"] == "外購·有日期").sum())
        st.caption("外購細分：已有庫存 {} 筆　·　有進貨日 {} 筆　·　交期待定(TBD) {} 筆。"
                   "這一包完全不進上面的每月排程，也不計入任何一家的月產能。"
                   .format(_b1, _b3, _b2))

# 產銷說不用生產、但 ERP 已經有工單的 —— 工單是真的在跑（而且常帶著要生產的板階
# 子單），所以留在主表；這裡只提醒有這一群，值得回頭確認是不是白開了。
_odd = _prod_view_all[~_prod_view_all["訂單·需生產"]]
if len(_odd):
    st.caption("另有 {} 張工單，產銷回覆說「庫存／外購」但 ERP 已經開了工單 —— "
               "工單是真的在跑（其中 {} 張還帶著板階子單），所以留在下面的每月排程裡，"
               "「趕得上嗎」欄會標 ➖ 不用生產。".format(
                   len(_odd), int((_odd["工單·子單數"] > 0).sum())))

# ─── ⑥ 每個月：出貨日掛該月的（母＋子）＋ 沒壓出貨日但齊料掛該月的 ───────────
_cur = "{:04d}-{:02d}".format(TODAY.year, TODAY.month)
PER_MONTH = 300          # 每月最多畫幾列（全畫 HTML 會太肥）

_prod_view = _prod_view_all
_months = sorted({m for m in _prod_view["月份·歸屬"] if m})
_in_year = [m for m in _months if m.startswith(str(_year))]
_out_year = [m for m in _months if not m.startswith(str(_year))]

st.markdown('<div style="margin:14px 0 6px;font-size:0.95rem;font-weight:800;color:#475569;">'
            '📅 每月出貨與基本產能</div>', unsafe_allow_html=True)
st.caption("月份歸屬：有產銷出貨日就看出貨日，沒有就看最終齊料日。同一條母子鏈"
           "（母單＋所有板階子單）一律跟著母單歸在同一個月，否則四列會被拆散在不同月份。")

_sort_col = SORT_FIELDS[_sort]


def _month_block(m, g):
    # 家族排序與整張表都走共用模組，跟全螢幕版同一套規則
    g = ui.family_sorted(g, _sort_col, _desc)
    n_late = int(g["鏈·結論"].astype(str).str.startswith("❌").sum())
    n_kid = int(g["鏈·層深"].sum())
    n_ship = int(g["鏈·目標出貨日"].notna().sum())
    title = ("📅 {}　{} 列（母 {}／子 {}）　·　數量 {:,}　·　有出貨日 {}　·　❌ 趕不上 {}"
             .format(m, len(g), len(g) - n_kid, n_kid,
                     int(g["訂單·數量"].sum()), n_ship, n_late))
    with st.expander(title, expanded=(m == _cur)):
        cap_line = []
        for fac in ["廠內", "國智", "唐佑", "其他"]:
            q = int(FAC_LOAD.get((fac, m), 0))
            if not q:
                continue
            cap = CAPACITY[fac]
            mark = "🔴" if q > cap else "🟡" if q >= cap * CAP_WARN else "🟢"
            cap_line.append("{} {} {:,}/{:,}".format(mark, fac, q, cap))
        if cap_line:
            st.caption("本月基本產能　" + "　·　".join(cap_line))
        st.markdown(ui.table_html(g, _sort, _desc, _PRESENT_WO,
                                  _ROW_DEFECTS, limit=PER_MONTH),
                    unsafe_allow_html=True)
        if len(g) > PER_MONTH:
            st.caption("本月僅列前 {} 列（共 {:,} 列）。用上方「看什麼」只留要處理的，"
                       "或看下方明細表／匯出 Excel。".format(PER_MONTH, len(g)))


if not _months:
    # 篩選條件有可能把「要生產的」整包濾光（例如只留不用生產的那些），
    # 這時月份區塊會是空的 —— 直接講清楚，不要留一片空白讓人以為壞掉。
    st.info("目前篩選條件下沒有要生產的工單。不用生產的那 {} 筆在上方獨立區塊。"
            .format(len(_np_view)), icon="🔍")

for m in _in_year:
    _month_block(m, _prod_view[_prod_view["月份·歸屬"] == m].copy())

if _out_year:
    _og = _prod_view[_prod_view["月份·歸屬"].isin(_out_year)]
    with st.expander("📅 跨年度：{}　共 {} 列（母單出貨日或齊料日不在 {} 年）"
                     .format("、".join(_out_year), len(_og), _year), expanded=False):
        for m in _out_year:
            _sub2 = _og[_og["月份·歸屬"] == m]
            st.markdown('<div style="font-size:0.8rem;font-weight:700;color:#64748b;'
                        'margin:8px 0 3px;">{}　{} 列</div>'.format(m, len(_sub2)),
                        unsafe_allow_html=True)
            st.markdown(ui.table_html(_sub2, _sort, _desc, _PRESENT_WO,
                                      _ROW_DEFECTS, limit=60),
                        unsafe_allow_html=True)

if _ROW_DEFECTS:
    st.error("表格渲染異常：{} 列的欄數不對（{}）。請回報，不要拿這張表做判斷。"
             .format(len(_ROW_DEFECTS), _ROW_DEFECTS[:5]), icon="⚠")


# ─── ⑤ 產能：每月 × 每廠 ─────────────────────────────────────────────────────
st.markdown('<div style="margin:16px 0 6px;font-size:0.95rem;font-weight:800;color:#475569;">'
            '📊 產能 ｜ 各月各廠投產量 vs 月上限</div>', unsafe_allow_html=True)
_show_m = [m for m in _in_year if m >= _cur][:6] or _in_year[-6:]
_grid = []
for fac, cap in CAPACITY.items():
    row = {"加工廠": fac, "月上限": cap}
    for m in _show_m:
        row[m] = int(FAC_LOAD.get((fac, m), 0))
    _grid.append(row)
_cap_df = pd.DataFrame(_grid)


def _cap_color(s):
    if s.name in ("加工廠", "月上限"):
        return ["" for _ in s]
    out = []
    for v, cap in zip(s, _cap_df["月上限"]):
        if v > cap:
            out.append("background-color:#fef2f2;color:#b91c1c;font-weight:800")
        elif v >= cap * CAP_WARN:
            out.append("background-color:#fefce8;color:#a16207;font-weight:800")
        else:
            out.append("background-color:#eff6ff;color:#1d4ed8;font-weight:700")
    return out


if _show_m:
    st.dataframe(_cap_df.style.apply(_cap_color, axis=0),
                 hide_index=True, use_container_width=True)
    st.caption("紅＝超出月上限、黃＝離上限剩 15% 以內。已扣除寶橋廠排程標記完工／取消的 "
               "{:,} 列，以及產銷回覆「庫存／外購」不用生產的。母單（成品階）與子單"
               "（板階）各算各的廠，因為本來就是兩段不同的工。".format(_DONE_N))


# ─── 明細表（可編輯調整開工日）───────────────────────────────────────────────
DETAIL_COLS = [
    KEY_COL, "訂單·客戶", "訂單·料號", "訂單·品名", "訂單·數量", "訂單·交期",
    "訂單·產銷回覆", "訂單·出貨判定", "訂單·V2出貨日",
    "工單·開單狀態", "工單·工單號", "工單·階層", "工單·母工單", "工單·子單數",
    "工單·開工日", ADJ_COL, DIFF_COL, "工單·完工日", "工單·加工廠",
    "料況·齊套狀態", "料況·缺料件數", "料況·缺料庫存", "料況·最終齊料日", "料況·齊料來源",
    "排程·回廠日", "排程·推算完工",
    "鏈·預計完工", "鏈·目標出貨日", "鏈·結論", "鏈·寬裕工作天", "鏈·卡點", "鏈·卡料",
    "鏈·採購動作", "月份·歸屬", "月份·來源",
    "治具·到廠", "治具·鋼板", "治具·載具",
    "產能·排產狀況", "產能·廠內進度", "產能·產線WIP",
]
with st.expander("📋 明細表 ｜ 只列要生產的，可編輯「調整開工日」（原開工日保留不動）",
                 expanded=False):
    tbl = _prod_view_all[[c for c in DETAIL_COLS if c in _prod_view_all.columns]]
    colcfg = {
        "訂單·交期":       st.column_config.DateColumn(format="YYYY/MM/DD", width="small"),
        "訂單·V2出貨日":   st.column_config.DateColumn("產銷回覆出貨日", format="YYYY/MM/DD",
                                                     width="small"),
        "訂單·數量":       st.column_config.NumberColumn(format="%d", width="small"),
        "訂單·品名":       st.column_config.TextColumn(width="medium"),
        "工單·開工日":     st.column_config.DateColumn("工單·開工日（原）", format="YYYY/MM/DD",
                                                     width="small", help="ERP 原始開工日，不會被覆蓋"),
        ADJ_COL:          st.column_config.DateColumn(format="YYYY/MM/DD", width="small",
                                                      help="可直接改；改完燈號與產能分月會跟著重算"),
        DIFF_COL:         st.column_config.NumberColumn(format="%+d", width="small"),
        "工單·完工日":     st.column_config.DateColumn(format="YYYY/MM/DD", width="small"),
        "料況·最終齊料日": st.column_config.DateColumn(format="YYYY/MM/DD", width="small"),
        "料況·缺料件數":   st.column_config.NumberColumn(format="%d", width="small"),
        "排程·回廠日":     st.column_config.DateColumn(format="YYYY/MM/DD", width="small"),
        "排程·推算完工":   st.column_config.DateColumn(format="YYYY/MM/DD", width="small"),
        "鏈·預計完工":     st.column_config.DateColumn(format="YYYY/MM/DD", width="small"),
        "鏈·目標出貨日":   st.column_config.DateColumn(format="YYYY/MM/DD", width="small"),
        "鏈·寬裕工作天":   st.column_config.NumberColumn(format="%+d", width="small",
                                                       help="正＝還有幾個工作天寬裕；負＝晚了幾個工作天"),
        "產能·產線WIP":    st.column_config.NumberColumn(format="%d", width="small"),
    }
    edited = st.data_editor(
        tbl, hide_index=True, use_container_width=True, column_config=colcfg,
        disabled=[c for c in tbl.columns if c != ADJ_COL],
        key="fp_editor", height=min(620, 62 + 35 * max(len(tbl), 1)),
    )
    if ADJ_COL in edited.columns:
        _changed = False
        for w, v in zip(_prod_view_all[KEY_COL], edited[ADJ_COL]):
            v = _norm_date(v)
            if ADJ.get(w) != v:
                _changed = True
                ADJ.pop(w, None) if v is None else ADJ.update({w: v})
        if _changed:
            st.rerun()

b1, b2, _sp = st.columns([1, 1, 4])
if b1.button("↺ 清除全部開工日調整", use_container_width=True):
    st.session_state["fp_adj"] = {}
    st.rerun()
_buf = io.BytesIO()
# 「料況·缺料項目」是 list，直接寫進 Excel 會變成一長串 Python repr。
# 可讀的缺料內容在「料況·缺料明細」那一欄，匯出用那個就夠。
_prod_view_all.drop(columns=["_start", "_cap_qty", "_s", "料況·缺料項目"],
                    errors="ignore").to_excel(_buf, index=False, engine="openpyxl")
_buf.seek(0)
b2.download_button("⬇ 匯出 Excel（要生產的）", data=_buf, use_container_width=True,
                   help="只匯出要生產的那包；不用生產的在上方獨立區塊，表格右上角也可以下載。",
                   file_name="全製程_{:%Y%m%d}.xlsx".format(TODAY),
                   mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

adj_rows = _prod_view_all[_prod_view_all[ADJ_COL].notna()]
if len(adj_rows):
    with st.expander("🕒 已調整開工日：{} 筆".format(len(adj_rows)), expanded=True):
        st.dataframe(
            adj_rows[[KEY_COL, "工單·工單號", "訂單·料號", "工單·開工日", ADJ_COL, DIFF_COL,
                      "工單·完工日", "工單·加工廠", "鏈·結論"]],
            hide_index=True, use_container_width=True)
