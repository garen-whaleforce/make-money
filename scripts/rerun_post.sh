#!/usr/bin/env bash
# Daily Brief Pipeline - Rerun Single Post
# P0-6: 只重跑指定的單篇文章（flash/earnings/deep）
#
# Usage:
#   ./scripts/rerun_post.sh flash      # 只重跑 flash
#   ./scripts/rerun_post.sh deep       # 只重跑 deep dive
#   ./scripts/rerun_post.sh earnings   # 只重跑 earnings
set -euo pipefail

POST_TYPE="${1:-}"

if [ -z "$POST_TYPE" ]; then
  echo "Usage: $0 <post_type>"
  echo "  post_type: flash, earnings, or deep"
  exit 1
fi

# Validate post type
case "$POST_TYPE" in
  flash|earnings|deep)
    ;;
  *)
    echo "Invalid post type: $POST_TYPE"
    echo "  Valid options: flash, earnings, deep"
    exit 1
    ;;
esac

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
export GHOST_SEND_ALL_NEWSLETTERS="false"  # 單篇重跑不發 newsletter
export GHOST_POST_VISIBILITY="${GHOST_POST_VISIBILITY:-members}"
export OPENAI_VERIFY_SSL="${OPENAI_VERIFY_SSL:-false}"
export LITELLM_TIMEOUT="${LITELLM_TIMEOUT:-300}"

LOG_DIR="${ROOT_DIR}/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="${LOG_DIR}/rerun_${POST_TYPE}_$(date +%F_%H%M%S).log"

echo "$(date): Starting single post rerun: $POST_TYPE" | tee -a "$LOG_FILE"

# P0-6: 使用 --resume --posts 來只重跑指定的文章
python3 -m src.pipeline.run_daily --mode prod --confirm-high-risk --resume --posts "$POST_TYPE" >> "$LOG_FILE" 2>&1

echo "$(date): Rerun completed for: $POST_TYPE" | tee -a "$LOG_FILE"
