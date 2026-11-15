"""CSV 解析与输入校验测试。"""

from __future__ import annotations

import pytest

from app.parsing import (
    AppError,
    MAX_EDGES,
    MAX_INTERSECTIONS,
    MAX_POINTS,
    MIN_POINTS,
    parse_edges,
    parse_intersections,
    parse_parameters,
    parse_track,
)

INTERSECTION_CSV = """intersection_id,x,y
A,0,0
B,100,0.5
"""

EDGE_CSV = """edge_id,from_intersection_id,to_intersection_id,length_m
E1,A,B,100
"""


def b(text: str) -> bytes:
    return text.encode("utf-8")


def test_parse_intersections_ok():
    nodes = parse_intersections(b(INTERSECTION_CSV))
    assert [n.node_id for n in nodes] == ["A", "B"]
    assert nodes[1].y == __import__("fractions").Fraction(1, 2)


def test_utf8_bom_is_accepted():
    nodes = parse_intersections(("﻿" + INTERSECTION_CSV).encode("utf-8"))
    assert nodes[0].node_id == "A"


def test_non_utf8_is_rejected():
    with pytest.raises(AppError) as exc:
        parse_intersections("intersection_id,x,y\nA,0,0\n".encode("utf-16"))
    assert exc.value.code == "ENCODING_ERROR"


def test_bad_header_rejected():
    with pytest.raises(AppError) as exc:
        parse_intersections(b("id,x,y\nA,0,0\n"))
    assert exc.value.code == "BAD_HEADER"


def test_column_count_mismatch_rejected():
    with pytest.raises(AppError) as exc:
        parse_intersections(b("intersection_id,x,y\nA,0\n"))
    assert exc.value.code == "BAD_COLUMN_COUNT"


def test_empty_cell_rejected():
    with pytest.raises(AppError) as exc:
        parse_intersections(b("intersection_id,x,y\nA,,0\n"))
    assert exc.value.code == "EMPTY_CELL"


def test_duplicate_intersection_id_rejected():
    with pytest.raises(AppError) as exc:
        parse_intersections(b("intersection_id,x,y\nA,0,0\nA,1,1\n"))
    assert exc.value.code == "DUPLICATE_ID"


def test_invalid_decimal_rejected():
    with pytest.raises(AppError) as exc:
        parse_intersections(b("intersection_id,x,y\nA,abc,0\n"))
    assert exc.value.code == "INVALID_NUMBER"


def test_intersection_count_limits():
    csv_text = "intersection_id,x,y\n" + "".join(f"N{i},0,0\n" for i in range(MAX_INTERSECTIONS + 1))
    with pytest.raises(AppError) as exc:
        parse_intersections(b(csv_text))
    assert exc.value.code == "COUNT_LIMIT"

    with pytest.raises(AppError) as exc:
        parse_intersections(b("intersection_id,x,y\n"))
    assert exc.value.code == "COUNT_LIMIT"


def test_empty_file_rejected():
    with pytest.raises(AppError) as exc:
        parse_intersections(b(""))
    assert exc.value.code == "EMPTY_FILE"


def test_edge_validation_ok_and_limits():
    edges = parse_edges(b(EDGE_CSV), {"A", "B"})
    assert edges[0].edge_id == "E1"
    assert edges[0].length == 100

    over = "edge_id,from_intersection_id,to_intersection_id,length_m\n" + "".join(
        f"E{i},A,B,1\n" for i in range(MAX_EDGES + 1)
    )
    with pytest.raises(AppError) as exc:
        parse_edges(b(over), {"A", "B"})
    assert exc.value.code == "COUNT_LIMIT"


def test_edge_unknown_endpoint_rejected():
    with pytest.raises(AppError) as exc:
        parse_edges(b("edge_id,from_intersection_id,to_intersection_id,length_m\nE1,A,Z,10\n"), {"A"})
    assert exc.value.code == "UNKNOWN_NODE"


def test_edge_length_must_be_positive_integer():
    base = "edge_id,from_intersection_id,to_intersection_id,length_m\n"
    with pytest.raises(AppError) as exc:
        parse_edges(b(base + "E1,A,B,0\n"), {"A", "B"})
    assert exc.value.code == "INTEGER_OUT_OF_RANGE"

    with pytest.raises(AppError) as exc:
        parse_edges(b(base + "E1,A,B,1.5\n"), {"A", "B"})
    assert exc.value.code == "INVALID_INTEGER"


def test_duplicate_edge_id_rejected():
    csv_text = (
        "edge_id,from_intersection_id,to_intersection_id,length_m\n"
        "E1,A,B,10\nE1,A,B,20\n"
    )
    with pytest.raises(AppError) as exc:
        parse_edges(b(csv_text), {"A", "B"})
    assert exc.value.code == "DUPLICATE_ID"


def test_track_count_and_timestamp_rules():
    good = "timestamp_utc,x,y\n0,0,0\n10,1,1\n"
    points = parse_track(b(good))
    assert len(points) == MIN_POINTS
    assert points[1].timestamp == 10

    too_few = b("timestamp_utc,x,y\n0,0,0\n")
    with pytest.raises(AppError) as exc:
        parse_track(too_few)
    assert exc.value.code == "COUNT_LIMIT"

    many = "timestamp_utc,x,y\n" + "".join(f"{i},0,0\n" for i in range(MAX_POINTS + 1))
    with pytest.raises(AppError) as exc:
        parse_track(b(many))
    assert exc.value.code == "COUNT_LIMIT"

    not_increasing = b("timestamp_utc,x,y\n0,0,0\n5,1,1\n5,2,2\n")
    with pytest.raises(AppError) as exc:
        parse_track(not_increasing)
    assert exc.value.code == "TIMESTAMP_NOT_STRICTLY_INCREASING"

    decreasing = b("timestamp_utc,x,y\n10,0,0\n5,1,1\n")
    with pytest.raises(AppError) as exc:
        parse_track(decreasing)
    assert exc.value.code == "TIMESTAMP_NOT_STRICTLY_INCREASING"


def test_track_negative_timestamp_allowed_but_integer_only():
    points = parse_track(b("timestamp_utc,x,y\n-10,0,0\n-5,1,1\n"))
    assert points[0].timestamp == -10

    with pytest.raises(AppError) as exc:
        parse_track(b("timestamp_utc,x,y\n0.5,0,0\n1,1,1\n"))
    assert exc.value.code == "INVALID_INTEGER"


def test_parameter_parsing():
    assert parse_parameters("0", "1") == (0, 1)
    assert parse_parameters("20", "15") == (20, 15)

    with pytest.raises(AppError) as exc:
        parse_parameters("-1", "15")
    assert exc.value.code == "INTEGER_OUT_OF_RANGE"

    with pytest.raises(AppError) as exc:
        parse_parameters("5", "0")
    assert exc.value.code == "INTEGER_OUT_OF_RANGE"

    with pytest.raises(AppError) as exc:
        parse_parameters(None, "15")
    assert exc.value.code == "MISSING_PARAMETER"

    with pytest.raises(AppError) as exc:
        parse_parameters("1.5", "15")
    assert exc.value.code == "INVALID_INTEGER"


def test_blank_lines_are_ignored_but_data_rows_validated():
    csv_text = "intersection_id,x,y\nA,0,0\n\nB,1,1\n"
    nodes = parse_intersections(b(csv_text))
    assert [n.node_id for n in nodes] == ["A", "B"]
