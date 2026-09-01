import subprocess
import sys
import base64
import time as _time
import os as _os
from pathlib import Path
from datetime import datetime as _dt
import streamlit as st
import streamlit.components.v1 as components

# ── 常數 ──────────────────────────────────────────────────────────────────────

PRIORITY_WHS = ["電子倉", "包材倉", "機構倉", "成品倉"]

# ── 套件安裝 ──────────────────────────────────────────────────────────────────

def ensure_calamine():
    try:
        import python_calamine  # noqa
    except ImportError:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "python-calamine", "-q"],
            check=True
        )

# ── 共用 CSS ──────────────────────────────────────────────────────────────────

def inject_css():
    st.markdown("""
<style>
    /* ══ 全域字型：白晝 HUD — 英數 Segoe UI、中文微軟正黑體 ══ */
    html, body, *, *::before, *::after,
    button, input, select, textarea, label,
    span, div, p, li, td, th, h1, h2, h3, h4, h5, h6,
    [class*="st-"], [data-testid] {
        font-family: 'Segoe UI', 'Microsoft JhengHei', '微軟正黑體', 'PingFang TC', Arial, sans-serif !important;
    }
    /* 還原 Material 圖示字體：上面的全域字型會把 expander 箭頭等圖示也改成 Arial，
       導致圖示的 ligature 文字（如 keyboard_arrow_right）直接顯示成英文字疊在標籤上 */
    [data-testid="stIconMaterial"] {
        font-family: 'Material Symbols Rounded' !important;
    }

    #MainMenu { visibility: hidden !important; display: none !important; }
    footer    { visibility: hidden !important; display: none !important; }

    /* ── Header：高度歸零但 overflow:visible，讓側欄展開按鈕仍可見 ── */
    [data-testid="stHeader"] {
        height: 0 !important; min-height: 0 !important; padding: 0 !important;
        overflow: visible !important;
        background: transparent !important; border: none !important;
        box-shadow: none !important;
    }
    /* toolbar 用 visibility:hidden（不用 display:none），保留 DOM 佔位 */
    [data-testid="stToolbar"]     { visibility: hidden !important; }
    [data-testid="stDecoration"]  { display: none !important; }
    [data-testid="stStatusWidget"]{ visibility: hidden !important; }

    /* ── 主內容區：縮小預設頂部留白，整體上移（個別頁面可用後載 CSS 覆蓋） ── */
    [data-testid="stMainBlockContainer"],
    .block-container {
        padding-top: 0.6rem !important;
    }

    /* ══ 側欄：永遠展開，CSS 層面完全鎖定，無視 JS 的 aria-expanded ══ */
    [data-testid="stSidebar"],
    [data-testid="stSidebar"][aria-expanded="false"],
    [data-testid="stSidebar"][aria-expanded="true"] {
        transform:   translateX(0) !important;
        width:       244px         !important;
        min-width:   244px         !important;
        max-width:   244px         !important;
        display:     flex          !important;
        visibility:  visible       !important;
        opacity:     1             !important;
        pointer-events: all        !important;
        position: relative         !important;
        height:     100vh          !important;
        max-height: 100vh          !important;
        flex-shrink: 0             !important;
    }
    /* 側欄內容鎖在視窗高度內部捲動；否則 section 會被內容撐高、
       外層 overflow:hidden 之下整條側欄無法捲動 */
    [data-testid="stSidebarContent"] {
        height: 100vh     !important;
        max-height: 100vh !important;
        overflow-y: auto  !important;
    }
    /* 收合 / 展開按鈕全部隱藏（側欄已鎖定，不需要這些控制） */
    [data-testid="stSidebarCollapseButton"],
    [data-testid="stSidebarCollapsedControl"],
    [data-testid="collapsedControl"] {
        display: none !important;
    }
    /* 側欄頂部表頭佔位壓掉，內容整體上移 */
    [data-testid="stSidebarHeader"] {
        padding: 0 !important; height: 0 !important; min-height: 0 !important;
    }
    [data-testid="stSidebarUserContent"] {
        padding-top: 0.75rem !important;
    }

    [data-testid="stAppViewContainer"] {
        background: linear-gradient(160deg, #e9f0f9 0%, #e0e9f6 55%, #e8e6f4 100%);
        position: relative;
    }
    /* ══ 白晝 HUD：科技格線 ══ */
    [data-testid="stAppViewContainer"]::before {
        content: ""; position: fixed; inset: 0; z-index: 0; pointer-events: none;
        background-image:
            linear-gradient(rgba(59,130,246,0.05) 1px, transparent 1px),
            linear-gradient(90deg, rgba(59,130,246,0.05) 1px, transparent 1px);
        background-size: 34px 34px;
        -webkit-mask-image: radial-gradient(ellipse 90% 80% at 50% 30%, #000 60%, transparent 100%);
        mask-image: radial-gradient(ellipse 90% 80% at 50% 30%, #000 60%, transparent 100%);
    }
    /* ══ 白晝 HUD：亮色極光緩慢漂移 ══ */
    [data-testid="stAppViewContainer"]::after {
        content: ""; position: fixed; inset: -20%; z-index: 0; pointer-events: none;
        background:
            radial-gradient(560px 420px at 12% 8%,  rgba(56,189,248,0.20), transparent 65%),
            radial-gradient(620px 460px at 88% 14%, rgba(167,139,250,0.18), transparent 65%),
            radial-gradient(680px 520px at 45% 96%, rgba(244,114,182,0.13), transparent 65%);
        animation: hudAurora 26s ease-in-out infinite alternate;
    }
    @keyframes hudAurora {
        from { transform: translate(0,0) scale(1); }
        to   { transform: translate(3%,2%) scale(1.08); }
    }
    [data-testid="stMain"], [data-testid="stMainBlockContainer"], .block-container {
        position: relative; z-index: 1;
    }
    /* 側欄不上 backdrop-filter：模糊疊在動態極光上會讓捲動拖曳卡死 */
    [data-testid="stSidebar"] {
        position: relative; z-index: 1;
        background: rgba(252,254,255,0.94);
        border-right: 1px solid rgba(96,165,250,0.30);
        box-shadow: 4px 0 24px rgba(59,130,246,0.08);
    }
    /* 隱藏 Streamlit 所有版本的自動頁面導覽 */
    [data-testid="stSidebarNav"]          { display: none !important; }
    [data-testid="stSidebarNavItems"]     { display: none !important; }
    [data-testid="stSidebarNavLink"]      { display: none !important; }
    [data-testid="stSidebarNavSeparator"] { display: none !important; }
    section[data-testid="stSidebar"] nav  { display: none !important; }
    section[data-testid="stSidebar"] ul   { display: none !important; }

    /* ── Status card：白玻璃＋藍光暈 ── */
    .status-card {
        padding: 16px 22px; border-radius: 14px;
        background: rgba(255,255,255,0.90);
        border: 1px solid rgba(96,165,250,0.40);
        border-left: 4px solid #0ea5e9;
        margin-bottom: 20px;
        box-shadow: 0 10px 30px rgba(59,130,246,0.14);
    }
    .status-card h3 { color: #16213a; margin: 0 0 6px 0; font-size: 1rem; }
    .status-card b { color: #1d4ed8; }

    /* ── Table / download：玻璃卡＋漸層流光按鈕 ── */
    .stDataFrame {
        border-radius: 12px !important;
        border: 1px solid rgba(96,165,250,0.38) !important;
        box-shadow: 0 8px 24px rgba(59,130,246,0.12) !important;
        overflow: hidden;
        background: rgba(255,255,255,0.86);
    }
    hr { border-color: rgba(96,165,250,0.30) !important; }
    .stDownloadButton > button {
        background: linear-gradient(100deg, #0ea5e9, #6366f1, #0ea5e9) !important;
        background-size: 200% 100% !important;
        color: white !important; border: none !important;
        border-radius: 9px !important; font-weight: 700 !important;
        font-size: 0.95rem !important;
        box-shadow: 0 6px 18px rgba(59,130,246,0.40) !important;
        transition: transform 0.15s, box-shadow 0.15s !important;
        animation: hudBtnFlow 3s linear infinite;
    }
    @keyframes hudBtnFlow { from { background-position: 0 0; } to { background-position: 200% 0; } }
    .stDownloadButton > button:hover {
        transform: translateY(-2px) !important;
        box-shadow: 0 9px 26px rgba(99,102,241,0.50) !important;
    }

    /* ── Sidebar: page links ── */
    [data-testid="stSidebar"] [data-testid="stPageLink"] a {
        background: transparent !important; border: none !important;
        border-radius: 8px !important; padding: 7px 10px 7px 18px !important;
        color: #475569 !important; font-size: 0.88rem !important;
        font-weight: 500 !important; display: flex !important;
        align-items: center !important; margin-left: 6px !important;
        transition: background 0.15s !important;
    }
    [data-testid="stSidebar"] [data-testid="stPageLink"] a:hover {
        background: #f1f5f9 !important; color: #1e293b !important;
    }
    [data-testid="stSidebar"] label { font-size: 0.93rem !important; }
    [data-testid="stSidebar"] h3 { font-size: 0.95rem !important; font-weight: 600 !important; }

    /* ── Block / metric card：玻璃卡 ── */
    [data-testid="stMetric"] {
        background: rgba(255,255,255,0.90); border-radius: 12px; padding: 16px 20px;
        box-shadow: 0 8px 22px rgba(59,130,246,0.12);
        border: 1px solid rgba(96,165,250,0.38);
    }

    /* ── Language toggle buttons 3D ── */
    [data-testid="stHorizontalBlock"] .stButton > button {
        border-radius: 20px !important;
        font-weight: 700 !important;
        font-size: 0.82rem !important;
        padding: 4px 14px !important;
        letter-spacing: 0.04em !important;
        transition: all 0.18s cubic-bezier(.34,1.56,.64,1) !important;
        white-space: nowrap !important;
    }
    [data-testid="stHorizontalBlock"] .stButton > button[kind="primary"] {
        background: linear-gradient(120deg, #0ea5e9 0%, #6366f1 100%) !important;
        color: #ffffff !important;
        border: none !important;
        box-shadow:
            0 4px 14px rgba(59,130,246,0.45),
            0 2px 4px rgba(0,0,0,0.10),
            inset 0 1px 0 rgba(255,255,255,0.30) !important;
    }
    [data-testid="stHorizontalBlock"] .stButton > button[kind="primary"]:hover {
        transform: translateY(-2px) scale(1.04) !important;
        box-shadow:
            0 7px 20px rgba(99,102,241,0.55),
            0 3px 6px rgba(0,0,0,0.12),
            inset 0 1px 0 rgba(255,255,255,0.35) !important;
    }
    [data-testid="stHorizontalBlock"] .stButton > button[kind="secondary"] {
        background: rgba(255,255,255,0.85) !important;
        color: #3b5280 !important;
        border: 1.5px solid rgba(96,165,250,0.45) !important;
        box-shadow:
            0 3px 10px rgba(59,130,246,0.10),
            inset 0 1px 0 rgba(255,255,255,0.95) !important;
    }
    [data-testid="stHorizontalBlock"] .stButton > button[kind="secondary"]:hover {
        background: #ffffff !important;
        color: #1d4ed8 !important;
        border-color: #60a5fa !important;
        transform: translateY(-2px) scale(1.04) !important;
        box-shadow:
            0 5px 16px rgba(59,130,246,0.22),
            inset 0 1px 0 rgba(255,255,255,0.95) !important;
    }

    /* ── 文字輸入框：白玻璃 ── */
    [data-testid="stTextInput"] input {
        background: rgba(255,255,255,0.88) !important;
        border: 1px solid rgba(96,165,250,0.40) !important;
        border-radius: 9px !important;
    }
    @media (prefers-reduced-motion: reduce) {
        [data-testid="stAppViewContainer"]::after,
        .stDownloadButton > button { animation: none !important; }
    }
</style>
""", unsafe_allow_html=True)


