import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from utils.shared import inject_css, render_header, render_sidebar

st.set_page_config(page_title="RMA總表", page_icon="🔄", layout="wide", initial_sidebar_state="expanded")
inject_css()

render_header(
    title="RMA 總表",
    subtitle="Return Material Authorization Summary &nbsp;·&nbsp; ORing Industrial Networking",
    badge="RMA",
    show_logo=False,
)
render_sidebar()

NAS_DIR  = r"\\192.168.2.34\MO_Storage\ORing MO\ORing-MO 工作\維修部\3_紀錄文件\3_01_RMA紀錄_交換機\3_01_01_每日統計_交換機\RMA總表"
DATA_RMA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "rma_latest.xlsx")
SHEET   = "RMA 總表"

CHART_LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(family="Arial,'標楷體',sans-serif", size=12, color="#334155"),
    margin=dict(l=10, r=10, t=36, b=10),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
)


# ── 載入 ──────────────────────────────────────────────────────────────────────

@st.cache_data(show_spinner=False)
def load_rma(file_bytes: bytes) -> pd.DataFrame:
    df = pd.read_excel(io.BytesIO(file_bytes), sheet_name=SHEET, engine="openpyxl")
    df.columns = df.columns.str.strip()
    df = df.rename(columns={"不良問題 ": "不良問題"}) if "不良問題 " in df.columns else df
    for col in ["收貨日期", "完修日期", "結案日期", "原始銷貨日期"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")
    for col in ["維修天數", "處理天數", "年", "月", "週"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "S/N" in df.columns:
        df = df[df["S/N"].notna() & (df["S/N"].astype(str).str.strip() != "")]
    # 若 B欄（年）為空或異常值（如 1900），從收貨日期自動補上
    if "收貨日期" in df.columns and "年" in df.columns:
        mask = (df["年"].isna() | (df["年"] < 2000)) & df["收貨日期"].notna()
        df.loc[mask, "年"] = df.loc[mask, "收貨日期"].dt.year
        df.loc[mask, "月"] = df.loc[mask, "收貨日期"].dt.month
    return df


def find_nas_file():
    try:
        files = sorted([
            f for f in os.listdir(NAS_DIR)
            if not f.startswith("~$") and f.startswith("RMA總表") and f.lower().endswith(".xlsx")
        ])
        return (os.path.join(NAS_DIR, files[-1]), files[-1]) if files else (None, None)
    except Exception:
        return None, None


# ── Sidebar：資料來源 ──────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("---")
    st.markdown(
        '<div style="color:#5eead4;font-size:0.72rem;font-weight:800;'
        'letter-spacing:0.1em;text-transform:uppercase;margin-bottom:6px;">📂 資料來源</div>',
        unsafe_allow_html=True,
    )

    nas_path, nas_name = find_nas_file()
    src_bytes, src_name = None, None

    if nas_path:
        st.success("✅ NAS 已連線")
        st.caption(f"最新檔：**{nas_name}**")
        if "rma_bytes" not in st.session_state:
            with open(nas_path, "rb") as f:
                st.session_state["rma_bytes"] = f.read()
            st.session_state["rma_name"] = nas_name
        if st.button("🔄 重新載入 NAS", use_container_width=True, key="rma_reload"):
            st.session_state.pop("rma_bytes", None)
            st.cache_data.clear()
            st.rerun()
        src_bytes = st.session_state.get("rma_bytes")
        src_name  = st.session_state.get("rma_name", nas_name)
    elif os.path.exists(DATA_RMA) and "rma_bytes" not in st.session_state:
        # NAS 離線時使用已同步的 data/ 資料
        with open(DATA_RMA, "rb") as f:
            st.session_state["rma_bytes"] = f.read()
        st.session_state["rma_name"] = "rma_latest.xlsx"
        st.info("📂 使用已同步資料（NAS 離線）")
        src_bytes = st.session_state.get("rma_bytes")
        src_name  = "rma_latest.xlsx"
    else:
        if "rma_bytes" in st.session_state:
            src_bytes = st.session_state["rma_bytes"]
            src_name  = st.session_state.get("rma_name", "已上傳")
        else:
            st.warning("⚠️ NAS 離線，請手動上傳")

    uploaded = st.file_uploader("手動上傳 RMA總表 (.xlsx)", type=["xlsx"], key="rma_upload")
    if uploaded:
        src_bytes = uploaded.read()
        src_name  = uploaded.name
        st.session_state.pop("rma_bytes", None)
        st.cache_data.clear()

if src_bytes is None:
    st.info("👈 請從左側連線 NAS 或手動上傳 RMA總表，以開始分析")
    st.stop()

with st.spinner("載入資料中…"):
    df = load_rma(src_bytes)

if df.empty:
    st.error("讀取失敗或工作表 'RMA 總表' 沒有資料。")
    st.stop()


# ── Sidebar：篩選 ─────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("---")
    st.markdown(
        '<div style="color:#5eead4;font-size:0.72rem;font-weight:800;'
        'letter-spacing:0.1em;text-transform:uppercase;margin-bottom:6px;">🔍 篩選條件</div>',
        unsafe_allow_html=True,
    )
    years = sorted(df["年"].dropna().astype(int).unique(), reverse=True)
    sel_years = st.multiselect("年份", years, default=[years[0]] if years else [])

    base = df[df["年"].isin(sel_years)] if sel_years else df
    months = sorted(base["月"].dropna().astype(int).unique())
    sel_months = st.multiselect("月份", months)

    statuses = sorted(df["狀態"].dropna().unique())
    sel_status = st.multiselect("狀態", statuses)

    engineers = sorted(df["維修人員"].dropna().astype(str).str.strip().unique())
    sel_engineer = st.multiselect("維修人員", engineers)

    warranty_opts = sorted(df["保固判斷"].dropna().unique()) if "保固判斷" in df.columns else []
    sel_warranty = st.multiselect("保固判斷", warranty_opts)


# ── 套用篩選 ──────────────────────────────────────────────────────────────────

filt = df.copy()
if sel_years:    filt = filt[filt["年"].isin(sel_years)]
if sel_months:   filt = filt[filt["月"].isin(sel_months)]
if sel_status:   filt = filt[filt["狀態"].isin(sel_status)]
if sel_engineer: filt = filt[filt["維修人員"].astype(str).str.strip().isin(sel_engineer)]
if sel_warranty: filt = filt[filt["保固判斷"].isin(sel_warranty)]


# ── KPI 卡片 ──────────────────────────────────────────────────────────────────

status_s = filt["狀態"].astype(str).str.strip() if "狀態" in filt.columns else pd.Series([""] * len(filt))

# 總數：V欄（收貨日期）有值的筆數
total   = int(filt["收貨日期"].notna().sum()) if "收貨日期" in filt.columns else len(filt)
# 已處理：Y欄包含「完修(結案)」
done    = int(status_s.str.contains("完修(結案)", regex=False, na=False).sum())
# 未處理：Y欄包含「待修(待維修)」，只要出現就計算
pending = int(status_s.str.contains("待修(待維修)", regex=False, na=False).sum())

rate     = f"{done/total*100:.1f}%" if total > 0 else "—"
avg_days = filt.loc[status_s.str.contains("完修(結案)", regex=False, na=False), "維修天數"].mean()
avg_str  = f"{avg_days:.1f} 天" if pd.notna(avg_days) else "—"

def kpi(icon, value, label, sub, color, bg):
    return f"""
<div style="background:{bg};border-radius:14px;padding:18px 16px 16px;
     border:1px solid #e2e8f0;box-shadow:0 3px 14px rgba(0,0,0,0.07);text-align:center;">
  <div style="font-size:1.6rem;line-height:1">{icon}</div>
  <div style="font-size:2.0rem;font-weight:900;color:{color};line-height:1.15;margin-top:6px">{value}</div>
  <div style="color:#1e293b;font-size:0.88rem;font-weight:700;margin-top:4px">{label}</div>
  <div style="color:#94a3b8;font-size:0.75rem;margin-top:2px">{sub}</div>
</div>"""

k1, k2, k3, k4, k5 = st.columns(5)
k1.markdown(kpi("📥", total,   "總收貨件數",    "收貨日期有值（V欄）",       "#1d4ed8", "#eff6ff"), unsafe_allow_html=True)
k2.markdown(kpi("✅", done,    "已處理",        "完修(結案)（Y欄）",         "#16a34a", "#f0fdf4"), unsafe_allow_html=True)
k3.markdown(kpi("🔧", pending, "未處理",        "待修(待維修)（Y欄）",       "#d97706", "#fffbeb"), unsafe_allow_html=True)
k4.markdown(kpi("📊", rate,    "完成率",        "已處理 ÷ 總收貨件數",       "#0891b2", "#ecfeff"), unsafe_allow_html=True)
k5.markdown(kpi("⏱",  avg_str, "平均維修天數",  "完修(結案) 件統計",         "#7c3aed", "#faf5ff"), unsafe_allow_html=True)

st.markdown("<div style='margin-top:22px'></div>", unsafe_allow_html=True)


# ── 圖表區 ────────────────────────────────────────────────────────────────────

# 1. 月趨勢（分組長條圖）
if not filt.empty and "收貨日期" in filt.columns:
    t = filt.copy()
    t["收貨月"] = t["收貨日期"].dt.to_period("M").astype(str)
    t["完修月"] = t["完修日期"].dt.to_period("M").astype(str)

    recv = t.groupby("收貨月").size().rename("收件數")
    comp = t.dropna(subset=["完修日期"]).groupby("完修月").size().rename("完修數")
    all_months = sorted(set(recv.index) | set(comp.index))
    recv = recv.reindex(all_months, fill_value=0)
    comp = comp.reindex(all_months, fill_value=0)

    fig_trend = go.Figure()
    fig_trend.add_bar(x=all_months, y=recv.values, name="收件數",
                      marker_color="#3b82f6", opacity=0.85)
    fig_trend.add_bar(x=all_months, y=comp.values, name="完修數",
                      marker_color="#22c55e", opacity=0.85)
    fig_trend.update_layout(
        **CHART_LAYOUT,
        title=dict(text="月趨勢：收件數 vs 完修數", font=dict(size=13, color="#1e293b")),
        barmode="group",
        height=280,
        xaxis=dict(showgrid=False, tickangle=-30),
        yaxis=dict(showgrid=True, gridcolor="#f1f5f9"),
    )
    st.plotly_chart(fig_trend, use_container_width=True)

# 2. 狀態分布 + 維修人員在架
col_l, col_r = st.columns(2)

with col_l:
    if "狀態" in filt.columns and not filt.empty:
        sc = filt["狀態"].value_counts().sort_values()
        colors = ["#22c55e" if "結案" in s else
                  "#3b82f6" if "完修" in s else
                  "#f59e0b" if "待修" in s else "#94a3b8"
                  for s in sc.index]
        fig_st = go.Figure(go.Bar(
            x=sc.values, y=sc.index, orientation="h",
            marker_color=colors, text=sc.values,
            textposition="outside", textfont=dict(size=11, color="#334155"),
        ))
        fig_st.update_layout(
            **CHART_LAYOUT,
            title=dict(text="狀態分布", font=dict(size=13, color="#1e293b")),
            height=280,
            showlegend=False,
            xaxis=dict(showgrid=True, gridcolor="#f1f5f9"),
            yaxis=dict(showgrid=False),
        )
        st.plotly_chart(fig_st, use_container_width=True)

with col_r:
    on_df = filt[filt["完修日期"].isna()]
    if "維修人員" in on_df.columns and not on_df.empty:
        ec = (on_df["維修人員"].astype(str).str.strip()
              .replace("nan", pd.NA).dropna().value_counts().sort_values())
        if not ec.empty:
            fig_eng = go.Figure(go.Bar(
                x=ec.values, y=ec.index, orientation="h",
                marker_color="#f97316", text=ec.values,
                textposition="outside", textfont=dict(size=11, color="#334155"),
            ))
            fig_eng.update_layout(
                **CHART_LAYOUT,
                title=dict(text="在架件數（依維修人員）", font=dict(size=13, color="#1e293b")),
                height=280,
                showlegend=False,
                xaxis=dict(showgrid=True, gridcolor="#f1f5f9"),
                yaxis=dict(showgrid=False),
            )
            st.plotly_chart(fig_eng, use_container_width=True)
        else:
            with col_r:
                st.info("目前無在架件數")

# 3. 保固分析（甜甜圈）+ 維修類別（甜甜圈）
col_d1, col_d2 = st.columns(2)

with col_d1:
    if "保固判斷" in filt.columns and not filt.empty:
        wc = filt["保固判斷"].dropna().value_counts()
        if not wc.empty:
            fig_w = go.Figure(go.Pie(
                labels=wc.index, values=wc.values, hole=0.5,
                marker_colors=["#3b82f6", "#f59e0b", "#94a3b8", "#22c55e"],
                textinfo="label+percent", textfont=dict(size=11),
            ))
            fig_w.update_layout(
                **CHART_LAYOUT,
                title=dict(text="保固分析", font=dict(size=13, color="#1e293b")),
                height=260,
            )
            st.plotly_chart(fig_w, use_container_width=True)

with col_d2:
    if "維修類別" in filt.columns and not filt.empty:
        rc = filt["維修類別"].dropna().value_counts()
        if not rc.empty:
            fig_r = go.Figure(go.Pie(
                labels=rc.index, values=rc.values, hole=0.5,
                marker_colors=["#6366f1", "#06b6d4", "#f43f5e", "#84cc16", "#fb923c"],
                textinfo="label+percent", textfont=dict(size=11),
            ))
            fig_r.update_layout(
                **CHART_LAYOUT,
                title=dict(text="維修類別分布", font=dict(size=13, color="#1e293b")),
                height=260,
            )
            st.plotly_chart(fig_r, use_container_width=True)

st.divider()


# ── 明細表 ────────────────────────────────────────────────────────────────────

st.markdown(
    f"**📋 RMA 明細**　共 **{len(filt)}** 筆　｜　"
    f"🟧 橘底 = 待修未完修（{pending} 件）　"
    f"<span style='background:#fee2e2;color:#dc2626;padding:1px 6px;border-radius:4px;font-size:0.8rem'>■ ≥14天</span>　"
    f"<span style='background:#fff3cd;color:#b45309;padding:1px 6px;border-radius:4px;font-size:0.8rem'>■ 7–13天</span>　"
    f"<span style='background:#d1fae5;color:#065f46;padding:1px 6px;border-radius:4px;font-size:0.8rem'>■ &lt;7天</span>",
    unsafe_allow_html=True,
)

search = st.text_input("🔍 搜尋", placeholder="S/N、客戶名稱、RMA單號、料號、業務…", key="rma_search")

SHOW_COLS = [
    "S/N", "RMA單號", "收貨日期", "客戶名稱", "業務",
    "威力料號", "保固判斷", "狀態", "維修人員",
    "完修日期", "結案日期", "維修天數", "處理天數",
    "廠測不良原因", "不良問題", "維修類別",
]
show = [c for c in SHOW_COLS if c in filt.columns]
disp = filt[show].copy()

if search:
    mask = disp.apply(
        lambda col: col.astype(str).str.contains(search, case=False, na=False)
    ).any(axis=1)
    disp = disp[mask]
    st.caption(f"搜尋「{search}」共找到 {len(disp)} 筆")

_today = pd.Timestamp.now().normalize()

def highlight_row(row):
    cols = list(row.index)

    # 底色：待修列全橘
    if "待修" in str(row.get("狀態", "")):
        styles = ["background-color:#fff7ed; color:#92400e"] * len(cols)
    else:
        styles = [""] * len(cols)

    # 收貨日期欄依天數上色（覆蓋底色）
    if "收貨日期" in cols:
        idx = cols.index("收貨日期")
        val = row["收貨日期"]
        if pd.notna(val):
            days = (_today - pd.Timestamp(val)).days
            if days >= 14:
                styles[idx] = "background-color:#fee2e2; color:#dc2626; font-weight:700"
            elif days >= 7:
                styles[idx] = "background-color:#fff3cd; color:#b45309; font-weight:700"
            else:
                styles[idx] = "background-color:#d1fae5; color:#065f46; font-weight:700"

    return styles

st.dataframe(
    disp.style.apply(highlight_row, axis=1),
    use_container_width=True,
    height=520,
)

buf = io.BytesIO()
disp.to_excel(buf, index=False, engine="openpyxl")
buf.seek(0)
st.download_button(
    "⬇️ 匯出篩選結果（Excel）",
    data=buf,
    file_name=f"RMA總表_篩選_{pd.Timestamp.now().strftime('%Y%m%d')}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)
