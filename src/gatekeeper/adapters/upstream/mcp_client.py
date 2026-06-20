"""MCP-client ``UpstreamClient`` — forwards a governed call to a real upstream MCP server.

Implements ``ports.upstream.UpstreamClient``. The ONLY layer allowed to import the MCP SDK on the
upstream side (ports & adapters / ADR-004). Holds ONE persistent, lazily-opened session per upstream
(re-launching a stdio server per call would be slow and lose its state) and serializes calls to each
session with a lock (a single stdio pipe is request/response, not concurrent). Each session's
anyio-backed lifecycle is pinned to its own dedicated task (``_SessionRunner``) so it is opened and
closed in the same task — ``aclose()`` stays correct even when the session was first opened inside a
forward's child task (the MCP server dispatches calls via ``tg.start_soon``).

Resilience (ADR-004): a per-call timeout; any failure is converted to a non-raising ``ToolResult``
with ``ok=False`` so the agent never hangs and the pipeline can still AUDIT the outcome (fail-closed
without un-audited bypass). ``summary`` is redacted/truncated — raw output is relayed live via
``ToolResult.raw`` but never persisted.
"""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client

from gatekeeper.config.loader import ConfigError
from gatekeeper.infra.logging import get_logger
from gatekeeper.schemas.models import ToolCall, ToolResult

_log = get_logger("gatekeeper.upstream")

#: Max chars of an upstream result kept in the audit summary (raw output is never persisted).
_SUMMARY_MAX = 200

#: In ``config/upstreams.yaml`` an env value may be a literal, OR ``{from_env: NAME}`` — a reference
#: whose VALUE is read from the process environment / ``.env`` at launch. Keeping only the NAME in
#: YAML upholds the project rule "secrets never live in YAML, only their names" (config/loader.py)
#: for an upstream's own credentials (e.g. a GitHub server's token) too.
_ENV_REF_KEY = "from_env"


def _resolve_env_value(upstream: str, key: str, value: object, source: Mapping[str, str]) -> str:
    """Resolve one upstream env entry to its final string value.

    A literal scalar passes through unchanged (backward compatible). A ``{from_env: NAME}`` mapping
    is replaced by ``source[NAME]`` (the live env / ``.env``). Fail-closed: a referenced-but-unset
    secret raises ``ConfigError`` so a half-configured credential aborts startup, rather than
    silently launching the server without it — or leaking the literal ``{...}`` placeholder as the
    credential. The resolved value is passed straight to the subprocess; it is never logged or
    persisted to the audit ledger.
    """
    if isinstance(value, Mapping):
        name = value.get(_ENV_REF_KEY)
        if set(value) != {_ENV_REF_KEY} or not isinstance(name, str) or not name:
            raise ConfigError(
                f"upstream {upstream!r} env {key!r}: expected a literal value or "
                f"{{{_ENV_REF_KEY}: NAME}}, got {value!r}."
            )
        try:
            return source[name]
        except KeyError:
            raise ConfigError(
                f"upstream {upstream!r} env {key!r}: secret {name!r} (referenced via "
                f"'{_ENV_REF_KEY}') is not set. Put it in .env — never in config/upstreams.yaml. "
                "Refusing to start (fail-closed)."
            ) from None
    return str(value)


def _resolve_launcher(command: str) -> str:
    """Resolve a stdio upstream's launcher command.

    A bare ``python``/``python3`` resolves via PATH, which under an MCP host (Claude Desktop, an
    IDE, cron) may not be the interpreter GateKeeper itself runs in — so a config-declared
    ``python -m your_server`` upstream would fail to import its package. Pin those to THIS
    interpreter (``sys.executable``) so such an upstream launches reliably regardless of the host's
    PATH or venv activation. Any other launcher (``npx``, a full path, a binary) is used verbatim.
    """
    if command in ("python", "python3"):
        return sys.executable
    return command


