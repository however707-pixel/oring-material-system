import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import date, timedelta
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from utils.shared import inject_css, render_header, render_sidebar

st.set_page_config(page_title="排程系統", page_icon="🗓", layout="wide")
inject_css()
render_header(title="排程系統", subtitle="Production Scheduling System", badge="生管 PC")
render_sidebar()

# ── 示意資料 ──────────────────────────────────────────────────────────────────
SAMPLE_WO = [
    dict(工單號="5220-20260501001", 產品="IGS-9122GP", 產線="宣-1線", 數量=100, 開工=date(2026,5,1),  完工=date(2026,5,6),  狀態="生產中", 優先="高"),
    dict(工單號="5220-20260502001", 產品="IES-3080",   產線="宣-2線", 數量=200, 開工=date(2026,5,2),  完工=date(2026,5,8),  狀態="生產中", 優先="中"),
    dict(工單號="5220-20260503001", 產品="RMC-111FB",  產線="賢-1線", 數量=50,  開工=date(2026,5,5),  完工=date(2026,5,9),  狀態="待開工", 優先="低"),
    dict(工單號="5220-20260504001", 產品="IGS-9084GP", 產線="宣-1線", 數量=80,  開工=date(2026,5,7),  完工=date(2026,5,13), 狀態="待開工", 優先="高"),
    dict(工單號="5220-20260505001", 產品="IPS-3082GC", 產線="賢-2線", 數量=400, 開工=date(2026,5,3),  完工=date(2026,5,12), 狀態="生產中", 優先="高"),
    dict(工單號="5220-20260506001", 產品="TCXK-ISW",   產線="宣-2線", 數量=150, 開工=date(2026,5,9),  完工=date(2026,5,15), 狀態="待開工", 優先="中"),
    dict(工單號="5220-20260507001", 產品="IGS-9122GP", 產線="賢-1線", 數量=60,  開工=date(2026,5,12), 完工=date(2026,5,16), 狀態="待開工", 優先="低"),
    dict(工單號="5220-20260408001", 產品="IES-3080",   產線="宣-1線", 數量=100, 開工=date(2026,4,28), 完工=date(2026,5,3),  狀態="已完工", 優先="中"),
    dict(工單號="5220-20260409001", 產品="RES-P9242GCL",產線="賢-2線",數量=31,  開工=date(2026,4,25), 完工=date(2026,5,2),  狀態="已完工", 優先="高"),
]
df = pd.DataFrame(SAMPLE_WO)
df["開工"] = pd.to_datetime(df["開工"])
df["完工"] = pd.to_datetime(df["完工"])

# ── 篩選控制列 ────────────────────────────────────────────────────────────────
st.markdown("---")
fc1, fc2, fc3, fc4 = st.columns([2, 2, 2, 1])
with fc1:
    date_range = st.date_input("日期區間", value=(date(2026,4,25), date(2026,5,16)),
                               key="sched_date")
with fc2:
    lines = ["全部"] + sorted(df["產線"].unique().tolist())
    sel_line = st.selectbox("產線", lines, key="sched_line")
with fc3:
    states = ["全部", "待開工", "生產中", "已完工"]
    sel_state = st.selectbox("狀態", states, key="sched_state")
with fc4:
    st.markdown("<br>", unsafe_allow_html=True)
    upload = st.file_uploader("上傳工單 Excel", type=["xlsx"], label_visibility="collapsed",
                               key="sched_upload")

# 套用篩選
dff = df.copy()
if isinstance(date_range, (list, tuple)) and len(date_range) == 2:
    dff = dff[(dff["開工"] >= pd.to_datetime(date_range[0])) &
              (dff["完工"] <= pd.to_datetime(date_range[1]))]
if sel_line != "全部":
    dff = dff[dff["產線"] == sel_line]
if sel_state != "全部":
    dff = dff[dff["狀態"] == sel_state]

# ── KPI 指標 ──────────────────────────────────────────────────────────────────
m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("工單總數",   len(dff))
m2.metric("待開工",     len(dff[dff["狀態"]=="待開工"]))
m3.metric("生產中",     len(dff[dff["狀態"]=="生產中"]))
m4.metric("已完工",     len(dff[dff["狀態"]=="已完工"]))
m5.metric("預計總產量", f"{dff['數量'].sum():,}")

st.markdown("---")

# ── 甘特圖 ────────────────────────────────────────────────────────────────────
st.markdown("#### 生產排程甘特圖")

color_map = {"生產中": "#1d4ed8", "待開工": "#f59e0b", "已完工": "#16a34a"}

if dff.empty:
    st.warning("目前篩選條件下無工單資料。")
else:
    fig = px.timeline(
        dff,
        x_start="開工", x_end="完工",
        y="產線",
        color="狀態",
        color_discrete_map=color_map,
        text="工單號",
        hover_data={"產品": True, "數量": True, "優先": True, "狀態": True},
        labels={"產線": "產線", "開工": "開工日", "完工": "完工日"},
    )
    fig.update_traces(textposition="inside", insidetextanchor="middle",
                      textfont=dict(size=11, color="white"))
    fig.update_layout(
        height=340,
        margin=dict(l=10, r=10, t=30, b=10),
        paper_bgcolor="white",
        plot_bgcolor="#f8fafc",
        yaxis=dict(autorange="reversed", gridcolor="#e2e8f0"),
        xaxis=dict(gridcolor="#e2e8f0"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        font=dict(family="'Segoe UI', sans-serif"),
    )
    # 今天線
    fig.add_vline(x=pd.Timestamp(date.today()), line_width=2,
                  line_dash="dash", line_color="#ef4444",
                  annotation_text="今天", annotation_position="top right")
    st.plotly_chart(fig, use_container_width=True)

# ── 產線負載圖 ────────────────────────────────────────────────────────────────
st.markdown("#### 各產線工單數量")
load = dff.groupby(["產線","狀態"])["數量"].sum().reset_index()
if not load.empty:
    fig2 = px.bar(load, x="產線", y="數量", color="狀態",
                  color_discrete_map=color_map, barmode="stack",
                  labels={"數量": "計畫產量"})
    fig2.update_layout(height=260, margin=dict(l=10, r=10, t=20, b=10),
                       paper_bgcolor="white", plot_bgcolor="#f8fafc",
                       yaxis=dict(gridcolor="#e2e8f0"),
                       legend=dict(orientation="h", yanchor="bottom", y=1.02))
    st.plotly_chart(fig2, use_container_width=True)

# ── 工單明細表 ────────────────────────────────────────────────────────────────
st.markdown("---")
st.markdown("#### 工單明細")

priority_color = {"高": "🔴", "中": "🟡", "低": "🟢"}
dff_show = dff.copy()
dff_show["優先"] = dff_show["優先"].map(lambda x: f"{priority_color.get(x,'')} {x}")
dff_show["開工"] = dff_show["開工"].dt.strftime("%Y/%m/%d")
dff_show["完工"] = dff_show["完工"].dt.strftime("%Y/%m/%d")

def style_state(val):
    c = {"生產中": "#dbeafe", "待開工": "#fef9c3", "已完工": "#dcfce7"}.get(val, "")
    return f"background-color:{c}" if c else ""

st.dataframe(
    dff_show[["工單號","產品","產線","數量","開工","完工","狀態","優先"]]
    .style.map(style_state, subset=["狀態"]),
    use_container_width=True, hide_index=True
)
