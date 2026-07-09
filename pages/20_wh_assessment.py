import io
import json
import sys
import os
from calendar import monthrange
from datetime import date, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from db import queries as wh_db

st.set_page_config(page_title="年度倉儲考核依據表", page_icon="📋",
                    layout="wide", initial_sidebar_state="collapsed")

# ══════════════════════════════════════════════════════
# 設計系統（沿用「倉儲備料看板」深色 · 午夜藍 × 香檳金）
# ══════════════════════════════════════════════════════
st.markdown("""
<style>
:root{
  --gold:#D9B36A; --green:#43C08F; --red:#EC6A7C; --amber:#E5B454; --blue:#5AA8F0;
}
.stApp{ color:#EAF1F8 !important; background:
   radial-gradient(1100px 540px at 100% -10%, #1A2A38 0%, rgba(26,42,56,0) 55%),
   radial-gradient(950px 480px at -8% 0%, #15222E 0%, rgba(21,34,46,0) 50%),
   #0C141D !important; }
[data-testid="stHeader"]{ background:transparent !important; }
.block-container{ padding:0.6rem 1.7rem 2.4rem !important; max-width:1720px !important; }
#MainMenu, footer, [data-testid="stToolbar"]{ visibility:hidden; }
[data-testid="stSidebar"], [data-testid="collapsedControl"]{ display:none !important; }
html, body, [class*="css"]{
  font-family:"微軟正黑體","Microsoft JhengHei","Noto Sans TC",Arial,sans-serif !important;
}
p{ color:#EAF1F8 !important; margin:0; } label{ color:#9DB0C0 !important; }
[data-testid="stVerticalBlock"]{ gap:.55rem; }
.stTabs [data-baseweb="tab-list"]{ gap:6px; }
.stTabs [data-baseweb="tab"]{
  background:#26394D; border:1px solid #46607A; border-radius:10px 10px 0 0;
  color:#D7E1EA !important; padding:8px 18px; font-weight:700;
}
.stTabs [aria-selected="true"]{
  background:linear-gradient(160deg,#35506A,#2A3F54) !important; border-bottom:3px solid #D9B36A !important;
  color:#EAF1F8 !important;
}
div[data-testid="stDownloadButton"] > button{
  background:linear-gradient(180deg,#D4B069,#C9A45C) !important; border:none !important;
  color:#1A1206 !important; font-size:14px !important; font-weight:800 !important;
  border-radius:11px !important; padding:11px 18px !important;
  box-shadow:0 4px 16px rgba(201,164,92,.35) !important;
}
</style>
""", unsafe_allow_html=True)

TODAY = date.today()
# 考核統計截止日＝前一日：今日資料仍在進行中，不列入計算，避免平均與評級失真
CUTOFF = TODAY - timedelta(days=1)

st.markdown(
    '<div style="margin-bottom:8px">'
    '<a href="/wh_dashboard" target="_self" style="color:#D9B36A;text-decoration:none;'
    'font-size:13px;font-weight:600;opacity:0.85">← 返回倉儲備料看板</a></div>',
    unsafe_allow_html=True
)

st.markdown(
    f'<div style="background:linear-gradient(110deg,#13202C 0%,#22344A 50%,#13202C 100%);'
    f'border:1px solid #56718B;border-radius:18px;padding:20px 30px;margin-bottom:14px;'
    f'box-shadow:0 10px 34px rgba(0,0,0,.40)">'
    f'<div style="color:#D9B36A;font-size:13px;font-weight:700;letter-spacing:2px">ORing &nbsp;·&nbsp; 倉管 WD</div>'
    f'<div style="color:#ffffff;font-size:30px;font-weight:900;letter-spacing:1px;margin-top:4px">'
    f'📋 年度倉儲考核依據表</div>'
    f'<div style="color:#9fb0c0;font-size:13px;margin-top:6px">'
    f'資料來源：倉儲備料看板 &nbsp;｜&nbsp; 依 2026 年 7 月起「倉庫團隊每日作業考核標準」計算</div>'
    f'</div>',
    unsafe_allow_html=True
)

