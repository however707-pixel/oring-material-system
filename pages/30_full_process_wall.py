import importlib
import io
import os
import sys
from datetime import date
from urllib.parse import quote

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from utils.shared import ensure_calamine, inject_css
from utils import full_process_data as fpd
from utils import full_process_ui as ui

# 熱重載：Streamlit 對「被 page 匯入的模組」重載不可靠，改了 utils 常常不生效。
for _m in (fpd, ui):
    _mt = int(os.path.getmtime(_m.__file__))
    if getattr(_m, "_loaded_mtime", None) != _mt:
        importlib.reload(_m)
        _m._loaded_mtime = _mt

st.set_page_config(page_title="全製程 · 全螢幕", page_icon="🖥️", layout="wide",
                   initial_sidebar_state="collapsed")
ensure_calamine()
inject_css()

# ═══════════════════════════════════════════════════════════════════════════════
# 全製程 · 全螢幕版
#
# 跟 pages/29_full_process.py 是同一份資料、同一套燈號規則（都走
# utils/full_process_ui.py），差別只在畫面：
#   * 沒有側邊主題選單，整個視窗都給表格
#   * 一次只看一個月，用上面的月份鈕切換（月份走 ?m= query param，
#     這樣點表頭排序時月份不會跳掉）
#   * 表身自己捲動、表頭釘住，捲到第 300 列還看得到欄位名稱
#
# 沒有側邊選單，所以所有狀態都放 query param：?m=月份&sort=欄位&desc=0/1&wo=製令號
# ═══════════════════════════════════════════════════════════════════════════════

TODAY = date.today()
CAPACITY = fpd.CAPACITY
CAP_WARN = ui.CAP_WARN
KEY_COL = "訂單·訂單單號"
PER_MONTH = 700          # 最大的月份約 440 列，一次全畫得完

