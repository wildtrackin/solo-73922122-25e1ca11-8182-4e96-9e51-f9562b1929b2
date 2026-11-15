"""三份 UTF-8 CSV 的解析与输入校验。

校验规则（任一不满足即抛出 :class:`AppError`，错误信息为中文）：

* 文件必须是 UTF-8 编码（允许带 BOM）；
* 表头必须与约定列名完全一致且顺序相同；
* 每行列数必须等于表头列数，任何单元格不得为空；
* 路口 1~20 个、路段 0~40 条、定位点 2~8 个；
* 路口 ID、路段 ID 非空且各自唯一；路段端点必须引用存在的路口；
* 路段长度为正整数；定位点 UTC 秒为严格递增整数；
* 吸附半径为非负整数，最高速度为正整数。
"""

from __future__ import annotations

import csv
import io
import re
from fractions import Fraction
from typing import Sequence

from .models import Edge, Intersection, TrackPoint

# 业务上限（需求明确规定）
MAX_INTERSECTIONS = 20
MAX_EDGES = 40
MIN_POINTS = 2
MAX_POINTS = 8

# 防止异常大数值导致的资源问题
MAX_ID_LEN = 64
MAX_COORD_ABS = 1_000_000_000
MAX_RADIUS = 1_000_000_000
MAX_SPEED = 1_000_000_000
MAX_TIMESTAMP_ABS = 10_000_000_000

INTERSECTION_HEADER = ("intersection_id", "x", "y")
EDGE_HEADER = ("edge_id", "from_intersection_id", "to_intersection_id", "length_m")
TRACK_HEADER = ("timestamp_utc", "x", "y")

_DECIMAL_RE = re.compile(r"^[+-]?(\d+\.\d+|\d+\.|\.\d+|\d+)([eE][+-]?\d+)?$")
_INT_RE = re.compile(r"^[+-]?\d+$")


class AppError(Exception):
    """面向用户的业务错误，``code`` 供前端程序化判断。"""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


# ---------------------------------------------------------------------------
# 基础取值
# ---------------------------------------------------------------------------
def _parse_decimal(text: str, what: str) -> Fraction:
    """解析有限十进制数（支持科学计数法），返回精确 Fraction。"""
    if not _DECIMAL_RE.match(text):
        raise AppError("INVALID_NUMBER", f"{what}必须是有限数字，实际为：{text!r}")
    try:
        value = Fraction(text)
    except (ValueError, ZeroDivisionError) as exc:  # pragma: no cover - 正则已兜底
        raise AppError("INVALID_NUMBER", f"{what}必须是有限数字，实际为：{text!r}") from exc
    if abs(value) > MAX_COORD_ABS:
        raise AppError("NUMBER_OUT_OF_RANGE", f"{what}绝对值不得超过 {MAX_COORD_ABS} 米：{text}")
    return value


def _parse_int(text: str, what: str, *, minimum: int, maximum: int) -> int:
    text = text.strip()
    if not _INT_RE.match(text):
        raise AppError("INVALID_INTEGER", f"{what}必须是整数，实际为：{text!r}")
    value = int(text)
    if value < minimum or value > maximum:
        raise AppError("INTEGER_OUT_OF_RANGE", f"{what}必须满足 {minimum} ≤ 值 ≤ {maximum}，实际为：{value}")
    return value


def _check_id(node_id: str, what: str, row_no: int) -> str:
    node_id = node_id.strip()
    if not node_id:
        raise AppError("EMPTY_ID", f"第 {row_no} 行的{what}不能为空")
    if len(node_id) > MAX_ID_LEN:
        raise AppError("ID_TOO_LONG", f"第 {row_no} 行的{what}长度不得超过 {MAX_ID_LEN} 个字符")
    return node_id


# ---------------------------------------------------------------------------
# CSV 通用解析
# ---------------------------------------------------------------------------
def _read_csv(raw: bytes, label: str) -> list[list[str]]:
    if raw is None or len(raw) == 0:
        raise AppError("EMPTY_FILE", f"{label}为空文件，请上传有效的 UTF-8 CSV")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise AppError("ENCODING_ERROR", f"{label}不是合法的 UTF-8 编码：{exc.reason}") from exc

    reader = csv.reader(io.StringIO(text, newline=""))
    try:
        rows = [row for row in reader]
    except csv.Error as exc:
        raise AppError("CSV_PARSE_ERROR", f"{label}CSV 格式无法解析：{exc}") from exc

    # csv.reader 会把纯空白行解析为空行，直接忽略；其余行必须列数齐全
    cleaned = [row for row in rows if row and not all(cell.strip() == "" for cell in row)]
    if not cleaned:
        raise AppError("EMPTY_FILE", f"{label}没有任何数据行")
    return cleaned