# ══════════════════════════════════════════════════════
# 資料載入
# ══════════════════════════════════════════════════════
db_ready = wh_db.db_exists()
if not db_ready:
    st.error("⚠️ NAS 離線或尚未建立資料庫，請先於「倉儲備料看板」頁面上傳「調件備料統計表.xlsx」。")
    st.stop()

src_mtime = wh_db.db_mtime()


@st.cache_data(ttl=5 * 60, show_spinner=False)
def load_wh(_mtime_key):
    return wh_db.load_wh()


with st.spinner("載入資料中…"):
    diao, _inbound = load_wh(str(src_mtime))

# ══════════════════════════════════════════════════════
# 考核標準設定（2026 年 7 月起實施）
# ══════════════════════════════════════════════════════
TEAM_TARGET = 250  # 全倉每日總備料筆數最低標準（採每週平均值統計）

MAIN_STAFF = ["林麗婷", "鄭雅萍", "羅恆崇", "張揚晃"]   # 倉庫主力作業人員
PART_STAFF = ["鍾志伶", "劉嘉怡", "陳冠芩", "賴仕杰"]    # 兼任其他專職工作

GRADE_RULE = {}
for _n in MAIN_STAFF:
    GRADE_RULE[_n] = {"group": "主力作業人員", "b_lo": 50, "a_th": 60, "c_lo": 30}
for _n in PART_STAFF:
    GRADE_RULE[_n] = {"group": "兼任人員", "b_lo": 15, "a_th": 21, "c_lo": 10}
ALL_STAFF = MAIN_STAFF + PART_STAFF

GRADE_COLOR = {
    "A 優異": "#43C08F", "B 達標": "#E5B454",
    "C 待加強": "#E58554", "D 未達標": "#EC6A7C",
    "未達標": "#EC6A7C",
}


def _grade(name, v):
    rule = GRADE_RULE.get(name)
    if rule is None:
        return "—", "#8094A6"
    if v >= rule["a_th"]:
        return "A 優異", GRADE_COLOR["A 優異"]
    elif v >= rule["b_lo"]:
        return "B 達標", GRADE_COLOR["B 達標"]
    elif v >= rule["c_lo"]:
        return "C 待加強", GRADE_COLOR["C 待加強"]
    else:
        return "D 未達標", GRADE_COLOR["D 未達標"]


def _team_grade(v):
    return ("達標", GRADE_COLOR["B 達標"]) if v >= TEAM_TARGET else ("未達標", GRADE_COLOR["未達標"])


with st.expander("📐 考核標準說明（點擊展開）", expanded=False):
    st.markdown(f"""
- **團隊基本低標**：全倉每日總備料筆數 ≥ **{TEAM_TARGET} 筆**（採每週平均值統計）
- **主力作業人員**（{"、".join(MAIN_STAFF)}）：A 級 60 筆以上/日、B 級 50 至 60 筆/日、C 級 30 至 49 筆/日、D 級 29 筆以下/日（備料＋入庫合計）
- **兼任人員**（{"、".join(PART_STAFF)}，扣除本身兼任之其他專職工作）：A 級 21 至 40 筆/日、B 級 15 至 20 筆/日、C 級 10 至 14 筆/日、D 級 9 筆以下/日（備料＋入庫合計）
- 「入庫」筆數採本看板「上架完成」（調撥單狀態＝上架）計算；若貴公司「入庫」實際對應「入庫單據」表的入庫人員紀錄，煩請告知以便調整計算來源。
""")

# ══════════════════════════════════════════════════════
# 個人每日「備料＋上架(入庫)」合計筆數
# ══════════════════════════════════════════════════════


def _split_names(raw):
    """拆解「張揚晃/婉兒」等複合欄位，並去除上架紀錄常見的句點後綴（如「林麗婷.」）。"""
    if pd.isna(raw):
        return []
    raw = str(raw).strip()
    if not raw:
        return []
    return [p.strip().rstrip(".").strip() for p in raw.split("/") if p.strip()]


