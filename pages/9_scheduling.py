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
# 示意資料
# ═══════════════════════════════════════════════════════════════════════════════
if "wo_data" not in st.session_state:
    st.session_state.wo_data = pd.DataFrame([
        dict(工單號="5220-20260501001", 產品="IGS-9122GP",    產線="宣-1線", 數量=100, UPH=12, 開工=date(2026,5,1),  完工=date(2026,5,6),  狀態="生產中", 優先順序=1),
        dict(工單號="5220-20260502001", 產品="IES-3080",      產線="宣-2線", 數量=200, UPH=15, 開工=date(2026,5,2),  完工=date(2026,5,8),  狀態="生產中", 優先順序=2),
        dict(工單號="5220-20260503001", 產品="RMC-111FB",     產線="賢-1線", 數量=50,  UPH=10, 開工=date(2026,5,5),  完工=date(2026,5,9),  狀態="待開工", 優先順序=5),
        dict(工單號="5220-20260504001", 產品="IGS-9084GP",    產線="宣-1線", 數量=80,  UPH=12, 開工=date(2026,5,7),  完工=date(2026,5,13), 狀態="待開工", 優先順序=3),
        dict(工單號="5220-20260505001", 產品="IPS-3082GC",    產線="賢-2線", 數量=400, UPH=8,  開工=date(2026,5,3),  完工=date(2026,5,12), 狀態="生產中", 優先順序=1),
        dict(工單號="5220-20260506001", 產品="TCXK-ISW",      產線="宣-2線", 數量=150, UPH=14, 開工=date(2026,5,9),  完工=date(2026,5,15), 狀態="待開工", 優先順序=4),
        dict(工單號="5220-20260507001", 產品="IGS-9122GP",    產線="賢-1線", 數量=60,  UPH=12, 開工=date(2026,5,12), 完工=date(2026,5,16), 狀態="待開工", 優先順序=6),
        dict(工單號="5220-20260408001", 產品="IES-3080",      產線="宣-1線", 數量=100, UPH=15, 開工=date(2026,4,28), 完工=date(2026,5,3),  狀態="已完工", 優先順序=0),
        dict(工單號="5220-20260409001", 產品="RES-P9242GCL",  產線="賢-2線", 數量=31,  UPH=6,  開工=date(2026,4,25), 完工=date(2026,5,2),  狀態="已完工", 優先順序=0),
    ])

df = st.session_state.wo_data.copy()
df["開工_dt"] = pd.to_datetime(df["開工"])
df["完工_dt"] = pd.to_datetime(df["完工"])

COLOR_MAP = {"生產中": "#1d4ed8", "待開工": "#f59e0b", "已完工": "#16a34a"}
PRIORITY_ICON = {1:"🔴", 2:"🔴", 3:"🟡", 4:"🟡", 5:"🟢", 6:"🟢", 0:"⚪"}

# ── 篩選列 ──────────────────────────────────────────────────────────────────
st.markdown("---")
fc1, fc2, fc3 = st.columns([3, 2, 2])
with fc1:
    dr = st.date_input("日期區間", value=(date(2026,4,25), date(2026,5,16)))
with fc2:
    lines = ["全部"] + sorted(df["產線"].unique().tolist())
    sel_line = st.selectbox("產線", lines)
with fc3:
    sel_state = st.selectbox("狀態", ["全部","待開工","生產中","已完工"])

dff = df.copy()
if isinstance(dr, (list,tuple)) and len(dr)==2:
    dff = dff[(dff["開工_dt"] >= pd.to_datetime(dr[0])) & (dff["完工_dt"] <= pd.to_datetime(dr[1]))]
if sel_line  != "全部": dff = dff[dff["產線"] == sel_line]
if sel_state != "全部": dff = dff[dff["狀態"] == sel_state]

# ── KPI ──────────────────────────────────────────────────────────────────────
m1,m2,m3,m4,m5 = st.columns(5)
m1.metric("工單總數",   len(dff))
m2.metric("待開工",     len(dff[dff["狀態"]=="待開工"]))
m3.metric("生產中",     len(dff[dff["狀態"]=="生產中"]))
m4.metric("已完工",     len(dff[dff["狀態"]=="已完工"]))
m5.metric("預計總產量", f"{dff['數量'].sum():,}")
st.markdown("---")

