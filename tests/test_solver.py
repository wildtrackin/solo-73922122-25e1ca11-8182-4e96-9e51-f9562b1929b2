"""求解器核心规则测试。"""

from __future__ import annotations

from fractions import Fraction

from app.solver import build_shortest_paths, solve
from tests.conftest import edge, node, point


def test_unique_solution_returns_edge_sequence(make_node, make_edge):
    intersections = [
        node("A", 0, 0),
        node("B", 100, 0),
        node("C", 200, 0),
        node("X", 50, 80),
    ]
    edges = [
        edge("E1", "A", "B", 100),
        edge("E2", "B", "C", 100),
        edge("E3", "A", "X", 95),
    ]
    points = [point(0, 0, 1, 0), point(1, 10, 99, 1), point(2, 20, 202, 0)]

    result = solve(intersections, edges, points, snap_radius=10, max_speed=15)

    assert result.status == "unique"
    assert result.matched_node_sequence == ["A", "B", "C"]
    assert [e.edge_id for e in result.edge_sequence] == ["E1", "E2"]
    # 平方距离：1 + 2 + 4 = 7
    assert result.minimum_cost == Fraction(7)
    assert result.hop_details[0]["edge_ids"] == ["E1"]
    assert result.hop_details[1]["edge_ids"] == ["E2"]


def test_radius_boundary_uses_exact_squared_distance():
    # 点 (3,4) 到 A(0,0) 距离恰好为 5，半径 5 必须包含（精确比较，无浮点误差）
    intersections = [node("A", 0, 0), node("B", 10, 0)]
    edges = [edge("E1", "A", "B", 10)]
    points = [point(0, 0, 3, 4), point(1, 1, 10, 0)]

    ok = solve(intersections, edges, points, snap_radius=5, max_speed=20)
    assert ok.status == "unique"
    assert ok.matched_node_sequence == ["A", "B"]

    tight = solve(intersections, edges, points, snap_radius=4, max_speed=20)
    assert tight.status == "infeasible"
    assert tight.reason_code == "NO_CANDIDATE_WITHIN_RADIUS"
    assert tight.infeasible_detail["empty_candidate_point_indexes"] == [0]


def test_same_node_hop_zero_edges_is_feasible(make_node, make_edge):
    # 两个定位点都吸附到同一个路口 A：零条路段、零里程，速度约束天然满足
    intersections = [node("A", 0, 0)]
    points = [point(0, 0, 1, 1), point(1, 5, 1, -1)]

    result = solve(intersections, [], points, snap_radius=5, max_speed=1)

    assert result.status == "unique"
    assert result.matched_node_sequence == ["A", "A"]
    assert result.edge_sequence == []
    assert result.hop_details[0]["shortest_length_m"] == 0
    assert result.hop_details[0]["shortest_path_count"] == 1


def test_speed_limit_violation_is_infeasible(make_node, make_edge):
    intersections = [node("A", 0, 0), node("B", 100, 0)]
    edges = [edge("E1", "A", "B", 100)]
    points = [point(0, 0, 0, 0), point(1, 5, 100, 0)]  # 时间差 5 秒，上限 75 米

    result = solve(intersections, edges, points, snap_radius=5, max_speed=15)

    assert result.status == "infeasible"
    assert result.reason_code == "NO_FEASIBLE_DIRECTED_PATH"
    blocked = result.infeasible_detail["hops"][0]["blocked_pairs"][0]
    assert blocked == {
        "from_node": "A",
        "to_node": "B",
        "reason": "speed_limit",
        "shortest_length_m": 100,
        "budget_m": 75,
    }


def test_directed_unreachable_is_infeasible(make_node, make_edge):
    intersections = [node("A", 0, 0), node("B", 100, 0)]
    edges = [edge("E1", "B", "A", 100)]  # 只有 B→A，需求方向 A→B 不可达
    points = [point(0, 0, 0, 0), point(1, 10, 100, 0)]

    result = solve(intersections, edges, points, snap_radius=5, max_speed=100)

    assert result.status == "infeasible"
    assert result.reason_code == "NO_FEASIBLE_DIRECTED_PATH"
    assert result.infeasible_detail["hops"][0]["blocked_pairs"][0]["reason"] == "unreachable"


def test_tied_node_sequences_is_pending_without_export(make_node, make_edge):
    # 中间定位点 (100,15) 到 B(100,0)、C(100,30) 等距（均为 15 米），
    # A、D 距离约 101 米落在半径 20 之外，形成干净的双序列并列
    intersections = [
        node("A", 0, 0),
        node("B", 100, 0),
        node("C", 100, 30),
        node("D", 200, 0),
    ]
    edges = [
        edge("AB", "A", "B", 100),
        edge("AC", "A", "C", 110),
        edge("BD", "B", "D", 100),
        edge("CD", "C", "D", 110),
    ]
    points = [point(0, 0, 2, 0), point(1, 10, 100, 15), point(2, 20, 198, 0)]

    result = solve(intersections, edges, points, snap_radius=20, max_speed=25)

    assert result.status == "pending"
    assert result.reason_code == "NON_UNIQUE_NODE_SEQUENCE"
    assert result.optimal_node_sequence_count == 2
    sequences = {tuple(seq) for seq in result.optimal_node_sequences}
    assert sequences == {("A", "B", "D"), ("A", "C", "D")}
    assert result.edge_sequence == []  # 待核不产生确定路径


