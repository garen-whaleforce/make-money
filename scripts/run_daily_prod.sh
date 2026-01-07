#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [ -f ".env" ]; then
  set -a
  # shellcheck disable=SC1091
  . ".env"
  set +a
fi

if [ -n "${VENV_PATH:-}" ] && [ -f "${VENV_PATH}/bin/activate" ]; then
  # shellcheck disable=SC1091
  . "${VENV_PATH}/bin/activate"
elif [ -f ".venv/bin/activate" ]; then
  # shellcheck disable=SC1091
  . ".venv/bin/activate"
fi

export PYTHONUNBUFFERED=1
export TZ="${TZ:-Asia/Taipei}"
export GHOST_SEND_ALL_NEWSLETTERS="${GHOST_SEND_ALL_NEWSLETTERS:-true}"
export GHOST_POST_VISIBILITY="${GHOST_POST_VISIBILITY:-members}"
export OPENAI_VERIFY_SSL="${OPENAI_VERIFY_SSL:-false}"

LOG_DIR="${ROOT_DIR}/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="${LOG_DIR}/daily_$(date +%F_%H%M%S).log"

python3 -m src.pipeline.run_daily --mode prod --confirm-high-risk >> "$LOG_FILE" 2>&1
