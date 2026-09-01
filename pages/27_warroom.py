# -*- coding: utf-8 -*-
"""ERP × AI 營運戰情室 —— 白色科技 3D 介面。"""
import html
import os
import sys
from datetime import date, datetime

import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from utils.shared import render_sidebar
from db import queries as wh_db
from utils import warroom_data as wd

st.set_page_config(page_title="營運戰情室", page_icon="🛰️", layout="wide")

# ── 分享模式：網址帶 ?kiosk=1 時完全不出左側目錄（給區網同仁看的乾淨版）──
# 目錄內容整個不 render，不只是用 CSS 藏起來，所以其他頁面的連結不會出現在 DOM 裡。
KIOSK = str(st.query_params.get("kiosk", "")).lower() in ("1", "true", "yes", "on")

if not KIOSK:
    render_sidebar()

# ── 資料同步：每 5 分鐘自動刷新，每次執行檢查 NAS 是否有新存檔（有就立即匯入）──
# 與 16_wh_dashboard 走同一支 sync_if_newer，避免兩頁停在不同版本的資料
st_autorefresh(interval=5 * 60 * 1000, key="wr_autorefresh")
wd.ensure_latest_db()

_DB_MTIME = wh_db.db_mtime()          # 調件備料統計 的存檔時間（取自 import_log）
_DB_KEY = str(_DB_MTIME)              # 快取鍵：資料一換版，快取就跟著失效
_DATA_TS = _DB_MTIME.strftime("%m/%d %H:%M") if _DB_MTIME is not None else "⚠️ 離線"

# 出貨排程來自另一個來源檔（早會的 簡版-工單缺料狀況），版本要分開追
_SD_MTIME = wh_db.sched_mtime()
_SD_KEY = str(_SD_MTIME)
_SD_TS = _SD_MTIME.strftime("%m/%d %H:%M") if _SD_MTIME is not None else "—"

# ── 目錄收合／還原：不用 Streamlit 原生機制（此版收合後無法還原），自行控制 ──
if "wr_sb_open" not in st.session_state:
    st.session_state["wr_sb_open"] = True

if not KIOSK:
    with st.sidebar:
        if st.button("◀　收合目錄", key="wr_sb_close", use_container_width=True):
            st.session_state["wr_sb_open"] = False
            st.rerun()

# kiosk 模式連 Streamlit 內建的多頁導覽與展開箭頭都一起關掉
_SB_KIOSK = """<style>
[data-testid="stSidebar"],[data-testid="stSidebarNav"],
[data-testid="stSidebarCollapsedControl"],[data-testid="collapsedControl"]{
  display:none!important;}
section.main,[data-testid="stMain"]{margin-left:0!important;}
</style>"""
_SB_OPEN = """<style>
[data-testid="stSidebar"],[data-testid="stSidebar"][aria-expanded="true"],
[data-testid="stSidebar"][aria-expanded="false"]{
  transform:translateX(0)!important;width:244px!important;min-width:244px!important;
  max-width:244px!important;display:flex!important;visibility:visible!important;
  opacity:1!important;pointer-events:all!important;overflow:visible!important;
  transition:width .22s ease,opacity .22s ease!important;}
</style>"""
_SB_SHUT = """<style>
[data-testid="stSidebar"],[data-testid="stSidebar"][aria-expanded="true"],
[data-testid="stSidebar"][aria-expanded="false"]{
  transform:translateX(0)!important;width:0!important;min-width:0!important;
  max-width:0!important;display:flex!important;visibility:visible!important;
  opacity:0!important;pointer-events:none!important;overflow:hidden!important;
  transition:width .22s ease,opacity .22s ease!important;}
</style>"""
if KIOSK:
    st.markdown(_SB_KIOSK, unsafe_allow_html=True)
else:
    st.markdown(_SB_OPEN if st.session_state["wr_sb_open"] else _SB_SHUT,
                unsafe_allow_html=True)

    if not st.session_state["wr_sb_open"]:
        _r1, _r2 = st.columns([1, 9])
        with _r1:
            if st.button("▶　展開目錄", key="wr_sb_open_btn", use_container_width=True):
                st.session_state["wr_sb_open"] = True
                st.rerun()

