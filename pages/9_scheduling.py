import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import date, timedelta
import io, sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from utils.shared import inject_css, render_header, render_sidebar

st.set_page_config(page_title="排程系統", page_icon="🗓", layout="wide")
inject_css()
render_header(title="排程系統", subtitle="Production Scheduling System", badge="生管 PC")
render_sidebar()

COLOR_STAGE  = {"組裝":"#1d4ed8","測試":"#7c3aed","包裝":"#0891b2","其他":"#64748b","委外":"#d97706"}
COLOR_STATUS = {"生產中":"#16a34a","待開工":"#f59e0b","已完工":"#94a3b8","已發料":"#0891b2"}

# G欄(製程名稱) → 大類（僅供甘特圖配色，不影響顯示）
STAGE_MAP = {
    "組裝":"組裝","組裝前製製程":"組裝","組裝2":"組裝","代工前製製程":"組裝","代工":"組裝",
    "測試":"測試","SWTS":"測試",
    "包裝":"包裝","包裝線":"包裝",
    "FW燒錄":"其他","點膠":"其他","其他":"其他",
}

# 「指定完工」不列入 → 工單明細讀取時整筆排除
STATUS_MAP = {
    "已完工":"已完工","生產中":"生產中","已生產":"生產中",
    "已發料":"已發料","未完工":"待開工","未完工前站":"待開工",
}

def add_workdays(start, n=5):
    """完工日 + n 個工作天（跳過週六日）"""
    cur = pd.Timestamp(start)
    count = 0
    while count < n:
        cur += timedelta(days=1)
        if cur.weekday() < 5:
            count += 1
    return cur.date()