def _validate_table(
    rows: Sequence[Sequence[str]], expected_header: tuple[str, ...], label: str
) -> list[list[str]]:
    header = tuple(cell.strip() for cell in rows[0])
    if header != expected_header:
        raise AppError(
            "BAD_HEADER",
            f"{label}表头必须为 {','.join(expected_header)}，实际为：{','.join(header) or '(空)'}",
        )
    width = len(expected_header)
    data_rows: list[list[str]] = []
    for offset, row in enumerate(rows[1:], start=2):
        if len(row) != width:
            raise AppError(
                "BAD_COLUMN_COUNT",
                f"{label}第 {offset} 行有 {len(row)} 列，应与表头一致为 {width} 列",
            )
        stripped = [cell.strip() for cell in row]
        if any(cell == "" for cell in stripped):
            raise AppError("EMPTY_CELL", f"{label}第 {offset} 行存在空单元格")
        data_rows.append(stripped)
    return data_rows


# ---------------------------------------------------------------------------
# 三类文件
# ---------------------------------------------------------------------------
def parse_intersections(raw: bytes) -> list[Intersection]:
    label = "路口文件"
    rows = _validate_table(_read_csv(raw, label), INTERSECTION_HEADER, label)
    if not (1 <= len(rows) <= MAX_INTERSECTIONS):
        raise AppError(
            "COUNT_LIMIT",
            f"路口数量必须在 1~{MAX_INTERSECTIONS} 个之间，实际为 {len(rows)} 个",
        )

    intersections: list[Intersection] = []
    seen: set[str] = set()
    for row_no, row in enumerate(rows, start=2):
        node_id = _check_id(row[0], "路口 ID", row_no)
        if node_id in seen:
            raise AppError("DUPLICATE_ID", f"路口 ID 重复：{node_id}（第 {row_no} 行）")
        seen.add(node_id)
        x = _parse_decimal(row[1], f"第 {row_no} 行路口 x 坐标")
        y = _parse_decimal(row[2], f"第 {row_no} 行路口 y 坐标")
        intersections.append(Intersection(node_id, x, y, row[1], row[2]))
    return intersections


def parse_edges(raw: bytes, known_nodes: set[str]) -> list[Edge]:
    label = "路段文件"
    rows = _validate_table(_read_csv(raw, label), EDGE_HEADER, label)
    if len(rows) > MAX_EDGES:
        raise AppError("COUNT_LIMIT", f"路段数量不得超过 {MAX_EDGES} 条，实际为 {len(rows)} 条")

    edges: list[Edge] = []
    seen: set[str] = set()
    for row_no, row in enumerate(rows, start=2):
        edge_id = _check_id(row[0], "路段 ID", row_no)
        if edge_id in seen:
            raise AppError("DUPLICATE_ID", f"路段 ID 重复：{edge_id}（第 {row_no} 行）")
        seen.add(edge_id)

        source_id, target_id = row[1], row[2]
        if source_id not in known_nodes:
            raise AppError("UNKNOWN_NODE", f"路段 {edge_id} 的起点路口不存在：{source_id}")
        if target_id not in known_nodes:
            raise AppError("UNKNOWN_NODE", f"路段 {edge_id} 的终点路口不存在：{target_id}")
        length = _parse_int(row[3], f"路段 {edge_id} 长度（米）", minimum=1, maximum=MAX_COORD_ABS)
        edges.append(Edge(edge_id, source_id, target_id, length))
    return edges


def parse_track(raw: bytes) -> list[TrackPoint]:
    label = "定位文件"
    rows = _validate_table(_read_csv(raw, label), TRACK_HEADER, label)
    if not (MIN_POINTS <= len(rows) <= MAX_POINTS):
        raise AppError(
            "COUNT_LIMIT",
            f"定位点数量必须在 {MIN_POINTS}~{MAX_POINTS} 个之间，实际为 {len(rows)} 个",
        )

    points: list[TrackPoint] = []
    prev_ts: int | None = None
    for row_no, row in enumerate(rows, start=2):
        ts = _parse_int(
            row[0], f"第 {row_no} 行 UTC 秒", minimum=-MAX_TIMESTAMP_ABS, maximum=MAX_TIMESTAMP_ABS
        )
        if prev_ts is not None and ts <= prev_ts:
            raise AppError(
                "TIMESTAMP_NOT_STRICTLY_INCREASING",
                f"定位点 UTC 秒必须严格递增：第 {row_no} 行时间戳 {ts} 不大于上一点 {prev_ts}",
            )
        prev_ts = ts
        x = _parse_decimal(row[1], f"第 {row_no} 行定位 x 坐标")
        y = _parse_decimal(row[2], f"第 {row_no} 行定位 y 坐标")
        points.append(TrackPoint(len(points), ts, x, y, row[1], row[2]))
    return points


def parse_parameters(radius_text: str | None, speed_text: str | None) -> tuple[int, int]:
    if radius_text is None or radius_text.strip() == "":
        raise AppError("MISSING_PARAMETER", "吸附半径不能为空")
    if speed_text is None or speed_text.strip() == "":
        raise AppError("MISSING_PARAMETER", "最高速度不能为空")
    radius = _parse_int(radius_text, "吸附半径（米）", minimum=0, maximum=MAX_RADIUS)
    speed = _parse_int(speed_text, "最高速度（米/秒）", minimum=1, maximum=MAX_SPEED)
    return radius, speed
