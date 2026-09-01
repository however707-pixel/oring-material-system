import io
import os
import sys

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from utils.shared import inject_css, render_header, render_sidebar
from utils.warroom_data import (ASSEMBLY_ROOT, PACKAGE_ROOT, TAKT_PEOPLE,
                                TAKT_TRIM, TEST_ROOTS, total_worktime_table)

st.set_page_config(page_title="總計工時表", page_icon="⏱", layout="wide")
inject_css()
render_header(title="總計工時表", subtitle="Total Work Time Summary · Process Station", badge="製程站 PS")
render_sidebar()

# ─── 說明 ─────────────────────────────────────────────────────────────────────
# 四站的機種平均工時相加＝一台成品的總工時。各站口徑沿用各自的頁面，
# 這裡只負責以「成品料號」為 key 對起來相加（計算在 utils/warroom_data.py）。

STATIONS = ["組裝(分)", "第一測程(分)", "第二測程(分)", "包裝(分)"]
BAR_COLORS = {"組裝(分)": "#14b8a6", "第一測程(分)": "#6366f1",
              "第二測程(分)": "#a855f7", "包裝(分)": "#f59e0b"}

with st.expander("📖 計算邏輯說明"):
    st.markdown(f"""
| 站別 | 平均工時怎麼來 | 資料來源 |
|---|---|---|
| **組裝** | 單台：有刷 End 取**頭尾工時**，只有 Start 取**節拍（頭頭）× 線上人數**；<br>再把該料號所有單台值去頭 {TAKT_TRIM:.0%}、去尾 {TAKT_TRIM:.0%} 取中間 {1 - 2 * TAKT_TRIM:.0%} 平均 | `{ASSEMBLY_ROOT}` |
| **第一／第二測程** | 同一 料號/工單/人員 內**相鄰兩筆 PASS Log 的分鐘差**（秒數捨去），<br>排除跨日與 > 中斷門檻的區間，再把該料號的有效區間全部取平均 | `{TEST_ROOTS["第一測程"]}`<br>`{TEST_ROOTS["第二測程"]}` |
| **包裝** | 單台**只取頭尾工時 End − Start**（包裝每台都會刷 End，只有 Start＝還在生產中）；<br>再去頭去尾 {TAKT_TRIM:.0%} 取中間 {1 - 2 * TAKT_TRIM:.0%} 平均 | `{PACKAGE_ROOT}` |
| **合計工時** | **組裝 ＋ 第一測程 ＋ 第二測程 ＋ 包裝**（缺資料的站以 0 計，「資料狀態」會標出來） | — |
| **完成品判定** | **組裝／測試／包裝三站都有值** → 這台的合計工時是完整的，資料狀態標 `✅ 完成品`。<br>測試**不一定兩站都跑**，第一或第二測程**任一有值就算過了測試**（第二測程空白多半是該機種不用測 PoE） | — |
| **機種對應** | 四站的 Log 都以**成品料號資料夾**為頂層，去掉 `#` 補位字元後直接對字串 | — |
""", unsafe_allow_html=True)

st.info("**這是「一台成品的平均工時」，不是產能**：各站的平均彼此獨立相加。"
        "**組裝／測試／包裝三站都有值就是完成品**（測試任一測程有值即可）；"
        "缺站的機種以 0 計，請搭配「資料狀態」欄一起看。", icon="ℹ️")

# ─── 控制列 ───────────────────────────────────────────────────────────────────

c_btn, c_g1, c_g2, c_ppl, _ = st.columns([1.2, 1.3, 1.3, 1.1, 2.1])
with c_btn:
    st.markdown("<div style='height:1.75rem'></div>", unsafe_allow_html=True)
    if st.button("🔄 重新掃描 NAS", width='stretch'):
        total_worktime_table.clear()
        st.rerun()
with c_g1:
    gap_assy = st.number_input("組裝／包裝 異常門檻 (分)", min_value=5, max_value=1440, value=120,
                               help="單台工時或節拍超過此分鐘數視為換線／等料／休息，不計入平均")
with c_g2:
    gap_test = st.number_input("測試 中斷門檻 (分)", min_value=5, max_value=480, value=30,
                               help="兩筆 PASS Log 間隔超過此分鐘數視為中斷，不計入平均")
with c_ppl:
    people = st.number_input("組裝線上人數", min_value=1, max_value=50, value=TAKT_PEOPLE,
                             help="組裝站「只有 Start」的那些台：標準工時 = 節拍 × 人數")

with st.spinner("掃描四站 NAS Log 中…（第一次約 2～3 分鐘，之後 30 分鐘內走快取）"):
    table, warns = total_worktime_table(gap_assy, gap_test, people, TAKT_TRIM)

for w in warns:
    st.warning(w)
if table.empty:
    st.error("四個站都沒有可用的 Log，無法計算。")
    st.stop()

# ─── 篩選 ─────────────────────────────────────────────────────────────────────

