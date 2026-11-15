"""领域模型：路口、单向路段、巡检定位点。

坐标统一使用 :class:`fractions.Fraction` 表示，平方距离与吸附半径
判定全部为精确有理数运算，避免浮点误差造成边界歧义。
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction


@dataclass(frozen=True)
class Intersection:
    """路口：ID 与平面米坐标。"""

    node_id: str
    x: Fraction
    y: Fraction
    x_raw: str
    y_raw: str


@dataclass(frozen=True)
class Edge:
    """单向路段：ID、起终点路口与正整数长度（米）。"""

    edge_id: str
    source_id: str
    target_id: str
    length: int


@dataclass(frozen=True)
class TrackPoint:
    """按 UTC 秒记录的巡检车定位点。"""

    index: int
    timestamp: int
    x: Fraction
    y: Fraction
    x_raw: str
    y_raw: str


@dataclass(frozen=True)
class SolveParameters:
    """求解参数。"""

    snap_radius: int
    max_speed: int
