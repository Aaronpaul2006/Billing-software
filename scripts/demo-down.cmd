@echo off
rem Double-click: stop the demo (see demo-down.ps1).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0demo-down.ps1" %*
pause
