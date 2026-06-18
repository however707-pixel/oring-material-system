-- ============================================================
-- 倉儲備料看板 資料庫 schema (SQLite)
-- 對應來源檔案：
--   \\192.168.2.34\...\調件備料統計表\調件備料統計-YYYYMMDD.xlsx
--     - 調撥單
--     - 入庫單據
--     - 錯料歸還追蹤
--   \\192.168.2.34\...\早會資料夾\簡版-工單缺料狀況.xlsx (LIST)
-- ============================================================

-- 調撥單（備料 / 上架紀錄）
CREATE TABLE IF NOT EXISTS transfer_orders (
    id              TEXT PRIMARY KEY,   -- 編號 (單別-單號)
    order_type      TEXT,               -- 單別
    order_no        TEXT,               -- 單號
    order_date      DATE,               -- 開單日
    demand_unit     TEXT,               -- 需求單位
    demand_date     DATE,               -- 需求日
    demand_qty      INTEGER,            -- 需求筆數
    complete_qty    INTEGER,            -- 完成筆數
    prep_staff      TEXT,               -- 備料人員
    prep_date       DATE,               -- 備料日
    complete_date   DATE,               -- 完成日
    status          TEXT,               -- 狀態 (已完成/上架/...)
    note            TEXT,               -- 備註
    deduction       TEXT,               -- 扣帳
    error_qty       INTEGER,            -- 出錯筆數
    error_reason    TEXT,               -- 出錯原因
    note2           TEXT,               -- 備註2
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_transfer_complete_date ON transfer_orders(complete_date);
CREATE INDEX IF NOT EXISTS idx_transfer_demand_date   ON transfer_orders(demand_date);
CREATE INDEX IF NOT EXISTS idx_transfer_order_date    ON transfer_orders(order_date);
CREATE INDEX IF NOT EXISTS idx_transfer_status        ON transfer_orders(status);

-- 入庫單據
CREATE TABLE IF NOT EXISTS inbound_orders (
    id              TEXT PRIMARY KEY,   -- 編號 (單別-單號)
    order_type      TEXT,               -- 單別
    order_no        TEXT,               -- 單號
    inspect_date    DATE,               -- 驗畢日期
    receive_date    DATE,               -- 接單日期
    expect_date     DATE,               -- 預計完成日
    qty             INTEGER,            -- 筆數
    pickup_date     DATE,               -- 取單日
    complete_date   DATE,               -- 完成日
    inbound_staff   TEXT,               -- 入庫人員
    note            TEXT,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_inbound_complete_date ON inbound_orders(complete_date);

-- 錯料歸還追蹤
CREATE TABLE IF NOT EXISTS error_returns (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    notify_date     DATE,               -- 通知日期
    prep_staff      TEXT,               -- 備料人員
    order_no        TEXT,               -- 單號
    part_no         TEXT,               -- 料號
    qty             INTEGER,            -- 數量
    close_date      DATE,               -- 結案日期
    unit            TEXT,               -- 單位
    note            TEXT,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 工單出貨排程／缺料狀況（每日快照，匯入時以 work_order 覆蓋更新）
CREATE TABLE IF NOT EXISTS shipment_schedule (
    work_order      TEXT PRIMARY KEY,   -- 工單
    product_no      TEXT,               -- 產品編號
    planned_qty     INTEGER,            -- 預計產量
    material_rate   REAL,               -- 整體料齊率 (0~1)
    ship_date       DATE,               -- 產銷出貨日
    status_note     TEXT,               -- 進料狀況內容／重點提示
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 匯入紀錄（追蹤每次從 NAS 同步的結果）
CREATE TABLE IF NOT EXISTS import_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source_file     TEXT,
    source_mtime    TIMESTAMP,
    imported_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    transfer_rows   INTEGER,
    inbound_rows    INTEGER,
    error_rows      INTEGER,
    schedule_rows   INTEGER
);

-- ============================================================
-- Views：取代「工時效率計算-每日」分頁，改用 SQL 即時計算
-- ============================================================

-- 每日備料筆數／人均（取代 eff_biao）
CREATE VIEW IF NOT EXISTS v_daily_prep AS
SELECT
    complete_date AS date,
    COUNT(DISTINCT prep_staff)                              AS staff_count,
    SUM(demand_qty)                                         AS prep_qty,
    ROUND(SUM(demand_qty) * 1.0 / COUNT(DISTINCT prep_staff), 1) AS avg_per_staff
FROM transfer_orders
WHERE status = '已完成' AND complete_date IS NOT NULL
GROUP BY complete_date;

-- 每日上架筆數／人均（取代 eff_in）
CREATE VIEW IF NOT EXISTS v_daily_inbound AS
SELECT
    complete_date AS date,
    COUNT(DISTINCT prep_staff)                                AS staff_count,
    SUM(complete_qty)                                         AS inbound_qty,
    ROUND(SUM(complete_qty) * 1.0 / COUNT(DISTINCT prep_staff), 1) AS avg_per_staff
FROM transfer_orders
WHERE status = '上架' AND complete_date IS NOT NULL
GROUP BY complete_date;
