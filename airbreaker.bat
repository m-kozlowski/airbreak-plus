@echo off
rem Opens AirBreaker (no console)
set "GUI=%~dp0python\airbreaker.py"

rem Python Launcher (python.org installs), then any Python on PATH.
where pyw >nul 2>&1 && (start "" pyw -3 "%GUI%" & exit /b 0)
where pythonw >nul 2>&1 && (start "" pythonw "%GUI%" & exit /b 0)
rem The Microsoft Store "python" alias fails --version when Python is absent.
python --version >nul 2>&1 && (start "" python "%GUI%" & exit /b 0)

rem No Windows Python: run the window with python3 in WSL (it shows through WSLg).
where wsl.exe >nul 2>&1 || goto nopython
wsl.exe --exec python3 -c "import tkinter" >nul 2>&1 && goto runwsl
echo Python 3 with tkinter was not found in WSL. Installing python3, python3-tk, make and
echo the ARM toolchain there (needs internet, takes a minute)...
wsl.exe -u root --exec bash -c "apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y python3 python3-tk make gcc-arm-none-eabi binutils-arm-none-eabi"
wsl.exe --exec python3 -c "import tkinter" >nul 2>&1 || goto nopython
:runwsl
powershell -NoProfile -WindowStyle Hidden -Command "Start-Process wsl.exe -WindowStyle Hidden -ArgumentList '--cd','%~dp0.','--exec','python3','python/airbreaker.py'"
exit /b 0

:nopython
echo Python 3 was not found.
echo Install it from https://www.python.org/downloads/windows/ with
echo "py launcher" and "tcl/tk and IDLE" selected, or set up WSL (docs/guide/wsl_setup.md),
echo then run this again.
pause
exit /b 1