# ── Logo 檔案路徑 ─────────────────────────────────────────────────────────────

_LOGO_FILE = Path(__file__).parent / "oring_logo.png"

def _logo_b64() -> str:
    if _LOGO_FILE.exists():
        return base64.b64encode(_LOGO_FILE.read_bytes()).decode()
    return ""

# ── 頁首 Header（3D 風格）────────────────────────────────────────────────────

def render_header_init():
    """不顯示 Header，但執行必要的 components.html() 初始化，防止 None 導覽元素出現。"""
    components.html(
        "<!DOCTYPE html><html><head></head>"
        "<body style='margin:0;padding:0;overflow:hidden'></body></html>",
        height=1
    )
    st.markdown(
        "<style>[data-testid='stCustomComponentV1']:first-of-type{"
        "height:1px!important;min-height:0!important;margin:0!important;padding:0!important;"
        "overflow:hidden!important;visibility:hidden!important}</style>",
        unsafe_allow_html=True
    )

def render_header(title: str, subtitle: str, badge: str = "Production Management System", show_logo: bool = True):
    logo_data = _logo_b64() if show_logo else ""
    logo_html = (
        f'<img src="data:image/png;base64,{logo_data}" '
        f'style="height:60px; background:#ffffff; border:1px solid rgba(96,165,250,0.45); '
        f'border-radius:12px; padding:6px 14px; '
        f'box-shadow:0 6px 18px rgba(59,130,246,0.22); flex-shrink:0;" />'
        if logo_data else ""
    )
    components.html(f"""
<!DOCTYPE html><html><head><meta charset="utf-8">
<style>
* {{ margin:0; padding:0; box-sizing:border-box;
    font-family: 'Segoe UI', 'Microsoft JhengHei', '微軟正黑體', 'PingFang TC', Arial, sans-serif; }}
body {{ background:transparent; padding:4px 0; }}
.header {{
    display: flex; align-items: center; gap: 22px;
    background: linear-gradient(135deg, rgba(255,255,255,0.94) 0%, rgba(240,247,255,0.92) 55%, rgba(244,240,253,0.94) 100%);
    border: 1px solid rgba(96,165,250,0.45);
    border-radius: 16px;
    padding: 18px 34px;
    box-shadow:
        0 12px 34px rgba(59,130,246,0.16),
        inset 0 1px 0 rgba(255,255,255,0.95);
    position: relative; overflow: hidden;
}}
/* 科技格線底紋 */
.header::before {{
    content: '';
    position: absolute; inset: 0; pointer-events: none;
    background-image:
        linear-gradient(rgba(59,130,246,0.06) 1px, transparent 1px),
        linear-gradient(90deg, rgba(59,130,246,0.06) 1px, transparent 1px);
    background-size: 26px 26px;
}}
.header::after {{
    content: '';
    position: absolute; top: -70px; right: -50px;
    width: 240px; height: 240px; border-radius: 50%;
    background: radial-gradient(circle, rgba(56,189,248,0.20) 0%, transparent 70%);
    pointer-events: none;
}}
/* 定期掃過橫幅的光澤（白晝版：淡青光） */
.sheen {{
    position: absolute; top: -20%; bottom: -20%; left: -45%; width: 34%;
    transform: skewX(-20deg);
    background: linear-gradient(105deg, transparent, rgba(125,211,252,0.28) 50%, transparent);
    animation: sheenMove 7s ease-in-out 2s infinite;
    pointer-events: none;
}}
@keyframes sheenMove {{
    0% {{ transform: translateX(0) skewX(-20deg); }}
    34% {{ transform: translateX(520%) skewX(-20deg); }}
    100% {{ transform: translateX(520%) skewX(-20deg); }}
}}
/* 底部能量光帶 */
.energy {{
    position: absolute; left: 0; right: 0; bottom: 0; height: 2.5px;
    background: linear-gradient(90deg, transparent, #38bdf8, #a78bfa, #f472b6, transparent);
    background-size: 200% 100%;
    animation: energyFlow 3.2s linear infinite;
    pointer-events: none;
}}
@keyframes energyFlow {{
    from {{ background-position: 200% 0; }}
    to   {{ background-position: -200% 0; }}
}}
.badge {{
    font-size: 0.68rem; font-weight: 700; letter-spacing: 0.14em;
    color: #0284c7; text-transform: uppercase; margin-bottom: 5px;
}}
.title {{
    font-size: 1.75rem; font-weight: 900;
    letter-spacing: 0.02em; line-height: 1.2;
    background: linear-gradient(100deg, #0284c7 0%, #4f46e5 35%, #0ea5e9 55%, #c026d3 90%);
    background-size: 220% 100%;
    -webkit-background-clip: text; background-clip: text;
    -webkit-text-fill-color: transparent; color: transparent;
    animation: titleSheen 6s ease-in-out infinite;
}}
@keyframes titleSheen {{
    0% {{ background-position: 130% 0; }}
    55%, 100% {{ background-position: -40% 0; }}
}}
.subtitle {{
    color: #5b6b85; font-size: 0.85rem; margin-top: 5px;
    letter-spacing: 0.03em;
}}
@media (prefers-reduced-motion: reduce) {{
    .sheen, .energy, .title {{ animation: none; }}
}}
</style></head><body>
<div class="header">
    <i class="sheen"></i><i class="energy"></i>
    {logo_html}
    <div>
        <div class="badge">{badge}</div>
        <div class="title">{title}</div>
        <div class="subtitle">{subtitle}</div>
    </div>
</div>
</body></html>
""", height=118)