# ══════════════════════════════════════════════════════════════
# 場景與玻璃樣式
# ══════════════════════════════════════════════════════════════
st.markdown("""
<style>
.stApp{
  background:radial-gradient(1400px 900px at 20% 4%, #F7FBFF 0%, rgba(247,251,255,0) 58%),
             linear-gradient(158deg,#EAF3FC 0%,#D6E8F8 36%,#C4DBF2 68%,#D8EAF8 100%) fixed;
}
.block-container{padding-top:1.2rem;max-width:100%;}
#MainMenu,footer{visibility:hidden;}
/* header 透明，否則會蓋掉右上角的時鐘與底圖 */
[data-testid="stHeader"]{background:transparent !important;box-shadow:none !important;}
[data-testid="stToolbar"]{right:150px !important;}
[data-testid="stSidebarNav"],[data-testid="stSidebarNavItems"],
[data-testid="stSidebarNavLink"],[data-testid="stSidebarNavSeparator"]{display:none !important;}
[data-testid="stSidebarHeader"]{padding-bottom:0 !important;}
[data-testid="stSidebarUserContent"]{padding-top:.5rem !important;}

[data-testid="stExpandSidebarButton"]{z-index:999996 !important;}
[data-testid="stSidebarCollapsedControl"]{z-index:999995;}
[data-testid="stSidebar"]{z-index:999994;}
[data-testid="stExpandSidebarButton"],
[data-testid="stSidebar"] [data-testid="stBaseButton-headerNoPadding"]{display:none !important;}
/* 側欄寬度改由下方 session state 動態注入 */


/* 環境光暈 */
.stApp::before{content:"";position:fixed;inset:0;pointer-events:none;z-index:0;
  background:
    radial-gradient(620px 520px at 8% 12%,  rgba(94,159,228,.42), transparent 62%),
    radial-gradient(560px 480px at 92% 8%,  rgba(63,184,220,.38), transparent 62%),
    radial-gradient(700px 520px at 68% 96%, rgba(127,169,238,.34), transparent 64%);}
.block-container{position:relative;z-index:2;}

/* ── 3D 場景：天花燈 / 光束 / 玻璃牆 / 地球 / 神經網路 / 地板 ── */
#wr-scene{position:fixed;inset:0;z-index:0;pointer-events:none;overflow:hidden;
  perspective:2200px;perspective-origin:50% 42%;}
#wr-scene .ceil{position:absolute;left:50%;top:-19vw;width:88vw;height:31vw;transform:translateX(-50%);
  border-radius:50%;border:3px solid rgba(255,255,255,.95);
  background:radial-gradient(60% 78% at 50% 100%, rgba(255,255,255,.85), rgba(255,255,255,0) 70%);
  box-shadow:0 34px 70px -18px rgba(120,190,255,.75), inset 0 -26px 50px rgba(255,255,255,.9);}
#wr-scene .ceil2{position:absolute;left:50%;top:-14vw;width:66vw;height:22vw;transform:translateX(-50%);
  border-radius:50%;border:2px solid rgba(255,255,255,.8);
  box-shadow:0 22px 54px -16px rgba(140,200,255,.6);}
#wr-scene .ray{position:absolute;border-radius:50%;filter:blur(26px);}
#wr-scene .r1{left:-14vw;top:56%;width:66vw;height:4.4vw;transform:rotate(-7deg);
  background:linear-gradient(90deg,rgba(255,255,255,0),rgba(186,226,255,.95),rgba(255,255,255,0));}
#wr-scene .r2{left:-16vw;top:63%;width:58vw;height:2.9vw;transform:rotate(-4deg);
  background:linear-gradient(90deg,rgba(255,255,255,0),rgba(150,205,250,.8),rgba(255,255,255,0));}
#wr-scene .r3{left:-12vw;top:70%;width:50vw;height:2.1vw;transform:rotate(-9deg);
  background:linear-gradient(90deg,rgba(255,255,255,0),rgba(206,236,255,.9),rgba(255,255,255,0));}
#wr-scene .wall{position:absolute;right:-2vw;top:4vw;width:62vw;height:36vw;
  transform:rotateY(-19deg) rotateX(2deg);transform-origin:100% 50%;}
#wr-scene .wp{position:absolute;border-radius:14px;border:1px solid rgba(255,255,255,.85);
  background:linear-gradient(150deg,rgba(226,242,255,.5),rgba(196,224,250,.28));
  box-shadow:0 20px 46px -18px rgba(20,70,130,.4), inset 0 1px 0 rgba(255,255,255,.9);}
#wr-scene .wl{position:absolute;height:5px;border-radius:99px;background:rgba(90,150,215,.36);}
#wr-scene .wb{position:absolute;bottom:0;border-radius:3px 3px 0 0;}
#wr-scene .globe{position:absolute;right:24%;top:7vw;width:20vw;height:20vw;
  filter:drop-shadow(0 26px 44px rgba(20,80,150,.45));}
#wr-scene .zodiac{position:absolute;right:2%;top:4.6vw;width:25vw;height:25vw;
  filter:drop-shadow(0 26px 42px rgba(12,52,110,.5));}
#wr-scene .z-stars circle{animation:zTwinkle 5.2s ease-in-out infinite;}
#wr-scene .z-stars circle:nth-child(3n){animation-delay:1.4s;}
#wr-scene .z-stars circle:nth-child(3n+1){animation-delay:2.9s;}
@keyframes zTwinkle{0%,100%{opacity:.4}50%{opacity:1}}
#wr-scene .z-sig{font-family:"Georgia","Times New Roman",serif;font-size:30px;font-weight:700;
  fill:#0B3F86;letter-spacing:.07em;}
#wr-scene .z-sub{font-family:ui-monospace,Consolas,monospace;font-size:10.5px;
  fill:#1B6BB8;letter-spacing:.24em;opacity:.8;}
@media (prefers-reduced-motion:reduce){#wr-scene .z-stars circle{animation:none;}}
#wr-scene .floor{position:absolute;left:0;right:0;bottom:0;height:26vh;
  background:linear-gradient(180deg,rgba(255,255,255,0) 0%,rgba(240,249,255,.75) 26%,
             rgba(214,236,252,.95) 62%,rgba(196,225,247,1) 100%);}
#wr-scene .pod{position:absolute;left:50%;bottom:-11vw;width:84vw;height:22vw;transform:translateX(-50%);
  border-radius:50%;border:2px solid rgba(255,255,255,.9);
  background:radial-gradient(closest-side,rgba(255,255,255,.9),rgba(226,243,255,.45) 70%,rgba(226,243,255,0));
  box-shadow:0 -16px 46px -12px rgba(130,195,255,.6);}
#wr-scene .pod2{position:absolute;left:50%;bottom:-13vw;width:104vw;height:25vw;transform:translateX(-50%);
  border-radius:50%;border:2px solid rgba(255,255,255,.7);}
/* 電影感：四周暗角 + 上緣壓深 + 地板鏡射帶 */
#wr-scene .vig{position:absolute;inset:0;pointer-events:none;
  background:radial-gradient(120% 90% at 50% 42%, rgba(255,255,255,0) 44%,
             rgba(28,72,124,.16) 76%, rgba(16,48,92,.34) 100%);}
#wr-scene .topfade{position:absolute;left:0;right:0;top:0;height:26vh;pointer-events:none;
  background:linear-gradient(180deg, rgba(24,66,116,.28) 0%, rgba(24,66,116,0) 100%);}
#wr-scene .mirror{position:absolute;left:0;right:0;bottom:0;height:23vh;pointer-events:none;
  background:linear-gradient(180deg, rgba(255,255,255,.5) 0%, rgba(196,224,248,.28) 34%,
             rgba(150,196,236,.4) 100%);
  -webkit-mask-image:linear-gradient(180deg,#000 0%,rgba(0,0,0,.35) 62%,transparent 100%);
  mask-image:linear-gradient(180deg,#000 0%,rgba(0,0,0,.35) 62%,transparent 100%);}
#wr-scene .grid{position:absolute;left:-20%;right:-20%;bottom:0;height:24vh;pointer-events:none;
  opacity:.4;transform:perspective(520px) rotateX(64deg);transform-origin:bottom center;
  background-image:linear-gradient(90deg, rgba(90,150,215,.5) 1px, transparent 1px),
                   linear-gradient(0deg,  rgba(90,150,215,.4) 1px, transparent 1px);
  background-size:70px 46px;
  -webkit-mask-image:linear-gradient(180deg,transparent 0%,#000 55%,transparent 100%);
  mask-image:linear-gradient(180deg,transparent 0%,#000 55%,transparent 100%);}


/* ── 底部導覽列（目錄移到下方） ── */
.block-container{padding-bottom:130px;}
[data-testid="stPageLink"] a, a[data-testid="stPageLink-NavLink"]{
  text-decoration:none;display:flex;align-items:center;gap:10px;justify-content:center;
  border-radius:16px;padding:12px 14px;
  background:linear-gradient(150deg,rgba(255,255,255,.82),rgba(228,244,255,.62));
  border:1px solid rgba(255,255,255,1);
  box-shadow:inset 0 1px 0 rgba(255,255,255,1), 0 0 0 1px rgba(158,208,244,.5),
             0 2px 0 rgba(198,228,250,.95), 0 5px 0 rgba(166,206,240,.6),
             0 12px 20px -6px rgba(16,60,110,.32);
  transition:transform .18s ease, box-shadow .18s ease;}
a[data-testid="stPageLink-NavLink"]:hover{transform:translateY(-3px);
  box-shadow:inset 0 1px 0 rgba(255,255,255,1), 0 0 0 1px rgba(120,190,240,.7),
             0 2px 0 rgba(198,228,250,.95), 0 7px 0 rgba(166,206,240,.6),
             0 18px 28px -8px rgba(16,60,110,.42);}
a[data-testid="stPageLink-NavLink"][aria-current]{border-color:#1668C6;
  box-shadow:0 0 0 3px rgba(26,100,196,.3), 0 14px 24px -8px rgba(16,60,110,.45);}
a[data-testid="stPageLink-NavLink"] span[data-testid="stIconMaterial"],
a[data-testid="stPageLink-NavLink"] .nb{width:38px;height:38px;border-radius:12px;flex:none;display:flex;
  align-items:center;justify-content:center;color:#fff;font-size:17px;font-weight:700;
  text-shadow:0 1px 2px rgba(8,28,52,.45);
  box-shadow:0 3px 0 rgba(14,45,85,.24), 0 8px 14px -5px rgba(18,52,95,.5),
             inset 0 2px 0 rgba(255,255,255,.45), inset 0 -5px 9px rgba(0,0,0,.26);}
a[data-testid="stPageLink-NavLink"] p, a[data-testid="stPageLink-NavLink"] .nt{font-size:17px;font-weight:800;color:#152B3E;line-height:1.15;}
a[data-testid="stPageLink-NavLink"] .ns{font-family:ui-monospace,Consolas,monospace;font-size:12px;color:#2B4557;
  margin-top:2px;font-weight:600;}

.wr-hd{display:block;margin-bottom:16px;}
.wr-hd .clk{position:fixed;top:12px;right:22px;z-index:1000001;text-align:right;
  background:linear-gradient(150deg,rgba(255,255,255,.82),rgba(228,244,255,.6));
  border:1px solid rgba(255,255,255,1);border-radius:14px;padding:7px 14px;
  box-shadow:0 2px 0 rgba(198,228,250,.9), 0 8px 16px -6px rgba(16,60,110,.3);}
.wr-hd h1{font-size:40px;font-weight:800;letter-spacing:-.03em;color:#0E2233;margin:0;line-height:1;}
.wr-hd h1 em{font-style:normal;background:linear-gradient(96deg,#082D5A,#1668C6 48%,#0B6E96);
  -webkit-background-clip:text;background-clip:text;color:transparent;}
.wr-hd .sub{font-size:17px;color:#2C4A5E;margin-top:8px;}
.wr-hd .clk{font-family:ui-monospace,Consolas,monospace;font-size:13px;color:#2B4557;line-height:1.5;}
.wr-hd .clk b{color:#0E2233;font-size:17px;}

/* 外層大框：半透明，看得見背景 */
.big{position:relative;border-radius:24px;padding:18px 20px;
  background:linear-gradient(152deg,rgba(255,255,255,.58) 0%,rgba(226,243,255,.42) 52%,rgba(255,255,255,.5) 100%);
  border:1px solid rgba(255,255,255,.98);
  -webkit-backdrop-filter:blur(16px) saturate(165%);backdrop-filter:blur(16px) saturate(165%);
  box-shadow:inset 0 1px 0 rgba(255,255,255,1), 0 0 0 1px rgba(150,205,245,.4),
             0 0 34px rgba(146,203,247,.45), 0 3px 0 rgba(196,226,250,.75),
             0 6px 0 rgba(166,206,240,.5), 0 20px 30px -12px rgba(16,60,110,.34),
             0 52px 72px -30px rgba(16,60,110,.46);}
.big.tl{transform-origin:left center;transform:perspective(1600px) rotateY(9deg);}
.big.tr{transform-origin:right center;transform:perspective(1600px) rotateY(-9deg);}
.bh{display:flex;justify-content:space-between;align-items:center;margin-bottom:13px;gap:12px;}
.bh h2{font-size:26px;font-weight:800;color:#0E2233;margin:0;line-height:1.15;}
.src{font-family:ui-monospace,Consolas,monospace;font-size:14px;color:#0C4187;
  background:rgba(26,100,196,.11);padding:5px 11px;border-radius:8px;white-space:nowrap;}
.stat-chip{font-size:15px;font-weight:800;padding:4px 12px;border-radius:9px;}

/* 內層小框：更亮、浮在外層之上 */
.g2{position:relative;border-radius:18px;-webkit-font-smoothing:antialiased;
  background:linear-gradient(150deg,rgba(255,255,255,.82),rgba(228,244,255,.62));
  border:1px solid rgba(255,255,255,1);
  box-shadow:inset 0 1px 0 rgba(255,255,255,1), 0 0 0 1px rgba(158,208,244,.5),
             0 2px 0 rgba(198,228,250,.95), 0 5px 0 rgba(166,206,240,.6),
             0 12px 20px -6px rgba(16,60,110,.32), 0 28px 40px -16px rgba(16,60,110,.38);}
.duo2{display:grid;grid-template-columns:1fr 1fr;gap:13px;margin-bottom:13px;}
.sm{padding:13px 16px;}
.sm .lb{font-size:18px;color:#2C4A5E;font-weight:700;line-height:1.2;}
.sm .vl{font-size:46px;font-weight:300;line-height:.95;letter-spacing:-.045em;color:#0E2233;
  font-variant-numeric:tabular-nums;margin-top:6px;}
.sm .vl u{text-decoration:none;font-size:19px;color:#2B4557;margin-left:7px;font-weight:500;letter-spacing:0;}
.sm .bd{font-size:14px;color:#2B4557;margin-top:7px;font-weight:600;}
.chart{padding:15px 17px;}
.ch{font-size:18px;font-weight:800;color:#152B3E;margin-bottom:11px;}
.trk{height:19px;border-radius:99px;background:rgba(76,46,160,.16);overflow:hidden;position:relative;
  box-shadow:inset 0 3px 5px rgba(40,22,100,.34), inset 0 -2px 0 rgba(255,255,255,.55);}
.trk>i{display:block;height:100%;border-radius:99px;font-style:normal;
  box-shadow:inset 0 2px 0 rgba(255,255,255,.5), inset 0 -5px 8px rgba(0,0,0,.28);}
.rowline{display:grid;grid-template-columns:1fr 74px;gap:12px;align-items:center;margin-top:9px;}
.rowline b{text-align:right;font-family:ui-monospace,Consolas,monospace;font-size:20px;font-weight:700;
  color:#0E2233;font-variant-numeric:tabular-nums;}
.meta{font-size:14px;color:#2B4557;margin-top:8px;text-align:right;font-weight:600;}
.hr{height:1px;background:rgba(26,100,196,.22);margin:12px 0;}

/* 週卡 */
.wk{padding:14px 12px;text-align:center;}
.wk .lab{font-size:14px;color:#2C4A5E;font-weight:700;}
.wk .n{font-size:50px;font-weight:800;color:#0E2233;line-height:1.05;font-variant-numeric:tabular-nums;
  letter-spacing:-.04em;margin:4px 0 2px;}
.wk .qty{font-size:14px;color:#2B4557;font-weight:600;margin-bottom:9px;}
.wk .split{display:flex;justify-content:center;gap:12px;margin-bottom:9px;}
.wk .split div{flex:1;}
.wk .split .v{font-size:26px;font-weight:800;line-height:1;font-variant-numeric:tabular-nums;}
.wk .split .t{font-size:13px;color:#2B4557;margin-top:3px;font-weight:600;}

/* 表格 */
.tbsearch{display:flex;align-items:center;gap:10px;margin-bottom:10px;}
.tbsearch input{flex:1;font:inherit;font-size:15px;color:#0E2233;padding:8px 13px;
  border-radius:11px;border:1px solid rgba(158,208,244,.9);outline:none;
  background:linear-gradient(150deg,rgba(255,255,255,.95),rgba(235,246,255,.85));
  box-shadow:inset 0 1px 3px rgba(16,60,110,.12);}
.tbsearch input:focus{border-color:#1668C6;box-shadow:0 0 0 3px rgba(26,100,196,.18);}
.tbsearch input::placeholder{color:#5A7387;}
.tbsearch span{font-size:14px;font-weight:700;color:#0C4187;white-space:nowrap;min-width:64px;}
.wtb{width:100%;border-collapse:collapse;}
.tbwrap{flex:1;min-height:0;}
.tbwrap::-webkit-scrollbar{width:6px;}
.tbwrap::-webkit-scrollbar-thumb{background:rgba(26,100,196,.32);border-radius:3px;}
.tbwrap::-webkit-scrollbar-track{background:transparent;}
.wtb thead th{position:sticky;top:0;z-index:2;
  background:linear-gradient(180deg,rgba(244,250,255,.98),rgba(232,244,255,.96));
  backdrop-filter:blur(4px);}
.wtb tbody tr:hover td{background:rgba(26,100,196,.06);}
.wtb tr.drill{cursor:pointer;}
.wtb tr.drill:hover td{background:rgba(26,100,196,.14)!important;}
.wtb tr.drill:hover td:first-child{box-shadow:inset 3px 0 0 #1668C6;}
.wtb tr.drill:active td{background:rgba(26,100,196,.22)!important;}
.wtb th{font-family:ui-monospace,Consolas,monospace;font-size:13px;letter-spacing:.06em;color:#2B4557;
  text-align:left;padding:0 9px 8px 0;border-bottom:2px solid rgba(14,34,51,.8);font-weight:600;white-space:nowrap;}
.wtb td{padding:8px 9px 8px 0;border-bottom:1px solid rgba(26,100,196,.15);font-size:16px;color:#20394D;line-height:1.3;}
.wtb tr:last-child td{border-bottom:none;}
.wtb td.id{font-family:ui-monospace,Consolas,monospace;font-size:14px;color:#0E2233;font-weight:600;}
.wtb td.n{text-align:right;font-variant-numeric:tabular-nums;font-weight:700;color:#0E2233;}
.pill{display:inline-block;font-size:13px;font-weight:700;padding:3px 9px;border-radius:7px;white-space:nowrap;}
</style>
""", unsafe_allow_html=True)

