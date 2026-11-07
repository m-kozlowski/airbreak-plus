@echo off
rem Opens AirBreaker (no console)
set "GUI=%~dp0python\airbreaker.py"

rem Python Launcher (python.org installs), then any Python on PATH.
where pyw >nul 2>&1 && (start "" pyw -3 "%GUI%" & exit /b 0)
where pythonw >nul 2>&1 && (start "" pythonw "%GUI%" & exit /b 0)
rem The Microsoft Store "python" alias fails --version when Python is absent.
python --version >nul 2>&1 && (start "" python "%GUI%" & exit /b 0)

echo Python 3 was not found.
echo Install it from https://www.python.org/downloads/windows/ with
echo "py launcher" and "tcl/tk and IDLE" selected, then run this again.
pause
exit /b 1
