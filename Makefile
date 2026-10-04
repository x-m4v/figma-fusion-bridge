# Figma Fusion Bridge

SHELL := /bin/bash
.DEFAULT_GOAL := help

.PHONY: help install build build-schema build-plugin build-app test test-python test-swift \
        typecheck clean dist docs pdf run stop

help: ## Show this help
	@grep -hE '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

install: ## Install JavaScript dependencies
	npm install

build: build-schema build-plugin build-app ## Build everything

build-schema: ## Compile the interchange schema
	npx tsc -p packages/schema/tsconfig.json

build-plugin: ## Bundle the Figma plugin
	cd packages/figma-plugin && node build.mjs

build-app: ## Build the macOS bridge as a .app
	CONFIG=release bash scripts/build-app.sh

test: test-python test-swift ## Run every test suite

test-python: ## Fusion builder tests (no Resolve needed)
	python3 -m pytest resolve/tests -q

test-swift: ## Bridge tests (no Xcode needed)
	cd bridge-macos && swift run BridgeTests 2>/dev/null

typecheck: ## Typecheck the TypeScript packages
	npx tsc --noEmit -p packages/schema/tsconfig.json
	npx tsc --noEmit -p packages/figma-plugin/tsconfig.json

pdf: ## Regenerate the PDF manual
	python3 scripts/build-manual.py

docs: pdf ## Build all documentation

run: build-app ## Build and launch the bridge
	open "dist/Figma Fusion Bridge.app"

stop: ## Quit the bridge
	@pkill -f "Figma Fusion Bridge.app" 2>/dev/null || true

clean: ## Remove build output
	rm -rf dist packages/*/dist bridge-macos/.build
	find . -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