def _explode(df, staff_col, qty_col):
    rows = []
    for d, staff_raw, qty in zip(df["完成日"], df[staff_col], df[qty_col]):
        names = _split_names(staff_raw)
        if not names or pd.isna(qty) or qty == 0:
            continue
        share = float(qty) / len(names)
        dd = d.date() if hasattr(d, "date") else d
        for n in names:
            rows.append({"date": dd, "staff": n, "qty": share})
    return pd.DataFrame(rows, columns=["date", "staff", "qty"])


_prep_rows = diao[(diao["狀態"] == "已完成") & diao["完成日"].notna()]
_putaway_rows = diao[diao["狀態"].isin(["上架", "上架W"]) & diao["完成日"].notna()]

_prep_ex = _explode(_prep_rows, "備料人員", "需求筆數")
_putaway_ex = _explode(_putaway_rows, "備料人員", "完成筆數")

person_daily = (
    pd.concat([_prep_ex, _putaway_ex], ignore_index=True)
    .groupby(["date", "staff"], as_index=False)["qty"].sum()
)

# 全倉備料（僅備料，不含上架）每日合計 —— 對應團隊 250 筆基本低標
team_daily_prep = _prep_rows.groupby(_prep_rows["完成日"].dt.date)["需求筆數"].sum()


def _person_range_value(name, s, e):
    if s > e or person_daily.empty:
        return 0.0
    m = (person_daily["staff"] == name) & (person_daily["date"] >= s) & (person_daily["date"] <= e)
    return float(person_daily.loc[m, "qty"].sum())


def _team_range_value(s, e):
    if s > e:
        return 0
    m = (team_daily_prep.index >= s) & (team_daily_prep.index <= e)
    return int(team_daily_prep[m].sum())


def _workdays(d0, d1):
    if d0 > d1:
        return 0
    n = 0
    d = d0
    while d <= d1:
        if d.weekday() < 5:
            n += 1
        d += timedelta(days=1)
    return n


# ══════════════════════════════════════════════════════
# 人工備註／考核結果覆寫 —— 依「期間」記錄：
#   daily=某一天、weekly=某一週、monthly=某一月。
#   手動改分只影響該期間；新的期間自動回到依筆數計算。
# ══════════════════════════════════════════════════════
OVERRIDE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "data", "assessment_overrides.json"
)
GRADE_OPTIONS = ["A 優異", "B 達標", "C 待加強", "D 未達標", "達標", "未達標"]
GRADE_BY_LETTER = {"A": "A 優異", "B": "B 達標", "C": "C 待加強", "D": "D 未達標",
                   "達標": "達標", "未達": "未達標"}
TEAM_KEY = "__team__"
_SCOPE_LABEL = {"daily": "今日", "weekly": "本週", "monthly": "本月"}
_OLD_TAB_SCOPE = {"本週每日": "daily", "近5週含本週": "weekly", "本年每月": "monthly"}


