# -*- coding: utf-8 -*-
"""
全工單料況追蹤 — 完全比照使用者現行「V2→V3→V4」缺料總表流程的程式化實作

資料來源（鼎新 ERP 匯出，header 在第 4 列；樣式 XML 不合規須用 calamine）：
  MOCR19  生產進度表     → 工單主檔（開工/完工/狀態/廠商）＋ 子製令配對池
  LRPMR05 品號供需明細表 → 時間軸（庫存＋需求）與供給池（備註=採購/委外單號）
  PURR28  採購預計進貨表 → y齊 交期回覆（備註欄），供 CF/TBC 判定

流程對照（原 xlsm：供需表(分倉)-自動V2 / 供需表分倉整理-V3 / 缺料總表V4）：
  V2  交期回覆＝以採購單號從 PURR28 備註帶回 y齊 註記
  V3  清洗：刪 9*（保留 9-71*）、刪品名含「需燒錄」（不含「不需」）、刪小計/合計
  V4  庫別→庫群組；時間軸只含庫存＋需求（預計領用/異動領料/預計銷售），
      未來供給不進結存；雙缺口（總缺K=全品號、工單缺N=庫群×品號）；
      在途倉（*-在途倉）庫存＝貨仍在途、非實際在庫 → 不計入工單缺N（總缺K照計）；
      供給池＝備註前綴 3310/3320/5220/5240/5260 之供給列，CF（y齊）優先再依日期；
      半成品(5-*)與需燒錄清單改配子製令（MOCR19 未生產量，依完工日序）；
      包材/標籤（品號前綴 1901~1907）→ P/L OK；
      final status ∈ {庫存, 待調撥, CF, TBC, needPO, P/L OK, 無子製令}

與原 xlsm 的三個刻意差異（原版行為過於寬鬆/未定義）：
  1. 找不到子製令 → 獨立狀態「無子製令」（原版誤標 CF）
  2. 子製令依「完工日」順序配（原版依 ERP WO 匯出列序＝開單日）
  3. 未在對照表的庫別 → 以原代號自成一群（原版留空白群）
"""
import re

import numpy as np
import pandas as pd

ENGINE = "calamine"

# ── V4 note K→L：庫別（名稱/代號）→ 庫群組 ────────────────────────────────────
UNUSABLE = "7不能用"
WH_GROUP = {
    # 1寶橋（廠內各倉＋所有在途倉＋客供等，視為可調撥的主體庫存）
    "電子倉": "1寶橋", "R01": "1寶橋", "機構倉": "1寶橋", "R02": "1寶橋",
    "包材倉": "1寶橋", "R03": "1寶橋", "半成品倉": "1寶橋", "R04": "1寶橋",
    "成品倉": "1寶橋", "R05": "1寶橋", "生產加工倉": "1寶橋", "R06": "1寶橋",
    "呆滯料倉": "1寶橋", "R17": "1寶橋", "熱銷備庫倉": "1寶橋", "R27": "1寶橋",
    "威力-在途倉": "1寶橋", "外部可用倉": "1寶橋", "客供倉": "1寶橋",
    "唐佑-在途倉": "1寶橋", "S071": "1寶橋",
    "修研/華盈/國智-在途倉": "1寶橋", "秦宏-在途倉": "1寶橋", "S051": "1寶橋",
    "貫崑-在途倉": "1寶橋", "S081": "1寶橋", "佑泰-在途倉": "1寶橋", "S091": "1寶橋",
    "正文-在途倉": "1寶橋", "S101": "1寶橋",
    "C00": "1寶橋", "S011": "1寶橋", "S02": "4唐佑代工倉", "WM倉": "1寶橋",
    "W01": "1寶橋", "S04": "1寶橋", "R00": "1寶橋", "H03": "1寶橋",
    # 代工倉（庫存僅供該廠使用）
    "修研/華盈/國智代工倉": "3修研/華盈/國智代工倉", "S01": "3修研/華盈/國智代工倉",
    "S012": "3修研/華盈/國智代工倉", "修研/華盈/國智-專案倉": "3修研/華盈/國智代工倉",
    "唐佑代工倉": "4唐佑代工倉", "S07": "4唐佑代工倉",
    "秦宏代工倉": "5秦宏代工倉", "S05": "5秦宏代工倉",
    "貫崑代工倉": "6貫崑代工倉", "S08": "6貫崑代工倉",
    "佑泰代工倉": "6.5佑泰代工倉", "S09": "6.5佑泰代工倉",
    "正文代工倉": "6.1正文代工倉", "S10": "6.1正文代工倉",
    "114無人機": "114無人機", "U14": "114無人機",
    # 不能用（庫存不可動用）
    "待定處置倉": UNUSABLE, "R20": UNUSABLE,
    "研發倉": UNUSABLE, "R14": UNUSABLE, "RD費用倉": UNUSABLE, "Z01": UNUSABLE,
}

