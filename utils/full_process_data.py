# -*- coding: utf-8 -*-
r"""全製程頁的真實資料載入。

來源資料夾：
    \\192.168.2.34\MO_Storage\ORing MO\ORing-MO 工作\資材部\@新AI介面

    PMC\【1】MOCR10*.xlsx              工單主檔（製令編號、預計開工/完工、加工廠商、狀態碼）
    PMC\【2】mosadexcel.xlsx           產銷統計表 → 訂單（客戶、預交日、未出數、代工廠商）
    PMC\【3.1】供需表(分倉)-*.xlsx      **料況唯一來源**：庫存可用量、預計進貨、預計領用
    PMC\【3.2】*加工廠互調料滙整表-*.xlsm 待備料 → 待調撥
    PMC\【補1】H2O缺料明細*.xls         （依指示暫不帶入，load_eta 保留備用）
    PMC\【補2】W11-缺料表-*.xlsx        （依指示暫不帶入，load_shortage 保留備用）
    PE\生產治工具一覽表*.xlsx           鋼板 / 載具

實測過的關聯鍵（2026-08-21 抽樣）：
  * 料況 → 工單：供需表(分倉)「備註」欄＝製令號，取異動別=預計領用的列。
    8,353 個備註值對得上 1,902 張未完工工單；對不到的工單標「未評估」，
    不可當成齊套。缺料不是直接看 ERP 的「預計結存」，而是自己依開工日
    排隊、逐張扣該倉庫存算出來的（見 allocate()），口徑才跟現場一致。
  * 庫別：庫存列的庫別欄混了代碼(S01/S07/R0x)與名稱(電子倉…)，領用列一律是
    代碼且另有庫別名稱欄。實測領用用到的 13 種代碼在庫存列全都找得到，
    所以配料用庫別代碼當鍵沒問題。
  * W11【至MMDD缺料】只涵蓋報表當下往後兩週（0817 那份是 06/17~08/28），
    拿它判定齊套會把「沒被評估」誤當成「沒缺料」—— 10 月開工的工單全被誤標齊套。
  * 產銷統計表 → MOCR10：MOCR10 的「訂單單號」多半只填在 2022 年以前的舊工單，
    2026 未出訂單只有約 5% 對得上，因此改以「品號」為主要關聯，
    訂單單號兩邊都有值時才優先採用。
  * PE 治工具「板階料號」→ MOCR10「產品品號」：1054 筆中 692 筆直接對上，
    全是 5-70-*（PCBA 階）。9-* 成品工單需經 BOM 才對得到，本版標示為不適用。
"""
import glob
import os
import re
import time
from datetime import date, datetime

import pandas as pd

NAS_BASE = r"\\192.168.2.34\MO_Storage\ORing MO\ORing-MO 工作\資材部\@新AI介面"
BAOQIAO_DIR = (r"\\192.168.2.34\MO_Storage\ORing MO\ORing-MO 工作\生管部"
               r"\09. 廠內改機排程\2026")
# 供需表(分倉) 的正式來源：鼎新每日 AM4:00 抓取，檔名帶日期，取最新一份。
# （原本讀 @新AI介面\PMC\【3.1】那份是人工複製過去的，會落後。）
SUPPLY_DIR = (r"\\192.168.2.34\MO_Storage\ORing MO\ORing-MO 鼎新系統報表"
              r"\LRPMR05庫存供需表(分倉)-每日(AM4-00抓取)(Ian提供)-2020")

# 這幾個單別依指示不列入；5220 是委外重工製令，要保留。
SKIP_MO_PREFIX = ("5130", "5131", "5147", "5210")
# 已結案與「指定完工（不生產）」一律不列入
SKIP_WO_STATUS = ("已完工", "已結案", "指定完工")

CAL = dict(engine="calamine")

# 改動 build()／各 loader 的輸出結構或口徑時，把這個號碼 +1。
# 頁面把它當 st.cache_data 的鍵，才不會拿到舊結構的快取（會 KeyError 或顯示舊數字），
# 而且會顯示在「資料來源」區塊裡，方便確認頁面到底跑到哪一版。
DATA_VERSION = 26

# 加工廠歸戶：ERP 的廠商名稱 → 產能上限的四個桶子
FAC_MAP = {"國智": "國智", "唐佑": "唐佑"}
INHOUSE = {"", "nan", "None", "威力", "威力公司", "廠內"}


def read_excel(path, **kw):
    """讀 NAS 上的 Excel，失敗自動重試。

    SMB 併發讀同一個大檔時會偶發 OSError [Errno 22] / PermissionError，
    直接讓例外往上拋會整頁掛掉並顯示一大串 traceback。重試三次通常就過了；
    真的過不了才拋出，讓頁面顯示可讀的錯誤。
    """
    last = None
    for attempt in range(3):
        try:
            return pd.read_excel(path, **dict(CAL, **kw))
        except (OSError, PermissionError) as e:
            last = e
            time.sleep(0.6 * (attempt + 1))
    raise last


def _pick(subdir: str, pattern: str):
    """取資料夾中符合樣式且最新的檔案；找不到回 None。"""
    hits = [p for p in glob.glob(os.path.join(NAS_BASE, subdir, pattern))
            if not os.path.basename(p).startswith("~$")]
    return max(hits, key=os.path.getmtime) if hits else None


SALES_V2_DIR = (r"\\192.168.2.34\MO_Storage\ORing OPD\Public Folder"
                r"\1、產銷\new\4、產銷統計表")
# 個人副本／檢查用的版本不要當來源
_V2_SKIP = ("-ray", "複製", "檢查", "第二版")


def _pick_sales_v2():
    r"""產銷統計表 V2（月報版）。目錄結構是 <YYYY-MM>\<MMDD>\<檔名>.xlsm。

    一定優先取檔名含「月報」的那份，取不到才退回最新的一般 V2。
    原因：純粹取最新的會抓到下一週的工作底稿，那份的「產銷回覆本周」欄
    還沒填（實測 0824 那份 811 筆只有 57 筆有值，0817 月報版則是全部填好）。
    """
    hits = []
    for p in glob.glob(os.path.join(SALES_V2_DIR, "**", "*產銷統計表 V2*.xlsm"),
                       recursive=True):
        b = os.path.basename(p)
        if b.startswith("~$") or any(k in b.lower() for k in _V2_SKIP):
            continue
        hits.append(p)
    if not hits:
        return None
    monthly = [p for p in hits if "月報" in os.path.basename(p)]
    return max(monthly or hits, key=os.path.getmtime)


def _pick_supply():
    r"""供需表(分倉)：鼎新系統報表資料夾裡檔名帶日期的最新一份。"""
    hits = [q for q in glob.glob(os.path.join(SUPPLY_DIR, "供需表(分倉)-*.xls*"))
            if not os.path.basename(q).startswith("~$")]
    return max(hits, key=os.path.getmtime) if hits else None


def _pick_baoqiao():
    """生管部\\09. 廠內改機排程\\2026 底下最新的『寶橋廠排程*.xlsx』。"""
    hits = [p for p in glob.glob(os.path.join(BAOQIAO_DIR, "寶橋廠排程*.xlsx"))
            if not os.path.basename(p).startswith("~$")]
    return max(hits, key=os.path.getmtime) if hits else None


def source_files() -> dict:
    """回傳各來源檔的實際路徑（找不到為 None），供頁面顯示資料來源狀態。"""
    return {
        "工單 MOCR10":   _pick("PMC", "【1】*.xlsx"),
        "訂單 產銷統計表": _pick("PMC", "【2】*.xlsx"),
        "供需表(分倉)":   _pick_supply(),
        "加工廠互調料":   _pick("PMC", "【3.2】*.xls*"),
        "H2O 缺料明細":   _pick("PMC", "【補1】*.xls*"),
        "W11 缺料表":     _pick("PMC", "【補2】*.xls*"),
        "PE 治工具一覽":  _pick("PE", "*治工具*.xls*"),
        "寶橋廠排程":     _pick_baoqiao(),
        "產銷統計表 V2":  _pick_sales_v2(),
    }


