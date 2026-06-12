@echo off
REM ===================================================================
REM  GateKeeperAI - customer demo launcher (double-click to run)
REM  Plays the 5-beat governance story on screen. Nothing is installed
REM  or changed on your machine; it cleans up after itself.
REM ===================================================================

REM Move into this script's own folder so the demo finds its config.
cd /d "%~dp0"

REM Run the demo using the Python that lives inside this project (.venv).
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m scripts.demo
) else (
    echo Could not find the project's Python at .venv\Scripts\python.exe
    echo Open the project once with your developer to run "make install", then try again.
)

echo.
echo ===================================================================
echo  Demo finished. Press any key to close this window.
echo ===================================================================
pause >nul
