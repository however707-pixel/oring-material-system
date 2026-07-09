# -*- coding: utf-8 -*-
"""
從 Outlook 讀取 Apollo HR（no_reply@mayohr.com）請假信，
解析倉庫同仁「當日」休假狀態，供倉儲備料看板顯示今日出勤。

信件範例（收件匣/mayohr.com 資料夾）：
    請假資料
    姓名：\t 陳冠芩
    日期/時間：\t 2026/07/03 08:30 ~ 2026/07/03 17:30
    假別/時數：\t 特休/8 時 0 分
"""
import os
import re
import sys
from datetime import date, datetime, timedelta

# 倉庫同仁名單（與年度倉儲考核依據表一致）
WAREHOUSE_STAFF = ["林麗婷", "鄭雅萍", "羅恆崇", "張揚晃",
                   "鍾志伶", "劉嘉怡", "陳冠芩", "賴仕杰"]

# HR 系統用字差異正規化（如「羅恒崇」→「羅恆崇」）
_CHAR_NORM = str.maketrans({"恒": "恆"})

_RE_NAME = re.compile(r"姓名：\s*(\S+)")
_RE_RANGE = re.compile(
    r"日期/時間：\s*(\d{4}/\d{1,2}/\d{1,2})\s*(\d{1,2}:\d{2})\s*~\s*"
    r"(\d{4}/\d{1,2}/\d{1,2})\s*(\d{1,2}:\d{2})")
_RE_TYPE = re.compile(r"假別/時數：\s*([^/\s]+)\s*/\s*(\d+)\s*時\s*(\d+)\s*分")


def _norm_name(s):
    return (s or "").strip().translate(_CHAR_NORM)


def _import_pywin32():
    """
    匯入 pythoncom / win32com.client。
    若服務行程早於 pywin32 安裝就啟動，pywin32.pth 尚未生效，
    這裡手動補上 win32 相關路徑與 DLL 目錄後重試，免重啟服務。
    """
    try:
        import pythoncom
        import win32com.client
        return pythoncom, win32com.client
    except ImportError:
        import site
        roots = list(site.getsitepackages())
        if site.getusersitepackages():
            roots.append(site.getusersitepackages())
        for root in roots:
            for sub in ("win32", os.path.join("win32", "lib"), "Pythonwin"):
                p = os.path.join(root, sub)
                if os.path.isdir(p) and p not in sys.path:
                    sys.path.append(p)
        import pywin32_bootstrap  # noqa: F401  # 註冊 pywin32_system32 DLL 目錄
        import pythoncom
        import win32com.client
        return pythoncom, win32com.client


def _parse_leave(body, today):
    """解析一封請假信；若請假區間涵蓋 today 回傳 dict，否則 None。"""
    m_n = _RE_NAME.search(body)
    m_r = _RE_RANGE.search(body)
    if not (m_n and m_r):
        return None
    name = _norm_name(m_n.group(1))
    try:
        d1 = datetime.strptime(m_r.group(1), "%Y/%m/%d").date()
        d2 = datetime.strptime(m_r.group(3), "%Y/%m/%d").date()
    except ValueError:
        return None
    if not (d1 <= today <= d2):
        return None
    t1 = m_r.group(2).zfill(5)
    t2 = m_r.group(4).zfill(5)
    m_t = _RE_TYPE.search(body)
    ltype = m_t.group(1) if m_t else "請假"
    hours = (int(m_t.group(2)) + int(m_t.group(3)) / 60.0) if m_t else 8.0

    # 判定「今天」休多少：單日直接用時數；跨日依當天涵蓋時段估算
    if d1 == d2:
        day_hours, s, e = hours, t1, t2
    elif today == d1:
        s, e = t1, "17:30"
        day_hours = 8 if t1 <= "09:00" else 4
    elif today == d2:
        s, e = "08:30", t2
        day_hours = 8 if t2 >= "17:00" else 4
    else:
        s, e = "08:30", "17:30"
        day_hours = 8

    if day_hours >= 7:
        part = "全天"
    elif day_hours >= 3:
        if s >= "12:00":
            part = "下午半天"
        elif e <= "13:30":
            part = "上午半天"
        else:
            part = "半天"
    else:
        part = f"{day_hours:g}時"

    return {"name": name, "type": ltype, "part": part, "time": f"{s}~{e}",
            "start": f"{d1} {t1}", "end": f"{d2} {t2}"}


def fetch_today_leaves(today=None, lookback_days=60):
    """
    掃描 Outlook 各帳戶的收件匣與 mayohr 子資料夾，
    回傳 (今日休假清單, 錯誤訊息或 None)。
    清單元素：{"name","type","part","time",...}，僅含倉庫同仁，
    全天在前、姓名排序。
    """
    today = today or date.today()
    try:
        pythoncom, win32client = _import_pywin32()
    except ImportError:
        return [], "未安裝 pywin32 套件（請執行 pip install pywin32）"

    pythoncom.CoInitialize()
    try:
        app = win32client.Dispatch("Outlook.Application")
        ns = app.GetNamespace("MAPI")

        folders = []
        for store in ns.Stores:
            try:
                inbox = store.GetDefaultFolder(6)   # olFolderInbox
            except Exception:
                continue
            folders.append(inbox)
            try:
                for sub in inbox.Folders:
                    if "mayohr" in (sub.Name or "").lower():
                        folders.append(sub)
            except Exception:
                pass
        if not folders:
            return [], "Outlook 中找不到收件匣"

        cutoff = datetime.combine(today - timedelta(days=lookback_days),
                                  datetime.min.time())
        seen, leaves = set(), []
        for folder in folders:
            try:
                items = folder.Items
                items.Sort("[ReceivedTime]", True)   # 新→舊
            except Exception:
                continue
            for it in items:
                try:
                    rt = it.ReceivedTime
                    if rt and rt.replace(tzinfo=None) < cutoff:
                        break
                    subj = it.Subject or ""
                except Exception:
                    continue
                if "請假單" not in subj:
                    continue
                try:
                    body = it.Body or ""
                except Exception:
                    continue
                rec = _parse_leave(body, today)
                if not rec or rec["name"] not in WAREHOUSE_STAFF:
                    continue
                key = (rec["name"], rec["start"], rec["end"], rec["type"])
                if key in seen:
                    continue
                seen.add(key)
                leaves.append(rec)

        leaves.sort(key=lambda r: (r["part"] != "全天", r["name"]))
        return leaves, None
    except Exception as e:
        return [], f"無法讀取 Outlook（{type(e).__name__}）"
    finally:
        pythoncom.CoUninitialize()