# 在途倉：貨仍在運送途中、非各庫群實際在庫 → 庫存不計入 庫群結餘M/工單缺N
# （總結餘J/總缺K 照計）。1寶橋在途=威力-在途倉、各代工群在途=各廠-在途倉。
# LRPMR05 庫存列的庫別多為名稱；代號（S0x1 系列）一併列入以防匯出格式改變。
TRANSIT_WH = {
    "威力-在途倉",
    "唐佑-在途倉", "S071",
    "修研/華盈/國智-在途倉", "S011",
    "秦宏-在途倉", "S051",
    "貫崑-在途倉", "S081",
    "佑泰-在途倉", "S091",
    "正文-在途倉", "S101",
}

# V4 note M 欄：需燒錄品號（不配 PO、改配子製令）
BURN_ITEMS = {
    "2116-2-XC2C32A6Q-1-0571", "2116-3-LCMXO2256-1-0202", "2116-3-LCMXO2256-1-0232",
    "2116-3-LCMXO2256-1-0282", "2116-3-LCMXO2256-1-0292", "2116-3-LCMXO2256-1-0471",
    "2116-3-LCMXO2256-1-0502", "2116-3-LCMXO2256-1-0562", "2116-3-LCMXO2256-1-0572",
    "2116-3-LCMXO2256-1-0592", "2116-3-LCMXO2256-1-0712", "2116-3-LCMXO2640-1-0251",
    "2116-3-LCMXO2640-1-0421", "2116-3-LCMXO2640-1-0431", "2116-3-LCMXO2640-1-0461",
    "2116-3-LCMXO2640-1-0471", "2116-3-LCMXO2640-1-0481", "2116-3-LCMXO2640-1-0511",
    "2116-EPM3064A-SW611", "2116-LCMXO256C-SW601", "2116-XC2C32A-SW60L",
    "2116-XC2C32A-SW60O", "2116-XC2C32A-SW60S", "2116-XC2C32A-SW60U",
    "2113-2-STM32G030-1-0011", "2113-2-STM32G030-1-0013", "2113-2-STM32G070-1-0011",
    "2113-2-STM32G070-1-0021", "2113-2-STM32G070-1-0031", "2113-2-STM32G030-1-0031",
    "2113-2-STM32G030-1-0033", "2113-2-STM32G070-1-0111", "2113-2-STM32G070-1-0121",
    "2116-XC2C32A-XX-001", "2113-2-STM32G070-1-0051", "2113-2-STM32G030-1-0023",
}

PL_PREFIXES = {"1901", "1902", "1903", "1904", "1905", "1906", "1907"}   # 包材/標籤
PO_PREFIXES = {"3310", "3320", "5220", "5240", "5260"}                   # 供給單別
DEMAND_KINDS = {"預計領用", "異動領料", "預計銷售"}                        # 進時間軸的需求
SUPPLY_KINDS = {"預計進貨", "預計生產", "預計請購", "請拋採未確認", "異動入庫"}

NEVER = pd.Timestamp("9999-09-09")