st.markdown("""
<div id="wr-scene" aria-hidden="true">
  <div class="ceil"></div><div class="ceil2"></div>
  <div class="ray r1"></div><div class="ray r2"></div><div class="ray r3"></div>
  <div class="wall">
    <div class="wp" style="left:0;top:3vw;width:13vw;height:10vw">
      <div class="wl" style="left:1vw;top:1.4vw;width:8vw"></div>
      <div class="wl" style="left:1vw;top:2.4vw;width:5.5vw;opacity:.6"></div>
      <div class="wl" style="left:1vw;top:3.4vw;width:7vw;opacity:.45"></div>
    </div>
    <div class="wp" style="left:0;top:15vw;width:13vw;height:9vw">
      <div class="wl" style="left:1vw;top:1.4vw;width:6.6vw"></div>
      <div class="wl" style="left:1vw;top:2.4vw;width:8.8vw;opacity:.55"></div>
    </div>
    <div class="wp" style="left:15vw;top:17vw;width:18vw;height:11vw">
      <div class="wb" style="left:1.4vw;width:1.4vw;height:3.5vw;background:#A8D6F4"></div>
      <div class="wb" style="left:3.4vw;width:1.4vw;height:5.5vw;background:#93CBF1"></div>
      <div class="wb" style="left:5.4vw;width:1.4vw;height:4.1vw;background:#B4DDF6"></div>
      <div class="wb" style="left:7.4vw;width:1.4vw;height:7.3vw;background:#86C4EE"></div>
      <div class="wb" style="left:9.4vw;width:1.4vw;height:4.9vw;background:#A0D2F3"></div>
      <div class="wb" style="left:11.4vw;width:1.4vw;height:6.3vw;background:#8CC7EF"></div>
      <div class="wb" style="left:13.4vw;width:1.4vw;height:3.2vw;background:#BCE2F8"></div>
    </div>
    <div class="wp" style="left:35vw;top:18vw;width:20vw;height:10vw">
      <svg viewBox="0 0 380 184" style="position:absolute;inset:0;width:100%;height:100%">
        <path d="M0,140 C60,120 90,60 150,72 C210,84 240,30 300,44 C340,54 360,96 380,88 L380,184 L0,184 Z"
              fill="rgba(150,205,240,.34)"/>
        <path d="M0,160 C70,148 100,104 160,112 C220,120 250,74 310,86 C348,94 364,124 380,118 L380,184 L0,184 Z"
              fill="rgba(120,185,232,.32)"/>
      </svg>
    </div>
    <div class="wp" style="left:15vw;top:3vw;width:8vw;height:8vw">
      <svg viewBox="0 0 150 150" style="position:absolute;inset:0;width:100%;height:100%">
        <circle cx="75" cy="75" r="44" fill="none" stroke="rgba(150,205,240,.6)" stroke-width="18"/>
        <circle cx="75" cy="75" r="44" fill="none" stroke="#7FBCEC" stroke-width="18"
                stroke-dasharray="160 116" stroke-linecap="round" transform="rotate(-90 75 75)"/>
      </svg>
    </div>
  </div>

  <svg class="globe" viewBox="0 0 400 400">
    <defs>
      <radialGradient id="wgs" cx="34%" cy="26%" r="78%">
        <stop offset="0%" stop-color="#F4FAFF"/><stop offset="46%" stop-color="#BCDFF7"/>
        <stop offset="100%" stop-color="#6BAADE"/></radialGradient>
      <radialGradient id="wgf" cx="34%" cy="26%" r="76%">
        <stop offset="0%" stop-color="#fff" stop-opacity="1"/>
        <stop offset="62%" stop-color="#fff" stop-opacity=".7"/>
        <stop offset="100%" stop-color="#fff" stop-opacity=".12"/></radialGradient>
      <mask id="wgm"><circle cx="200" cy="200" r="150" fill="url(#wgf)"/></mask>
      <pattern id="wgd" width="10" height="10" patternUnits="userSpaceOnUse">
        <circle cx="2.2" cy="2.2" r="1.8" fill="#3E90D8"/></pattern>
    </defs>
    <circle cx="200" cy="200" r="184" fill="none" stroke="rgba(140,200,245,.5)" stroke-width="1.5"/>
    <circle cx="200" cy="200" r="168" fill="rgba(150,210,250,.2)"/>
    <circle cx="200" cy="200" r="150" fill="url(#wgs)"/>
    <g mask="url(#wgm)"><circle cx="200" cy="200" r="150" fill="url(#wgd)" opacity=".9"/></g>
    <g fill="none" stroke="rgba(38,110,180,.32)" stroke-width="1.4">
      <ellipse cx="200" cy="200" rx="150" ry="52"/><ellipse cx="200" cy="200" rx="150" ry="104"/>
      <ellipse cx="200" cy="200" rx="52" ry="150"/><ellipse cx="200" cy="200" rx="104" ry="150"/>
      <circle cx="200" cy="200" r="150"/></g>
    <path d="M64 132 A150 150 0 0 1 176 54" fill="none" stroke="rgba(255,255,255,.95)"
          stroke-width="6" stroke-linecap="round"/>
    <circle cx="200" cy="200" r="150" fill="none" stroke="rgba(70,150,215,.5)" stroke-width="2"/>
  </svg>

  <svg class="zodiac" viewBox="0 0 400 400">
    <defs>
      <radialGradient id="zSky" cx="42%" cy="34%" r="72%">
        <stop offset="0%"  stop-color="#F4FAFF"/>
        <stop offset="52%" stop-color="#CFE4F7"/>
        <stop offset="100%" stop-color="#9CC4E6"/>
      </radialGradient>
      <linearGradient id="zGold" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0%"   stop-color="#FFFFFF"/>
        <stop offset="34%"  stop-color="#DCEDFB"/>
        <stop offset="62%"  stop-color="#8FBEE4"/>
        <stop offset="100%" stop-color="#3B7FBF"/>
      </linearGradient>
      <linearGradient id="zGold2" x1="0" y1="0" x2="0.6" y2="1">
        <stop offset="0%"   stop-color="#FFFFFF"/>
        <stop offset="28%"  stop-color="#E8F4FD"/>
        <stop offset="58%"  stop-color="#A8CFEC"/>
        <stop offset="100%" stop-color="#5A96CE"/>
      </linearGradient>
      <linearGradient id="zJar" x1="0.15" y1="0" x2="0.9" y2="1">
        <stop offset="0%"   stop-color="#FFFFFF"/>
        <stop offset="22%"  stop-color="#E4F1FC"/>
        <stop offset="48%"  stop-color="#B4D5EF"/>
        <stop offset="72%"  stop-color="#6FA6D6"/>
        <stop offset="100%" stop-color="#C9E1F5"/>
      </linearGradient>
      <linearGradient id="zWater" x1="0" y1="0" x2="0.3" y2="1">
        <stop offset="0%"   stop-color="#DFF3FE"/>
        <stop offset="30%"  stop-color="#8FD3F7"/>
        <stop offset="65%"  stop-color="#3E9BE4"/>
        <stop offset="100%" stop-color="#1A5FB4"/>
      </linearGradient>
      <linearGradient id="zFoam" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%"   stop-color="#FFFFFF"/>
        <stop offset="100%" stop-color="#BFE4FA"/>
      </linearGradient>
      <radialGradient id="zGlow" cx="50%" cy="50%" r="50%">
        <stop offset="0%"   stop-color="#8FD3F7" stop-opacity=".55"/>
        <stop offset="100%" stop-color="#8FD3F7" stop-opacity="0"/>
      </radialGradient>
      <filter id="zSoft" x="-30%" y="-30%" width="160%" height="160%">
        <feGaussianBlur stdDeviation="3"/>
      </filter>
    </defs>
    <!-- 外光暈 -->
    <circle cx="200" cy="200" r="196" fill="url(#zGlow)"/>
    <!-- 鎏金外環 -->
    <circle cx="200" cy="200" r="184" fill="none" stroke="url(#zGold)" stroke-width="6"/>
    <circle cx="200" cy="200" r="184" fill="none" stroke="#FFFFFF" stroke-width="1.2" opacity=".55"/>
    <line x1="368.0" y1="200.0" x2="378.0" y2="200.0" stroke="url(#zGold)" stroke-width="2.2" opacity=".85"/><line x1="370.5" y1="222.5" x2="376.5" y2="223.2" stroke="url(#zGold)" stroke-width="1.1" opacity=".85"/><line x1="366.1" y1="244.5" x2="371.9" y2="246.1" stroke="url(#zGold)" stroke-width="1.1" opacity=".85"/><line x1="358.9" y1="265.8" x2="364.5" y2="268.1" stroke="url(#zGold)" stroke-width="1.1" opacity=".85"/><line x1="345.5" y1="284.0" x2="354.2" y2="289.0" stroke="url(#zGold)" stroke-width="2.2" opacity=".85"/><line x1="336.5" y1="304.7" x2="341.2" y2="308.4" stroke="url(#zGold)" stroke-width="1.1" opacity=".85"/><line x1="321.6" y1="321.6" x2="325.9" y2="325.9" stroke="url(#zGold)" stroke-width="1.1" opacity=".85"/><line x1="304.7" y1="336.5" x2="308.4" y2="341.2" stroke="url(#zGold)" stroke-width="1.1" opacity=".85"/><line x1="284.0" y1="345.5" x2="289.0" y2="354.2" stroke="url(#zGold)" stroke-width="2.2" opacity=".85"/><line x1="265.8" y1="358.9" x2="268.1" y2="364.5" stroke="url(#zGold)" stroke-width="1.1" opacity=".85"/><line x1="244.5" y1="366.1" x2="246.1" y2="371.9" stroke="url(#zGold)" stroke-width="1.1" opacity=".85"/><line x1="222.5" y1="370.5" x2="223.2" y2="376.5" stroke="url(#zGold)" stroke-width="1.1" opacity=".85"/><line x1="200.0" y1="368.0" x2="200.0" y2="378.0" stroke="url(#zGold)" stroke-width="2.2" opacity=".85"/><line x1="177.5" y1="370.5" x2="176.8" y2="376.5" stroke="url(#zGold)" stroke-width="1.1" opacity=".85"/><line x1="155.5" y1="366.1" x2="153.9" y2="371.9" stroke="url(#zGold)" stroke-width="1.1" opacity=".85"/><line x1="134.2" y1="358.9" x2="131.9" y2="364.5" stroke="url(#zGold)" stroke-width="1.1" opacity=".85"/><line x1="116.0" y1="345.5" x2="111.0" y2="354.2" stroke="url(#zGold)" stroke-width="2.2" opacity=".85"/><line x1="95.3" y1="336.5" x2="91.6" y2="341.2" stroke="url(#zGold)" stroke-width="1.1" opacity=".85"/><line x1="78.4" y1="321.6" x2="74.1" y2="325.9" stroke="url(#zGold)" stroke-width="1.1" opacity=".85"/><line x1="63.5" y1="304.7" x2="58.8" y2="308.4" stroke="url(#zGold)" stroke-width="1.1" opacity=".85"/><line x1="54.5" y1="284.0" x2="45.8" y2="289.0" stroke="url(#zGold)" stroke-width="2.2" opacity=".85"/><line x1="41.1" y1="265.8" x2="35.5" y2="268.1" stroke="url(#zGold)" stroke-width="1.1" opacity=".85"/><line x1="33.9" y1="244.5" x2="28.1" y2="246.1" stroke="url(#zGold)" stroke-width="1.1" opacity=".85"/><line x1="29.5" y1="222.5" x2="23.5" y2="223.2" stroke="url(#zGold)" stroke-width="1.1" opacity=".85"/><line x1="32.0" y1="200.0" x2="22.0" y2="200.0" stroke="url(#zGold)" stroke-width="2.2" opacity=".85"/><line x1="29.5" y1="177.5" x2="23.5" y2="176.8" stroke="url(#zGold)" stroke-width="1.1" opacity=".85"/><line x1="33.9" y1="155.5" x2="28.1" y2="153.9" stroke="url(#zGold)" stroke-width="1.1" opacity=".85"/><line x1="41.1" y1="134.2" x2="35.5" y2="131.9" stroke="url(#zGold)" stroke-width="1.1" opacity=".85"/><line x1="54.5" y1="116.0" x2="45.8" y2="111.0" stroke="url(#zGold)" stroke-width="2.2" opacity=".85"/><line x1="63.5" y1="95.3" x2="58.8" y2="91.6" stroke="url(#zGold)" stroke-width="1.1" opacity=".85"/><line x1="78.4" y1="78.4" x2="74.1" y2="74.1" stroke="url(#zGold)" stroke-width="1.1" opacity=".85"/><line x1="95.3" y1="63.5" x2="91.6" y2="58.8" stroke="url(#zGold)" stroke-width="1.1" opacity=".85"/><line x1="116.0" y1="54.5" x2="111.0" y2="45.8" stroke="url(#zGold)" stroke-width="2.2" opacity=".85"/><line x1="134.2" y1="41.1" x2="131.9" y2="35.5" stroke="url(#zGold)" stroke-width="1.1" opacity=".85"/><line x1="155.5" y1="33.9" x2="153.9" y2="28.1" stroke="url(#zGold)" stroke-width="1.1" opacity=".85"/><line x1="177.5" y1="29.5" x2="176.8" y2="23.5" stroke="url(#zGold)" stroke-width="1.1" opacity=".85"/><line x1="200.0" y1="32.0" x2="200.0" y2="22.0" stroke="url(#zGold)" stroke-width="2.2" opacity=".85"/><line x1="222.5" y1="29.5" x2="223.2" y2="23.5" stroke="url(#zGold)" stroke-width="1.1" opacity=".85"/><line x1="244.5" y1="33.9" x2="246.1" y2="28.1" stroke="url(#zGold)" stroke-width="1.1" opacity=".85"/><line x1="265.8" y1="41.1" x2="268.1" y2="35.5" stroke="url(#zGold)" stroke-width="1.1" opacity=".85"/><line x1="284.0" y1="54.5" x2="289.0" y2="45.8" stroke="url(#zGold)" stroke-width="2.2" opacity=".85"/><line x1="304.7" y1="63.5" x2="308.4" y2="58.8" stroke="url(#zGold)" stroke-width="1.1" opacity=".85"/><line x1="321.6" y1="78.4" x2="325.9" y2="74.1" stroke="url(#zGold)" stroke-width="1.1" opacity=".85"/><line x1="336.5" y1="95.3" x2="341.2" y2="91.6" stroke="url(#zGold)" stroke-width="1.1" opacity=".85"/><line x1="345.5" y1="116.0" x2="354.2" y2="111.0" stroke="url(#zGold)" stroke-width="2.2" opacity=".85"/><line x1="358.9" y1="134.2" x2="364.5" y2="131.9" stroke="url(#zGold)" stroke-width="1.1" opacity=".85"/><line x1="366.1" y1="155.5" x2="371.9" y2="153.9" stroke="url(#zGold)" stroke-width="1.1" opacity=".85"/><line x1="370.5" y1="177.5" x2="376.5" y2="176.8" stroke="url(#zGold)" stroke-width="1.1" opacity=".85"/>
    <circle cx="200" cy="200" r="164" fill="none" stroke="url(#zGold2)" stroke-width="3.4"/>
    <!-- 星空圓盤 -->
    <circle cx="200" cy="200" r="158" fill="url(#zSky)"/>
    <g class="z-stars"><circle cx="172.9" cy="254.2" r="2.4" fill="#2E86D8" opacity="0.48"/><circle cx="221.5" cy="155.3" r="1.8" fill="#2E86D8" opacity="0.48"/><circle cx="164.8" cy="198.4" r="1.4" fill="#2E86D8" opacity="0.68"/><circle cx="304.5" cy="240.7" r="1.1" fill="#2E86D8" opacity="0.80"/><circle cx="163.6" cy="179.1" r="1.8" fill="#2E86D8" opacity="0.67"/><circle cx="237.5" cy="194.4" r="1.1" fill="#2E86D8" opacity="0.61"/><circle cx="233.6" cy="242.9" r="1.4" fill="#2E86D8" opacity="0.76"/><circle cx="178.7" cy="153.1" r="1.8" fill="#2E86D8" opacity="0.80"/><circle cx="238.3" cy="215.9" r="1.1" fill="#2E86D8" opacity="0.72"/><circle cx="71.7" cy="174.1" r="1.4" fill="#2E86D8" opacity="0.77"/><circle cx="120.7" cy="224.0" r="1.1" fill="#2E86D8" opacity="0.83"/><circle cx="63.1" cy="178.1" r="2.4" fill="#2E86D8" opacity="0.70"/><circle cx="165.3" cy="171.7" r="1.8" fill="#2E86D8" opacity="0.68"/><circle cx="202.7" cy="139.2" r="1.4" fill="#2E86D8" opacity="0.68"/><circle cx="244.6" cy="189.2" r="1.8" fill="#2E86D8" opacity="0.77"/><circle cx="260.1" cy="140.3" r="2.4" fill="#2E86D8" opacity="0.64"/><circle cx="67.6" cy="202.8" r="0.9" fill="#2E86D8" opacity="0.91"/><circle cx="296.9" cy="164.9" r="2.4" fill="#2E86D8" opacity="0.49"/><circle cx="190.1" cy="116.4" r="1.8" fill="#2E86D8" opacity="1.00"/><circle cx="235.3" cy="127.2" r="1.4" fill="#2E86D8" opacity="0.94"/><circle cx="128.5" cy="202.8" r="1.4" fill="#2E86D8" opacity="0.52"/><circle cx="232.2" cy="166.3" r="1.4" fill="#2E86D8" opacity="0.67"/><circle cx="189.9" cy="257.2" r="1.4" fill="#2E86D8" opacity="0.93"/><circle cx="258.5" cy="184.1" r="1.1" fill="#2E86D8" opacity="0.53"/><circle cx="185.6" cy="177.8" r="1.8" fill="#2E86D8" opacity="0.55"/><circle cx="188.1" cy="258.5" r="1.8" fill="#2E86D8" opacity="0.65"/><circle cx="67.8" cy="141.5" r="2.4" fill="#2E86D8" opacity="0.92"/><circle cx="314.6" cy="163.0" r="2.4" fill="#2E86D8" opacity="0.48"/><circle cx="305.8" cy="122.6" r="2.4" fill="#2E86D8" opacity="0.89"/><circle cx="126.0" cy="259.4" r="0.9" fill="#2E86D8" opacity="0.71"/><circle cx="145.4" cy="239.4" r="1.1" fill="#2E86D8" opacity="0.69"/><circle cx="289.8" cy="267.3" r="1.8" fill="#2E86D8" opacity="0.51"/><circle cx="179.4" cy="223.7" r="1.1" fill="#2E86D8" opacity="0.79"/><circle cx="245.5" cy="261.5" r="1.4" fill="#2E86D8" opacity="0.78"/><circle cx="146.7" cy="208.7" r="1.4" fill="#2E86D8" opacity="1.00"/><circle cx="98.3" cy="222.1" r="0.9" fill="#2E86D8" opacity="0.53"/><circle cx="199.7" cy="72.2" r="1.4" fill="#2E86D8" opacity="0.91"/></g>
    <circle cx="200" cy="200" r="158" fill="none" stroke="#5A96CE" stroke-width="2" opacity=".7"/>
    <!-- 頂部 水瓶座符號 ♒ -->
    <g transform="translate(150,84)" class="z-sign"><circle r="27" fill="#0E3C78" opacity=".72"/><circle r="27" fill="none" stroke="url(#zGold2)" stroke-width="2.2"/><path d="M-15,-5 q5.5,-7 10,0 t10,0 t10,0" fill="none" stroke="url(#zGold2)" stroke-width="4.2" stroke-linecap="round"/><path d="M-15,7 q5.5,-7 10,0 t10,0 t10,0" fill="none" stroke="url(#zGold2)" stroke-width="4.2" stroke-linecap="round"/></g><g transform="translate(250,84)" class="z-sign2"><circle r="27" fill="#0E3C78" opacity=".72"/><circle r="27" fill="none" stroke="url(#zGold2)" stroke-width="2.2"/><path d="M-13,13 L13,-13" fill="none" stroke="url(#zGold2)" stroke-width="4.2" stroke-linecap="round"/><path d="M13,-13 L2,-13 M13,-13 L13,-2" fill="none" stroke="url(#zGold2)" stroke-width="4.2" stroke-linecap="round"/><path d="M-12,-2 L2,12" fill="none" stroke="url(#zGold2)" stroke-width="4.2" stroke-linecap="round"/></g>
    <!-- 傾倒的金瓶 -->
    <g transform="translate(232,186) rotate(34)" class="z-jar">
      <!-- 把手 -->
      <path d="M-52,-34 C-84,-40 -90,4 -60,14" fill="none" stroke="url(#zGold)"
            stroke-width="11" stroke-linecap="round"/>
      <path d="M52,-34 C84,-40 90,4 60,14" fill="none" stroke="url(#zGold)"
            stroke-width="11" stroke-linecap="round"/>
      <!-- 瓶身 -->
      <path d="M-54,-4 C-54,52 -32,82 0,82 C32,82 54,52 54,-4
               C54,-40 32,-60 0,-60 C-32,-60 -54,-40 -54,-4 Z" fill="url(#zJar)"/>
      <!-- 瓶身裝飾帶 -->
      <path d="M-53,-14 C-30,-4 30,-4 53,-14" fill="none" stroke="#3B7FBF" stroke-width="3" opacity=".6"/>
      <path d="M-49,26 C-26,38 26,38 49,26" fill="none" stroke="#3B7FBF" stroke-width="3" opacity=".55"/>
      <!-- 瓶身上的 ♒ -->
      <g transform="translate(0,6)">
        <path d="M-22,-4 q7,-9 14,0 t14,0 t14,0" fill="none" stroke="#0B4A86"
              stroke-width="5" stroke-linecap="round"/>
        <path d="M-22,12 q7,-9 14,0 t14,0 t14,0" fill="none" stroke="#0B4A86"
              stroke-width="5" stroke-linecap="round"/>
      </g>
      <!-- 高光 -->
      <path d="M-34,-30 C-46,-8 -44,28 -30,50" fill="none" stroke="#FFFFFF"
            stroke-width="7" stroke-linecap="round" opacity=".5"/>
      <!-- 頸與唇口 -->
      <path d="M-24,-58 L-21,-86 L21,-86 L24,-58 Z" fill="url(#zJar)"/>
      <path d="M-36,-96 Q0,-108 36,-96 L31,-82 Q0,-92 -31,-82 Z" fill="url(#zGold2)"/>
      <ellipse cx="0" cy="-96" rx="36" ry="9" fill="#0E3C78" opacity=".55"/>
      <!-- 底座 -->
      <path d="M-26,76 Q0,88 26,76 L21,90 Q0,99 -21,90 Z" fill="url(#zGold)"/>
    </g>
    <!-- 傾瀉的水流 -->
    <g class="z-water">
      <path d="M150,120 C126,150 118,178 124,206 C130,236 116,258 96,276
               C120,268 140,250 148,228 C156,250 150,272 136,290
               C166,272 178,240 172,208 C166,176 168,146 182,124 Z"
            fill="url(#zWater)" opacity=".95"/>
      <path d="M158,126 C142,152 138,176 143,200 C148,226 138,246 124,262"
            fill="none" stroke="#EAF7FE" stroke-width="3.4" stroke-linecap="round" opacity=".72"/>
      <path d="M170,130 C160,152 158,172 162,192" fill="none" stroke="#FFFFFF"
            stroke-width="2.2" stroke-linecap="round" opacity=".5"/>
      <circle cx="132" cy="238" r="3.4" fill="#EAF7FE" opacity=".85"/>
      <circle cx="146" cy="266" r="2.6" fill="#EAF7FE" opacity=".7"/>
      <circle cx="118" cy="212" r="2.2" fill="#EAF7FE" opacity=".65"/>
    </g>
    <g transform="translate(163,238) rotate(-38) scale(0.7)" class="z-bow"><path d="M4,-98 C-50,-56 -50,56 4,98" fill="none" stroke="#3B7FBF" stroke-width="13" stroke-linecap="round" opacity=".45"/><path d="M0,-98 C-54,-56 -54,56 0,98" fill="none" stroke="url(#zGold)" stroke-width="10" stroke-linecap="round"/><path d="M0,-98 C-54,-56 -54,56 0,98" fill="none" stroke="#FFFFFF" stroke-width="3" stroke-linecap="round" opacity=".55"/><path d="M0,-98 C12,-108 24,-100 20,-88 C17,-79 6,-80 6,-88" fill="none" stroke="url(#zGold2)" stroke-width="6" stroke-linecap="round"/><path d="M0,98 C12,108 24,100 20,88 C17,79 6,80 6,88" fill="none" stroke="url(#zGold2)" stroke-width="6" stroke-linecap="round"/><path d="M0,-96 L0,96" fill="none" stroke="#EAF7FE" stroke-width="2" opacity=".9"/><path d="M-76,0 L82,0" fill="none" stroke="#3B7FBF" stroke-width="9" stroke-linecap="round" opacity=".4"/><path d="M-78,0 L80,0" fill="none" stroke="url(#zGold)" stroke-width="6.5" stroke-linecap="round"/><path d="M-98,0 L-72,-15 L-72,15 Z" fill="url(#zGold2)" stroke="#3B7FBF" stroke-width="1.6"/><path d="M-93,0 L-76,-8 L-76,8 Z" fill="#FFFFFF" opacity=".55"/><path d="M56,0 C66,-16 80,-22 94,-20 C88,-10 78,-3 68,0 Z" fill="url(#zFoam)" stroke="#5A96CE" stroke-width="1.4"/><path d="M56,0 C66,16 80,22 94,20 C88,10 78,3 68,0 Z" fill="#DFF3FE" stroke="#5A96CE" stroke-width="1.4"/><circle r="21" fill="#0E3C78" opacity=".2"/><path d="M0,-15 L3.8,-5.3 L14.3,-4.6 L6.2,2 L8.8,12.1 L0,6.5 L-8.8,12.1 L-6.2,2 L-14.3,-4.6 L-3.8,-5.3 Z" fill="url(#zJar)" stroke="#3B7FBF" stroke-width="1.6"/><circle cx="-3" cy="-4" r="3.2" fill="#FFFFFF" opacity=".8"/><circle cx="-30" cy="-52" r="7" fill="#6FA6D6" stroke="#FFFFFF" stroke-width="1.6"/><circle cx="-30" cy="52" r="7" fill="#6FA6D6" stroke="#FFFFFF" stroke-width="1.6"/></g><!-- 底部雲浪 -->
    <g class="z-foam">
      <path d="M48,318 C74,296 104,300 122,314 C136,296 166,292 184,308
               C202,292 232,296 244,314 C262,300 292,304 310,322
               C330,308 356,316 366,334 L366,360 L36,360 Z"
            fill="url(#zFoam)" opacity=".9"/>
      <path d="M40,340 C70,322 100,328 118,340 C140,324 172,326 190,340
               C210,326 240,330 254,342 C276,328 304,332 322,346
               C340,334 358,340 368,352 L368,376 L34,376 Z"
            fill="#FFFFFF" opacity=".72"/>
    </g>
    <!-- 署名 -->
    <g class="z-label">
      <text x="200" y="352" class="z-sig" text-anchor="middle">K&amp;K</text>
      <text x="200" y="371" class="z-sub" text-anchor="middle">AQUARIUS · SAGITTARIUS</text>
    </g>
  </svg>

  <div class="floor"></div><div class="grid"></div><div class="mirror"></div>
  <div class="pod2"></div><div class="pod"></div>
  <div class="topfade"></div><div class="vig"></div>
</div>
""", unsafe_allow_html=True)

