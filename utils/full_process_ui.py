# -*- coding: utf-8 -*-
"""全製程的畫面元件：燈號判定與 HTML 表格。

兩個頁面共用 —— pages/29_full_process.py（一般版，有側邊主題選單）與
pages/30_full_process_wall.py（全螢幕版，沒有選單）。規則只寫一份，
不然改了口徑只改到一邊，兩頁的數字會互相打架。

狀態一律用參數傳（fac_load / present_wo / defects），不放模組層變數：
Streamlit 每個 session 各跑一次腳本，模組卻是跨 session 共用的，
放在模組層會被別人的 session 汙染。

資料口徑見 utils/full_process_data.py 檔頭。
"""
import hashlib
import os
import html
import re
import sys
from datetime import date, datetime
from difflib import SequenceMatcher
from urllib.parse import quote

import pandas as pd
import streamlit as st

from utils.workdays import add_workdays, net_workdays
from utils import full_process_data as fpd

TODAY = date.today()

CAP_WARN = 0.85      # 用量到上限的 85% 就轉黃
WO_DAYS = 2          # 訂單開立後幾個工作天內要把工單開出來
RED_WD = 10          # 距開工日 <=10 工作天還沒備完＝紅
YEL_WD = 12          # <=12 工作天＝黃

LIGHT = {            # state -> (文字色, 底色, 框色)
    "pass": ("#1d4ed8", "#eff6ff", "#bfdbfe"),
    "run":  ("#15803d", "#f0fdf4", "#bbf7d0"),
    "warn": ("#a16207", "#fefce8", "#fde68a"),
    "late": ("#b91c1c", "#fef2f2", "#fecaca"),
    "unk":  ("#64748b", "#f8fafc", "#e2e8f0"),
    "na":   ("#cbd5e1", "#ffffff", "#f1f5f9"),
}
LIGHT_LABELS = [("pass", "PASS"), ("run", "進行中"), ("warn", "快到期"),
                ("late", "未完成"), ("unk", "不適用／未知")]


def norm_date(v):
    if v is None or v is pd.NaT:
        return None
    if isinstance(v, float) and pd.isna(v):
        return None
    if isinstance(v, pd.Timestamp):
        return v.date()
    if isinstance(v, datetime):
        return v.date()
    return v


def wd(a, b) -> int:
    return net_workdays(a, b)


def md(d) -> str:
    """同年只顯示 月/日；跨年一定帶年份，否則 2020-03-10 會被看成今年的 03/10。"""
    d = norm_date(d)
    if not d:
        return "—"
    return "{:%m/%d}".format(d) if d.year == TODAY.year else "{:%y/%m/%d}".format(d)


def days(n: int) -> str:
    """把工作天數寫成人看得懂的字：負數是已經過了那個日子。"""
    return "剩{}天".format(n) if n >= 0 else "逾{}天".format(-n)


