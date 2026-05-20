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
st.set_page_config(page_title="委外調撥確認", page_icon="🏭", layout="wide", initial_sidebar_state="expanded")
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
    st.info("👈 請在左側上傳「委外需求表」及「供需表」開始分析")
    st.markdown("""
    <div style="background:#f0fdf4;border:1.5px dashed #86efac;border-radius:12px;padding:20px 24px;margin-top:16px;">
    <b style="color:#15803d;font-size:1rem;">📋 操作步驟</b>
    <ol style="color:#374151;margin-top:10px;line-height:2.2;">
      <li>ERP → 製令/託外管理系統 → <b>委外需求表</b> → 匯出 Excel，上傳至左側</li>
      <li>ERP → 供需管理 → <b>供需表（分倉）</b> → 匯出 Excel，上傳至左側</li>
      <li>設定<b>分析基準日</b>（用於判斷在途料是否計入）</li>
      <li>設定<b>考慮未來天數</b>（預計幾天內需要發料）</li>
      <li>系統自動比對委外缺料 vs 各倉庫存，產出調撥建議</li>
    </ol>
    <br>
    <b style="color:#15803d;">🎯 分類邏輯</b>
    <table style="margin-top:8px;width:100%;border-collapse:collapse;font-size:0.88rem;">
      <tr style="background:#dcfce7;"><td style="padding:5px 10px;">🟢 可調撥</td><td style="padding:5px 10px;">廠內倉庫存充足，可直接發料至委外廠</td></tr>
      <tr><td style="padding:5px 10px;">🟡 部分可調</td><td style="padding:5px 10px;">庫存不足全量，需配合在途料或分批發料</td></tr>
      <tr style="background:#dcfce7;"><td style="padding:5px 10px;">🔴 真缺料</td><td style="padding:5px 10px;">全公司庫存皆不足，需採購補料</td></tr>
      <tr><td style="padding:5px 10px;">⚪ IQC 待驗</td><td style="padding:5px 10px;">料已到廠但在品管檢驗中，尚無法使用</td></tr>
    </table>
    </div>
    """, unsafe_allow_html=True)