OK_BG, OK_FG = "rgba(212,245,231,.95)", "#03503A"
WARN_BG, WARN_FG = "rgba(254,236,211,.95)", "#6B2D03"
CRIT_BG, CRIT_FG = "rgba(254,226,226,.95)", "#8F1212"

NOW = datetime.now()
st.markdown(
    f'<div class="wr-hd"><div><h1>營運<em>戰情室</em></h1>'
    f'<div class="sub">鼎新 ERP GP ／ 倉儲・出貨・製程即時同步　·　資料 {_DATA_TS}</div></div>'
    f'<div class="clk"><b>{NOW.strftime("%H:%M")}</b><br>{NOW.strftime("%Y/%m/%d")}　'
    f'{"一二三四五六日"[NOW.weekday()]}</div></div>',
    unsafe_allow_html=True)


def _bar(pct, grad):
    pct = max(0, min(100, int(pct)))
    return f'<div class="trk"><i style="width:{pct}%;background:{grad}"></i></div>'


def _table(df, cols, fmt=None, limit=8):
    if df is None or df.empty:
        return '<div style="padding:22px;text-align:center;color:#2B4557;font-size:16px">— 無資料 —</div>'
    fmt = fmt or {}
    head = "".join(f"<th>{c}</th>" for c in cols)
    body = ""
    for _, r in df.head(limit).iterrows():
        tds = ""
        for c in cols:
            v = r.get(c)
            if pd.isna(v):
                tds += '<td style="color:#526C80">—</td>'
            else:
                cls, txt = fmt.get(c, ("", None))
                tds += f'<td class="{cls}">{txt(v) if txt else v}</td>'
        body += f"<tr>{tds}</tr>"
    return f'<table class="wtb"><tr>{head}</tr>{body}</table>'


