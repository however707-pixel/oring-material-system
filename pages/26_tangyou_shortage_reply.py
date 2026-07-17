# -*- coding: utf-8 -*-
"""唐佑缺料回信：H2O缺料明細 P欄(E.T.A)依庫存/委外競爭/進貨配料逐列改寫，其餘內容不動。"""
import datetime as dt
import glob
import os
import sys
import tempfile

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from utils.shared import ensure_calamine, inject_css, render_header, render_sidebar
from utils import tangyou_reply as ty

st.set_page_config(page_title="唐佑缺料回信", page_icon="✉️", layout="wide",
                   initial_sidebar_state="expanded")
ensure_calamine()
inject_css()
render_header(
    title="唐佑缺料回信",
    subtitle="Tang You Shortage Reply · H2O缺料明細 P欄(E.T.A) 自動回覆調撥日期",
    badge="PMC",
)
render_sidebar()

DESKTOP = os.path.join(os.path.expanduser("~"), "Desktop")

ST_CSS = {
    ty.ST_STOCK:     "background-color:#f0fdf4;color:#15803d;",
    ty.ST_INCOMING:  "background-color:#dbeafe;color:#1d4ed8;",
    ty.ST_OVERDUE:   "background-color:#fef9c3;color:#854d0e;font-weight:bold;",
    ty.ST_SHORT:     "background-color:#fee2e2;color:#991b1b;font-weight:bold;",
    ty.ST_NOT_FOUND: "background-color:#fee2e2;color:#991b1b;font-weight:bold;",
    ty.ST_NOQTY:     "background-color:#f1f5f9;color:#64748b;",
    ty.ST_FUTURE:    "background-color:#f1f5f9;color:#64748b;",
}
ST_ORDER = [ty.ST_SHORT, ty.ST_NOT_FOUND, ty.ST_OVERDUE, ty.ST_INCOMING,
            ty.ST_STOCK, ty.ST_NOQTY, ty.ST_FUTURE]

with st.expander("📖 回信日期規則（逐列配料）", expanded=False):
    st.markdown("""
**供給池** ＝ 我司四倉（電子/機構/半成品/成品倉）現有可用量 ＋ 供需表「預計進貨」
（我司四倉＋唐佑倉；直送唐佑倉的進貨保留給唐佑，不給其他委外分）。

**先扣競爭需求**：其他委外代工倉（修研/華盈/國智、秦宏、貫崑、佑泰、正文）各自
以自身庫存＋自身進貨掃時間軸，吃不到的量＝要向我司調撥的競爭需求。
所有需求（含唐佑各列，需求量= **N欄不足數量**、需求日= B欄預計齊料日）
依 **需求日早者先給料**（同日委外優先，取保守）。

| 唐佑該列補齊方式 | P欄 (E.T.A 預計進料日) |
|---|---|
| 全由現有庫存補齊 | **基準日 + 2 個工作天** |
| 需等「預計進貨」，以最後補齊那筆為準 | **該進貨日 + 4 個工作天** |
| 補齊靠的進貨已逾期 | 基準日 + 4 個工作天，並標示提醒 |
| 供給不足（被更早需求先分走）/ 供需表查無品號 | **P欄不修改**，標紅請人工確認 |
| **B欄齊料日超過基準日+2週** | **P欄不修改**（只回覆近兩週內的缺料） |

- 同一品號的不同工單列可能得到不同日期（早齊料日的列先分到庫存）。
- 工作天僅跳過週六、週日（國定假日不扣）。
- 品號比對：H2O缺料明細 **J欄(客戶件號)** ↔ 供需表 **品號**。
- 寫回時只改 H2O 工作表 P 欄，其餘欄位、格式、工作表全部保持原樣。
""")

# ═══ 1. 檔案來源 ═══════════════════════════════════════════════════════════
st.markdown("#### 1️⃣ 選擇 H2O 缺料明細")
mode = st.radio("H2O 檔案來源", ["📂 NAS/本機檔案（直接就地修改）", "⬆️ 上傳檔案（產出下載檔）"],
                horizontal=True, label_visibility="collapsed")

h2o_path, h2o_upload = None, None
if mode.startswith("📂"):
    try:
        default = ty.latest_h2o_file() or ""
    except OSError:
        default = ""
    src_hint = "NAS @唐佑專屬缺料表 最新檔"
    if not default:                              # NAS 連不上 → 桌面備援
        cands = sorted(glob.glob(os.path.join(DESKTOP, "*H2O缺料明細*.xls*")),
                       key=os.path.getmtime, reverse=True)
        default = cands[0] if cands else ""
        src_hint = "連不上 NAS，改抓桌面最新檔"
    h2o_path = st.text_input(f"檔案路徑（預設：{src_hint}）", value=default)
    if h2o_path and not os.path.exists(h2o_path):
        st.error("找不到檔案，請確認路徑")
        h2o_path = None
    elif h2o_path:
        mt = dt.datetime.fromtimestamp(os.path.getmtime(h2o_path))
        st.caption(f"檔案更新時間：{mt:%Y/%m/%d %H:%M}")