# ── 側欄導覽 Sidebar ──────────────────────────────────────────────────────────

def render_sidebar():
    from utils.i18n import t
    if "lang" not in st.session_state:
        st.session_state["lang"] = "zh"
    with st.sidebar:
        st.markdown("""
        <style>
        section[data-testid="stSidebar"], [data-testid="stSidebarContent"] {
            background: linear-gradient(180deg, rgba(252,254,255,0.94) 0%, rgba(240,246,255,0.92) 55%, rgba(244,241,253,0.94) 100%) !important; }
        section[data-testid="stSidebar"] { border-right: 1px solid rgba(96,165,250,0.30) !important; }
        section[data-testid="stSidebar"] ::-webkit-scrollbar { width: 8px; }
        section[data-testid="stSidebar"] ::-webkit-scrollbar-thumb {
            background: rgba(59,130,246,0.35); border-radius: 4px; }
        section[data-testid="stSidebar"] button[kind="secondary"],
        section[data-testid="stSidebar"] button[data-testid="baseButton-secondary"] {
            background: rgba(255,255,255,0.85) !important;
            border: 1px solid rgba(96,165,250,0.40) !important; color: #3b5280 !important; }
        /* 語言切換等橫排按鈕：特異度需壓過 inject_css 的 pill 規則 */
        section[data-testid="stSidebar"] [data-testid="stHorizontalBlock"] .stButton > button[kind="secondary"] {
            background: rgba(255,255,255,0.88) !important;
            color: #3b5280 !important;
            border: 1.5px solid rgba(96,165,250,0.45) !important;
            box-shadow: 0 2px 8px rgba(59,130,246,0.10), inset 0 1px 0 rgba(255,255,255,0.95) !important; }
        section[data-testid="stSidebar"] [data-testid="stHorizontalBlock"] .stButton > button[kind="secondary"]:hover {
            background: #ffffff !important;
            color: #1d4ed8 !important;
            border-color: #60a5fa !important;
            box-shadow: 0 4px 14px rgba(59,130,246,0.25) !important; }
        section[data-testid="stSidebar"] button[kind="primary"],
        section[data-testid="stSidebar"] button[data-testid="baseButton-primary"] {
            background: linear-gradient(120deg,#0ea5e9,#6366f1) !important;
            border: none !important; color: #ffffff !important;
            box-shadow: 0 4px 14px rgba(59,130,246,0.40) !important; }
        section[data-testid="stSidebar"] a,
        section[data-testid="stSidebar"] a:link,
        section[data-testid="stSidebar"] a:visited,
        section[data-testid="stSidebar"] a:hover,
        section[data-testid="stSidebar"] a[href],
        section[data-testid="stSidebar"] a *,
        section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] a {
            color: #33415e !important; }
        /* ── 側欄文字全部深墨色（白晝 HUD） ── */
        section[data-testid="stSidebar"] label,
        section[data-testid="stSidebar"] p,
        section[data-testid="stSidebar"] small,
        section[data-testid="stSidebar"] span,
        section[data-testid="stSidebar"] div[data-testid="stText"],
        section[data-testid="stSidebar"] [data-testid="stCaption"],
        section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p,
        section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] span,
        section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzoneInput"] + div,
        section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] small,
        section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] span {
            color: #33415e !important; }
        </style>
        """, unsafe_allow_html=True)
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
        st.markdown(f"""
        <div style="
            text-align:center; padding:22px 12px 18px; margin-bottom:16px;
            background: rgba(255,255,255,0.85);
            border: 1px solid rgba(96,165,250,0.40);
            border-radius: 14px;
            box-shadow: 0 8px 24px rgba(59,130,246,0.14),
                        inset 0 1px 0 rgba(255,255,255,0.95);
            position: relative; overflow: hidden;
        ">
            <div style="position:absolute; top:0; left:0; right:0; height:2px;
                background:linear-gradient(90deg,transparent,#38bdf8,#a78bfa,transparent);"></div>
            <div style="color:#16213a !important; font-size:1.45rem; font-weight:900; line-height:1.55;
                letter-spacing:0.02em;">
                {t("company_name")}
            </div>
            <div style="font-size:0.78rem; margin-top:7px;
                letter-spacing:0.1em; font-weight:800; text-transform:uppercase;
                background:linear-gradient(100deg,#0284c7,#7c3aed);
                -webkit-background-clip:text; background-clip:text;
                -webkit-text-fill-color:transparent;">
                ORing Industrial Networking
            </div>
            <div style="margin-top:12px; display:inline-block;
                background:rgba(59,130,246,0.10); border:1px solid rgba(96,165,250,0.45);
                border-radius:20px; padding:4px 14px;
                font-size:0.72rem; color:#1d4ed8 !important; font-weight:700; letter-spacing:0.06em;">
                {t("system_ver")}
            </div>
        </div>
        """, unsafe_allow_html=True)

        # 首頁按鈕
        st.markdown("""
        <style>
        [data-testid="stSidebar"] [data-testid="stLinkButton"] > a {
            background: linear-gradient(120deg, #0ea5e9 0%, #6366f1 100%) !important;
            color: #ffffff !important;
            font-weight: 800 !important;
            font-size: 0.93rem !important;
            letter-spacing: 0.04em !important;
            border: none !important;
            border-radius: 10px !important;
            box-shadow: 0 4px 16px rgba(59,130,246,0.40), inset 0 1px 0 rgba(255,255,255,0.30) !important;
            margin-bottom: 4px !important;
        }
        [data-testid="stSidebar"] [data-testid="stLinkButton"] > a:hover {
            background: linear-gradient(120deg, #38bdf8 0%, #818cf8 100%) !important;
            box-shadow: 0 6px 20px rgba(99,102,241,0.50) !important;
        }
        </style>
        """, unsafe_allow_html=True)
        st.link_button("🏠  首頁  Home", url="/", use_container_width=True)

        st.markdown(f"""<div style="color:#7b8aa0; font-size:0.68rem; font-weight:800;
            letter-spacing:0.12em; text-transform:uppercase; margin-bottom:10px;">
            {t("nav_title")}</div>""", unsafe_allow_html=True)

        # 全流程
        st.markdown(f"""
        <div style="display:flex; align-items:center; gap:8px; padding:9px 10px 7px;
                    background:rgba(139,92,246,0.10); border:1px solid rgba(167,139,250,0.32);
                    border-left:3px solid #8b5cf6; border-radius:8px; margin-bottom:3px;">
            <span style="font-size:1.1rem;">🧭</span>
            <div>
                <div style="font-size:1.0rem; font-weight:800; color:#6d28d9; line-height:1.2;">{t("dept_full_flow")}</div>
                <div style="font-size:0.67rem; color:#7c3aed; letter-spacing:0.04em;">{t("dept_full_flow_sub")}</div>
            </div>
        </div>
        <a href="/full_process" target="_self" style="
            display:flex; align-items:center; gap:8px;
            padding:7px 10px 7px 18px; margin-left:6px; margin-bottom:2px;
            border-radius:8px; font-size:0.88rem; font-weight:500;
            color:#33415e !important; text-decoration:none !important;
            transition:background 0.15s;
        " onmouseover="this.style.background='rgba(139,92,246,0.16)';this.style.color='#0f2460'"
           onmouseout="this.style.background='';this.style.color='#33415e'">
            ⚙️ {t("link_full_process")}
        </a>
        <a href="/full_process_wall" target="_self" style="
            display:flex; align-items:center; gap:8px;
            padding:7px 10px 7px 18px; margin-left:6px; margin-bottom:2px;
            border-radius:8px; font-size:0.88rem; font-weight:500;
            color:#33415e !important; text-decoration:none !important;
            transition:background 0.15s;
        " onmouseover="this.style.background='rgba(139,92,246,0.16)';this.style.color='#0f2460'"
           onmouseout="this.style.background='';this.style.color='#33415e'">
            🖥️ 全製程 · 全螢幕
        </a>
        """, unsafe_allow_html=True)

        # PMC
        st.markdown(f"""
        <div style="display:flex; align-items:center; gap:8px; padding:9px 10px 7px;
                    background:rgba(245,158,11,0.10); border:1px solid rgba(245,158,11,0.30);
                    border-left:3px solid #f59e0b; border-radius:8px; margin:8px 0 3px;">
            <span style="font-size:1.1rem;">📑</span>
            <div>
                <div style="font-size:1.0rem; font-weight:800; color:#b45309; line-height:1.2;">PMC</div>
                <div style="font-size:0.67rem; color:#d97706; letter-spacing:0.04em;">Production Material Control</div>
            </div>
        </div>
        <a href="/pmc_order_tracking" target="_self" style="
            display:flex; align-items:center; gap:8px;
            padding:7px 10px 7px 18px; margin-left:6px; margin-bottom:2px;
            border-radius:8px; font-size:0.88rem; font-weight:500;
            color:#33415e !important; text-decoration:none !important;
            transition:background 0.15s;
        " onmouseover="this.style.background='rgba(245,158,11,0.16)';this.style.color='#0f2460'"
           onmouseout="this.style.background='';this.style.color='#33415e'">
            📑 {t("link_pmc_order")}
        </a>
        <a href="/wo_material_trace" target="_self" style="
            display:flex; align-items:center; gap:8px;
            padding:7px 10px 7px 18px; margin-left:6px; margin-bottom:2px;
            border-radius:8px; font-size:0.88rem; font-weight:500;
            color:#33415e !important; text-decoration:none !important;
            transition:background 0.15s;
        " onmouseover="this.style.background='rgba(245,158,11,0.16)';this.style.color='#0f2460'"
           onmouseout="this.style.background='';this.style.color='#33415e'">
            📋 {t("link_wo_trace")}
        </a>
        <a href="/tangyou_shortage_reply" target="_self" style="
            display:flex; align-items:center; gap:8px;
            padding:7px 10px 7px 18px; margin-left:6px; margin-bottom:2px;
            border-radius:8px; font-size:0.88rem; font-weight:500;
            color:#33415e !important; text-decoration:none !important;
            transition:background 0.15s;
        " onmouseover="this.style.background='rgba(245,158,11,0.16)';this.style.color='#0f2460'"
           onmouseout="this.style.background='';this.style.color='#33415e'">
            ✉️ {t("link_tangyou_reply")}
        </a>
        """, unsafe_allow_html=True)

        # 物管 MC
        st.markdown(f"""
        <div style="display:flex; align-items:center; gap:8px; padding:9px 10px 7px;
                    background:rgba(59,130,246,0.10); border:1px solid rgba(96,165,250,0.30);
                    border-left:3px solid #60a5fa; border-radius:8px; margin:8px 0 3px;">
            <span style="font-size:1.1rem;">📦</span>
            <div>
                <div style="font-size:1.0rem; font-weight:800; color:#1d4ed8; line-height:1.2;">{t("dept_mc")}</div>
                <div style="font-size:0.67rem; color:#3b82f6; letter-spacing:0.04em;">{t("dept_mc_sub")}</div>
            </div>
        </div>
        """, unsafe_allow_html=True)
        st.markdown(f"""
        <a href="/transfer" target="_self" style="
            display:flex; align-items:center; gap:8px;
            padding:7px 10px 7px 18px; margin-left:6px; margin-bottom:2px;
            border-radius:8px; font-size:0.88rem; font-weight:500;
            color:#33415e !important; text-decoration:none !important;
            transition:background 0.15s;
        " onmouseover="this.style.background='rgba(56,189,248,0.14)';this.style.color='#0f2460'"
           onmouseout="this.style.background='';this.style.color='#33415e'">
            📊 {t("link_transfer")}
        </a>
        <a href="/outsource" target="_self" style="
            display:flex; align-items:center; gap:8px;
            padding:7px 10px 7px 18px; margin-left:6px; margin-bottom:2px;
            border-radius:8px; font-size:0.88rem; font-weight:500;
            color:#33415e !important; text-decoration:none !important;
            transition:background 0.15s;
        " onmouseover="this.style.background='rgba(56,189,248,0.14)';this.style.color='#0f2460'"
           onmouseout="this.style.background='';this.style.color='#33415e'">
            🏭 {t("link_outsource")}
        </a>
        <a href="/h2o" target="_self" style="
            display:flex; align-items:center; gap:8px;
            padding:7px 10px 7px 18px; margin-left:6px; margin-bottom:2px;
            border-radius:8px; font-size:0.88rem; font-weight:500;
            color:#33415e !important; text-decoration:none !important;
            transition:background 0.15s;
        " onmouseover="this.style.background='rgba(56,189,248,0.14)';this.style.color='#0f2460'"
           onmouseout="this.style.background='';this.style.color='#33415e'">
            💧 {t("link_h2o")}
        </a>
        <a href="/guozhi" target="_self" style="
            display:flex; align-items:center; gap:8px;
            padding:7px 10px 7px 18px; margin-left:6px; margin-bottom:2px;
            border-radius:8px; font-size:0.88rem; font-weight:500;
            color:#33415e !important; text-decoration:none !important;
            transition:background 0.15s;
        " onmouseover="this.style.background='rgba(56,189,248,0.14)';this.style.color='#0f2460'"
           onmouseout="this.style.background='';this.style.color='#33415e'">
            🏭 {t("link_guozhi")}
        </a>
        <a href="/factory" target="_self" style="
            display:flex; align-items:center; gap:8px;
            padding:7px 10px 7px 18px; margin-left:6px; margin-bottom:2px;
            border-radius:8px; font-size:0.88rem; font-weight:500;
            color:#33415e !important; text-decoration:none !important;
            transition:background 0.15s;
        " onmouseover="this.style.background='rgba(56,189,248,0.14)';this.style.color='#0f2460'"
           onmouseout="this.style.background='';this.style.color='#33415e'">
            🏭 {t("link_factory")}
        </a>
        """, unsafe_allow_html=True)
        st.markdown(f"""
        <div style="margin:7px 0 3px 6px;font-size:0.62rem;font-weight:800;letter-spacing:0.10em;text-transform:uppercase;color:#8fa0bd;">{t("todo_title")}</div>
        <div style="display:flex;align-items:center;gap:8px;padding:6px 10px 6px 18px;margin-left:6px;margin-bottom:2px;border-radius:8px;font-size:0.84rem;font-weight:500;color:#5b6b85;border-left:2px dashed rgba(148,163,184,0.55);"><span style="font-size:0.8rem;opacity:0.7;">🔧</span><span>{t("todo_mc_arrival")}</span><span style="margin-left:auto;font-size:0.58rem;font-weight:700;color:#92400e;background:rgba(245,158,11,0.16);border:1px solid rgba(245,158,11,0.45);border-radius:6px;padding:1px 6px;">{t("todo_badge")}</span></div>
        """, unsafe_allow_html=True)

        # 生管 PC
        st.markdown(f"""
        <div style="display:flex; align-items:center; gap:8px; padding:9px 10px 7px;
                    background:rgba(14,165,233,0.10); border:1px solid rgba(56,189,248,0.30);
                    border-left:3px solid #38bdf8; border-radius:8px; margin:8px 0 3px;">
            <span style="font-size:1.1rem;">🏗</span>
            <div>
                <div style="font-size:1.0rem; font-weight:800; color:#0369a1; line-height:1.2;">{t("dept_pc")}</div>
                <div style="font-size:0.67rem; color:#0284c7; letter-spacing:0.04em;">{t("dept_pc_sub")}</div>
            </div>
        </div>
        """, unsafe_allow_html=True)
        st.markdown(f"""
        <a href="/wo_progress" target="_self" style="
            display:flex; align-items:center; gap:8px;
            padding:7px 10px 7px 18px; margin-left:6px; margin-bottom:2px;
            border-radius:8px; font-size:0.88rem; font-weight:500;
            color:#33415e !important; text-decoration:none !important;
            transition:background 0.15s;
        " onmouseover="this.style.background='rgba(56,189,248,0.14)';this.style.color='#0f2460'"
           onmouseout="this.style.background='';this.style.color='#33415e'">
            📋 {t("link_wo_progress")}
        </a>
        """, unsafe_allow_html=True)
        st.markdown(f"""
        <a href="/shortage_detail" target="_self" style="
            display:flex; align-items:center; gap:8px;
            padding:7px 10px 7px 18px; margin-left:6px; margin-bottom:2px;
            border-radius:8px; font-size:0.88rem; font-weight:500;
            color:#33415e !important; text-decoration:none !important;
            transition:background 0.15s;
        " onmouseover="this.style.background='rgba(56,189,248,0.14)';this.style.color='#0f2460'"
           onmouseout="this.style.background='';this.style.color='#33415e'">
            📊 {t("link_shortage_detail")}
        </a>
        <a href="/full_material_trace" target="_self" style="
            display:flex; align-items:center; gap:8px;
            padding:7px 10px 7px 18px; margin-left:6px; margin-bottom:2px;
            border-radius:8px; font-size:0.88rem; font-weight:500;
            color:#33415e !important; text-decoration:none !important;
            transition:background 0.15s;
        " onmouseover="this.style.background='rgba(56,189,248,0.14)';this.style.color='#0f2460'"
           onmouseout="this.style.background='';this.style.color='#33415e'">
            🏭 {t("link_full_trace")}
        </a>
        <a href="/production_tracker" target="_self" style="
            display:flex; align-items:center; gap:8px;
            padding:7px 10px 7px 18px; margin-left:6px; margin-bottom:2px;
            border-radius:8px; font-size:0.88rem; font-weight:500;
            color:#33415e !important; text-decoration:none !important;
            transition:background 0.15s;
        " onmouseover="this.style.background='rgba(56,189,248,0.14)';this.style.color='#0f2460'"
           onmouseout="this.style.background='';this.style.color='#33415e'">
            🏭 {t("link_production_tracker")}
        </a>
        <a href="/monthly_cost" target="_self" style="
            display:flex; align-items:center; gap:8px;
            padding:7px 10px 7px 18px; margin-left:6px; margin-bottom:2px;
            border-radius:8px; font-size:0.88rem; font-weight:500;
            color:#33415e !important; text-decoration:none !important;
            transition:background 0.15s;
        " onmouseover="this.style.background='rgba(56,189,248,0.14)';this.style.color='#0f2460'"
           onmouseout="this.style.background='';this.style.color='#33415e'">
            📊 {t("link_monthly_cost")}
        </a>
        <a href="/scheduling" target="_self" style="
            display:flex; align-items:center; gap:8px;
            padding:7px 10px 7px 18px; margin-left:6px; margin-bottom:2px;
            border-radius:8px; font-size:0.88rem; font-weight:500;
            color:#33415e !important; text-decoration:none !important;
            transition:background 0.15s;
        " onmouseover="this.style.background='rgba(56,189,248,0.14)';this.style.color='#0f2460'"
           onmouseout="this.style.background='';this.style.color='#33415e'">
            🗓 {t("link_scheduling")}
        </a>
        <a href="/loss_rate" target="_self" style="
            display:flex; align-items:center; gap:8px;
            padding:7px 10px 7px 18px; margin-left:6px; margin-bottom:2px;
            border-radius:8px; font-size:0.88rem; font-weight:500;
            color:#33415e !important; text-decoration:none !important;
            transition:background 0.15s;
        " onmouseover="this.style.background='rgba(56,189,248,0.14)';this.style.color='#0f2460'"
           onmouseout="this.style.background='';this.style.color='#33415e'">
            📉 {t("link_loss_rate")}
        </a>
        <a href="/kanban" target="_self" style="
            display:flex; align-items:center; gap:8px;
            padding:7px 10px 7px 18px; margin-left:6px; margin-bottom:2px;
            border-radius:8px; font-size:0.88rem; font-weight:700;
            color:#0369a1 !important; text-decoration:none !important;
            background:rgba(56,189,248,0.12); border:1px solid rgba(56,189,248,0.45);
            transition:background 0.15s;
        " onmouseover="this.style.background='rgba(56,189,248,0.22)';this.style.color='#0f2460'"
           onmouseout="this.style.background='rgba(56,189,248,0.12)';this.style.color='#0369a1'">
            📺 {t("link_kanban")}
        </a>
        <a href="/outsource_schedule" target="_self" style="
            display:flex; align-items:center; gap:8px;
            padding:7px 10px 7px 18px; margin-left:6px; margin-bottom:2px;
            border-radius:8px; font-size:0.88rem; font-weight:500;
            color:#33415e !important; text-decoration:none !important;
            transition:background 0.15s;
        " onmouseover="this.style.background='rgba(56,189,248,0.14)';this.style.color='#0f2460'"
           onmouseout="this.style.background='';this.style.color='#33415e'">
            🏭 {t("link_outsource_schedule")}
        </a>
        """, unsafe_allow_html=True)
        st.markdown(f"""
        <div style="margin:7px 0 3px 6px;font-size:0.62rem;font-weight:800;letter-spacing:0.10em;text-transform:uppercase;color:#8fa0bd;">{t("todo_title")}</div>
        <div style="display:flex;align-items:center;gap:8px;padding:6px 10px 6px 18px;margin-left:6px;margin-bottom:2px;border-radius:8px;font-size:0.84rem;font-weight:500;color:#5b6b85;border-left:2px dashed rgba(148,163,184,0.55);"><span style="font-size:0.8rem;opacity:0.7;">🔧</span><span>{t("todo_pc_confirm")}</span><span style="margin-left:auto;font-size:0.58rem;font-weight:700;color:#92400e;background:rgba(245,158,11,0.16);border:1px solid rgba(245,158,11,0.45);border-radius:6px;padding:1px 6px;">{t("todo_badge")}</span></div>
        <div style="display:flex;align-items:center;gap:8px;padding:6px 10px 6px 18px;margin-left:6px;margin-bottom:2px;border-radius:8px;font-size:0.84rem;font-weight:500;color:#5b6b85;border-left:2px dashed rgba(148,163,184,0.55);"><span style="font-size:0.8rem;opacity:0.7;">🔧</span><span>{t("todo_pc_release")}</span><span style="margin-left:auto;font-size:0.58rem;font-weight:700;color:#92400e;background:rgba(245,158,11,0.16);border:1px solid rgba(245,158,11,0.45);border-radius:6px;padding:1px 6px;">{t("todo_badge")}</span></div>
        <div style="display:flex;align-items:center;gap:8px;padding:6px 10px 6px 18px;margin-left:6px;margin-bottom:2px;border-radius:8px;font-size:0.84rem;font-weight:500;color:#5b6b85;border-left:2px dashed rgba(148,163,184,0.55);"><span style="font-size:0.8rem;opacity:0.7;">🔧</span><span>{t("todo_pc_report")}</span><span style="margin-left:auto;font-size:0.58rem;font-weight:700;color:#92400e;background:rgba(245,158,11,0.16);border:1px solid rgba(245,158,11,0.45);border-radius:6px;padding:1px 6px;">{t("todo_badge")}</span></div>
        """, unsafe_allow_html=True)

        # 倉管 WH
        st.markdown(f"""
        <div style="display:flex; align-items:center; gap:8px; padding:9px 10px 7px;
                    background:rgba(99,102,241,0.10); border:1px solid rgba(129,140,248,0.30);
                    border-left:3px solid #818cf8; border-radius:8px; margin:4px 0 3px;">
            <span style="font-size:1.1rem;">🏬</span>
            <div>
                <div style="font-size:1.0rem; font-weight:800; color:#4f46e5; line-height:1.2;">{t("dept_wh")}</div>
                <div style="font-size:0.67rem; color:#6366f1; letter-spacing:0.04em;">{t("dept_wh_sub")}</div>
            </div>
        </div>
        """, unsafe_allow_html=True)
        st.markdown(f"""
        <a href="/daily_inbound" target="_self" style="
            display:flex; align-items:center; gap:8px;
            padding:7px 10px 7px 18px; margin-left:6px; margin-bottom:2px;
            border-radius:8px; font-size:0.88rem; font-weight:500;
            color:#33415e !important; text-decoration:none !important;
            transition:background 0.15s;
        " onmouseover="this.style.background='rgba(129,140,248,0.16)';this.style.color='#0f2460'"
           onmouseout="this.style.background='';this.style.color='#33415e'">
            📥 {t("link_daily_inbound")}
        </a>
        <a href="/daily_picking" target="_self" style="
            display:flex; align-items:center; gap:8px;
            padding:7px 10px 7px 18px; margin-left:6px; margin-bottom:2px;
            border-radius:8px; font-size:0.88rem; font-weight:500;
            color:#33415e !important; text-decoration:none !important;
            transition:background 0.15s;
        " onmouseover="this.style.background='rgba(129,140,248,0.16)';this.style.color='#0f2460'"
           onmouseout="this.style.background='';this.style.color='#33415e'">
            📋 {t("link_daily_picking")}
        </a>
        <a href="/wh_staff" target="_self" style="
            display:flex; align-items:center; gap:8px;
            padding:7px 10px 7px 18px; margin-left:6px; margin-bottom:2px;
            border-radius:8px; font-size:0.88rem; font-weight:500;
            color:#33415e !important; text-decoration:none !important;
            transition:background 0.15s;
        " onmouseover="this.style.background='rgba(129,140,248,0.16)';this.style.color='#0f2460'"
           onmouseout="this.style.background='';this.style.color='#33415e'">
            👥 {t("link_wh_staff")}
        </a>
        <a href="/wh_dashboard" target="_self" style="
            display:flex; align-items:center; gap:8px;
            padding:7px 10px 7px 18px; margin-left:6px; margin-bottom:2px;
            border-radius:8px; font-size:0.88rem; font-weight:500;
            color:#33415e !important; text-decoration:none !important;
            transition:background 0.15s;
        " onmouseover="this.style.background='rgba(129,140,248,0.16)';this.style.color='#0f2460'"
           onmouseout="this.style.background='';this.style.color='#33415e'">
            🏭 {t("link_wh_dashboard")}
        </a>
        <a href="/wh_assessment" target="_self" style="
            display:flex; align-items:center; gap:8px;
            padding:7px 10px 7px 18px; margin-left:6px; margin-bottom:2px;
            border-radius:8px; font-size:0.88rem; font-weight:500;
            color:#33415e !important; text-decoration:none !important;
            transition:background 0.15s;
        " onmouseover="this.style.background='rgba(129,140,248,0.16)';this.style.color='#0f2460'"
           onmouseout="this.style.background='';this.style.color='#33415e'">
            📋 {t("link_wh_assessment")}
        </a>
        """, unsafe_allow_html=True)
        st.markdown(f"""
        <div style="margin:7px 0 3px 6px;font-size:0.62rem;font-weight:800;letter-spacing:0.10em;text-transform:uppercase;color:#8fa0bd;">{t("todo_title")}</div>
        <div style="display:flex;align-items:center;gap:8px;padding:6px 10px 6px 18px;margin-left:6px;margin-bottom:2px;border-radius:8px;font-size:0.84rem;font-weight:500;color:#5b6b85;border-left:2px dashed rgba(148,163,184,0.55);"><span style="font-size:0.8rem;opacity:0.7;">🔧</span><span>{t("todo_wh_iqc")}</span><span style="margin-left:auto;font-size:0.58rem;font-weight:700;color:#92400e;background:rgba(245,158,11,0.16);border:1px solid rgba(245,158,11,0.45);border-radius:6px;padding:1px 6px;">{t("todo_badge")}</span></div>
        <div style="display:flex;align-items:center;gap:8px;padding:6px 10px 6px 18px;margin-left:6px;margin-bottom:2px;border-radius:8px;font-size:0.84rem;font-weight:500;color:#5b6b85;border-left:2px dashed rgba(148,163,184,0.55);"><span style="font-size:0.8rem;opacity:0.7;">🔧</span><span>{t("todo_wh_putaway")}</span><span style="margin-left:auto;font-size:0.58rem;font-weight:700;color:#92400e;background:rgba(245,158,11,0.16);border:1px solid rgba(245,158,11,0.45);border-radius:6px;padding:1px 6px;">{t("todo_badge")}</span></div>
        <div style="display:flex;align-items:center;gap:8px;padding:6px 10px 6px 18px;margin-left:6px;margin-bottom:2px;border-radius:8px;font-size:0.84rem;font-weight:500;color:#5b6b85;border-left:2px dashed rgba(148,163,184,0.55);"><span style="font-size:0.8rem;opacity:0.7;">🔧</span><span>{t("todo_wh_packing")}</span><span style="margin-left:auto;font-size:0.58rem;font-weight:700;color:#92400e;background:rgba(245,158,11,0.16);border:1px solid rgba(245,158,11,0.45);border-radius:6px;padding:1px 6px;">{t("todo_badge")}</span></div>
        <div style="display:flex;align-items:center;gap:8px;padding:6px 10px 6px 18px;margin-left:6px;margin-bottom:2px;border-radius:8px;font-size:0.84rem;font-weight:500;color:#5b6b85;border-left:2px dashed rgba(148,163,184,0.55);"><span style="font-size:0.8rem;opacity:0.7;">🔧</span><span>{t("todo_wh_shipping")}</span><span style="margin-left:auto;font-size:0.58rem;font-weight:700;color:#92400e;background:rgba(245,158,11,0.16);border:1px solid rgba(245,158,11,0.45);border-radius:6px;padding:1px 6px;">{t("todo_badge")}</span></div>
        """, unsafe_allow_html=True)

        # RMA
        st.markdown(f"""
        <div style="display:flex; align-items:center; gap:8px; padding:9px 10px 7px;
                    background:rgba(45,212,191,0.10); border:1px solid rgba(45,212,191,0.30);
                    border-left:3px solid #2dd4bf; border-radius:8px; margin:8px 0 3px;">
            <span style="font-size:1.1rem;">🔄</span>
            <div>
                <div style="font-size:1.0rem; font-weight:800; color:#0f766e; line-height:1.2;">{t("dept_rma")}</div>
                <div style="font-size:0.67rem; color:#0d9488; letter-spacing:0.04em;">{t("dept_rma_sub")}</div>
            </div>
        </div>
        """, unsafe_allow_html=True)
        st.markdown(f"""
        <a href="/rma_summary" target="_self" style="
            display:flex; align-items:center; gap:8px;
            padding:7px 10px 7px 18px; margin-left:6px; margin-bottom:2px;
            border-radius:8px; font-size:0.88rem; font-weight:500;
            color:#33415e !important; text-decoration:none !important;
            transition:background 0.15s;
        " onmouseover="this.style.background='rgba(45,212,191,0.16)';this.style.color='#0f2460'"
           onmouseout="this.style.background='';this.style.color='#33415e'">
            📋 {t("link_rma_summary")}
        </a>
        """, unsafe_allow_html=True)

        # 製程站
        st.markdown(f"""
        <div style="display:flex; align-items:center; gap:8px; padding:9px 10px 7px;
                    background:rgba(20,184,166,0.10); border:1px solid rgba(45,212,191,0.30);
                    border-left:3px solid #14b8a6; border-radius:8px; margin:8px 0 3px;">
            <span style="font-size:1.1rem;">🛠</span>
            <div>
                <div style="font-size:1.0rem; font-weight:800; color:#0f766e; line-height:1.2;">{t("dept_ps")}</div>
                <div style="font-size:0.67rem; color:#0d9488; letter-spacing:0.04em;">{t("dept_ps_sub")}</div>
            </div>
        </div>
        <a href="/assembly" target="_self" style="
            display:flex; align-items:center; gap:8px;
            padding:7px 10px 7px 18px; margin-left:6px; margin-bottom:2px;
            border-radius:8px; font-size:0.88rem; font-weight:500;
            color:#33415e !important; text-decoration:none !important;
            transition:background 0.15s;
        " onmouseover="this.style.background='rgba(45,212,191,0.16)';this.style.color='#0f2460'"
           onmouseout="this.style.background='';this.style.color='#33415e'">
            🔩 {t("link_assembly")}
        </a>
        <a href="/test_station" target="_self" style="
            display:flex; align-items:center; gap:8px;
            padding:7px 10px 7px 18px; margin-left:6px; margin-bottom:2px;
            border-radius:8px; font-size:0.88rem; font-weight:500;
            color:#33415e !important; text-decoration:none !important;
            transition:background 0.15s;
        " onmouseover="this.style.background='rgba(45,212,191,0.16)';this.style.color='#0f2460'"
           onmouseout="this.style.background='';this.style.color='#33415e'">
            🧪 {t("link_test_station")}
        </a>
        <a href="/packaging" target="_self" style="
            display:flex; align-items:center; gap:8px;
            padding:7px 10px 7px 18px; margin-left:6px; margin-bottom:2px;
            border-radius:8px; font-size:0.88rem; font-weight:500;
            color:#33415e !important; text-decoration:none !important;
            transition:background 0.15s;
        " onmouseover="this.style.background='rgba(45,212,191,0.16)';this.style.color='#0f2460'"
           onmouseout="this.style.background='';this.style.color='#33415e'">
            📦 {t("link_packaging")}
        </a>
        <a href="/total_worktime" target="_self" style="
            display:flex; align-items:center; gap:8px;
            padding:7px 10px 7px 18px; margin-left:6px; margin-bottom:2px;
            border-radius:8px; font-size:0.88rem; font-weight:500;
            color:#33415e !important; text-decoration:none !important;
            transition:background 0.15s;
        " onmouseover="this.style.background='rgba(45,212,191,0.16)';this.style.color='#0f2460'"
           onmouseout="this.style.background='';this.style.color='#33415e'">
            ⏱ {t("link_total_worktime")}
        </a>
        """, unsafe_allow_html=True)

