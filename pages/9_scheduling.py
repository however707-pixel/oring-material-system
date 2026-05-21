import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import date, timedelta
import io, math, sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from utils.shared import inject_css, render_header, render_sidebar

st.set_page_config(page_title="排程系統", page_icon="🗓", layout="wide")
inject_css()
render_header(title="排程系統", subtitle="Production Scheduling System", badge="生管 PC")
render_sidebar()

STAGE_ORDER  = ["組裝", "測試", "包裝", "委外"]
COLOR_STAGE  = {"組裝":"#1d4ed8","測試":"#7c3aed","包裝":"#0891b2","委外":"#d97706"}
COLOR_STATUS = {"生產中":"#16a34a","待開工":"#f59e0b","已完工":"#94a3b8"}

# ═══════════════════════════════════════════════════════════════════════════════
# ERP 生產進度表 → 排程格式 轉換函數
# ═══════════════════════════════════════════════════════════════════════════════
def parse_erp(file_bytes):
    raw = pd.read_excel(io.BytesIO(file_bytes))
    raw.columns = raw.columns.str.strip()

    # 狀態對應
    status_map = {"已完工":"已完工","生產中":"生產中","已生產":"生產中",
                  "已發料":"生產中","未完工":"待開工","已領料":"待開工"}
    raw["狀態"] = raw["製令狀態"].map(status_map).fillna("待開工")

    # 廠內 / 委外
    raw["類型"] = raw["廠商名稱"].apply(lambda x: "委外" if pd.notna(x) and str(x).strip() else "廠內")

    # 工序
    def get_stage(row):
        if row["類型"] == "委外":
            return "委外"
        line = str(row.get("生產線別名稱",""))
        if "包裝" in line:
            return "包裝"
        return "組裝"
    raw["工序"] = raw.apply(get_stage, axis=1)

    # 產線（委外用廠商名稱，廠內用生產線別名稱）
    raw["產線"] = raw.apply(
        lambda r: str(r["廠商名稱"]).strip() if r["類型"]=="委外" and pd.notna(r["廠商名稱"])
                  else str(r.get("生產線別名稱","")).strip(), axis=1
    )
    raw["產線"] = raw["產線"].replace({"nan":"未指定","":"未指定"})

    # 日期
    raw["開工"] = pd.to_datetime(raw["開 工 日"], errors="coerce").dt.date
    raw["完工"] = pd.to_datetime(raw["完 工 日"], errors="coerce").dt.date

    # 品名（截短）
    raw["產品"] = raw["品          名"].astype(str).str.strip().str[:40]

    df = raw[["製令編號","產品","產品品號","類型","工序","產線","預計產量",
              "已生產量","未生產量","開工","完工","狀態"]].copy()
    df = df.rename(columns={"製令編號":"工單號","預計產量":"數量"})
    df["數量"]    = pd.to_numeric(df["數量"],    errors="coerce").fillna(0)
    df["已生產量"] = pd.to_numeric(df["已生產量"], errors="coerce").fillna(0)
    df["未生產量"] = pd.to_numeric(df["未生產量"], errors="coerce").fillna(0)
    df["UPH"]     = 10
    df["優先順序"] = 99
    df["出貨日"]   = pd.NaT
    df = df.dropna(subset=["開工","完工"])
    df = df[df["開工"] <= df["完工"]]
    df = df.sort_values("開工").reset_index(drop=True)
    return df

# ═══════════════════════════════════════════════════════════════════════════════
# 上傳 / 示意資料
# ═══════════════════════════════════════════════════════════════════════════════
st.markdown("---")
up_col, _ = st.columns([2, 3])
with up_col:
    upload = st.file_uploader("上傳 ERP 生產進度表 (.xlsx)", type=["xlsx"], key="sched_upload")

REQUIRED_COLS = {"工單號","產品","類型","工序","產線","數量","UPH","開工","完工","出貨日","狀態","優先順序","已生產量","未生產量"}

if upload:
    with st.spinner("讀取中..."):
        st.session_state.wo_data = parse_erp(upload.read())
    st.success(f"已載入 {len(st.session_state.wo_data):,} 筆工單")

if "wo_data" not in st.session_state or not REQUIRED_COLS.issubset(st.session_state.wo_data.columns):
    st.session_state.wo_data = pd.DataFrame([
        dict(工單號="5220-20260501001",產品="IGS-9122GP",產品品號="9-xxx",類型="廠內",工序="組裝",產線="組-1線",數量=100,已生產量=60,未生產量=40,UPH=12,開工=date(2026,5,1),完工=date(2026,5,4),出貨日=date(2026,5,10),狀態="生產中",優先順序=1),
        dict(工單號="5220-20260501001",產品="IGS-9122GP",產品品號="9-xxx",類型="廠內",工序="測試",產線="測試站A",數量=100,已生產量=0,未生產量=100,UPH=20,開工=date(2026,5,5),完工=date(2026,5,6),出貨日=date(2026,5,10),狀態="待開工",優先順序=1),
        dict(工單號="5220-20260501001",產品="IGS-9122GP",產品品號="9-xxx",類型="廠內",工序="包裝",產線="包裝線",數量=100,已生產量=0,未生產量=100,UPH=30,開工=date(2026,5,7),完工=date(2026,5,8),出貨日=date(2026,5,10),狀態="待開工",優先順序=1),
        dict(工單號="MO02-20260501001",產品="機殼-A型",產品品號="1511-xxx",類型="委外",工序="委外",產線="唐佑",數量=500,已生產量=200,未生產量=300,UPH=50,開工=date(2026,5,1),完工=date(2026,5,10),出貨日=date(2026,5,12),狀態="生產中",優先順序=2),
    ])

df = st.session_state.wo_data.copy()
df["開工_dt"] = pd.to_datetime(df["開工"])
df["完工_dt"] = pd.to_datetime(df["完工"])

# ── 篩選列 ──────────────────────────────────────────────────────────────────
fc1, fc2, fc3, fc4 = st.columns([3, 2, 2, 2])
with fc1:
    min_d = df["開工_dt"].min().date() if not df.empty else date(2026,1,1)
    max_d = df["完工_dt"].max().date() if not df.empty else date(2026,12,31)
    dr = st.date_input("日期區間", value=(min_d, max_d))
with fc2:
    sel_type  = st.selectbox("類型", ["全部","廠內","委外"])
with fc3:
    sel_stage = st.selectbox("工序", ["全部","組裝","測試","包裝","委外"])
with fc4:
    sel_state = st.selectbox("狀態", ["全部","待開工","生產中","已完工"])

dff = df.copy()
if isinstance(dr,(list,tuple)) and len(dr)==2:
    dff = dff[(dff["開工_dt"]>=pd.to_datetime(dr[0])) & (dff["完工_dt"]<=pd.to_datetime(dr[1]))]
if sel_type  != "全部": dff = dff[dff["類型"]==sel_type]
if sel_stage != "全部": dff = dff[dff["工序"]==sel_stage]
if sel_state != "全部": dff = dff[dff["狀態"]==sel_state]

# ── KPI ──────────────────────────────────────────────────────────────────────
m1,m2,m3,m4,m5 = st.columns(5)
m1.metric("工單數",    dff["工單號"].nunique())
m2.metric("廠內",      dff[dff["類型"]=="廠內"]["工單號"].nunique())
m3.metric("委外",      dff[dff["類型"]=="委外"]["工單號"].nunique())
m4.metric("生產中工序", len(dff[dff["狀態"]=="生產中"]))
m5.metric("待開工工序", len(dff[dff["狀態"]=="待開工"]))
st.markdown("---")

# ═══════════════════════════════════════════════════════════════════════════════
tab1, tab2, tab3, tab4 = st.tabs(["📅 甘特圖","📊 產線稼動率","🔢 優先序管理","🧮 預計完工試算"])

# ── Tab1 甘特圖 ──────────────────────────────────────────────────────────────
with tab1:
    if dff.empty:
        st.warning("目前篩選條件下無資料。")
    else:
        MAX_GANTT = 200
        gantt_df = dff.sort_values("開工_dt").head(MAX_GANTT)
        if len(dff) > MAX_GANTT:
            st.info(f"工單數較多，甘特圖顯示前 {MAX_GANTT} 筆（依開工日排序）。")

        c_l, c_r = st.columns([3,1])
        with c_r:
            y_axis   = st.radio("Y 軸",["產線","工序"], horizontal=True)
            color_by = st.radio("顏色",["工序","狀態"], horizontal=True)

        cmap = COLOR_STAGE if color_by=="工序" else COLOR_STATUS
        fig = px.timeline(
            gantt_df, x_start="開工_dt", x_end="完工_dt",
            y=y_axis, color=color_by, color_discrete_map=cmap,
            text="工單號",
            hover_data={"產品":True,"類型":True,"工序":True,"數量":True,"狀態":True},
            category_orders={"工序":STAGE_ORDER},
        )
        fig.update_traces(textposition="inside", insidetextanchor="middle",
                          textfont=dict(size=9, color="white"))
        fig.update_layout(
            height=max(400, len(gantt_df[y_axis].unique())*30),
            margin=dict(l=10,r=10,t=30,b=10),
            paper_bgcolor="white", plot_bgcolor="#f8fafc",
            yaxis=dict(autorange="reversed",gridcolor="#e2e8f0"),
            xaxis=dict(gridcolor="#e2e8f0"),
            legend=dict(orientation="h",yanchor="bottom",y=1.02,x=1,xanchor="right"),
        )
        today_str = date.today().isoformat()
        fig.add_shape(type="line",x0=today_str,x1=today_str,y0=0,y1=1,yref="paper",
                      line=dict(color="#ef4444",width=2,dash="dash"))
        fig.add_annotation(x=today_str,y=1,yref="paper",text="今天",
                           showarrow=False,font=dict(color="#ef4444",size=12),
                           xanchor="left",yanchor="bottom")
        with c_l:
            st.plotly_chart(fig, use_container_width=True)

# ── Tab2 稼動率 ──────────────────────────────────────────────────────────────
with tab2:
    c1,c2 = st.columns([1,3])
    with c1:
        daily_hours = st.number_input("每日可用工時（hr）",1,24,8)
        work_days   = max((dr[1]-dr[0]).days+1,1) if isinstance(dr,(list,tuple)) and len(dr)==2 else 20
        st.metric("區間天數",   f"{work_days} 天")
        st.metric("每線可用工時",f"{daily_hours*work_days} hr")
    with c2:
        active = dff[dff["狀態"]!="已完工"].copy()
        if active.empty:
            st.info("無進行中/待開工工序。")
        else:
            active["計畫工時"] = (active["數量"]/active["UPH"]).round(1)
            load = active.groupby(["產線","工序"])["計畫工時"].sum().reset_index()
            lt   = active.groupby("產線")["計畫工時"].sum().reset_index()
            avail = daily_hours * work_days
            lt["稼動率%"] = (lt["計畫工時"]/avail*100).round(1)
            fig2 = px.bar(load,x="產線",y="計畫工時",color="工序",
                          color_discrete_map=COLOR_STAGE,barmode="stack")
            fig2.add_hline(y=avail,line_dash="dash",line_color="#ef4444")
            fig2.update_layout(height=300,margin=dict(l=10,r=10,t=20,b=10),
                               paper_bgcolor="white",plot_bgcolor="#f8fafc",
                               yaxis=dict(gridcolor="#e2e8f0"),
                               legend=dict(orientation="h",yanchor="bottom",y=1.02))
            st.plotly_chart(fig2,use_container_width=True)
            def cr(v):
                if v>=90: return "background-color:#fee2e2;color:#dc2626;font-weight:bold"
                if v>=70: return "background-color:#fef9c3;color:#92400e"
                return "background-color:#dcfce7;color:#15803d"
            st.dataframe(lt.style.map(cr,subset=["稼動率%"]),use_container_width=True,hide_index=True)

# ── Tab3 優先序管理 ──────────────────────────────────────────────────────────
with tab3:
    st.caption("可直接修改優先順序數字（越小越優先），按「套用」後甘特圖同步更新。")
    _want = ["工單號","產品","類型","數量","已生產量","未生產量","狀態","優先順序"]
    _have = [c for c in _want if c in dff.columns]
    wo_view = (dff[dff["狀態"]!="已完工"]
               .drop_duplicates(subset=["工單號"])
               [_have]
               .sort_values("優先順序")
               .copy())
    edited = st.data_editor(
        wo_view,
        column_config={
            "優先順序": st.column_config.NumberColumn("優先順序",min_value=1,max_value=999,step=1),
            **{c: st.column_config.TextColumn(disabled=True) for c in ["工單號","產品","類型","狀態"] if c in _have},
            **{c: st.column_config.NumberColumn(disabled=True) for c in ["數量","已生產量","未生產量"] if c in _have},
        },
        hide_index=True,use_container_width=True,key="priority_editor"
    )
    if st.button("套用排序",type="primary"):
        for _,row in edited.iterrows():
            st.session_state.wo_data.loc[st.session_state.wo_data["工單號"]==row["工單號"],"優先順序"] = row["優先順序"]
        st.success("排序已更新！")
        st.rerun()

    st.markdown("**依開工日排序 — 完整工序清單**")
    show_cols = ["工單號","產品","類型","工序","產線","數量","已生產量","未生產量","開工","完工","出貨日","狀態"]
    show_cols = [c for c in show_cols if c in dff.columns]
    sorted_df = dff.sort_values("開工_dt")[show_cols]
    def st_type(v): return "background-color:#eff6ff" if v=="廠內" else "background-color:#fffbeb"
    def st_stage(v):
        c={"組裝":"#dbeafe","測試":"#ede9fe","包裝":"#cffafe","委外":"#fef3c7"}.get(v,"")
        return f"background-color:{c}" if c else ""
    st.dataframe(sorted_df.style.map(st_type,subset=["類型"]).map(st_stage,subset=["工序"]),
                 use_container_width=True,hide_index=True)

# ── Tab4 預計完工試算 ─────────────────────────────────────────────────────────
with tab4:
    st.caption("依 數量 ÷ UPH 推算所需工時，自動計算試算完工日並標示是否延遲。")
    c1,c2 = st.columns([1,3])
    with c1:
        daily_h    = st.number_input("每日工作小時",1,24,8,key="calc_h")
        skip_wkend = st.checkbox("跳過週六日",value=True)

    def add_wd(start,hrs,dh,skip):
        rem = hrs; cur = pd.Timestamp(start)
        while rem > 0:
            cur += timedelta(days=1)
            if skip and cur.weekday()>=5: continue
            rem -= dh
        return cur.date()

    pending = dff[dff["狀態"]!="已完工"].copy()
    if pending.empty:
        st.info("無待開工/生產中工序。")
    else:
        rows=[]
        for _,r in pending.iterrows():
            hrs = r["數量"]/max(r["UPH"],1)
            est = add_wd(r["開工"],hrs,daily_h,skip_wkend)
            diff= (pd.Timestamp(est)-pd.Timestamp(r["完工"])).days
            rows.append({"工單號":r["工單號"],"產品":r["產品"],"類型":r["類型"],
                         "工序":r["工序"],"數量":r["數量"],"UPH":r["UPH"],
                         "計畫工時(hr)":round(hrs,1),
                         "計畫完工":r["完工"],"試算完工":est,"差異(天)":diff})
        calc_df = pd.DataFrame(rows)
        def sd(v):
            if v>0: return "background-color:#fee2e2;color:#dc2626;font-weight:bold"
            if v<0: return "background-color:#dcfce7;color:#15803d"
            return ""
        with c2:
            st.dataframe(calc_df.style.map(sd,subset=["差異(天)"]),
                         use_container_width=True,hide_index=True)
        late = calc_df[calc_df["差異(天)"]>0]
        if not late.empty:
            st.warning(f"⚠️ **{late['工單號'].nunique()}** 張工單共 **{len(late)}** 道工序預計延遲。")
        else:
            st.success("✅ 所有工序依 UPH 試算均可在計畫日內完工。")
