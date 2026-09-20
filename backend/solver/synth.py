"""合成空闲矩阵(测试与演示用)。真实数据由成员在系统里填写,这里只是造出“像真的”的输入。"""

from __future__ import annotations

import random
from collections.abc import Iterable

from .types import AVAILABLE, AVOID, UNAVAILABLE, Availability, EventConfig


def synthesize_availability(
    config: EventConfig,
    members: Iterable[str],
    *,
    seed: int = 42,
    density: float = 0.55,
    avoid_rate: float = 0.05,
    persistence: float = 0.8,
    ensure_eval_window: bool = True,
) -> Availability:
    """按“工作日晚上更空、周末整天更空”的模式随机生成,并用马尔可夫链让可用时段成块。

    ``ensure_eval_window`` 为 True 时,会在评估日开出一个全员共同可用的 3 小时窗口。
    """
    rng = random.Random(seed)
    slots = config.slots_per_day
    evening_from = max(0, 18 - config.day_start_hour)
    avail = Availability()
    for m in members:
        for d in config.all_dates:
            weekend = d.weekday() >= 5
            row = [UNAVAILABLE] * slots
            prev = None
            for h in range(slots):
                if weekend:
                    p = min(1.0, density * 1.2)
                elif h >= evening_from:
                    p = min(1.0, density * 1.4)
                else:
                    p = density * 0.5
                if prev is None or rng.random() > persistence:
                    state = AVAILABLE if rng.random() < p else UNAVAILABLE
                else:
                    state = prev
                prev = state
                row[h] = state
            for h in range(slots):
                if row[h] == AVAILABLE and rng.random() < avoid_rate:
                    row[h] = AVOID
            avail.set_row(m, d, row)

    if ensure_eval_window:
        width = max(config.eval_durations)
        start = rng.randrange(0, slots - width + 1)
        for m in members:
            row = avail.grid[m][config.eval_date]
            for h in range(start, start + width):
                if row[h] == UNAVAILABLE:
                    row[h] = AVAILABLE
    return avail
