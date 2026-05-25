import subprocess
import sys
import base64
from pathlib import Path
import streamlit as st
import streamlit.components.v1 as components

# ── 常數 ──────────────────────────────────────────────────────────────────────

PRIORITY_WHS = ["電子倉", "包材倉", "機構倉", "成品倉"]

ORING_LOGO = "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"

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
    }
    /* 收合 / 展開按鈕全部隱藏（側欄已鎖定，不需要這些控制） */
    [data-testid="stSidebarCollapseButton"],
    [data-testid="stSidebarCollapsedControl"],
    [data-testid="collapsedControl"] {
        display: none !important;
    }

    [data-testid="stAppViewContainer"] {
        background: linear-gradient(160deg, #eef2fb 0%, #e8eef8 50%, #dde6f5 100%);
    }
    [data-testid="stSidebar"] {
        background: #ffffff;
        border-right: 1.5px solid #e2e8f0;
        box-shadow: 4px 0 24px rgba(29,78,216,0.06);
    }
    [data-testid="stSidebarNav"] { display: none !important; }

    /* ── Status card 3D ── */
    .status-card {
        padding: 16px 22px; border-radius: 12px;
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-left: 4px solid #1d4ed8;
        margin-bottom: 20px;
        box-shadow: 0 4px 20px rgba(29,78,216,0.08), 0 1px 4px rgba(0,0,0,0.04);
    }
    .status-card h3 { color: #1e293b; margin: 0 0 6px 0; font-size: 1rem; }
    .status-card b { color: #1d4ed8; }

    /* ── Table / download ── */
    .stDataFrame {
        border-radius: 12px !important;
        border: 1px solid #e2e8f0 !important;
        box-shadow: 0 2px 12px rgba(0,0,0,0.06) !important;
        overflow: hidden;
    }
    hr { border-color: #e2e8f0 !important; }
    .stDownloadButton > button {
        background: linear-gradient(135deg, #1d4ed8, #1e40af) !important;
        color: white !important; border: none !important;
        border-radius: 8px !important; font-weight: 600 !important;
        font-size: 0.95rem !important;
        box-shadow: 0 4px 14px rgba(29,78,216,0.35) !important;
        transition: transform 0.15s, box-shadow 0.15s !important;
    }
    .stDownloadButton > button:hover {
        transform: translateY(-1px) !important;
        box-shadow: 0 6px 20px rgba(29,78,216,0.45) !important;
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

    /* ── Block / metric card ── */
    [data-testid="stMetric"] {
        background: white; border-radius: 12px; padding: 16px 20px;
        box-shadow: 0 2px 12px rgba(0,0,0,0.06);
        border: 1px solid #e2e8f0;
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
        background: linear-gradient(135deg, #0f2460 0%, #1d4ed8 60%, #3b82f6 100%) !important;
        color: #ffffff !important;
        border: none !important;
        box-shadow:
            0 4px 14px rgba(29,78,216,0.50),
            0 2px 4px rgba(0,0,0,0.20),
            inset 0 1px 0 rgba(255,255,255,0.22) !important;
    }
    [data-testid="stHorizontalBlock"] .stButton > button[kind="primary"]:hover {
        transform: translateY(-2px) scale(1.04) !important;
        box-shadow:
            0 7px 20px rgba(29,78,216,0.60),
            0 3px 6px rgba(0,0,0,0.22),
            inset 0 1px 0 rgba(255,255,255,0.25) !important;
    }
    [data-testid="stHorizontalBlock"] .stButton > button[kind="secondary"] {
        background: linear-gradient(135deg, #f8faff 0%, #e8eef8 100%) !important;
        color: #3b5280 !important;
        border: 1.5px solid #c3d0e8 !important;
        box-shadow:
            0 3px 10px rgba(0,0,0,0.10),
            0 1px 3px rgba(0,0,0,0.06),
            inset 0 1px 0 rgba(255,255,255,0.90) !important;
    }
    [data-testid="stHorizontalBlock"] .stButton > button[kind="secondary"]:hover {
        background: linear-gradient(135deg, #ffffff 0%, #dde8f8 100%) !important;
        color: #1d4ed8 !important;
        border-color: #93a8d8 !important;
        transform: translateY(-2px) scale(1.04) !important;
        box-shadow:
            0 5px 16px rgba(29,78,216,0.18),
            0 2px 4px rgba(0,0,0,0.08),
            inset 0 1px 0 rgba(255,255,255,0.95) !important;
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

def render_header(title: str, subtitle: str, badge: str = "Production Management System", show_logo: bool = True):
    logo_data = _logo_b64() if show_logo else ""
    logo_html = (
        f'<img src="data:image/png;base64,{logo_data}" '
        f'style="height:60px; background:white; border-radius:10px; '
        f'padding:6px 14px; box-shadow:0 2px 10px rgba(0,0,0,0.18); flex-shrink:0;" />'
        if logo_data else ""
    )
    components.html(f"""
<!DOCTYPE html><html><head><meta charset="utf-8">
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ background:transparent; padding:4px 0; }}
.header {{
    display: flex; align-items: center; gap: 22px;
    background: linear-gradient(135deg, #0f2460 0%, #1a3a8f 40%, #1d4ed8 100%);
    border-radius: 16px;
    padding: 20px 36px;
    box-shadow:
        0 10px 40px rgba(15,36,96,0.45),
        0 4px 12px rgba(0,0,0,0.25),
        inset 0 1px 0 rgba(255,255,255,0.12);
    position: relative; overflow: hidden;
}}
.header::before {{
    content: '';
    position: absolute; top: 0; left: 0; right: 0;
    height: 1px;
    background: linear-gradient(90deg, transparent, rgba(255,255,255,0.3), transparent);
}}
.header::after {{
    content: '';
    position: absolute; top: -60px; right: -40px;
    width: 220px; height: 220px; border-radius: 50%;
    background: radial-gradient(circle, rgba(99,172,255,0.12) 0%, transparent 70%);
    pointer-events: none;
}}
.badge {{
    font-size: 0.68rem; font-weight: 700; letter-spacing: 0.14em;
    color: #93c5fd; text-transform: uppercase; margin-bottom: 5px;
    text-shadow: 0 1px 4px rgba(0,0,0,0.3);
}}
.title {{
    color: #ffffff; font-size: 1.75rem; font-weight: 900;
    letter-spacing: 0.01em; line-height: 1.15;
    text-shadow: 0 2px 8px rgba(0,0,0,0.3);
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
}}
.subtitle {{
    color: #bfdbfe; font-size: 0.85rem; margin-top: 5px;
    letter-spacing: 0.03em;
    text-shadow: 0 1px 4px rgba(0,0,0,0.2);
}}
</style></head><body>
<div class="header">
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
    with st.sidebar:
        st.markdown(f"""
        <div style="
            text-align:center; padding:22px 12px 18px; margin-bottom:16px;
            background: linear-gradient(160deg, #0f2460, #1a3a8f);
            border-radius: 14px;
            box-shadow: 0 6px 24px rgba(15,36,96,0.35), 0 2px 6px rgba(0,0,0,0.2),
                        inset 0 1px 0 rgba(255,255,255,0.12);
            position: relative; overflow: hidden;
        ">
            <div style="position:absolute; top:0; left:0; right:0; height:1px;
                background:linear-gradient(90deg,transparent,rgba(255,255,255,0.3),transparent);"></div>
            <div style="color:#ffffff; font-size:1.45rem; font-weight:900; line-height:1.55;
                letter-spacing:0.02em;
                text-shadow: 0 2px 8px rgba(0,0,0,0.4), 0 1px 0 rgba(255,255,255,0.1);">
                {t("company_name")}
            </div>
            <div style="color:#93c5fd; font-size:0.78rem; margin-top:7px;
                letter-spacing:0.1em; font-weight:700; text-transform:uppercase;
                text-shadow: 0 1px 4px rgba(0,0,0,0.3);">
                ORing Industrial Networking
            </div>
            <div style="margin-top:12px; display:inline-block;
                background:rgba(255,255,255,0.15); border:1px solid rgba(255,255,255,0.25);
                border-radius:20px; padding:4px 14px;
                font-size:0.72rem; color:#e0eaff; font-weight:700; letter-spacing:0.06em;
                box-shadow: 0 2px 8px rgba(0,0,0,0.2);">
                {t("system_ver")}
            </div>
        </div>
        """, unsafe_allow_html=True)

        # 首頁按鈕
        st.markdown("""
        <style>
        [data-testid="stSidebar"] [data-testid="stLinkButton"] > a {
            background: linear-gradient(135deg, #0f2460 0%, #1d4ed8 60%, #3b82f6 100%) !important;
            color: #ffffff !important;
            font-weight: 800 !important;
            font-size: 0.93rem !important;
            letter-spacing: 0.04em !important;
            border: none !important;
            border-radius: 10px !important;
            box-shadow: 0 4px 16px rgba(29,78,216,0.40), inset 0 1px 0 rgba(255,255,255,0.18) !important;
            text-shadow: 0 1px 4px rgba(0,0,0,0.4) !important;
            margin-bottom: 4px !important;
        }
        [data-testid="stSidebar"] [data-testid="stLinkButton"] > a:hover {
            background: linear-gradient(135deg, #1a3a8f 0%, #2563eb 60%, #60a5fa 100%) !important;
            box-shadow: 0 6px 20px rgba(29,78,216,0.55) !important;
        }
        </style>
        """, unsafe_allow_html=True)
        st.link_button("🏠  首頁  Home", url="/", use_container_width=True)

        st.markdown(f"""<div style="color:#94a3b8; font-size:0.68rem; font-weight:800;
            letter-spacing:0.12em; text-transform:uppercase; margin-bottom:10px;">
            {t("nav_title")}</div>""", unsafe_allow_html=True)

        # 物管 MC
        st.markdown(f"""
        <div style="display:flex; align-items:center; gap:8px; padding:9px 10px 7px;
                    background:#eff6ff; border-radius:8px; margin-bottom:3px;">
            <span style="font-size:1.1rem;">📦</span>
            <div>
                <div style="font-size:1.0rem; font-weight:800; color:#1e40af; line-height:1.2;">{t("dept_mc")}</div>
                <div style="font-size:0.67rem; color:#3b82f6; letter-spacing:0.04em;">{t("dept_mc_sub")}</div>
            </div>
        </div>
        """, unsafe_allow_html=True)
        st.markdown(f"""
        <a href="/transfer" target="_self" style="
            display:flex; align-items:center; gap:8px;
            padding:7px 10px 7px 18px; margin-left:6px; margin-bottom:2px;
            border-radius:8px; font-size:0.88rem; font-weight:500;
            color:#475569 !important; text-decoration:none !important;
            transition:background 0.15s;
        " onmouseover="this.style.background='#f1f5f9';this.style.color='#1e293b'"
           onmouseout="this.style.background='';this.style.color='#475569'">
            📊 {t("link_transfer")}
        </a>
        <a href="/outsource" target="_self" style="
            display:flex; align-items:center; gap:8px;
            padding:7px 10px 7px 18px; margin-left:6px; margin-bottom:2px;
            border-radius:8px; font-size:0.88rem; font-weight:500;
            color:#475569 !important; text-decoration:none !important;
            transition:background 0.15s;
        " onmouseover="this.style.background='#f1f5f9';this.style.color='#1e293b'"
           onmouseout="this.style.background='';this.style.color='#475569'">
            🏭 {t("link_outsource")}
        </a>
        <a href="/h2o" target="_self" style="
            display:flex; align-items:center; gap:8px;
            padding:7px 10px 7px 18px; margin-left:6px; margin-bottom:2px;
            border-radius:8px; font-size:0.88rem; font-weight:500;
            color:#475569 !important; text-decoration:none !important;
            transition:background 0.15s;
        " onmouseover="this.style.background='#f1f5f9';this.style.color='#1e293b'"
           onmouseout="this.style.background='';this.style.color='#475569'">
            💧 {t("link_h2o")}
        </a>
        <a href="/guozhi" target="_self" style="
            display:flex; align-items:center; gap:8px;
            padding:7px 10px 7px 18px; margin-left:6px; margin-bottom:2px;
            border-radius:8px; font-size:0.88rem; font-weight:500;
            color:#475569 !important; text-decoration:none !important;
            transition:background 0.15s;
        " onmouseover="this.style.background='#f1f5f9';this.style.color='#1e293b'"
           onmouseout="this.style.background='';this.style.color='#475569'">
            🏭 {t("link_guozhi")}
        </a>
        <a href="/factory" target="_self" style="
            display:flex; align-items:center; gap:8px;
            padding:7px 10px 7px 18px; margin-left:6px; margin-bottom:2px;
            border-radius:8px; font-size:0.88rem; font-weight:500;
            color:#475569 !important; text-decoration:none !important;
            transition:background 0.15s;
        " onmouseover="this.style.background='#f1f5f9';this.style.color='#1e293b'"
           onmouseout="this.style.background='';this.style.color='#475569'">
            🏭 {t("link_factory")}
        </a>
        """, unsafe_allow_html=True)

        # 生管 PC
        st.markdown(f"""
        <div style="display:flex; align-items:center; gap:8px; padding:9px 10px 7px;
                    background:#f0fdf4; border-radius:8px; margin:8px 0 3px;">
            <span style="font-size:1.1rem;">🏗</span>
            <div>
                <div style="font-size:1.0rem; font-weight:800; color:#15803d; line-height:1.2;">{t("dept_pc")}</div>
                <div style="font-size:0.67rem; color:#22c55e; letter-spacing:0.04em;">{t("dept_pc_sub")}</div>
            </div>
        </div>
        """, unsafe_allow_html=True)
        st.markdown(f"""
        <a href="/wo_progress" target="_self" style="
            display:flex; align-items:center; gap:8px;
            padding:7px 10px 7px 18px; margin-left:6px; margin-bottom:2px;
            border-radius:8px; font-size:0.88rem; font-weight:500;
            color:#475569 !important; text-decoration:none !important;
            transition:background 0.15s;
        " onmouseover="this.style.background='#f1f5f9';this.style.color='#1e293b'"
           onmouseout="this.style.background='';this.style.color='#475569'">
            📋 {t("link_wo_progress")}
        </a>
        """, unsafe_allow_html=True)
        st.markdown(f"""
        <a href="/shortage_detail" target="_self" style="
            display:flex; align-items:center; gap:8px;
            padding:7px 10px 7px 18px; margin-left:6px; margin-bottom:2px;
            border-radius:8px; font-size:0.88rem; font-weight:500;
            color:#475569 !important; text-decoration:none !important;
            transition:background 0.15s;
        " onmouseover="this.style.background='#f1f5f9';this.style.color='#1e293b'"
           onmouseout="this.style.background='';this.style.color='#475569'">
            📊 {t("link_shortage_detail")}
        </a>
        <a href="/production_tracker" target="_self" style="
            display:flex; align-items:center; gap:8px;
            padding:7px 10px 7px 18px; margin-left:6px; margin-bottom:2px;
            border-radius:8px; font-size:0.88rem; font-weight:500;
            color:#475569 !important; text-decoration:none !important;
            transition:background 0.15s;
        " onmouseover="this.style.background='#f1f5f9';this.style.color='#1e293b'"
           onmouseout="this.style.background='';this.style.color='#475569'">
            🏭 {t("link_production_tracker")}
        </a>
        <a href="/monthly_cost" target="_self" style="
            display:flex; align-items:center; gap:8px;
            padding:7px 10px 7px 18px; margin-left:6px; margin-bottom:2px;
            border-radius:8px; font-size:0.88rem; font-weight:500;
            color:#475569 !important; text-decoration:none !important;
            transition:background 0.15s;
        " onmouseover="this.style.background='#f1f5f9';this.style.color='#1e293b'"
           onmouseout="this.style.background='';this.style.color='#475569'">
            📊 {t("link_monthly_cost")}
        </a>
        <a href="/scheduling" target="_self" style="
            display:flex; align-items:center; gap:8px;
            padding:7px 10px 7px 18px; margin-left:6px; margin-bottom:2px;
            border-radius:8px; font-size:0.88rem; font-weight:500;
            color:#475569 !important; text-decoration:none !important;
            transition:background 0.15s;
        " onmouseover="this.style.background='#f1f5f9';this.style.color='#1e293b'"
           onmouseout="this.style.background='';this.style.color='#475569'">
            🗓 {t("link_scheduling")}
        </a>
        """, unsafe_allow_html=True)

        # 倉管 WH
        st.markdown(f"""
        <div style="display:flex; align-items:center; gap:8px; padding:9px 10px 7px;
                    background:#f5f3ff; border-radius:8px; margin:4px 0 3px;">
            <span style="font-size:1.1rem;">🏬</span>
            <div>
                <div style="font-size:1.0rem; font-weight:800; color:#6d28d9; line-height:1.2;">{t("dept_wh")}</div>
                <div style="font-size:0.67rem; color:#8b5cf6; letter-spacing:0.04em;">{t("dept_wh_sub")}</div>
            </div>
        </div>
        """, unsafe_allow_html=True)
        st.markdown(f"""
        <a href="/daily_inbound" target="_self" style="
            display:flex; align-items:center; gap:8px;
            padding:7px 10px 7px 18px; margin-left:6px; margin-bottom:2px;
            border-radius:8px; font-size:0.88rem; font-weight:500;
            color:#475569 !important; text-decoration:none !important;
            transition:background 0.15s;
        " onmouseover="this.style.background='#f5f3ff';this.style.color='#6d28d9'"
           onmouseout="this.style.background='';this.style.color='#475569'">
            📥 {t("link_daily_inbound")}
        </a>
        <a href="/daily_picking" target="_self" style="
            display:flex; align-items:center; gap:8px;
            padding:7px 10px 7px 18px; margin-left:6px; margin-bottom:2px;
            border-radius:8px; font-size:0.88rem; font-weight:500;
            color:#475569 !important; text-decoration:none !important;
            transition:background 0.15s;
        " onmouseover="this.style.background='#f5f3ff';this.style.color='#6d28d9'"
           onmouseout="this.style.background='';this.style.color='#475569'">
            📋 {t("link_daily_picking")}
        </a>
        <a href="/wh_staff" target="_self" style="
            display:flex; align-items:center; gap:8px;
            padding:7px 10px 7px 18px; margin-left:6px; margin-bottom:2px;
            border-radius:8px; font-size:0.88rem; font-weight:500;
            color:#475569 !important; text-decoration:none !important;
            transition:background 0.15s;
        " onmouseover="this.style.background='#f5f3ff';this.style.color='#6d28d9'"
           onmouseout="this.style.background='';this.style.color='#475569'">
            👥 {t("link_wh_staff")}
        </a>
        """, unsafe_allow_html=True)
