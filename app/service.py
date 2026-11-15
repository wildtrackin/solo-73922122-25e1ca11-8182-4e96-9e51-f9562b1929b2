"""应用服务层：编排解析、求解与结果导出。"""

from __future__ import annotations

import io
import csv
import time
import uuid
from dataclasses import dataclass
from fractions import Fraction
from threading import Lock

from .parsing import AppError, parse_edges, parse_intersections, parse_parameters, parse_track
from .solver import SolveResult, solve

RESULT_TTL_SECONDS = 3600
RESULT_MAX_ENTRIES = 200


@dataclass
class StoredResult:
    result: SolveResult
    created_at: float
    export_filename: str
    export_content: bytes


class ResultStore:
    """线程安全的短期结果存储，供求解后下载使用。"""

    def __init__(self) -> None:
        self._lock = Lock()
        self._items: dict[str, StoredResult] = {}

    def put(self, stored: StoredResult) -> str:
        token = uuid.uuid4().hex
        with self._lock:
            self._purge_locked()
            if len(self._items) >= RESULT_MAX_ENTRIES:
                oldest = min(self._items.items(), key=lambda kv: kv[1].created_at)[0]
                del self._items[oldest]
            self._items[token] = stored
        return token

    def get(self, token: str) -> StoredResult | None:
        with self._lock:
            self._purge_locked()
            stored = self._items.get(token)
            return stored

    def _purge_locked(self) -> None:
        now = time.time()
        expired = [token for token, item in self._items.items() if now - item.created_at > RESULT_TTL_SECONDS]
        for token in expired:
            del self._items[token]


RESULT_STORE = ResultStore()


def run_solve(
    intersections_raw: bytes | None,
    edges_raw: bytes | None,
    track_raw: bytes | None,
    radius_text: str | None,
    speed_text: str | None,
) -> SolveResult:
    """校验三份 CSV 与参数并执行求解；无效输入抛出 :class:`AppError`。"""
    if intersections_raw is None:
        raise AppError("MISSING_FILE", "未上传路口 CSV 文件")
    if edges_raw is None:
        raise AppError("MISSING_FILE", "未上传路段 CSV 文件")
    if track_raw is None:
        raise AppError("MISSING_FILE", "未上传定位 CSV 文件")

    snap_radius, max_speed = parse_parameters(radius_text, speed_text)
    intersections = parse_intersections(intersections_raw)
    node_ids = {node.node_id for node in intersections}
    edges = parse_edges(edges_raw, node_ids)
    points = parse_track(track_raw)

    return solve(intersections, edges, points, snap_radius, max_speed)


def build_export(result: SolveResult) -> tuple[str, bytes]:
    """为唯一解生成路段 ID CSV；待核/不可行不允许导出。"""
    if result.status != "unique":
        raise AppError("EXPORT_NOT_ALLOWED", "仅唯一确定的结果允许导出，待核或不可行结果不产生文件")

    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(["sequence_no", "edge_id", "from_intersection_id", "to_intersection_id", "length_m"])
    for seq, edge in enumerate(result.edge_sequence, start=1):
        writer.writerow([seq, edge.edge_id, edge.source_id, edge.target_id, edge.length])
    data = buffer.getvalue().encode("utf-8")
    filename = "edge_sequence.csv"
    return filename, data


def serialize_result(result: SolveResult, download_token: str | None = None) -> dict:
    """把求解结果转换为可 JSON 序列化的响应体。"""
    payload: dict = {
        "status": result.status,
        "reason_code": result.reason_code,
        "message": result.message,
        "point_count": result.point_count,
        "candidate_counts": result.candidate_counts,
    }
    if result.minimum_cost is not None:
        payload["minimum_squared_distance_sum"] = _fraction_to_json(result.minimum_cost)
    if result.optimal_node_sequences:
        payload["optimal_node_sequences"] = result.optimal_node_sequences
        payload["optimal_node_sequence_count"] = result.optimal_node_sequence_count

    if result.status == "unique":
        payload["matched_node_sequence"] = result.matched_node_sequence
        payload["edge_sequence"] = [
            {
                "sequence_no": i,
                "edge_id": edge.edge_id,
                "from_intersection_id": edge.source_id,
                "to_intersection_id": edge.target_id,
                "length_m": edge.length,
            }
            for i, edge in enumerate(result.edge_sequence, start=1)
        ]
        payload["hop_details"] = result.hop_details
        if download_token is not None:
            payload["download_url"] = f"/api/results/{download_token}/download"
    elif result.status == "pending":
        payload["ambiguity"] = result.ambiguity
        if result.hop_details:
            payload["hop_details"] = result.hop_details
    else:  # infeasible
        payload["infeasible_detail"] = result.infeasible_detail
    return payload


def _fraction_to_json(value: Fraction) -> dict:
    return {
        "exact": f"{value.numerator}/{value.denominator}",
        "decimal": float(value),
        "is_integer": value.denominator == 1,
    }


def store_result(result: SolveResult) -> str | None:
    """唯一解生成导出文件并登记；其他状态不产生结果文件。"""
    if result.status != "unique":
        return None
    filename, content = build_export(result)
    return RESULT_STORE.put(StoredResult(result, time.time(), filename, content))