# ─── 全螢幕：把側邊選單與 Streamlit 的預設留白整個拿掉 ───────────────────────
st.markdown("""
<style>
/* 側邊主題選單完全不要，連展開鈕也不留。
   選擇器要重複寫 data-testid 來墊高 specificity：utils/shared.py 用了
   [data-testid="stSidebar"][aria-expanded="true"]（0,2,0），
   單寫 section[data-testid="stSidebar"] 只有 (0,1,1)，會被壓過去，
   實測側邊欄還是 244px 寬地站在那裡。 */
[data-testid="stSidebar"][data-testid][data-testid],
[data-testid="stSidebarContent"][data-testid][data-testid],
[data-testid="stSidebarUserContent"][data-testid][data-testid],
[data-testid="stSidebarHeader"][data-testid][data-testid],
[data-testid="stSidebarCollapsedControl"][data-testid][data-testid],
[data-testid="stSidebarCollapseButton"][data-testid][data-testid],
[data-testid="stExpandSidebarButton"][data-testid][data-testid],
[data-testid="collapsedControl"][data-testid][data-testid]{
  display:none !important; width:0 !important; min-width:0 !important;
  max-width:0 !important; visibility:hidden !important;
}
[data-testid="stAppViewContainer"] > .main,
[data-testid="stMain"]{ margin-left:0 !important; }

/* 版面吃滿整個視窗 */
.block-container{
  max-width:100% !important; padding:0.6rem 1.1rem 1.2rem !important;
}
header[data-testid="stHeader"]{ height:0 !important; min-height:0 !important;
  background:transparent !important; }
[data-testid="stToolbar"]{ right:6px; top:2px; }
footer, #MainMenu { display:none !important; }

/* 控制列壓扁一點，把高度留給表格 */
.block-container [data-testid="stVerticalBlock"]{ gap:0.35rem !important; }
.wallbar{
  display:flex; align-items:center; gap:14px; flex-wrap:wrap;
  padding:8px 12px; margin:0 0 8px;
  background:linear-gradient(90deg,#0f2460 0%,#1e3a8a 55%,#2563eb 100%);
  border-radius:10px; color:#e8efff;
}
.wallbar .ttl{ font-size:1.05rem; font-weight:800; letter-spacing:.04em; }
.wallbar .sub{ font-size:0.72rem; color:#bfd3ff; }
.wallbar .kpi{ display:flex; gap:16px; margin-left:auto; flex-wrap:wrap; }
.wallbar .kpi b{ display:block; font-size:1.15rem; font-weight:800; line-height:1.1;
  font-variant-numeric:tabular-nums; }
.wallbar .kpi span{ font-size:0.68rem; color:#bfd3ff; }
.wallbar a.back{ color:#e8efff !important; text-decoration:none !important;
  border:1px solid rgba(232,239,255,.45); border-radius:7px; padding:3px 9px;
  font-size:0.72rem; }
.wallbar a.back:hover{ background:rgba(255,255,255,.14); }

/* 月份切換鈕 */
.mrow{ display:flex; gap:6px; flex-wrap:wrap; margin:0 0 8px; }
.mrow a{
  display:inline-flex; align-items:center; gap:6px;
  padding:5px 11px; border-radius:8px; font-size:0.8rem; font-weight:700;
  border:1px solid #dbe3ef; background:#fff; color:#475569 !important;
  text-decoration:none !important; white-space:nowrap;
}
.mrow a:hover{ background:#eef4ff; border-color:#bfd3ff; }
.mrow a.on{ background:#0f2460; border-color:#0f2460; color:#fff !important; }
.mrow a .n{ font-size:0.7rem; opacity:.75; font-variant-numeric:tabular-nums; }
.mrow a.on .n{ opacity:.9; }
.mrow a .bad{ color:#fca5a5; font-weight:800; }
.mrow a.on .bad{ color:#fecaca; }

/* 表身自己捲、表頭釘住 —— 捲到第 300 列還看得到欄位名稱 */
.wallwrap{ height:calc(100vh - 232px); min-height:340px; overflow:auto;
  border:1px solid #e6ebf3; border-radius:10px; background:#fff; }
.wallwrap .ftw{ overflow:visible; }
.capline{ font-size:0.75rem; color:#64748b; margin:0 0 6px; }
.capline b{ font-variant-numeric:tabular-nums; }
</style>
""", unsafe_allow_html=True)


# ─── 資料：跟一般版共用同一份快取（見 utils/full_process_ui.load_data）──────
load_data = ui.load_data
_FPD_MTIME = ui.data_mtime()

# ─── query param 就是這一頁的全部狀態（沒有側邊選單可以放東西）───────────────
qp = st.query_params
_year = int(qp.get("y") or TODAY.year)
_mode = str(qp.get("v") or "全部")
_kw = str(qp.get("q") or "")
_sort = str(qp.get("sort") or "出貨日")
if _sort not in ui.SORT_FIELDS:
    _sort = "出貨日"
_desc = str(qp.get("desc") or "0") == "1"
_sel_wo = str(qp.get("wo") or "").strip()

df = load_data(_year, fpd.DATA_VERSION, _FPD_MTIME)
if df.empty:
    st.error("讀不到資料。請確認 NAS 路徑可連線。", icon="🚫")
    st.stop()

_NEED = ["鏈·根工單", "鏈·層深", "鏈·結論", "鏈·卡點", "月份·歸屬", "治具·到廠",
         "工單·子單號", "工單·子單明細",
         "工單·開單狀態", "排程·回廠日", "排程·推算完工"]
_miss = [c for c in _NEED if c not in df.columns]
if _miss:
    if not st.session_state.get("_wall_reloaded"):
        st.session_state["_wall_reloaded"] = True
        st.cache_data.clear()
        st.rerun()
    st.error("資料結構與頁面不符，缺少欄位：{}".format("、".join(_miss[:6])), icon="🚫")
    st.stop()
st.session_state["_wall_reloaded"] = False

df["_start"] = df["工單·開工日"]

