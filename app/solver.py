"""核心求解：定位点到路口序列的最优吸附与有向最短路拼接。

业务规则
--------
1. 每个定位点只能匹配吸附半径（米）内的路口；
2. 相邻两个匹配路口之间必须存在有向最短路（允许匹配到同一路口，
   此时经过 0 条路段、长度 0，仍满足速度约束）；
3. 最短路长度不得超过两点时间差 × 最高速度；
4. 在所有可行方案中，取各定位点到所选路口的平方距离总和最小的方案；
5. 最优路口序列不唯一，或唯一路口序列上存在相邻路口的最短路段序列
   不唯一（含等长平行路段）时，判定为“待核”，不导出确定路径。

实现要点
--------
* 平方距离、半径比较全部使用 :class:`fractions.Fraction` 精确运算；
* Floyd-Warshall 同时维护最短距离矩阵和最短路径“条数”矩阵，
  路径条数按有向边序列计数（等长平行路段各自计数）；
* 动态规划按点序推进，维护到每个候选路口的最小平方距离代价与
  达到该代价的路口序列条数，同样支持精确计数与唯一回溯。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction

from .models import Edge, Intersection, TrackPoint

# 路径条数超过该值即视为“很多”，仅保留量级用于展示，避免极端组合爆炸
WAY_COUNT_CAP = 1_000_000


def _cap_ways(value: int) -> int:
    return value if value < WAY_COUNT_CAP else WAY_COUNT_CAP


@dataclass
class ShortestPathMatrix:
    """有向图全源最短路结果。

    ``dist[i][j]`` 为路口 i→j 的最短距离（整数），不可达为 ``None``；
    ``ways[i][j]`` 为达到该最短距离的有向路段序列条数
    （``i == j`` 时空序列计 1 条）；
    ``first_edge[i][j]`` 为某条最短路上的第一条边，供唯一时重建。
    """

    n: int
    dist: list[list[int | None]]
    ways: list[list[int]]
    first_edge: list[list[Edge | None]]


def build_shortest_paths(intersections: list[Intersection], edges: list[Edge]) -> ShortestPathMatrix:
    """Floyd-Warshall 求全源最短路及最短路径条数。"""
    n = len(intersections)
    index_of = {node.node_id: i for i, node in enumerate(intersections)}

    dist: list[list[int | None]] = [[None] * n for _ in range(n)]
    ways: list[list[int]] = [[0] * n for _ in range(n)]
    first_edge: list[list[Edge | None]] = [[None] * n for _ in range(n)]

    for i in range(n):
        dist[i][i] = 0
        ways[i][i] = 1  # 空路径

    # 平行边全部保留：等长时 ways 累加，长度更小时替换
    for edge in edges:
        u = index_of[edge.source_id]
        v = index_of[edge.target_id]
        current = dist[u][v]
        if current is None or edge.length < current:
            dist[u][v] = edge.length
            ways[u][v] = 1
            first_edge[u][v] = edge
        elif edge.length == current:
            ways[u][v] += 1

    for k in range(n):
        for i in range(n):
            if i == k or dist[i][k] is None:
                continue
            dik = dist[i][k]
            assert dik is not None
            for j in range(n):
                if j == k or dist[k][j] is None:
                    continue
                dkj = dist[k][j]
                assert dkj is not None
                candidate = dik + dkj
                current = dist[i][j]
                if current is None or candidate < current:
                    dist[i][j] = candidate
                    ways[i][j] = ways[i][k] * ways[k][j]
                    first_edge[i][j] = first_edge[i][k]
                elif candidate == current:
                    ways[i][j] += ways[i][k] * ways[k][j]

    return ShortestPathMatrix(n, dist, ways, first_edge)


def _squared_distance(px: Fraction, py: Fraction, node: Intersection) -> Fraction:
    dx = px - node.x
    dy = py - node.y
    return dx * dx + dy * dy


@dataclass
class PointCandidate:
    """单个定位点在半径内的候选路口。"""

    point_index: int
    node_index: int
    squared_distance: Fraction


@dataclass
class SolveResult:
    """求解结果，状态由 ``status`` 区分。"""

    status: str  # "unique" | "pending" | "infeasible"
    reason_code: str
    message: str
    # 输入回显
    point_count: int
    candidate_counts: list[int] = field(default_factory=list)
    # unique / pending 共有
    optimal_node_sequences: list[list[str]] = field(default_factory=list)
    optimal_node_sequence_count: int = 0
    minimum_cost: Fraction | None = None
    # unique 专用
    edge_sequence: list[Edge] = field(default_factory=list)
    matched_node_sequence: list[str] = field(default_factory=list)
    hop_details: list[dict] = field(default_factory=list)
    # pending 专用
    ambiguity: dict = field(default_factory=dict)
    # infeasible 专用
    infeasible_detail: dict = field(default_factory=dict)


def solve(
    intersections: list[Intersection],
    edges: list[Edge],
    points: list[TrackPoint],
    snap_radius: int,
    max_speed: int,
) -> SolveResult:
    """执行完整求解流程。"""
    n = len(intersections)
    index_of = {node.node_id: i for i, node in enumerate(intersections)}
    radius_sq = Fraction(snap_radius * snap_radius)
    matrix = build_shortest_paths(intersections, edges)

    # 1) 每点候选路口（平方距离 ≤ 半径平方，精确比较）
    candidates_per_point: list[list[PointCandidate]] = []
    for point in points:
        candidates: list[PointCandidate] = []
        for j, node in enumerate(intersections):
            sq = _squared_distance(point.x, point.y, node)
            if sq <= radius_sq:
                candidates.append(PointCandidate(point.index, j, sq))
        candidates_per_point.append(candidates)

    candidate_counts = [len(c) for c in candidates_per_point]

    empty_points = [p.index + 1 for p, c in zip(points, candidates_per_point) if not c]
    if empty_points:
        return SolveResult(
            status="infeasible",
            reason_code="NO_CANDIDATE_WITHIN_RADIUS",
            message=f"第 {', '.join(map(str, empty_points))} 个定位点在吸附半径内没有可匹配的路口",
            point_count=len(points),
            candidate_counts=candidate_counts,
            infeasible_detail={"empty_candidate_point_indexes": [i - 1 for i in empty_points]},
        )

    # 2) 动态规划
    #    dp_cost[t][j]：第 t 个点匹配路口 j 的最小平方距离累计代价
    #    dp_ways[t][j]：达到该最小代价的路口序列条数
    dp_cost: list[list[Fraction | None]] = [[None] * n for _ in points]
    dp_ways: list[list[int]] = [[0] * n for _ in points]
    back: list[list[int | None]] = [[None] * n for _ in points]

    for cand in candidates_per_point[0]:
        dp_cost[0][cand.node_index] = cand.squared_distance
        dp_ways[0][cand.node_index] = 1

    infeasible_hops: list[dict] = []
    for t in range(1, len(points)):
        dt = points[t].timestamp - points[t - 1].timestamp  # 严格递增，故为正
        reach_budget = dt * max_speed
        prev_candidates = candidates_per_point[t - 1]
        reachable_from: dict[int, list[int]] = {}

        for cand in candidates_per_point[t]:
            j = cand.node_index
            best: Fraction | None = None
            best_ways = 0
            best_prev: int | None = None
            valid_predecessors: list[int] = []

            for prev in prev_candidates:
                i = prev.node_index
                hop_len = matrix.dist[i][j]
                if hop_len is None or hop_len > reach_budget:
                    continue
                valid_predecessors.append(i)
                prev_cost = dp_cost[t - 1][i]
                assert prev_cost is not None
                candidate_cost = prev_cost + cand.squared_distance
                if best is None or candidate_cost < best:
                    best = candidate_cost
                    best_ways = dp_ways[t - 1][i]
                    best_prev = i
                elif candidate_cost == best:
                    best_ways += dp_ways[t - 1][i]

            if best is not None:
                dp_cost[t][j] = best
                dp_ways[t][j] = _cap_ways(best_ways)
                back[t][j] = best_prev
                reachable_from[j] = valid_predecessors

        if all(dp_cost[t][c.node_index] is None for c in candidates_per_point[t]):
            # 找出具体是哪些候选对没有满足条件的有向最短路，用于诊断
            blocked: list[dict] = []
            for cand in candidates_per_point[t]:
                j = cand.node_index
                for prev in prev_candidates:
                    i = prev.node_index
                    hop_len = matrix.dist[i][j]
                    if hop_len is None:
                        blocked.append(
                            {
                                "from_node": intersections[i].node_id,
                                "to_node": intersections[j].node_id,
                                "reason": "unreachable",
                            }
                        )
                    elif hop_len > reach_budget:
                        blocked.append(
                            {
                                "from_node": intersections[i].node_id,
                                "to_node": intersections[j].node_id,
                                "reason": "speed_limit",
                                "shortest_length_m": hop_len,
                                "budget_m": reach_budget,
                            }
                        )
            infeasible_hops.append(
                {
                    "point_index": t,
                    "time_delta_s": dt,
                    "budget_m": reach_budget,
                    "blocked_pairs": blocked,
                }
            )
            return SolveResult(
                status="infeasible",
                reason_code="NO_FEASIBLE_DIRECTED_PATH",
                message=(
                    f"第 {t} 个到第 {t + 1} 个定位点之间，所有候选路口对均不存在满足"
                    f"时间差 {dt} 秒、最高速度 {max_speed} 米/秒（里程上限 {reach_budget} 米）的有向最短路"
                ),
                point_count=len(points),
                candidate_counts=candidate_counts,
                infeasible_detail={"hops": infeasible_hops},
            )

    # 3) 终态择优
    terminal = [(j, dp_cost[-1][j], dp_ways[-1][j]) for j in range(n) if dp_cost[-1][j] is not None]
    min_cost = min(cost for _, cost, _ in terminal)
    best_ends = [j for j, cost, _ in terminal if cost == min_cost]
    total_ways = _cap_ways(sum(dp_ways[-1][j] for j in best_ends))

    # 枚举全部最优路口序列（点数 ≤ 8、路口 ≤ 20，规模可控；条数封顶防爆炸）
    optimal_sequences = _enumerate_optimal_sequences(
        points, candidates_per_point, dp_cost, back, min_cost, limit=51
    )

    if total_ways > 1 or len(optimal_sequences) > 1 or len(best_ends) > 1:
        ambiguity = {
            "type": "node_sequence",
            "optimal_node_sequence_count": total_ways,
            "sample_node_sequences": [
                [intersections[j].node_id for j in seq] for seq in optimal_sequences[:50]
            ],
        }
        return SolveResult(
            status="pending",
            reason_code="NON_UNIQUE_NODE_SEQUENCE",
            message=f"最优路口序列不唯一（共 {total_ways} 条达到最小平方距离 {_format_fraction(min_cost)}），结果待人工核验，不导出确定路径",
            point_count=len(points),
            candidate_counts=candidate_counts,
            optimal_node_sequences=[
                [intersections[j].node_id for j in seq] for seq in optimal_sequences[:50]
            ],
            optimal_node_sequence_count=total_ways,
            minimum_cost=min_cost,
            ambiguity=ambiguity,
        )

    # 4) 路口序列唯一：回溯并逐跳检查最短路段序列唯一性
    end = best_ends[0]
    node_idx_sequence = _backtrack(back, len(points) - 1, end)
    node_sequence = [intersections[j].node_id for j in node_idx_sequence]

    edge_sequence: list[Edge] = []
    hop_details: list[dict] = []
    non_unique_hops: list[dict] = []
    for t in range(1, len(points)):
        i, j = node_idx_sequence[t - 1], node_idx_sequence[t]
        hop_len = matrix.dist[i][j]
        assert hop_len is not None
        path_ways = matrix.ways[i][j]
        hop_info = {
            "hop": t,
            "from_node": intersections[i].node_id,
            "to_node": intersections[j].node_id,
            "shortest_length_m": hop_len,
            "shortest_path_count": path_ways,
        }
        if path_ways != 1:
            non_unique_hops.append(hop_info)
        else:
            hop_edges = _reconstruct(matrix, index_of, i, j)
            hop_info["edge_ids"] = [e.edge_id for e in hop_edges]
            edge_sequence.extend(hop_edges)
        hop_details.append(hop_info)

    if non_unique_hops:
        ambiguity = {
            "type": "edge_sequence",
            "matched_node_sequence": node_sequence,
            "non_unique_hops": non_unique_hops,
        }
        return SolveResult(
            status="pending",
            reason_code="NON_UNIQUE_EDGE_SEQUENCE",
            message=(
                "最优路口序列唯一，但路口 "
                + "、".join(f"{h['from_node']}→{h['to_node']}" for h in non_unique_hops)
                + " 之间的最短路段序列不唯一，结果待人工核验，不导出确定路径"
            ),
            point_count=len(points),
            candidate_counts=candidate_counts,
            optimal_node_sequences=[node_sequence],
            optimal_node_sequence_count=1,
            minimum_cost=min_cost,
            ambiguity=ambiguity,
            hop_details=hop_details,
        )

    return SolveResult(
        status="unique",
        reason_code="OK",
        message="求解成功：路口序列与最短路段序列均唯一",
        point_count=len(points),
        candidate_counts=candidate_counts,
        optimal_node_sequences=[node_sequence],
        optimal_node_sequence_count=1,
        minimum_cost=min_cost,
        edge_sequence=edge_sequence,
        matched_node_sequence=node_sequence,
        hop_details=hop_details,
    )


# ---------------------------------------------------------------------------
# 回溯与枚举
# ---------------------------------------------------------------------------
def _backtrack(back: list[list[int | None]], t: int, end: int) -> list[int]:
    sequence = [end]
    cur = end
    while t > 0:
        prev = back[t][cur]
        assert prev is not None
        sequence.append(prev)
        cur = prev
        t -= 1
    sequence.reverse()
    return sequence


def _reconstruct(
    matrix: ShortestPathMatrix, index_of: dict[str, int], src: int, dst: int
) -> list[Edge]:
    """利用外部 ID→索引映射重建唯一最短路上的边序列。"""
    if src == dst:
        return []
    edges: list[Edge] = []
    cur = src
    for _ in range(matrix.n + 1):
        if cur == dst:
            return edges
        edge = matrix.first_edge[cur][dst]
        if edge is None:  # pragma: no cover - 调用方保证可达
            raise RuntimeError("最短路径重建失败")
        edges.append(edge)
        cur = index_of[edge.target_id]
    raise RuntimeError("最短路径重建超出最大步数")  # pragma: no cover


def _enumerate_optimal_sequences(
    points: list[TrackPoint],
    candidates_per_point: list[list[PointCandidate]],
    dp_cost: list[list[Fraction | None]],
    back: list[list[int | None]],
    min_cost: Fraction,
    *,
    limit: int,
) -> list[list[int]]:
    """枚举达到全局最小代价的路口索引序列，最多 ``limit`` 条。

    ``back`` 只记录最优前驱之一，因此这里按 DP 代价关系重新 DFS，
    而非仅沿 back 指针回溯，确保并列最优序列都能被枚举到。
    """
    results: list[list[int]] = []

    def dfs(t: int, node: int, suffix: list[int]) -> None:
        if len(results) >= limit:
            return
        suffix.append(node)
        if t == 0:
            results.append(list(reversed(suffix)))
        else:
            target_cost = dp_cost[t][node]
            assert target_cost is not None
            node_sq = next(
                c.squared_distance for c in candidates_per_point[t] if c.node_index == node
            )
            for prev_cand in candidates_per_point[t - 1]:
                i = prev_cand.node_index
                prev_cost = dp_cost[t - 1][i]
                if prev_cost is None:
                    continue
                if prev_cost + node_sq == target_cost:
                    dfs(t - 1, i, suffix)
                    if len(results) >= limit:
                        break
        suffix.pop()

    last = len(points) - 1
    for cand in candidates_per_point[last]:
        if dp_cost[last][cand.node_index] == min_cost:
            dfs(last, cand.node_index, [])
    return results


def _format_fraction(value: Fraction) -> str:
    """展示用：整数不带小数点，非整数保留 6 位小数并标注精确值。"""
    if value.denominator == 1:
        return str(value.numerator)
    return f"{float(value):.6f}（精确值 {value.numerator}/{value.denominator}）"
