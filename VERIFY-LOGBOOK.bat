@echo off
REM ===================================================================
REM  GateKeeperAI - verify the audit logbook (double-click to run)
REM  Recomputes the hash-chain. OK = untampered; TAMPERED = altered.
REM ===================================================================
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m gatekeeper.cli.app verify
) else (
    echo Could not find the project's Python at .venv\Scripts\python.exe
)
echo.
echo  Press any key to close this window.
pause >nul
