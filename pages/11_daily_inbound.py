import io
import random
import sys
import os
from datetime import date, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from utils.shared import inject_css, render_header, render_sidebar

st.set_page_config(page_title="每日入庫筆數", page_icon="🏬", layout="wide")
inject_css()
render_header(title="每日入庫筆數", subtitle="Daily Inbound Count · Warehouse Management", badge="倉管 WH")
render_sidebar()

# ─── 範例資料 ─────────────────────────────────────────────────────────────────

@st.cache_data
def _generate(today_str: str):
    today = date.fromisoformat(today_str)
    rng = random.Random(42)

    vendors = ["鴻海精密", "台達電子", "光寶科技", "研華科技", "威強電"]
    parts = [
        ("1.01.0001", "電阻 10KΩ 1%"),
        ("1.01.0002", "電容 100uF 25V"),
        ("1.02.0015", "IC 微控制器 STM32"),
        ("1.02.0033", "IC 電源管理"),
        ("1.03.0007", "連接器 RJ45"),
        ("1.03.0008", "連接器 SFP"),
        ("2.01.0101", "PCB 主板"),
        ("2.01.0102", "PCB 子板"),
        ("3.01.0201", "散熱片 40×40"),
        ("3.02.0305", "外殼鋁合金"),
    ]

    rows = []
    gr = 1000
    for offset in range(-9, 1):
        day = today + timedelta(days=offset)
        for _ in range(rng.randint(5, 14)):
            pno, pname = rng.choice(parts)
            received: date | None = None
            putaway:  date | None = None

            if offset < 0:
                received = day
            elif offset == 0 and rng.random() < 0.72:
                received = day

            if received is not None:
                lag = (today - received).days
                if lag == 0:
                    putaway = received if rng.random() < 0.58 else None
                elif lag == 1:
                    putaway = received + timedelta(days=rng.randint(0, 1)) if rng.random() < 0.78 else None
                else:
                    putaway = received + timedelta(days=rng.randint(0, min(lag, 2))) if rng.random() < 0.90 else None

            gr += 1
            rows.append({
                "收貨單號":   f"GR-{gr}",
                "品號":       pno,
                "品名":       pname,
                "廠商":       rng.choice(vendors),
                "預計收貨日": day + timedelta(days=rng.randint(-1, 1)),
                "實際收貨日": received,
                "入庫日期":   putaway,
                "數量":       rng.randint(1, 50) * 10,
            })

    df = pd.DataFrame(rows)
    df["實際收貨日"] = pd.to_datetime(df["實際收貨日"])
    df["入庫日期"]   = pd.to_datetime(df["入庫日期"])
    df["預計收貨日"] = pd.to_datetime(df["預計收貨日"])
    return df


df = _generate(date.today().isoformat())

# ─── 日期選擇 ─────────────────────────────────────────────────────────────────

col_hd, _ = st.columns([1, 4])
with col_hd:
    sel = st.date_input("查詢日期", value=date.today(), key="inbound_date")

today_ts = pd.Timestamp(sel)

# ─── 四大指標 ─────────────────────────────────────────────────────────────────

m1 = df[df["實際收貨日"].notna() & (df["實際收貨日"] < today_ts)]
m2 = df[df["實際收貨日"].notna() & (df["實際收貨日"].dt.date == sel)]
m3 = df[df["實際收貨日"].notna() & (df["實際收貨日"] < today_ts) & df["入庫日期"].isna()]
m4 = df[df["入庫日期"].notna()   & (df["入庫日期"].dt.date == sel)]

c1, c2, c3, c4 = st.columns(4)

with c1:
    st.metric(
        label="今日前已收貨項次",
        value=f"{len(m1)} 筆",
        help="查詢日以前，實際到貨並完成收貨的項次合計（含已入庫）",
    )
with c2:
    st.metric(
        label="今日已收貨項次",
        value=f"{len(m2)} 筆",
        delta=f"+{len(m2)}",
        help="查詢當日新增收貨的項次",
    )
with c3:
    st.metric(
        label="今日前待入庫項次",
        value=f"{len(m3)} 筆",
        delta=f"−{len(m3)}" if len(m3) else "0",
        delta_color="inverse",
        help="查詢日以前已收貨、但尚未完成入庫上架的積壓項次",
    )
with c4:
    st.metric(
        label="今日已入庫項次",
        value=f"{len(m4)} 筆",
        delta=f"+{len(m4)}",
        help="查詢當日完成入庫上架的項次",
    )

st.divider()

# ─── 圖表 ────────────────────────────────────────────────────────────────────

col_bar, col_pie = st.columns([3, 2])

