"""Integration — the narrated ENTERPRISE demo (scripts/demo_enterprise) runs clean end-to-end.

Deep OIDC-over-HTTP governance correctness is covered by ``test_oidc_http``; here we assert the
demo SCRIPT itself drives the REAL path (uvicorn + validated JWTs + subprocess upstream) to
completion, narrates allow + deny + verify + a caught tamper, surfaces ``/metrics``, and never
prints a raw JWT (a credential).
"""

from __future__ import annotations

from rich.console import Console
from scripts.demo_enterprise import run_enterprise_demo


async def test_enterprise_demo_runs_clean_and_leaks_no_token() -> None:
    console = Console(record=True, width=100, force_terminal=False)
    code = await run_enterprise_demo(console=console)
    out = console.export_text()

    assert code == 0, out
    # The enterprise beats all fire.
    assert "ALLOW" in out and "DENY" in out  # Beats 1-3: governed allow + RBAC/identity denies
    assert "verified" in out  # Beat 5: verify passed over the HTTP-governed chain
    assert "TAMPERED" in out  # Beat 5: the tamper was caught (the wedge)
    assert "gatekeeper_calls_total" in out  # Beat 4: the /metrics surface was shown
    # A base64url JWT header always starts with "eyJ"; minted tokens are credentials and must
    # never appear in the narrative (the gateway never logs them either).
    assert "eyJ" not in out
