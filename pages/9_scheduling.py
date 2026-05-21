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

STAGE_ORDER  = ["組裝", "測試", "包裝", "其他", "委外"]
COLOR_STAGE  = {"組裝":"#1d4ed8","測試":"#7c3aed","包裝":"#0891b2","其他":"#64748b","委外":"#d97706"}
COLOR_STATUS = {"生產中":"#16a34a","待開工":"#f59e0b","已完工":"#94a3b8","已發料":"#0891b2"}

STAGE_MAP = {
    "組裝":"組裝","組裝前製製程":"組裝","組裝2":"組裝","代工前製製程":"組裝","代工":"組裝",
    "測試":"測試","SWTS":"測試",
    "包裝":"包裝","包裝線":"包裝",
    "FW燒錄":"其他","點膠":"其他","其他":"其他",
}

# 「指定完工」不列入 STATUS_MAP → 工單明細讀取時直接整筆排除
STATUS_MAP = {
    "已完工":"已完工","生產中":"生產中","已生產":"生產中",
    "已發料":"已發料","未完工":"待開工","未完工前站":"待開工",
}

LINE_MAP = {
    "測量線":"測試站","0001-威力生產線":"威力生產線","0003-零件線":"零件線",
    "0005-包裝線":"包裝線","0004-倉庫線":"倉庫線","0002-代工線":"代工線",
    "release-待發料":"待發料",
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
    # H欄(index 7)=預計開工 → 開工
    # I欄(index 8)=預計完工 → 完工
    # M欄(index 12)=狀態碼  → 排除「指定完工」整筆
    if "狀態碼" in wo.columns:
        wo = wo[wo["狀態碼"].astype(str).str.strip() != "指定完工"].copy()

    wo["開工"] = pd.to_datetime(wo.iloc[:, 7], errors="coerce").dt.date   # H欄
    wo["完工"] = pd.to_datetime(wo.iloc[:, 8], errors="coerce").dt.date   # I欄
    wo["類型"] = wo["廠商名稱"].apply(
        lambda x: "委外" if pd.notna(x) and str(x).strip() not in ["", "nan"] else "廠內"
    )
    wo["狀態_wo"] = wo["狀態碼"].map(STATUS_MAP).fillna("待開工")

    wo_keep = ["製令編號", "品名", "產品品號", "預計產量", "已生產量", "未生產量",
               "開工", "完工", "類型", "狀態_wo", "廠商名稱"]
    wo_base = wo[[c for c in wo_keep if c in wo.columns]].copy()
    wo_base = wo_base.rename(columns={"品名": "產品", "預計產量": "數量"})

    # ── 廠內進度 ──────────────────────────────────────────────────────────────
    # A欄(index 0)=製令編號  → JOIN key
    # G欄(index 6)=製程名稱  → 工序 mapping
    # H欄(index 7)=製令狀態  → 工序狀態
    # I欄(index 8)=批量狀態  → 直接保留顯示
    prog["工序"]   = prog.iloc[:, 6].map(STAGE_MAP).fillna("其他")   # G欄 製程名稱
    prog["工序狀態"] = prog.iloc[:, 7].map(STATUS_MAP).fillna("待開工") # H欄 製令狀態
    # I欄 批量狀態（index 8）
    batch_col = prog.columns[8] if len(prog.columns) > 8 else None
    prog["批量狀態"] = prog.iloc[:, 8].astype(str).str.strip() if batch_col else ""

    prog["產線"]   = prog["生產線"].map(LINE_MAP).fillna(
        prog["生產線"].astype(str).str.strip()) if "生產線" in prog.columns else "未知"

    prog_keep = ["製令編號", "工序", "批量狀態", "工序狀態", "產線",
                 "預計產量", "派工數量", "未完工數量", "已完工數量"]
    prog_base = prog[[c for c in prog_keep if c in prog.columns]].copy()
    prog_base = prog_base.rename(columns={
        "未完工數量": "未生產量_prog",
        "已完工數量": "已生產量_prog",
        "預計產量":   "數量_prog",
    })

    # ── JOIN：廠內進度（左表）← 工單明細（右表） ──────────────────────────
    merged = prog_base.merge(
        wo_base[["製令編號", "產品", "產品品號", "數量", "已生產量", "未生產量",
                 "開工", "完工", "類型", "廠商名稱"]],
        on="製令編號", how="left"
    )
    # 以工序狀態為主；開工完工來自工單明細
    merged["狀態"] = merged["工序狀態"]
    merged["已生產量"] = pd.to_numeric(
        merged.get("已生產量_prog", merged.get("已生產量", 0)), errors="coerce").fillna(0)
    merged["未生產量"] = pd.to_numeric(
        merged.get("未生產量_prog", merged.get("未生產量", 0)), errors="coerce").fillna(0)

    merged = merged.dropna(subset=["開工", "完工"])
    merged = merged[merged["開工"] <= merged["完工"]]
    # 出貨日 = 完工 + 5 個工作天
    merged["出貨日"] = merged["完工"].apply(add_workdays)

    # ── 委外工單（只從工單明細取） ────────────────────────────────────────────
    ow = wo_base[wo_base["類型"] == "委外"].copy()
    ow["工序"]     = "委外"
    ow["批量狀態"] = ""
    ow["工序狀態"] = ow["狀態_wo"]
    ow["狀態"]     = ow["狀態_wo"]
    ow["產線"]     = ow["廠商名稱"].fillna("未知廠商").astype(str).str.strip()
    ow = ow.dropna(subset=["開工", "完工"])
    ow = ow[ow["開工"] <= ow["完工"]]
    # 出貨日 = 完工 + 5 個工作天
    ow["出貨日"] = ow["完工"].apply(add_workdays)

    # ── 合併廠內 + 委外 ───────────────────────────────────────────────────────
    cols = ["製令編號", "產品", "類型", "工序", "批量狀態", "產線",
            "數量", "已生產量", "未生產量", "開工", "完工", "出貨日", "狀態"]

    for c in ["出貨日", "類型", "批量狀態"]:
        if c not in merged.columns:
            merged[c] = ""

    final_inner = merged[[c for c in cols if c in merged.columns]].copy()
    final_outer = ow[[c for c in cols if c in ow.columns]].copy()
    final = pd.concat([final_inner, final_outer], ignore_index=True)
    final["UPH"]      = 10
    final["優先順序"] = 99
    final["數量"]     = pd.to_numeric(final["數量"],     errors="coerce").fillna(0)
    final["已生產量"] = pd.to_numeric(final["已生產量"], errors="coerce").fillna(0)
    final["未生產量"] = pd.to_numeric(final["未生產量"], errors="coerce").fillna(0)
    final = final.sort_values("開工").reset_index(drop=True)
    return final

# ═══════════════════════════════════════════════════════════════════════════════
# 上傳區
# ═══════════════════════════════════════════════════════════════════════════════
st.markdown("---")
u1, u2, u3 = st.columns([2, 2, 1])
with u1:
    f_wo   = st.file_uploader("① 工單明細.xlsx", type=["xlsx"], key="f_wo")
with u2:
    f_prog = st.file_uploader("② 廠內進度.xlsx", type=["xlsx"], key="f_prog")
with u3:
    st.markdown("<br>", unsafe_allow_html=True)
    load_btn = st.button("載入", type="primary", disabled=not (f_wo and f_prog))

if load_btn and f_wo and f_prog:
    with st.spinner("讀取並合併中..."):
        st.session_state.wo_data = parse_files(f_wo.read(), f_prog.read())
    st.success(
        f"載入完成：{len(st.session_state.wo_data):,} 筆工序記錄，"
        f"{st.session_state.wo_data['製令編號'].nunique():,} 張工單"
    )

REQUIRED_COLS = {"製令編號", "產品", "類型", "工序", "批量狀態",
                 "產線", "數量", "UPH", "開工", "完工", "狀態", "優先順序"}

if "wo_data" not in st.session_state or not REQUIRED_COLS.issubset(st.session_state.wo_data.columns):
    st.session_state.wo_data = pd.DataFrame([
        dict(製令編號="5140-20260501001", 產品="IGS-9122GP",  類型="廠內", 工序="組裝", 批量狀態="待進站",
             產線="威力生產線", 數量=100, 已生產量=60,  未生產量=40,  UPH=12,
             開工=date(2026,5,1), 完工=date(2026,5,4), 出貨日=date(2026,5,10), 狀態="生產中", 優先順序=1),
        dict(製令編號="5140-20260501001", 產品="IGS-9122GP",  類型="廠內", 工序="測試", 批量狀態="待進站",
             產線="組-1線",    數量=100, 已生產量=0,   未生產量=100, UPH=20,
             開工=date(2026,5,5), 完工=date(2026,5,6), 出貨日=date(2026,5,10), 狀態="待開工", 優先順序=1),
        dict(製令編號="5140-20260501001", 產品="IGS-9122GP",  類型="廠內", 工序="包裝", 批量狀態="待進站",
             產線="包裝線",    數量=100, 已生產量=0,   未生產量=100, UPH=30,
             開工=date(2026,5,7), 完工=date(2026,5,8), 出貨日=date(2026,5,10), 狀態="待開工", 優先順序=1),
        dict(製令編號="MO02-20260501001", 產品="機殼-A型",   類型="委外", 工序="委外", 批量狀態="",
             產線="唐佑",      數量=500, 已生產量=200, 未生產量=300, UPH=50,
             開工=date(2026,5,1), 完工=date(2026,5,10),出貨日=date(2026,5,12), 狀態="生產中", 優先順序=2),
    ])

df = st.session_state.wo_data.copy()
df["開工_dt"] = pd.to_datetime(df["開工"])
df["完工_dt"] = pd.to_datetime(df["完工"])

# ── 篩選列 ──────────────────────────────────────────────────────────────────
fc1, fc2, fc3, fc4 = st.columns([3, 2, 2, 2])
with fc1:
    min_d = df["開工_dt"].min().date() if not df.empty else date(2026, 1, 1)
    max_d = df["完工_dt"].max().date() if not df.empty else date(2026, 12, 31)
    dr = st.date_input("日期區間", value=(min_d, max_d))
with fc2:
    sel_type  = st.selectbox("類型", ["全部", "廠內", "委外"])
with fc3:
    sel_stage = st.selectbox("工序", ["全部"] + STAGE_ORDER)
with fc4:
    sel_state = st.selectbox("狀態", ["全部", "待開工", "已發料", "生產中", "已完工"])

dff = df.copy()
if isinstance(dr, (list, tuple)) and len(dr) == 2:
    dff = dff[(dff["開工_dt"] >= pd.to_datetime(dr[0])) & (dff["完工_dt"] <= pd.to_datetime(dr[1]))]
if sel_type  != "全部": dff = dff[dff["類型"]  == sel_type]
if sel_stage != "全部": dff = dff[dff["工序"]  == sel_stage]
if sel_state != "全部": dff = dff[dff["狀態"]  == sel_state]

# ── KPI ──────────────────────────────────────────────────────────────────────
m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("工單數",     dff["製令編號"].nunique())
m2.metric("廠內",       dff[dff["類型"] == "廠內"]["製令編號"].nunique())
m3.metric("委外",       dff[dff["類型"] == "委外"]["製令編號"].nunique())
m4.metric("生產中工序", len(dff[dff["狀態"] == "生產中"]))
m5.metric("待開工工序", len(dff[dff["狀態"].isin(["待開工", "已發料"])]))
st.markdown("---")

# ═══════════════════════════════════════════════════════════════════════════════
tab1, tab2, tab3, tab4 = st.tabs(["📅 甘特圖", "📊 產線稼動率", "🔢 優先序管理", "🧮 預計完工試算"])

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
            y_axis   = st.radio("Y 軸",   ["產線", "工序"], horizontal=True)
            color_by = st.radio("顏色", ["工序", "狀態"], horizontal=True)

        cmap = COLOR_STAGE if color_by == "工序" else COLOR_STATUS
        hover_extra = {"產品": True, "類型": True, "工序": True, "數量": True,
                       "批量狀態": True, "狀態": True}
        if "出貨日" in gantt_df.columns:
            hover_extra["出貨日"] = True

        fig = px.timeline(
            gantt_df, x_start="開工_dt", x_end="完工_dt",
            y=y_axis, color=color_by, color_discrete_map=cmap,
            text="製令編號",
            hover_data=hover_extra,
            category_orders={"工序": STAGE_ORDER},
        )
        fig.update_traces(textposition="inside", insidetextanchor="middle",
                          textfont=dict(size=9, color="white"))
        n_y = gantt_df[y_axis].nunique()
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

# ── Tab2 稼動率 ──────────────────────────────────────────────────────────────
with tab2:
    c1, c2 = st.columns([1, 3])
    with c1:
        daily_cap = st.number_input("每日產能（PCS/線）", min_value=1, max_value=99999,
                                    value=200, step=10)
        work_days = max((dr[1] - dr[0]).days + 1, 1) if isinstance(dr, (list, tuple)) and len(dr) == 2 else 20
        avail     = daily_cap * work_days
        st.metric("區間天數",   f"{work_days} 天")
        st.metric("每線總產能", f"{avail:,} PCS")
    with c2:
        active = dff[~dff["狀態"].isin(["已完工"])].copy()
        if active.empty:
            st.info("無進行中工序。")
        else:
            active["計畫產量"] = pd.to_numeric(active["數量"], errors="coerce").fillna(0)
            load = active.groupby(["產線", "工序"])["計畫產量"].sum().reset_index()
            lt   = active.groupby("產線")["計畫產量"].sum().reset_index()
            lt["稼動率%"] = (lt["計畫產量"] / avail * 100).round(1)

            fig2 = px.bar(load, x="產線", y="計畫產量", color="工序",
                          color_discrete_map=COLOR_STAGE, barmode="stack",
                          labels={"計畫產量": "計畫產量 (PCS)"})
            fig2.add_hline(y=avail, line_dash="dash", line_color="#ef4444",
                           annotation_text=f"可用上限 {avail:,} PCS")
            fig2.update_layout(height=300, margin=dict(l=10, r=10, t=20, b=10),
                                paper_bgcolor="white", plot_bgcolor="#f8fafc",
                                yaxis=dict(gridcolor="#e2e8f0", title="PCS"),
                                legend=dict(orientation="h", yanchor="bottom", y=1.02))
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
    st.caption("可直接修改優先順序（數字越小越優先），按「套用」後更新。")
    _want = ["製令編號", "產品", "類型", "數量", "已生產量", "未生產量",
             "開工", "完工", "出貨日", "狀態", "優先順序"]
    _have = [c for c in _want if c in dff.columns]
    wo_view = (
        dff[~dff["狀態"].isin(["已完工"])]
        .drop_duplicates(subset=["製令編號"])
        [_have]
        .sort_values("優先順序")
        .copy()
    )
    edited = st.data_editor(
        wo_view,
        column_config={
            "優先順序": st.column_config.NumberColumn("優先順序", min_value=1, max_value=999, step=1),
            **{c: st.column_config.TextColumn(disabled=True)
               for c in ["製令編號", "產品", "類型", "狀態"] if c in _have},
            **{c: st.column_config.NumberColumn(disabled=True)
               for c in ["數量", "已生產量", "未生產量"] if c in _have},
            **{c: st.column_config.DateColumn(disabled=True)
               for c in ["開工", "完工", "出貨日"] if c in _have},
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

    st.markdown("**依開工日排序 — 完整工序清單**")
    show = ["製令編號", "產品", "類型", "工序", "批量狀態", "產線",
            "數量", "已生產量", "未生產量", "開工", "完工", "出貨日", "狀態"]
    show = [c for c in show if c in dff.columns]
    sorted_df = dff.sort_values("開工_dt")[show]

    def st_type(v):  return "background-color:#eff6ff" if v == "廠內" else "background-color:#fffbeb"
    def st_stage(v):
        c = {"組裝": "#dbeafe", "測試": "#ede9fe", "包裝": "#cffafe",
             "委外": "#fef3c7", "其他": "#f1f5f9"}.get(v, "")
        return f"background-color:{c}" if c else ""

    st.dataframe(
        sorted_df.style.map(st_type, subset=["類型"]).map(st_stage, subset=["工序"]),
        use_container_width=True, hide_index=True
    )

# ── Tab4 預計完工試算 ─────────────────────────────────────────────────────────
with tab4:
    st.caption("依 數量 ÷ UPH 推算所需工時，自動計算試算完工日並標示是否延遲。")
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
            hrs  = r["數量"] / max(r["UPH"], 1)
            est  = add_wd(r["開工"], hrs, daily_h, skip_wkend)
            diff = (pd.Timestamp(est) - pd.Timestamp(r["完工"])).days
            row  = {
                "製令編號": r["製令編號"], "產品": r["產品"], "類型": r["類型"],
                "工序": r["工序"], "數量": r["數量"],
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