def _load_overrides():
    try:
        with open(OVERRIDE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {}
    # 舊格式（依分頁整表存）→ 新格式（依期間存）一次性轉換，歸入最近一個期間
    if any(k in data for k in _OLD_TAB_SCOPE):
        cur_key = {"daily": CUTOFF.isoformat(),
                   "weekly": (TODAY - timedelta(days=TODAY.weekday())).isoformat(),
                   "monthly": CUTOFF.strftime("%Y-%m")}
        migrated = {k: v for k, v in data.items() if k not in _OLD_TAB_SCOPE}
        for old_tab, scope in _OLD_TAB_SCOPE.items():
            for rn, entry in data.get(old_tab, {}).items():
                if "全倉" in rn:
                    continue
                person = rn.split("（")[0]
                migrated.setdefault(scope, {}).setdefault(cur_key[scope], {})[person] = entry
        data = migrated
        _save_overrides(data)
    return data


def _save_overrides(data):
    try:
        os.makedirs(os.path.dirname(OVERRIDE_PATH), exist_ok=True)
        with open(OVERRIDE_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        st.error(f"儲存失敗：{e}")
        return False


# ══════════════════════════════════════════════════════
# 共用：趨勢曲線圖（個人＝左軸，全倉合計＝右軸虛線）
# ══════════════════════════════════════════════════════
_LINE_COLORS = ["#4FA3F7", "#43C08F", "#E5B454", "#EC6A7C",
                "#9B7EF2", "#4ED0C9", "#F08BC0", "#A3B85C"]


def _render_trend_chart(period_labels, row_values, row_meta, file_tag):
    x = [l.replace("\n", "<br>") for l in period_labels]
    fig = go.Figure()
    ci = 0
    team_y = None
    for vals, (kind, name) in zip(row_values, row_meta):
        # 0 筆（如尚無資料）以 None 斷開，避免曲線掉到 0 造成誤判
        y = [round(v) if v else None for v in vals]
        if kind == "team":
            team_y = y
            continue
        fig.add_trace(go.Scatter(
            x=x, y=y, mode="lines+markers", name=name,
            line=dict(color=_LINE_COLORS[ci % len(_LINE_COLORS)],
                      width=2.5, shape="spline"),
            marker=dict(size=6), connectgaps=False,
        ))
        ci += 1
    if team_y is not None:
        fig.add_trace(go.Scatter(
            x=x, y=team_y, mode="lines+markers", name="全倉合計（右軸）",
            line=dict(color="#F5C542", width=3, dash="dash", shape="spline"),
            marker=dict(size=7, symbol="diamond"),
            connectgaps=False, yaxis="y2",
        ))
    _tickfont = dict(color="#C7D3DE", size=12, family="'微軟正黑體',Arial,sans-serif")
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0,
                    font=dict(color="#C7D3DE", size=12)),
        xaxis=dict(showgrid=False, tickfont=_tickfont),
        yaxis=dict(title=dict(text="個人筆數", font=dict(color="#8094A6", size=12)),
                   showgrid=True, gridcolor="#283845",
                   tickfont=dict(color="#8094A6", size=11), zeroline=False),
        yaxis2=dict(title=dict(text="全倉合計", font=dict(color="#F5C542", size=12)),
                    overlaying="y", side="right", showgrid=False,
                    tickfont=dict(color="#F5C542", size=11), zeroline=False),
        hovermode="x unified",
        margin=dict(l=10, r=10, t=10, b=10), height=420,
    )
    st.markdown("#### 📈 趨勢曲線")
    st.plotly_chart(fig, width='stretch', key=f"chart_{file_tag}")


# ══════════════════════════════════════════════════════
# 共用：期間表格 render（可編輯備註／考核結果）
# ══════════════════════════════════════════════════════