# ─── 欄位轉換小工具 ──────────────────────────────────────────────────────────
def _d(v):
    """把各種日期寫法轉成 datetime.date；轉不動回 None。"""
    if v is None or v is pd.NaT:
        return None
    if isinstance(v, float) and pd.isna(v):
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip()
    if not s or s.lower() in ("nan", "nat", "none"):
        return None
    s = s.split(" ")[0]
    m = re.fullmatch(r"(\d{4})[/\-.]?(\d{1,2})[/\-.]?(\d{1,2})", s)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    try:
        return pd.to_datetime(s).date()
    except Exception:
        return None


def _n(v, default=0):
    x = pd.to_numeric(v, errors="coerce")
    return default if pd.isna(x) else x


def _s(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    return str(v).strip()


_PCBA_KW = ("PCB", "PCBA")
_PACK_KW = ("標籤", "紙箱", "包材", "說明書", "彩盒", "珍珠板", "PE袋", "膠帶")


def _cat_flag(items, kws) -> str:
    """缺料清單裡有沒有這一類的料。用品名關鍵字判，不猜品號前綴。"""
    for it in items:
        name = _s(it.get("品名")).upper()
        if any(k.upper() in name for k in kws):
            return "❌ 缺"
    return "✅ OK"


from datetime import timedelta  # noqa: E402  （排程換算用）

from utils.workdays import add_workdays, net_workdays, next_workday  # noqa: E402

# 使用者定義的排程換算：子工單齊料日 +1 週 = 回廠日，回廠日 +2 週 = 完工日。
# 「週」照字面是日曆週（7 天），但落點碰到假日就往後挪到下一個工作日 ——
# 回廠與完工都要有人上班才算數。
KIT_TO_BACK_DAYS = 7        # 齊料 → 回廠
BACK_TO_DONE_DAYS = 14      # 回廠 → 完工


def derive_schedule(kit_date):
    """由齊料日推回廠日與完工日。回傳 (回廠日, 完工日)；沒有齊料日就都是 None。"""
    if not kit_date:
        return None, None
    back = next_workday(kit_date + timedelta(days=KIT_TO_BACK_DAYS))
    return back, next_workday(back + timedelta(days=BACK_TO_DONE_DAYS))


def _jig_at_site(info: dict, fac: str, vendor: str) -> str:
    """治具在不在該做的那個廠。PE 表的「位置」就是治具目前放在哪一家。"""
    if not info:
        return "無治具資料"
    seen = []
    for k in ("鋼板", "載具"):
        for part in re.split(r"[\s,、／/]+", str(info.get(k + "位置") or "")):
            # 鋼板與載具常放在同一家，不去重會印成「研騰 研騰」
            if part and part not in seen:
                seen.append(part)
    locs = " ".join(seen)
    if not locs:
        return "位置未填"
    want = [x for x in (vendor, fac) if x and x != "其他"]
    if fac == "廠內":
        want += ["威力"]
    for wnt in want:
        if wnt and wnt in locs:
            return "✅ 已到 " + wnt
    return "❌ 未到（現在 {}）".format(locs[:18])


def _fac(vendor: str, plant: str = "") -> str:
    v = _s(vendor)
    if v in FAC_MAP:
        return FAC_MAP[v]
    if v in INHOUSE or not v:
        return "廠內"
    return "其他"


# ─── 各來源讀取 ──────────────────────────────────────────────────────────────
def load_wo():
    r"""MOCR10。回傳 (未完工工單 DataFrame, meta)。

    meta 內含全檔（含已完工）的索引與子母關係，因為子單的母單常常已經完工，
    只看未完工那份會把關係斷掉：
        index    製令號 → {品號, 品名, 狀態}
        child_of 子製令號 → 母製令號
        kids     母製令號 → [子製令號…]

    子母語意（實測 44,146 筆）：母製令號恆有值，等於自己代表獨立單或母單。
    20,611 筆查得到母單品號的子單裡，母=9-* 成品且子=5-70-* 板階佔 14,740 筆（71%），
    母子同品號只有 12%——也就是「母工單＝成品階、子工單＝板階」。
    """
    p = _pick("PMC", "【1】*.xlsx")
    if not p:
        return pd.DataFrame(), {"index": {}, "child_of": {}, "kids": {}}
    mo = read_excel(p, sheet_name=0)

    index, child_of, kids = {}, {}, {}
    for no, pn, nm, stt, mu, st_d in zip(mo["製令編號"].map(_s), mo["產品品號"].map(_s),
                                         mo["品名"].map(_s), mo["狀態碼"].map(_s),
                                         mo["母製令號"].map(_s), mo["預計開工"].map(_d)):
        if not no:
            continue
        index[no] = {"品號": pn, "品名": nm, "狀態": stt, "開工": st_d}
        if mu and mu != no:
            child_of[no] = mu
            kids.setdefault(mu, []).append(no)
    meta = {"index": index, "child_of": child_of, "kids": kids}

    mo = mo[~mo["狀態碼"].astype(str).str.strip().isin(SKIP_WO_STATUS)].copy()
    out = pd.DataFrame({
        "製令編號": mo["製令編號"].map(_s),
        "產品品號": mo["產品品號"].map(_s),
        "品名":     mo["品名"].map(_s),
        "狀態碼":   mo["狀態碼"].map(_s),
        "預計產量": mo["預計產量"].map(lambda v: int(_n(v))),
        "未生產量": mo["未生產量"].map(lambda v: int(_n(v))),
        "開單日期": mo["開單日期"].map(_d),
        "預計開工": mo["預計開工"].map(_d),
        "預計完工": mo["預計完工"].map(_d),
        "訂單單號": mo["訂單單號"].map(_s),
        "母製令號": mo["母製令號"].map(_s),
        "加工廠":   [_fac(v, p2) for v, p2 in zip(mo["廠商名稱"], mo["廠別名稱"])],
        "廠商原名": mo["廠商名稱"].map(_s),
        "急料":     mo["急料"].map(_s),
    })
    out = out[out["製令編號"] != ""]
    out = out[~out["製令編號"].str.startswith(SKIP_MO_PREFIX)]
    return out.reset_index(drop=True), meta


def load_orders() -> pd.DataFrame:
    """產銷統計表未出貨訂單。"""
    p = _pick("PMC", "【2】*.xlsx")
    if not p:
        return pd.DataFrame()
    so = read_excel(p, sheet_name="產銷統計表")
    so = so[pd.to_numeric(so["未出數"], errors="coerce").fillna(0) > 0].copy()
    item = pd.to_numeric(so["項次"], errors="coerce").fillna(0).astype(int)
    out = pd.DataFrame({
        "訂單單號": (so["單別"].map(_s) + "-" + so["單號"].map(_s) + "-"
                     + item.map("{:04d}".format)),
        "客戶":     so["客戶簡稱"].map(_s),
        "品號":     so["品號"].map(_s),
        "訂單日":   so["訂單日期"].map(_d),
        "交期":     [(_d(a) or _d(b) or _d(c))
                     for a, b, c in zip(so["預交日"], so["排定交貨日"], so["原預交日"])],
        "訂單數":   so["訂單數"].map(lambda v: int(_n(v))),
        "未出數":   so["未出數"].map(lambda v: int(_n(v))),
        "代工廠商": so["代工廠商"].map(_s),
        "生管開工日": so["預計開工日"].map(_d),
        "生管齊料日": so["預計齊料日"].map(_d),
        "業務":     so["業務"].map(_s),
        "工單影響原因": so["工單影響原因"].map(_s),
    })
    return out[out["品號"] != ""].reset_index(drop=True)


_V2_DATE = re.compile(r"(\d{1,2})\s*/\s*(\d{1,2})")


def parse_v2_reply(raw: str, today: date):
    """解讀產銷統計表 V2【當月+次兩月】X 欄「產銷回覆本周」。

    使用者定義的口徑：
        含「外購」 → 外購品，買進賣出，不經任何製程 → 不用生產
        「庫存」   → 庫存有帳 → 不用生產
        「新單」   → 新增的訂單
        單純壓日期 → 目前預計出貨日
    其餘（fee、PM入庫、TBD、轉板待改型號…）歸「其他」，原文保留不臆測。

    外購再細分成 外購·庫存 / 外購·待定 / 外購·<日期>，因為現場處理方式不同。
    回傳 (判定, 出貨日 or None, 是否需要生產)。
    """
    s = _s(raw)
    if not s:
        return "", None, True

    def _md_date(m):
        mm, dd = int(m.group(1)), int(m.group(2))
        yr = today.year + (1 if mm < today.month - 6 else 0)
        try:
            return date(yr, mm, dd)
        except ValueError:
            return None

    if "外購" in s:
        if "庫存" in s:
            return "外購·庫存", None, False
        if "TBD" in s.upper():
            return "外購·待定", None, False
        m = _V2_DATE.search(s)
        return "外購·有日期", (_md_date(m) if m else None), False
    if s == "庫存" or s.startswith("庫存"):
        return "庫存", None, False
    if "新單" in s:
        return "新單", None, True

    d = _d(s)                       # 儲存格本身就是日期
    if d:
        return "預計出貨", d, True
    # 「8/28*33pcs」這種是分批出貨：8/28 要出 33 pcs，一樣是預計出貨日。
    # 只要開頭是 月/日，後面接不接數量都算壓日期。
    m = _V2_DATE.match(s)
    if m and m.start() == 0:
        return "預計出貨", _md_date(m), True
    return "其他", None, True


def load_sales_v2(today: date = None) -> dict:
    """產銷統計表 V2【當月+次兩月】→ 訂單單號 → 產銷回覆與出貨判定。

    這份跟【2】mosadexcel 是不同來源：mosadexcel 是全年未出訂單，
    這份只有當月＋次兩月，但多了業務/生管每週更新的「產銷回覆本周」（X 欄）。
    實測 811 筆訂單有 92% 對得上 mosadexcel 的訂單單號。
    """
    today = today or date.today()
    p = _pick_sales_v2()
    if not p:
        return {}
    d = read_excel(p, sheet_name="當月+次兩月", header=0)
    d.columns = [str(c).replace("\n", "") for c in d.columns]
    need = {"單別", "單號", "項次", "產銷回覆本周"}
    if not need <= set(d.columns):
        return {}
    item = pd.to_numeric(d["項次"], errors="coerce").fillna(0).astype(int)
    keys = (d["單別"].map(_s) + "-" + d["單號"].map(_s) + "-" + item.map("{:04d}".format))

    out = {}
    for k, raw, ym, mat in zip(keys, d["產銷回覆本周"], d.get("年月份", keys),
                               d.get("料況", keys)):
        verdict, ship, need_prod = parse_v2_reply(raw, today)
        out[k] = {"產銷回覆": _s(raw), "判定": verdict, "出貨日": ship,
                  "需生產": need_prod, "年月份": _s(ym), "V2料況": _s(mat)}
    return out


def load_shortage() -> pd.DataFrame:
    """W11 缺料表：以製令號彙總缺料件數與最早需求日。

    注意：製令號在「客戶訂單」欄，不是「備註」欄（實測 129/129 對上 MOCR10）。
    """
    p = _pick("PMC", "【補2】*.xls*")
    if not p:
        return pd.DataFrame()
    xl = pd.ExcelFile(p, **CAL)
    sh = next((s for s in xl.sheet_names if "缺料" in s), xl.sheet_names[-1])
    w = read_excel(p, sheet_name=sh)
    w["_mo"] = w["客戶訂單"].map(_s)
    w["_pn"] = w["品號"].map(_s)
    w["_date"] = w["日期"].map(_d)
    w["_proc"] = w["製程名稱"].map(_s)
    w = w[(w["_mo"] != "") & (w["_pn"] != "")]

    w["_name"] = w["品名"].map(_s)
    w["_need"] = pd.to_numeric(w["異動數量"], errors="coerce").fillna(0)
    w["_bal"] = pd.to_numeric(w["預計結存"], errors="coerce").fillna(0)

    rows = []
    for mo_no, g in w.groupby("_mo"):
        procs = set(g["_proc"])
        dates = [d for d in g["_date"] if d]
        items = []
        for pn, gg in g.groupby("_pn"):
            items.append({
                "品號": pn,
                "品名": next((x for x in gg["_name"] if x), ""),
                "需求量": float(gg["_need"].sum()),
                "缺量": float(-min(gg["_bal"].min(), 0)),
                "製程": "／".join(sorted({x for x in gg["_proc"] if x})),
                "需求日": min([d for d in gg["_date"] if d], default=None),
            })
        items.sort(key=lambda x: (x["需求日"] or date(2099, 1, 1)))
        rows.append({
            "製令編號": mo_no,
            "缺料件數": g["_pn"].nunique(),
            "缺料品號": sorted(set(g["_pn"])),
            "缺料明細": items,
            "最早需求日": min(dates) if dates else None,
            "缺PCBA": bool(procs & {"SMT", "DIP", "PCBA"}),
            "缺包材": bool(procs & {"包裝", "包材"}),
            "缺製程": "／".join(sorted(x for x in procs if x)),
        })
    return pd.DataFrame(rows)


def load_eta() -> dict:
    """H2O 缺料明細：品號 → 最晚預計進料日（E.T.A）。"""
    p = _pick("PMC", "【補1】*.xls*")
    if not p:
        return {}
    h = read_excel(p, sheet_name="H2O")
    pn_col = next((c for c in h.columns if "Customer P/N" in str(c)), None)
    eta_col = next((c for c in h.columns if "E.T.A" in str(c)), None)
    if pn_col is None or eta_col is None:
        return {}
    out = {}
    for pn, eta in zip(h[pn_col], h[eta_col]):
        pn, eta = _s(pn), _d(eta)
        if pn and eta:
            out[pn] = max(eta, out.get(pn, eta))
    return out


def load_transfer() -> set:
    """加工廠互調料【待備料】分頁：仍待調撥的品號集合。"""
    p = _pick("PMC", "【3.2】*.xls*")
    if not p:
        return set()
    try:
        t = read_excel(p, sheet_name="待備料")
    except Exception:
        return set()
    done_col = next((c for c in t.columns if "完成日期" in str(c)), None)
    pend = t if done_col is None else t[t[done_col].map(_d).isna()]
    return {_s(v) for v in pend["品號"] if _s(v)}


def load_supply():
    """供需表(分倉)。回傳 (依品號的供給面, 依製令號的領用面)。

    ── 供給面 supply：品號 → {庫存, 進貨清單, 請購中}
    ── 領用面 demand：製令號 → [{品號, 品名, 庫別, 需求量, 結存, 需求日}]
       「備註」欄就是製令號（全檔 8,353 個不重複值，對得上 1,902 張未完工工單）。
       每個品號取該工單領用列的最低「預計結存」，< 0 代表該庫別在時間軸上缺料。

    為什麼一定要用這裡而不是 W11：W11【至MMDD缺料】只涵蓋到報表當下往後兩週
    （0817 那份是 2026-06-17 ~ 2026-08-28），10 月才開工的工單根本不在裡面。
    早期版本把「W11 查不到」當成「沒缺料」，於是把 33 項缺料的工單標成齊套。
    查不到就是查不到，要標「未評估」，不能標齊套。
    """

    p = _pick_supply()
    if not p:
        return {}, {}, {}, {}
    cols = ["品號", "品名", "庫別", "庫別名稱", "日期", "異動別", "異動數量",
            "預計結存", "備註", "廠商", "交期回覆"]
    sd = read_excel(p, sheet_name=0, usecols=cols)
    sd["_pn"] = sd["品號"].map(_s)
    sd["_kind"] = sd["異動別"].map(_s)
    sd["_raw"] = sd["日期"].map(_s)
    sd["_q"] = pd.to_numeric(sd["異動數量"], errors="coerce").fillna(0)
    sd["_bal"] = pd.to_numeric(sd["預計結存"], errors="coerce")
    sd["_mo"] = sd["備註"].map(_s)
    sd = sd[sd["_pn"] != ""]

    # 交期回覆欄直接寫了每張工單的齊料日，例如
    #   「齊2026/9/16_5141-20260731005；MOQ:10；SPQ:1」
    #   「y齊2026/8/12_5145-20260430027；…」
    # 這是採購回覆時標的，比用「最晚一筆進貨」推算權威。同一張工單被標多次時取最晚。
    kit_by_wo = {}
    for reply in sd["交期回覆"].map(_s):
        if not reply:
            continue
        for m in _KIT_RE.finditer(reply):
            try:
                dd = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                continue
            wo_no = m.group(4)
            if wo_no not in kit_by_wo or dd > kit_by_wo[wo_no]:
                kit_by_wo[wo_no] = dd

    out, stock_by_wh = {}, {}
    stock = sd[sd["_raw"].str.startswith("庫存可用量")]
    for pn, q in stock.groupby("_pn")["_q"].sum().items():
        out.setdefault(pn, {"庫存": 0.0, "進貨": [], "請購": False})["庫存"] = float(q)
    # 分倉庫存：配料要看「開工那個倉」有多少，不是全倉合計。
    # 庫存列的庫別欄混了代碼(S01/S07/R0x)與名稱(電子倉…)，領用列一律是代碼，
    # 實測領用用到的 13 種代碼在庫存列全都找得到，所以直接用庫別欄當鍵。
    for (pn, wh), q in stock.groupby(["_pn", sd["庫別"].map(_s)])["_q"].sum().items():
        stock_by_wh[(pn, wh)] = float(q)

    inbound = sd[sd["_kind"] == "預計進貨"]
    for pn, d, q, vendor, reply in zip(inbound["_pn"], inbound["日期"], inbound["_q"],
                                       inbound["廠商"], inbound["交期回覆"]):
        dd = _d(d)
        if not dd:
            continue
        e = out.setdefault(pn, {"庫存": 0.0, "進貨": [], "請購": False})
        e["進貨"].append((dd, float(q), _s(vendor), _s(reply)))

    pend = sd[sd["_kind"].isin(["預計請購", "請拋採未確認"])]
    for pn in set(pend["_pn"]):
        out.setdefault(pn, {"庫存": 0.0, "進貨": [], "請購": False})["請購"] = True

    for e in out.values():
        e["進貨"].sort(key=lambda x: x[0])

    # ── 領用面：製令號 → 該工單各 (品號, 庫別) 的需求 ──
    # 同一張工單同一品號可能有多列，先加總；庫別要進鍵，因為配料是分倉扣的。
    use = sd[(sd["_kind"] == "預計領用") & (sd["_mo"] != "")]
    demand = {}
    for mo_no, g in use.groupby("_mo"):
        items = {}
        for pn, name, wh, whn, d, q, bal in zip(g["_pn"], g["品名"], g["庫別"],
                                                g["庫別名稱"], g["日期"], g["_q"], g["_bal"]):
            key = (pn, _s(wh))
            it = items.setdefault(key, {"品號": pn, "品名": _s(name), "庫別": _s(wh),
                                        "庫別名稱": _s(whn), "需求量": 0.0,
                                        "結存": None, "需求日": None})
            it["需求量"] += float(q)
            if bal is not None and not pd.isna(bal):
                it["結存"] = float(bal) if it["結存"] is None else min(it["結存"], float(bal))
            dd = _d(d)
            if dd and (it["需求日"] is None or dd < it["需求日"]):
                it["需求日"] = dd
        demand[mo_no] = list(items.values())
    return out, stock_by_wh, demand, kit_by_wo


def allocate(demand: dict, stock_by_wh: dict, start_of: dict) -> dict:
    r"""依開工日排序，逐張工單扣該倉庫存，算出每張工單真正缺多少。

    使用者定義的口徑：
        A 料該倉有 1000 pcs，三張工單依開工日排隊 ——
        第 1 張要 500 → 配 500，剩 500
        第 2 張要 400 → 配 400，剩 100
        第 3 張要 150 → 只配得到 100，缺 50

    回傳 製令號 → [{品號, 品名, 庫別, 需求量, 配到, 缺量, 先前佔用, 需求日}]，
    只收缺量 > 0 的項目；完全配得到的工單不會出現在回傳值裡。
    """
    far = date(2099, 12, 31)
    queue = []
    for mo_no, items in demand.items():
        st_d = start_of.get(mo_no) or far
        for it in items:
            queue.append((st_d, mo_no, it))
    queue.sort(key=lambda x: (x[0], x[1]))          # 開工日 → 製令號，穩定排隊

    avail = dict(stock_by_wh)
    used = {}
    short = {}
    for st_d, mo_no, it in queue:
        key = (it["品號"], it["庫別"])
        have = max(avail.get(key, 0.0), 0.0)
        need = float(it["需求量"])
        take = min(have, need)
        avail[key] = have - take
        before = used.get(key, 0.0)
        used[key] = before + take
        lack = need - take
        if lack > 0:
            short.setdefault(mo_no, []).append({
                "品號": it["品號"], "品名": it["品名"],
                "庫別": it["庫別"], "庫別名稱": it.get("庫別名稱", ""),
                "需求量": need, "配到": take, "缺量": lack,
                "先前佔用": before, "需求日": it.get("需求日"),
                "開工日": None if st_d is far else st_d,
            })
    for v in short.values():
        v.sort(key=lambda x: -x["缺量"])
    return short


_MODEL_RE = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)*")


