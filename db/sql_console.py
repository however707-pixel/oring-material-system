# -*- coding: utf-8 -*-
"""
簡易 SQL 主控台 —— 直接對 wh_dashboard.db 下 SQL。

用法：
    python db/sql_console.py
    （進入後輸入 SQL，按 Enter 執行；輸入 .tables 看所有表；.quit 離開）
"""
import os
import sqlite3
import pandas as pd

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                  "data", "wh_dashboard.db")

pd.set_option("display.max_rows", 100)
pd.set_option("display.width", 200)
pd.set_option("display.unicode.east_asian_width", True)

conn = sqlite3.connect(DB)
print(f"已連線：{DB}")
print("輸入 SQL 後按 Enter 執行。指令：.tables 看表 / .schema 表名 / .quit 離開\n")

while True:
    try:
        sql = input("sql> ").strip()
    except (EOFError, KeyboardInterrupt):
        break
    if not sql:
        continue
    if sql in (".quit", ".exit", "exit", "quit"):
        break
    if sql == ".tables":
        rows = conn.execute(
            "SELECT name, type FROM sqlite_master WHERE type IN ('table','view') ORDER BY type, name"
        ).fetchall()
        for name, typ in rows:
            print(f"  [{typ}] {name}")
        print()
        continue
    if sql.startswith(".schema"):
        parts = sql.split()
        if len(parts) > 1:
            row = conn.execute(
                "SELECT sql FROM sqlite_master WHERE name=?", (parts[1],)
            ).fetchone()
            print(row[0] if row else "(找不到該表)")
        print()
        continue
    try:
        if sql.lower().startswith(("select", "with", "pragma")):
            df = pd.read_sql_query(sql, conn)
            print(df.to_string(index=False) if not df.empty else "(無資料)")
            print(f"\n共 {len(df)} 列\n")
        else:
            cur = conn.execute(sql)
            conn.commit()
            print(f"OK，影響 {cur.rowcount} 列\n")
    except Exception as e:
        print(f"[錯誤] {e}\n")

conn.close()
print("已離開。")