else:
    h2o_upload = st.file_uploader("上傳 H2O缺料明細 (.xls)", type=["xls", "xlsx"])

# ═══ 2. 供需表(分倉) ══════════════════════════════════════════════════════
st.markdown("#### 2️⃣ 供需表(分倉)　`每日檔，自動抓最新日期`")
lrp_src, lrp_label = None, ""
try:
    nas_file = ty.latest_lrp_file()
except OSError:
    nas_file = None
if nas_file:
    lrp_src, lrp_label = nas_file, os.path.basename(nas_file)
    st.success(f"✅ NAS 最新檔：**{lrp_label}**")
else:
    st.warning("⚠️ 連不上 NAS，請手動上傳 供需表(分倉)-YYYYMMDD.xlsx")
    up = st.file_uploader("上傳 供需表(分倉)", type=["xlsx"])
    if up is not None:
        lrp_src, lrp_label = up, up.name

# ═══ 3. 基準日 ═══════════════════════════════════════════════════════════
st.markdown("#### 3️⃣ 基準日（「當天日期」）與時間窗")
col_a, col_b = st.columns([1, 1])
base_date = col_a.date_input("基準日", value=dt.date.today(), format="YYYY/MM/DD")
horizon = col_b.number_input("只修改 B欄齊料日在基準日+幾天內的列", min_value=1,
                             max_value=365, value=14, step=7)


@st.cache_data(show_spinner="讀取供需表(分倉)…")
def load_lrp_cached(path: str, mtime: float) -> pd.DataFrame:
    return ty.parse_lrp_daily(path)


def read_h2o(src) -> pd.DataFrame:
    raw = pd.read_excel(src, sheet_name="H2O", header=None, engine="calamine")
    hdr = raw.iloc[0].astype(str)
    if "E.T.A" not in hdr[15] or ("客戶件號" not in hdr[9] and "Customer" not in hdr[9]):
        raise ValueError("表頭不符：J欄應為 Customer P/N(客戶件號)、P欄應為 E.T.A，"
                         "請確認上傳的是 H2O缺料明細")
    df = raw.iloc[1:].copy()
    out = pd.DataFrame({
        "sheet_row": df.index + 1,                       # 工作表列號（表頭=列1）
        "序號": df[0],
        "工令單號": df[4].fillna("").astype(str).str.strip(),
        "品號": df[9].fillna("").astype(str).str.strip(),
        "品名": df[10].fillna("").astype(str).str.strip(),
        "齊料日": pd.to_datetime(df[1], errors="coerce"),
        "需求N": pd.to_numeric(df[13], errors="coerce").fillna(0),
        "原P": pd.to_datetime(df[15], errors="coerce"),
    })
    return out[out["品號"] != ""].reset_index(drop=True)


# ═══ 試算 ════════════════════════════════════════════════════════════════
ready = (h2o_path or h2o_upload is not None) and lrp_src is not None
if st.button("🧮 試算調撥日期", type="primary", disabled=not ready):
    print(f"[tangyou] {dt.datetime.now():%H:%M:%S} 試算開始 "
          f"src={'upload' if h2o_upload else h2o_path}", flush=True)
    try:
        with st.spinner("⏳ 讀取缺料明細與供需表、配料計算中（第一次約需 10 秒）…"):
            h2o = read_h2o(h2o_path or h2o_upload)
            if isinstance(lrp_src, str):
                lrp = load_lrp_cached(lrp_src, os.path.getmtime(lrp_src))
            else:
                lrp = ty.parse_lrp_daily(lrp_src)
            res = ty.compute_allocation(lrp, h2o, base_date, horizon_days=int(horizon))
        print(f"[tangyou] {dt.datetime.now():%H:%M:%S} 試算完成 "
              f"{len(res)}列/改寫{int(res['新P日期'].notna().sum())}列", flush=True)
        st.session_state["ty_calc"] = {
            "res": res, "base": base_date, "horizon": int(horizon), "lrp_label": lrp_label,
            "path": h2o_path,
            "upload": (h2o_upload.name, h2o_upload.getvalue()) if h2o_upload else None,
        }
        st.session_state.pop("ty_written", None)
        st.session_state.pop("ty_dl", None)
    except Exception as e:
        import traceback
        print(f"[tangyou] 試算失敗: {traceback.format_exc()}", flush=True)
        st.session_state.pop("ty_calc", None)
        st.error(f"試算失敗：{e}")

