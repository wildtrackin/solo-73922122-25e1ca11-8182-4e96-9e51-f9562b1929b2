"""FastAPI HTTP 接口端到端测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

SAMPLE_DIR = Path(__file__).resolve().parent.parent / "app" / "web" / "samples"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _form(client_files: dict, radius: str = "20", speed: str = "15"):
    files = {}
    for key, (name, path) in client_files.items():
        content = path if isinstance(path, bytes) else Path(path).read_bytes()
        files[key] = (name, content, "text/csv")
    data = {"snap_radius": radius, "max_speed": speed}
    return files, data


def _sample_files():
    return {
        "intersections": ("intersections.csv", SAMPLE_DIR / "intersections.csv"),
        "edges": ("edges.csv", SAMPLE_DIR / "edges.csv"),
        "track": ("track.csv", SAMPLE_DIR / "track.csv"),
    }


def test_healthz(client):
    res = client.get("/healthz")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_index_page_served(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    assert "巡检定位" in res.text


def test_sample_problem_is_unique_and_downloadable(client):
    files, data = _form(_sample_files())
    res = client.post("/api/solve", files=files, data=data)
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "unique"
    assert body["matched_node_sequence"] == ["A", "B", "C"]
    assert [e["edge_id"] for e in body["edge_sequence"]] == ["E1", "E2"]
    assert body["minimum_squared_distance_sum"]["is_integer"] is True

    download_url = body["download_url"]
    dl = client.get(download_url)
    assert dl.status_code == 200
    assert "attachment" in dl.headers["content-disposition"]
    assert "text/csv" in dl.headers["content-type"]
    content = dl.content.decode("utf-8")
    lines = content.strip().splitlines()
    assert lines[0] == "sequence_no,edge_id,from_intersection_id,to_intersection_id,length_m"
    assert lines[1].split(",")[1] == "E1"
    assert lines[2].split(",")[1] == "E2"


def test_invalid_input_returns_400_and_no_result_file(client):
    bad_files = {
        "intersections": ("intersections.csv", b"intersection_id,x,y\nA,0,0\nA,1,1\n"),
        "edges": ("edges.csv", Path(SAMPLE_DIR / "edges.csv").read_bytes()),
        "track": ("track.csv", Path(SAMPLE_DIR / "track.csv").read_bytes()),
    }
    files, data = _form(bad_files)
    res = client.post("/api/solve", files=files, data=data)
    assert res.status_code == 400
    body = res.json()
    assert body["status"] == "error"
    assert body["reason_code"] == "DUPLICATE_ID"


def test_missing_file_returns_400(client):
    files, data = _form(
        {
            "edges": ("edges.csv", Path(SAMPLE_DIR / "edges.csv").read_bytes()),
            "track": ("track.csv", Path(SAMPLE_DIR / "track.csv").read_bytes()),
        }
    )
    res = client.post("/api/solve", files=files, data=data)
    assert res.status_code == 400
    assert res.json()["reason_code"] == "MISSING_FILE"


def test_infeasible_problem_returns_200_with_status_infeasible(client):
    files, data = _form(_sample_files(), radius="20", speed="1")  # 1 米/秒远不够
    res = client.post("/api/solve", files=files, data=data)
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "infeasible"
    assert "download_url" not in body


def test_pending_result_has_no_download(client, tmp_path):
    intersections = b"intersection_id,x,y\nA,0,0\nB,100,0\nC,100,30\nD,200,0\n"
    edges = (
        b"edge_id,from_intersection_id,to_intersection_id,length_m\n"
        b"AB,A,B,100\nAC,A,C,110\nBD,B,D,100\nCD,C,D,110\n"
    )
    track = b"timestamp_utc,x,y\n0,2,0\n10,100,15\n20,198,0\n"
    files = {
        "intersections": ("i.csv", intersections),
        "edges": ("e.csv", edges),
        "track": ("t.csv", track),
    }
    res = client.post("/api/solve", files=files, data={"snap_radius": "20", "max_speed": "25"})
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "pending"
    assert body["optimal_node_sequence_count"] == 2
    assert "download_url" not in body


def test_download_unknown_token_400(client):
    res = client.get("/api/results/00000000000000000000000000000000/download")
    assert res.status_code == 400
    assert res.json()["reason_code"] == "RESULT_NOT_FOUND"


def test_download_malformed_token_400(client):
    res = client.get("/api/results/zzz/download")
    assert res.status_code == 400
    assert res.json()["reason_code"] == "RESULT_NOT_FOUND"


def test_bad_parameter_returns_400(client):
    files, _ = _form(_sample_files())
    res = client.post("/api/solve", files=files, data={"snap_radius": "-3", "max_speed": "15"})
    assert res.status_code == 400
    assert res.json()["reason_code"] == "INTEGER_OUT_OF_RANGE"

    files, _ = _form(_sample_files())
    res = client.post("/api/solve", files=files, data={"snap_radius": "5", "max_speed": "0"})
    assert res.status_code == 400
    assert res.json()["reason_code"] == "INTEGER_OUT_OF_RANGE"


def test_missing_form_field_returns_400_chinese_error(client):
    files, _ = _form(_sample_files())
    res = client.post("/api/solve", files=files, data={"snap_radius": "20"})
    assert res.status_code == 400
    body = res.json()
    assert body["status"] == "error"
    assert body["reason_code"] == "MISSING_PARAMETER"


def test_non_utf8_file_returns_400(client):
    files, data = _form(
        {
            "intersections": ("i.csv", "intersection_id,x,y\nA,0,0\n".encode("utf-16")),
            "edges": ("e.csv", Path(SAMPLE_DIR / "edges.csv").read_bytes()),
            "track": ("t.csv", Path(SAMPLE_DIR / "track.csv").read_bytes()),
        }
    )
    res = client.post("/api/solve", files=files, data=data)
    assert res.status_code == 400
    assert res.json()["reason_code"] == "ENCODING_ERROR"
