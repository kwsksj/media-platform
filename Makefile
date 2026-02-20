SHELL := /bin/bash

ADMIN_WEB_DIR ?= apps/admin-web
WORKER_API_DIR ?= apps/worker-api
INGEST_TOOL_DIR ?= ./tools/ingest
PUBLISH_TOOL_DIR ?= ./tools/publish
GALLERY_BUILD_TOOL_DIR ?= ./tools/gallery-build

DATE ?= $(shell date +%Y-%m-%d)
TAKEOUT_DIR ?= ./takeout-photos
THRESHOLD ?= 10
MAX_PER_GROUP ?= 10

.PHONY: help check-monorepo ingest-preview ingest-import-dry publish-dry publish-catchup-dry publish-monthly-schedule-dry gallery-export gallery-tag-recalc-dry gallery-tag-recalc-apply admin-smoke worker-dry secrets-list

help:
	@echo "Monorepo helper targets"
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