def model_key(text: str) -> str:
    """從品名／機種名稱抽出機種代號並正規化，例如
    'RD TPS-9168GT-M12 主板' → 'TPS9168GTM12'、'IES-3082GP;General' → 'IES3082GP'。
    抽不出（沒有數字）回空字串，避免拿 'RD'、'PCBA' 這種字去亂配。
    """
    s = _s(text)
    if not s:
        return ""
    s = re.split(r"[;,（(\n]", s)[0]
    s = re.sub(r"^\s*(RD|DIP|SMT)\s+", "", s, flags=re.I)
    for tok in _MODEL_RE.findall(s):
        if any(c.isdigit() for c in tok) and len(tok) >= 5:
            return re.sub(r"[^A-Z0-9]", "", tok.upper())
    return ""


def load_jigs() -> tuple:
    """PE 生產治工具一覽表【量產】。

    表頭兩列：r0 是「鋼板 / 載具」群組，r1 是子欄位，資料自 r2 起。
      欄0 板階料號、欄1 板號、欄2~8 鋼板（機種名稱/位置/產編/數量/移轉日期/備註/維修）、
      欄9~15 載具（位置/機種名稱/產編/數量/移轉日期/備註/維修）。

    回傳 (依板階料號的索引, 依機種代號的索引)。9-* 成品工單對不到板階料號，
    改用機種代號比對品名，覆蓋率才拉得起來。
    """
    p = _pick("PE", "*治工具*.xls*")
    if not p:
        return {}, {}
    raw = read_excel(p, sheet_name="量產", header=None)
    by_pn, by_model = {}, {}
    for i in range(2, len(raw)):
        r = raw.iloc[i]
        pn = _s(r.iloc[0])
        info = {
            "鋼板位置": _s(r.iloc[3]), "鋼板數量": _n(r.iloc[5], None), "鋼板備註": _s(r.iloc[7]),
            "鋼板產編": _s(r.iloc[4]), "鋼板移轉": _d(r.iloc[6]),
            "載具位置": _s(r.iloc[9]), "載具數量": _n(r.iloc[12], None), "載具備註": _s(r.iloc[14]),
            "載具產編": _s(r.iloc[11]), "載具移轉": _d(r.iloc[13]),
            "機種":     _s(r.iloc[2]) or _s(r.iloc[10]), "板階料號": pn,
        }
        if pn:
            by_pn.setdefault(pn, info)
        mk = model_key(r.iloc[2]) or model_key(r.iloc[10])
        if mk:
            by_model.setdefault(mk, info)
    return by_pn, by_model