@dataclass(frozen=True)
class UpstreamSpec:
    """How to reach one registered upstream (from ``config/upstreams.yaml``)."""

    name: str
    transport: str
    command: tuple[str, ...] = ()
    env: Mapping[str, str] | None = None
    cwd: str | None = None

    @classmethod
    def from_config(
        cls, raw: Mapping[str, Any], *, secret_source: Mapping[str, str] | None = None
    ) -> UpstreamSpec:
        """Build a spec from one ``config/upstreams.yaml`` entry.

        Each ``env`` value is a literal, or a ``{from_env: NAME}`` secret reference resolved against
        ``secret_source`` (defaults to the live process env). Injecting the source keeps resolution
        testable without mutating real env vars.
        """
        source = os.environ if secret_source is None else secret_source
        name = str(raw["name"])
        raw_env = raw.get("env")
        env = (
            {str(k): _resolve_env_value(name, str(k), v, source) for k, v in raw_env.items()}
            if raw_env
            else None
        )
        return cls(
            name=name,
            transport=str(raw.get("transport", "stdio")),
            command=tuple(str(part) for part in raw.get("command", [])),
            env=env,
            cwd=str(raw["cwd"]) if raw.get("cwd") else None,
        )

    def stdio_params(self) -> StdioServerParameters:
        if self.transport != "stdio":
            raise NotImplementedError(
                f"upstream {self.name!r}: transport {self.transport!r} not supported yet "
                "(stdio only this slice; HTTP is a fast-follow)."
            )
        if not self.command:
            raise ValueError(f"upstream {self.name!r}: stdio transport needs a 'command'.")
        return StdioServerParameters(
            command=_resolve_launcher(self.command[0]),
            args=list(self.command[1:]),
            env=self._child_env(),
            cwd=self.cwd,
        )

    def _child_env(self) -> dict[str, str]:
        """Environment for the upstream subprocess.

        The MCP SDK's default stdio environment is a scrubbed allowlist that, under an MCP host on
        Windows, can omit vars a child interpreter needs to even start (e.g. ``SystemRoot``) — so a
        config-declared ``python -m ...`` upstream fails to spawn and its tools silently never
        appear (``upstream unavailable; skipping``). Inherit the gateway's own process environment
        so upstreams launch reliably regardless of host, then overlay the upstream's configured env
        (incl. resolved ``{from_env}`` secrets). The gateway's OWN secrets (``GATEKEEPER_*`` — the
        ledger HMAC key, the agent token) are stripped first, so a governed upstream never inherits
        them (least privilege; only its own declared credentials reach it).
        """
        env = {k: v for k, v in os.environ.items() if not k.startswith("GATEKEEPER_")}
        if self.env:
            env.update(self.env)
        return env


def _summarize(result: types.CallToolResult) -> str:
    """Status-only summary for the ledger — metadata, NOT the raw output body (PII stance).

    A successful result records only shape (block count + total text length): the actual content
    is relayed live to the agent via ``ToolResult.raw`` but is never written to the audit log, so a
    governed read of a secret file leaves no plaintext in the ledger. An error records a truncated
    diagnostic message (errors carry *why*, which is the point of auditing them) capped at
    ``_SUMMARY_MAX``.
    """
    block_count = len(result.content)
    if result.isError:
        first = next((b.text for b in result.content if isinstance(b, types.TextContent)), "")
        message = first[:_SUMMARY_MAX]
        return f"error: {message}" if message else "error"
    text_len = sum(len(b.text) for b in result.content if isinstance(b, types.TextContent))
    return f"ok: {block_count} block(s), {text_len} chars"


@dataclass
class _SessionRunner:
    """One upstream session, whose anyio contexts are opened AND closed inside a single task.

    The stdio + ``ClientSession`` contexts are anyio-backed: their cancel scopes must be exited in
    the SAME task that entered them. But the low-level MCP server dispatches every call in a child
    task (``tg.start_soon``), so a session first opened during a ``forward`` would otherwise be torn
    down by ``aclose()`` running in a *different* task — anyio's "cancel scope in a different task"
    ``RuntimeError`` on shutdown. Pinning the whole open→hold→close lifecycle to one dedicated
    ``task`` decouples it from whichever caller triggered the open: ``aclose()`` only sets ``stop``.
    """

    ready: asyncio.Event  # set once the session is usable (success) OR the open has failed
    stop: asyncio.Event  # set by aclose() to ask the task to unwind its contexts
    task: asyncio.Task[None] | None = None
    session: ClientSession | None = None  # populated before ``ready`` fires on success
    error: BaseException | None = None  # populated before ``ready`` fires on open failure