# ─── 篩選（跟一般版同一套口徑）───────────────────────────────────────────────
view = df.copy()
# 殭屍工單：交期在本年度、開工日卻停在前年以前（ERP 沒結案也沒更新排程）
view = view[[not (bool(s) and s < date(_year - 1, 1, 1)) for s in view["工單·開工日"]]]
# 完工日早於本月 1 日的拉掉；沒有完工日的（還沒發單）留著
_floor = date(TODAY.year, TODAY.month, 1)
view = view[[(f is None) or (f >= _floor) for f in view["工單·完工日"]]]

if _mode == "只看趕不上的":
    pick = view["鏈·結論"].astype(str).str.startswith("❌")
elif _mode == "只看卡料的":
    pick = view["料況·缺料件數"] > 0
elif _mode == "只看沒開工單的":
    pick = view["工單·開單狀態"] == "未開立"
else:
    pick = pd.Series(True, index=view.index)
if _kw.strip():
    pick = pick & ui.fuzzy_mask(view, _kw)
# 命中一張就把整個母子家族帶出來
view = view[pick | view["鏈·根工單"].isin(set(view.loc[pick, "鏈·根工單"]))]

if view.empty:
    st.warning("目前條件下沒有資料。", icon="🔍")
    st.stop()

# 產能負載：加工廠 × 歸屬月份。用整份資料算，不跟著畫面篩選變 ——
# 產線的負荷是實體的，畫面上篩掉幾張工單不會讓產能空出來。
# 逐張的累計（依產銷出貨日排隊）在資料層算好了，見 fpd.capacity_queue。
FAC_LOAD = df.groupby(["工單·加工廠", "月份·歸屬"])["產能·計入量"].sum().to_dict()
PRESENT_WO = set(view["工單·工單號"])

# 不用生產（產銷回覆庫存／外購，而且沒開工單）整包不進主表 —— 這裡只看要生產的
_noprod = (~view["訂單·需生產"]) & (view["工單·工單號"] == "")
np_view = view[_noprod]
prod = view[~_noprod]

_months = sorted({m for m in prod["月份·歸屬"] if m})
_cur = "{:04d}-{:02d}".format(TODAY.year, TODAY.month)
_m = str(qp.get("m") or "")
if _m not in _months:
    _m = _cur if _cur in _months else (_months[0] if _months else "")
g_all = prod[prod["月份·歸屬"] == _m] if _m else prod.iloc[0:0]


def qs(**kw) -> str:
    """組 query string：沿用目前的狀態，只改指定的幾個。"""
    cur = {"y": _year, "v": _mode, "q": _kw, "m": _m, "sort": _sort,
           "desc": "1" if _desc else "0"}
    cur.update(kw)
    parts = ["{}={}".format(k, quote(str(v))) for k, v in cur.items() if str(v) != ""]
    return "?" + "&".join(parts)


# ─── 頂端列：標題 + KPI ──────────────────────────────────────────────────────
_late = int(g_all["鏈·結論"].astype(str).str.startswith("❌").sum())
_ok = int(g_all["鏈·結論"].astype(str).str.startswith("✅").sum())
_noopen = int((g_all["工單·開單狀態"] == "未開立").sum())
_short = int((g_all["料況·缺料件數"] > 0).sum())
_push = int(g_all["鏈·採購動作"].astype(str).str.startswith("🔺").sum())
_kid = int(g_all["鏈·層深"].sum())

