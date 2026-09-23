@echo off
rem Start SlideMage from the repo's .venv, without a console window.
rem One-time setup, from the repo root:
rem     python -m venv .venv
rem     .venv\Scripts\pip install -e .
start "" "%~dp0..\.venv\Scripts\pythonw.exe" -m slidemage %*