_STATION_RE = re.compile(r"([一-鿿]{2,4})\s*(\d+)")
# 供需表「交期回覆」裡的齊料日標記：齊YYYY/M/D_製令號（前面可能有 y）
_KIT_RE = re.compile(r"[yY]?齊\s*(\d{4})[/-](\d{1,2})[/-](\d{1,2})\s*_\s*([A-Za-z0-9\-]+)")


def load_baoqiao() -> dict:
    r"""寶橋廠排程：製令號 → 廠內真實生產進度。

    生管部\09. 廠內改機排程\2026\寶橋廠排程*.xlsx，取最新一份。
      [排程]  0線別 1工單 2機種 3數量 4進度 5進度說明 … 14整體料齊率
      [已完工] 0線別 1製令 2機種 3數量 4進度說明 … 14整體料齊率（少一欄，之後整體左移 1）

    實測（0820 版）：排程 265 筆、已完工 228 筆，兩表工單零重疊，
    且 493 筆全部對得上 MOCR10 製令編號。其中已完工表有 14 筆
    在 MOCR10 仍列「未完工」——這正是要拿這份檔案來校正產能的原因。

    進度說明形如「未完工，組裝99，待換料1，測試99，包裝99」，
    解析成 {組裝:99, 待換料:1, 測試:99, 包裝:99} 當作各站真實進度。
    """
    p = _pick_baoqiao()
    if not p:
        return {}
    out = {}
    for sheet in ("排程", "已完工"):
        try:
            d = read_excel(p, sheet_name=sheet)
        except Exception:
            continue
        note_at = 5 if sheet == "排程" else 4
        for _, r in d.iterrows():
            no = _s(r.iloc[1])
            if not no or no.lower() == "nan":
                continue
            status = _s(r.iloc[4])
            note = _s(r.iloc[note_at])
            qty = int(_n(r.iloc[3]))
            prog = {m.group(1): int(m.group(2)) for m in _STATION_RE.finditer(note)}
            blob = status + note
            if "取消" in blob:
                state = "取消"
            elif "已完工" in blob or "指定完工" in blob:
                state = "已完工"
            elif "品檢中" in blob:
                state = "品檢中"
            elif "生產中" in blob or "未完工" in blob:
                state = "生產中"
            elif "未齊料" in blob:
                state = "未齊料"
            elif "齊料" in blob:
                state = "已齊料"
            elif "異常" in blob or "待確認" in blob:
                state = "異常"
            else:
                state = "排程中"
            # 還沒包完的量＝廠內真實在製；沒有站別數字就整張工單算在製
            packed = prog.get("包裝", 0)
            wip = 0 if state in ("已完工", "取消") else max(qty - packed, 0)
            out[no] = {
                "來源表": sheet, "進度": state, "進度說明": note,
                "數量": qty, "線別": _s(r.iloc[0]), "站別進度": prog,
                "WIP": wip, "料齊率": _n(r.iloc[14], None),
                "已完工": state in ("已完工", "取消"),
            }
    return out


