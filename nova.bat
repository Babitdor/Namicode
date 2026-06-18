@echo off
REM Nova CLI wrapper — always runs from the repo's venv, always up to date.
REM Usage: nova [args...]
"%~dp0.venv\Scripts\python.exe" -m novacode_cli.main %*