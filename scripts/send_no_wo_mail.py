# -*- coding: utf-8 -*-
"""其他代工廠-未開立工單 每日郵件報表

讀取 NAS 工單紀錄.xlsx（與廠銷訂單追蹤頁面同一套解析邏輯），
挑出「其他代工廠（非國智）且成品工單號碼空白」的清單，寄給生管主管。

用法:
    python send_no_wo_mail.py            # 實際寄出
    python send_no_wo_mail.py --dry-run  # 只產生預覽（data/mail_preview.html），不寄信

排程: Windows 工作排程器每日早上執行（工作名稱 ORing_PMC_NoWO_DailyMail）
"""
import argparse
import html
import json
import os
import smtplib
import sys
import time
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from email.utils import formataddr

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # oring_project/
sys.path.insert(0, ROOT)
from utils.pmc_wo_record import WO_REC_PATH, fmt_cell, parse_workbook, enrich  # noqa: E402

SMTP_HOST = "mail.oringnet.com"
SMTP_PORT = 25
SENDER = ("廠銷訂單追蹤系統", "pmc-tracking@oringnet.com")
RECIPIENTS = ["kevinkao@oringnet.com", "edisonkao@oringnet.com"]

EDITS_PATH = os.path.join(ROOT, "data", "pmc_tracking_edits.json")
PREVIEW_PATH = os.path.join(ROOT, "data", "mail_preview.html")
LOG_PATH = os.path.join(ROOT, "data", "mail_log.txt")

MAIL_COLS = ["通知日期", "訂單單號", "客戶簡稱", "品號", "品名", "訂單數量",
             "預交日", "完工日", "代工廠", "需求備註"]


