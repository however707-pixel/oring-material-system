import streamlit as st
import sys, os
from PIL import Image
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

img_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "wh_staff.png")
if os.path.exists(img_path):
    img = Image.open(img_path)
    st.image(img, use_container_width=True)
else:
    st.warning("找不到流程圖檔案，請確認 assets/wh_staff.png 是否存在。")