# ── NAS 通用工具 ──────────────────────────────────────────────────────────────

def first_existing_dir(*dirs):
    """回傳第一個存在的資料夾；都不存在時回傳第一個（讓錯誤訊息帶得出原路徑）。

    NAS 上的年度資料夾會改名（例：`2025早會` → `2026`），寫死路徑隔年就變假離線。
    """
    for d in dirs:
        if d and _os.path.isdir(d):
            return d
    return dirs[0] if dirs else None


# 「另存複本」會在檔名前面加這些字，比對前綴前要先剝掉
_COPY_PREFIXES = ('複本 ', '複本', '副本 ', '副本', 'Copy of ', '- 複本')


def _strip_copy_prefix(name: str) -> str:
    for p in _COPY_PREFIXES:
        if name.startswith(p):
            return name[len(p):].lstrip()
    return name


def find_latest_nas_file_status(nas_dir: str, prefix: str,
                                exts=('.xlsx', '.xlsm', '.xls')):
    """
    在 nas_dir 內找出檔名以 prefix 開頭、副檔名符合 exts 的最新檔案。

    - 檔名前的「複本 」「副本 」會先剝掉再比對前綴
      （現場常直接另存複本，例：`複本 加工廠互調料滙整表-20260714.xlsm`）。
    - 排除 ~$ 暫存檔。
    - 排序：以剝掉複本字樣後的檔名為主（檔名含日期），同名時取較新的存檔。

    回傳 (完整路徑, 檔名, 狀態)，狀態為 'ok' / 'no_match'（資料夾讀得到但沒有符合的檔）
    / 'offline'（資料夾讀不到）。
    """
    try:
        names = _os.listdir(nas_dir)
    except Exception:
        return None, None, 'offline'

    cands = []
    for f in names:
        if f.startswith('~$'):
            continue
        if not any(f.lower().endswith(e) for e in exts):
            continue
        base = _strip_copy_prefix(f)
        if not base.startswith(prefix):
            continue
        try:
            mt = _os.path.getmtime(_os.path.join(nas_dir, f))
        except OSError:
            mt = 0
        cands.append((base, mt, f))

    if not cands:
        return None, None, 'no_match'

    cands.sort()
    latest = cands[-1][2]
    return _os.path.join(nas_dir, latest), latest, 'ok'


