"""Cross-cutting infrastructure: structured (JSON) logging and resilience helpers.

Resilience (ADR-004): timeouts, retry-transient-only, circuit-breaker — applied by adapters that
talk to externals. Logging is structured for SIEM ingestion (config: logging.format=json).
"""