# ═══════════════════════════════════════════════════════════════════════════════
# 四個 Tab
# ═══════════════════════════════════════════════════════════════════════════════
tab1, tab2, tab3, tab4 = st.tabs(["📅 甘特圖", "📊 產線稼動率", "🔢 優先序管理", "🧮 預計完工試算"])

# ────────────────────────────────────────────────────────────────────────────
# Tab 1：甘特圖
# ────────────────────────────────────────────────────────────────────────────
with tab1:
    if dff.empty:
        st.warning("目前篩選條件下無工單資料。")
    else:
        fig = px.timeline(
            dff, x_start="開工_dt", x_end="完工_dt",
            y="產線", color="狀態", color_discrete_map=COLOR_MAP,
            text="工單號",
            hover_data={"產品":True,"數量":True,"UPH":True,"優先順序":True},
        )
        fig.update_traces(textposition="inside", insidetextanchor="middle",
                          textfont=dict(size=11, color="white"))
        fig.update_layout(
            height=360, margin=dict(l=10,r=10,t=30,b=10),
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
        st.plotly_chart(fig, use_container_width=True)

# ────────────────────────────────────────────────────────────────────────────
# Tab 2：產線稼動率
# ────────────────────────────────────────────────────────────────────────────
with tab2:
    c1, c2 = st.columns([1, 3])
    with c1:
        daily_hours = st.number_input("每日可用工時（小時）", min_value=1, max_value=24, value=8, step=1)
        if isinstance(dr, (list,tuple)) and len(dr)==2:
            work_days = max((dr[1]-dr[0]).days + 1, 1)
        else:
            work_days = 10
        st.metric("區間天數", f"{work_days} 天")
        total_avail = daily_hours * work_days
        st.metric("每線可用工時", f"{total_avail} hr")

    with c2:
        active = dff[dff["狀態"] != "已完工"].copy()
        if active.empty:
            st.info("篩選區間內無待開工/生產中工單。")
        else:
            active["計畫工時"] = (active["數量"] / active["UPH"]).round(1)
            load = active.groupby(["產線","狀態"])["計畫工時"].sum().reset_index()
            line_total = active.groupby("產線")["計畫工時"].sum().reset_index()
            line_total["可用工時"] = total_avail
            line_total["稼動率%"] = (line_total["計畫工時"] / total_avail * 100).round(1)

            fig2 = go.Figure()
            for state, color in COLOR_MAP.items():
                sub = load[load["狀態"]==state]
                if sub.empty: continue
                fig2.add_trace(go.Bar(name=state, x=sub["產線"], y=sub["計畫工時"],
                                      marker_color=color))
            fig2.add_trace(go.Scatter(
                x=line_total["產線"], y=[total_avail]*len(line_total),
                mode="lines+markers", name="可用工時上限",
                line=dict(color="#ef4444", dash="dash", width=2),
                marker=dict(size=8)
            ))
            fig2.update_layout(
                barmode="stack", height=300,
                margin=dict(l=10,r=10,t=20,b=10),
                paper_bgcolor="white", plot_bgcolor="#f8fafc",
                yaxis=dict(title="計畫工時 (hr)", gridcolor="#e2e8f0"),
                legend=dict(orientation="h", yanchor="bottom", y=1.02),
            )
            st.plotly_chart(fig2, use_container_width=True)

            st.markdown("**各產線稼動率**")
            rate_df = line_total[["產線","計畫工時","可用工時","稼動率%"]].copy()
            def color_rate(v):
                if v >= 90: return "background-color:#fee2e2;color:#dc2626;font-weight:bold"
                if v >= 70: return "background-color:#fef9c3;color:#92400e"
                return "background-color:#dcfce7;color:#15803d"
            st.dataframe(rate_df.style.map(color_rate, subset=["稼動率%"]),
                         use_container_width=True, hide_index=True)

# ────────────────────────────────────────────────────────────────────────────
# Tab 3：優先序管理
# ────────────────────────────────────────────────────────────────────────────
with tab3:
    st.caption("直接在表格中修改「優先順序」數字（數字越小越優先），完成後按「套用排序」。")

    edit_df = dff[dff["狀態"]!="已完工"][["工單號","產品","產線","數量","開工","完工","狀態","優先順序"]].copy()
    edited = st.data_editor(
        edit_df,
        column_config={
            "優先順序": st.column_config.NumberColumn("優先順序", min_value=1, max_value=99, step=1),
            "開工": st.column_config.DateColumn("開工"),
            "完工": st.column_config.DateColumn("完工"),
            "工單號": st.column_config.TextColumn("工單號", disabled=True),
            "產品":   st.column_config.TextColumn("產品",   disabled=True),
            "產線":   st.column_config.TextColumn("產線",   disabled=True),
            "數量":   st.column_config.NumberColumn("數量", disabled=True),
            "狀態":   st.column_config.TextColumn("狀態",   disabled=True),
        },
        hide_index=True, use_container_width=True, key="priority_editor"
    )

    if st.button("套用排序", type="primary"):
        for _, row in edited.iterrows():
            mask = st.session_state.wo_data["工單號"] == row["工單號"]
            st.session_state.wo_data.loc[mask, "優先順序"] = row["優先順序"]
            st.session_state.wo_data.loc[mask, "開工"] = row["開工"]
            st.session_state.wo_data.loc[mask, "完工"] = row["完工"]
        st.success("排序已更新！")
        st.rerun()

    st.markdown("**依優先順序排列（含已完工）**")
    sorted_df = dff.sort_values(["優先順序","開工_dt"])[["工單號","產品","產線","數量","開工","完工","狀態","優先順序"]].copy()
    sorted_df["優先"] = sorted_df["優先順序"].map(lambda x: f"{PRIORITY_ICON.get(x,'')}")
    st.dataframe(sorted_df[["優先","工單號","產品","產線","數量","開工","完工","狀態"]],
                 use_container_width=True, hide_index=True)

# ────────────────────────────────────────────────────────────────────────────
# Tab 4：預計完工日試算
# ────────────────────────────────────────────────────────────────────────────
with tab4:
    st.caption("輸入各工單的開工日與每小時產出（UPH），系統自動推算預計完工日。")

    c1, c2 = st.columns([1, 3])
    with c1:
        daily_h = st.number_input("每日工作小時", min_value=1, max_value=24, value=8, key="calc_h")
        skip_weekend = st.checkbox("跳過週六日", value=True)

    def add_workdays(start, hours_needed, daily_h, skip_weekend):
        remaining = hours_needed
        current = pd.Timestamp(start)
        while remaining > 0:
            current += timedelta(days=1)
            if skip_weekend and current.weekday() >= 5:
                continue
            remaining -= daily_h
        return current.date()

    pending = dff[dff["狀態"] != "已完工"].copy()
    if pending.empty:
        st.info("目前無待開工/生產中工單。")
    else:
        calc_rows = []
        for _, r in pending.iterrows():
            hours = r["數量"] / max(r["UPH"], 1)
            est_end = add_workdays(r["開工"], hours, daily_h, skip_weekend)
            orig_end = r["完工"]
            diff = (pd.Timestamp(est_end) - pd.Timestamp(orig_end)).days
            calc_rows.append({
                "工單號": r["工單號"],
                "產品":   r["產品"],
                "產線":   r["產線"],
                "數量":   r["數量"],
                "UPH":    r["UPH"],
                "計畫工時(hr)": round(hours, 1),
                "預計開工": r["開工"],
                "ERP完工日": orig_end,
                "試算完工日": est_end,
                "差異(天)":  diff,
            })
        calc_df = pd.DataFrame(calc_rows)

        def style_diff(v):
            if v > 0:  return "background-color:#fee2e2;color:#dc2626;font-weight:bold"
            if v < 0:  return "background-color:#dcfce7;color:#15803d"
            return ""

        st.dataframe(
            calc_df.style.map(style_diff, subset=["差異(天)"]),
            use_container_width=True, hide_index=True
        )

        late = calc_df[calc_df["差異(天)"] > 0]
        if not late.empty:
            st.warning(f"⚠️ 有 **{len(late)}** 張工單依 UPH 試算後，預計完工日晚於 ERP 排定日期！")
        else:
            st.success("✅ 所有工單依 UPH 試算均可在預定日完工。")
