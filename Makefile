# Daily Deep Brief - Makefile
# ============================

.PHONY: help install dev test test-unit test-replay test-integration lint format clean dry-run run publish metrics

# 預設目標
help:
	@echo "Daily Deep Brief - Available Commands"
	@echo ""
	@echo "Setup:"
	@echo "  make install        - Install production dependencies"
	@echo "  make dev            - Install development dependencies"
	@echo ""
	@echo "Testing:"
	@echo "  make test           - Run all tests"
	@echo "  make test-unit      - Run unit tests only"
	@echo "  make test-replay    - Run replay tests (no API calls)"
	@echo "  make test-integration - Run integration tests"
	@echo "  make coverage       - Run tests with coverage report"
	@echo ""
	@echo "Code Quality:"
	@echo "  make lint           - Run linters (ruff)"
	@echo "  make format         - Format code (black + isort)"
	@echo "  make typecheck      - Run type checker (pyright)"
	@echo ""
	@echo "Running:"
	@echo "  make dry-run        - Dry run (no publish)"
	@echo "  make run            - Full run (draft mode)"
	@echo "  make publish        - Full run (publish mode)"
	@echo ""
	@echo "Ghost CMS (三段式安全發佈):"
	@echo "  make ghost-draft    - Step 1: 建立 Draft (最安全)"
	@echo "  make ghost-publish  - Step 2: 發佈但不寄信"
	@echo "  make ghost-send     - Step 3: 發佈並寄 Newsletter (需 allowlist)"
	@echo "  make ghost-smoke-test - 執行 Ghost 連線測試"
	@echo ""
	@echo "Post Enhancement (第二次編輯增強):"
	@echo "  make enhance        - 增強初稿 (使用 LiteLLM)"
	@echo "  make enhance-test   - 測試品質閘門（不呼叫 LLM）"
	@echo "  make enhance-draft  - 增強後建立 Draft"
	@echo "  make enhance-send-internal - 增強後發到內部測試"
	@echo "  make enhance-send   - 增強後發佈並寄信（需確認）"
	@echo ""
	@echo "Utilities:"
	@echo "  make metrics        - Generate metrics rollup"
	@echo "  make fixtures       - Create sample fixtures"
	@echo "  make clean          - Clean generated files"
	@echo ""

# ============================
# Setup
# ============================

install:
	pip install -e .

dev:
	pip install -e ".[dev]"

# ============================
# Testing
# ============================

test:
	pytest tests/ -v --tb=short

test-unit:
	pytest tests/unit tests/test_*.py -v --tb=short

test-replay:
	pytest tests/replay/ -v --tb=short

test-integration:
	pytest tests/integration/ -v --tb=short

coverage:
	pytest tests/ --cov=src --cov-report=html --cov-report=term-missing
	@echo "Coverage report generated at htmlcov/index.html"

# ============================
# Code Quality
# ============================

lint:
	ruff check src/ tests/
	@echo "Lint passed!"

format:
	black src/ tests/
	isort src/ tests/
	@echo "Formatting complete!"

typecheck:
	pyright src/

# ============================
# Running
# ============================

# 乾跑 - 不發佈，只驗證
dry-run:
	python3 -m src.app run --edition postclose --mode draft --dry-run

# 執行 - draft 模式
run:
	python3 -m src.app run --edition postclose --mode draft

# 發佈模式
publish:
	python3 -m src.app run --edition postclose --mode publish

# 帶 record 的執行 (記錄 API 回應)
run-record:
	REPLAY_MODE=record python -m src.app run --edition postclose --mode draft

# 使用 fixtures 重播
run-replay:
	REPLAY_MODE=replay python -m src.app run --edition postclose --mode draft

# ============================
# Post Enhancement (第二次編輯增強)
# ============================

# 增強初稿 (使用 LiteLLM)
enhance:
	python3 scripts/enhance_post.py

# 測試增強品質閘門（不呼叫 LLM，只檢查現有檔案）
enhance-test:
	@echo "Testing quality gates on existing enhanced post..."
	@python3 -c "\
import json; \
from scripts.enhance_post import extract_numbers, check_numbers_gate, check_attribution_gate, run_quality_gates; \
rp = json.load(open('out/research_pack.json')); \
draft = json.load(open('out/post.json')); \
enhanced = json.load(open('out/post_enhanced.json')); \
passed, report = run_quality_gates(rp, draft.get('html',''), enhanced.get('html','')); \
print(json.dumps(report, indent=2, ensure_ascii=False)); \
exit(0 if passed else 1)"

# 增強後發佈 Draft（安全）
enhance-draft: enhance
	python3 scripts/ghost_publish_safe.py --mode draft \
		--post-json out/post_enhanced.json \
		--post-html out/post_enhanced.html

# 增強後發佈到內部測試（安全）
enhance-send-internal: enhance
	python3 scripts/ghost_publish_safe.py --mode publish-send \
		--post-json out/post_enhanced.json \
		--post-html out/post_enhanced.html \
		--newsletter daily-brief-test --segment "label:internal"

# 增強後發佈並寄信（需要明確指定 segment）
enhance-send: enhance
	@echo "=========================================="
	@echo "WARNING: 這會發送增強版 Newsletter！"
	@echo "=========================================="
	@read -p "Newsletter slug: " newsletter; \
	read -p "Segment (建議用 label:xxx，慎用 all): " segment; \
	if [ "$$segment" = "all" ] || [ "$$segment" = "status:free" ] || [ "$$segment" = "status:-free" ]; then \
		echo "[高風險] 你選擇的 segment '$$segment' 會發給大量用戶"; \
		read -p "確定要繼續嗎？(輸入 YES 確認): " confirm; \
		if [ "$$confirm" = "YES" ]; then \
			python3 scripts/ghost_publish_safe.py --mode publish-send \
				--post-json out/post_enhanced.json \
				--post-html out/post_enhanced.html \
				--newsletter "$$newsletter" --segment "$$segment" \
				--confirm-high-risk; \
		else \
			echo "已取消"; \
			exit 1; \
		fi; \
	else \
		python3 scripts/ghost_publish_safe.py --mode publish-send \
			--post-json out/post_enhanced.json \
			--post-html out/post_enhanced.html \
			--newsletter "$$newsletter" --segment "$$segment"; \
	fi

# ============================
# Quality Gates
# ============================

quality-check:
	python3 -m src.quality.quality_gate --post out/post.json --research-pack out/research_pack.json

# ============================
# Ghost CMS Publishing (三段式安全發佈)
# ============================

# Step 1: 驗證 Ghost 連線 + 建立 Draft（最安全）
ghost-draft:
	python3 scripts/ghost_publish_safe.py --mode draft

# Step 2: 發佈到網站但不寄信（仍很安全）
ghost-publish:
	python3 scripts/ghost_publish_safe.py --mode publish-no-email

# Step 3: 發佈並寄 Newsletter（需要 allowlist 設定）
# 使用前請確認：
#   1. GHOST_NEWSLETTER_ALLOWLIST 已設定
#   2. GHOST_SEGMENT_ALLOWLIST 已設定
#   3. out/quality_report.json 顯示 overall_passed: true
ghost-send:
	@echo "WARNING: This will send a newsletter!"
	@echo "Make sure GHOST_NEWSLETTER_ALLOWLIST and GHOST_SEGMENT_ALLOWLIST are set."
	@read -p "Newsletter slug: " newsletter; \
	read -p "Segment (e.g., label:internal): " segment; \
	python3 scripts/ghost_publish_safe.py --mode publish-send \
		--newsletter "$$newsletter" --segment "$$segment"

# Ghost Smoke Test (使用原始腳本)
ghost-smoke-test:
	@echo "Running Ghost smoke test (draft only)..."
	python3 scripts/ghost_smoke_test.py \
		--html-file out/post.html \
		--title "Smoke Test $(shell date +%Y%m%d-%H%M%S)" \
		--slug "smoke-test-$(shell date +%Y%m%d-%H%M%S)" \
		--mode draft

# ============================
# Utilities
# ============================

metrics:
	python3 scripts/metrics_rollup.py --reports-dir out/reports --days 30

fixtures:
	python3 -c "from src.replay.fixture_manager import create_sample_fixtures; create_sample_fixtures()"

clean:
	rm -rf out/*.json
	rm -rf htmlcov/
	rm -rf .pytest_cache/
	rm -rf **/__pycache__/
	rm -rf *.egg-info/
	rm -rf .ruff_cache/
	@echo "Cleaned!"

# 清理快取
clean-cache:
	rm -rf data/cache/**/*.json
	@echo "Cache cleaned!"

# ============================
# Daily Pipeline v2 (三篇文章產線)
# ============================

# 測試模式 - 產生三篇，發到內部
daily-test:
	python3 -m src.pipeline.run_daily --mode test

# 生產模式 - 產生三篇，發到正式（需確認）
daily-prod:
	python3 -m src.pipeline.run_daily --mode prod --confirm-high-risk

# 只產生 Flash (Post A)
daily-flash:
	python3 -m src.pipeline.run_daily --mode test --posts flash

# 只產生 Earnings (Post B)
daily-earnings:
	python3 -m src.pipeline.run_daily --mode test --posts earnings

# 只產生 Deep Dive (Post C)
daily-deep:
	python3 -m src.pipeline.run_daily --mode test --posts deep

# 產生全部三篇但不發佈
daily-no-publish:
	python3 -m src.pipeline.run_daily --mode test --skip-publish

# 指定日期產生（用於補發）
daily-backfill:
	@read -p "Date (YYYY-MM-DD): " date; \
	python3 -m src.pipeline.run_daily --mode test --date "$$date"

# ============================
# CI/CD
# ============================

ci-test:
	pytest tests/ -v --tb=short --junitxml=test-results.xml

ci-lint:
	ruff check src/ tests/ --output-format=github

# ============================
# Docker (Optional)
# ============================

docker-build:
	docker build -t daily-deep-brief:latest .

docker-run:
	docker run --rm -it \
		-v $(PWD)/out:/app/out \
		-v $(PWD)/data:/app/data \
		--env-file .env \
		daily-deep-brief:latest run --edition postclose --mode draft