class McpUpstreamClient:
    """Forward calls to registered upstreams over the MCP SDK, one persistent session each."""

    def __init__(self, specs: Sequence[UpstreamSpec], *, timeout: float = 30.0) -> None:
        self._specs = {spec.name: spec for spec in specs}
        self._timeout = timeout
        # One dedicated lifecycle task per opened upstream (see ``_SessionRunner``).
        self._runners: dict[str, _SessionRunner] = {}
        # Per-upstream call lock (serialize the single request/response stdio pipe) — pre-created so
        # it is never assigned *after* first use. A separate lock guards session CREATION: the MCP
        # server dispatches requests concurrently (tg.start_soon), so two first-calls to the same
        # upstream could otherwise both open a session and leak/duplicate the subprocess.
        self._locks = {name: asyncio.Lock() for name in self._specs}
        self._create_lock = asyncio.Lock()

    @classmethod
    def from_config(
        cls,
        upstreams: Sequence[Mapping[str, Any]],
        *,
        timeout: float = 30.0,
        secret_source: Mapping[str, str] | None = None,
    ) -> McpUpstreamClient:
        return cls(
            [UpstreamSpec.from_config(u, secret_source=secret_source) for u in upstreams],
            timeout=timeout,
        )

    def upstream_names(self) -> list[str]:
        return list(self._specs)

    async def _session_for(self, name: str) -> ClientSession:
        runner = self._runners.get(name)
        if runner is None:
            async with self._create_lock:  # double-checked: one lifecycle task per upstream
                runner = self._runners.get(name)
                if runner is None:
                    runner = _SessionRunner(ready=asyncio.Event(), stop=asyncio.Event())
                    # Spawn an independent task: it owns the session's anyio cancel scopes so they
                    # are entered AND exited in this one task, never the (child) caller's task.
                    runner.task = asyncio.create_task(
                        self._run_session(name, runner), name=f"gk-upstream:{name}"
                    )
                    self._runners[name] = runner
        await runner.ready.wait()
        if runner.error is not None:
            # Open failed: drop the runner (not sticky) so a later call can relaunch, then surface
            # the failure — forward() turns it into ok=False; _build_tool_index skips. Fail-closed.
            async with self._create_lock:
                if self._runners.get(name) is runner:
                    del self._runners[name]
            raise runner.error
        assert runner.session is not None  # set before ``ready`` fires on the success path
        return runner.session

    async def _run_session(self, name: str, runner: _SessionRunner) -> None:
        """Open the session, publish it, hold its contexts open until ``stop`` — all in THIS task.

        Closing the stdio + ``ClientSession`` contexts here (on ``stop`` or on task cancellation
        from ``aclose``) keeps cancel-scope enter/exit in a single task, which is what makes
        shutdown safe no matter which task first opened the session (see ``_SessionRunner``).
        """
        spec = self._specs[name]
        try:
            async with stdio_client(spec.stdio_params()) as (read, write):
                async with ClientSession(read, write) as session:
                    await asyncio.wait_for(session.initialize(), self._timeout)
                    runner.session = session
                    _log.info("upstream session opened", extra={"upstream": name})
                    runner.ready.set()
                    await runner.stop.wait()  # keep the contexts alive until gateway shutdown
        except asyncio.CancelledError:
            raise  # cooperative shutdown: let the contexts unwind in this task, then propagate
        except Exception as exc:  # noqa: BLE001 — surface any open failure to the waiter (fail-closed)
            runner.error = exc
            _log.error("upstream session failed to open", extra={"upstream": name})
        finally:
            runner.session = None
            runner.ready.set()  # never leave _session_for blocked, even on a failed open

    async def list_tools(self, name: str) -> list[types.Tool]:
        """List the tools a registered upstream exposes (used to build the proxy's tool surface)."""
        session = await self._session_for(name)
        async with self._locks[name]:
            result = await asyncio.wait_for(session.list_tools(), self._timeout)
        return list(result.tools)

    async def forward(self, call: ToolCall) -> ToolResult:
        """Forward an approved call to its upstream. Never raises — failures become ok=False."""
        if call.upstream not in self._specs:
            return self._failure(call, f"unknown upstream {call.upstream!r}")
        try:
            session = await self._session_for(call.upstream)
            async with self._locks[call.upstream]:
                raw = await asyncio.wait_for(
                    session.call_tool(call.tool, call.arguments), self._timeout
                )
        except Exception as exc:  # noqa: BLE001 — fail-closed: convert any failure, never hang
            _log.error(
                "upstream forward failed",
                extra={"call_id": call.call_id, "upstream": call.upstream, "tool": call.tool},
            )
            return self._failure(call, f"{type(exc).__name__}: {exc}")
        return ToolResult(
            call_id=call.call_id, ok=not raw.isError, summary=_summarize(raw), raw=raw
        )

    @staticmethod
    def _failure(call: ToolCall, reason: str) -> ToolResult:
        raw = types.CallToolResult(
            content=[types.TextContent(type="text", text=reason)], isError=True
        )
        return ToolResult(call_id=call.call_id, ok=False, summary=f"error: {reason}", raw=raw)

    async def aclose(self) -> None:
        """Close every open upstream session (called on gateway shutdown).

        Signals each session's dedicated task to stop, then awaits it. Each task unwinds its own
        anyio contexts in the task that opened them, so this is safe to call from any task — even
        when a session was first opened inside a forward's child task. Best-effort: a hung teardown
        is cancelled after ``timeout`` and shutdown never raises.
        """
        runners = list(self._runners.items())
        for _name, runner in runners:
            runner.stop.set()
        for name, runner in runners:
            task = runner.task
            if task is None:
                continue
            try:
                # wait_for cancels the task on timeout (injecting CancelledError, which _run_session
                # re-raises so the contexts still unwind in-task before the task ends).
                await asyncio.wait_for(task, self._timeout)
            except (TimeoutError, asyncio.CancelledError):
                pass
            except Exception:  # noqa: BLE001 — never let a teardown error break shutdown
                _log.error("error closing upstream session", extra={"upstream": name})
        self._runners.clear()
        self._locks.clear()
