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

st.set_page_config(page_title="每日備料筆數", page_icon="🏬", layout="wide")
inject_css()
render_header(title="每日備料筆數", subtitle="Daily Material Preparation Count · Warehouse Management", badge="倉管 WH")
render_sidebar()

# ─── 自訂指標卡 HTML ──────────────────────────────────────────────────────────

def _card(title: str, total: int, note: str = "",
          breakdown: dict | None = None,
          delta: str | None = None, delta_inv: bool = False) -> str:
    delta_color = "#dc2626" if delta_inv else "#16a34a"
    delta_html = (
        f'<div style="font-size:.82rem;color:{delta_color};font-weight:700;margin-top:3px;">{delta}</div>'
        if delta else ""
    )
    bd_html = ""
    if breakdown:
        items = "".join(
            f'<span style="display:inline-flex;align-items:center;gap:3px;'
            f'background:#f5f3ff;border-radius:6px;padding:2px 8px;'
            f'font-size:.76rem;color:#6d28d9;font-weight:600;">'
            f'{k} <b style="color:#7c3aed;">{v}</b> 筆</span>'
            for k, v in breakdown.items()
        )
        bd_html = f'<div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:8px;">{items}</div>'
    note_html = (
        f'<div style="font-size:.72rem;color:#94a3b8;margin-top:5px;">{note}</div>'
        if note else ""
    )
    return f"""
    <div style="background:white;border-radius:12px;padding:18px 22px 16px;
                border:1px solid #e2e8f0;border-left:4px solid #6d28d9;
                box-shadow:0 2px 14px rgba(109,40,217,.08);height:100%;">
        <div style="font-size:.72rem;color:#64748b;font-weight:700;
                    letter-spacing:.06em;text-transform:uppercase;margin-bottom:6px;">
            {title}
        </div>
        <div style="font-size:2.1rem;font-weight:900;color:#1e293b;line-height:1.15;">
            {total}
            <span style="font-size:1rem;font-weight:500;color:#94a3b8;">筆</span>
        </div>
        {delta_html}{bd_html}{note_html}
    </div>"""


# ─── 範例資料 ─────────────────────────────────────────────────────────────────

@st.cache_data
def _generate(today_str: str) -> pd.DataFrame:
    today = date.fromisoformat(today_str)
    rng = random.Random(99)

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
    lines, pk, wo = [], 2000, 5000

    for offset in range(-9, 1):
        day = today + timedelta(days=offset)
        for _ in range(rng.randint(6, 16)):
            pno, pname = rng.choice(parts)
            typ = "廠內" if rng.random() < 0.60 else "委外"
            need_date = day + timedelta(days=rng.randint(0, 3))

            done: date | None = None
            if offset < 0:
                lag = (today - day).days
                if lag >= 2 and rng.random() < 0.88:
                    done = day + timedelta(days=rng.randint(0, min(lag, 2)))
                elif lag == 1 and rng.random() < 0.72:
                    done = day + timedelta(days=rng.randint(0, 1))
            elif offset == 0 and rng.random() < 0.55:
                done = day

            pk += 1; wo += 1
            lines.append({
                "備料單號":   f"PK-{pk}",
                "工單號":     f"WO-{wo}",
                "品號":       pno,
                "品名":       pname,
                "類型":       typ,
                "建立日期":   day,
                "需求日期":   need_date,
                "完成日期":   done,
                "需求數量":   rng.randint(1, 60) * 10,
            })

    df = pd.DataFrame(lines)
    df["建立日期"] = pd.to_datetime(df["建立日期"])
    df["需求日期"] = pd.to_datetime(df["需求日期"])
    df["完成日期"] = pd.to_datetime(df["完成日期"])
    return df


df = _generate(date.today().isoformat())

# ─── 日期選擇 ─────────────────────────────────────────────────────────────────

col_hd, _ = st.columns([1, 4])
with col_hd:
    sel = st.date_input("查詢日期", value=date.today(), key="pick_date")