def jig_detail(info: dict) -> str:
    """治具明細：鋼板／載具各在哪、產編、數量、移轉日、備註。"""
    if not info:
        return "PE 治工具一覽表查無此機種"
    parts = []
    for kind in ("鋼板", "載具"):
        loc = info.get(kind + "位置") or "位置未填"
        qty = info.get(kind + "數量")
        sn = info.get(kind + "產編") or ""
        mv = info.get(kind + "移轉")
        note = info.get(kind + "備註") or ""
        seg = "{}：{}".format(kind, loc)
        if qty:
            seg += " ×{:g}".format(qty)
        if sn:
            seg += "　產編 " + sn
        if mv:
            seg += "　移轉 {:%Y/%m/%d}".format(mv)
        if note:
            seg += "　備註 " + note.replace("\n", " ")[:40]
        parts.append(seg)
    if info.get("板階料號"):
        parts.append("板階料號 " + info["板階料號"])
    return "　｜　".join(parts)


def _jig_state(info: dict, kind: str) -> str:
    """把治具原始欄位翻成狀態字串。"""
    if not info:
        return "➖ 無資料"
    loc = info.get(kind + "位置", "")
    qty = info.get(kind + "數量")
    note = info.get(kind + "備註", "")
    bad = any(k in note for k in ("報廢", "破損", "遺失", "待修", "維修"))
    if bad:
        return "❌ {}".format(note[:8] or "異常")
    if qty and qty > 0:
        return "✅ 已備{}".format("（" + loc + "）" if loc else "")
    if loc:
        return "🟡 待確認（{}）".format(loc)
    return "➖ 無資料"


# ─── 母子串連：整條鏈趕不趕得上產銷出貨日 ──────────────────────────────────
# 每月產能上限（使用者給的口徑，單位=pcs/月）
CAPACITY = {"國智": 30000, "唐佑": 15000, "其他": 10000, "廠內": 9000}


def _month_key(d):
    return "{:04d}-{:02d}".format(d.year, d.month) if d else ""


def chain(df: pd.DataFrame, today: date = None) -> pd.DataFrame:
    """母子工單串連，並判斷整條鏈趕不趕得上產銷出貨日。

    口徑（使用者定義）：
      * 一張工單一列，母單帶三張子單就是四列，這裡只補欄位不動列數。
      * 子單完工日＝齊料日 +1 週（回廠）+2 週（完工），見 derive_schedule()。
      * 母單要等所有子單回來才做得完，所以整條鏈的預計完工
        ＝ max(本單推算完工, 所有下游子單的鏈完工)，一路遞迴到最底層。
      * 目標出貨日看產銷回覆；子單自己沒有訂單，跟著同一條鏈的根（母單）走。
      * 趕不上的時候要指出卡在母單還是子單、卡哪幾項料、進貨來不來得及。
    """
    today = today or date.today()
    if df.empty:
        return df
    idx = {mo: i for i, mo in enumerate(df["工單·工單號"]) if mo}
    parent = list(df["工單·母工單"])
    kids = {}
    for i, p_ in enumerate(parent):
        if p_ and p_ in idx:
            kids.setdefault(idx[p_], []).append(i)

    # 本單自己的預計完工：優先用齊料日推算，沒有齊料日才退回 ERP 預計完工
    own = [(r or e) for r, e in zip(df["排程·推算完工"], df["工單·完工日"])]
    own_src = ["齊料推算" if r else ("ERP 預計完工" if e else "")
               for r, e in zip(df["排程·推算完工"], df["工單·完工日"])]

    chain_done, blocker = [None] * len(df), [""] * len(df)

    def walk(i, depth=0):
        """回傳 (整條鏈完工日, 決定這個日期的那一列)。"""
        if chain_done[i] is not None:
            return chain_done[i], blocker[i]
        best, who = own[i], (df["工單·工單號"].iat[i] if own[i] else "")
        if depth < 6:
            for k in kids.get(i, []):
                kd, kw = walk(k, depth + 1)
                if kd and (best is None or kd > best):
                    best, who = kd, (kw or df["工單·工單號"].iat[k])
        chain_done[i] = best or False      # False＝算過但沒有日期，避免重算
        blocker[i] = who
        return best, who

    for i in range(len(df)):
        walk(i)
    chain_done = [d or None for d in chain_done]

    # 每一列所屬的「鏈根」：一路往上找到沒有母單為止
    root = []
    for i in range(len(df)):
        cur, hops = i, 0
        while parent[cur] and parent[cur] in idx and hops < 10:
            cur, hops = idx[parent[cur]], hops + 1
        root.append(cur)

    # 目標出貨日：一律看鏈根（母單）的產銷出貨日，子單不管自己有沒有配到訂單
    # 都跟著母單走（使用者口徑）。子單常因為品號相同被配到另一張訂單，各走各的
    # 日期時，同一家母子四列會顯示 09/01、09/28、11/17 三個不同月份，看起來像在
    # 跳來跳去 —— 但整條鏈本來就是為了同一個成品出貨。
    # 子單自己那張訂單的日期沒有丟掉，還留在「訂單·V2出貨日／訂單·交期」欄。
    v2d, due = list(df["訂單·V2出貨日"]), list(df["訂單·交期"])
    hasord = list(df["訂單·有出貨需求"])
    tgt, tsrc = [], []
    for i in range(len(df)):
        r = root[i]
        suffix = "" if r == i else "（承母單）"
        if v2d[r]:
            tgt.append(v2d[r]); tsrc.append("產銷出貨日" + suffix)
        elif hasord[r] and due[r]:
            tgt.append(due[r]); tsrc.append("訂單交期" + suffix)
        else:
            tgt.append(None); tsrc.append("無出貨日")

    # 判斷來不來得及 + 卡點 + 缺什麼料 + 進貨追不追得上
    short_n, short_items = list(df["料況·缺料件數"]), list(df["料況·缺料項目"])
    nkid = [len(kids.get(i, [])) for i in range(len(df))]
    wono, needp = list(df["工單·工單號"]), list(df["訂單·需生產"])
    fits, gaps, bwho, bwhat, buy = [], [], [], [], []
    for i in range(len(df)):
        cd, td = chain_done[i], tgt[i]
        b = blocker[i]
        bi = idx.get(b, i)
        is_self = (bi == i)
        # 卡點：決定鏈完工日的那張單，是自己還是某張子單
        # 有子單才叫「母單」，孤單一張就照實說「本單」
        me = "母單" if (is_self and nkid[i]) else ("本單" if is_self else "子單")
        if not wono[i]:
            # 只有「連工單都沒開」才講不用生產／還沒開。工單真的在跑就照實
            # 報卡點 —— 產銷回覆走庫存不代表這張工單不用做，蓋掉真正的缺料
            # 會讓那 70 幾張（多半還帶著板階子單）的問題整個消失。
            bwho.append("➖ 不用生產" if not needp[i] else "❗ 工單還沒開")
        elif not cd:
            bwho.append("❔ 無齊料日，算不出完工")
        elif short_n[bi] > 0:
            bwho.append(me + "缺料（{}）".format(b))
        else:
            bwho.append(me + "工期（{}）".format(b))
        its = short_items[bi] or []
        bwhat.append("、".join("{}×{:,.0f}".format(x["品號"], x.get("缺量", 0))
                              for x in its[:4]) + ("…" if len(its) > 4 else ""))
        if not needp[i]:
            # 產銷回覆庫存／外購，這筆本來就不經製程，沒有趕不趕得上的問題
            fits.append("➖ 不用生產"); gaps.append(None)
        elif not wono[i]:
            fits.append("❔ 未開單"); gaps.append(None)
        elif not cd:
            fits.append("❔ 無齊料日"); gaps.append(None)
        elif not td:
            fits.append("➖ 無出貨日"); gaps.append(None)
        elif cd <= td:
            fits.append("✅ 來得及"); gaps.append(net_workdays(cd, td))
        else:
            n = net_workdays(td, cd)
            fits.append("❌ 來不及（晚 {} 個工作天）".format(n)); gaps.append(-n)
        # 要不要請採購拉進貨：卡點那張單最晚的一筆進貨晚於出貨日就要拉
        eta = max([x["進貨日"] for x in its if x.get("進貨日")], default=None)
        if td and eta and eta > td:
            buy.append("🔺 請採購拉進貨（最晚進貨 {:%m/%d} 晚於出貨 {:%m/%d}）"
                       .format(eta, td))
        elif its and not eta:
            buy.append("🔺 請採購（缺料無進貨排程）")
        else:
            buy.append("—")

    df = df.copy()
    df["鏈·本單完工"] = own
    df["鏈·完工來源"] = own_src
    df["鏈·預計完工"] = chain_done
    df["鏈·目標出貨日"] = tgt
    df["鏈·出貨日來源"] = tsrc
    df["鏈·結論"] = fits
    df["鏈·寬裕工作天"] = gaps
    df["鏈·卡點"] = bwho
    df["鏈·卡料"] = bwhat
    df["鏈·採購動作"] = buy
    df["鏈·根工單"] = [df["工單·工單號"].iat[r] or df["訂單·訂單單號"].iat[r]
                       for r in root]
    df["鏈·層深"] = [0 if root[i] == i else 1 for i in range(len(df))]

    # ── 月份歸屬：有出貨日就看出貨日，沒有就看最終齊料日；整條鏈跟著根走，
    #    母子四列才不會被拆到不同月份（使用者：一張工單一列、母子要串在一起）。
    kitf = list(df["料況·最終齊料日"])
    mon, msrc = [], []
    for i in range(len(df)):
        r = root[i]
        if tgt[r]:
            mon.append(_month_key(tgt[r])); msrc.append(tsrc[r])
        elif kitf[r]:
            mon.append(_month_key(kitf[r])); msrc.append("最終齊料日")
        elif chain_done[r]:
            mon.append(_month_key(chain_done[r])); msrc.append("推算完工")
        else:
            mon.append(""); msrc.append("無日期")
    df["月份·歸屬"] = mon
    df["月份·來源"] = msrc
    return df