def _norm_cols(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = [re.sub(r"\s+", "", str(c)) for c in df.columns]
    return df


def _s(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip()


def _num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").fillna(0.0)


def _dt(series: pd.Series) -> pd.Series:
    ss = _s(series)
    out = pd.to_datetime(ss, format="%Y/%m/%d", errors="coerce")
    if out.notna().sum() == 0 and (ss != "").any():
        out = pd.to_datetime(ss, errors="coerce")
    return out


def report_date(raw_head: pd.DataFrame) -> str:
    for _, row in raw_head.iterrows():
        for v in row:
            m = re.search(r"製表日期[:：]\s*(\d{4}/\d{1,2}/\d{1,2})", str(v))
            if m:
                return m.group(1)
    return ""


# ═══════════════════════════════════════════════════════════════════════════
# 解析
# ═══════════════════════════════════════════════════════════════════════════
def parse_mo(src) -> pd.DataFrame:
    df = _norm_cols(pd.read_excel(src, header=3, engine=ENGINE))
    need = ["製令編號", "製令狀態", "開工日", "完工日", "產品品號", "預計產量"]
    miss = [c for c in need if c not in df.columns]
    if miss:
        raise ValueError(f"生產進度表缺少欄位 {miss}，請確認上傳的是 MOCR19 匯出檔")
    df = df[_s(df["製令編號"]) != ""].copy()
    for c in ("製令編號", "製令狀態", "產品品號", "品名", "廠商名稱",
              "訂單單號", "客戶名稱", "人員名稱"):
        if c in df.columns:
            df[c] = _s(df[c])
    for c in ("開工日", "完工日", "實開工", "實完工"):
        df[c] = _dt(df.get(c, pd.Series(index=df.index)))
    df["預計產量"] = _num(df["預計產量"])
    df["未生產量"] = _num(df.get("未生產量"))
    df.loc[df["廠商名稱"] == "", "廠商名稱"] = "廠內"
    return df.drop_duplicates(subset=["製令編號"], keep="first")


def parse_lrp(src) -> pd.DataFrame:
    """LRPMR05 → 逐列表（含庫存列，庫別以區塊回填），並附品名。"""
    df = _norm_cols(pd.read_excel(src, header=3, engine=ENGINE))
    need = ["品號", "品名", "庫別", "日期", "異動別", "異動數量", "預計結存", "備註"]
    miss = [c for c in need if c not in df.columns]
    if miss:
        raise ValueError(f"供需明細表缺少欄位 {miss}，請確認上傳的是 LRPMR05 匯出檔")

    out = pd.DataFrame({
        "品號": _s(df["品號"]), "品名": _s(df["品名"]), "庫別": _s(df["庫別"]),
        "日期str": _s(df["日期"]), "異動別": _s(df["異動別"]),
        "數量": _num(df["異動數量"]), "結存": _num(df["預計結存"]),
        "備註": _s(df["備註"]), "廠商": _s(df.get("廠商", pd.Series(index=df.index))),
    })
    # 合計列的庫別欄放品號（會污染回填）先剔除；小計列要留到回填後才刪，
    # 因為「純庫存區塊」（無交易列）的庫別名稱只存在於它的小計列
    out = out[~out["日期str"].str.startswith("合計")].copy()
    out["is_stock"] = out["日期str"].str.startswith("庫存可用量")
    # 庫存列的庫別空白 → 往下回填（同區塊交易列代號或小計列名稱）
    wh = out["庫別"].replace("", np.nan).bfill().fillna("")
    out["庫別"] = np.where(out["is_stock"], wh, out["庫別"])
    out = out[~out["日期str"].str.startswith("小計")].copy()
    out["日期"] = _dt(out["日期str"])
    # 有效列：庫存列 或 (有異動別且日期可解析)
    out = out[(out["is_stock"]) |
              ((out["異動別"] != "") & out["日期"].notna())].reset_index(drop=True)
    out = out[out["品號"] != ""].reset_index(drop=True)
    return out


_YQI_RE = re.compile(r"[齊][\s，,、/_\-：:．.]*[（(]?(\d{4}[/.\-]\d{1,2}[/.\-]\d{1,2})")
_WO_RE = re.compile(r"[A-Za-z0-9]{2,6}-20\d{9,12}")


def parse_pur(src) -> pd.DataFrame:
    """PURR28 → 採購單號(-項次) 對 備註（交期回覆）；CF=備註含 y/Y。"""
    df = _norm_cols(pd.read_excel(src, header=3, engine=ENGINE))
    need = ["採購單號", "品號", "備註"]
    miss = [c for c in need if c not in df.columns]
    if miss:
        raise ValueError(f"採購預計進貨表缺少欄位 {miss}，請確認上傳的是 PURR28 匯出檔")
    df = df[(_s(df["品號"]) != "") &
            (_s(df.get("品名", pd.Series(index=df.index))) != "小計:")].copy()
    po = pd.DataFrame({
        "採購單號": _s(df["採購單號"]), "品號": _s(df["品號"]),
        "備註": _s(df["備註"]), "採購人員": _s(df.get("採購人員", pd.Series(index=df.index))),
    })
    po["CF"] = po["備註"].str.contains("y", case=False, regex=False)
    yq = []
    for s in po["備註"]:
        m = _YQI_RE.search(s)
        yq.append(pd.to_datetime(m.group(1).replace(".", "/").replace("-", "/"),
                                 errors="coerce") if m else pd.NaT)
    po["y齊日"] = yq
    po["y齊工單"] = po["備註"].map(_WO_RE.findall)
    return po.drop_duplicates(subset=["採購單號"], keep="first")


# ═══════════════════════════════════════════════════════════════════════════
# V4 核心運算
# ═══════════════════════════════════════════════════════════════════════════
def _v3_clean(lrp: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """V3 清洗（品號層級）：刪 9*（保留 9-71*）、刪品名含需燒錄（不含不需）。"""
    name_map = dict(zip(lrp.loc[lrp["品名"] != "", "品號"],
                        lrp.loc[lrp["品名"] != "", "品名"]))
    pno = lrp["品號"]
    drop9 = pno.str.startswith("9") & ~pno.str.contains("9-71", regex=False)
    nm = pno.map(lambda p: name_map.get(p, ""))
    burn_name = nm.str.contains("需燒錄", regex=False) & ~nm.str.contains("不需", regex=False)
    return lrp[~(drop9 | burn_name)].copy(), name_map


def build_v4(mo: pd.DataFrame, lrp: pd.DataFrame, pur: pd.DataFrame):
    """回傳 (輸出表 out_df, 工單彙總 wo_df, 未對照庫別 list)。"""
    lrp, name_map = _v3_clean(lrp)

    # ── 庫群組 ────────────────────────────────────────────────────────────
    grp = lrp["庫別"].map(WH_GROUP)
    unmapped = sorted(set(lrp.loc[grp.isna() & (lrp["庫別"] != ""), "庫別"]))
    lrp["庫"] = grp.fillna(lrp["庫別"])          # 未對照 → 原代號自成一群

    # ── 時間軸（整理表）：庫存＋需求，未來供給不進結存 ─────────────────────
    tl = lrp[lrp["is_stock"] | lrp["異動別"].isin(DEMAND_KINDS)].copy()
    tl["L"] = np.where(tl["is_stock"], tl["數量"], -tl["數量"])
    tl["_d"] = tl["日期"].fillna(pd.Timestamp("1900-01-01"))
    tl.loc[tl["is_stock"], "_d"] = pd.Timestamp("1900-01-01")
    tl = tl.sort_values(["品號", "_d"], kind="mergesort").reset_index(drop=True)

    tl["J"] = tl.groupby("品號", sort=False)["L"].cumsum()          # 總結餘
    j_prev = tl["J"] - tl["L"]
    first = ~tl["品號"].duplicated()
    j_prev = j_prev.where(~first, 0.0)
    tl["K"] = np.where(tl["J"] >= 0, 0.0,
                       np.where(j_prev >= 0, tl["J"], tl["L"]))      # 總缺（本列新增）
    # 庫群結餘：在途倉庫存（貨未到）不算該群可用量 → 工單缺 N 為扣除在途後的實缺
    transit = tl["庫別"].isin(TRANSIT_WH) | tl["庫別"].str.contains("在途", regex=False)
    l_grp = tl["L"].where(~(tl["is_stock"] & transit), 0.0)
    tl["M"] = l_grp.groupby([tl["庫"], tl["品號"]], sort=False).cumsum()   # 庫群結餘
    tl["N"] = np.where(tl["M"] >= 0, 0.0, np.maximum(tl["L"], tl["M"]))  # 工單缺

    # ── 供給池 1：PO（備註前綴 3310/3320/5220/5240/5260 的供給列）────────────
    sup = lrp[lrp["異動別"].isin(SUPPLY_KINDS) &
              lrp["備註"].str[:4].isin(PO_PREFIXES) & lrp["日期"].notna()].copy()
    cf_map = dict(zip(pur["採購單號"], pur["CF"]))
    remark_map = dict(zip(pur["採購單號"], pur["備註"]))
    sup["CF"] = sup["備註"].map(cf_map).fillna(False).astype(bool)
    sup = sup.sort_values(["品號", "CF", "日期"],
                          ascending=[True, False, True], kind="mergesort")
    po_pool = {k: list(zip(g["日期"], g["數量"].astype(float), g["備註"], g["CF"]))
               for k, g in sup.groupby("品號", sort=False)}

    # ── 供給池 2：子製令（5-* 與需燒錄品號用；MOCR19 未生產量、依完工日）──────
    kids = mo[(mo["未生產量"] > 0)].copy().sort_values("完工日", kind="mergesort")
    wo_pool = {k: list(zip(g["完工日"], g["未生產量"].astype(float), g["製令編號"]))
               for k, g in kids.groupby("產品品號", sort=False)}

    # ── Pegging（依品號分組、時間軸序累計 K 缺口；指標單向前進）──────────────
    is5burn_all = tl["品號"].str.startswith("5") | tl["品號"].isin(BURN_ITEMS)
    pl_all = tl["品號"].str[:4].isin(PL_PREFIXES)
    arr_item = tl["品號"].to_numpy()
    arr_kind = tl["異動別"].to_numpy()
    arr_K = tl["K"].to_numpy()
    arr_N = tl["N"].to_numpy()
    arr_5b = is5burn_all.to_numpy()
    arr_pl = pl_all.to_numpy()

    n = len(tl)
    out_date = np.full(n, None, dtype=object)   # 料齊日
    out_ref = np.full(n, "", dtype=object)      # 對應單據
    out_st = np.full(n, "", dtype=object)       # final status

    cur_item = None
    cum_k = 0.0
    ptr = cum_sup = 0.0
    pool = []
    p_i = 0
    for i in range(n):
        it = arr_item[i]
        if it != cur_item:
            cur_item = it
            cum_k = 0.0
            pool = wo_pool.get(it, []) if arr_5b[i] else po_pool.get(it, [])
            p_i = 0
            cum_sup = 0.0
        cum_k += arr_K[i]
        if arr_kind[i] != "預計領用":
            continue
        K, N = arr_K[i], arr_N[i]
        if K >= 0 and N >= 0:
            out_st[i] = "庫存"
            continue
        if K >= 0 and N < 0:
            out_ref[i] = "待調撥"
            out_st[i] = "待調撥"
            continue
        # K < 0：走供給池補累計缺口
        need = -cum_k
        while p_i < len(pool) and cum_sup < need:
            cum_sup += pool[p_i][1]
            if cum_sup >= need:
                break
            p_i += 1
        if p_i < len(pool) and cum_sup >= need:
            d, _q, ref = pool[p_i][0], pool[p_i][1], pool[p_i][2]
            out_date[i] = d if pd.notna(d) else None
            out_ref[i] = ref
            if arr_5b[i]:
                out_st[i] = "CF"                      # 子製令視同已確認
            elif arr_pl[i]:
                out_st[i] = "P/L OK"                  # 包材/標籤不擋料
            else:
                out_st[i] = "CF" if pool[p_i][3] else "TBC"
        else:
            if arr_5b[i]:
                out_ref[i] = "找不到子製令"
                out_st[i] = "無子製令"
            else:
                out_date[i] = NEVER
                out_ref[i] = "未開單"
                out_st[i] = "needPO"

    tl["料齊日"] = out_date
    tl["對應單據"] = out_ref
    tl["final status"] = out_st

    # ── 輸出表（=V4 輸出表：只留預計領用列）─────────────────────────────────
    out_df = tl[tl["異動別"] == "預計領用"].copy()
    out_df["品名"] = out_df["品號"].map(lambda p: name_map.get(p, ""))
    out_df["包材/標籤"] = np.where(out_df["品號"].str[:4].isin(PL_PREFIXES), "Y", "")
    out_df["交期回覆"] = out_df["對應單據"].map(remark_map).fillna("")
    out_df = out_df.rename(columns={"備註": "工單", "數量": "異動數量",
                                    "K": "總缺", "N": "工單缺", "日期": "需求日"})
    out_df["料齊日"] = pd.to_datetime(out_df["料齊日"])
    out_df = out_df[["庫", "品號", "品名", "需求日", "異動別", "異動數量", "工單",
                     "工單缺", "總缺", "包材/標籤", "料齊日", "對應單據",
                     "final status", "交期回覆", "庫別"]].reset_index(drop=True)

    # ── 工單彙總（疊在輸出表上的工單層視圖）──────────────────────────────────
    buyer = {}
    for r in pur.itertuples(index=False):
        if pd.isna(r.y齊日):
            continue
        for w in r.y齊工單:
            buyer[w] = max(buyer.get(w, r.y齊日), r.y齊日)

    grp_wo = {k: g for k, g in out_df.groupby("工單", sort=False)}
    # 供需表有領用、但進度表匯出缺漏的工單 → 補一列空主檔，避免在彙總隱形
    extra = [w for w in grp_wo if w not in set(mo["製令編號"])]
    mo_iter = list(mo.itertuples(index=False))
    if extra:
        blank = pd.DataFrame({
            "製令編號": extra, "製令狀態": "（不在進度表匯出）", "產品品號": "",
            "品名": "", "預計產量": 0.0, "未生產量": 0.0, "廠商名稱": "",
            "開工日": pd.NaT, "完工日": pd.NaT, "實開工": pd.NaT, "實完工": pd.NaT,
            "訂單單號": "", "客戶名稱": "",
        })
        mo_iter += list(blank.itertuples(index=False))
    rows = []
    for r in mo_iter:
        wo = r.製令編號
        g = grp_wo.get(wo)
        cnt = {"庫存": 0, "待調撥": 0, "CF": 0, "TBC": 0, "needPO": 0,
               "P/L OK": 0, "無子製令": 0}
        ready = pd.NaT
        if g is None:
            status = "📦 無領用需求"
            n_mat = 0
        else:
            n_mat = len(g)
            for s in g["final status"]:
                cnt[s] = cnt.get(s, 0) + 1
            # 齊料日：CF/TBC 列（真缺且有單）的最大料齊日；P/L OK 不擋料
            gate = g[g["final status"].isin(["CF", "TBC"])]
            if len(gate):
                ready = gate["料齊日"].max()
            if cnt["needPO"] or cnt["無子製令"]:
                status = f"⛔ 缺料無單 {cnt['needPO'] + cnt['無子製令']} 項"
                ready = pd.NaT
            elif cnt["TBC"]:
                status = f"🕐 待確認交期 {cnt['TBC']} 項"
            elif cnt["CF"]:
                status = f"🚚 在途中 {cnt['CF']} 項"
            elif cnt["待調撥"]:
                status = f"🔁 待調撥 {cnt['待調撥']} 項"
            else:
                status = "✅ 齊料"
        delay = ""
        if pd.notna(ready) and pd.notna(r.開工日):
            delay = int((ready - r.開工日).days)
        rows.append({
            "製令編號": wo, "狀態": r.製令狀態, "產品品號": r.產品品號,
            "品名": getattr(r, "品名", ""), "預計產量": r.預計產量,
            "廠商": r.廠商名稱, "開工日": r.開工日, "完工日": r.完工日,
            "用料項數": n_mat, "庫存OK": cnt["庫存"], "待調撥": cnt["待調撥"],
            "CF在途": cnt["CF"], "TBC": cnt["TBC"],
            "needPO": cnt["needPO"] + cnt["無子製令"], "P/L": cnt["P/L OK"],
            "齊料日": ready, "齊料-開工(天)": delay,
            "採購註記齊料": buyer.get(wo, pd.NaT), "料況": status,
            "訂單單號": getattr(r, "訂單單號", ""), "客戶名稱": getattr(r, "客戶名稱", ""),
        })
    wo_df = pd.DataFrame(rows)
    return out_df, wo_df, unmapped