sel_ts = pd.Timestamp(sel)

# ─── 指標計算 ─────────────────────────────────────────────────────────────────

# m1: 今日前建立、尚未完成（積壓）
m1 = df[(df["建立日期"] < sel_ts) & df["完成日期"].isna()]
m1_n  = {"廠內": int((m1["類型"] == "廠內").sum()), "委外": int((m1["類型"] == "委外").sum())}

# m2: 今日已完成備料
m2 = df[df["完成日期"].notna() & (df["完成日期"].dt.date == sel)]

# m3: 今日新增（今日建立）
m3 = df[df["建立日期"].dt.date == sel]
m3_n  = {"廠內": int((m3["類型"] == "廠內").sum()), "委外": int((m3["類型"] == "委外").sum())}

# m4: 目前全部待備料（未完成，不限建立日期）
m4 = df[df["完成日期"].isna()]
m4_n  = {"廠內": int((m4["類型"] == "廠內").sum()), "委外": int((m4["類型"] == "委外").sum())}

# ─── 四大指標卡 ───────────────────────────────────────────────────────────────

c1, c2, c3, c4 = st.columns(4)
with c1:
    st.markdown(_card(
        "今日前需備料積壓",
        len(m1),
        "今日以前建立、尚未完成備料",
        breakdown=m1_n,
        delta=f"−{len(m1)}" if len(m1) else "0",
        delta_inv=True,
    ), unsafe_allow_html=True)

with c2:
    st.markdown(_card(
        "今日已備料",
        len(m2),
        "今日完成備料的項次",
        delta=f"+{len(m2)}",
    ), unsafe_allow_html=True)

with c3:
    st.markdown(_card(
        "今日新增備料",
        len(m3),
        "今日新開立的備料項次",
        breakdown=m3_n,
        delta=f"+{len(m3)}",
    ), unsafe_allow_html=True)

with c4:
    st.markdown(_card(
        "目前待備料",
        len(m4),
        "所有尚未完成備料的項次",
        breakdown=m4_n,
        delta=f"−{len(m4)}" if len(m4) else "0",
        delta_inv=True,
    ), unsafe_allow_html=True)

st.divider()

# ─── 圖表 ────────────────────────────────────────────────────────────────────

col_bar, col_pie = st.columns([3, 2])

with col_bar:
    st.markdown("#### 近 7 日備料新增 vs 完成 趨勢（廠內 / 委外）")
    days7  = [sel - timedelta(days=i) for i in range(6, -1, -1)]
    xlbl   = [d.strftime("%m/%d") for d in days7]

    def _cnt(cond): return [int(cond(d)) for d in days7]

    add_in  = _cnt(lambda d: ((df["建立日期"].dt.date == d) & (df["類型"] == "廠內")).sum())
    add_out = _cnt(lambda d: ((df["建立日期"].dt.date == d) & (df["類型"] == "委外")).sum())
    don_in  = _cnt(lambda d: (df["完成日期"].notna() & (df["完成日期"].dt.date == d) & (df["類型"] == "廠內")).sum())
    don_out = _cnt(lambda d: (df["完成日期"].notna() & (df["完成日期"].dt.date == d) & (df["類型"] == "委外")).sum())

    fig_bar = go.Figure()
    fig_bar.add_trace(go.Bar(name="廠內新增", x=xlbl, y=add_in,
                             marker_color="#6d28d9", opacity=.85,
                             text=add_in, textposition="inside", textfont=dict(size=10, color="white")))
    fig_bar.add_trace(go.Bar(name="委外新增", x=xlbl, y=add_out,
                             marker_color="#a78bfa", opacity=.85,
                             text=add_out, textposition="inside", textfont=dict(size=10)))
    fig_bar.add_trace(go.Bar(name="廠內完成", x=xlbl, y=don_in,
                             marker_color="#14b8a6", opacity=.85,
                             text=don_in, textposition="inside", textfont=dict(size=10, color="white")))
    fig_bar.add_trace(go.Bar(name="委外完成", x=xlbl, y=don_out,
                             marker_color="#5eead4", opacity=.85,
                             text=don_out, textposition="inside", textfont=dict(size=10)))
    fig_bar.update_layout(
        barmode="stack",
        plot_bgcolor="white", paper_bgcolor="white",
        height=320, margin=dict(t=30, b=10, l=10, r=10),
        legend=dict(orientation="h", y=-0.22, x=0.5, xanchor="center"),
        yaxis=dict(gridcolor="#f0f0f0", rangemode="tozero"),
        font=dict(family="sans-serif", size=12),
    )
    st.plotly_chart(fig_bar, use_container_width=True)