def capacity_by_month(df: pd.DataFrame) -> pd.DataFrame:
    """每月各廠的投產量 vs 產能上限。一張工單算在它自己的加工廠，
    母單（成品階）與子單（板階）各算各的，因為本來就是兩段不同的工。"""
    if df.empty:
        return pd.DataFrame()
    d = df[(df["工單·工單號"] != "") & (df["月份·歸屬"] != "")
           & (~df["產能·已完工"])]
    if d.empty:
        return pd.DataFrame()
    g = (d.groupby(["月份·歸屬", "工單·加工廠"])
           .agg(數量=("訂單·數量", "sum"), 工單數=("工單·工單號", "count"))
           .reset_index())
    g["上限"] = g["工單·加工廠"].map(CAPACITY).fillna(0).astype(int)
    g["用量%"] = (g["數量"] / g["上限"].replace(0, pd.NA) * 100).round(0)
    g["燈號"] = ["🔴 超出" if p and p >= 100 else
                 "🟡 逼近" if p and p >= 85 else "🟢 OK"
                 for p in g["用量%"]]
    return g.sort_values(["月份·歸屬", "工單·加工廠"]).reset_index(drop=True)


# ─── 組裝成全製程主表 ────────────────────────────────────────────────────────
def build(today: date = None, year: int = None) -> pd.DataFrame:
    """把七個來源組成全製程主表；欄位名稱與頁面既有的五大群組一致。

    year：只保留該年度的資料（交期年；交期空白時看開工年）。預設當年度。
    產銷統計表與 MOCR10 都有大量 2020~2025 未結案的殭屍單，不濾會整個洗版。
    傳 0 或 None 以外的假值代表不過濾。
    """
    today = today or date.today()
    year = today.year if year is None else year
    wo, wmeta = load_wo()
    so = load_orders()
    if wo.empty and so.empty:
        return pd.DataFrame()
    wo_index = wmeta["index"]
    child_of, kids = wmeta["child_of"], wmeta["kids"]

    # 【補1】H2O、【補2】W11 依使用者指示暫不帶入料況，載入函式保留備用。
    transfer = load_transfer()
    v2 = load_sales_v2(today)
    supply, stock_by_wh, demand, kit_by_wo = load_supply()
    # 依開工日排隊扣庫存，得到每張工單真正缺多少（口徑見 allocate 說明）
    start_of = {no: info.get("開工") for no, info in wo_index.items()}
    short_map = allocate(demand, stock_by_wh, start_of)
    jig_pn, jig_model = load_jigs()
    bq = load_baoqiao()

    # 工單索引：訂單單號 → 工單、品號 → 工單清單（取預計開工最早者）
    by_ord, by_pn = {}, {}
    for _, w in wo.iterrows():
        if w["訂單單號"]:
            by_ord.setdefault(w["訂單單號"], w)
        by_pn.setdefault(w["產品品號"], []).append(w)
    for k in by_pn:
        by_pn[k].sort(key=lambda w: w["預計開工"] or date(2099, 1, 1))

    # 子母關係已在 load_wo() 由全檔（含已完工）建好，見該函式說明。

    used_mo, rows = set(), []

    def emit(o, w):
        """o=訂單列(可為 None)、w=工單列(可為 None)。"""
        pn = _s(o["品號"]) if o is not None else _s(w["產品品號"])
        mo_no = _s(w["製令編號"]) if w is not None else ""
        start = w["預計開工"] if w is not None else (o["生管開工日"] if o is not None else None)

        # ── 料況：只用供需表(分倉)，備註欄=製令號取預計領用列。
        # 供需表裡查不到這張工單 ＝ 料已經扣帳扣完了，等同齊料（使用者口徑）。
        # 早期標成「未評估」是錯的：整張都扣完就不會再出現在供需表的未來需求裡。
        in_supply = bool(mo_no) and mo_no in demand
        items = short_map.get(mo_no, []) if mo_no else []
        short = len(items)
        short_pns = [x["品號"] for x in items]
        lines, etas, all_on_hand, any_pending = [], [], True, False
        for it in items:
            pn_i = it["品號"]
            sup = supply.get(pn_i, {})
            on_hand = float(sup.get("庫存", 0) or 0)
            inb = sup.get("進貨", [])
            nxt = next((x for x in inb if x[0] >= today), inb[-1] if inb else None)
            # 「該庫別結存」是時間軸上的預計結存（負值＝那個倉在那天不夠），
            # 「全倉」是所有庫別的庫存可用量合計。兩者不同層次，並列而不是相減 ——
            # 全倉有貨但該倉負，代表這是可以靠調撥解決的缺。
            # 依開工日排隊配賦後的結果：需求 / 配到 / 缺多少 / 這個倉先前已被前面幾張佔走多少
            seg = "{}　{}　{}倉 需求 {:,.0f}　配到 {:,.0f}　缺 {:,.0f}".format(
                pn_i, (it["品名"] or "")[:16], it.get("庫別") or "",
                it["需求量"], it.get("配到", 0), it.get("缺量", 0))
            if it.get("先前佔用"):
                seg += "（前面工單先佔 {:,.0f}）".format(it["先前佔用"])
            if on_hand > 0:
                seg += "　全倉 {:,.0f}".format(on_hand)
            else:
                seg += "　全倉 0"
                all_on_hand = False
            # 把進貨與全倉庫存直接掛回項目，頁面點開明細時不用再查一次
            it["全倉"] = on_hand
            it["進貨日"] = nxt[0] if nxt else None
            it["進貨量"] = nxt[1] if nxt else None
            it["進貨廠商"] = nxt[2] if nxt else ""
            it["全部進貨"] = [(d0, q0, v0) for d0, q0, v0, _r0 in inb][:6]
            if nxt:
                etas.append(nxt[0])
                seg += "　進貨 {:%m/%d} ×{:,.0f}{}".format(
                    nxt[0], nxt[1], "（{}）".format(nxt[2]) if nxt[2] else "")
            elif sup.get("請購"):
                seg += "　請購中（無進貨排程）"
                any_pending = True
            elif pn_i in transfer:
                seg += "　待調撥"
            else:
                seg += "　無進貨排程"
                any_pending = True
            lines.append(seg)

        # ── 最終齊料日 ──
        # 第一優先：供需表「交期回覆」欄直接標的「齊YYYY/M/D_製令號」（採購回覆，最權威）
        # 第二優先：缺料各項裡最晚的一筆預計進貨（要等最後一項到齊才算齊料）
        # 都沒有：齊套的話就是開工日／齊套日；否則未知
        kit_final, kit_src = None, "無"
        if mo_no and mo_no in kit_by_wo:
            kit_final, kit_src = kit_by_wo[mo_no], "交期回覆"
        elif etas:
            kit_final, kit_src = max(etas), "推算(最晚進貨)"
        elif short == 0:
            kit_final = (start or None)
            kit_src = "已齊套" if in_supply else "已扣帳（供需表無此單）"

        need_days = [x["需求日"] for x in items if x.get("需求日")]
        first_need = min(need_days) if need_days else None
        if not mo_no:
            # 連工單都沒開，供需表當然查不到 —— 這不是「已扣帳」，是還沒得算。
            fit, kit = "➖ 未開單", None
            kit_final, kit_src = None, "未開單"
        elif short == 0 and not in_supply:
            fit, kit = "✅ 已扣帳", (o["生管齊料日"] if o is not None else None) or start
        elif short == 0:
            fit = "✅ 齊套"
            kit = (o["生管齊料日"] if o is not None else None) or start
        elif any(p in transfer for p in short_pns):
            fit, kit = "🔄 待調撥", first_need
        elif not all_on_hand and any_pending:
            fit, kit = "🟡 待採購", first_need
        else:
            fit, kit = "❌ 缺料", first_need

        # 子母工單：母＝成品階（9-*）、子＝板階（5-70-*）
        parent = child_of.get(mo_no, "") if mo_no else ""
        p_info = wo_index.get(parent) if parent else None
        p_pn = p_info["品號"] if p_info else ""
        p_state = p_info["狀態"] if p_info else ""
        n_kids = len(kids.get(mo_no, [])) if mo_no else 0
        # 子單清單含「不會顯示在列表上」的那些（指定完工、已結案、被單別過濾掉的）。
        # 徽章寫 6 子、底下卻只有 5 列，就是因為第 6 張是指定完工被拉掉了 ——
        # 把清單和狀態一起帶出去，畫面才有辦法照實說明差額。
        kid_list = kids.get(mo_no, []) if mo_no else []
        kid_detail = "，".join(
            "{}（{}）".format(k, (wo_index.get(k) or {}).get("狀態") or "？")
            for k in kid_list)
        if not mo_no:
            tier = ""
        elif parent:
            tier = "子·板階" if pn.startswith("5-") else "子單"
        elif n_kids:
            tier = "母·成品" if pn.startswith("9") else "母單"
        else:
            tier = "單一"

        # 廠內真實進度：寶橋廠排程優先於 ERP 狀態碼（ERP 常有已完工卻沒結案的落差）
        b = bq.get(mo_no) if mo_no else None
        if b is not None:
            sched = {"已完工": "🏁 已完工", "取消": "⛔ 取消", "品檢中": "🔬 品檢中",
                     "生產中": "✅ 生產中", "未齊料": "❌ 未齊料",
                     "已齊料": "🟢 已齊料", "異常": "⚠ 異常"}.get(b["進度"], "🟡 排程中")
        elif w is not None:
            sched = "✅ 已排產" if w["狀態碼"] in ("生產中", "已發料") else "🟡 待排產"
        else:
            sched = "❌ 未開單"

        # 治具：9 開頭是成品階，本來就沒有鋼板／載具，一律視為不適用（PASS）。
        # 先前用機種代號回頭比對，會把板階的治具狀態掛到成品單上，誤報未備。
        # 其餘（5-70-* 板階）先用板階料號直接對，對不到再用品名的機種代號對。
        wo_pn = _s(w["產品品號"]) if w is not None else pn
        if wo_pn.startswith("9"):
            steel = carrier = "➖ 不適用（成品階）"
            jg = None
        else:
            jg = jig_pn.get(wo_pn)
            if jg is None:
                mk = model_key(_s(w["品名"]) if w is not None else "") or model_key(wo_pn)
                jg = jig_model.get(mk) if mk else None
            steel, carrier = _jig_state(jg, "鋼板"), _jig_state(jg, "載具")

        # 產銷統計表 V2 的「產銷回覆本周」：庫存／外購都不用生產，直接出貨
        vv = v2.get(_s(o["訂單單號"])) if o is not None else None
        rows.append({
            "訂單·產銷回覆": (vv["產銷回覆"] if vv else ""),
            "訂單·出貨判定": (vv["判定"] if vv else ""),
            "訂單·V2出貨日": (vv["出貨日"] if vv else None),
            "訂單·需生產":   (vv["需生產"] if vv else True),
            "訂單·外購品":   bool(vv and vv["判定"].startswith("外購")),
            "訂單·有出貨需求": o is not None,
            "訂單·訂單單號": _s(o["訂單單號"]) if o is not None else "（無訂單）",
            "訂單·客戶":     _s(o["客戶"]) if o is not None else "—",
            "訂單·料號":     pn,
            "訂單·品名":     (_s(w["品名"]) if w is not None else ""),
            "訂單·訂單日":   (o["訂單日"] if o is not None else
                              (w["開單日期"] if w is not None else None)),
            "訂單·交期":     (o["交期"] if o is not None else
                              (w["預計完工"] if w is not None else None)),
            "訂單·數量":     int(o["未出數"]) if o is not None else int(w["預計產量"]),
            # 這張訂單的工單開了沒；沒開的話是「不用開」還是「忘了開」
            "工單·開單狀態": ("已開立" if mo_no else
                              "不用開（庫存出貨）" if (vv and vv["判定"] == "庫存") else
                              "不用開（外購）" if (vv and vv["判定"].startswith("外購")) else
                              "未開立"),
            "工單·工單號":   mo_no,
            "工單·母工單":   parent,
            "工單·母工單品號": p_pn,
            "工單·母工單狀態": p_state,
            "工單·階層":     tier,
            "工單·子單數":   n_kids,
            "工單·子單號":   ",".join(kid_list),
            "工單·子單明細": kid_detail,
            "工單·開工日":   start if w is not None else None,
            "工單·完工日":   w["預計完工"] if w is not None else None,
            "工單·加工廠":   (w["加工廠"] if w is not None
                              else _fac(o["代工廠商"] if o is not None else "")),
            "工單·廠商原名": (_s(w["廠商原名"]) if w is not None
                              else _s(o["代工廠商"]) if o is not None else ""),
            "料況·齊套狀態": fit,
            "料況·齊套日":   kit,
            "料況·缺料件數": short,
            # 這欄講的是「缺的那幾項料在全倉有沒有貨」，不是成品有沒有庫存。
            # 早期寫成「缺料件數==0 就一律有庫存」，連未評估的都被標成有庫存 ——
            # 沒查過就不能說有，所以未評估一律照實寫「未評估」。
            "料況·缺料庫存": ("未開單（無工單可查）" if not mo_no else
                              "無缺料（已扣帳）" if (short == 0 and not in_supply) else
                              "無缺料" if short == 0 else
                              "缺料·全倉有貨（可調撥）" if all_on_hand else
                              "缺料·全倉無貨"),
            # 成品本身在供需表的庫存可用量（全倉合計），跟上面那欄是兩回事
            "料況·成品庫存": float(supply.get(pn, {}).get("庫存", 0) or 0),
            "料況·預計進貨日": max(etas) if etas else None,
            "料況·最近進貨日": min(etas) if etas else None,
            "料況·缺料明細": "\n".join(lines),
            "料況·缺料項目": items,          # 給頁面點擊後開明細用（含配到/缺量/進貨）
            "料況·最終齊料日": kit_final,
            "料況·齊料來源": kit_src,
            # 使用者公式：齊料日 +1 週 = 回廠日，回廠日 +2 週 = 完工日
            "排程·回廠日":   derive_schedule(kit_final)[0],
            "排程·推算完工": derive_schedule(kit_final)[1],
            "料況·PCBA":     _cat_flag(items, _PCBA_KW),
            "料況·包材":     _cat_flag(items, _PACK_KW),
            "治具·鋼板":     steel,
            "治具·載具":     carrier,
            "治具·明細":     ("成品階（9 開頭）無鋼板／載具需求"
                              if wo_pn.startswith("9") else jig_detail(jg)),
            # 治具在不在該做的那個委外倉（成品階與外購品不需要治具）
            "治具·到廠": ("➖ 成品階不需" if wo_pn.startswith("9") else
                          _jig_at_site(jg, (w["加工廠"] if w is not None else ""),
                                       _s(w["廠商原名"]) if w is not None else "")),
            "治具·預計完成日": None,
            "產能·產線WIP":  (int(b["WIP"]) if b is not None
                              else int(w["未生產量"]) if w is not None else 0),
            "產能·排產狀況": sched,
            "產能·廠內進度": (b["進度說明"][:40] if b is not None and b["進度說明"] else "—"),
            "產能·線別":     (b["線別"] if b is not None and b["線別"] else "—"),
            "產能·已完工":   bool(b["已完工"]) if b is not None else False,
            "產能·瓶頸資源": (b["進度說明"][:16] if b is not None and b["進度說明"]
                              else "➖"),
        })

    # ① 每一筆未出訂單：先找工單（訂單單號優先，其次品號）
    for _, o in so.iterrows():
        # 訂單單號優先，但一樣要檢查有沒有被前面的訂單用掉 ——
        # 少了這個檢查，同一張工單會被兩筆訂單各配一次，畫面上就出現重複列。
        w = by_ord.get(o["訂單單號"])
        if w is not None and _s(w["製令編號"]) in used_mo:
            w = None
        if w is None:
            cand = [x for x in by_pn.get(o["品號"], [])
                    if _s(x["製令編號"]) not in used_mo]
            w = cand[0] if cand else None
        if w is not None:
            used_mo.add(_s(w["製令編號"]))
        emit(o, w)

    # ② 其餘未完工工單一律收進來（備貨型、或同品號已被別張訂單配走的）。
    #    早期只收「有缺料或生產中」，結果像 MO02-20260817002 這種
    #    未生產＋沒缺料的母單會整張消失，連帶三張板階子單也看不到。
    #    範圍交給年度過濾把關，不要在這裡先砍。
    for _, w in wo.iterrows():
        mo_no = _s(w["製令編號"])
        if mo_no in used_mo:
            continue
        used_mo.add(mo_no)
        emit(None, w)

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    # R 開頭的料號（R002-02、R003-… 這類）依指示整批不列入，直接在資料層拉掉
    df = df[~df["訂單·料號"].astype(str).str.upper().str.startswith("R")]
    if df.empty:
        return df
    # 母子串連要在年度過濾前做：子單常落在隔年，先濾就會把鏈截斷
    df = chain(df.reset_index(drop=True), today)
    # 產能排隊要在串連之後（要用到目標出貨日與月份歸屬），也要在年度過濾之前，
    # 這樣同一個月的隊伍是完整的，不會因為畫面只看某幾張就把累計算少。
    df = capacity_queue(df)

    # 只留當年度：交期年為準，交期空白時看開工年。兩者都空白就丟掉。
    # 但板階子單留下來時，它的成品母單一定要跟著留 —— 母單常因交期落在隔年
    # 而被年度濾掉，畫面上就會出現一堆看不出屬於誰的孤兒子單。
    if year:
        keep = [(d.year == year) if d else ((s.year == year) if s else False)
                for d, s in zip(df["訂單·交期"], df["工單·開工日"])]
        kept = df[keep]
        # 母單可能自己也是別人的子單，所以要一路往上補到收斂為止；
        # 只補一層的話，上一層的母單還是會變成孤兒。
        for _ in range(10):
            need = ({p for p in kept["工單·母工單"] if p}
                    - set(kept["工單·工單號"]))
            extra = df[df["工單·工單號"].isin(need)] if need else df.iloc[0:0]
            if not len(extra):
                break
            kept = pd.concat([kept, extra])
        df = kept

    # 排序：同一條鏈黏在一起（母單在前、子單緊接在後），鏈與鏈之間依目標出貨日。
    far = date(2099, 12, 31)
    df = df.assign(_k1=[d or far for d in df["鏈·目標出貨日"]],
                   _k2=df["鏈·根工單"], _k3=df["鏈·層深"],
                   _k4=[d or far for d in df["工單·開工日"]])
    df = (df.sort_values(["_k1", "_k2", "_k3", "_k4"])
            .drop(columns=["_k1", "_k2", "_k3", "_k4"])
            .reset_index(drop=True))
    return df