def find_latest_nas_file(nas_dir: str, prefix: str, exts=('.xlsx', '.xlsm', '.xls')):
    """相容舊介面：回傳 (完整路徑, 檔名) 或 (None, None)。"""
    path, name, _ = find_latest_nas_file_status(nas_dir, prefix, exts)
    return path, name

def render_nas_loader(key: str, nas_dir: str, prefix: str, label: str,
                      types: list = None, exts: tuple = ('.xlsx', '.xlsm', '.xls')):
    """
    通用 NAS 檔案自動載入元件，在 st.sidebar 內呼叫。
    自動偵測 nas_dir 內最新的 prefix 開頭檔案，提供一鍵載入。
    手動上傳優先權最高。
    回傳 src：UploadedFile | str(路徑) | None
    """
    if types is None:
        types = ['xlsx', 'xls', 'xlsm']

    skey_path = f"_tf_path_{key}"
    skey_name = f"_tf_name_{key}"

    nas_path, nas_name, nas_status = find_latest_nas_file_status(nas_dir, prefix, exts)

    if nas_path:
        # NAS 有連線 → 自動載入，不需按鈕
        st.session_state[skey_path] = nas_path
        st.session_state[skey_name] = nas_name
        st.success("✅ NAS 已連線，已自動載入最新版")
        st.caption(f"**{nas_name}**")
        if st.button("🔄 重新偵測 NAS", use_container_width=True, key=f"_btn_ref_{key}"):
            st.session_state.pop(skey_path, None)
            st.rerun()
    elif nas_status == 'no_match':
        # 連得到資料夾但沒有符合的檔案 —— 多半是檔名或資料夾被改，不是離線
        st.warning(f"⚠️ NAS 連得到，但資料夾內沒有「{prefix}…」的檔案")
        st.caption(f"路徑：{nas_dir}")
        st.session_state.pop(skey_path, None)
    else:
        st.warning("⚠️ NAS 離線，請手動上傳")
        st.caption(f"路徑：{nas_dir}")
        st.session_state.pop(skey_path, None)

    st.caption("手動上傳可覆蓋 NAS 版本：")
    uploaded = st.file_uploader(label, type=types, key=f"_upload_{key}")

    if uploaded:
        st.session_state.pop(skey_path, None)
        return uploaded
    elif skey_path in st.session_state:
        return st.session_state[skey_path]
    return None

