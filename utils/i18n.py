TEXTS = {
    "zh": {
        # Header
        "header_badge":    "Production Management System",
        "header_title":    "資材管理決策系統",
        "header_subtitle": "Material &amp; Production Decision Support &nbsp;·&nbsp; MC / PC / WH &nbsp;·&nbsp; ORing Industrial Networking",

        # Sidebar company
        "company_name":  "威力工業網絡<br>股份有限公司",
        "system_ver":    "⚙ 生產輔助決策系統 v1.0",
        "nav_title":     "部門功能導覽",
        "dept_mc":       "物管 MC",
        "dept_mc_sub":   "Material Control",
        "dept_pc":       "生管 PC",
        "dept_pc_sub":   "Production Control",
        "dept_wh":       "倉管 WH",
        "dept_wh_sub":   "Warehouse Management",
        "coming_soon":   "功能開發中，敬請期待",
        "link_transfer": "工單調撥決策看板",
        "link_outsource":"委外調撥確認",
        "link_wo_progress": "工單進度表",
        "link_shortage_detail": "區間工單缺料明細",

        # Sidebar settings
        "settings":      "⚙️ 設定",
        "upload_label":  "上傳供需表",
        "date_start":    "📅 分析起始日",
        "date_end":      "📅 分析結束日",
        "date_err":      "⚠️ 結束日不可早於起始日！",
        "date_caption":  "共",
        "date_caption2": "天",
        "mode_label":    "📦 顯示模式",
        "mode_all":      "總表（全部倉別）",
        "mode_filter":   "篩選特定缺料倉別",
        "wh_select":     "選擇缺料倉別",
        "wh_hint":       "請先上傳供需表，倉別清單將自動載入",
        "info_title":    "💡 **分析邏輯**",
        "info_body": (
            "💡 **分析邏輯**\n\n"
            "**可用量** = 區間末預計結存 − 區間內預計進貨\n\n"
            "**調撥量規則（SPQ 為最小單位）：**\n"
            "- 缺料進位到 SPQ 倍數，來源倉足夠就給\n"
            "- 來源倉不足一個 SPQ → 給實際可用量"
        ),
        "fmt_support":   "支援格式：xlsx、xls、csv（UTF-8 / CP950 / BIG5）",

        # Main results
        "matrix_title":  "📊 跨庫別缺料調撥矩陣（已扣除預計進貨）",
        "period_label":  "分析區間",
        "days_label":    "共",
        "days_unit":     "天",
        "item_label":    "缺料品號數",
        "item_unit":     "個",
        "wh_label":      "涵蓋庫別",
        "wh_unit":       "個",
        "search_ph":     "🔍 搜尋品號",
        "search_hint":   "輸入品號關鍵字，例如：1.01",
        "legend":        "**負數（紅色）** = 缺料量｜**正數（綠色）** = 可撥出量｜**0（灰色）** = 無庫存",
        "export_matrix": "⬇️ 匯出調撥矩陣（Excel）",
        "rec_title":     "💡 智慧調撥建議",
        "rec_caption":   "可用量已排除預計進貨｜調撥數量以 SPQ 為最小單位",
        "export_rec":    "⬇️ 匯出調撥建議（Excel）",
        "no_rec":        "目前暫無直接對應的調撥建議（可能全公司都缺貨，無可撥來源）。",
        "no_shortage":   "✅ 所選區間內沒有任何缺料品號，庫存狀況良好！",
        "spinner":       "分析中，請稍候...",

        # Recommendation table columns
        "col_pno":       "品號",
        "col_spq":       "SPQ",
        "col_short_wh":  "缺料庫別",
        "col_short_qty": "缺料量",
        "col_src_wh":    "建議來源倉",
        "col_src_avail": "來源倉可用量",
        "col_xfer_qty":  "建議調撥數量",
        "col_feasible":  "調撥可行性",

        # Flow board
        "board_title":   "資材作業流程看板",
        "board_sub":     "Material Operation Flow Board &nbsp;·&nbsp; Production Control System",
        "upload_hint":   "👈 &nbsp;請從左側選擇功能並上傳對應檔案，開始分析作業&nbsp;·&nbsp; 支援 <strong>xlsx / xls / csv</strong> 格式",

        # Feasibility
        "full_cover":    "✅ 完全覆蓋",
        "partial":       "⚠️ 部分供應",
        "partial_spq":   "⚠️ 部分供應（不足一個 SPQ）",

        # Format expander
        "fmt_title":     "📋 檔案格式說明",
        "fmt_body": """
**必要欄位：** `品號`、`庫別`、`庫別名稱`、`日期`、`異動別`、`異動數量`、`預計結存`、`SPQ`

**可用量計算：**
- 期初庫存從「庫存可用量」行的「庫別」欄取得
- 區間末預計結存扣除區間內預計進貨累計

**SPQ 調撥規則：**
| 情況 | 調撥數量 |
|------|----------|
| min(可用,缺料) ≥ SPQ | floor(min / SPQ) × SPQ |
| min(可用,缺料) < SPQ | 直接給 min(可用,缺料) |
| 可撥量為 0 | 無法調撥 |
""",
    },

    "en": {
        # Header
        "header_badge":    "Production Management System",
        "header_title":    "Material Management System",
        "header_subtitle": "Material &amp; Production Decision Support &nbsp;·&nbsp; MC / PC / WH &nbsp;·&nbsp; ORing Industrial Networking",

        # Sidebar company
        "company_name":  "ORing Industrial<br>Networking Co., Ltd.",
        "system_ver":    "⚙ Decision Support System v1.0",
        "nav_title":     "NAVIGATION",
        "dept_mc":       "MC Dept.",
        "dept_mc_sub":   "Material Control",
        "dept_pc":       "PC Dept.",
        "dept_pc_sub":   "Production Control",
        "dept_wh":       "WH Dept.",
        "dept_wh_sub":   "Warehouse Management",
        "coming_soon":   "Coming Soon",
        "link_transfer": "Transfer Decision Board",
        "link_outsource":"Outsource Confirmation",
        "link_wo_progress": "Work Order Progress",
        "link_shortage_detail": "Period Shortage Detail",

        # Sidebar settings
        "settings":      "⚙️ Settings",
        "upload_label":  "Upload Supply/Demand File",
        "date_start":    "📅 Start Date",
        "date_end":      "📅 End Date",
        "date_err":      "⚠️ End date must not be earlier than start date!",
        "date_caption":  "Total",
        "date_caption2": "days",
        "mode_label":    "📦 Display Mode",
        "mode_all":      "All Warehouses",
        "mode_filter":   "Filter by Shortage Warehouse",
        "wh_select":     "Select Warehouse",
        "wh_hint":       "Upload a file first to load the warehouse list",
        "info_body": (
            "💡 **Analysis Logic**\n\n"
            "**Available Qty** = End-of-period balance − Planned receipts\n\n"
            "**Transfer Rules (SPQ as minimum unit):**\n"
            "- Round shortage up to SPQ multiple; transfer if source has enough\n"
            "- If source < 1 SPQ → transfer actual available qty"
        ),
        "fmt_support":   "Supported: xlsx, xls, csv (UTF-8 / CP950 / BIG5)",

        # Main results
        "matrix_title":  "📊 Cross-Warehouse Shortage Transfer Matrix (Net of Planned Receipts)",
        "period_label":  "Period",
        "days_label":    "Total",
        "days_unit":     "days",
        "item_label":    "Shortage Items",
        "item_unit":     "",
        "wh_label":      "Warehouses",
        "wh_unit":       "",
        "search_ph":     "🔍 Search Part No.",
        "search_hint":   "Enter part number keyword",
        "legend":        "**Negative (Red)** = Shortage qty｜**Positive (Green)** = Available to transfer｜**0 (Grey)** = No stock",
        "export_matrix": "⬇️ Export Transfer Matrix (Excel)",
        "rec_title":     "💡 Smart Transfer Recommendations",
        "rec_caption":   "Available qty excludes planned receipts｜Transfer qty in SPQ multiples",
        "export_rec":    "⬇️ Export Recommendations (Excel)",
        "no_rec":        "No transfer recommendations available (possible company-wide shortage).",
        "no_shortage":   "✅ No shortage items found in the selected period. Inventory is healthy!",
        "spinner":       "Analyzing, please wait...",

        # Recommendation table columns
        "col_pno":       "Part No.",
        "col_spq":       "SPQ",
        "col_short_wh":  "Shortage WH",
        "col_short_qty": "Shortage Qty",
        "col_src_wh":    "Source WH",
        "col_src_avail": "Source Available",
        "col_xfer_qty":  "Transfer Qty",
        "col_feasible":  "Feasibility",

        # Flow board
        "board_title":   "Material Operation Flow Board",
        "board_sub":     "資材作業流程看板 &nbsp;·&nbsp; Production Control System",
        "upload_hint":   "👈 &nbsp;Select a function from the left and upload a file to begin analysis&nbsp;·&nbsp; Supported: <strong>xlsx / xls / csv</strong>",

        # Feasibility
        "full_cover":    "✅ Fully Covered",
        "partial":       "⚠️ Partially Supplied",
        "partial_spq":   "⚠️ Partially Supplied (< 1 SPQ)",

        # Format expander
        "fmt_title":     "📋 File Format Guide",
        "fmt_body": """
**Required Columns:** `品號`, `庫別`, `庫別名稱`, `日期`, `異動別`, `異動數量`, `預計結存`, `SPQ`

**Available Qty Calculation:**
- Opening stock from the '庫存可用量' row in the '庫別' column
- End-of-period balance minus planned receipts within the period

**SPQ Transfer Rules:**
| Condition | Transfer Qty |
|-----------|--------------|
| min(avail, shortage) ≥ SPQ | floor(min / SPQ) × SPQ |
| min(avail, shortage) < SPQ | transfer actual min |
| Available = 0 | No transfer possible |
""",
    },
}


def t(key: str) -> str:
    import streamlit as st
    lang = st.session_state.get("lang", "zh")
    return TEXTS[lang].get(key, TEXTS["zh"].get(key, key))
