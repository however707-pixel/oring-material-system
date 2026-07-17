import hashlib
import html
import io
import json
import os
import re
import subprocess
import sys
from datetime import date, datetime

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from utils.shared import ensure_calamine, inject_css, render_header, render_sidebar
from utils.pmc_wo_record import (
    KEEP_COLS, NO_FIN, WO_REC_PATH, fmt_cell,
    enrich as wo_enrich, parse_workbook as wo_parse_workbook,
    sync_edits_to_excel as wo_sync_edits,
)

st.set_page_config(page_title="廠銷訂單追蹤", page_icon="📑", layout="wide")
ensure_calamine()
inject_css()
render_header(title="廠銷訂單追蹤", subtitle="Factory Sales Order Tracking · 改機排程工單紀錄", badge="PMC")
render_sidebar()

# ══════════════════════════════════════════════════════════════════════════════
# 資料來源：NAS 工單紀錄.xlsx（工作表1）
#   逐批 log：每批通知前插入一列表頭（第0欄=通知日期），表頭版本隨時間演變，
#   需逐區塊切割、依該區塊表頭對欄後再合併；「目標入庫日」= 新版的「完工日」。
# 顯示規則：只看今年（依通知日期），依完工日排序、按月份分組；
#   國智一份、其他（非國智）一份，其他再抓「未開立工單」清單。
# 填寫層：EDIT_COLS 欄位可填寫（識別欄不給填寫欄）。儲存後自動同步回 NAS 原檔
#   （寫入前備份、逐列身分核對）；檔案鎖定/離線時暫存 data/pmc_tracking_edits.json
#   作為待同步佇列，可手動「立即同步」。
# ══════════════════════════════════════════════════════════════════════════════

TODAY = date.today()
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
EDITS_PATH = os.path.join(DATA_DIR, "pmc_tracking_edits.json")
SNAP_PATH = os.path.join(DATA_DIR, "pmc_tracking_snapshot.json")     # 上次看到的檔案內容快照
CHANGES_PATH = os.path.join(DATA_DIR, "pmc_tracking_changes.json")   # 異動紀錄（新→舊）

# 可填寫的欄位（通知日期/訂單日期/訂單單號/客戶簡稱/品號/品名/訂單數量/成品工單號碼 不會修改，不給填寫欄）
EDIT_COLS = ["預交日", "完工日", "開工日(組包)", "完工日(打件)", "開工日(打件)", "代工廠", "需求備註"]


@st.cache_data(show_spinner=False)
def read_nas_bytes(path: str, mtime: float) -> bytes:
    with open(path, "rb") as f:
        return f.read()


@st.cache_data(show_spinner=False)
def parse_workbook(file_bytes: bytes) -> pd.DataFrame:
    """共用解析邏輯在 utils/pmc_wo_record.py（與每日郵件報表同一份）"""
    return wo_parse_workbook(file_bytes)


# ─── 填寫層（本機 JSON，不回寫 NAS 原檔）──────────────────────────────────────