# ── 供需表 NAS 自動載入（共用）─────────────────────────────────────────────────

_NAS_SD_DIR = "//192.168.2.34/MO_Storage/ORing MO/ORing-MO 鼎新系統報表/LRPMR05庫存供需表(分倉)-每日(AM4-00抓取)(Ian提供)-2020"
_LOCAL_SD   = _os.path.join(_os.path.dirname(__file__), "..", "data", "sd_latest.xlsx")
_LOCAL_DONE = _os.path.join(_os.path.dirname(__file__), "..", "data", "sd_fetch_done.txt")

def _find_latest_nas_sd():
    """回傳 (完整路徑, 檔名, 是否今日)，NAS 不可達則 (None, None, False)"""
    try:
        today_tag = _dt.now().strftime('%Y%m%d')
        files = sorted([
            f for f in _os.listdir(_NAS_SD_DIR)
            if f.startswith('供需表(分倉)-') and f.endswith('.xlsx')
        ])
        if not files:
            return None, None, False
        latest   = files[-1]
        is_today = today_tag in latest
        return _os.path.join(_NAS_SD_DIR, latest), latest, is_today
    except Exception:
        return None, None, False

def _local_cache_date():
    """回傳本機快取的日期字串，無則 None"""
    try:
        if _os.path.exists(_LOCAL_DONE):
            return open(_LOCAL_DONE, encoding='utf-8').read().strip()
    except Exception:
        pass
    return None