calc = st.session_state.get("ty_calc")
if calc:
    res: pd.DataFrame = calc["res"]
    n_write = int(res["新P日期"].notna().sum())
    st.markdown("---")
    st.caption(f"供需表：{calc['lrp_label']}　·　基準日：{calc['base']:%Y/%m/%d}"
               f"　·　只改齊料日 +{calc['horizon']} 天內")
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("缺料明細列數", f"{len(res):,}")
    c2.metric("庫存滿足 (+2工作天)", f"{(res['狀態'] == ty.ST_STOCK).sum():,}")
    c3.metric("等進貨 (+4工作天)", f"{res['狀態'].isin([ty.ST_INCOMING, ty.ST_OVERDUE]).sum():,}")
    c4.metric("需人工確認 (不改)", f"{res['狀態'].isin(ty.NO_CHANGE).sum():,}")
    c5.metric(f"超過{calc['horizon']}天 (不改)", f"{(res['狀態'] == ty.ST_FUTURE).sum():,}")
    c6.metric("將改寫 P 欄列數", f"{n_write:,}")

    only_manual = st.toggle("只看需人工確認（P欄不改）的列")
    show = res[res["狀態"].isin(ty.NO_CHANGE)] if only_manual else res
    show = show.copy()
    show["_o"] = show["狀態"].map({s: i for i, s in enumerate(ST_ORDER)})
    show = show.sort_values(["_o", "品號", "sheet_row"]).drop(columns="_o")
    show = show[["sheet_row", "序號", "工令單號", "品號", "品名", "需求N",
                 "齊料日", "原P", "狀態", "新P日期", "我司庫存", "委外競爭", "說明"]]
    _d = lambda v: f"{v:%Y/%m/%d}" if pd.notna(v) else "—"
    st.dataframe(
        show.style.map(lambda v: ST_CSS.get(v, ""), subset=["狀態"])
            .format({"需求N": "{:,.0f}", "我司庫存": "{:,.0f}", "委外競爭": "{:,.0f}",
                     "齊料日": _d, "原P": _d,
                     "新P日期": lambda v: f"{v:%Y/%m/%d}" if pd.notna(v) else "— 不改"}),
        use_container_width=True, height=460, hide_index=True,
        column_config={"sheet_row": st.column_config.NumberColumn("Excel列", format="%d")})

    # ═══ 寫回 ═══════════════════════════════════════════════════════════
    st.markdown("#### 4️⃣ 寫回 Excel（只改 P 欄）")
    new_dates = {int(r["sheet_row"]): r["新P日期"] for _, r in res.iterrows()
                 if pd.notna(r["新P日期"])}
    if calc["path"]:
        st.caption(f"目標檔案：{calc['path']}（直接就地修改，寫回前請先關閉 Excel）")
        if st.button("✍️ 寫回 P 欄", type="primary"):
            try:
                with st.spinner("Excel 寫入中…"):
                    r = ty.write_p_column(calc["path"], new_dates)
                st.session_state["ty_written"] = (
                    f"✅ 完成：{r['rows_updated']:,} / {r['rows_total']:,} 列已更新 → {calc['path']}")
            except Exception as e:
                st.session_state["ty_written"] = f"❌ 寫回失敗：{e}"
    else:
        name, blob = calc["upload"]
        if st.button("✍️ 產生回覆檔", type="primary"):
            tmp = os.path.join(tempfile.mkdtemp(prefix="ty_reply_"), name)
            try:
                with open(tmp, "wb") as f:
                    f.write(blob)
                with st.spinner("Excel 寫入中…"):
                    r = ty.write_p_column(tmp, new_dates)
                with open(tmp, "rb") as f:
                    st.session_state["ty_dl"] = (name, f.read())
                st.session_state["ty_written"] = (
                    f"✅ 完成：{r['rows_updated']:,} / {r['rows_total']:,} 列已更新，請下載")
            except Exception as e:
                st.session_state["ty_written"] = f"❌ 產生失敗：{e}"
        if st.session_state.get("ty_dl"):
            dl_name, dl_bytes = st.session_state["ty_dl"]
            st.download_button("⬇️ 下載回覆檔", data=dl_bytes, file_name=dl_name,
                               mime="application/vnd.ms-excel")

    msg = st.session_state.get("ty_written")
    if msg:
        (st.success if msg.startswith("✅") else st.error)(msg)
elif not ready:
    st.info("請先備妥 H2O缺料明細 與 供需表(分倉)，再按「試算調撥日期」。")
