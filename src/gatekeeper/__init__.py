"""GateKeeperAI — a tool-agnostic, verifiable governance gateway for MCP.

Layout (ports & adapters, dependencies point inward):
  transport/  speak MCP to the agent (stdio/HTTP) — no business logic
  gateway/    the PEP: pipeline identity->policy->[risk->approval]->audit->forward
  domain/     pure domain logic + value objects (the "what")
  ports/      adapter INTERFACES (the hexagon's ports)
  adapters/   concrete, config-selected implementations of ports
  schemas/    typed DTOs that cross boundaries (pydantic)
  audit/      tamper-evident ledger service + verify
  approval/   M2 human-in-the-loop write-approval gate
  ai/         M2 LLM risk classification (uses the llm port)
  infra/      cross-cutting: structured logging, resilience
  config/     typed config loader (reads .env + config/*.yaml)
  cli/        operator CLI (Typer)
  db/         persistence wiring + Alembic migrations
"""

__version__ = "0.0.1"