# ═══════════════════════════════════════════════════════════════════════════════
# 解析函數
# ═══════════════════════════════════════════════════════════════════════════════
def parse_files(bytes_wo, bytes_prog):
    wo   = pd.read_excel(io.BytesIO(bytes_wo))
    prog = pd.read_excel(io.BytesIO(bytes_prog))
    wo.columns   = wo.columns.str.strip()
    prog.columns = prog.columns.str.strip()

    # ── 工單明細 ──────────────────────────────────────────────────────────────
    # D欄(index 3)=預計產量, E欄(index 4)=已生產量, F欄(index 5)=已領套數
    # G欄(index 6)=未生產量, H欄(index 7)=預計開工, I欄(index 8)=預計完工
    # M欄(index 12)=狀態碼 → 排除「指定完工」
    if "狀態碼" in wo.columns:
        wo = wo[wo["狀態碼"].astype(str).str.strip() != "指定完工"].copy()

    wo["開工"] = pd.to_datetime(wo.iloc[:, 7], errors="coerce").dt.date   # H欄
    wo["完工"] = pd.to_datetime(wo.iloc[:, 8], errors="coerce").dt.date   # I欄
    wo["類型"] = wo["廠商名稱"].apply(
        lambda x: "委外" if pd.notna(x) and str(x).strip() not in ["", "nan"] else "廠內"
    )
    wo["狀態_wo"] = wo["狀態碼"].map(STATUS_MAP).fillna("待開工")

    wo_keep = ["製令編號", "品名", "產品品號", "預計產量", "已生產量", "已領套數",
               "未生產量", "開工", "完工", "類型", "狀態_wo", "廠商名稱"]
    wo_base = wo[[c for c in wo_keep if c in wo.columns]].copy()
    wo_base = wo_base.rename(columns={"品名": "產品"})

    # ── 廠內進度原始欄位（供選取工單後展開用） ───────────────────────────────
    _raw_cols = ["製令編號", "急料", "品號",
                 "製程代號", "製程名稱", "製令狀態", "批量狀態", "工序",
                 "預計產量", "數量", "包裝數量", "單位"]
    prog_raw = prog[[c for c in _raw_cols if c in prog.columns]].copy()
    prog_raw["製令編號"] = prog_raw["製令編號"].astype(str).str.strip()  # 確保值無空白

    # ── 廠內進度 ──────────────────────────────────────────────────────────────
    # A欄(index 0)=製令編號, G欄(index 6)=製程名稱, H欄(index 7)=製令狀態, I欄(index 8)=批量狀態
    prog["工序"]    = prog.iloc[:, 6].fillna("").astype(str).str.strip()   # G欄 原值顯示
    prog["工序_類"] = prog.iloc[:, 6].map(STAGE_MAP).fillna("其他")        # G欄 → 配色分類
    prog["工序狀態"] = prog.iloc[:, 7].map(STATUS_MAP).fillna("待開工")    # H欄
    prog["批量狀態"] = prog.iloc[:, 8].astype(str).str.strip() if len(prog.columns) > 8 else ""  # I欄
    # G欄空白的列直接排除
    prog = prog[prog["工序"].str.len() > 0]

    prog_keep = ["製令編號", "工序", "工序_類", "批量狀態", "工序狀態"]
    prog_base = prog[[c for c in prog_keep if c in prog.columns]].copy()

    # ── JOIN：廠內進度（左表）← 工單明細（右表） ──────────────────────────
    # 預計產量/已生產量/已領套數/未生產量 全部取工單明細（D/E/F/G欄）
    wo_join_cols = ["製令編號", "產品", "產品品號", "預計產量", "已生產量", "已領套數",
                    "未生產量", "開工", "完工", "類型", "廠商名稱"]
    merged = prog_base.merge(
        wo_base[[c for c in wo_join_cols if c in wo_base.columns]],
        on="製令編號", how="left"
    )
    merged["狀態"]     = merged["工序狀態"]
    merged["已生產量"] = pd.to_numeric(merged["已生產量"], errors="coerce").fillna(0)
    merged["未生產量"] = pd.to_numeric(merged["未生產量"], errors="coerce").fillna(0)

    merged = merged.dropna(subset=["開工", "完工"])
    merged = merged[merged["開工"] <= merged["完工"]]
    merged["出貨日"] = merged["完工"].apply(add_workdays)   # 完工 + 5 工作天
    merged["齊料日"] = ""

    # ── 委外工單（只從工單明細取） ────────────────────────────────────────────
    ow = wo_base[wo_base["類型"] == "委外"].copy()
    ow["工序"]     = "委外"
    ow["工序_類"]  = "委外"
    ow["批量狀態"] = ""
    ow["狀態"]     = ow["狀態_wo"]
    ow = ow.dropna(subset=["開工", "完工"])
    ow = ow[ow["開工"] <= ow["完工"]]
    ow["出貨日"] = ow["完工"].apply(add_workdays)
    ow["齊料日"] = ""

    # ── 合併廠內 + 委外 ───────────────────────────────────────────────────────
    cols = ["製令編號", "產品", "類型", "工序", "工序_類", "批量狀態",
            "預計產量", "已生產量", "已領套數", "未生產量",
            "開工", "完工", "出貨日", "齊料日", "狀態"]

    for c in ["出貨日", "齊料日", "類型", "批量狀態", "工序_類", "已領套數"]:
        if c not in merged.columns:
            merged[c] = ""

    final_inner = merged[[c for c in cols if c in merged.columns]].copy()
    final_outer = ow[[c for c in cols if c in ow.columns]].copy()
    final = pd.concat([final_inner, final_outer], ignore_index=True)
    final["UPH"]      = 10
    final["優先順序"] = 99
    for col in ["預計產量", "已生產量", "已領套數", "未生產量"]:
        final[col] = pd.to_numeric(final.get(col, 0), errors="coerce").fillna(0)
    final = final.sort_values("開工").reset_index(drop=True)
    return final, wo_base, prog_raw   # 同時回傳工單明細+廠內進度原始資料


def read_ship_dates(bytes_ship):
    """
    從出貨日.xlsx 的「彙總」工作表讀取出貨日資訊
    C欄(index 2) = 製令編號，V欄(index 21) = 對應/出貨組（文字原封不動）
    """
    df = pd.read_excel(io.BytesIO(bytes_ship), sheet_name=1, header=2)
    wo_col   = df.iloc[:, 2]    # C欄 = 工單號碼
    ship_col = df.iloc[:, 21]   # V欄 = 對應/出貨組

    mapping = {}
    for wo, ship in zip(wo_col, ship_col):
        wo_str = str(wo).strip()
        if not wo_str or wo_str in ("nan", "None", ""):
            continue
        if pd.isna(ship):
            continue
        # datetime → 日期字串；其他文字原封不動
        if hasattr(ship, "strftime"):
            ship_str = ship.strftime("%Y-%m-%d")
        else:
            ship_str = str(ship).strip()
        if ship_str:
            mapping[wo_str] = ship_str
    return mapping   # {製令編號: 出貨日文字}


