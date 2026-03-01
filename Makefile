SHELL := /bin/bash

# Paths
ADMIN_WEB_DIR ?= apps/admin-web
GALLERY_WEB_DIR ?= apps/gallery-web
WORKER_API_DIR ?= apps/worker-api
INGEST_TOOL_DIR ?= ./tools/ingest
PUBLISH_TOOL_DIR ?= ./tools/publish
GALLERY_BUILD_TOOL_DIR ?= ./tools/gallery-build
REPO ?= .

# Python toolchain
PYTHON ?= python3
VENV_DIR ?= venv
VENV_BIN := $(VENV_DIR)/bin
VENV_PYTHON := $(VENV_BIN)/python
PIP := $(VENV_PYTHON) -m pip
RUFF := $(VENV_PYTHON) -m ruff
MYPY := $(VENV_PYTHON) -m mypy
PYTEST := $(VENV_PYTHON) -m pytest
PRE_COMMIT := $(VENV_PYTHON) -m pre_commit

# Runtime options
DATE ?= $(shell date +%Y-%m-%d)
TAKEOUT_DIR ?= ./takeout-photos
THRESHOLD ?= 10
MAX_PER_GROUP ?= 10
ENV_FILE ?= ./.env

# Deploy options
WRANGLER_CONFIG ?= $(WORKER_API_DIR)/wrangler.toml
R2_BUCKET_NAME ?= woodcarving-photos
GALLERY_HTML_FILE ?= $(GALLERY_WEB_DIR)/gallery.html
ADMIN_HTML_FILE ?= $(ADMIN_WEB_DIR)/admin.html
ADMIN_INDEXES_OUT_DIR ?=

# SNS posting options
AUTO_POST_PLATFORM ?= all
PUBLISH_DAILY_BASIC_LIMIT ?= 2
PUBLISH_DAILY_CATCHUP_LIMIT ?= 1
PUBLISH_DAILY_YEAR_START_LIMIT ?= 1
PUBLISH_CATCHUP_LIMIT ?= 1
MONTHLY_TARGET ?= next
MONTHLY_YEAR ?=
MONTHLY_MONTH ?=

# Gallery build options
GALLERY_THUMB_WIDTH ?= 600
GALLERY_LIGHT_MAX_SIZE ?= 1600
GALLERY_LIGHT_QUALITY ?= 75
GALLERY_OVERWRITE_THUMBS ?= false
GALLERY_OVERWRITE_LIGHT ?= false

PR_POS_ARG = $(if $(PR),$(PR),)
PR_FLAG_ARG = $(if $(PR),--pr $(PR),)

.PHONY: \
	help \
	ensure-python-venv \
	setup-python-dev \
	setup-admin-web \
	setup-gallery-web \
	setup-web \
	pre-commit-install \
	lint \
	format-check \
	typecheck \
	test \
	recommend-checks \
	recommend-checks-strict \
	check-required \
	check-required-strict \
	check-changed-python \
	fix-changed-python \
	check-fast \
	check-python \
	check-monorepo \
	check-markdown \
	pr-ready \
	pr-fix-ci \
	pr-comments \
	pr-merge-local \
	ingest-preview \
	ingest-import-dry \
	publish-daily \
	publish-daily-dry \
	publish-catchup \
	publish-catchup-dry \
	publish-monthly-schedule \
	publish-monthly-schedule-dry \
	gallery-build \
	gallery-build-dry \
	gallery-tag-recalc-dry \
	gallery-tag-recalc-apply \
	deploy-gallery-html \
	deploy-gallery-data \
	deploy-gallery \
	deploy-admin-html \
	deploy-admin-indexes \
	deploy-admin \
	deploy-worker \
	deploy-worker-dry \
	deploy-all \
	admin-smoke \
	r2-backup \
	r2-backup-dry \
	r2-restore-dry \
	secrets-list

help: ## Show available helper targets
	@echo "Monorepo helper targets"
	@awk 'BEGIN {FS = ":.*## "}; /^[a-zA-Z0-9_.\/-]+:.*## / {printf "  make %-32s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