def capacity_queue(df: pd.DataFrame) -> pd.DataFrame:
    """依產銷出貨日排隊吃產能，逐張累加。

    使用者口徑：「產能的計算方式，就產銷出貨日順序開始加總」。
    也就是同一個廠、同一個月裡，出貨日早的先吃產能，累計到超過月上限，
    後面那些才算超出 —— 而不是整個月加總後把所有工單一律標成超。
    這樣看得出來是「排到第幾張開始塞不下」，要拉單也知道拉哪幾張。

    不吃產能的：寶橋標已完工／取消的、產銷回覆庫存或外購（不用生產）的。
    排序：產銷出貨日 → 最終齊料日 → 工單號（後兩個只是讓順序穩定，不會跳動）。
    在資料層算而不是在頁面算，是因為產能是實體的：畫面上篩掉幾張工單，
    產線的負荷不會跟著變少，數字不該跟著篩選條件跑。
    """
    if df.empty:
        return df
    far = date(2099, 12, 31)
    qty = [0 if (done or not need) else int(q)
           for done, need, q in zip(df["產能·已完工"], df["訂單·需生產"], df["訂單·數量"])]
    order = sorted(
        range(len(df)),
        key=lambda i: (df["工單·加工廠"].iat[i], df["月份·歸屬"].iat[i],
                       df["鏈·目標出貨日"].iat[i] or far,
                       df["料況·最終齊料日"].iat[i] or far,
                       str(df["工單·工單號"].iat[i])))
    seq = [0] * len(df)
    cum = [0] * len(df)
    run, n, key = 0, 0, None
    for i in order:
        k = (df["工單·加工廠"].iat[i], df["月份·歸屬"].iat[i])
        if k != key:
            run, n, key = 0, 0, k
        run += qty[i]
        n += 1
        seq[i], cum[i] = n, run
    caps = [int(CAPACITY.get(f, CAPACITY["其他"])) for f in df["工單·加工廠"]]
    df = df.copy()
    df["產能·計入量"] = qty
    df["產能·排隊序"] = seq
    df["產能·累計"] = cum
    df["產能·月上限"] = caps
    df["產能·超出量"] = [max(0, c - p) for c, p in zip(cum, caps)]
    df["產能·吃到超出"] = [c > p for c, p in zip(cum, caps)]
    return df