def read_qiliao_dates(bytes_supply):
    """
    從供需表(分倉).xlsx 計算齊料日
      G欄(index 6)  = 到料日（datetime）
      J欄(index 9)  = 差異（負數 = 缺料）
      L欄(index 11) = 工單號碼

    對每張工單，取所有缺料物料（差異 < 0）中到料日最晚的日期 → 齊料日
    """
    import datetime as _dt
    df = pd.read_excel(io.BytesIO(bytes_supply), header=0)

    tmp = pd.DataFrame({
        "工單":  df.iloc[:, 11],   # L欄 = 工單號碼
        "到料日": df.iloc[:, 6],   # G欄 = 到料日
        "差異":  df.iloc[:, 9],    # J欄 = 差異（負 = 缺料）
    })

    # 篩選條件：工單欄有值 + G欄是日期型別 + 差異 < 0
    tmp = tmp[tmp["工單"].notna()]
    tmp["工單"] = tmp["工單"].astype(str).str.strip()
    tmp = tmp[~tmp["工單"].isin(["", "nan", "None"])]
    tmp = tmp[tmp["到料日"].apply(
        lambda v: isinstance(v, (_dt.datetime, _dt.date, pd.Timestamp))
    )]
    tmp["差異"] = pd.to_numeric(tmp["差異"], errors="coerce").fillna(0)
    tmp = tmp[tmp["差異"] < 0]

    if tmp.empty:
        return {}

    tmp["到料日"] = pd.to_datetime(tmp["到料日"])
    latest = tmp.groupby("工單")["到料日"].max()
    return {wo: dt.strftime("%Y-%m-%d") for wo, dt in latest.items()}


# ═══════════════════════════════════════════════════════════════════════════════
# 上傳區
# ═══════════════════════════════════════════════════════════════════════════════
st.markdown("---")
u1, u2, u3, u4, u5 = st.columns([2, 2, 2, 2, 1])
with u1:
    f_wo   = st.file_uploader("① 工單明細.xlsx",  type=["xlsx"], key="f_wo")
with u2:
    f_prog = st.file_uploader("② 廠內進度.xlsx",  type=["xlsx"], key="f_prog")
with u3:
    f_ship = st.file_uploader("③ 出貨日.xlsx（選填）", type=["xlsx"], key="f_ship")
with u4:
    f_qiliao = st.file_uploader("④ 供需表.xlsx（齊料日）", type=["xlsx"], key="f_qiliao")
with u5:
    st.markdown("<br>", unsafe_allow_html=True)
    load_btn = st.button("載入", type="primary", disabled=not (f_wo and f_prog))

if load_btn and f_wo and f_prog:
    with st.spinner("讀取並合併中..."):
        _result, _wo_all, _prog_raw = parse_files(f_wo.read(), f_prog.read())

        # ── 出貨日.xlsx：V欄原文覆寫出貨日 ──────────────────────────────────
        if f_ship:
            ship_map = read_ship_dates(f_ship.read())
            if ship_map:
                mapped = _result["製令編號"].astype(str).str.strip().map(ship_map)
                _result["出貨日"] = mapped.where(mapped.notna(), _result["出貨日"].astype(str))

        # ── 供需表.xlsx：計算齊料日（缺料物料中到料日最晚者） ──────────────
        if f_qiliao:
            qiliao_map = read_qiliao_dates(f_qiliao.read())
            if qiliao_map:
                mapped_q = _result["製令編號"].astype(str).str.strip().map(qiliao_map)
                _result["齊料日"] = mapped_q.where(mapped_q.notna(), _result["齊料日"])

        st.session_state.wo_data   = _result
        st.session_state.wo_all    = _wo_all
        st.session_state.prog_raw  = _prog_raw
    _tags = []
    if f_ship:   _tags.append("出貨日")
    if f_qiliao: _tags.append("齊料日")
    st.success(
        f"載入完成：{len(st.session_state.wo_data):,} 筆工序記錄，"
        f"{st.session_state.wo_data['製令編號'].nunique():,} 張工單"
        + (f"（已套用：{'、'.join(_tags)}）" if _tags else "")
    )

REQUIRED_COLS = {"製令編號", "產品", "類型", "工序", "工序_類", "批量狀態",
                 "預計產量", "已領套數", "UPH", "開工", "完工", "狀態", "優先順序"}

