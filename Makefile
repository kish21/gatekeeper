# GateKeeperAI — common tasks a newcomer can just run.
# Uses `uv` if available, else falls back to pip/python.
.DEFAULT_GOAL := help
PY ?= python

.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

.PHONY: install
install: ## Install deps (prod+dev) and git hooks
	uv sync --all-extras --group dev || pip install -e ".[ai]" && pip install pre-commit pytest ruff mypy
	pre-commit install

.PHONY: demo
demo: ## Play the 5-beat governance story end-to-end (no setup; hermetic, throwaway ledger)
	$(PY) -m scripts.demo

.PHONY: demo-enterprise
demo-enterprise: ## Play the ENTERPRISE story: governed over HTTP with real-login (OIDC), hermetic
	$(PY) -m scripts.demo_enterprise

.PHONY: serve
serve: ## Run the gateway (MCP transport, from config/)
	$(PY) -m gatekeeper.cli.app serve

.PHONY: verify
verify: ## Verify the audit ledger integrity (hash-chain)
	$(PY) -m gatekeeper.cli.app verify

.PHONY: tail
tail: ## Tail the audit ledger
	$(PY) -m gatekeeper.cli.app tail

.PHONY: test
test: ## Run the test suite
	pytest -q

.PHONY: lint
lint: ## Lint + format-check + types
	ruff check . && ruff format --check . && mypy

.PHONY: check
check: lint test ## Lint + tests (CI parity)

.PHONY: migrate
migrate: ## Apply DB migrations (Alembic)
	alembic upgrade head

.PHONY: seed
seed: ## Seed example config (upstreams, identities, policy) for a local demo
	$(PY) -m gatekeeper.cli.app seed-demo
