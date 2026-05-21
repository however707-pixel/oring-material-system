import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import date, timedelta
import math, sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from utils.shared import inject_css, render_header, render_sidebar

st.set_page_config(page_title="排程系統", page_icon="🗓", layout="wide")
inject_css()
render_header(title="排程系統", subtitle="Production Scheduling System", badge="生管 PC")
render_sidebar()

# ═══════════════════════════════════════════════════════════════════════════════
# 示意資料  (每張工單 × 工序 = 一列)
# 廠內：組裝 → 測試 → 包裝
# 委外：一道工序
# ═══════════════════════════════════════════════════════════════════════════════
STAGE_ORDER = ["組裝", "測試", "包裝", "委外"]
COLOR_STAGE = {"組裝": "#1d4ed8", "測試": "#7c3aed", "包裝": "#0891b2", "委外": "#d97706"}
COLOR_STATUS = {"生產中": "#16a34a", "待開工": "#f59e0b", "已完工": "#94a3b8"}

if "wo_data" not in st.session_state:
    st.session_state.wo_data = pd.DataFrame([
        # 廠內 工單 A
        dict(工單號="5220-20260501001", 產品="IGS-9122GP", 類型="廠內", 工序="組裝", 產線="宣-1線", 數量=100, UPH=12, 開工=date(2026,5,1),  完工=date(2026,5,4),  狀態="已完工", 優先順序=1),
        dict(工單號="5220-20260501001", 產品="IGS-9122GP", 類型="廠內", 工序="測試", 產線="測試站A", 數量=100, UPH=20, 開工=date(2026,5,5),  完工=date(2026,5,6),  狀態="生產中", 優先順序=1),
        dict(工單號="5220-20260501001", 產品="IGS-9122GP", 類型="廠內", 工序="包裝", 產線="包裝線",  數量=100, UPH=30, 開工=date(2026,5,7),  完工=date(2026,5,8),  狀態="待開工", 優先順序=1),
        # 廠內 工單 B
        dict(工單號="5220-20260502001", 產品="IES-3080",   類型="廠內", 工序="組裝", 產線="賢-1線", 數量=200, UPH=15, 開工=date(2026,5,2),  完工=date(2026,5,7),  狀態="生產中", 優先順序=2),
        dict(工單號="5220-20260502001", 產品="IES-3080",   類型="廠內", 工序="測試", 產線="測試站B", 數量=200, UPH=20, 開工=date(2026,5,8),  完工=date(2026,5,9),  狀態="待開工", 優先順序=2),
        dict(工單號="5220-20260502001", 產品="IES-3080",   類型="廠內", 工序="包裝", 產線="包裝線",  數量=200, UPH=30, 開工=date(2026,5,10), 完工=date(2026,5,11), 狀態="待開工", 優先順序=2),
        # 廠內 工單 C
        dict(工單號="5220-20260503001", 產品="IPS-3082GC", 類型="廠內", 工序="組裝", 產線="宣-2線", 數量=400, UPH=8,  開工=date(2026,5,3),  完工=date(2026,5,12), 狀態="生產中", 優先順序=1),
        dict(工單號="5220-20260503001", 產品="IPS-3082GC", 類型="廠內", 工序="測試", 產線="測試站A", 數量=400, UPH=20, 開工=date(2026,5,13), 完工=date(2026,5,15), 狀態="待開工", 優先順序=1),
        dict(工單號="5220-20260503001", 產品="IPS-3082GC", 類型="廠內", 工序="包裝", 產線="包裝線",  數量=400, UPH=30, 開工=date(2026,5,16), 完工=date(2026,5,18), 狀態="待開工", 優先順序=1),
        # 委外 工單 D
        dict(工單號="MO02-20260501001", 產品="機殼-A型",   類型="委外", 工序="委外", 產線="唐佑",   數量=500, UPH=50, 開工=date(2026,5,1),  完工=date(2026,5,10), 狀態="生產中", 優先順序=2),
        dict(工單號="MO02-20260502001", 產品="PCBA-B型",   類型="委外", 工序="委外", 產線="國智",   數量=200, UPH=20, 開工=date(2026,5,5),  完工=date(2026,5,15), 狀態="待開工", 優先順序=3),
        dict(工單號="MO02-20260503001", 產品="背板-C型",   類型="委外", 工序="委外", 產線="唐佑",   數量=100, UPH=25, 開工=date(2026,4,25), 完工=date(2026,5,3),  狀態="已完工", 優先順序=0),
    ])

df = st.session_state.wo_data.copy()
df["開工_dt"] = pd.to_datetime(df["開工"])
df["完工_dt"] = pd.to_datetime(df["完工"])

# ── 篩選列 ──────────────────────────────────────────────────────────────────
st.markdown("---")
fc1, fc2, fc3, fc4 = st.columns([3, 2, 2, 2])
with fc1:
    dr = st.date_input("日期區間", value=(date(2026,4,25), date(2026,5,20)))
