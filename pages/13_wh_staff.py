import streamlit as st
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from utils.shared import inject_css, render_header, render_sidebar

st.set_page_config(page_title="倉儲人員編製", page_icon="👥", layout="wide", initial_sidebar_state="expanded")
inject_css()
render_header(
    title="倉儲人員編製",
    subtitle="Warehouse Staff Organization &nbsp;·&nbsp; ORing Industrial Networking",
    badge="Warehouse · WH",
    show_logo=False,
)
render_sidebar()

st.info("🚧 功能開發中，敬請期待。")