f1, f2 = st.columns([1.4, 3])
with f1:
    only_full = st.checkbox("只看完成品機種", value=False,
                            help="組裝／測試／包裝三站都有值的機種；測試只要任一測程有值就算")
with f2:
    kw = st.text_input("料號關鍵字", placeholder="例：IGPS、IES1160…").strip()

view = table if not only_full else table[table["完成品"]]
if kw:
    view = view[view["成品料號"].str.contains(kw, case=False, na=False)]
if view.empty:
    st.info("沒有符合條件的機種。")
    st.stop()

# ─── KPI ──────────────────────────────────────────────────────────────────────

n_model = len(view)
n_full = int(view["完成品"].sum())
full_view = view[view["完成品"]]
avg_full = full_view["合計工時(分)"].mean() if not full_view.empty else float("nan")

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("機種數", f"{n_model} 種")
m2.metric("完成品機種", f"{n_full} 種",
          help="組裝、測試、包裝三站都有值＝這台的工時是完整的；測試不一定兩站都跑，任一測程有值即可")
m3.metric("完成品平均合計", "—" if pd.isna(avg_full) else f"{avg_full:.1f} 分",
          help="只統計三站都有值的完成品機種，避免被缺站的機種拉低")
m4.metric("最長合計工時", f'{view["合計工時(分)"].max():.1f} 分',
          help=view.loc[view["合計工時(分)"].idxmax(), "成品料號"])
m5.metric("最短合計工時", f'{view["合計工時(分)"].min():.1f} 分',
          help=view.loc[view["合計工時(分)"].idxmin(), "成品料號"])

# ─── 主表 ─────────────────────────────────────────────────────────────────────

st.subheader("📋 每機種成品工時表")
st.caption("合計工時 ＝ 組裝 ＋ 第一測程 ＋ 第二測程 ＋ 包裝；缺資料的站以 0 計，"
           "排序為「完成品優先，再依合計工時由大到小」。"
           "**組裝／測試／包裝三站都有值＝完成品**（測試不一定兩站都跑，任一測程有值就算過站；"
           "第二測程空白多半是該機種本來就不用測 PoE）。")

SHOW_COLS = ["成品料號"] + STATIONS[:2] + ["第二測程(分)", "測試小計(分)", "包裝(分)",
                                            "合計工時(分)", "資料狀態"]
show = view[SHOW_COLS].copy()
# 沒資料的站顯示「—」而不是 None：pandas 3 的 NaN 走 Streamlit 表格會印成 None
st.dataframe(show.style.format(na_rep="—", precision=1),
             width="stretch", hide_index=True)

buf = io.BytesIO()
view.drop(columns=["完成品"]).to_excel(buf, index=False, engine="openpyxl")
buf.seek(0)
st.download_button("⬇ 匯出成品工時表 (Excel)", data=buf,
                   file_name="total_worktime.xlsx",
                   mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# ─── 堆疊圖：各站佔比 ─────────────────────────────────────────────────────────

st.divider()
top_n = min(15, len(view))
st.subheader(f"📊 合計工時最長的 {top_n} 個機種（各站堆疊）")

chart_df = view.nlargest(top_n, "合計工時(分)")            # 直式：最長的排最左邊
fig = go.Figure()
for col in STATIONS:
    vals = chart_df[col].fillna(0)
    fig.add_bar(
        x=chart_df["成品料號"], y=vals, name=col.replace("(分)", ""),
        marker_color=BAR_COLORS[col],
        text=[f"{v:.1f}" if v > 0 else "" for v in vals],
        textposition="inside", insidetextanchor="middle", textangle=0,
        textfont=dict(color="#ffffff", size=11), cliponaxis=False,
        hovertemplate="%{x}<br>" + col.replace("(分)", "") + "：%{y:.1f} 分<extra></extra>",
    )
fig.update_layout(
    barmode="stack",
    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0,
                font=dict(color="#33415e", size=12)),
    xaxis=dict(showgrid=False, tickangle=-45,
               tickfont=dict(color="#33415e", size=11)),
    yaxis=dict(title=dict(text="分鐘 / 台", font=dict(color="#5a6b85", size=12)),
               showgrid=True, gridcolor="rgba(45,212,191,0.18)",
               tickfont=dict(color="#5a6b85", size=11), zeroline=False),
    margin=dict(l=10, r=10, t=10, b=10),
    height=560,
)
st.plotly_chart(fig, width='stretch')

# ─── 樣本數 ───────────────────────────────────────────────────────────────────

with st.expander("🔍 各站有效樣本數（判斷這筆平均可不可信）"):
    st.caption("組裝／包裝為「算得出標準工時的台數」；測試為該料號的不重複序號台數。")
    st.dataframe(
        view[["成品料號", "組裝樣本(台)", "第一測程台數", "第二測程台數",
              "包裝樣本(台)", "資料狀態"]].style.format(na_rep="—", precision=0),
        width="stretch", hide_index=True)
