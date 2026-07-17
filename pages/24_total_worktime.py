import os
import sys

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from utils.shared import inject_css, render_header, render_sidebar

st.set_page_config(page_title="總計工時表", page_icon="⏱", layout="wide")
inject_css()
render_header(title="總計工時表", subtitle="Total Work Time Summary · Process Station", badge="製程站 PS")
render_sidebar()

# ─── 佔位頁：計算邏輯待定義後補上 ─────────────────────────────────────────────

st.markdown("""
<div style="
    margin-top:40px; padding:56px 32px; text-align:center;
    background:rgba(20,184,166,0.07); border:1px dashed rgba(45,212,191,0.45);
    border-radius:16px;">
    <div style="font-size:3rem; line-height:1">⏱</div>
    <div style="font-size:1.35rem; font-weight:800; margin-top:14px;">總計工時表　建置中</div>
    <div style="font-size:0.95rem; opacity:0.75; margin-top:10px;">
        頁面已就緒，統計邏輯待定義後補上。<br>
        預計彙整 組裝（Start→End）與 測試（第一／第二測程）各站工時。
    </div>
</div>
""", unsafe_allow_html=True)
