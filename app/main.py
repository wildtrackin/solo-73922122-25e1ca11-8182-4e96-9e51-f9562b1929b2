"""FastAPI 入口：网页、求解接口与结果下载接口。"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .parsing import AppError
from .service import RESULT_STORE, run_solve, serialize_result, store_result

MAX_UPLOAD_BYTES = 2 * 1024 * 1024  # 单个 CSV 上限 2 MB

WEB_DIR = Path(__file__).resolve().parent / "web"

app = FastAPI(
    title="巡检定位转路段序列服务",
    description="上传路口、单向路段、巡检定位三份 UTF-8 CSV，求解唯一路段通行序列。",
    version="1.0.0",
)
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


@app.exception_handler(AppError)
async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={"status": "error", "reason_code": exc.code, "message": exc.message},
    )


async def _read_limited(upload: UploadFile | None, label: str) -> bytes | None:
    if upload is None:
        return None
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(65536)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_UPLOAD_BYTES:
            raise AppError("FILE_TOO_LARGE", f"{label}超过 {MAX_UPLOAD_BYTES // 1024 // 1024} MB 上限")
        chunks.append(chunk)
    return b"".join(chunks)


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.post("/api/solve")
async def solve_endpoint(
    intersections: UploadFile | None = File(default=None),
    edges: UploadFile | None = File(default=None),
    track: UploadFile | None = File(default=None),
    snap_radius: str | None = Form(default=None),
    max_speed: str | None = Form(default=None),
) -> JSONResponse:
    """接收三份 CSV 与两个参数，返回求解结果。"""
    intersections_raw = await _read_limited(intersections, "路口文件")
    edges_raw = await _read_limited(edges, "路段文件")
    track_raw = await _read_limited(track, "定位文件")

    result = run_solve(intersections_raw, edges_raw, track_raw, snap_radius, max_speed)
    token = store_result(result)
    return JSONResponse(content=serialize_result(result, token))


@app.get("/api/results/{token}/download")
async def download_endpoint(token: str) -> Response:
    """下载唯一解对应的路段 ID CSV；待核/不可行结果不存在下载入口。"""
    if len(token) != 32 or not all(ch in "0123456789abcdef" for ch in token):
        raise AppError("RESULT_NOT_FOUND", "结果不存在或已过期，请重新求解")
    stored = RESULT_STORE.get(token)
    if stored is None:
        raise AppError("RESULT_NOT_FOUND", "结果不存在或已过期（结果保留 1 小时），请重新求解")

    filename = stored.export_filename
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return Response(
        content=stored.export_content,
        media_type="text/csv; charset=utf-8",
        headers=headers,
    )


@app.get("/healthz", include_in_schema=False)
async def healthz() -> dict:
    return {"status": "ok"}