def log(msg: str):
    line = f"[{datetime.now():%Y/%m/%d %H:%M:%S}] {msg}"
    print(line)
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def load_edits() -> dict:
    try:
        with open(EDITS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def build_mail():
    """回傳 (筆數, 主旨, HTML 內文)"""
    today = date.today()
    with open(WO_REC_PATH, "rb") as f:
        df = enrich(parse_workbook(f.read()), today)
    sub = df[(df["_grp"] == "其他") & (~df["_has_wo"])]
    edits = load_edits()

    esc = html.escape
    soon = today + timedelta(days=14)
    rows = []
    for i, (_, r) in enumerate(sub.iterrows(), 1):
        due = r["預交日"]
        try:
            due_d = due.date() if hasattr(due, "date") else None
        except (TypeError, ValueError):
            due_d = None
        urgent = due_d is not None and due_d <= soon
        due_style = "color:#b91c1c;font-weight:bold;" if urgent else ""
        note = fmt_cell(r["需求備註"]).replace("\n", "／")
        ed = edits.get(r["_key"], {})
        ed_txt = "；".join(f"{c}={v}" for c, v in ed.items())
        bg = "#fff7f7" if urgent else ("#ffffff" if i % 2 else "#f8fafc")
        cells = [
            str(i),
            fmt_cell(r["通知日期"]),
            fmt_cell(r["訂單單號"]) or "—",
            fmt_cell(r["客戶簡稱"]) or "—",
            fmt_cell(r["品號"]),
            fmt_cell(r["品名"])[:40],
            fmt_cell(r["訂單數量"]),
            (fmt_cell(r["預交日"]), due_style),
            fmt_cell(r["完工日"]),
            fmt_cell(r["代工廠"]) or "未填",
            note[:80] + ("…" if len(note) > 80 else ""),
            ed_txt,
        ]
        tds = []
        for c in cells:
            if isinstance(c, tuple):
                tds.append(f'<td style="padding:6px 8px;border:1px solid #dbe3ec;{c[1]}">{esc(c[0]) or "—"}</td>')
            else:
                tds.append(f'<td style="padding:6px 8px;border:1px solid #dbe3ec;">{esc(c) or "—"}</td>')
        rows.append(f'<tr style="background:{bg};">' + "".join(tds) + "</tr>")

    headers = ["#", "通知日期", "訂單單號", "客戶", "品號", "品名", "數量",
               "預交日", "完工日", "代工廠", "需求備註", "✏️填寫"]
    ths = "".join(
        f'<th style="padding:7px 8px;border:1px solid #33475a;background:#1e3a5f;color:#ffffff;'
        f'font-size:13px;white-space:nowrap;">{h}</th>' for h in headers
    )
    n = len(sub)
    n_urgent = sum("color:#b91c1c" in r for r in rows)

    if n == 0:
        body_main = ('<p style="font-size:15px;color:#15803d;">🎉 目前「其他代工廠」沒有未開立工單的項目。</p>')
    else:
        body_main = (
            f'<p style="font-size:14px;color:#334155;">共 <b style="color:#b91c1c;font-size:16px;">{n}</b> 筆'
            f'尚未開立成品工單（紅底＝預交日已過或 14 天內），請確認是否需開單：</p>'
            f'<table cellspacing="0" cellpadding="0" style="border-collapse:collapse;font-size:13px;'
            f'font-family:Segoe UI,Microsoft JhengHei,sans-serif;color:#334155;">'
            f"<tr>{ths}</tr>{''.join(rows)}</table>"
        )

    body = (
        '<div style="font-family:Segoe UI,Microsoft JhengHei,sans-serif;">'
        f'<h2 style="color:#1e3a5f;margin:0 0 4px;">📋 其他代工廠-未開立工單日報</h2>'
        f'<p style="color:#64748b;font-size:12.5px;margin:0 0 12px;">'
        f'{today:%Y/%m/%d}｜資料來源：生管部 改機排程 工單紀錄.xlsx（今年起、排除國智、成品工單號碼空白）｜'
        f'產生時間 {datetime.now():%H:%M}</p>'
        + body_main +
        '<p style="color:#94a3b8;font-size:11.5px;margin-top:14px;">'
        '此郵件由廠銷訂單追蹤系統自動寄出；明細與填寫請至 http://localhost:8501/pmc_order_tracking'
        '（⚠️ 其他-未開立工單 分頁）。</p></div>'
    )
    subject = f"【廠銷訂單追蹤】其他代工廠未開立工單 {n} 筆（{today:%m/%d}）"
    return n, subject, body


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只產生預覽，不寄信")
    args = ap.parse_args()

    try:
        n, subject, body = build_mail()
    except Exception as e:
        log(f"❌ 產生報表失敗: {e!r}")
        raise

    if args.dry_run:
        os.makedirs(os.path.dirname(PREVIEW_PATH), exist_ok=True)
        with open(PREVIEW_PATH, "w", encoding="utf-8") as f:
            f.write(body)
        log(f"dry-run: {n} 筆，預覽已存 {PREVIEW_PATH}")
        return

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr(SENDER)
    msg["To"] = ", ".join(RECIPIENTS)
    msg.set_content("此郵件為 HTML 格式，請使用支援 HTML 的郵件軟體開啟。")
    msg.add_alternative(body, subtype="html")

    # 公司郵件伺服器有灰名單（第一次寄會回 450 暫拒，數分鐘後重試即放行）→ 自動重試
    max_attempts, wait_s = 6, 300
    for attempt in range(1, max_attempts + 1):
        try:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=60) as s:
                refused = s.send_message(msg)
            if refused:
                log(f"⚠️ 部分收件者被拒: {refused}")
            log(f"✅ 已寄出 {n} 筆 → {', '.join(RECIPIENTS)}（第 {attempt} 次嘗試）")
            return
        except smtplib.SMTPRecipientsRefused as e:
            codes = {c for c, _ in e.recipients.values()}
            if all(400 <= c < 500 for c in codes) and attempt < max_attempts:
                log(f"⏳ 灰名單暫拒（第 {attempt} 次），{wait_s} 秒後自動重試…")
                time.sleep(wait_s)
                continue
            log(f"❌ 收件者被拒: {e.recipients}")
            raise
        except (smtplib.SMTPException, OSError) as e:
            if attempt < max_attempts:
                log(f"⏳ 寄送失敗（第 {attempt} 次）{e!r}，{wait_s} 秒後自動重試…")
                time.sleep(wait_s)
                continue
            log(f"❌ 寄信失敗: {e!r}")
            raise


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