with col_bar:
    st.markdown("#### 近 7 日收貨 vs 入庫 趨勢")
    days7 = [sel - timedelta(days=i) for i in range(6, -1, -1)]
    recv7 = [int((df["實際收貨日"].dt.date == d).sum()) for d in days7]
    put7  = [int((df["入庫日期"].dt.date    == d).sum()) for d in days7]
    xlbl  = [d.strftime("%m/%d") for d in days7]

    fig_bar = go.Figure()
    fig_bar.add_trace(go.Bar(
        name="收貨筆數", x=xlbl, y=recv7,
        marker_color="#6d28d9", opacity=0.85,
        text=recv7, textposition="outside",
        textfont=dict(size=11),
    ))
    fig_bar.add_trace(go.Bar(
        name="入庫筆數", x=xlbl, y=put7,
        marker_color="#a78bfa", opacity=0.85,
        text=put7, textposition="outside",
        textfont=dict(size=11),
    ))
    fig_bar.update_layout(
        barmode="group",
        plot_bgcolor="white", paper_bgcolor="white",
        height=300, margin=dict(t=30, b=10, l=10, r=10),
        legend=dict(orientation="h", y=-0.18, x=0.5, xanchor="center"),
        yaxis=dict(gridcolor="#f0f0f0", rangemode="tozero"),
        font=dict(family="sans-serif", size=12),
    )
    st.plotly_chart(fig_bar, use_container_width=True)

with col_pie:
    st.markdown("#### 今日入庫狀態分布")
    today_recv = df[df["實際收貨日"].dt.date == sel]
    n_done     = int((today_recv["入庫日期"].dt.date == sel).sum())
    n_wait_td  = int(today_recv["入庫日期"].isna().sum())
    n_backlog  = len(m3)

    labels = ["今日已入庫", "今日收貨待入庫", "歷史積壓待入庫"]
    values = [n_done, n_wait_td, n_backlog]
    colors = ["#6d28d9", "#a78bfa", "#ddd6fe"]

    fig_pie = go.Figure(go.Pie(
        labels=labels, values=values, hole=0.52,
        marker=dict(colors=colors, line=dict(color="#ffffff", width=2)),
        textinfo="label+percent",
        hovertemplate="%{label}: %{value} 筆<extra></extra>",
    ))
    fig_pie.add_annotation(
        text=f"<b>{n_done + n_wait_td + n_backlog}</b><br>筆",
        x=0.5, y=0.5, font_size=18, showarrow=False,
    )
    fig_pie.update_layout(
        height=300, margin=dict(t=30, b=10, l=10, r=10),
        showlegend=False, paper_bgcolor="white",
        font=dict(family="sans-serif", size=12),
    )
    st.plotly_chart(fig_pie, use_container_width=True)

st.divider()

# ─── 報表 ────────────────────────────────────────────────────────────────────

def _fmt(src: pd.DataFrame) -> pd.DataFrame:
    d = src[[
        "收貨單號", "品號", "品名", "廠商",
        "預計收貨日", "實際收貨日", "入庫日期", "數量",
    ]].copy()
    for col in ("預計收貨日", "實際收貨日", "入庫日期"):
        d[col] = d[col].apply(
            lambda v: v.strftime("%Y-%m-%d") if pd.notna(v) else "—"
        )
    d["數量"] = d["數量"].apply(lambda x: f"{x:,}")
    d.index = range(1, len(d) + 1)
    return d


tab1, tab2, tab3, tab4 = st.tabs([
    f"今日收貨明細（{len(m2)} 筆）",
    f"今日前待入庫積壓（{len(m3)} 筆）",
    f"今日已入庫明細（{len(m4)} 筆）",
    f"完整明細（{len(df)} 筆）",
])

with tab1:
    if m2.empty:
        st.info("今日暫無收貨紀錄。")
    else:
        st.dataframe(_fmt(m2), use_container_width=True)

with tab2:
    if m3.empty:
        st.success("今日前無待入庫積壓，作業狀況良好！")
    else:
        st.caption("⚠️ 以下項次已收貨但尚未完成入庫上架，請盡快處理。")
        st.dataframe(_fmt(m3.sort_values("實際收貨日")), use_container_width=True)

with tab3:
    if m4.empty:
        st.info("今日暫無入庫紀錄。")
    else:
        st.dataframe(_fmt(m4), use_container_width=True)

with tab4:
    st.dataframe(
        _fmt(df.sort_values("實際收貨日", ascending=False, na_position="last")),
        use_container_width=True,
    )

# ─── 下載 ────────────────────────────────────────────────────────────────────

st.divider()


def _to_excel(src: pd.DataFrame, sheet: str) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        src.to_excel(w, index=False, sheet_name=sheet)
    return buf.getvalue()


dc1, dc2, _ = st.columns([1, 1, 3])
with dc1:
    st.download_button(
        label="⬇️ 下載今日報表（Excel）",
        data=_to_excel(
            pd.concat([m2, m3, m4]).drop_duplicates().sort_values(
                "實際收貨日", ascending=False, na_position="last"
            ),
            "每日入庫",
        ),
        file_name=f"每日入庫筆數_{sel}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )
with dc2:
    st.download_button(
        label="⬇️ 下載完整明細（Excel）",
        data=_to_excel(
            df.sort_values("實際收貨日", ascending=False, na_position="last"),
            "完整明細",
        ),
        file_name=f"入庫完整明細_{sel}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )
