import streamlit as st
import pandas as pd
import io
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from utils.shared import inject_css, render_header, render_sidebar

st.set_page_config(page_title="每月成本計算表", page_icon="📊", layout="wide")
inject_css()
render_header(title="每月成本計算表", subtitle="Monthly Cost Analysis", badge="生管 PC")
render_sidebar()

st.markdown("### 上傳報表")
st.caption("請從鼎新 ERP 匯出以下四張報表（同一月份），再上傳進行分析。")

col1, col2 = st.columns(2)
with col1:
    f_mocr27 = st.file_uploader("① 製令用料分析表 (MOCR27)", type=["xlsx", "xls"], key="mocr27")
    f_mocr41 = st.file_uploader("② 製令領料成本明細表 (MOCR41)", type=["xlsx", "xls"], key="mocr41")
with col2:
    f_mocr13 = st.file_uploader("③ 生產入庫明細表 (MOCR13)", type=["xlsx", "xls"], key="mocr13")
    f_mocr12 = st.file_uploader("④ 退料單明細表 (MOCR12)", type=["xlsx", "xls"], key="mocr12")

if st.button("開始計算", type="primary", disabled=not (f_mocr27 and f_mocr41)):
    with st.spinner("計算中..."):
        mo_mat  = pd.read_excel(io.BytesIO(f_mocr27.read()))
        mo_cost = pd.read_excel(io.BytesIO(f_mocr41.read()))
        wh_in   = pd.read_excel(io.BytesIO(f_mocr13.read())) if f_mocr13 else pd.DataFrame()
        ret     = pd.read_excel(io.BytesIO(f_mocr12.read())) if f_mocr12 else pd.DataFrame()

        # 單位成本對照（以材料品號取最新一筆）
        cost_by_mat = (
            mo_cost.sort_values("確認日期", ascending=False)
            .drop_duplicates(subset=["材料品號"])[["材料品號", "單位成本"]]
        )

        # 損耗明細
        loss = mo_mat[["製令編號","產品品號","品    名","實際完工期","實際產量",
                        "材料品號","品    名.1","單位.1",
                        "標準用量","實際用量","用量差異","差異比率%"]].copy()
        loss.columns = ["製令編號","產品品號","產品名稱","完工日期","實際產量",
                        "材料品號","材料名稱","單位",
                        "標準用量","實際用量","損耗數量","損耗率%"]
        loss_over = loss[loss["損耗數量"] > 0].copy()
        loss_over = loss_over.merge(cost_by_mat, on="材料品號", how="left")
        loss_over["損耗金額"] = loss_over["損耗數量"] * loss_over["單位成本"]

        # 領料總成本
        issued_total = mo_cost.groupby("製令編號")["領用成本"].sum().reset_index()
        issued_total.columns = ["製令編號", "領料總成本"]

        # 工單彙總
        wo_sum = (
            loss_over.groupby(["製令編號","產品品號","產品名稱","完工日期","實際產量"])
            .agg(超耗材料筆數=("材料品號","count"),
                 損耗數量合計=("損耗數量","sum"),
                 損耗金額合計=("損耗金額","sum"))
            .reset_index()
        )
        wo_sum = wo_sum.merge(issued_total, on="製令編號", how="left")
        wo_sum["損耗率(金額%)"] = (wo_sum["損耗金額合計"] / wo_sum["領料總成本"] * 100).round(2)
        wo_sum = wo_sum.sort_values("損耗金額合計", ascending=False)

        # 材料排行
        mat_sum = (
            loss_over.groupby(["材料品號","材料名稱","單位"])
            .agg(影響工單數=("製令編號", pd.Series.nunique),
                 損耗數量合計=("損耗數量","sum"),
                 損耗金額合計=("損耗金額","sum"))
            .reset_index()
            .sort_values("損耗金額合計", ascending=False)
        )

        # 整體摘要
        total_issued   = mo_cost["領用成本"].sum()
        total_loss_amt = loss_over["損耗金額"].sum()
        total_loss_qty = loss_over["損耗數量"].sum()

    # ── 摘要指標 ──────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### 摘要")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("領料總成本", f"{total_issued:,.0f}")
    m2.metric("損耗金額合計", f"{total_loss_amt:,.0f}")
    m3.metric("整體損耗率", f"{total_loss_amt/total_issued*100:.2f}%" if total_issued else "N/A")
    m4.metric("有損耗工單數", f"{loss_over['製令編號'].nunique():,}")

    # ── 工單損耗彙總 ──────────────────────────────────────────
    st.markdown("### 工單損耗彙總")
    st.dataframe(wo_sum, use_container_width=True, height=320)

    # ── 材料損耗排行 ──────────────────────────────────────────
    st.markdown("### 材料損耗排行（Top 20）")
    st.dataframe(mat_sum.head(20), use_container_width=True)

    # ── 下載 ──────────────────────────────────────────────────
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        loss_over.to_excel(writer, sheet_name="超耗明細", index=False)
        wo_sum.to_excel(writer, sheet_name="工單損耗彙總", index=False)
        mat_sum.to_excel(writer, sheet_name="材料損耗排行", index=False)
        if not ret.empty:
            ret.to_excel(writer, sheet_name="退料明細", index=False)
    buf.seek(0)
    st.download_button(
        label="下載完整分析結果 (.xlsx)",
        data=buf,
        file_name="每月成本計算表.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary"
    )

elif not (f_mocr27 and f_mocr41):
    st.info("請至少上傳 ① 製令用料分析表 和 ② 製令領料成本明細表 才能開始計算。")