if "wo_data" not in st.session_state or not REQUIRED_COLS.issubset(st.session_state.wo_data.columns):
    st.session_state.wo_data = pd.DataFrame([
        dict(製令編號="5140-20260501001", 產品="IGS-9122GP", 類型="廠內",
             工序="組裝前製製程", 工序_類="組裝", 批量狀態="待進站",
             預計產量=100, 已生產量=60, 已領套數=80, 未生產量=40, UPH=12,
             開工=date(2026,5,1), 完工=date(2026,5,4), 出貨日=date(2026,5,9), 齊料日="",
             狀態="生產中", 優先順序=1),
        dict(製令編號="5140-20260501001", 產品="IGS-9122GP", 類型="廠內",
             工序="測試", 工序_類="測試", 批量狀態="待進站",
             預計產量=100, 已生產量=0, 已領套數=0, 未生產量=100, UPH=20,
             開工=date(2026,5,5), 完工=date(2026,5,6), 出貨日=date(2026,5,13), 齊料日="",
             狀態="待開工", 優先順序=1),
        dict(製令編號="5140-20260501001", 產品="IGS-9122GP", 類型="廠內",
             工序="包裝", 工序_類="包裝", 批量狀態="待進站",
             預計產量=100, 已生產量=0, 已領套數=0, 未生產量=100, UPH=30,
             開工=date(2026,5,7), 完工=date(2026,5,8), 出貨日=date(2026,5,15), 齊料日="",
             狀態="待開工", 優先順序=1),
        dict(製令編號="MO02-20260501001", 產品="機殼-A型", 類型="委外",
             工序="委外", 工序_類="委外", 批量狀態="",
             預計產量=500, 已生產量=200, 已領套數=200, 未生產量=300, UPH=50,
             開工=date(2026,5,1), 完工=date(2026,5,10), 出貨日=date(2026,5,17), 齊料日="",
             狀態="生產中", 優先順序=2),
    ])

df = st.session_state.wo_data.copy()
df["開工_dt"] = pd.to_datetime(df["開工"])
df["完工_dt"] = pd.to_datetime(df["完工"])

# ── 篩選列 ──────────────────────────────────────────────────────────────────
fc1, fc2, fc3, fc4 = st.columns([3, 2, 2, 2])
with fc1:
    min_d = df["開工_dt"].min().date() if not df.empty else date(2026, 1, 1)
    max_d = df["開工_dt"].max().date() if not df.empty else date(2026, 12, 31)
    dr = st.date_input("開工日區間", value=(min_d, max_d))
with fc2:
    sel_type  = st.selectbox("類型", ["全部", "廠內", "委外"])
with fc3:
    stage_opts = ["全部"] + sorted(df["工序"].dropna().unique().tolist())
    sel_stage  = st.selectbox("工序", stage_opts)
with fc4:
    sel_state = st.selectbox("狀態", ["全部", "待開工", "已發料", "生產中", "已完工"])

dff = df.copy()
if isinstance(dr, (list, tuple)) and len(dr) == 2:
    dff = dff[(dff["開工_dt"] >= pd.to_datetime(dr[0])) & (dff["開工_dt"] <= pd.to_datetime(dr[1]))]
if sel_type  != "全部": dff = dff[dff["類型"] == sel_type]
if sel_stage != "全部": dff = dff[dff["工序"] == sel_stage]
if sel_state != "全部": dff = dff[dff["狀態"] == sel_state]

# ── KPI ──────────────────────────────────────────────────────────────────────
m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("工單數",     dff["製令編號"].nunique())
m2.metric("廠內",       dff[dff["類型"] == "廠內"]["製令編號"].nunique())
m3.metric("委外",       dff[dff["類型"] == "委外"]["製令編號"].nunique())
m4.metric("生產中工序", len(dff[dff["狀態"] == "生產中"]))
m5.metric("待開工工序", len(dff[dff["狀態"].isin(["待開工", "已發料"])]))
st.markdown("---")

# ═══════════════════════════════════════════════════════════════════════════════
tab1, tab2, tab3, tab4 = st.tabs(["📅 甘特圖", "📊 工序稼動率", "🔢 優先序管理", "🧮 預計完工試算"])