with col_pie:
    st.markdown("#### 目前待備料分布")
    labels = ["廠內待備料", "委外待備料"]
    values = [m4_n["廠內"], m4_n["委外"]]
    colors = ["#6d28d9", "#a78bfa"]

    fig_pie = go.Figure(go.Pie(
        labels=labels, values=values, hole=0.52,
        marker=dict(colors=colors, line=dict(color="#fff", width=2)),
        textinfo="label+percent",
        hovertemplate="%{label}: %{value} 筆<extra></extra>",
    ))
    fig_pie.add_annotation(
        text=f"<b>{len(m4)}</b><br>待備料",
        x=0.5, y=0.5, font_size=16, showarrow=False,
    )
    fig_pie.update_layout(
        height=320, margin=dict(t=30, b=10, l=10, r=10),
        showlegend=False, paper_bgcolor="white",
        font=dict(family="sans-serif", size=12),
    )
    st.plotly_chart(fig_pie, use_container_width=True)

# ─── 第二行圖表：完成率進度條 ────────────────────────────────────────────────

total_all  = len(df)
total_done = int(df["完成日期"].notna().sum())
rate       = round(total_done / total_all * 100, 1) if total_all else 0

in_all  = int((df["類型"] == "廠內").sum())
in_done = int((df["完成日期"].notna() & (df["類型"] == "廠內")).sum())
out_all  = int((df["類型"] == "委外").sum())
out_done = int((df["完成日期"].notna() & (df["類型"] == "委外")).sum())
in_rate  = round(in_done  / in_all  * 100, 1) if in_all  else 0
out_rate = round(out_done / out_all * 100, 1) if out_all else 0

st.markdown(f"""
<div style="background:white;border-radius:12px;padding:18px 28px;
            border:1px solid #e2e8f0;box-shadow:0 2px 12px rgba(0,0,0,.06);margin-bottom:8px;">
    <div style="font-size:.8rem;color:#64748b;font-weight:700;letter-spacing:.06em;
                text-transform:uppercase;margin-bottom:12px;">整體備料完成率</div>
    <div style="display:flex;gap:32px;flex-wrap:wrap;align-items:center;">
        <div style="flex:1;min-width:220px;">
            <div style="display:flex;justify-content:space-between;
                        font-size:.82rem;font-weight:600;color:#475569;margin-bottom:4px;">
                <span>整體</span><span style="color:#6d28d9;">{rate}%（{total_done}/{total_all}）</span>
            </div>
            <div style="background:#ede9fe;border-radius:8px;height:10px;">
                <div style="background:#6d28d9;border-radius:8px;height:10px;width:{rate}%;transition:width .4s;"></div>
            </div>
        </div>
        <div style="flex:1;min-width:220px;">
            <div style="display:flex;justify-content:space-between;
                        font-size:.82rem;font-weight:600;color:#475569;margin-bottom:4px;">
                <span>廠內</span><span style="color:#7c3aed;">{in_rate}%（{in_done}/{in_all}）</span>
            </div>
            <div style="background:#ede9fe;border-radius:8px;height:10px;">
                <div style="background:#7c3aed;border-radius:8px;height:10px;width:{in_rate}%;"></div>
            </div>
        </div>
        <div style="flex:1;min-width:220px;">
            <div style="display:flex;justify-content:space-between;
                        font-size:.82rem;font-weight:600;color:#475569;margin-bottom:4px;">
                <span>委外</span><span style="color:#a78bfa;">{out_rate}%（{out_done}/{out_all}）</span>
            </div>
            <div style="background:#ede9fe;border-radius:8px;height:10px;">
                <div style="background:#a78bfa;border-radius:8px;height:10px;width:{out_rate}%;"></div>
            </div>
        </div>
    </div>
</div>
""", unsafe_allow_html=True)

