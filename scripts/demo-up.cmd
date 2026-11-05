@echo off
rem Double-click: start the demo and open it (see demo-up.ps1).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0demo-up.ps1" %*
pause
