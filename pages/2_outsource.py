import streamlit as st
import pandas as pd
from datetime import datetime
import io
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from utils.shared import ensure_calamine, inject_css, render_header, render_sidebar

# =========================
# 0. 初始化
# =========================
ensure_calamine()

# =========================
# 1. 頁面設定
# =========================
st.set_page_config(page_title="委外調撥確認", page_icon="🏭", layout="wide")
inject_css()
render_header(
    title="委外調撥確認",
    subtitle="Outsourcing Transfer Confirmation &nbsp;·&nbsp; ORing Industrial Networking",
    badge="Material Control · MC",
    show_logo=False,
)

# =========================
# 2. Sidebar
# =========================
render_sidebar()

with st.sidebar:
    st.divider()
    st.markdown("### ⚙️ 設定")
    outsource_file = st.file_uploader("上傳委外需求表", type=["xlsx", "xls", "csv"])
    supply_file    = st.file_uploader("上傳供需表",     type=["xlsx", "xls", "csv"])
    analysis_date  = st.date_input("📅 分析基準日", datetime(2026, 5, 15), format="YYYY/MM/DD")
    days_range     = st.slider("考慮未來天數", 1, 30, 14)
    st.divider()
    st.info(
        "💡 **分析邏輯**\n\n"
        "1. 讀取委外需求表的品號與缺料量\n"
        "2. 比對供需表找出各倉可調撥庫存\n"
        "3. 依優先倉別計算可調撥數量\n"
        "4. 產出委外調撥確認清單"
    )

# =========================
# 3. 主畫面
# =========================
if outsource_file and supply_file:
    st.info("🔧 功能開發中，敬請期待！")
else:
    st.markdown("""
    <div style="text-align:center; padding:60px 0; color:#94a3b8;">
        <div style="font-size:3rem; margin-bottom:16px;">🏭</div>
        <div style="font-size:1rem; font-weight:600; color:#64748b; margin-bottom:8px;">委外調撥確認</div>
        <div style="font-size:0.85rem;">請從左側上傳委外需求表及供需表開始分析</div>
    </div>""", unsafe_allow_html=True)