with fc2:
    sel_type  = st.selectbox("類型", ["全部","廠內","委外"])
with fc3:
    sel_stage = st.selectbox("工序", ["全部","組裝","測試","包裝","委外"])
with fc4:
    sel_state = st.selectbox("狀態", ["全部","待開工","生產中","已完工"])

dff = df.copy()
if isinstance(dr,(list,tuple)) and len(dr)==2:
    dff = dff[(dff["開工_dt"]>=pd.to_datetime(dr[0])) & (dff["完工_dt"]<=pd.to_datetime(dr[1]))]
if sel_type  != "全部": dff = dff[dff["類型"]==sel_type]
if sel_stage != "全部": dff = dff[dff["工序"]==sel_stage]
if sel_state != "全部": dff = dff[dff["狀態"]==sel_state]

# ── KPI ──────────────────────────────────────────────────────────────────────
wo_total = dff["工單號"].nunique()
m1,m2,m3,m4,m5 = st.columns(5)
m1.metric("工單數（去重）", wo_total)
m2.metric("廠內工單",  dff[dff["類型"]=="廠內"]["工單號"].nunique())
m3.metric("委外工單",  dff[dff["類型"]=="委外"]["工單號"].nunique())
m4.metric("進行中工序", len(dff[dff["狀態"]=="生產中"]))
m5.metric("待開工工序", len(dff[dff["狀態"]=="待開工"]))
st.markdown("---")

# ═══════════════════════════════════════════════════════════════════════════════
# 四個 Tab
# ═══════════════════════════════════════════════════════════════════════════════
tab1, tab2, tab3, tab4 = st.tabs(["📅 甘特圖", "📊 產線稼動率", "🔢 優先序管理", "🧮 預計完工試算"])