def _render_period_table(period_labels, period_ranges, file_tag, scope, period_keys,
                         show_summary=False, show_chart=False):
    # 顯示值＝含今日的即時筆數；計算值＝截至前一日（成績、平均只看已完成日）
    workdays_calc = [_workdays(s, min(e, CUTOFF)) for s, e in period_ranges]

    row_names, row_meta, disp_rows, calc_rows = [], [], [], []
    for name in ALL_STAFF:
        disp_rows.append([_person_range_value(name, s, min(e, TODAY)) for s, e in period_ranges])
        calc_rows.append([_person_range_value(name, s, min(e, CUTOFF)) for s, e in period_ranges])
        row_names.append(f"{name}（{GRADE_RULE[name]['group']}）")
        row_meta.append(("staff", name))

    disp_rows.append([_team_range_value(s, min(e, TODAY)) for s, e in period_ranges])
    calc_rows.append([_team_range_value(s, min(e, CUTOFF)) for s, e in period_ranges])
    row_names.append("🏭 全倉備料合計（僅備料，團隊低標）")
    row_meta.append(("team", None))

    ov_scope = _load_overrides().get(scope, {})

    def _saved(pk, kind, name):
        who = name if kind == "staff" else TEAM_KEY
        return ov_scope.get(pk, {}).get(who, {})

    # 每格「數字 (等級)」：依該期間的每日平均判定等級；0 筆（尚無資料）不標
    def _cell_tag(n, wd, kind, name):
        if n <= 0:
            return None
        avg = n / wd if wd else n
        if kind == "staff":
            g, _c = _grade(name, avg)
            return g.split()[0]          # A / B / C / D
        g, _c = _team_grade(avg)
        return "達標" if g == "達標" else "未達"

    # 逐格：數字顯示即時值；等級依「截至前一日」計算（comp），
    # 若該期間有手動覆寫（eff）則以人工等級為準並加 * 標記。
    # 今日／進行中期間：只顯示數字不評級（成績以昨日為準）
    comp_tag_rows, eff_tag_rows, display_values = [], [], []
    for disp, calc, (kind, name) in zip(disp_rows, calc_rows, row_meta):
        ctags, etags, cells = [], [], []
        for dv, cv, wd, pk in zip(disp, calc, workdays_calc, period_keys):
            nd = round(dv) if dv else 0
            nc = round(cv) if cv else 0
            ctag = _cell_tag(nc, wd, kind, name)
            g_ov = _saved(pk, kind, name).get("grade")
            if g_ov in GRADE_OPTIONS:
                etag = (g_ov.split()[0] if kind == "staff"
                        else ("達標" if g_ov == "達標" else "未達"))
                cells.append(f"{nd} ({etag}*)")
            else:
                etag = ctag
                cells.append(f"{nd} ({etag})" if etag else str(nd))
            ctags.append(ctag)
            etags.append(etag)
        comp_tag_rows.append(ctags)
        eff_tag_rows.append(etags)
        display_values.append(cells)
    df = pd.DataFrame(display_values, index=row_names, columns=period_labels)

    # 總合：各等級出現次數（含手動調整後的等級；0 筆的期間不計）
    if show_summary:
        sums = []
        for tags, (kind, _name) in zip(eff_tag_rows, row_meta):
            if kind == "staff":
                sums.append("、".join(f"{g}×{tags.count(g)}" for g in ("A", "B", "C", "D")))
            else:
                sums.append(f"達標×{tags.count('達標')}、未達×{tags.count('未達')}")
        df["總合"] = sums

    total_workdays = sum(workdays_calc)
    avgs, sys_grades = [], []
    for calc, (kind, name) in zip(calc_rows, row_meta):
        total = sum(calc)
        avg = round(total / total_workdays, 1) if total_workdays else 0.0
        avgs.append(avg)
        g, _c = _grade(name, avg) if kind == "staff" else _team_grade(avg)
        sys_grades.append(g)

    df["平均/日"] = avgs
    df["系統評定"] = sys_grades

    # 最新期間（daily=昨日、weekly=本週、monthly=本月）可手動改分／填備註；
    # 只影響該期間，之後的期間自動回到依筆數計算
    last_pk = period_keys[-1]
    last_i = len(period_keys) - 1
    scope_label = _SCOPE_LABEL[scope]
    last_label = period_labels[-1].replace("\n", " ")
    grade_col = f"{scope_label}考核（可改）"
    note_col = f"{scope_label}備註（可填）"
    cur_grades, cur_notes = [], []
    for etags, (kind, name) in zip(eff_tag_rows, row_meta):
        saved = _saved(last_pk, kind, name)
        g = saved.get("grade")
        if g not in GRADE_OPTIONS:
            t = etags[last_i]
            g = GRADE_BY_LETTER.get(t, "—") if t else "—"
        cur_grades.append(g)
        cur_notes.append(saved.get("note", ""))
    df[grade_col] = cur_grades
    df[note_col] = cur_notes

    col_config = {
        c: st.column_config.TextColumn(
            c, disabled=True,
            help="筆數 (等級)；* 為手動調整。今日／進行中期間只顯示數字，成績以昨日為準")
        for c in period_labels
    }
    if show_summary:
        col_config["總合"] = st.column_config.TextColumn(
            "總合（等級次數）", disabled=True, width="medium",
            help="各期間等級出現次數統計（含手動調整；0 筆的期間不計）")
    col_config["平均/日"] = st.column_config.NumberColumn("平均/日", format="%.1f", disabled=True)
    col_config["系統評定"] = st.column_config.TextColumn("系統評定", disabled=True,
                                                    help="整表期間的平均/日評定，僅供參考")
    col_config[grade_col] = st.column_config.SelectboxColumn(
        grade_col, options=["—"] + GRADE_OPTIONS, required=True,
        help=f"僅影響{scope_label}（{last_label}）；其他期間依筆數自動計算。改後請按下方儲存")
    col_config[note_col] = st.column_config.TextColumn(
        note_col, width="large", help=f"{scope_label}（{last_label}）的備註")

    sort_mode = st.radio(
        "排序", ["預設順序", "依等級 A→D"], horizontal=True,
        key=f"sort_{file_tag}", label_visibility="collapsed")
    if sort_mode == "依等級 A→D":
        # 依「系統評定」排序（同級再依平均/日高→低）；全倉合計固定最後一列
        rank = {"A 優異": 0, "B 達標": 1, "達標": 1,
                "C 待加強": 2, "D 未達標": 3, "未達標": 3}
        staff_order = sorted(
            row_names[:-1],
            key=lambda rn: (rank.get(str(df.loc[rn, "系統評定"]), 9),
                            -float(df.loc[rn, "平均/日"])))
        df = df.reindex(staff_order + [row_names[-1]])

    if st.session_state.pop(f"saved_flag_{file_tag}", False):
        st.success(f"✅ 已儲存{scope_label}（{last_label}）的考核與備註；"
                   f"之後的期間會自動依筆數計算。")

    edited = st.data_editor(
        df, width='stretch', height=(len(df) + 1) * 36 + 6,
        column_config=col_config,
        key=f"editor_{file_tag}_{sort_mode}",
    )

    c1, c2, c3 = st.columns([1.2, 0.9, 1])
    with c1:
        if st.button(f"💾　儲存{scope_label}考核／備註（{last_label}）",
                     key=f"save_{file_tag}", width='stretch'):
            allo = _load_overrides()
            scope_map = allo.setdefault(scope, {})
            pmap = scope_map.setdefault(last_pk, {})
            # 只存「與依筆數計算不同」的手動等級與非空備註，且只記在該期間
            for i, (rn, (kind, name)) in enumerate(zip(row_names, row_meta)):
                who = name if kind == "staff" else TEAM_KEY
                g = str(edited.loc[rn, grade_col])
                note = edited.loc[rn, note_col]
                note = "" if pd.isna(note) else str(note).strip()
                ct = comp_tag_rows[i][last_i]
                comp_full = GRADE_BY_LETTER.get(ct, "—") if ct else "—"
                entry = {}
                if g in GRADE_OPTIONS and g != comp_full:
                    entry["grade"] = g
                if note:
                    entry["note"] = note
                if entry:
                    pmap[who] = entry
                else:
                    pmap.pop(who, None)
            if not pmap:
                scope_map.pop(last_pk, None)
            if not scope_map:
                allo.pop(scope, None)
            if _save_overrides(allo):
                st.session_state[f"saved_flag_{file_tag}"] = True
                st.rerun()
    with c2:
        if st.button("↩️　清除手動調整（回復依筆數計算）",
                     key=f"reset_{file_tag}", width='stretch',
                     help="移除本表所有期間的手動等級（備註會保留）"):
            allo = _load_overrides()
            scope_map = allo.get(scope, {})
            for pk in list(scope_map):
                for who in list(scope_map[pk]):
                    scope_map[pk][who].pop("grade", None)
                    if not scope_map[pk][who].get("note"):
                        scope_map[pk].pop(who, None)
                if not scope_map[pk]:
                    scope_map.pop(pk, None)
            if not scope_map:
                allo.pop(scope, None)
            if _save_overrides(allo):
                st.rerun()
    with c3:
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as w:
            edited.to_excel(w, sheet_name="考核依據表")
        buf.seek(0)
        st.download_button(
            "⬇️　下載本表（Excel）",
            data=buf,
            file_name=f"倉儲考核_{file_tag}_{TODAY.strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key=f"dl_{file_tag}",
            width='stretch',
        )

    if show_chart:
        _render_trend_chart(period_labels, disp_rows, row_meta, file_tag)