ensure-python-venv: ## Ensure Python venv exists
	@if [ ! -x "$(VENV_PYTHON)" ]; then \
		echo "Python venv not found: $(VENV_PYTHON)"; \
		echo "Run: make setup-python-dev"; \
		exit 1; \
	fi

setup-python-dev: ## Create venv and install Python dev dependencies
	@if [ ! -d "$(VENV_DIR)" ]; then $(PYTHON) -m venv "$(VENV_DIR)"; fi
	@$(PIP) install --upgrade pip
	@$(PIP) install -e ".[dev]"

setup-admin-web: ## Install admin web dependencies
	@cd "$(abspath $(ADMIN_WEB_DIR))" && npm install --no-package-lock

setup-gallery-web: ## Install gallery web dependencies
	@cd "$(abspath $(GALLERY_WEB_DIR))" && npm install --no-package-lock

setup-web: setup-admin-web setup-gallery-web ## Install all web app dependencies

pre-commit-install: ensure-python-venv ## Install pre-commit hooks
	@$(PRE_COMMIT) install

lint: ensure-python-venv ## Run Ruff lint
	@$(RUFF) check src tests scripts

format-check: ensure-python-venv ## Check formatting with Ruff
	@$(RUFF) format --check src tests scripts

typecheck: ensure-python-venv ## Run mypy
	@$(MYPY) src

test: ensure-python-venv ## Run pytest
	@$(PYTEST) -q

recommend-checks: ensure-python-venv ## Suggest minimal checks from changed files
	@$(VENV_PYTHON) scripts/recommend_checks.py --repo "$(REPO)"

recommend-checks-strict: ensure-python-venv ## Suggest checks with strict cross-cutting rules
	@$(VENV_PYTHON) scripts/recommend_checks.py --repo "$(REPO)" --strict

check-required: ensure-python-venv ## Auto-run required checks from recommendations
	@$(VENV_PYTHON) scripts/execute_recommended_checks.py --repo "$(REPO)"

check-required-strict: ensure-python-venv ## Auto-run strict required checks
	@$(VENV_PYTHON) scripts/execute_recommended_checks.py --repo "$(REPO)" --strict

check-changed-python: ensure-python-venv ## Check changed Python files only (ruff + mypy)
	@$(VENV_PYTHON) scripts/check_changed_python.py --repo "$(REPO)" --python "$(VENV_PYTHON)"

fix-changed-python: ensure-python-venv ## Auto-fix changed Python files
	@$(VENV_PYTHON) scripts/check_changed_python.py --repo "$(REPO)" --python "$(VENV_PYTHON)" --fix

check-fast: lint typecheck ## Run lint + typecheck

check-python: check-fast test ## Run lint + typecheck + test

check-monorepo: ## Check monorepo structure rules
	@./scripts/check-repo-structure.sh

check-markdown: ## Run markdown lint when npx is available
	@if command -v npx >/dev/null 2>&1; then \
		npx -y markdownlint-cli2; \
	else \
		echo "Skip: npx not found (install Node.js to run markdown lint)."; \
	fi

pr-ready: ## Run PR readiness flow (checks + status)
	@./scripts/gh_pr_ready.sh $(PR_POS_ARG)

pr-fix-ci: ensure-python-venv ## Inspect failing GitHub Actions checks for a PR
	@$(VENV_PYTHON) scripts/inspect_pr_checks.py --repo "$(REPO)" $(PR_FLAG_ARG)

pr-comments: ensure-python-venv ## Summarize actionable PR comments/review threads
	@$(VENV_PYTHON) scripts/fetch_pr_comments.py --repo "$(REPO)" $(PR_FLAG_ARG)

pr-merge-local: ## Merge PR and delete local branch
	@./scripts/gh_pr_merge_and_cleanup_local.sh $(PR_POS_ARG)

ingest-preview: ## Preview ingest groups from takeout
	@"$(INGEST_TOOL_DIR)/preview.sh" "$(TAKEOUT_DIR)" --threshold "$(THRESHOLD)" --max-per-group "$(MAX_PER_GROUP)"

ingest-import-dry: ## Dry-run direct ingest import
	@"$(INGEST_TOOL_DIR)/import-direct.sh" "$(TAKEOUT_DIR)" --threshold "$(THRESHOLD)" --max-per-group "$(MAX_PER_GROUP)" --dry-run