# ── Tab1 甘特圖 ──────────────────────────────────────────────────────────────
with tab1:
    if dff.empty:
        st.warning("目前篩選條件下無資料。")
    else:
        MAX_G = 300
        gantt_df = dff.sort_values("開工_dt").head(MAX_G)
        if len(dff) > MAX_G:
            st.info(f"資料較多，甘特圖顯示前 {MAX_G} 筆（依開工日）。")

        cl, cr = st.columns([3, 1])
        with cr:
            color_by = st.radio("顏色", ["工序", "狀態"], horizontal=True)

        color_col = "工序_類" if color_by == "工序" else "狀態"
        cmap      = COLOR_STAGE if color_by == "工序" else COLOR_STATUS
        hover_extra = {"產品": True, "類型": True, "工序": True,
                       "預計產量": True, "批量狀態": True, "狀態": True}
        if "出貨日" in gantt_df.columns:
            hover_extra["出貨日"] = True

        fig = px.timeline(
            gantt_df, x_start="開工_dt", x_end="完工_dt",
            y="工序", color=color_col, color_discrete_map=cmap,
            text="製令編號", hover_data=hover_extra,
        )
        fig.update_traces(textposition="inside", insidetextanchor="middle",
                          textfont=dict(size=9, color="white"))
        n_y = gantt_df["工序"].nunique()
        fig.update_layout(
            height=max(400, n_y * 28),
            margin=dict(l=10, r=10, t=30, b=10),
            paper_bgcolor="white", plot_bgcolor="#f8fafc",
            yaxis=dict(autorange="reversed", gridcolor="#e2e8f0"),
            xaxis=dict(gridcolor="#e2e8f0"),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, x=1, xanchor="right"),
        )
        today_str = date.today().isoformat()
        fig.add_shape(type="line", x0=today_str, x1=today_str, y0=0, y1=1,
                      yref="paper", line=dict(color="#ef4444", width=2, dash="dash"))
        fig.add_annotation(x=today_str, y=1, yref="paper", text="今天",
                           showarrow=False, font=dict(color="#ef4444", size=12),
                           xanchor="left", yanchor="bottom")
        with cl:
            st.plotly_chart(fig, use_container_width=True)

# ── Tab2 工序稼動率 ───────────────────────────────────────────────────────────
with tab2:
    c1, c2 = st.columns([1, 3])
    with c1:
        daily_cap = st.number_input("每日產能（PCS/工序）", min_value=1, max_value=99999,
                                    value=200, step=10)
        work_days = max((dr[1] - dr[0]).days + 1, 1) if isinstance(dr, (list, tuple)) and len(dr) == 2 else 20
        avail     = daily_cap * work_days
        st.metric("區間天數",     f"{work_days} 天")
        st.metric("每工序總產能", f"{avail:,} PCS")
    with c2:
        active = dff[~dff["狀態"].isin(["已完工"])].copy()
        if active.empty:
            st.info("無進行中工序。")
        else:
            active["計畫產量"] = pd.to_numeric(active["預計產量"], errors="coerce").fillna(0)
            load = active.groupby("工序")["計畫產量"].sum().reset_index()
            lt   = load.copy()
            lt["稼動率%"] = (lt["計畫產量"] / avail * 100).round(1)

            fig2 = px.bar(load, x="工序", y="計畫產量", color="工序",
                          color_discrete_map=COLOR_STAGE,
                          labels={"計畫產量": "計畫產量 (PCS)"},
                          text_auto=True)
            fig2.add_hline(y=avail, line_dash="dash", line_color="#ef4444",
                           annotation_text=f"可用上限 {avail:,} PCS")
            fig2.update_layout(height=300, margin=dict(l=10, r=10, t=20, b=10),
                                paper_bgcolor="white", plot_bgcolor="#f8fafc",
                                yaxis=dict(gridcolor="#e2e8f0", title="PCS"),
                                showlegend=False)
            st.plotly_chart(fig2, use_container_width=True)

            def cr(v):
                if v >= 90: return "background-color:#fee2e2;color:#dc2626;font-weight:bold"
                if v >= 70: return "background-color:#fef9c3;color:#92400e"
                return "background-color:#dcfce7;color:#15803d"
            st.dataframe(
                lt.rename(columns={"計畫產量": "計畫產量 (PCS)"})
                  .style.map(cr, subset=["稼動率%"]),
                use_container_width=True, hide_index=True
            )