# ══════════════════════════════════════════════════════
# Tab 1：當週每日
# ══════════════════════════════════════════════════════

def _tab_week_daily():
    wday_names = ["一", "二", "三", "四", "五"]
    mon = TODAY - timedelta(days=TODAY.weekday())
    days = [mon + timedelta(days=i) for i in range(5) if mon + timedelta(days=i) <= TODAY]
    if not days:
        st.info("本週尚未開始。")
        return
    labels = [
        f"週{wday_names[d.weekday()]}{'（今日）' if d == TODAY else ''}\n{d.strftime('%m/%d')}"
        for d in days
    ]
    ranges = [(d, d) for d in days]
    keys = [d.isoformat() for d in days]
    _render_period_table(labels, ranges, "本週每日", "daily", keys)


# ══════════════════════════════════════════════════════
# Tab 2：近5週（含本週 + 前4週，週一~週五）
# ══════════════════════════════════════════════════════

def _tab_recent5_weekly():
    this_mon = TODAY - timedelta(days=TODAY.weekday())  # 本週一
    weeks = []
    for w in range(4, -1, -1):                          # 前4週 → 本週
        wk_start = this_mon - timedelta(weeks=w)
        wk_end = wk_start + timedelta(days=4)           # 週一~週五
        wnum = wk_start.isocalendar()[1]
        weeks.append((wnum, wk_start, wk_end))
    labels = []
    for i, (wn, s, e) in enumerate(weeks):
        tag = "（本週）" if i == len(weeks) - 1 else ""
        labels.append(f"W{wn}{tag}\n{s.strftime('%m/%d')}~{e.strftime('%m/%d')}")
    ranges = [(s, e) for _wn, s, e in weeks]
    keys = [s.isoformat() for _wn, s, _e in weeks]
    _render_period_table(labels, ranges, "近5週含本週", "weekly", keys,
                         show_summary=True, show_chart=True)


