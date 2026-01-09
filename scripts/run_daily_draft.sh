#!/usr/bin/env bash
# Daily Brief Pipeline - Draft Mode
# 自動生成文章並發布為 Ghost draft，等待人工審核後發布
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
# Draft mode: 不發送 newsletter，發布為 draft
export GHOST_SEND_ALL_NEWSLETTERS="false"
export GHOST_POST_VISIBILITY="members"
export GHOST_POST_STATUS="draft"
export OPENAI_VERIFY_SSL="${OPENAI_VERIFY_SSL:-false}"
export LITELLM_TIMEOUT="${LITELLM_TIMEOUT:-180}"

LOG_DIR="${ROOT_DIR}/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="${LOG_DIR}/daily_$(date +%F_%H%M%S).log"

echo "$(date): Starting Daily Brief Pipeline (draft mode)" | tee -a "$LOG_FILE"
python3 -m src.pipeline.run_daily --mode prod --confirm-high-risk >> "$LOG_FILE" 2>&1
echo "$(date): Pipeline completed" | tee -a "$LOG_FILE"
