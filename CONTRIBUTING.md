# Contributing to GateKeeperAI

## Getting started
```bash
make install   # deps + git hooks
make check     # lint + tests (must pass before a PR)
```

## Ground rules
- **No hardcoding.** Secrets → `.env`; tunable knobs → `config/*.yaml`; never a key in a code file.
- **Ports & adapters.** No external SDK (LLM, DB, MCP) imported in domain logic — go through a port in
  `src/gatekeeper/ports/` with a concrete adapter in `src/gatekeeper/adapters/`.
- **Typed contracts.** Data crossing a boundary is a `pydantic` model in `src/gatekeeper/schemas/`.
- **Fail-closed.** Errors in the decision path deny, never allow.
- **DB via migrations.** Change schema with Alembic; never hand-edit the DB.
- **Tests required.** Unit (isolated) + integration (real contracts) + adversarial (tamper/bypass).

## Workflow
One feature per branch → PR → CI green → review → squash-merge. See `PRODUCT.md` for the phase plan.