# ══════════════════════════════════════════════════════════════
# 取數
# ══════════════════════════════════════════════════════════════
try:
    k = wd.load_wh_kpi(_DB_KEY)
except Exception as e:
    st.error(f"倉儲資料讀取失敗：{e}")
    st.stop()

weeks = wd.load_ship_weeks(_SD_KEY)
with st.spinner("掃描 NAS 製程 Log…"):
    asm, asm_err = wd.scan_assembly()
    asum, asum_err = wd.assembly_summary()
    fast, fast_err = wd.load_fastest_per_model()
    psum, psum_err = wd.packaging_summary()
    tot, tot_warns = wd.total_worktime_table()
    _prog_map, _prog_file, _prog_err = wd.load_mo_progress()


def _wh_block(title, icon, done, pend, rate, total, target, line1, line2):
    """倉儲用的一個內層小框（備料 或 上架）"""
    if rate >= 0.8:
        sbg, sfg, stxt = OK_BG, OK_FG, "達標"
    elif rate >= 0.5:
        sbg, sfg, stxt = WARN_BG, WARN_FG, "持續推進"
    else:
        sbg, sfg, stxt = CRIT_BG, CRIT_FG, "進度落後"
    gap = target - done
    t_pct = int(done / target * 100) if target else 0
    if gap > 0:
        t_txt = f'<span style="color:{CRIT_FG};font-weight:800">▼ {gap:,} 未達標</span>'
        t_grad = "linear-gradient(90deg,#8F1212,#DC2626)"
    else:
        t_txt = f'<span style="color:{OK_FG};font-weight:800">✔ 已達標</span>'
        t_grad = "linear-gradient(90deg,#03503A,#0B8F63)"
    pct = int(rate * 100)
    return (
        '<div class="g2 sm">'
        '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">'
        f'<div class="lb" style="font-size:20px">{icon} {title}</div>'
        f'<span class="stat-chip" style="background:{sbg};color:{sfg};font-size:13px">{stxt}</span></div>'
        '<div style="display:flex;gap:18px;align-items:flex-end">'
        f'<div><div class="vl" style="color:{OK_FG};font-size:44px">{done:,}</div>'
        '<div class="bd">已完成</div></div>'
        f'<div><div class="vl" style="color:{CRIT_FG};font-size:44px">{pend:,}</div>'
        '<div class="bd">待完成</div></div>'
        '<div style="margin-left:auto;text-align:right">'
        f'<div class="vl" style="font-size:44px">{pct}<u>%</u></div>'
        '<div class="bd">完成率</div></div></div>'
        f'<div class="bd" style="margin-top:9px">{line1}　｜　{line2}</div>'
        '<div style="margin-top:11px">'
        + _bar(pct, "linear-gradient(90deg,#0B6E96,#1E9BCC)") +
        f'<div class="meta">目標總筆數 {total:,}</div></div>'
        '<div class="hr"></div>'
        '<div style="display:flex;justify-content:space-between;font-size:14px;color:#2B4557;'
        f'font-weight:600;margin-bottom:7px"><span>🎯 第{k["q_num"]}季每日指標 {target:,} 筆</span>{t_txt}</div>'
        + _bar(t_pct, t_grad) +
        f'<div class="meta">{t_pct}%</div></div>'
    )



