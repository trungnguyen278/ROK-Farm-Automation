@echo off
REM Keep the Discord bot up on its own, independent of any dev session.
REM
REM It restarts itself after a crash or a dropped gateway connection, because
REM a remote control that quietly dies is worse than none -- you only find out
REM when you need it. Close this window to stop it for good.

title ROK farm - Discord bot
cd /d "D:\ROK Farm Automation"

:loop
echo.
echo === starting bot at %date% %time%
".venv\Scripts\python.exe" "tools\remote\discord_bot.py"
echo === bot exited with code %errorlevel%, restarting in 15s (Ctrl+C to stop)
timeout /t 15 /nobreak >nul
goto loop
