@echo off
rem Line endings for this SlideMage checkout: let .gitattributes decide (stored LF, CRLF in the working tree),
rem not Git's per-PC core.autocrlf, which differs between machines (Git for Windows installs it as "true").
rem Double-click this file, or run it from any folder: it changes only the repository it lives in.
setlocal
cd /d "%~dp0.." || goto :fail
git rev-parse --show-toplevel >nul 2>&1 || goto :fail
git config core.autocrlf false || goto :fail
echo.
echo core.autocrlf is now "false" for this checkout:
git config --show-origin core.autocrlf
echo.
echo Files whose line endings differ from what .gitattributes now says (none is fine):
git add --renormalize --dry-run . 2>nul
echo.
echo If files are listed, run "git add --renormalize ." and commit them, or ask Claude.
goto :end
:fail
echo This file must stay in the tools folder of a SlideMage git checkout, and git must be installed.
:end
echo.
pause
