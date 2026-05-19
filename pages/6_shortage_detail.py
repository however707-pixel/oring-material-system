import streamlit as st
import pandas as pd
import io
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from utils.shared import inject_css, render_header, render_sidebar
from utils.i18n import t

# ── 初始化 ────────────────────────────────────────────────────────────────────
if "lang" not in st.session_state:
    st.session_state["lang"] = "zh"

st.set_page_config(page_title="區間工單缺料明細", page_icon="📊", layout="wide", initial_sidebar_state="expanded")
inject_css()

with st.sidebar:
    col_zh, col_en = st.columns(2)
    with col_zh:
        if st.button("🇹🇼 中文", key="btn_zh",
                     type="primary" if st.session_state["lang"] == "zh" else "secondary",
                     use_container_width=True):
            st.session_state["lang"] = "zh"
            st.rerun()
    with col_en:
        if st.button("🇺🇸 EN", key="btn_en",
                     type="primary" if st.session_state["lang"] == "en" else "secondary",
                     use_container_width=True):
            st.session_state["lang"] = "en"
            st.rerun()

render_header(
    title="區間工單缺料明細",
    subtitle="Period Work Order Shortage Detail · Production Control · ORing Industrial Networking",
    badge="Production Management System",
)
render_sidebar()

# ── 側邊欄上傳 ────────────────────────────────────────────────────────────────
with st.sidebar:
    st.divider()
    st.markdown("### 📂 上傳資料檔案")
    f_supply   = st.file_uploader("供需表（分倉）", type=["xlsx", "xls"], key="f_supply")
    f_wo       = st.file_uploader("工單表",         type=["xlsx", "xls"], key="f_wo")
    f_qc       = st.file_uploader("QC表",           type=["xlsx", "xls"], key="f_qc")

# ── 主畫面（等待邏輯定義）────────────────────────────────────────────────────
st.info("⚙️ 此功能建置中，請提供分析邏輯後即可上線。")