# ────────────────────────────────────────────────────────────────────────────
# Tab 1：甘特圖（按工序分色，Y 軸為產線）
# ────────────────────────────────────────────────────────────────────────────
with tab1:
    if dff.empty:
        st.warning("目前篩選條件下無資料。")
    else:
        # 廠內 / 委外 分開畫，再合併顯示
        col_l, col_r = st.columns([3,1])
        with col_r:
            y_axis = st.radio("Y 軸", ["產線","工序"], horizontal=True)
            color_by = st.radio("顏色", ["工序","狀態"], horizontal=True)

        color_map = COLOR_STAGE if color_by=="工序" else COLOR_STATUS

        fig = px.timeline(
            dff.sort_values("開工_dt"),
            x_start="開工_dt", x_end="完工_dt",
            y=y_axis, color=color_by,
            color_discrete_map=color_map,
            text="工單號",
            hover_data={"產品":True,"類型":True,"工序":True,"數量":True,"狀態":True},
            category_orders={"工序": STAGE_ORDER},
        )
        fig.update_traces(textposition="inside", insidetextanchor="middle",
                          textfont=dict(size=10, color="white"))
        fig.update_layout(
            height=400, margin=dict(l=10,r=10,t=30,b=10),
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
        with col_l:
            st.plotly_chart(fig, use_container_width=True)

# ────────────────────────────────────────────────────────────────────────────
# Tab 2：產線稼動率（廠內/委外分開）
# ────────────────────────────────────────────────────────────────────────────
with tab2:
    c1, c2 = st.columns([1, 3])
    with c1:
        daily_hours = st.number_input("每日可用工時（hr）", 1, 24, 8)
        if isinstance(dr,(list,tuple)) and len(dr)==2:
            work_days = max((dr[1]-dr[0]).days+1, 1)
        else:
            work_days = 10
        st.metric("區間天數", f"{work_days} 天")
        st.metric("每線可用工時", f"{daily_hours*work_days} hr")

    with c2:
        active = dff[dff["狀態"]!="已完工"].copy()
        if active.empty:
            st.info("無進行中/待開工工序。")
        else:
            active["計畫工時"] = (active["數量"] / active["UPH"]).round(1)
            load = active.groupby(["產線","工序"])["計畫工時"].sum().reset_index()
            line_total = active.groupby("產線")["計畫工時"].sum().reset_index()
            avail = daily_hours * work_days
            line_total["稼動率%"] = (line_total["計畫工時"] / avail * 100).round(1)

            fig2 = px.bar(load, x="產線", y="計畫工時", color="工序",
                          color_discrete_map=COLOR_STAGE, barmode="stack")
            fig2.add_hline(y=avail, line_dash="dash", line_color="#ef4444",
                           annotation_text="可用工時上限")
            fig2.update_layout(height=280, margin=dict(l=10,r=10,t=20,b=10),
                               paper_bgcolor="white", plot_bgcolor="#f8fafc",
                               yaxis=dict(gridcolor="#e2e8f0"),
                               legend=dict(orientation="h", yanchor="bottom", y=1.02))
            st.plotly_chart(fig2, use_container_width=True)

            def color_rate(v):
                if v >= 90: return "background-color:#fee2e2;color:#dc2626;font-weight:bold"
                if v >= 70: return "background-color:#fef9c3;color:#92400e"
                return "background-color:#dcfce7;color:#15803d"
            st.dataframe(line_total.style.map(color_rate, subset=["稼動率%"]),
                         use_container_width=True, hide_index=True)

# ────────────────────────────────────────────────────────────────────────────
# Tab 3：優先序管理
# ────────────────────────────────────────────────────────────────────────────
with tab3:
    st.caption("修改優先順序後按「套用」，甘特圖會同步更新。")

    # 以工單為單位顯示（取第一道工序代表）
    wo_view = (
        dff[dff["狀態"]!="已完工"]
        .drop_duplicates(subset=["工單號"])
        [["工單號","產品","類型","數量","狀態","優先順序"]]
        .copy()
    )

    edited = st.data_editor(
        wo_view,
        column_config={
            "優先順序": st.column_config.NumberColumn("優先順序", min_value=1, max_value=99, step=1),
            "工單號": st.column_config.TextColumn(disabled=True),
            "產品":   st.column_config.TextColumn(disabled=True),
            "類型":   st.column_config.TextColumn(disabled=True),
            "數量":   st.column_config.NumberColumn(disabled=True),
            "狀態":   st.column_config.TextColumn(disabled=True),
        },
        hide_index=True, use_container_width=True, key="priority_editor"
    )

    if st.button("套用排序", type="primary"):
        for _, row in edited.iterrows():
            mask = st.session_state.wo_data["工單號"] == row["工單號"]
            st.session_state.wo_data.loc[mask, "優先順序"] = row["優先順序"]
        st.success("排序已更新！")
        st.rerun()

    st.markdown("**依優先順序 — 完整工序清單**")
    sorted_df = dff.sort_values(["優先順序","工單號","開工_dt"])[
        ["優先順序","工單號","產品","類型","工序","產線","數量","開工","完工","狀態"]
    ]
    def style_type(val):
        return "background-color:#eff6ff" if val=="廠內" else "background-color:#fffbeb"
    def style_stage(val):
        c = {"組裝":"#dbeafe","測試":"#ede9fe","包裝":"#cffafe","委外":"#fef3c7"}.get(val,"")
        return f"background-color:{c}" if c else ""
    st.dataframe(sorted_df.style.map(style_type,subset=["類型"])
                              .map(style_stage,subset=["工序"]),
                 use_container_width=True, hide_index=True)

# ────────────────────────────────────────────────────────────────────────────
# Tab 4：預計完工試算
# ────────────────────────────────────────────────────────────────────────────
with tab4:
    st.caption("依數量 ÷ UPH 推算各工序所需工時，自動計算預計完工日並標示是否延遲。")

    c1, c2 = st.columns([1,3])
    with c1:
        daily_h    = st.number_input("每日工作小時", 1, 24, 8, key="calc_h")
        skip_wkend = st.checkbox("跳過週六日", value=True)

    def add_workdays(start, hours_needed, daily_h, skip_wkend):
        remaining = hours_needed
        cur = pd.Timestamp(start)
        while remaining > 0:
            cur += timedelta(days=1)
            if skip_wkend and cur.weekday() >= 5:
                continue
            remaining -= daily_h
        return cur.date()

    pending = dff[dff["狀態"]!="已完工"].copy()
    if pending.empty:
        st.info("無待開工/生產中工序。")
    else:
        rows = []
        for _, r in pending.iterrows():
            hrs = r["數量"] / max(r["UPH"], 1)
            est = add_workdays(r["開工"], hrs, daily_h, skip_wkend)
            diff = (pd.Timestamp(est) - pd.Timestamp(r["完工"])).days
            rows.append({
                "工單號":r["工單號"], "產品":r["產品"], "類型":r["類型"],
                "工序":r["工序"], "產線":r["產線"], "數量":r["數量"], "UPH":r["UPH"],
                "計畫工時(hr)": round(hrs,1),
                "計畫完工": r["完工"],
                "試算完工": est,
                "差異(天)": diff,
            })
        calc_df = pd.DataFrame(rows)

        def style_diff(v):
            if v > 0: return "background-color:#fee2e2;color:#dc2626;font-weight:bold"
            if v < 0: return "background-color:#dcfce7;color:#15803d"
            return ""

        with c2:
            st.dataframe(calc_df.style.map(style_diff, subset=["差異(天)"]),
                         use_container_width=True, hide_index=True)

        late = calc_df[calc_df["差異(天)"]>0]
        if not late.empty:
            st.warning(f"⚠️ 有 **{late['工單號'].nunique()}** 張工單共 **{len(late)}** 道工序預計延遲，請注意調整。")
        else:
            st.success("✅ 所有工序依 UPH 試算均可在計畫日內完工。")