publish-daily: ## Run daily SNS posting (live)
	@"$(PUBLISH_TOOL_DIR)/post.sh" \
		--date "$(DATE)" \
		--platform "$(AUTO_POST_PLATFORM)" \
		--basic-limit "$(PUBLISH_DAILY_BASIC_LIMIT)" \
		--catchup-limit "$(PUBLISH_DAILY_CATCHUP_LIMIT)" \
		--year-start-limit "$(PUBLISH_DAILY_YEAR_START_LIMIT)"

publish-daily-dry: ## Dry-run daily SNS posting
	@"$(PUBLISH_TOOL_DIR)/post.sh" \
		--dry-run \
		--date "$(DATE)" \
		--platform "$(AUTO_POST_PLATFORM)" \
		--basic-limit "$(PUBLISH_DAILY_BASIC_LIMIT)" \
		--catchup-limit "$(PUBLISH_DAILY_CATCHUP_LIMIT)" \
		--year-start-limit "$(PUBLISH_DAILY_YEAR_START_LIMIT)"

publish-catchup: ## Run catch-up SNS posting (live)
	@"$(PUBLISH_TOOL_DIR)/catchup.sh" \
		--limit "$(PUBLISH_CATCHUP_LIMIT)" \
		--platform "$(AUTO_POST_PLATFORM)"

publish-catchup-dry: ## Dry-run catch-up SNS posting
	@"$(PUBLISH_TOOL_DIR)/catchup.sh" \
		--dry-run \
		--limit "$(PUBLISH_CATCHUP_LIMIT)" \
		--platform "$(AUTO_POST_PLATFORM)"

publish-monthly-schedule: ## Generate and post monthly schedule image (live)
	@set -euo pipefail; \
	args=(--platform "$(AUTO_POST_PLATFORM)"); \
	if [ -n "$(MONTHLY_TARGET)" ]; then args+=(--target "$(MONTHLY_TARGET)"); fi; \
	if [ -n "$(MONTHLY_YEAR)" ]; then args+=(--year "$(MONTHLY_YEAR)"); fi; \
	if [ -n "$(MONTHLY_MONTH)" ]; then args+=(--month "$(MONTHLY_MONTH)"); fi; \
	"$(PUBLISH_TOOL_DIR)/monthly-schedule.sh" "$${args[@]}"

publish-monthly-schedule-dry: ## Dry-run monthly schedule generation and posting
	@set -euo pipefail; \
	args=(--dry-run --platform "$(AUTO_POST_PLATFORM)"); \
	if [ -n "$(MONTHLY_TARGET)" ]; then args+=(--target "$(MONTHLY_TARGET)"); fi; \
	if [ -n "$(MONTHLY_YEAR)" ]; then args+=(--year "$(MONTHLY_YEAR)"); fi; \
	if [ -n "$(MONTHLY_MONTH)" ]; then args+=(--month "$(MONTHLY_MONTH)"); fi; \
	"$(PUBLISH_TOOL_DIR)/monthly-schedule.sh" "$${args[@]}"

gallery-build: ensure-python-venv ## Export gallery assets and upload gallery.json/images to R2
	@set -euo pipefail; \
	args=( \
		--thumb-width "$(GALLERY_THUMB_WIDTH)" \
		--light-max-size "$(GALLERY_LIGHT_MAX_SIZE)" \
		--light-quality "$(GALLERY_LIGHT_QUALITY)" \
	); \
	if [ "$(GALLERY_OVERWRITE_THUMBS)" = "true" ]; then args+=(--overwrite-thumbs); fi; \
	if [ "$(GALLERY_OVERWRITE_LIGHT)" = "true" ]; then args+=(--overwrite-light); fi; \
	"$(GALLERY_BUILD_TOOL_DIR)/export.sh" "$${args[@]}"

gallery-build-dry: ensure-python-venv ## Dry-run gallery build (no upload/thumb/light generation)
	@"$(GALLERY_BUILD_TOOL_DIR)/export.sh" --no-upload --no-thumbs --no-light

