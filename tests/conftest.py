"""pytest 共享夹具。"""

from __future__ import annotations

import pytest

from app.models import Edge, Intersection, TrackPoint
from fractions import Fraction


def node(node_id: str, x: int | float | str = 0, y: int | float | str = 0) -> Intersection:
    fx, fy = Fraction(x), Fraction(y)
    return Intersection(node_id, fx, fy, str(x), str(y))


def edge(edge_id: str, src: str, dst: str, length: int) -> Edge:
    return Edge(edge_id, src, dst, length)


def point(index: int, ts: int, x: int | float | str = 0, y: int | float | str = 0) -> TrackPoint:
    return TrackPoint(index, ts, Fraction(x), Fraction(y), str(x), str(y))


@pytest.fixture
def make_node():
    return node


@pytest.fixture
def make_edge():
    return edge


@pytest.fixture
def make_point():
    return point


@pytest.fixture
def diamond_graph():
    """A→B→D 与 A→C→D 两条等长最短路的菱形有向图。

    坐标（米）：A(0,0) B(0,100) C(100,0) D(100,100)
    """
    intersections = [
        node("A", 0, 0),
        node("B", 0, 100),
        node("C", 100, 0),
        node("D", 100, 100),
    ]
    edges = [
        edge("AB", "A", "B", 100),
        edge("AC", "A", "C", 100),
        edge("BD", "B", "D", 100),
        edge("CD", "C", "D", 100),
    ]
    return intersections, edges
