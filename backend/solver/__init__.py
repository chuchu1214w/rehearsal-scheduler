"""舞团排练排程求解包。

纯 Python + OR-Tools CP-SAT,不依赖数据库或 Web 框架。入口:

- :func:`solve` — 字典序分层求解(含缺席降级阶梯与全员评估场)
- :func:`validate_schedule` — 独立校验器
- :func:`diagnose` — 无解诊断
"""

from .diagnosis import diagnose
from .lexicographic import SolveOptions, solve
from .types import (
    DEFAULT_LADDER,
    DEFAULT_OBJECTIVES,
    OBJECTIVE_LABELS,
    Availability,
    EventConfig,
    FixedSession,
    LadderLevel,
    Problem,
    Rules,
    Session,
    SolveResult,
    Song,
)
from .validator import ValidationReport, compute_metrics, validate_schedule

__all__ = [
    "DEFAULT_LADDER",
    "DEFAULT_OBJECTIVES",
    "OBJECTIVE_LABELS",
    "Availability",
    "EventConfig",
    "FixedSession",
    "LadderLevel",
    "Problem",
    "Rules",
    "Session",
    "SolveOptions",
    "SolveResult",
    "Song",
    "ValidationReport",
    "compute_metrics",
    "diagnose",
    "solve",
    "validate_schedule",
]