# ══════════════════════════════════════════════════════════════
# 四個主題面板（各自獨立）
# ══════════════════════════════════════════════════════════════
if weeks:
    _cells = ""
    for wk in weeks:
        _ac = OK_FG if wk["n_short"] == 0 else CRIT_FG
        _g = ("linear-gradient(90deg,#03503A,#0B8F63)" if wk["n_short"] == 0
              else "linear-gradient(90deg,#0B6E96,#1E9BCC)")
        _cells += (
            '<div style="flex:1;text-align:center;min-width:0">'
            f'<div style="font-size:14px;color:#2C4A5E;font-weight:700">{wk["label"]}</div>'
            f'<div style="font-size:12px;color:#2B4557">{wk["start"]:%m/%d}~{wk["end"]:%m/%d}</div>'
            '<div style="font-size:44px;font-weight:800;color:#0E2233;line-height:1.1;'
            f'font-variant-numeric:tabular-nums;margin:4px 0">{wk["n"]}</div>'
            f'<div style="font-size:13px;color:#2B4557">張工單 ／ {wk["tq"]:,} pcs</div>'
            # 三格拆分與 15_kanban 的出貨工單概況卡一致：已齊料 / IQC中 / 缺料
            '<div style="font-size:17px;margin-top:8px">'
            f'<span style="color:{OK_FG};font-weight:800">{wk["n_ready"]}</span>'
            '<span style="color:#526C80"> / </span>'
            f'<span style="color:{WARN_FG};font-weight:800">{wk["n_iqc"]}</span>'
            '<span style="color:#526C80"> / </span>'
            f'<span style="color:{CRIT_FG};font-weight:800">{wk["n_true_short"]}</span></div>'
            '<div style="font-size:12px;color:#2B4557">已齊料 / IQC中 / 缺料</div>'
            f'<div style="margin-top:9px">{_bar(wk["pct"], _g)}</div>'
            f'<div style="font-size:13px;color:{_ac};font-weight:700;margin-top:5px">{wk["pct"]}%</div>'
            '</div>')
    _wk_html = f'<div style="display:flex;gap:11px">{_cells}</div>'
else:
    _wk_html = '<div style="padding:26px;text-align:center;color:#2B4557">— 無排程資料 —</div>'

b_l1 = f'已完成 廠內 {k["b_done_inhouse"]:,}・委外 {k["b_done_outsource"]:,}'
b_l2 = f'待完成 廠內 {k["b_pend_inhouse"]:,}・委外 {k["b_pend_outsource"]:,}'
i_l1 = "已完成 依調撥單需求單位＝入庫"
i_l2 = f'待完成 其中逾期 {k["i_pend_overdue"]:,}'

if asum_err or asm_err:
    _asm_tbl = f'<div style="padding:26px;color:{CRIT_FG};font-size:16px">{asum_err or asm_err}</div>'
    _asm_n = _asm_done = 0
else:
    _asm_n = int(asum["完成台數"].sum()) if not asum.empty else 0
    _asm_done = int(asum["有效樣本"].sum()) if not asum.empty else 0
    _asm_tbl = _table(asum,
                      ["成品料號", "工單號碼", "完成台數", "組裝中", "有效樣本",
                       "標準工時(分)"], limit=200,
                      fmt={"成品料號": ("id", None), "工單號碼": ("id", None),
                           "完成台數": ("n", lambda v: f"{int(v):,}"),
                           "組裝中": ("n", lambda v: f"{int(v):,}"),
                           "有效樣本": ("n", lambda v: f"{int(v):,}"),
                           "標準工時(分)": ("n", lambda v: f"{v:g}")})

if fast is None or fast.empty:
    _fast_tbl = f'<div style="padding:26px;color:{CRIT_FG};font-size:16px">{fast_err or "無資料"}</div>'
    _fast_n, _fast_best = 0, "—"
else:
    _fast_n = len(fast)
    _fast_best = f'{fast["一台最快合計(分)"].min():g}'
    _fast_tbl = _table(fast, ["成品料號", "第一測程最快(分)", "第二測程最快(分)", "一台最快合計(分)"],
                       limit=200,
                       fmt={"成品料號": ("id", None),
                            "第一測程最快(分)": ("n", lambda v: f"{v:g}"),
                            "第二測程最快(分)": ("n", lambda v: f"{v:g}"),
                            "一台最快合計(分)": ("n", lambda v: f"{v:g}")})

if psum_err:
    _pkg_tbl = f'<div style="padding:26px;color:{CRIT_FG};font-size:16px">{psum_err}</div>'
    _pkg_n = _pkg_done = 0
else:
    _pkg_n = int(psum["完成台數"].sum()) if not psum.empty else 0
    _pkg_done = int(psum["有效樣本"].sum()) if not psum.empty else 0
    _pkg_tbl = _table(psum,
                      ["成品料號", "工單號碼", "完成台數", "包裝中", "有效樣本",
                       "標準工時(分)"], limit=200,
                      fmt={"成品料號": ("id", None), "工單號碼": ("id", None),
                           "完成台數": ("n", lambda v: f"{int(v):,}"),
                           "包裝中": ("n", lambda v: f"{int(v):,}"),
                           "有效樣本": ("n", lambda v: f"{int(v):,}"),
                           "標準工時(分)": ("n", lambda v: f"{v:g}")})


