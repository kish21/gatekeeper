@echo off
REM ===================================================================
REM  GateKeeperAI - show the audit logbook (double-click to run)
REM  Lists the most recent governed calls: who, what, allow/deny.
REM ===================================================================
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m gatekeeper.cli.app tail
) else (
    echo Could not find the project's Python at .venv\Scripts\python.exe
)
echo.
echo  Press any key to close this window.
pause >nul