gallery-tag-recalc-dry: ## Dry-run gallery tag recalculation
	@"$(GALLERY_BUILD_TOOL_DIR)/tag-recalc.sh" --dry-run

gallery-tag-recalc-apply: ## Apply gallery tag recalculation
	@"$(GALLERY_BUILD_TOOL_DIR)/tag-recalc.sh" --apply

deploy-gallery-html: ## Upload gallery.html to R2
	@bash "$(abspath $(GALLERY_WEB_DIR))/scripts/upload-gallery-html.sh" "$(R2_BUCKET_NAME)" "$(abspath $(GALLERY_HTML_FILE))"

deploy-gallery-data: gallery-build ## Deploy gallery data (gallery.json/thumbs/light images)

deploy-gallery: deploy-gallery-data deploy-gallery-html ## Deploy public gallery data + HTML

deploy-admin-html: ## Upload admin HTML/CSS/JS assets to R2
	@set -euo pipefail; \
	upload() { \
		local object_path="$$1"; \
		local file_path="$$2"; \
		local content_type="$$3"; \
		local cache_control="$$4"; \
		npx wrangler r2 object put "$(R2_BUCKET_NAME)/$$object_path" \
			--config="$(abspath $(WRANGLER_CONFIG))" \
			--file="$$file_path" \
			--content-type="$$content_type" \
			--cache-control="$$cache_control" \
			--remote; \
	}; \
	upload "admin.html" "$(abspath $(ADMIN_HTML_FILE))" "text/html" "max-age=3600"; \
	upload "admin/admin.css" "$(abspath $(ADMIN_WEB_DIR))/admin/admin.css" "text/css; charset=utf-8" "max-age=3600"; \
	upload "admin/admin.js" "$(abspath $(ADMIN_WEB_DIR))/admin/admin.js" "text/javascript; charset=utf-8" "max-age=3600"; \
	upload "shared/gallery-core.css" "$(abspath $(ADMIN_WEB_DIR))/shared/gallery-core.css" "text/css; charset=utf-8" "max-age=3600"; \
	upload "shared/gallery-core.js" "$(abspath $(ADMIN_WEB_DIR))/shared/gallery-core.js" "text/javascript; charset=utf-8" "max-age=3600"

deploy-admin-indexes: ## Build and upload students/tags index JSON to R2
	@set -euo pipefail; \
	if [ -n "$(ADMIN_INDEXES_OUT_DIR)" ]; then \
		bash "$(abspath $(ADMIN_WEB_DIR))/scripts/upload-admin-indexes.sh" "$(R2_BUCKET_NAME)" "$(abspath $(ENV_FILE))" "$(abspath $(ADMIN_INDEXES_OUT_DIR))"; \
	else \
		bash "$(abspath $(ADMIN_WEB_DIR))/scripts/upload-admin-indexes.sh" "$(R2_BUCKET_NAME)" "$(abspath $(ENV_FILE))"; \
	fi

deploy-admin: deploy-admin-html deploy-admin-indexes ## Deploy admin web assets and indexes

deploy-worker: ## Deploy Cloudflare Worker (live)
	@cd "$(abspath $(WORKER_API_DIR))" && npx wrangler deploy

deploy-worker-dry: ## Dry-run worker deploy via Wrangler
	@cd "$(abspath $(WORKER_API_DIR))" && npx wrangler deploy --dry-run

deploy-all: deploy-gallery deploy-admin deploy-worker ## Deploy gallery, admin web, and worker

admin-smoke: ## Run admin upload-queue smoke test
	@cd "$(abspath $(ADMIN_WEB_DIR))" && \
		if [ ! -d node_modules ]; then npm install --no-package-lock; fi && \
		npx playwright install chromium >/dev/null && \
		npm run test:upload-queue-smoke

r2-backup: ## Copy R2 data to backup remote
	@./scripts/r2_backup.sh backup

r2-backup-dry: ## Dry-run R2 backup
	@./scripts/r2_backup.sh backup-dry-run

r2-restore-dry: ## Dry-run backup restore to R2
	@./scripts/r2_backup.sh restore-dry-run

secrets-list: ## List required GitHub secrets from env file
	@./scripts/list-required-gh-secrets.sh "$(abspath $(ENV_FILE))"