def _full_pill(v):
    """成品工時表的資料狀態：完成品給綠章，缺站給黃章"""
    v = str(v)
    if v.startswith("✅"):
        return f'<span class="pill" style="background:{OK_BG};color:{OK_FG}">完成品</span>'
    return f'<span class="pill" style="background:{WARN_BG};color:{WARN_FG}">{v}</span>'


def _min_or_dash(v):
    return f"{v:g}" if v else "—"


if tot is None or tot.empty:
    _msg = tot_warns[0] if tot_warns else "無資料"
    _tot_tbl = f'<div style="padding:26px;color:{CRIT_FG};font-size:16px">{_msg}</div>'
    _tot_n = _tot_full = 0
else:
    _tot_n = len(tot)
    _tot_full = int(tot["完成品"].sum())
    _tot_tbl = _table(tot,
                      ["成品料號", "組裝(分)", "測試小計(分)", "包裝(分)",
                       "合計工時(分)", "資料狀態"], limit=200,
                      fmt={"成品料號": ("id", None),
                           "組裝(分)": ("n", _min_or_dash),
                           "測試小計(分)": ("n", _min_or_dash),
                           "包裝(分)": ("n", _min_or_dash),
                           "合計工時(分)": ("n", _min_or_dash),
                           "資料狀態": ("", _full_pill)})

_det, _det_total = wd.load_ship_detail(_SD_KEY)

def _st_pill(v):
    v = str(v)
    if v == "已齊料":
        return f'<span class="pill" style="background:{OK_BG};color:{OK_FG}">已齊料</span>'
    if v == "未備料":
        return f'<span class="pill" style="background:{CRIT_BG};color:{CRIT_FG}">未備料</span>'
    return f'<span class="pill" style="background:{WARN_BG};color:{WARN_FG}">{v}</span>'

INFO_BG, INFO_FG = "rgba(219,234,254,.95)", "#0C4187"
GREY_BG, GREY_FG = "rgba(226,232,240,.95)", "#3C5164"
_PROG_COLOR = {
    "已完工": (OK_BG, OK_FG), "指定完工": (OK_BG, OK_FG),
    "生產中": (INFO_BG, INFO_FG), "品檢中": (INFO_BG, INFO_FG), "齊料": (INFO_BG, INFO_FG),
    "未完工": (WARN_BG, WARN_FG), "未齊料": (WARN_BG, WARN_FG), "待確認": (WARN_BG, WARN_FG),
    "異常": (CRIT_BG, CRIT_FG), "取消": (GREY_BG, GREY_FG),
    "排程中": (GREY_BG, GREY_FG),
}


_DASH_TD = '<td style="color:#526C80">—</td>'


def _prog_cells(wo, pno):
    """
    回傳「生產進度」「備註說明」兩格：
      進度 → 先查已完工表 E 欄，沒有再看排程表的進度
      備註 → 已完工的只放 PASS；未完工的放排程表 F 欄（進度說明）
    """
    rec = wd.mo_progress_of(_prog_map, wo, pno)
    if not rec:
        return _DASH_TD + _DASH_TD
    txt = rec["進度"]
    bg, fg = _PROG_COLOR.get(txt, (INFO_BG, INFO_FG))
    prog_td = f'<td><span class="pill" style="background:{bg};color:{fg}">{txt}</span></td>'

    if txt in ("已完工", "指定完工"):
        note_td = '<td class="pass">PASS</td>'
    elif rec["說明"]:
        _n = html.escape(str(rec["說明"]))
        note_td = f'<td class="note" title="{_n}">{_n}</td>'
    else:
        note_td = _DASH_TD
    return prog_td + note_td


if _det is None or _det.empty:
    _det_html = '<div style="padding:22px;text-align:center;color:#2B4557">— 無出貨排程 —</div>'
else:
    _tr = ""
    for _, _r in _det.iterrows():
        _tr += (f'<tr class="drill" data-wo="{_r["工單"]}" title="點擊：於新分頁開啟此工單的缺料明細">'
                f'<td class="id">{_r["工單"]}</td>'
                f'<td class="id" style="font-size:12.5px">{_r["成品料號"]}</td>'
                f'<td class="n">{int(_r["預計產量"]):,}</td>'
                f'<td class="sm2">{_r["出貨日"]}</td>'
                f'<td>{_st_pill(_r["料況狀態"])}</td>'
                + _prog_cells(_r["工單"], _r["成品料號"]) + '</tr>')
    _prog_src = (f'　<span style="font-weight:600;font-size:13px;color:#2B4557">'
                 f'生產進度：{_prog_err or _prog_file}</span>')
    _det_html = (
        f'<div class="ch" style="margin-top:10px">出貨工單明細　<span style="font-weight:600;'
        f'font-size:14px;color:#2B4557">有出貨日 — {_det_total} 張</span>{_prog_src}</div>'
        '<div class="tbsearch"><input type="search" autocomplete="off"'
        ' placeholder="🔍 搜尋工單 / 成品料號 / 出貨日 / 生產進度 / 備註…"><span></span></div>'
        '<div class="tbwrap" style="overflow:auto;padding-right:6px">'
        '<table class="wtb"><thead><tr>'
        '<th>工單</th><th>成品料號</th><th class="r">預計產量</th><th>出貨日</th>'
        '<th>料況狀態</th><th>生產進度</th><th>備註說明</th>'
        '</tr></thead><tbody>' + _tr + '</tbody></table></div>')

PANELS = [
    ("倉儲進度", "📦", f'前一工作日 {k["yesterday"]:%m/%d} · 資料 {_DATA_TS}',
     _wh_block("備料", "📦", k["b_done"], k["b_pend"], k["b_rate"],
               k["b_display_total"], k["b_target_day"], b_l1, b_l2)
     + '<div style="height:10px"></div>'
     + _wh_block("上架", "🏭", k["i_done"], k["i_pend"], k["i_rate"],
                 k["i_display_total"], k["i_target_day"], i_l1, i_l2)),

    ("出貨工單概況", "🚚", f"今日 ~ +4週 · 共 {_det_total} 張 · 資料 {_SD_TS}",
     f'<div class="g2 chart">{_wk_html}{_det_html}</div>'),

    ("產量與組裝標準工時", "🔩", f'完成 {_asm_n:,} 台 · 有效樣本 {_asm_done:,} · 有 End 取頭尾、只有 Start 取節拍×{wd.TAKT_PEOPLE}人 · 去頭去尾各 {wd.TAKT_TRIM:.0%}',
     f'<div class="g2 chart">'
     f'<div class="tbsearch"><input type="search" autocomplete="off"'
     f' placeholder="🔍 搜尋成品料號 / 工單號碼…"><span></span></div>'
     f'<div class="tbwrap" style="overflow:auto;padding-right:6px">'
     f'{_asm_tbl}</div></div>'),

    ("測試站｜每機種最快完成時間", "🏁", f'{_fast_n:,} 個機種 · 最快 {_fast_best} 分',
     f'<div class="g2 chart">'
     f'<div class="tbsearch"><input type="search" autocomplete="off"'
     f' placeholder="🔍 搜尋成品料號…"><span></span></div>'
     f'<div class="tbwrap" style="overflow:auto;padding-right:6px">'
     f'{_fast_tbl}</div></div>'),

    ("產量與包裝標準工時", "📦", f'完成 {_pkg_n:,} 台 · 有效樣本 {_pkg_done:,} · 只認頭尾 End−Start（只有 Start＝還在包裝中）· 去頭去尾各 {wd.TAKT_TRIM:.0%}',
     f'<div class="g2 chart">'
     f'<div class="tbsearch"><input type="search" autocomplete="off"'
     f' placeholder="🔍 搜尋成品料號 / 工單號碼…"><span></span></div>'
     f'<div class="tbwrap" style="overflow:auto;padding-right:6px">'
     f'{_pkg_tbl}</div></div>'),

    ("每機種成品工時表", "⏱", f'{_tot_n:,} 個機種 · 完成品 {_tot_full:,} 種 · 組裝 ＋ 測試 ＋ 包裝＝一台成品工時',
     f'<div class="g2 chart">'
     f'<div class="tbsearch"><input type="search" autocomplete="off"'
     f' placeholder="🔍 搜尋成品料號…"><span></span></div>'
     f'<div class="tbwrap" style="overflow:auto;padding-right:6px">'
     f'{_tot_tbl}</div></div>'),
]

_cards = ""
for n, (title, icon, sub, inner) in enumerate(PANELS):
    _cards += (
        f'<div class="orb" data-i="{n}">'
        f'<div class="obh"><h2>{icon} {title}</h2><span class="osrc">{sub}</span></div>'
        f'<div class="obody">{inner}</div></div>'
    )



# ══════════════════════════════════════════════════════════════
# 環繞式切換（iframe 內才能跑 JS；背景透明讓場景透上來）
# ══════════════════════════════════════════════════════════════
import streamlit.components.v1 as components