st.markdown(
    '<div class="wallbar">'
    '<div><div class="ttl">⚙️ 全製程 · {m}</div>'
    '<div class="sub">一張工單一列　·　母單在上、板階子單縮排在下　·　天數皆為工作天'
    '　·　資料 v{v}</div></div>'
    '<a class="back" href="/full_process" target="_self">☰ 回一般版</a>'
    '<div class="kpi">'
    '<div><b>{n:,}</b><span>本月列數（子 {k}）</span></div>'
    '<div><b>{q:,}</b><span>數量</span></div>'
    '<div><b style="color:#fca5a5">{late:,}</b><span>❌ 趕不上</span></div>'
    '<div><b style="color:#a7f3d0">{ok:,}</b><span>✅ 來得及</span></div>'
    '<div><b style="color:#fecaca">{no:,}</b><span>未開工單</span></div>'
    '<div><b style="color:#fde68a">{sh:,}</b><span>缺料</span></div>'
    '<div><b style="color:#fca5a5">{pu:,}</b><span>🔺 催採購</span></div>'
    '</div></div>'.format(
        m=_m or "（無資料）", v=fpd.DATA_VERSION, n=len(g_all), k=_kid,
        q=int(g_all["訂單·數量"].sum()), late=_late, ok=_ok, no=_noopen,
        sh=_short, pu=_push),
    unsafe_allow_html=True)

# ─── 月份切換（走 ?m=，點表頭排序時月份不會跳掉）────────────────────────────
_mrow = []
for m in _months:
    sub = prod[prod["月份·歸屬"] == m]
    bad = int(sub["鏈·結論"].astype(str).str.startswith("❌").sum())
    _mrow.append(
        '<a class="{on}" href="{href}" target="_self" title="{tip}">{m}'
        '<span class="n">{n}</span>{badhtml}</a>'.format(
            on="on" if m == _m else "", href=qs(m=m, wo=""), m=m, n=len(sub),
            tip="{} 共 {} 列，趕不上 {} 列".format(m, len(sub), bad),
            badhtml='<span class="bad">✗{}</span>'.format(bad) if bad else ""))
st.markdown('<div class="mrow">' + "".join(_mrow) + "</div>", unsafe_allow_html=True)

# ─── 控制列 ──────────────────────────────────────────────────────────────────
c1, c2, c3, c4, c5 = st.columns([0.9, 2.6, 2.6, 1.0, 1.0])
_y2 = c1.selectbox("年度", [TODAY.year, TODAY.year - 1, TODAY.year + 1],
                   index=[TODAY.year, TODAY.year - 1, TODAY.year + 1].index(_year),
                   label_visibility="collapsed")
_opts = ["全部", "只看趕不上的", "只看卡料的", "只看沒開工單的"]
_v2 = c2.radio("看什麼", _opts, index=_opts.index(_mode) if _mode in _opts else 0,
               horizontal=True, label_visibility="collapsed")
_q2 = c3.text_input("關鍵字", _kw, placeholder="關鍵字：料號／工單／客戶",
                    label_visibility="collapsed")
if c4.button("🔄 重新讀取", use_container_width=True):
    st.cache_data.clear()
    st.rerun()
if _y2 != _year or _v2 != _mode or _q2 != _kw:
    st.query_params.update({"y": str(_y2), "v": _v2, "q": _q2, "m": _m,
                            "sort": _sort, "desc": "1" if _desc else "0"})
    st.rerun()

_buf = io.BytesIO()
prod.drop(columns=["_start", "_cap_qty", "_s", "料況·缺料項目"],
          errors="ignore").to_excel(_buf, index=False, engine="openpyxl")