st.divider()

# ─── 報表 ────────────────────────────────────────────────────────────────────

COLS = ["備料單號", "工單號", "品號", "品名", "類型",
        "建立日期", "需求日期", "完成日期", "需求數量"]


def _fmt(src: pd.DataFrame) -> pd.DataFrame:
    d = src[COLS].copy()
    for col in ("建立日期", "需求日期", "完成日期"):
        d[col] = d[col].apply(lambda v: v.strftime("%Y-%m-%d") if pd.notna(v) else "—")
    d["需求數量"] = d["需求數量"].apply(lambda x: f"{x:,}")
    d.index = range(1, len(d) + 1)
    return d


tab1, tab2, tab3, tab4 = st.tabs([
    f"今日前積壓待備料（{len(m1)} 筆）",
    f"今日已備料明細（{len(m2)} 筆）",
    f"今日新增備料（{len(m3)} 筆）",
    f"完整明細（{len(df)} 筆）",
])

with tab1:
    if m1.empty:
        st.success("今日前無積壓待備料，作業狀況良好！")
    else:
        st.caption("⚠️ 今日以前建立、尚未完成備料的項次，請優先處理。")
        typ_filter = st.radio("篩選類型", ["全部", "廠內", "委外"],
                              horizontal=True, key="tab1_type")
        data = m1 if typ_filter == "全部" else m1[m1["類型"] == typ_filter]
        st.dataframe(_fmt(data.sort_values("建立日期")), use_container_width=True)

with tab2:
    if m2.empty:
        st.info("今日暫無備料完成紀錄。")
    else:
        st.dataframe(_fmt(m2), use_container_width=True)

with tab3:
    if m3.empty:
        st.info("今日暫無新增備料項次。")
    else:
        typ_filter2 = st.radio("篩選類型", ["全部", "廠內", "委外"],
                               horizontal=True, key="tab3_type")
        data3 = m3 if typ_filter2 == "全部" else m3[m3["類型"] == typ_filter2]
        st.dataframe(_fmt(data3), use_container_width=True)

with tab4:
    st.dataframe(
        _fmt(df.sort_values("建立日期", ascending=False)),
        use_container_width=True,
    )

# ─── 下載 ────────────────────────────────────────────────────────────────────

st.divider()


def _to_excel(src: pd.DataFrame, sheet: str) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        src.to_excel(w, index=False, sheet_name=sheet)
    return buf.getvalue()


dc1, dc2, dc3, _ = st.columns([1, 1, 1, 2])

with dc1:
    st.download_button(
        label="⬇️ 今日積壓待備料",
        data=_to_excel(m1.sort_values("建立日期"), "積壓待備料"),
        file_name=f"積壓待備料_{sel}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )
with dc2:
    st.download_button(
        label="⬇️ 今日備料報表",
        data=_to_excel(
            pd.concat([m2, m3]).drop_duplicates().sort_values("建立日期", ascending=False),
            "每日備料",
        ),
        file_name=f"每日備料筆數_{sel}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )
with dc3:
    st.download_button(
        label="⬇️ 完整明細",
        data=_to_excel(df.sort_values("建立日期", ascending=False), "完整明細"),
        file_name=f"備料完整明細_{sel}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )
