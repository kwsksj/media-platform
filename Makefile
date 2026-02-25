SHELL := /bin/bash

ADMIN_WEB_DIR ?= apps/admin-web
WORKER_API_DIR ?= apps/worker-api
INGEST_TOOL_DIR ?= ./tools/ingest
PUBLISH_TOOL_DIR ?= ./tools/publish
GALLERY_BUILD_TOOL_DIR ?= ./tools/gallery-build
PYTHON ?= python3
VENV_DIR ?= venv
VENV_BIN := $(VENV_DIR)/bin
VENV_PYTHON := $(VENV_BIN)/python
PIP := $(VENV_PYTHON) -m pip
RUFF := $(VENV_PYTHON) -m ruff
MYPY := $(VENV_PYTHON) -m mypy
PYTEST := $(VENV_PYTHON) -m pytest
PRE_COMMIT := $(VENV_PYTHON) -m pre_commit

DATE ?= $(shell date +%Y-%m-%d)
TAKEOUT_DIR ?= ./takeout-photos
THRESHOLD ?= 10
MAX_PER_GROUP ?= 10

.PHONY: help ensure-python-venv setup-python-dev setup-admin-web pre-commit-install lint format-check typecheck test recommend-checks recommend-checks-strict check-required check-required-strict check-changed-python fix-changed-python check-fast check-python check-monorepo ingest-preview ingest-import-dry publish-dry publish-catchup-dry publish-monthly-schedule-dry gallery-export gallery-tag-recalc-dry gallery-tag-recalc-apply admin-smoke worker-dry secrets-list

help:
	@echo "Monorepo helper targets"
	@echo "  make setup-python-dev"
	@echo "  make setup-admin-web"
	@echo "  make pre-commit-install"
	@echo "  make recommend-checks        # suggest minimal checks from changed files"
	@echo "  make recommend-checks-strict # same as above, but marks cross-cutting checks required"
	@echo "  make check-required          # auto-run required checks from suggestions"
	@echo "  make check-required-strict   # strict required set (for pre-merge/release)"
	@echo "  make check-changed-python    # changed Python files only (ruff + mypy)"
	@echo "  make fix-changed-python      # auto-fix changed Python files"
	@echo "  make check-fast              # lint + typecheck"
	@echo "  make check-python            # lint + typecheck + test"
	@echo "  make check-monorepo"
	@echo "  make ingest-preview TAKEOUT_DIR=./takeout-photos [THRESHOLD=10] [MAX_PER_GROUP=10]"
	@echo "  make ingest-import-dry TAKEOUT_DIR=./takeout-photos [THRESHOLD=10] [MAX_PER_GROUP=10]"
	@echo "  make publish-dry [DATE=$$(date +%Y-%m-%d)]"
	@echo "  make publish-catchup-dry"
	@echo "  make publish-monthly-schedule-dry"
	@echo "  make gallery-export"
	@echo "  make gallery-tag-recalc-dry"
	@echo "  make gallery-tag-recalc-apply"
	@echo "  make admin-smoke"
	@echo "  make worker-dry"
	@echo "  make secrets-list [ENV_FILE=./.env]"

ensure-python-venv:
	@if [ ! -x "$(VENV_PYTHON)" ]; then \
		echo "Python venv not found: $(VENV_PYTHON)"; \
		echo "Run: make setup-python-dev"; \
		exit 1; \
	fi

setup-python-dev:
	@if [ ! -d "$(VENV_DIR)" ]; then $(PYTHON) -m venv "$(VENV_DIR)"; fi
	@$(PIP) install --upgrade pip
	@$(PIP) install -e ".[dev]"

setup-admin-web:
	@cd "$(ADMIN_WEB_DIR)" && npm install --no-package-lock

pre-commit-install: ensure-python-venv
	@$(PRE_COMMIT) install

lint: ensure-python-venv
	@$(RUFF) check src tests scripts

format-check: ensure-python-venv
	@$(RUFF) format --check src tests scripts

typecheck: ensure-python-venv
	@$(MYPY) src

test: ensure-python-venv
	@$(PYTEST) -q

recommend-checks: ensure-python-venv
	@$(VENV_PYTHON) scripts/recommend_checks.py --repo .

recommend-checks-strict: ensure-python-venv
	@$(VENV_PYTHON) scripts/recommend_checks.py --repo . --strict

check-required: ensure-python-venv
	@$(VENV_PYTHON) scripts/execute_recommended_checks.py --repo .

check-required-strict: ensure-python-venv
	@$(VENV_PYTHON) scripts/execute_recommended_checks.py --repo . --strict

check-changed-python: ensure-python-venv
	@set -e; \
	files="$$( \
		{ \
			git diff --name-only --diff-filter=ACMR -- '*.py'; \
			git diff --cached --name-only --diff-filter=ACMR -- '*.py'; \
			git ls-files --others --exclude-standard -- '*.py'; \
		} | sort -u \
	)"; \
	if [ -z "$$files" ]; then \
		echo "No changed Python files."; \
		exit 0; \
	fi; \
	echo "Changed Python files:"; \
	echo "$$files"; \
	$(RUFF) check $$files; \
	$(RUFF) format --check $$files; \
	src_files="$$(echo "$$files" | awk '/^src\/.*\.py$$/ {print}')"; \
	if [ -n "$$src_files" ]; then \
		$(MYPY) $$src_files; \
	else \
		echo "No changed files under src/ for mypy."; \
	fi

fix-changed-python: ensure-python-venv
	@set -e; \
	files="$$( \
		{ \
			git diff --name-only --diff-filter=ACMR -- '*.py'; \
			git diff --cached --name-only --diff-filter=ACMR -- '*.py'; \
			git ls-files --others --exclude-standard -- '*.py'; \
		} | sort -u \
	)"; \
	if [ -z "$$files" ]; then \
		echo "No changed Python files."; \
		exit 0; \
	fi; \
	echo "Auto-fixing changed Python files:"; \
	echo "$$files"; \
	$(RUFF) check --fix $$files; \
	$(RUFF) format $$files

check-fast: lint typecheck

check-python: check-fast test

check-monorepo:
	@./scripts/check-repo-structure.sh

ingest-preview:
	@"$(INGEST_TOOL_DIR)/preview.sh" "$(TAKEOUT_DIR)" --threshold "$(THRESHOLD)" --max-per-group "$(MAX_PER_GROUP)"

ingest-import-dry:
	@"$(INGEST_TOOL_DIR)/import-direct.sh" "$(TAKEOUT_DIR)" --threshold "$(THRESHOLD)" --max-per-group "$(MAX_PER_GROUP)" --dry-run

publish-dry:
	@"$(PUBLISH_TOOL_DIR)/post.sh" --dry-run --date "$(DATE)"

publish-catchup-dry:
	@"$(PUBLISH_TOOL_DIR)/catchup.sh" --dry-run

publish-monthly-schedule-dry:
	@"$(PUBLISH_TOOL_DIR)/monthly-schedule.sh" --dry-run

gallery-export:
	@"$(GALLERY_BUILD_TOOL_DIR)/export.sh" --no-upload --no-thumbs --no-light

gallery-tag-recalc-dry:
	@"$(GALLERY_BUILD_TOOL_DIR)/tag-recalc.sh" --dry-run

gallery-tag-recalc-apply:
	@"$(GALLERY_BUILD_TOOL_DIR)/tag-recalc.sh" --apply

admin-smoke:
	@cd "$(ADMIN_WEB_DIR)" && \
		if [ ! -d node_modules ]; then npm install --no-package-lock; fi && \
		npx playwright install chromium >/dev/null && \
		npm run test:upload-queue-smoke

worker-dry:
	@cd "$(WORKER_API_DIR)" && npx wrangler deploy --dry-run

secrets-list:
	@./scripts/list-required-gh-secrets.sh "$(if $(ENV_FILE),$(ENV_FILE),./.env)"
