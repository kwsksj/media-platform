SHELL := /bin/bash

AUTO_POST_BIN ?= $(if $(wildcard ./venv/bin/auto-post),./venv/bin/auto-post,auto-post)
GALLERY_DIR ?= apps/gallery

DATE ?= $(shell date +%Y-%m-%d)
TAKEOUT_DIR ?= ./takeout-photos
THRESHOLD ?= 10
MAX_PER_GROUP ?= 10

.PHONY: help check-monorepo ingest-preview ingest-import-dry publish-dry gallery-export admin-smoke worker-dry secrets-list

help:
	@echo "Monorepo helper targets"
	@echo "  make check-monorepo"
	@echo "  make ingest-preview TAKEOUT_DIR=./takeout-photos [THRESHOLD=10] [MAX_PER_GROUP=10]"
	@echo "  make ingest-import-dry TAKEOUT_DIR=./takeout-photos [THRESHOLD=10] [MAX_PER_GROUP=10]"
	@echo "  make publish-dry [DATE=$$(date +%Y-%m-%d)]"
	@echo "  make gallery-export"
	@echo "  make admin-smoke"
	@echo "  make worker-dry"
	@echo "  make secrets-list [ENV_FILE=./.env]"

check-monorepo:
	@cd "$(GALLERY_DIR)" && ./scripts/check-monorepo-migration-readiness.sh

ingest-preview:
	@"$(AUTO_POST_BIN)" preview-groups "$(TAKEOUT_DIR)" --threshold "$(THRESHOLD)" --max-per-group "$(MAX_PER_GROUP)"

ingest-import-dry:
	@"$(AUTO_POST_BIN)" import-direct "$(TAKEOUT_DIR)" --threshold "$(THRESHOLD)" --max-per-group "$(MAX_PER_GROUP)" --dry-run

publish-dry:
	@"$(AUTO_POST_BIN)" post --dry-run --date "$(DATE)"

gallery-export:
	@"$(AUTO_POST_BIN)" export-gallery-json --no-upload --no-thumbs --no-light

admin-smoke:
	@cd "$(GALLERY_DIR)" && if [ ! -d node_modules ]; then npm install --no-package-lock; fi
	@cd "$(GALLERY_DIR)" && npx playwright install chromium >/dev/null
	@cd "$(GALLERY_DIR)" && npm run test:upload-queue-smoke

worker-dry:
	@cd "$(GALLERY_DIR)" && npx wrangler deploy --dry-run

secrets-list:
	@./scripts/list-required-gh-secrets.sh "$(if $(ENV_FILE),$(ENV_FILE),./.env)"
