#!/usr/bin/env bash
# 本地开发便捷脚本：启动 uvicorn（需要先创建 .venv 并安装 requirements.txt）
set -euo pipefail
cd "$(dirname "$0")/.."
exec .venv/bin/python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