_buf.seek(0)
c5.download_button("⬇ Excel", data=_buf, use_container_width=True,
                   file_name="全製程_{:%Y%m%d}.xlsx".format(TODAY),
                   mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ─── 本月各廠產能 ────────────────────────────────────────────────────────────
_cap = []
for fac in ["廠內", "國智", "唐佑", "其他"]:
    q = int(FAC_LOAD.get((fac, _m), 0))
    if not q:
        continue
    cap = CAPACITY[fac]
    mark = "🔴" if q > cap else "🟡" if q >= cap * CAP_WARN else "🟢"
    _cap.append("{} {} <b>{:,}</b>/{:,}".format(mark, fac, q, cap))
if _cap:
    st.markdown('<div class="capline">本月基本產能　' + "　·　".join(_cap)
                + '　｜　另有不用生產 {} 筆（庫存／外購，不佔產能）</div>'.format(len(np_view)),
                unsafe_allow_html=True)

# ─── 缺料明細（點表格裡的缺料格帶 ?wo= 進來）─────────────────────────────────
if _sel_wo:
    sub = view[view["工單·工單號"] == _sel_wo]
    if not len(sub):
        sub = df[df["工單·工單號"] == _sel_wo]
    with st.expander("🔎 缺料明細 ｜ {}".format(_sel_wo), expanded=True):
        if not len(sub):
            st.info("這張工單不在目前的年度／篩選範圍內。", icon="🔍")
        else:
            r = sub.iloc[0]
            st.caption("{}　·　{}　·　開工 {}　·　齊料 {}　·　回廠 {}　·　完工 {}　·　{}"
                       .format(r["訂單·料號"], r["工單·加工廠"], ui.md(r["_start"]),
                               ui.md(r["料況·最終齊料日"]), ui.md(r["排程·回廠日"]),
                               ui.md(r["排程·推算完工"]), r["料況·齊套狀態"]))
            items = r["料況·缺料項目"] or []
            if not items:
                st.success("這張工單目前沒有缺料。", icon="✅")
            else:
                st.dataframe(pd.DataFrame([{
                    "品號": x["品號"], "品名": str(x.get("品名") or "")[:26],
                    "庫別": "{} {}".format(x.get("庫別") or "",
                                          x.get("庫別名稱") or "").strip(),
                    "需求量": int(x["需求量"]), "配到": int(x.get("配到", 0)),
                    "缺量": int(x.get("缺量", 0)),
                    "前面工單先佔": int(x.get("先前佔用", 0)),
                    "全倉庫存": int(x.get("全倉", 0) or 0),
                    "預計進貨日": x.get("進貨日"),
                    "進貨量": (int(x["進貨量"]) if x.get("進貨量") else None),
                    "進貨廠商": x.get("進貨廠商") or "",
                    "需求日": x.get("需求日"),
                } for x in items]), hide_index=True, use_container_width=True)
                st.caption("「配到」是依開工日排隊後這張工單實際分到的量；"
                           "「前面工單先佔」是同一個倉、開工日更早的工單已經吃掉的量。"
                           "　·　{}".format(r["鏈·採購動作"]))
        st.markdown('<a href="{}" target="_self">✕ 關閉明細</a>'.format(qs(wo="")),
                    unsafe_allow_html=True)

# ─── 主表：表頭釘住、表身自己捲 ──────────────────────────────────────────────
st.markdown(ui.TABLE_CSS, unsafe_allow_html=True)
_defects = []
if len(g_all):
    g = ui.family_sorted(g_all, ui.SORT_FIELDS[_sort], _desc)
    # base 讓表頭排序與缺料連結都把年度／月份／關鍵字帶回去，不然一點就跳回預設
    # base 讓表頭排序與缺料連結都把年度／月份／關鍵字帶回去，
    # 不然點一下排序就跳回預設的月份。sort/desc 由 ui.head() 自己接上。
    _base = "&".join(
        "{}={}".format(k, quote(str(v)))
        for k, v in (("y", _year), ("v", _mode), ("q", _kw), ("m", _m))
        if str(v) != "")
    _base = (_base + "&") if _base else ""
    st.markdown('<div class="wallwrap">'
                + ui.table_html(g, _sort, _desc, PRESENT_WO,
                                _defects, limit=PER_MONTH, base=_base)
                + "</div>", unsafe_allow_html=True)
    if len(g) > PER_MONTH:
        st.caption("本月僅列前 {} 列（共 {:,} 列）。用上面的「看什麼」或關鍵字縮小範圍。"
                   .format(PER_MONTH, len(g)))
    st.markdown(ui.legend_html("　點欄位名稱可排序　·　點缺料格看明細"),
                unsafe_allow_html=True)
else:
    st.info("這個月沒有要生產的工單。", icon="🔍")

if _defects:
    st.error("表格渲染異常：{} 列的欄數不對（{}）。請回報，不要拿這張表做判斷。"
             .format(len(_defects), _defects[:5]), icon="⚠")