# ── Tab3 優先序管理 ──────────────────────────────────────────────────────────
with tab3:
    # ── 快速查詢列 ───────────────────────────────────────────────────────────
    sq1, sq2 = st.columns([4, 1])
    with sq1:
        search_input = st.text_input("貼上工單號碼查詢（可貼多筆，以逗號或換行分隔）",
                                     placeholder="例：5142-20260417001, 5142-20260427002",
                                     label_visibility="visible")
    with sq2:
        st.markdown("<br>", unsafe_allow_html=True)
        search_btn = st.button("🔍 查詢", type="primary")

    if search_btn and search_input.strip():
        import re
        query_nos = [s.strip() for s in re.split(r"[,\n\r；，]+", search_input) if s.strip()]

        # ① 先查合併後的工序明細（廠內進度 JOIN 工單明細，含 -rw01 衍生編號）
        hit = df[df["製令編號"].apply(
            lambda x: any(str(x) == p or str(x).startswith(p + "-") for p in query_nos)
        )].copy()

        if not hit.empty:
            show_q = ["製令編號", "產品", "類型", "工序", "批量狀態",
                      "預計產量", "已生產量", "已領套數", "未生產量",
                      "開工", "完工", "出貨日", "齊料日", "狀態"]
            show_q = [c for c in show_q if c in hit.columns]
            st.success(f"找到 {hit['製令編號'].nunique()} 張工單，共 {len(hit)} 筆工序記錄")
            def _st(v): return "background-color:#eff6ff" if v == "廠內" else "background-color:#fffbeb"
            st.dataframe(hit.sort_values("開工_dt")[show_q].style.map(_st, subset=["類型"]),
                         use_container_width=True, hide_index=True)
        else:
            # ② 找不到時回查工單明細原始資料
            wo_all = st.session_state.get("wo_all", pd.DataFrame())
            hit2 = wo_all[wo_all["製令編號"].apply(
                lambda x: any(str(x) == p or str(x).startswith(p + "-") for p in query_nos)
            )] if not wo_all.empty else pd.DataFrame()
            if hit2.empty:
                st.warning(f"查無符合的工單：{', '.join(query_nos)}")
            else:
                show_q2 = ["製令編號", "產品", "類型", "預計產量", "已生產量",
                           "已領套數", "未生產量", "開工", "完工", "狀態_wo"]
                show_q2 = [c for c in show_q2 if c in hit2.columns]
                st.info(f"此工單不在廠內進度中，以下顯示工單明細原始資料")
                st.dataframe(hit2[show_q2].rename(columns={"狀態_wo": "狀態"}),
                             use_container_width=True, hide_index=True)
        st.markdown("---")

    st.caption("可直接修改優先順序（數字越小越優先）；勾選工單號碼可展開工序明細。按「套用」後更新。")
    _want = ["製令編號", "產品", "類型", "預計產量", "已生產量", "已領套數", "未生產量",
             "開工", "完工", "出貨日", "齊料日", "狀態", "優先順序"]
    _have = [c for c in _want if c in dff.columns]
    wo_view = (
        dff[~dff["狀態"].isin(["已完工"])]
        .drop_duplicates(subset=["製令編號"])
        [_have]
        .sort_values("優先順序")
        .copy()
    )
    wo_view.insert(0, "選取", False)   # 最左欄加 checkbox

    edited = st.data_editor(
        wo_view,
        column_config={
            "選取":   st.column_config.CheckboxColumn("選取", default=False),
            "優先順序": st.column_config.NumberColumn("優先順序", min_value=1, max_value=999, step=1),
            **{c: st.column_config.TextColumn(disabled=True)
               for c in ["製令編號", "產品", "類型", "狀態"] if c in _have},
            **{c: st.column_config.NumberColumn(disabled=True)
               for c in ["預計產量", "已生產量", "已領套數", "未生產量"] if c in _have},
            **{c: st.column_config.DateColumn(disabled=True)
               for c in ["開工", "完工", "出貨日"] if c in _have},
            "齊料日": st.column_config.TextColumn("齊料日", disabled=True),
        },
        hide_index=True, use_container_width=True, key="priority_editor"
    )
    if st.button("套用排序", type="primary"):
        for _, row in edited.iterrows():
            st.session_state.wo_data.loc[
                st.session_state.wo_data["製令編號"] == row["製令編號"], "優先順序"
            ] = row["優先順序"]
        st.success("排序已更新！")
        st.rerun()

    # ── 只有勾選的工單才顯示廠內進度工序明細 ────────────────────────────────
    selected_wos = [str(s).strip() for s in edited[edited["選取"] == True]["製令編號"].tolist()]

    def prefix_match(series, prefixes):
        """比對完整編號，或以 prefix + '-' 開頭的衍生工單（如 -rw01）"""
        return series.apply(
            lambda x: any(str(x) == p or str(x).startswith(p + "-") for p in prefixes)
        )

    if selected_wos:
        st.markdown(f"**工序明細 — {', '.join(selected_wos)}**")
        prog_raw = st.session_state.get("prog_raw", pd.DataFrame())

        # ① 優先從廠內進度原始資料取（含 -rw01 等衍生編號）
        if not prog_raw.empty and "製令編號" in prog_raw.columns:
            detail_df = prog_raw[prefix_match(prog_raw["製令編號"], selected_wos)].reset_index(drop=True)
        else:
            detail_df = pd.DataFrame()

        # ② 查不到 → 從工單明細取（委外工單或廠內進度無此工單）
        if detail_df.empty:
            wo_all = st.session_state.get("wo_all", pd.DataFrame())
            if not wo_all.empty and "製令編號" in wo_all.columns:
                _show = ["製令編號", "產品", "類型", "預計產量", "已生產量",
                         "已領套數", "未生產量", "開工", "完工", "狀態_wo"]
                _show = [c for c in _show if c in wo_all.columns]
                detail_df = (wo_all[prefix_match(wo_all["製令編號"], selected_wos)][_show]
                             .rename(columns={"狀態_wo": "狀態"})
                             .reset_index(drop=True))
                if not detail_df.empty:
                    st.caption("此工單不在廠內進度中，顯示工單明細資料。")

        if detail_df.empty:
            st.info("查無此工單的工序資料。")
        else:
            st.dataframe(detail_df, use_container_width=True, hide_index=True)

