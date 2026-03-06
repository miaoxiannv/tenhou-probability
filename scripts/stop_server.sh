#!/usr/bin/env bash
set -euo pipefail

pkill -f '.venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port 8888' || true