# ══════════════════════════════════════════════════════
# Tab 3：當年每月
# ══════════════════════════════════════════════════════

def _tab_year_monthly():
    months = []
    for m in range(1, CUTOFF.month + 1):
        first = date(CUTOFF.year, m, 1)
        last = date(CUTOFF.year, m, monthrange(CUTOFF.year, m)[1])
        months.append((m, first, min(last, CUTOFF)))
    labels = [f"{m}月" for m, _s, _e in months]
    ranges = [(s, e) for _m, s, e in months]
    keys = [f"{CUTOFF.year}-{m:02d}" for m, _s, _e in months]
    _render_period_table(labels, ranges, "本年每月", "monthly", keys,
                         show_summary=True, show_chart=True)


st.markdown(
    f'<div style="color:#8FA3B8;font-size:12.5px;margin:2px 0 6px 2px">'
    f'🗓 考核成績計算截至 <b style="color:#E5B454">{CUTOFF.strftime("%Y/%m/%d")}</b>（前一日）'
    f'｜今日（{TODAY.strftime("%m/%d")}）筆數即時顯示、不評級不列入平均；'
    f'可於「今日考核」欄手動評定今日成績</div>',
    unsafe_allow_html=True)

tab1, tab2, tab3 = st.tabs(["📅 當週每日", "🗓 近5週（含本週）", "📆 當年每月"])
with tab1:
    _tab_week_daily()
with tab2:
    _tab_recent5_weekly()
with tab3:
    _tab_year_monthly()

st.markdown(
    f'<div style="text-align:center;color:#6E8094;font-size:11px;margin-top:26px;letter-spacing:1.5px">'
    f'DATA · {wh_db.source_filename() or "wh_dashboard.db"}'
    f'</div>',
    unsafe_allow_html=True
)
