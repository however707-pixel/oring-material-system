# -*- coding: utf-8 -*-
"""工作日計算：週一~週五，扣除國定假日、加回補班日。

假日表依「中華民國115年（2026）政府行政機關辦公日曆表」（行政院人事行政總處）。
2026 全年共 16 個落在週一~週五的放假日（見下表），且自 2025 下半年起已取消補班
制度，改為一律補假，故 2026 無補班日。補假原則：逢星期六補前一個上班日、逢星期
日補次一個上班日。

注意：本表與 pages/10_scheduling.py、pages/15_kanban.py 內既有的 TAIWAN_HOLIDAYS
不同——那兩份缺了《紀念日及節日實施條例》新增的教師節、光復節、行憲紀念日，
且 1/2 誤列為彈性放假、228 補假誤植為 3/2。以本檔為準。
"""
from datetime import date, timedelta

# ── 國定假日（週六日已由 weekday() 排除，這裡只填平日放假與補假）─────────────
TW_HOLIDAYS = {
    # ── 2026（115年）──────────────────────────────────────
    date(2026, 1, 1),    # 元旦（四）　※1/2(五) 為正常上班日
    date(2026, 2, 16),   # 農曆除夕（一）
    date(2026, 2, 17),   # 春節初一（二）
    date(2026, 2, 18),   # 春節初二（三）
    date(2026, 2, 19),   # 春節初三（四）
    date(2026, 2, 20),   # 小年夜補假（五）－ 小年夜 2/14 逢週六
    date(2026, 2, 27),   # 和平紀念日補假（五）－ 2/28 逢週六
    date(2026, 4, 3),    # 兒童節補假（五）－ 4/4 逢週六
    date(2026, 4, 6),    # 民族掃墓節補假（一）－ 4/5 逢週日
    date(2026, 5, 1),    # 勞動節（五）
    date(2026, 6, 19),   # 端午節（五）
    date(2026, 9, 25),   # 中秋節（五）
    date(2026, 9, 28),   # 教師節（一）
    date(2026, 10, 9),   # 國慶日補假（五）－ 10/10 逢週六
    date(2026, 10, 26),  # 臺灣光復暨金門古寧頭大捷紀念日補假（一）－ 10/25 逢週日
    date(2026, 12, 25),  # 行憲紀念日（五）
    # ── 2027（116年）──────────────────────────────────────
    date(2027, 1, 1),    # 元旦（五）
    # TODO: 2027 其餘假日待人事行政總處公告辦公日曆表後補上
}

# ── 補班日：逢彈性放假而挪移的上班六 ─────────────────────────────────────────
# 2026 已取消補班制度，維持空集合；若日後恢復，填入日期即會被視為工作日。
TW_MAKEUP_WORKDAYS = set()

# ── 臨時停班日：颱風、災防等實際未上班的日子（非國定假日）───────────────────
# 原本記錄在 utils/warroom_data.py。保留於此，歷史 KPI（倉儲備料看板的
# prev_workday／週工作日數）才不會把當天誤算成工作日。
TW_CLOSURES = {
    date(2026, 7, 10),   # 颱風停班
}

# 所有不上班的日子＝國定假日 ∪ 臨時停班日。
# is_workday() 以此判斷；utils/warroom_data.TW_HOLIDAYS 也沿用這個名稱對外相容。
TW_OFF_DAYS = TW_HOLIDAYS | TW_CLOSURES


def is_workday(d: date) -> bool:
    """d 是否為工作日（週一~週五、非國定假日與停班日；補班日視為工作日）。"""
    if d is None:
        return False
    if d in TW_MAKEUP_WORKDAYS:
        return True
    return d.weekday() < 5 and d not in TW_OFF_DAYS


def net_workdays(a: date, b: date) -> int:
    """a → b 之間的工作天數；不含 a、含 b。b 早於 a 回傳負值。

    與 pages/10_scheduling.py 的 count_workdays() 同語意，差別只在允許負值。
    """
    if a is None or b is None or a == b:
        return 0
    sign = 1 if b > a else -1
    lo, hi = (a, b) if b > a else (b, a)
    n, cur = 0, lo
    while cur < hi:
        cur += timedelta(days=1)
        if is_workday(cur):
            n += 1
    return sign * n


def add_workdays(d: date, n: int) -> date:
    """從 d 往後（n>0）或往前（n<0）推 n 個工作天。"""
    if d is None:
        return None
    if n == 0:
        return d
    step = 1 if n > 0 else -1
    left, cur = abs(int(n)), d
    while left:
        cur += timedelta(days=step)
        if is_workday(cur):
            left -= 1
    return cur


def next_workday(d: date) -> date:
    """d 當天若為工作日就回傳 d，否則往後找到第一個工作日。"""
    cur = d
    while cur is not None and not is_workday(cur):
        cur += timedelta(days=1)
    return cur


def prev_workday(d: date) -> date:
    """d 的「前一個」工作日（不含 d 當天），跳過週六日、國定假日與停班日。

    與 utils/warroom_data.py 原本的 prev_workday() 同語意。
    """
    if d is None:
        return None
    cur = d - timedelta(days=1)
    while not is_workday(cur):
        cur -= timedelta(days=1)
    return cur