# 正規化時要保留的字元：英數 ＋ 中日韓文字與假名。
# 只留英數是錯的：客戶名有「億光電子」這種純中文，正規化後會變成空字串，
# 搜尋條件等於不存在，fuzzy_mask 直接回全部命中 —— 使用者打了關鍵字，
# 畫面卻把別的客戶全列出來，看起來像篩選壞掉。
_KEEP = re.compile(r"[^0-9A-Z\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


def norm_key(v) -> str:
    """比對用的正規化字串：去掉 -、#、_、空白等雜訊，英文轉大寫。
    中文字要留著（見 _KEEP 說明）。這樣打 igps9822 能命中
    9-00-IGPS9822DGP+##############-00_XXB11，打「億光電子」也命中得到。"""
    return _KEEP.sub("", str(v).upper())


def _near(hay: str, needle: str, cutoff: float = 0.82) -> bool:
    """在 hay 裡滑動比對，容許一兩個字元差異。
    資料裡客戶名有 Weidmuller 和 Weidmueller 兩種拼法，嚴格比對只會中一半。"""
    n = len(needle)
    if n < 4 or not hay:
        return False
    for i in range(0, max(len(hay) - n + 2, 1)):
        if SequenceMatcher(None, hay[i:i + n + 1], needle).ratio() >= cutoff:
            return True
    return False


def fuzzy_mask(frame, query: str):
    """模糊搜尋：可搜欄位併成一串正規化文字，查詢字拆 token 後全部要命中
    （不管順序）。料號中間的 - 和 # 不用打，大小寫也不管；某個 token 完全
    命中不到時才退回單字元容錯比對（較慢，所以只在必要時跑）。"""
    raw = str(query or "").strip()
    toks = [norm_key(t) for t in query.split() if norm_key(t)]
    if not toks:
        # 使用者明明打了字，卻正規化成空的（例如整串都是標點）——
        # 這時回全部命中等於把篩選條件吃掉，畫面看起來像沒篩。
        # 退回原字串直接比對，寧可找不到也不要假裝全部都符合。
        if raw:
            up = raw.upper()
            return (frame["訂單·料號"].astype(str) + "" + frame["訂單·品名"].astype(str)
                    + "" + frame["工單·工單號"].astype(str)
                    + "" + frame["訂單·客戶"].astype(str)
                    + "" + frame["訂單·訂單單號"].astype(str)
                    ).str.upper().str.contains(up, regex=False)
        return pd.Series(True, index=frame.index)
    blob = (frame["訂單·料號"].astype(str) + "" + frame["訂單·品名"].astype(str)
            + "" + frame["工單·工單號"].astype(str)
            + "" + frame["工單·母工單"].astype(str)
            + "" + frame["訂單·客戶"].astype(str)
            + "" + frame["訂單·訂單單號"].astype(str)).map(norm_key)
    mask = pd.Series(True, index=frame.index)
    for t in toks:
        m = blob.str.contains(t, regex=False)
        if not m.any():
            m = blob.map(lambda x, _t=t: _near(x, _t))
        mask &= m
    return mask


def pn_html(pn) -> str:
    """料號完整顯示，ERP 用來補齊的 # 調淡，讓眼睛聚焦在有意義的字元。

    絕對不可截斷：實測 74% 的料號長度是 40 字，尾端的 -00_XXB21 / -00_EUB20 /
    -00_USB10 是版本與地區別。截掉尾碼會讓兩個不同產品在畫面上長得一模一樣。
    """
    return "".join(
        ('<span class="pad">{}</span>'.format(esc(seg)) if seg.startswith("#") else esc(seg))
        for seg in re.findall(r"#+|[^#]+", str(pn or ""))
    )


TIP_LINES = 8          # tooltip 最多幾行
TIP_CHARS = 700        # tooltip 最多幾個字
NL = chr(10)


def tip(text: str, more: str = "點缺料格看完整明細") -> str:
    """把 tooltip 限長。

    踩過的坑：某張工單缺 43 項，整串塞進 title 屬性讓那一列變成 5,687 字元，
    渲染時該列會少掉一格（而且是靜默的，畫面看起來只是欄位對不齊）。
    完整內容本來就該看明細分頁，tooltip 只留前幾行。
    """
    s = str(text or "")
    lines = s.split(NL)
    if len(lines) > TIP_LINES or len(s) > TIP_CHARS:
        s = NL.join(lines[:TIP_LINES])[:TIP_CHARS].rstrip() + NL + "…（{}）".format(more)
    return s


def esc(v) -> str:
    """所有進到 HTML 的字串都要跳脫，而且換行一定要換成 &#10;。

    兩個踩過的坑：
      1. 品名／備註裡有雙引號，直接塞進 title="…" 會把屬性提早關掉，
         整列儲存格結構就壞了。
      2. st.markdown(unsafe_allow_html=True) 會先跑 markdown，字串裡的空行
         會被當成區塊結束，把 <td> 從中間切開 —— 該欄會整個消失。
         用 &#10; 換行，tooltip 一樣會斷行。
    """
    s = html.escape("" if v is None else str(v), quote=True)
    return (s.replace(chr(13) + chr(10), "&#10;")
             .replace(chr(10), "&#10;").replace(chr(13), "&#10;"))


# ─── 每一站的燈號（顏色直接上在該欄，不另外拉一列）───────────────────────────
def light_wo(r):
    """① 工單開了沒；沒開是不用開還是忘了開。"""
    stt = str(r["工單·開單狀態"])
    if stt == "已開立":
        return "pass", "已開立", "工單 " + str(r["工單·工單號"])
    if stt.startswith("不用開"):
        return "unk", stt, "產銷回覆「{}」，不用開工單".format(
            r["訂單·產銷回覆"] or r["訂單·出貨判定"])
    # 忘了開：訂單開立後 WO_DAYS 個工作天內要開出來
    deadline = add_workdays(norm_date(r["訂單·訂單日"]), WO_DAYS)
    remain = wd(TODAY, deadline) if deadline else None
    if remain is None:
        return "late", "未開立", "沒有訂單日，無法算應開單期限"
    why = "訂單開立後 {} 個工作天內要開出工單（{}）".format(WO_DAYS, days(remain))
    return ("late" if remain < 0 else "warn" if remain <= 1 else "run"), \
           "未開立 " + days(remain), why


def light_mat(r, start):
    """③ 料況：缺什麼料、有沒有庫存、什麼時候進貨。"""
    short = int(r["料況·缺料件數"] or 0)
    fit = str(r["料況·齊套狀態"])
    if fit.startswith("➖"):
        return "unk", "未開單", "工單還沒開，供需表無從查起，料況未知"
    if short == 0:
        return "pass", fit.replace("✅ ", ""), "{}　齊料日 {}（{}）".format(
            fit, md(r["料況·最終齊料日"]), r["料況·齊料來源"])
    n = wd(TODAY, start) if start else 999
    state = "late" if n <= RED_WD else "warn" if n <= YEL_WD else "run"
    last = norm_date(r["料況·預計進貨日"])       # 最晚一筆進貨＝真正齊料的時間點
    lbl = "缺{}項".format(short)
    long = "缺 {} 項，距開工日 {} 個工作天".format(short, n)
    if last:
        lbl += " 進貨" + md(last)
        long += "；最晚一筆進貨 {}（最早 {}）".format(md(last), md(r["料況·最近進貨日"]))
        if start and last > start:
            state = "late"
    elif str(r["料況·缺料庫存"]).startswith("缺料·全倉無貨"):
        lbl += " 無進貨排程"
        long += "；全倉無貨且查無進貨排程"
        state = "late"
    else:
        lbl += " 可調撥"
    long += NL + str(r["料況·缺料庫存"])
    if str(r["料況·缺料明細"] or ""):
        long += NL + NL + "缺什麼料：" + NL + str(r["料況·缺料明細"])
    return state, lbl, long


def light_jig(r, start):
    """④ 鋼板／載具到該做的那一家了沒。成品階與外購品不需要。"""
    at = str(r["治具·到廠"] or "")
    if at.startswith("➖") or r["訂單·外購品"]:
        return "unk", "不需", "成品階／外購品不需要鋼板與載具"
    detail = str(r["治具·明細"] or "")
    if at.startswith("✅"):
        return "pass", at.replace("✅ ", ""), at + "　｜　" + detail
    if at.startswith("❌"):
        n = wd(TODAY, start) if start else 999
        state = "late" if n <= RED_WD else "warn" if n <= YEL_WD else "run"
        return state, at.replace("❌ ", ""), "{}，距開工日 {} 個工作天　｜　{}".format(
            at, n, detail)
    return "unk", at or "無資料", (at + "　｜　" + detail) if detail else "PE 治工具表查無此機種"


def light_cap(r):
    """⑤ 產能：依產銷出貨日排隊累加到這一張為止，吃掉多少、超了沒。

    數字是資料層算好的（見 fpd.capacity_queue）：同一個廠、同一個月，
    出貨日早的先吃，所以每一列看到的是「排到我這張為止的累計」，
    不是整個月的總和 —— 排在前面吃得下的照樣是藍的，只有排到超過上限的才紅。
    """
    if r["產能·已完工"]:
        return "pass", "已完工", "寶橋廠排程已標記完工／取消，不佔產能"
    cap = int(r["產能·月上限"] or 0)
    used = int(r["產能·累計"] or 0)
    ratio = used / cap if cap else 0
    long = NL.join([
        "{} {}　依產銷出貨日排隊，這張排第 {} 位".format(
            r["工單·加工廠"], r["月份·歸屬"] or "—", int(r["產能·排隊序"] or 0)),
        "本張投產 {:,}　排到這裡累計 {:,} ／ 月上限 {:,}（{:.0%}）".format(
            int(r["產能·計入量"] or 0), used, cap, ratio),
    ])
    if used > cap:
        long += NL + "已經排不下了：超出 {:,}，要嘛往後月挪、要嘛拉去別的廠".format(used - cap)
        return "late", "超 {:,}".format(used - cap), long
    if ratio >= CAP_WARN:
        long += NL + "還剩 {:,} 的空間".format(cap - used)
        return "warn", "{:.0%}".format(ratio), long
    return "pass", "{:.0%}".format(ratio), long


def light_chain(r):
    """③ 整條鏈趕不趕得上產銷出貨日。"""
    con = str(r["鏈·結論"])
    gap = r["鏈·寬裕工作天"]
    if con.startswith("✅"):
        return "pass", ("來得及 剩{}天".format(int(gap)) if gap is not None else "來得及")
    if con.startswith("❌"):
        return "late", ("來不及 晚{}天".format(int(-gap)) if gap is not None else "來不及")
    if con == "❔ 未開單":
        return "late", "工單未開"
    return "unk", con.replace("➖ ", "").replace("❔ ", "")


def light_stock(r):
    """缺的料在全倉有沒有貨、要不要催採購。"""
    n_short = int(r["料況·缺料件數"] or 0)
    stockv = str(r["料況·缺料庫存"])
    buy = str(r["鏈·採購動作"] or "—")
    if str(r["料況·齊套狀態"]).startswith("➖"):
        state, lbl = "unk", "未開單"
    elif n_short == 0:
        state, lbl = "pass", stockv
    elif stockv.startswith("缺料·全倉有貨"):
        state, lbl = "warn", "全倉有貨·待調撥"
    else:
        state, lbl = "late", "全倉無貨"
    if buy.startswith("🔺"):
        state = "late"
        lbl += " 🔺催採購"
    return state, lbl, stockv + NL + buy


# ─── 表格 ────────────────────────────────────────────────────────────────────
# 排序：家族綁在一起，所以主鍵是家族的代表值，家族內再母→子。
SORT_FIELDS = {
    "出貨日": "鏈·目標出貨日", "齊料日": "料況·最終齊料日", "鏈完工": "鏈·預計完工",
    "寬裕天數": "鏈·寬裕工作天", "交期": "訂單·交期", "開工": "_start",
    "數量": "訂單·數量", "工單號": "工單·工單號", "料號": "訂單·料號",
    "客戶": "訂單·客戶", "缺料件數": "料況·缺料件數", "加工廠": "工單·加工廠",
}
HEAD_COLS = [
    ("生產地", "加工廠", ""),
    ("工單（母／子）", "工單號", ""),
    ("料號 · 客戶", "料號", ""),
    ("數量", "數量", " class='r'"),
    ("產銷出貨日", "出貨日", ""),
    ("齊料日", "齊料日", ""),
    ("卡在哪", "", ""),
    ("缺什麼料", "缺料件數", ""),
    ("庫存 / 進貨", "", ""),
    ("治具到廠", "", ""),
    ("產能", "", ""),
]
NCOL = len(HEAD_COLS)

TABLE_CSS = """
<style>
.ftw{overflow-x:auto;}
.ft{border-collapse:collapse;width:100%;font-size:0.78rem;}
.ft th{background:#f8fafc;color:#64748b;font-weight:700;font-size:0.71rem;
       letter-spacing:.05em;padding:7px 9px;text-align:left;white-space:nowrap;
       border-bottom:1px solid #e2e8f0;position:sticky;top:0;z-index:2;}
.ft td{padding:6px 9px;border-bottom:1px solid #f1f5f9;color:#334155;
       white-space:nowrap;vertical-align:middle;}
.ft tr:hover td{background:#fbfdff;}
.ft tr.kidrow td{background:#fcfcfe;}
.ft tr.kidrow:hover td{background:#f6f8ff;}
.ft .wo{font-weight:700;color:#0f2460;font-variant-numeric:tabular-nums;}
.ft .kid{color:#5b6b85;font-weight:600;font-variant-numeric:tabular-nums;}
.ft .none{color:#b91c1c;font-weight:800;}
.ft .tag{display:inline-block;font-size:0.63rem;font-weight:700;border-radius:4px;
         padding:0 5px;margin-left:5px;vertical-align:1px;}
.ft .t-mu{background:#ede9fe;color:#6d28d9;}
.ft .t-zi{background:#eef2f7;color:#64748b;}
.ft .t-no{background:#fee2e2;color:#b91c1c;}
.ft .t-sk{background:#f1f5f9;color:#94a3b8;}
.ft .pn{color:#475569;}
.ft .pad{color:#d3dbe6;}
.ft .cu{color:#94a3b8;font-size:0.72rem;}
.ft .r{text-align:right;font-variant-numeric:tabular-nums;}
.ft .st{font-weight:600;font-size:0.74rem;border-left:2px solid transparent;}
.ft .dt{font-variant-numeric:tabular-nums;}
.ft a.drill{color:inherit!important;text-decoration:underline dotted!important;cursor:pointer;}
.ft a.sorth{color:inherit!important;text-decoration:none!important;cursor:pointer;display:block;}
.ft th:hover{background:#eef2f8;}
.ft a.drill:hover{text-decoration:underline solid!important;}
</style>
"""


def legend_html(extra: str = "") -> str:
    body = "".join(
        '<span style="display:inline-flex;align-items:center;gap:5px;margin-right:14px;">'
        '<i style="width:11px;height:11px;border-radius:3px;background:{bg};'
        'border:1px solid {bd};display:inline-block;"></i>'
        '<span style="font-size:0.75rem;color:#64748b;">{t}</span></span>'
        .format(bg=LIGHT[k][1], bd=LIGHT[k][2], t=v) for k, v in LIGHT_LABELS)
    return ('<div style="margin:0 0 8px;font-size:0.75rem;color:#94a3b8;">'
            + body + extra + "</div>")


def head(active: str, desc: bool, base: str = "") -> str:
    """表頭。每一欄都是連結，點下去用 ?sort= 換排序欄位；再點同一欄切換升／降。
    Streamlit 會濾掉 <script>，所以只能走 query param。
    base 是要一起帶回去的其他 query string（例如全螢幕版的月份）。"""
    arrow = " ↓" if desc else " ↑"

    def th(label, key, cls=""):
        if not key:
            return "<th{}>{}</th>".format(cls, label)
        on = (key == active)
        nxt = "1" if (on and not desc) else "0"      # 點目前這欄 → 換方向
        href = "?{}sort={}&desc={}".format(base, quote(key), nxt)
        style = " style='color:#6d28d9'" if on else ""
        return ("<th{}{}><a class='sorth' href='{}' target='_self' title='依「{}」排序'>"
                "{}{}</a></th>").format(cls, style, href, label,
                                        label, arrow if on else "")

    return "<thead><tr>" + "".join(th(a, b, c) for a, b, c in HEAD_COLS) + "</tr></thead>"


def cell(state, body, long, extra=""):
    fg, bg, bd = LIGHT[state]
    return ('<td class="st" style="color:{};background:{};border-left-color:{};{}" '
            'title="{}">{}</td>').format(fg, bg, bd, extra, esc(tip(long)), body)


def wo_cell(r, present_wo):
    """工單欄：母單在上、子單縮排；沒開單的直接標紅並說明為什麼。"""
    no = str(r["工單·工單號"] or "").strip()
    tier = str(r["工單·階層"] or "")
    stt = str(r["工單·開單狀態"])
    if not no:
        if stt.startswith("不用開"):
            return ('<span class="wo" style="color:#94a3b8">—</span>'
                    '<span class="tag t-sk" title="{}">{}</span>').format(
                        esc("產銷回覆：{}".format(r["訂單·產銷回覆"] or r["訂單·出貨判定"])),
                        esc(stt.replace("不用開", "不用開單")))
        return ('<span class="none">未開立</span>'
                '<span class="tag t-no" title="{}">忘了開？</span>').format(
                    esc("訂單 {} 已開立 {}，ERP 查不到對應工單".format(
                        r["訂單·訂單單號"], md(r["訂單·訂單日"]))))
    if tier.startswith("子"):
        mu = str(r["工單·母工單"] or "")
        t = "板階子單　母單（成品階）{} {}　母單狀態 {}".format(
            mu, r["工單·母工單品號"], r["工單·母工單狀態"] or "—")
        out = ('<span class="kid" title="{}">└ {}</span>'
               '<span class="tag t-zi" title="{}">子·板階</span>').format(
                   esc(t), esc(no), esc(t))
        if mu and mu not in present_wo:
            out += '<span class="tag t-sk" title="{}">母單 {}</span>'.format(
                esc(t), esc(r["工單·母工單狀態"] or "不在範圍"))
        return out
    if tier.startswith("母") or int(r["工單·子單數"] or 0) > 0:
        # 徽章要寫「畫面上真的看得到幾張 / ERP 裡總共幾張」。
        # 只寫總數的話會出現「母·成品 6子」底下卻只有 5 列的狀況 ——
        # 差的那張多半是指定完工／已結案，依規則不列出來，但要說得出來去哪了。
        all_k = [x for x in str(r["工單·子單號"] or "").split(",") if x]
        seen = [x for x in all_k if x in present_wo]
        total = len(all_k) or int(r["工單·子單數"] or 0)
        gone = [x for x in all_k if x not in present_wo]
        lbl = "母·成品 {}子".format(total) if len(seen) == total else \
              "母·成品 {}/{}子".format(len(seen), total)
        t = "成品階工單，ERP 裡有 {} 張板階子單".format(total)
        if gone:
            t += NL + "這裡看得到 {} 張；沒列出來的 {} 張：".format(len(seen), len(gone))
            det = {k: s for k, s in (x.rstrip("）").split("（")
                                     for x in str(r["工單·子單明細"] or "").split("，")
                                     if "（" in x)}
            t += NL + NL.join("　{}　{}".format(k, det.get(k, "？")) for k in gone)
            t += NL + "（指定完工／已結案依規則不列入；其餘可能是不在本年度或被條件濾掉）"
        return ('<span class="wo">{}</span>'
                '<span class="tag t-mu" title="{}">{}</span>').format(
                    esc(no), esc(t), esc(lbl))
    return '<span class="wo">{}</span>'.format(esc(no))


def row(r, present_wo, defects=None, drill_base=""):
    """畫一列。一張工單一列；母單在上、板階子單縮排在下。

    present_wo  這次畫面上有哪些工單號（母單不在裡面時，子單要標出來）
    defects     欄數對不上時把工單號附加進去（防呆用，可為 None）
    drill_base  缺料連結要一起帶回去的其他 query string
    """
    no = str(r["工單·工單號"] or "").strip()
    start = norm_date(r["_start"])
    st_mat, lbl_mat, why_mat = light_mat(r, start)
    st_jig, lbl_jig, why_jig = light_jig(r, start)
    st_cap, lbl_cap, why_cap = light_cap(r)
    st_stk, lbl_stk, why_stk = light_stock(r)
    st_ch, lbl_ch = light_chain(r)
    _s_wo, _l_wo, why_wo = light_wo(r)

    fac = str(r["工單·加工廠"] or "—")
    vendor = str(r["工單·廠商原名"] or "").strip()
    fac_tip = fac + (("（{}）".format(vendor)) if vendor and vendor != fac else "")

    # 回廠／完工／鏈完工／趕不趕得上這四項依指示不另外開欄，掛在 tooltip 裡。
    # 資料本身沒有拿掉：明細表與匯出的 Excel 仍然有這幾欄。
    sched_tip = NL.join([
        "{}　{}".format(r["鏈·結論"], lbl_ch),
        "回廠 {}　推算完工 {}".format(md(r["排程·回廠日"]), md(r["排程·推算完工"])),
        "整條鏈完工 {}（{}）".format(md(r["鏈·預計完工"]), r["鏈·完工來源"] or "—"),
        "目標出貨 {}（{}）".format(md(r["鏈·目標出貨日"]), r["鏈·出貨日來源"]),
    ])
    if str(r["鏈·卡料"] or ""):
        sched_tip += NL + "卡料：" + str(r["鏈·卡料"])

    # 出貨日：子單一律跟母單走，但它自己那張訂單的日期不藏起來，寫在 tooltip 裡
    ship_tip = ["出貨日來源：" + str(r["鏈·出貨日來源"]),
                "產銷回覆：" + (r["訂單·產銷回覆"]
                              or "（不在 V2 當月+次兩月裡）")]
    # 只有「這張子單自己也配到一張訂單」時才提自己的日期。
    # 沒配到訂單的工單，訂單·交期欄放的是它的預計完工，不是什麼訂單日期，
    # 拿來說「本單自己那張訂單是…」會是假的。
    if "承母單" in str(r["鏈·出貨日來源"]) and r["訂單·有出貨需求"]:
        own = r["訂單·V2出貨日"] or r["訂單·交期"]
        if own and norm_date(own) != norm_date(r["鏈·目標出貨日"]):
            ship_tip.append("本單自己那張訂單是 {}，依規則改跟母單走".format(md(own)))

    # 缺什麼料：點下去帶 ?wo= 到缺料明細
    n_short = int(r["料況·缺料件數"] or 0)
    if n_short and no:
        mat_body = '<a href="?{}wo={}" target="_self" class="drill">{} 🔎</a>'.format(
            drill_base, esc(no), esc(lbl_mat))
    else:
        mat_body = esc(lbl_mat)

    cells = [
        cell(st_ch, esc(fac),
             NL.join(["生產地：" + fac_tip, why_cap, "工單：" + why_wo, sched_tip]),
             extra="border-left:3px solid {};font-weight:800;".format(LIGHT[st_ch][2])),
        "<td>{}</td>".format(wo_cell(r, present_wo)),
        '<td><span class="pn" title="{}">{}</span><br><span class="cu">{}</span></td>'.format(
            esc("{}　{}".format(r["訂單·料號"], r["訂單·品名"] or "")),
            pn_html(r["訂單·料號"]),
            esc("{}　{}".format("🚚" if r["訂單·有出貨需求"] else "📦", r["訂單·客戶"]))),
        '<td class="r">{:,}</td>'.format(int(r["訂單·數量"])),
        '<td class="dt" title="{}">{}</td>'.format(
            esc(NL.join(ship_tip)), md(r["鏈·目標出貨日"])),
        '<td class="dt" title="{}">{}</td>'.format(
            esc("齊料日來源：{}".format(r["料況·齊料來源"] or "無")),
            md(r["料況·最終齊料日"])),
        cell(st_ch, esc(str(r["鏈·卡點"])), sched_tip),
        cell(st_mat, mat_body, why_mat),
        cell(st_stk, esc(lbl_stk), why_stk),
        cell(st_jig, esc(lbl_jig), why_jig),
        cell(st_cap, esc(lbl_cap), why_cap),
    ]
    # 防呆：欄數對不上就是有格子被吃掉（歷史上發生過兩次，都是靜默的）。
    if len(cells) != NCOL and defects is not None:
        defects.append((no or str(r["訂單·訂單單號"]), len(cells)))
    cls = ' class="kidrow"' if str(r["工單·階層"]).startswith("子") else ""
    # 每一格掛上欄位序號：相鄰兩格的 class 與 style 完全相同時，渲染階段曾經
    # 把其中一格整個吃掉（Python 端明明產了 11 格，DOM 只剩 10 格，而且是靜默的）。
    # 加了 data-c 之後每一格都不一樣，也方便對照是第幾欄出事。
    cells = [c.replace("<td", '<td data-c="{}"'.format(n), 1)
             for n, c in enumerate(cells)]
    return "<tr{}>".format(cls) + "".join(cells) + "</tr>"


def sort_key(v):
    """把各型別轉成可比大小的鍵；空值給極大值排最後（升冪降冪都是）。"""
    v = norm_date(v)
    if v is None or (isinstance(v, float) and pd.isna(v)) or v is pd.NaT:
        return (1, 0.0, "")
    if isinstance(v, date):
        return (0, float(v.toordinal()), "")
    if isinstance(v, (int, float)):
        return (0, float(v), "")
    return (0, 0.0, str(v))


def family_sorted(g, sort_col: str, desc: bool):
    """整個母子家族用同一個鍵排序（取家族內最小值），家族內再母→子。
    不這樣做的話，母單和它的子單會被拆散到表格的不同位置。"""
    fam = {}
    for root, v in zip(g["鏈·根工單"], g[sort_col]):
        k = sort_key(v)
        if root not in fam or k < fam[root]:
            fam[root] = k
    g = g.assign(_s=[(fam.get(root, (1, 0.0, "")), str(root), int(dep), str(no))
                     for root, dep, no in zip(g["鏈·根工單"], g["鏈·層深"],
                                              g["工單·工單號"])])
    return g.sort_values("_s", ascending=not desc)


def table_html(g, sort_name: str, desc: bool, present_wo,
               defects=None, limit=None, base="") -> str:
    """整張表：表頭 + 每一列。base 是要帶回 query string 的其他參數。"""
    rows = g if limit is None else g.head(limit)
    body = "".join(row(r, present_wo, defects, base)
                   for _, r in rows.iterrows())
    return ('<div class="ftw"><table class="ft">' + head(sort_name, desc, base)
            + "<tbody>" + body + "</tbody></table></div>")


# ─── 資料載入：兩個頁面共用同一份快取 ────────────────────────────────────────
# 一般版與全螢幕版各自 @st.cache_data 的話，會各讀一次 NAS、各拿一份快照。
# 來源檔白天有人在改，兩邊的數字就會對不起來（實測差了 1 列、產能差 150 pcs），
# 使用者同時開兩頁會以為系統壞掉。放同一個函式就只會有一份。
@st.cache_data(show_spinner="讀取 NAS 來源檔中…", ttl=600)
def load_data(year: int, _ver: int, _mtime: int) -> pd.DataFrame:
    """_ver 帶 fpd.DATA_VERSION、_mtime 帶資料層檔案時間，
    改欄位結構或口徑時就會自動失效，不會拿到舊結構的快取。"""
    return fpd.build(year=year)


@st.cache_data(show_spinner=False, ttl=600)
def source_status(_ver: int, _mtime: int) -> list:
    """各來源檔實際讀到哪一個檔案、檔案日期，供頁面顯示資料來源狀態。"""
    out = []
    for label, path in fpd.source_files().items():
        if path:
            out.append((label, os.path.basename(path),
                        date.fromtimestamp(os.path.getmtime(path)), True))
        else:
            out.append((label, "找不到檔案", None, False))
    return out


def data_mtime() -> int:
    """資料層＋畫面層檔案的指紋，當 st.cache_data 快取鍵的一部分。

    用內容雜湊而不是 os.path.getmtime：mtime 只有秒級解析度，同一秒內連續
    存兩次檔（例如先改 chain() 的邏輯、再 bump DATA_VERSION）會拿到同一個
    數字。夾在中間的那次 rerun 就會把「舊程式碼算出來的結果」快取在新的
    版本號底下，之後怎麼重新整理都還是舊資料，只能手動按重新讀取 ——
    實測踩過：頁面標示 v24，畫面上卻是 v23 的出貨日。
    """
    h = hashlib.md5()
    for mod in (fpd, sys.modules[__name__]):
        try:
            with open(mod.__file__, "rb") as f:
                h.update(f.read())
        except OSError:      # 檔案剛好在被寫入，這次就跳過
            pass
    return int(h.hexdigest()[:12], 16)
