#!/usr/bin/env bash
set -euo pipefail

ROOT="/home/zhang/tenhou-probability"
cd "$ROOT"

if [[ -f ".env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source ".env"
  set +a
fi

if [[ -z "${OPENAI_API_KEY:-}" && -n "${SUB2API_API_KEY:-}" ]]; then
  export OPENAI_API_KEY="${SUB2API_API_KEY}"
fi

if [[ -z "${OPENAI_API_KEY:-}" ]]; then
  echo "WARN: neither OPENAI_API_KEY nor SUB2API_API_KEY is set. LLM calls may fall back to rule-based behavior." >&2
fi

export SUB2API_BASE_URL="${SUB2API_BASE_URL:-http://sub2api.chenlabs.online}"
export MODEL_NAME="${MODEL_NAME:-gpt-5.3-codex}"
export REVIEW_MODEL_NAME="${REVIEW_MODEL_NAME:-gpt-5.3-codex}"
export MODEL_REASONING_EFFORT="${MODEL_REASONING_EFFORT:-xhigh}"
export DISABLE_RESPONSE_STORAGE="${DISABLE_RESPONSE_STORAGE:-true}"
export MODEL_NETWORK_ACCESS="${MODEL_NETWORK_ACCESS:-enabled}"
export ENABLE_LEGACY_BACKEND_RENDER="${ENABLE_LEGACY_BACKEND_RENDER:-false}"
export MPLCONFIGDIR="${MPLCONFIGDIR:-/tmp/mplconfig}"

exec ./.venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port 8888
