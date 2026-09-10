@echo off
REM Keep the Discord bot up on its own, independent of any dev session.
REM
REM It restarts itself after a crash or a dropped gateway connection, because
REM a remote control that quietly dies is worse than none -- you only find out
REM when you need it. Close this window to stop it for good.

title ROK farm - Discord bot

REM Derive the project root from this file's own location (%~dp0 is
REM ...\tools\remote\), never a fixed drive letter: this ships to machines
REM where the folder is somewhere else entirely.
cd /d "%~dp0..\.."

set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

:loop
echo.
echo === starting bot at %date% %time%
"%PY%" "tools\remote\discord_bot.py"
echo === bot exited with code %errorlevel%, restarting in 15s (Ctrl+C to stop)
timeout /t 15 /nobreak >nul
goto loop