def test_multiple_shortest_edge_sequences_is_pending(diamond_graph):
    intersections, edges = diamond_graph
    # 三点分别只靠近 A、D、D，路口序列唯一为 A→D→D
    points = [point(0, 0, 2, 2), point(1, 10, 98, 98), point(2, 20, 99, 99)]

    result = solve(intersections, edges, points, snap_radius=10, max_speed=50)

    assert result.status == "pending"
    assert result.reason_code == "NON_UNIQUE_EDGE_SEQUENCE"
    assert result.ambiguity["non_unique_hops"][0]["from_node"] == "A"
    assert result.ambiguity["non_unique_hops"][0]["to_node"] == "D"
    assert result.ambiguity["non_unique_hops"][0]["shortest_path_count"] == 2
    assert result.edge_sequence == []


def test_parallel_equal_edges_count_as_multiple_paths(make_node, make_edge):
    intersections = [node("A", 0, 0), node("B", 100, 0)]
    edges = [edge("E1", "A", "B", 100), edge("E2", "A", "B", 100)]
    points = [point(0, 0, 0, 0), point(1, 10, 100, 0)]

    result = solve(intersections, edges, points, snap_radius=5, max_speed=20)

    assert result.status == "pending"
    assert result.reason_code == "NON_UNIQUE_EDGE_SEQUENCE"
    assert result.ambiguity["non_unique_hops"][0]["shortest_path_count"] == 2


def test_parallel_edges_shorter_one_is_unique(make_node, make_edge):
    intersections = [node("A", 0, 0), node("B", 100, 0)]
    edges = [edge("E1", "A", "B", 100), edge("E2", "A", "B", 120)]
    points = [point(0, 0, 0, 0), point(1, 10, 100, 0)]

    result = solve(intersections, edges, points, snap_radius=5, max_speed=20)

    assert result.status == "unique"
    assert [e.edge_id for e in result.edge_sequence] == ["E1"]


def test_dp_picks_minimum_squared_distance_cost(make_node, make_edge):
    # 点 1 同时在 A、B 半径内，但选 B 的累计平方距离更小
    intersections = [node("A", 0, 0), node("B", 10, 0)]
    edges = [edge("E1", "A", "B", 10)]
    points = [point(0, 0, 0, 0), point(1, 1, 9, 0)]

    result = solve(intersections, edges, points, snap_radius=10, max_speed=20)

    assert result.status == "unique"
    assert result.matched_node_sequence == ["A", "B"]
    assert result.minimum_cost == Fraction(1)  # 选 A 代价为 81，选 B 为 1


def test_multi_hop_shortest_path_reconstruction(make_node, make_edge):
    intersections = [node("A", 0, 0), node("B", 10, 0), node("C", 20, 0)]
    edges = [edge("E1", "A", "B", 10), edge("E2", "B", "C", 10)]
    points = [point(0, 0, 0, 0), point(1, 5, 20, 0)]

    result = solve(intersections, edges, points, snap_radius=2, max_speed=10)

    assert result.status == "unique"
    assert [e.edge_id for e in result.edge_sequence] == ["E1", "E2"]
    assert result.hop_details[0]["shortest_length_m"] == 20


def test_longer_direct_edge_vs_two_edge_shortest_path(make_node, make_edge):
    # A→C 直连 50 米；A→B→C 合计 30 米，最短路应为两跳序列
    intersections = [node("A", 0, 0), node("B", 5, 0), node("C", 10, 0)]
    edges = [
        edge("DIR", "A", "C", 50),
        edge("E1", "A", "B", 15),
        edge("E2", "B", "C", 15),
    ]
    points = [point(0, 0, 0, 0), point(1, 10, 10, 0)]

    result = solve(intersections, edges, points, snap_radius=2, max_speed=5)

    assert result.status == "unique"
    assert [e.edge_id for e in result.edge_sequence] == ["E1", "E2"]
    assert result.hop_details[0]["shortest_length_m"] == 30


def test_floyd_ways_matrix_basic_counts(diamond_graph):
    intersections, edges = diamond_graph
    matrix = build_shortest_paths(intersections, edges)
    idx = {n.node_id: i for i, n in enumerate(intersections)}

    assert matrix.dist[idx["A"]][idx["D"]] == 200
    assert matrix.ways[idx["A"]][idx["D"]] == 2
    assert matrix.dist[idx["A"]][idx["A"]] == 0
    assert matrix.ways[idx["A"]][idx["A"]] == 1
    assert matrix.dist[idx["B"]][idx["A"]] is None
    assert matrix.ways[idx["B"]][idx["A"]] == 0


def test_zero_radius_requires_exact_coordinate_match(make_node, make_edge):
    intersections = [node("A", 1.5, 2.25), node("B", 10, 0)]
    edges = [edge("E1", "A", "B", 20)]
    points = [point(0, 0, 1.5, 2.25), point(1, 1, 10, 0)]

    result = solve(intersections, edges, points, snap_radius=0, max_speed=30)
    assert result.status == "unique"

    miss = solve(
        [node("A", 1.5, 2.25), node("B", 10, 0)],
        edges,
        [point(0, 0, 1.5, 2.26), point(1, 1, 10, 0)],
        snap_radius=0,
        max_speed=30,
    )
    assert miss.status == "infeasible"
    assert miss.reason_code == "NO_CANDIDATE_WITHIN_RADIUS"


def test_eight_points_full_limit_supported(make_node, make_edge):
    intersections = [node("A", 0, 0), node("B", 10, 0)]
    edges = [edge("E1", "A", "B", 10), edge("E2", "B", "A", 10)]
    points = []
    for i in range(8):
        ts = i * 2
        points.append(point(i, ts, 10 if i % 2 else 0, 0))

    result = solve(intersections, edges, points, snap_radius=0, max_speed=10)
    assert result.status == "unique"
    assert result.point_count == 8
    assert [e.edge_id for e in result.edge_sequence] == ["E1", "E2", "E1", "E2", "E1", "E2", "E1"]