def render_sd_loader(key: str = "sd", label: str = "📂 上傳供需表（選填覆蓋）"):
    """
    在 st.sidebar 內呼叫。
    自動偵測 NAS 最新供需表，NAS 離線時 fallback 到本機快取。
    手動上傳的檔案優先權最高。
    回傳 sd_source：UploadedFile | str(路徑) | None
    """
    skey_path = f"_sd_path_{key}"
    skey_name = f"_sd_name_{key}"
    today_str = _dt.now().strftime('%Y%m%d')

    nas_path, nas_name, nas_is_today = _find_latest_nas_sd()
    cache_date = _local_cache_date()
    local_ok   = _os.path.exists(_LOCAL_SD)

    if nas_path:
        tag = "（今日 ✅）" if nas_is_today else "（非今日）"
        # NAS 有連線 → 自動載入，不需按鈕
        st.session_state[skey_path] = nas_path
        st.session_state[skey_name] = nas_name
        st.success("✅ NAS 已連線，供需表已自動載入")
        st.caption(f"**{nas_name}** {tag}")
        if st.button("🔄 重新偵測 NAS", use_container_width=True, key=f"_btn_ref_{key}"):
            st.session_state.pop(skey_path, None)
            st.rerun()
    else:
        st.warning("⚠️ NAS 離線")
        st.session_state.pop(skey_path, None)
        if local_ok:
            cl = f"今日（{cache_date}）" if cache_date == today_str else f"前次備份（{cache_date or '?'}）"
            st.session_state[skey_path] = _LOCAL_SD
            st.session_state[skey_name] = f"sd_latest.xlsx（{cl}）"
            st.info(f"💾 已自動載入本機快取：{cl}")

    st.caption("手動上傳可覆蓋 NAS 版本：")
    uploaded = st.file_uploader(label, type=["xlsx", "xls", "csv"], key=f"_upload_{key}")

    if uploaded:
        st.session_state.pop(skey_path, None)
        return uploaded
    elif skey_path in st.session_state:
        return st.session_state[skey_path]
    return None

def read_source(src) -> bytes:
    """從 UploadedFile 或路徑字串讀取 bytes。"""
    if src is None:
        return b""
    if isinstance(src, str):
        # NAS 檔案可能正被排程任務覆寫，一次性 f.read() 在 SMB 網路磁碟上
        # 偶爾會炸 OSError([Errno 22] Invalid argument)；改用分塊讀取 + 重試降低風險
        last_err = None
        for _attempt in range(3):
            try:
                chunks = []
                with open(src, 'rb') as f:
                    while True:
                        chunk = f.read(1024 * 1024)
                        if not chunk:
                            break
                        chunks.append(chunk)
                return b"".join(chunks)
            except OSError as e:
                last_err = e
                _time.sleep(1)
        raise last_err
    data = src.read()
    if hasattr(src, 'seek'):
        src.seek(0)
    return data

def source_filename(src) -> str:
    """取得檔名，支援 UploadedFile 或路徑字串。"""
    if src is None:
        return ''
    if isinstance(src, str):
        return _os.path.basename(src)
    return getattr(src, 'name', 'file.xlsx')

def source_is_csv(src) -> bool:
    """判斷來源是否為 CSV。"""
    return source_filename(src).lower().endswith('.csv')