_ORBIT_HTML = """
<style>
*{box-sizing:border-box;}
html,body{margin:0;padding:0;background:transparent;overflow:hidden;
  font-family:"Noto Sans TC","PingFang TC","Microsoft JhengHei",system-ui,sans-serif;}
#stage{position:relative;width:100%;height:800px;perspective:2000px;perspective-origin:50% 46%;}
.orb{position:absolute;left:50%;top:22px;width:900px;height:712px;margin-left:-450px;
  border-radius:24px;padding:18px 20px;cursor:pointer;display:flex;flex-direction:column;
  transition:transform .72s cubic-bezier(.22,1,.36,1), opacity .72s ease, filter .72s ease;
  transform-style:preserve-3d;}
.orb .obh{display:flex;justify-content:space-between;align-items:center;margin-bottom:13px;gap:12px;flex:none;}
.orb .obody{flex:1;min-height:0;overflow:auto;display:flex;flex-direction:column;}
.orb .obody > .g2.chart{flex:1;min-height:0;}   /* 圖表框吃掉剩餘高度 */
.orb .obody > .g2.chart > .wtb{flex:none;}
.orb .obody::-webkit-scrollbar{width:7px;}
.orb .obody::-webkit-scrollbar-thumb{background:rgba(26,100,196,.3);border-radius:4px;}
.orb .obh h2{font-size:26px;font-weight:800;color:#0E2233;margin:0;line-height:1.15;}
.osrc{font-family:ui-monospace,Consolas,monospace;font-size:14px;color:#0C4187;
  background:rgba(26,100,196,.11);padding:5px 11px;border-radius:8px;white-space:nowrap;}

/* 中心：實色 */
.orb.p0{z-index:40;opacity:1;filter:none;
  transform:none;                       /* 1:1 呈現，文字才不會被縮放取樣 */
  backface-visibility:hidden;
  -webkit-font-smoothing:antialiased;
  text-rendering:optimizeLegibility;
  background:linear-gradient(152deg,#FFFFFF 0%,#EAF4FE 52%,#F7FBFF 100%);
  border:1px solid #FFFFFF;
  box-shadow:inset 0 1px 0 #FFF, 0 0 0 1px rgba(150,205,245,.6),
             0 0 52px rgba(146,203,247,.62), 0 5px 0 rgba(196,226,250,.95),
             0 10px 0 rgba(166,206,240,.7), 0 16px 0 rgba(146,190,232,.4),
             0 34px 46px -12px rgba(16,60,110,.46),
             0 80px 100px -30px rgba(16,60,110,.55);}
/* 圍繞：半透明 */
.orb.p1,.orb.p2,.orb.p3{
  background:linear-gradient(152deg,rgba(255,255,255,.4),rgba(226,243,255,.24));
  border:1px solid rgba(255,255,255,.75);
  -webkit-backdrop-filter:blur(9px) saturate(150%);backdrop-filter:blur(9px) saturate(150%);
  box-shadow:0 0 0 1px rgba(150,205,245,.3), 0 20px 34px -14px rgba(16,60,110,.34);
  opacity:.42;filter:saturate(.7);}
.orb.p1{z-index:30;transform:translateX(-500px) translateZ(-320px) rotateY(34deg) scale(.72);}
.orb.p2{z-index:20;transform:translateY(-64px) translateZ(-660px) scale(.62);}
.orb.p3{z-index:30;transform:translateX(500px)  translateZ(-320px) rotateY(-34deg) scale(.72);}
.orb.p1:hover,.orb.p2:hover,.orb.p3:hover{opacity:.72;filter:none;}
/* 超過 4 張時的候補位：藏在最後面，輪到了才轉進來 */
.orb.phid{z-index:10;opacity:0;pointer-events:none;
  transform:translateY(-64px) translateZ(-900px) scale(.5);}

__INNER_CSS__
</style>
<div id="stage">__CARDS__</div>
<script>
(function(){
  var N=document.querySelectorAll('.orb').length||1, KEY='wr_orbit_cur', cur=0;
  // 自動刷新（每 5 分鐘）會重建 iframe，記住目前面板，避免每次都跳回第一張
  try{ var s=+sessionStorage.getItem(KEY); if(isFinite(s)&&s>=0&&s<N){ cur=s; } }catch(e){}
  function apply(){
    try{ sessionStorage.setItem(KEY, cur); }catch(e){}
    document.querySelectorAll('.orb').forEach(function(el){
      var i=+el.dataset.i, d=((i-cur)%N+N)%N;
      // 舞台只擺得下 4 張（中央＋左＋後＋右），再多的先藏到後面
      el.className='orb '+(d>3?'phid':'p'+d);
    });
  }
  document.querySelectorAll('.orb').forEach(function(el){
    el.addEventListener('click',function(){
      if(el.className.indexOf('p0')<0){ cur=+el.dataset.i; apply(); }
    });
  });
  apply();

  document.querySelectorAll('tr.drill').forEach(function(tr){
    tr.addEventListener('click', function(e){
      e.stopPropagation();
      var wo = tr.dataset.wo || '';
      var url = '/scheduling?wo=' + encodeURIComponent(wo);
      // Streamlit 的 components iframe sandbox 沒有 allow-top-navigation，
      // 改不了父視窗網址（SecurityError），但有 allow-popups → 用 window.open 開新分頁
      var base = '';
      try{ base = window.parent.location.origin; }catch(e){ base = location.origin; }
      var w = window.open(base + url, '_blank');
      if(!w){
        // 彈窗被擋時，退而顯示可手動點的連結
        tr.querySelector('td').innerHTML =
          '<a href="' + base + url + '" target="_blank" style="color:#0B4A86;font-weight:700">'
          + wo + ' ↗</a>';
      }
    });
  });

  document.querySelectorAll('.tbsearch').forEach(function(box){
    var q=box.querySelector('input'), n=box.querySelector('span');
    var tb=box.closest('.g2').querySelector('.wtb');
    if(!q||!tb) return;
    var run=function(){
      var v=q.value.trim().toLowerCase();
      var rows=[].slice.call(tb.rows,1), c=0;
      rows.forEach(function(r){
        var hit=!v || r.textContent.toLowerCase().indexOf(v)>=0;
        r.style.display=hit?'':'none';
        if(hit) c++;
      });
      n.textContent = v ? (c+' 筆符合') : (rows.length+' 筆');
    };
    q.addEventListener('input', run);
    q.addEventListener('click', function(e){ e.stopPropagation(); });
    run();
  });
})();
</script>
"""

_INNER_CSS = """
.g2{position:relative;border-radius:18px;-webkit-font-smoothing:antialiased;
  background:linear-gradient(150deg,rgba(255,255,255,.86),rgba(228,244,255,.66));
  border:1px solid rgba(255,255,255,1);
  box-shadow:inset 0 1px 0 rgba(255,255,255,1), 0 0 0 1px rgba(158,208,244,.5),
             0 2px 0 rgba(198,228,250,.95), 0 5px 0 rgba(166,206,240,.6),
             0 12px 20px -6px rgba(16,60,110,.32);}
.sm{padding:11px 15px;}
.chart{padding:13px 16px;display:flex;flex-direction:column;min-height:0;}
.lb{font-size:18px;color:#2C4A5E;font-weight:700;line-height:1.2;}
.vl{font-size:46px;font-weight:300;line-height:.95;letter-spacing:-.045em;color:#0E2233;
  font-variant-numeric:tabular-nums;margin-top:6px;}
.vl u{text-decoration:none;font-size:19px;color:#2B4557;margin-left:7px;font-weight:500;}
.bd{font-size:14px;color:#2B4557;margin-top:7px;font-weight:600;}
.ch{font-size:18px;font-weight:800;color:#152B3E;margin-bottom:11px;}
.stat-chip{font-size:15px;font-weight:800;padding:4px 12px;border-radius:9px;}
.trk{height:19px;border-radius:99px;background:rgba(76,46,160,.16);overflow:hidden;position:relative;
  box-shadow:inset 0 3px 5px rgba(40,22,100,.34), inset 0 -2px 0 rgba(255,255,255,.55);}
.trk>i{display:block;height:100%;border-radius:99px;font-style:normal;
  box-shadow:inset 0 2px 0 rgba(255,255,255,.5), inset 0 -5px 8px rgba(0,0,0,.28);}
.meta{font-size:14px;color:#2B4557;margin-top:8px;text-align:right;font-weight:600;}
.hr{height:1px;background:rgba(26,100,196,.22);margin:12px 0;}
.tbsearch{display:flex;align-items:center;gap:10px;margin-bottom:10px;}
.tbsearch input{flex:1;font:inherit;font-size:15px;color:#0E2233;padding:8px 13px;
  border-radius:11px;border:1px solid rgba(158,208,244,.9);outline:none;
  background:linear-gradient(150deg,rgba(255,255,255,.95),rgba(235,246,255,.85));
  box-shadow:inset 0 1px 3px rgba(16,60,110,.12);}
.tbsearch input:focus{border-color:#1668C6;box-shadow:0 0 0 3px rgba(26,100,196,.18);}
.tbsearch input::placeholder{color:#5A7387;}
.tbsearch span{font-size:14px;font-weight:700;color:#0C4187;white-space:nowrap;min-width:64px;}
.wtb{width:100%;border-collapse:collapse;}
.tbwrap{flex:1;min-height:0;}
.tbwrap::-webkit-scrollbar{width:6px;}
.tbwrap::-webkit-scrollbar-thumb{background:rgba(26,100,196,.32);border-radius:3px;}
.tbwrap::-webkit-scrollbar-track{background:transparent;}
.wtb thead th{position:sticky;top:0;z-index:2;
  background:linear-gradient(180deg,rgba(244,250,255,.98),rgba(232,244,255,.96));
  backdrop-filter:blur(4px);}
.wtb tbody tr:hover td{background:rgba(26,100,196,.06);}
.wtb tr.drill{cursor:pointer;}
.wtb tr.drill:hover td{background:rgba(26,100,196,.14)!important;}
.wtb tr.drill:hover td:first-child{box-shadow:inset 3px 0 0 #1668C6;}
.wtb tr.drill:active td{background:rgba(26,100,196,.22)!important;}
.wtb th{font-family:ui-monospace,Consolas,monospace;font-size:13px;color:#2B4557;text-align:left;
  padding:0 9px 8px 0;border-bottom:2px solid rgba(14,34,51,.8);font-weight:600;white-space:nowrap;}
.wtb td{padding:8px 9px 8px 0;border-bottom:1px solid rgba(26,100,196,.15);font-size:16px;
  color:#20394D;line-height:1.3;}
.wtb tr:last-child td{border-bottom:none;}
.wtb td.id{font-family:ui-monospace,Consolas,monospace;font-size:14px;color:#0E2233;font-weight:600;}
.wtb td.n{text-align:right;font-variant-numeric:tabular-nums;font-weight:700;color:#0E2233;}
.pill{display:inline-block;font-size:13px;font-weight:700;padding:3px 9px;
  border-radius:7px;white-space:nowrap;}
.wtb td.note{font-size:13px;color:#20394D;line-height:1.35;max-width:330px;}
.wtb td.pass{font-weight:800;color:#03503A;letter-spacing:.09em;}
"""

components.html(
    _ORBIT_HTML.replace("__CARDS__", _cards)
               .replace("__INNER_CSS__", _INNER_CSS),
    height=820, scrolling=False)
