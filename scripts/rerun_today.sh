#!/usr/bin/env bash
# Daily Brief Pipeline - Rerun/Resume Mode
# P0-6: 用於重跑當天失敗的文章，從 checkpoint 繼續
# 不會重新執行 ingest/pack，只會重新生成失敗的文章
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
export GHOST_SEND_ALL_NEWSLETTERS="${GHOST_SEND_ALL_NEWSLETTERS:-false}"
export GHOST_POST_VISIBILITY="${GHOST_POST_VISIBILITY:-members}"
export OPENAI_VERIFY_SSL="${OPENAI_VERIFY_SSL:-false}"
# P0-5: 使用較長的 timeout 來避免長文截斷
export LITELLM_TIMEOUT="${LITELLM_TIMEOUT:-300}"

LOG_DIR="${ROOT_DIR}/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="${LOG_DIR}/rerun_$(date +%F_%H%M%S).log"

# 檢查 checkpoint 是否存在
CHECKPOINT_FILE="${ROOT_DIR}/out/checkpoint.json"
if [ ! -f "$CHECKPOINT_FILE" ]; then
  echo "$(date): No checkpoint found. Running fresh pipeline instead." | tee -a "$LOG_FILE"
  python3 -m src.pipeline.run_daily --mode prod --confirm-high-risk >> "$LOG_FILE" 2>&1
else
  echo "$(date): Starting Daily Brief Pipeline (RESUME mode from checkpoint)" | tee -a "$LOG_FILE"
  echo "$(date): Checkpoint: $(cat "$CHECKPOINT_FILE" | head -5)" | tee -a "$LOG_FILE"
  # P0-6: 使用 --resume 從 checkpoint 繼續，只重跑失敗的部分
  python3 -m src.pipeline.run_daily --mode prod --confirm-high-risk --resume >> "$LOG_FILE" 2>&1
fi

echo "$(date): Pipeline completed" | tee -a "$LOG_FILE"
