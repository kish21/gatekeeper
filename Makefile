# GateKeeperAI — common tasks a newcomer can just run.
# Uses `uv` if available, else falls back to pip/python.
.DEFAULT_GOAL := help
PY ?= python

.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

.PHONY: install
install: ## Install deps (prod+dev) and git hooks
	uv sync --all-extras --group dev || (pip install -e ".[demo]" && pip install pytest pytest-asyncio pytest-timeout ruff mypy types-PyYAML pre-commit)
	pre-commit install

.PHONY: demo
demo: ## Play the 5-beat governance story end-to-end (no setup; hermetic, throwaway ledger)
	$(PY) -m scripts.demo

.PHONY: demo-enterprise
demo-enterprise: ## Play the ENTERPRISE story: governed over HTTP with real-login (OIDC), hermetic
	$(PY) -m scripts.demo_enterprise

.PHONY: init
init: ## One-time setup: secrets into .env, ledger created, demo files seeded
	$(PY) -m gatekeeper.cli.app init

.PHONY: doctor
doctor: ## Check everything and print the MCP host config to paste
	$(PY) -m gatekeeper.cli.app doctor

.PHONY: serve
serve: ## Run the gateway (MCP transport, from config/)
	$(PY) -m gatekeeper.cli.app serve

.PHONY: verify
verify: ## Verify the audit ledger integrity (hash-chain)
	$(PY) -m gatekeeper.cli.app verify

.PHONY: tail
tail: ## Tail the audit ledger
	$(PY) -m gatekeeper.cli.app tail --with-id

.PHONY: test
test: ## Run the test suite
	pytest -q

.PHONY: lint
lint: ## Lint + format-check + types
	ruff check . && ruff format --check . && mypy

.PHONY: check
check: lint test ## Lint + tests (CI parity)

.PHONY: migrate
migrate: ## Apply DB migrations by hand (serve/init already do this on boot)
	alembic upgrade head