def load_edits() -> dict:
    try:
        with open(EDITS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_edits(edits: dict):
    os.makedirs(os.path.dirname(EDITS_PATH), exist_ok=True)
    with open(EDITS_PATH, "w", encoding="utf-8") as f:
        json.dump(edits, f, ensure_ascii=False, indent=1)


def apply_edits(edited: pd.DataFrame) -> int:
    """把編輯器中 ✏️ 欄的內容寫回 JSON；回傳異動列數"""
    edits = load_edits()
    changed = 0
    for key, row in edited.iterrows():
        cur = edits.get(key, {})
        new = {}
        for c in EDIT_COLS:
            v = str(row.get(f"{c} ✏️", "")).strip()
            if v and v.lower() not in ("nan", "none"):
                new[c] = v
        if new != cur:
            changed += 1
            if new:
                edits[key] = new
            else:
                edits.pop(key, None)
    if changed:
        save_edits(edits)
    return changed


def sync_pending_edits():
    """本機填寫層同步回 NAS Excel；成功項目自 pending 移除。回傳訊息（無事可做回 None）"""
    edits = load_edits()
    if not edits:
        return None
    try:
        res = wo_sync_edits(edits, TODAY)
    except PermissionError:
        return f"⚠️ Excel 檔案使用中（可能有人開著），{len(edits)} 筆填寫已暫存本機，稍後再按「立即同步」"
    except OSError as e:
        return f"⚠️ 無法寫入 NAS（{e}），填寫已暫存本機"
    remaining = {k: v for k, v in edits.items() if k not in set(res["synced"])}
    save_edits(remaining)
    msgs = []
    if res["synced"]:
        msgs.append(f"✅ 已同步 {len(res['synced'])} 筆填寫回工單紀錄.xlsx（已自動備份）")
    if res["skipped"]:
        reasons = "；".join(list(res["skipped"].values())[:2])
        msgs.append(f"⚠️ {len(res['skipped'])} 筆未同步：{reasons}")
    return "｜".join(msgs) if msgs else None


# ─── 異動監看：快照比對 + 異動紀錄（NAS 檔案有變動時自動更新並記錄差異）──────

def load_snapshot():
    try:
        with open(SNAP_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def save_snapshot(rows: dict, file_mtime: float):
    os.makedirs(DATA_DIR, exist_ok=True)
    snap = {"mtime": file_mtime, "created": f"{datetime.now():%Y/%m/%d %H:%M:%S}", "rows": rows}
    with open(SNAP_PATH, "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False)


def load_changes() -> list:
    try:
        with open(CHANGES_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def df_to_rows(dframe: pd.DataFrame) -> dict:
    return {
        r["_key"]: {c: fmt_cell(r[c]) for c in KEEP_COLS}
        for _, r in dframe.iterrows()
    }


def compute_diff(old_rows: dict, new_rows: dict) -> list:
    """回傳異動清單：新增 / 移除 / 修改（含欄位層級差異）"""
    changes = []
    old_keys, new_keys = set(old_rows), set(new_rows)
    for k in sorted(new_keys - old_keys):
        changes.append({"type": "add", "row": new_rows[k]})
    for k in sorted(old_keys - new_keys):
        changes.append({"type": "del", "row": old_rows[k]})
    for k in sorted(old_keys & new_keys):
        diffs = [
            {"col": c, "old": old_rows[k].get(c, ""), "new": new_rows[k][c]}
            for c in KEEP_COLS
            if old_rows[k].get(c, "") != new_rows[k][c]
        ]
        if diffs:
            changes.append({"type": "mod", "row": new_rows[k], "diffs": diffs})
    return changes


def check_and_log_changes(dframe: pd.DataFrame, file_mtime: float):
    """NAS 檔案時間與快照不同時：比對差異 → 寫入異動紀錄 → 更新快照"""
    snap = load_snapshot()
    if snap is None:
        save_snapshot(df_to_rows(dframe), file_mtime)
        return
    if abs(snap.get("mtime", 0) - file_mtime) < 1e-6:
        return
    new_rows = df_to_rows(dframe)
    changes = compute_diff(snap.get("rows", {}), new_rows)
    if changes:
        n_add = sum(c["type"] == "add" for c in changes)
        n_mod = sum(c["type"] == "mod" for c in changes)
        n_del = sum(c["type"] == "del" for c in changes)
        batch = {
            "time": f"{datetime.now():%Y/%m/%d %H:%M:%S}",
            "file_time": f"{datetime.fromtimestamp(file_mtime):%Y/%m/%d %H:%M:%S}",
            "n_add": n_add, "n_mod": n_mod, "n_del": n_del,
            "n_total": len(changes),
            "changes": changes[:500],  # 單批最多存 500 筆明細
        }
        log = load_changes()
        log.insert(0, batch)
        del log[50:]  # 最多保留 50 批
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(CHANGES_PATH, "w", encoding="utf-8") as f:
            json.dump(log, f, ensure_ascii=False)
        st.toast(f"📢 工單紀錄有異動：新增 {n_add}・修改 {n_mod}・移除 {n_del}")
    save_snapshot(new_rows, file_mtime)


@st.fragment(run_every="30s")
def nas_watchdog(loaded_mtime: float):
    """每 30 秒檢查 NAS 檔案時間，變動時整頁重新載入（觸發重讀＋異動比對）"""
    try:
        cur = os.path.getmtime(WO_REC_PATH)
    except OSError:
        st.caption(f"⏱ 每 30 秒自動檢查 NAS 異動｜{datetime.now():%H:%M:%S} 無法連線 NAS")
        return
    if abs(cur - loaded_mtime) > 1e-6:
        st.toast("📢 偵測到工單紀錄檔案異動，重新載入最新版…")
        st.rerun()
    st.caption(
        f"⏱ 每 30 秒自動檢查 NAS 異動｜最後檢查 {datetime.now():%H:%M:%S}｜"
        f"目前載入版本：{datetime.fromtimestamp(loaded_mtime):%Y/%m/%d %H:%M:%S}"
    )


# ─── 資料來源（側欄）──────────────────────────────────────────────────────────

with st.sidebar:
    st.divider()
    st.markdown("### 📑 廠銷訂單追蹤 · 資料來源")
    nas_ok = os.path.exists(WO_REC_PATH)
    if nas_ok:
        mt = datetime.fromtimestamp(os.path.getmtime(WO_REC_PATH))
        st.success("✅ NAS 工單紀錄已連線")
        st.caption(f"檔案更新時間：{mt:%Y/%m/%d %H:%M}")
    else:
        st.warning("⚠️ NAS 離線或找不到 工單紀錄.xlsx")
    wo_uploaded = st.file_uploader("📂 上傳工單紀錄（NAS 離線時備援）", type=["xlsx"], key="_up_wo_rec")
    if st.button("🔄 重新載入 NAS 資料", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

nas_mtime = None
if wo_uploaded is not None:
    file_bytes = wo_uploaded.read()
elif nas_ok:
    nas_mtime = os.path.getmtime(WO_REC_PATH)
    with st.spinner("讀取 NAS 工單紀錄中…"):
        file_bytes = read_nas_bytes(WO_REC_PATH, nas_mtime)
else:
    st.info("📂 NAS 離線且未上傳檔案，無法顯示。")
    st.stop()

df = parse_workbook(file_bytes)

# 今年以前不看（依通知日期）＋分組/工單有無/完工月/列鍵（共用邏輯）
df = wo_enrich(df, TODAY)
if df.empty:
    st.warning(f"工單紀錄中找不到 {TODAY.year} 年（依通知日期）的資料。")
    st.stop()

EDITS = load_edits()

# NAS 檔案有異動 → 比對差異並寫入異動紀錄（手動上傳時不比對）
if nas_mtime is not None:
    check_and_log_changes(df, nas_mtime)

_saved = st.session_state.pop("_pmc_saved", None)
if _saved is not None:
    st.toast(f"💾 已儲存（{_saved} 列填寫內容更新）")
_sync_msg = st.session_state.pop("_pmc_sync_msg", None)
if _sync_msg:
    st.toast(_sync_msg)

# ─── 編輯器 ───────────────────────────────────────────────────────────────────

def build_view(sub: pd.DataFrame, with_status: bool) -> pd.DataFrame:
    view = pd.DataFrame(index=sub["_key"].tolist())
    if with_status:
        view["工單狀態"] = ["✅ 已開立" if b else "❌ 未開立" for b in sub["_has_wo"]]
    for c in KEEP_COLS:
        view[c] = [fmt_cell(v) for v in sub[c]]
        if c in EDIT_COLS:
            view[f"{c} ✏️"] = [EDITS.get(k, {}).get(c, "") for k in sub["_key"]]
    return view


def render_editor(sub: pd.DataFrame, tag: str, with_status: bool = False):
    view = build_view(sub, with_status)
    sig = hashlib.md5("|".join(view.index).encode()).hexdigest()[:8]
    colcfg = {}
    for c in view.columns:
        if c.endswith("✏️"):
            colcfg[c] = st.column_config.TextColumn(c, width="small", help="填寫後按下方💾儲存")
        elif c == "品名":
            colcfg[c] = st.column_config.TextColumn(c, width="large")
    edited = st.data_editor(
        view,
        hide_index=True,
        use_container_width=True,
        disabled=[c for c in view.columns if not c.endswith("✏️")],
        column_config=colcfg,
        key=f"ed_{tag}_{sig}",
        height=min(620, 62 + 35 * len(view)),
    )
    if st.button("💾 儲存此表填寫內容", key=f"sv_{tag}"):
        n = apply_edits(edited)
        st.session_state["_pmc_saved"] = n
        st.session_state["_pmc_sync_msg"] = sync_pending_edits()  # 同步回 NAS Excel
        st.rerun()


def month_sections(sub: pd.DataFrame, tag_prefix: str, with_status: bool = False):
    months = sorted(m for m in sub["_month"].unique() if m != NO_FIN)
    if (sub["_month"] == NO_FIN).any():
        months.append(NO_FIN)
    cur_month = TODAY.strftime("%Y/%m")
    for m in months:
        g = sub[sub["_month"] == m]
        qty = int(g["_qty"].fillna(0).sum())
        title = f"📅 {m}｜{len(g)} 筆・訂單量 {qty:,}・已開工單 {int(g['_has_wo'].sum())}/{len(g)}"
        with st.expander(title, expanded=(m == cur_month)):
            render_editor(g, f"{tag_prefix}_{m.replace('/', '')}", with_status)


def export_button(sub: pd.DataFrame, fname: str, tag: str, with_status: bool = False):
    exp = build_view(sub, with_status).rename(columns={f"{c} ✏️": f"{c}(填寫)" for c in EDIT_COLS})
    buf = io.BytesIO()
    exp.to_excel(buf, index=False, engine="openpyxl")
    buf.seek(0)
    st.download_button(
        "⬇ 匯出此分頁 (Excel)", data=buf, file_name=fname, key=f"dl_{tag}",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ─── 主畫面 ───────────────────────────────────────────────────────────────────

sub_gz = df[df["_grp"] == "國智"]
sub_ot = df[df["_grp"] == "其他"]
sub_no = sub_ot[~sub_ot["_has_wo"]]

k0, k1, k2, k3 = st.columns(4)
k0.metric(f"{TODAY.year} 年追蹤筆數", f"{len(df):,}")
k1.metric("國智", f"{len(sub_gz):,}")
k2.metric("其他代工廠", f"{len(sub_ot):,}")
k3.metric("其他-未開立工單", f"{len(sub_no):,}", help="其他代工廠中，成品工單號碼空白者")

st.markdown(
    f'<div class="status-card">'
    f'<h3>📑 改機排程工單紀錄（{TODAY.year} 年起，依通知日期）</h3>'
    f'依<b>完工日</b>排序、按月份分組（新版表頭的「目標入庫日」視為完工日）｜'
    f'國智分頁含複合代工廠（寶橋/國智…）｜'
    f'預交日/完工日/開工完工(組包/打件)/代工廠/需求備註 有 ✏️ 填寫欄，'
    f'按 💾 儲存後<b>自動同步回 NAS 工單紀錄.xlsx</b>（寫入前自動備份；'
    f'檔案使用中會暫存本機、稍後重試）'
    f'</div>',
    unsafe_allow_html=True,
)

# 待同步提示：儲存時檔案被鎖定/NAS 離線 → 填寫暫存本機，可手動重試
if EDITS:
    pd1, pd2 = st.columns([4.2, 1])
    pd1.warning(f"⏳ 有 {len(EDITS)} 筆填寫尚未同步回 Excel（暫存本機，不會遺失）")
    if pd2.button("🔄 立即同步", use_container_width=True):
        st.session_state["_pmc_sync_msg"] = sync_pending_edits()
        st.rerun()

# ═══ AI 助理 · 關鍵字查詢看板 ════════════════════════════════════════════════

st.markdown("### 🤖 AI 助理 · 關鍵字查詢")
st.caption(
    "輸入任何關鍵字（品號／訂單單號／客戶／工單號／代工廠／品名／備註／填寫內容…），"
    "按「查詢看板」直接彈出資訊看板；「問 AI」用自然語言提問（Claude API，多個關鍵字用空格隔開＝同時符合）。"
)

# 全欄位搜尋索引（原文 15 欄＋填寫層）
_hay = df[KEEP_COLS].map(fmt_cell).agg("｜".join, axis=1)
_hay_edit = df["_key"].map(lambda k: "｜".join(EDITS[k].values()) if k in EDITS else "")
HAY = (_hay + "｜" + _hay_edit).str.lower()


def edits_text(key: str, sep: str = "；") -> str:
    d = EDITS.get(key)
    return sep.join(f"{c}={v}" for c, v in d.items()) if d else ""


@st.cache_data(show_spinner=False)
def build_ai_context(_sig: str) -> str:
    """壓縮版全量資料（供 AI 讀取）：一列一筆"""
    lines = ["單號|客戶|品號|數量|預交日|完工日|開工(組包)|完工(打件)|開工(打件)|代工廠|工單號|備註|填寫"]
    for _, r in df.iterrows():
        note = fmt_cell(r["需求備註"]).replace("\n", " ")[:60]
        lines.append(
            f'{fmt_cell(r["訂單單號"])}|{fmt_cell(r["客戶簡稱"])}|{fmt_cell(r["品號"])}|'
            f'{fmt_cell(r["訂單數量"])}|{fmt_cell(r["預交日"])}|{fmt_cell(r["完工日"])}|'
            f'{fmt_cell(r["開工日(組包)"])}|{fmt_cell(r["完工日(打件)"])}|{fmt_cell(r["開工日(打件)"])}|'
            f'{fmt_cell(r["代工廠"])}|{fmt_cell(r["成品工單號碼"])}|{note}|{edits_text(r["_key"], ";")}'
        )
    return "\n".join(lines)


def ensure_anthropic():
    try:
        import anthropic  # noqa: F401
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "anthropic", "-q"], check=True)


def ask_ai(question: str):
    msgs = st.session_state.setdefault("pmc_ai_msgs", [])
    msgs.append({"role": "user", "text": question})
    try:
        ensure_anthropic()
        import anthropic

        client = anthropic.Anthropic()
        edits_mt = os.path.getmtime(EDITS_PATH) if os.path.exists(EDITS_PATH) else 0
        ctx = build_ai_context(f"{len(df)}|{edits_mt}")
        system_stable = (
            "你是「廠銷訂單追蹤」頁面的 AI 助理，服務台灣電子製造業（威力工業網絡）的生管與業務，"
            "資料來源是廠內改機排程的工單紀錄（今年起）。\n"
            "欄位說明：預交日＝業務要求交期；完工日＝目標入庫日；製程順序為 開工(打件)→完工(打件)→開工(組包)→完工日；"
            "工單號空白＝尚未開立工單；代工廠含「國智」歸國智分頁、其餘歸其他；"
            "「填寫」為生管人工補充的最新資訊，與原文不同時以填寫為準。\n"
            f"以下為全部資料，以 | 分隔、一列一筆：\n{ctx}\n\n"
            "請用繁體中文回答，簡潔（150字內），直接點出關鍵單號、品號、日期與數量；"
            "資料裡沒有的請直說並建議下一步。不要用 Markdown 符號。"
        )
        history = [
            {"role": "user" if m["role"] == "user" else "assistant", "content": m["text"]}
            for m in msgs[-7:]
        ]
        resp = client.messages.create(
            model="claude-opus-4-8",
            max_tokens=1000,
            system=[
                {"type": "text", "text": system_stable, "cache_control": {"type": "ephemeral"}},
                {"type": "text", "text": f"今天是 {TODAY:%Y-%m-%d}。"},
            ],
            messages=history,
        )
        answer = "".join(b.text for b in resp.content if b.type == "text").strip()
        answer = answer or "（沒有取得回覆，請再試一次）"
    except Exception as e:
        answer = None
        try:
            import anthropic as _a
            if isinstance(e, _a.AuthenticationError):
                answer = "API 金鑰無效或未設定。請設定 ANTHROPIC_API_KEY 環境變數後重新啟動應用程式。"
            elif isinstance(e, _a.RateLimitError):
                answer = "已達 Claude API 速率限制，請稍候再試。"
            elif isinstance(e, _a.APIConnectionError):
                answer = "連線 Claude API 失敗，請確認網路後再試。"
        except Exception:
            pass
        if answer is None:
            if "Could not resolve authentication" in str(e):
                answer = "尚未設定 API 金鑰。請設定 ANTHROPIC_API_KEY 環境變數後重新啟動應用程式。"
            else:
                answer = f"發生錯誤：{e}"
    msgs.append({"role": "ai", "text": answer})


with st.form("pmc_ai_form", clear_on_submit=False):
    fc1, fc2, fc3 = st.columns([5, 1.2, 1.2])
    q_input = fc1.text_input(
        "查詢", placeholder="例：9168｜2260-20260703001｜ORing SH｜5141｜寶橋…",
        label_visibility="collapsed",
    )
    b_board = fc2.form_submit_button("🔍 查詢看板", use_container_width=True)
    b_ai = fc3.form_submit_button("🤖 問 AI", use_container_width=True)

if b_board:
    st.session_state["pmc_q"] = q_input.strip()
if b_ai and q_input.strip():
    with st.spinner("AI 讀取工單紀錄中…"):
        ask_ai(q_input.strip())

# ── 對話紀錄 ──
for m in st.session_state.get("pmc_ai_msgs", []):
    body = html.escape(m["text"]).replace("\n", "<br>")
    if m["role"] == "user":
        st.markdown(
            f'<div style="background:#eef2fb;border:1px solid #c3d0e8;border-radius:12px;'
            f'padding:8px 14px;margin:6px 0 6px 18%;font-size:0.92rem;color:#1e293b;">{body}</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f'<div style="background:#ffffff;border:1px solid #e2e8f0;border-left:3px solid #1d4ed8;'
            f'border-radius:12px;padding:8px 14px;margin:6px 18% 6px 0;font-size:0.92rem;'
            f'color:#334155;line-height:1.7;">🤖 {body}</div>',
            unsafe_allow_html=True,
        )
if st.session_state.get("pmc_ai_msgs"):
    if st.button("🗑 清除對話", key="pmc_ai_clear"):
        st.session_state.pop("pmc_ai_msgs", None)
        st.rerun()

# ── 關鍵字資訊看板 ──
KB_CSS = """
<style>
.kb-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(330px,1fr)); gap:10px; margin:6px 0 4px; }
.kb-card { background:#ffffff; border:1px solid #dbe3ec; border-radius:12px; padding:11px 13px;
  font-size:13px; color:#334155; line-height:1.55; box-shadow:0 1px 2px rgba(15,23,42,.05); }
.kb-r1 { display:flex; justify-content:space-between; align-items:center; gap:6px; flex-wrap:wrap; }
.kb-oid { font-family:Consolas,monospace; font-weight:700; color:#1e3a5f; font-size:13px; }
.kb-pill { display:inline-block; border-radius:999px; padding:2px 9px; font-size:11.5px; font-weight:600; }
.kb-gz { background:#dbeafe; color:#1d4ed8; } .kb-ot { background:#ede9fe; color:#6d28d9; }
.kb-nv { background:#f1f5f9; color:#64748b; }
.kb-wo-y { background:#dcfce7; color:#15803d; } .kb-wo-n { background:#fee2e2; color:#b91c1c; }
.kb-r2 { margin-top:6px; font-weight:700; color:#0f172a; font-size:13.5px; }
.kb-r3 { color:#64748b; font-size:12px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.kb-dt { margin-top:6px; } .kb-dt b { color:#b91c1c; }
.kb-proc { color:#475569; font-size:12.5px; }
.kb-note { margin-top:4px; color:#92400e; font-size:12px; background:#fffbeb; border-radius:6px; padding:3px 8px; }
.kb-edit { margin-top:4px; color:#1d4ed8; font-size:12px; background:#eff6ff; border-radius:6px; padding:3px 8px; }
</style>
"""


def board_cards_html(hits: pd.DataFrame, limit: int = 24) -> str:
    esc = html.escape
    cards = []
    for _, r in hits.head(limit).iterrows():
        oid = fmt_cell(r["訂單單號"]) or fmt_cell(r["通知日期"])
        vend = fmt_cell(r["代工廠"])
        if r["_grp"] == "國智":
            vend_pill = f'<span class="kb-pill kb-gz">{esc(vend)}</span>'
        elif vend:
            vend_pill = f'<span class="kb-pill kb-ot">{esc(vend)}</span>'
        else:
            vend_pill = '<span class="kb-pill kb-nv">未填代工廠</span>'
        wo = fmt_cell(r["成品工單號碼"])
        wo_pill = (f'<span class="kb-pill kb-wo-y">✅ {esc(wo)}</span>' if wo
                   else '<span class="kb-pill kb-wo-n">❌ 未開工單</span>')
        qty = fmt_cell(r["訂單數量"])
        proc = []
        if fmt_cell(r["開工日(打件)"]) or fmt_cell(r["完工日(打件)"]):
            proc.append(f'打件 {esc(fmt_cell(r["開工日(打件)"])) or "—"}→{esc(fmt_cell(r["完工日(打件)"])) or "—"}')
        if fmt_cell(r["開工日(組包)"]):
            proc.append(f'組包 {esc(fmt_cell(r["開工日(組包)"]))}')
        proc_html = f'<div class="kb-proc">{"｜".join(proc)}</div>' if proc else ""
        note = fmt_cell(r["需求備註"]).replace("\n", "／")
        note_html = f'<div class="kb-note">📝 {esc(note[:60])}{"…" if len(note) > 60 else ""}</div>' if note else ""
        ed = edits_text(r["_key"])
        edit_html = f'<div class="kb-edit">✏️ {esc(ed)}</div>' if ed else ""
        cards.append(
            f'<div class="kb-card">'
            f'<div class="kb-r1"><span class="kb-oid">{esc(oid)}</span><span>{vend_pill} {wo_pill}</span></div>'
            f'<div class="kb-r2">{esc(fmt_cell(r["客戶簡稱"])) or "—"}　{esc(fmt_cell(r["品號"]))}</div>'
            f'<div class="kb-r3">{esc(fmt_cell(r["品名"]))}</div>'
            f'<div class="kb-dt">數量 {esc(qty) or "—"}｜預交 <b>{esc(fmt_cell(r["預交日"])) or "—"}</b>'
            f'｜完工 <b>{esc(fmt_cell(r["完工日"])) or "—"}</b></div>'
            + proc_html + note_html + edit_html
            + '</div>'
        )
    return KB_CSS + '<div class="kb-grid">' + "".join(cards) + "</div>"


board_q = st.session_state.get("pmc_q", "")
if board_q:
    terms = [t.lower() for t in board_q.split() if t]
    mask = pd.Series(True, index=df.index)
    for t in terms:
        mask &= HAY.str.contains(re.escape(t))
    hits = df[mask].sort_values(["_dt_完工", "_dt_通知"], na_position="last")

    h1, h2 = st.columns([5, 1])
    h1.markdown(f"#### 📌 「{board_q}」資訊看板")
    if h2.button("✖ 清除查詢", key="pmc_q_clear", use_container_width=True):
        st.session_state.pop("pmc_q", None)
        st.rerun()

    if hits.empty:
        st.warning(f"找不到包含「{board_q}」的資料（搜尋範圍：全部欄位＋填寫內容）。")
    else:
        b0, b1, b2, b3 = st.columns(4)
        b0.metric("命中筆數", f"{len(hits):,}")
        b1.metric("訂單量合計", f"{int(hits['_qty'].fillna(0).sum()):,}")
        b2.metric("已開立工單", f"{int(hits['_has_wo'].sum()):,}")
        b3.metric("未開立工單", f"{int((~hits['_has_wo']).sum()):,}")
        _mc = hits["_month"].value_counts()
        _mtxt = "、".join(f"{m}×{n}" for m, n in sorted(_mc.items()))
        st.caption(f"國智 {int((hits['_grp'] == '國智').sum())}・其他 {int((hits['_grp'] == '其他').sum())}"
                   f"｜完工月份：{_mtxt}")

        st.markdown(board_cards_html(hits), unsafe_allow_html=True)
        if len(hits) > 24:
            st.caption(f"僅顯示前 24 張卡片（共 {len(hits):,} 筆），完整清單請展開下方明細。")

        with st.expander(f"📋 命中明細表（{len(hits):,} 筆）"):
            disp_b = hits[KEEP_COLS].map(fmt_cell)
            disp_b["✏️填寫"] = hits["_key"].map(edits_text)
            st.dataframe(disp_b, use_container_width=True, hide_index=True,
                         height=min(500, 62 + 35 * len(disp_b)))
            buf_b = io.BytesIO()
            disp_b.to_excel(buf_b, index=False, engine="openpyxl")
            buf_b.seek(0)
            st.download_button(
                "⬇ 匯出查詢結果 (Excel)", data=buf_b, file_name=f"pmc_query_{board_q}.xlsx",
                key="dl_board",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

# ═══ 工單紀錄異動（NAS 檔案變動的差異紀錄）═══════════════════════════════════

st.markdown("### 📢 工單紀錄異動")

if nas_mtime is not None:
    nas_watchdog(nas_mtime)
else:
    st.caption("目前使用手動上傳檔案，異動監看暫停（NAS 恢復連線後自動繼續）。")

CHG_CSS = """
<style>
.chg-line { border-radius:8px; padding:5px 11px; margin:4px 0; font-size:12.8px; line-height:1.6; }
.chg-add { background:#f0fdf4; color:#166534; border:1px solid #bbf7d0; }
.chg-mod { background:#fffbeb; color:#92400e; border:1px solid #fde68a; }
.chg-del { background:#fef2f2; color:#b91c1c; border:1px solid #fecaca; }
.chg-line b { color:#0f172a; }
.chg-old { text-decoration:line-through; opacity:.7; }
.chg-new { font-weight:700; color:#b91c1c; }
</style>
"""


def _chg_ident(row: dict) -> str:
    esc = html.escape
    oid = row.get("訂單單號") or row.get("通知日期") or ""
    cust = row.get("客戶簡稱") or "—"
    return f'<b>{esc(oid)}</b>｜{esc(cust)}｜{esc(row.get("品號", ""))}'


def change_lines_html(changes: list, limit: int = 100) -> str:
    esc = html.escape
    lines = []
    for c in changes[:limit]:
        row = c["row"]
        if c["type"] == "add":
            brief = []
            for col in ["訂單數量", "預交日", "完工日", "代工廠", "成品工單號碼"]:
                if row.get(col):
                    brief.append(f'{col.replace("成品工單號碼", "工單")} {esc(row[col])}')
            lines.append(f'<div class="chg-line chg-add">🆕 新增｜{_chg_ident(row)}'
                         f'{"｜" + "・".join(brief) if brief else ""}</div>')
        elif c["type"] == "del":
            lines.append(f'<div class="chg-line chg-del">🗑 移除｜{_chg_ident(row)}</div>')
        else:
            diffs = "；".join(
                f'{esc(d["col"])}：<span class="chg-old">{esc(d["old"]) or "(空)"}</span>'
                f' → <span class="chg-new">{esc(d["new"]) or "(空)"}</span>'
                for d in c.get("diffs", [])
            )
            lines.append(f'<div class="chg-line chg-mod">✏️ 修改｜{_chg_ident(row)}｜{diffs}</div>')
    if len(changes) > limit:
        lines.append(f'<div class="chg-line">…另有 {len(changes) - limit} 筆異動</div>')
    return CHG_CSS + "".join(lines)


chg_log = load_changes()
if not chg_log:
    _snap = load_snapshot()
    base_t = _snap.get("created", "—") if _snap else "—"
    st.info(f"目前尚無異動紀錄。已建立比對基準（{base_t}），之後檔案一有變動就會列在這裡。")
else:
    latest = chg_log[0]
    st.markdown(
        f'<div class="status-card"><h3>📢 最新異動：{latest["time"]}</h3>'
        f'檔案存檔時間 <b>{latest["file_time"]}</b>｜'
        f'🆕 新增 <b>{latest["n_add"]}</b> 筆・✏️ 修改 <b>{latest["n_mod"]}</b> 筆・'
        f'🗑 移除 <b>{latest["n_del"]}</b> 筆</div>',
        unsafe_allow_html=True,
    )
    for i, batch in enumerate(chg_log[:10]):
        title = (f'🕒 {batch["time"]}｜檔案 {batch["file_time"]}｜'
                 f'🆕 {batch["n_add"]}・✏️ {batch["n_mod"]}・🗑 {batch["n_del"]}')
        with st.expander(title, expanded=(i == 0)):
            st.markdown(change_lines_html(batch["changes"]), unsafe_allow_html=True)
    if len(chg_log) > 10:
        st.caption(f"僅顯示最近 10 批異動（共保留 {len(chg_log)} 批）。")
    if st.button("🗑 清除異動紀錄", key="chg_clear"):
        try:
            os.remove(CHANGES_PATH)
        except OSError:
            pass
        st.rerun()

st.divider()

tab_gz, tab_ot, tab_no = st.tabs([
    f"🏭 國智（{len(sub_gz):,}）",
    f"🏭 其他代工廠（{len(sub_ot):,}）",
    f"⚠️ 其他-未開立工單（{len(sub_no):,}）",
])

with tab_gz:
    st.caption("代工廠含「國智」者（含 寶橋/國智 等複合），依完工日按月分組。")
    month_sections(sub_gz, "gz")
    export_button(sub_gz, "pmc_tracking_國智.xlsx", "gz")

with tab_ot:
    st.caption("排除國智的其他代工廠，首欄顯示是否已開立工單（依成品工單號碼有無）。")
    month_sections(sub_ot, "ot", with_status=True)
    export_button(sub_ot, "pmc_tracking_其他.xlsx", "ot", with_status=True)

with tab_no:
    st.caption("其他代工廠中「尚未開立工單」的清單（成品工單號碼空白），依完工日排序。此處填寫與「其他代工廠」分頁同步。")
    if sub_no.empty:
        st.success("🎉 其他代工廠目前沒有未開立工單的項目。")
    else:
        render_editor(sub_no, "noWo")
        export_button(sub_no, "pmc_tracking_其他未開工單.xlsx", "noWo")
