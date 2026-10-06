@echo off
rem Double-click to start Lightyear. Keep this window open while you use the page.
cd /d "%~dp0"
echo Starting Lightyear at http://127.0.0.1:8100 ...
python -m lightyear
echo.
echo Lightyear stopped. If an error is shown above, copy it to Claude.
pause