# ── Tab4 預計完工試算 ─────────────────────────────────────────────────────────
with tab4:
    st.caption("依 預計產量 ÷ UPH 推算所需工時，自動計算試算完工日並標示是否延遲。")
    c1, c2 = st.columns([1, 3])
    with c1:
        daily_h    = st.number_input("每日工作小時", 1, 24, 8, key="calc_h")
        skip_wkend = st.checkbox("跳過週六日", value=True)

    def add_wd(start, hrs, dh, skip):
        rem = hrs; cur = pd.Timestamp(start)
        while rem > 0:
            cur += timedelta(days=1)
            if skip and cur.weekday() >= 5: continue
            rem -= dh
        return cur.date()

    pending = dff[~dff["狀態"].isin(["已完工"])].copy()
    if pending.empty:
        st.info("無待開工/生產中工序。")
    else:
        rows = []
        for _, r in pending.iterrows():
            hrs  = r["預計產量"] / max(r["UPH"], 1)
            est  = add_wd(r["開工"], hrs, daily_h, skip_wkend)
            diff = (pd.Timestamp(est) - pd.Timestamp(r["完工"])).days
            row  = {
                "製令編號": r["製令編號"], "產品": r["產品"], "類型": r["類型"],
                "工序": r["工序"], "預計產量": r["預計產量"],
                "計畫工時(hr)": round(hrs, 1),
                "計畫完工": r["完工"], "試算完工": est, "差異(天)": diff,
            }
            if "出貨日" in r: row["出貨日"] = r["出貨日"]
            rows.append(row)
        calc_df = pd.DataFrame(rows)

        def sd(v):
            if v > 0: return "background-color:#fee2e2;color:#dc2626;font-weight:bold"
            if v < 0: return "background-color:#dcfce7;color:#15803d"
            return ""
        with c2:
            st.dataframe(calc_df.style.map(sd, subset=["差異(天)"]),
                         use_container_width=True, hide_index=True)
        late = calc_df[calc_df["差異(天)"] > 0]
        if not late.empty:
            st.warning(f"⚠️ **{late['製令編號'].nunique()}** 張工單共 **{len(late)}** 道工序預計延遲。")
        else:
            st.success("✅ 所有工序依 UPH 試算均可在計畫日內完工。")
