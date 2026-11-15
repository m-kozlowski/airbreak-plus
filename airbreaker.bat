@echo off
rem Opens AirBreaker (no console)
set "GUI=%~dp0python\airbreaker.py"

rem A Python only counts when it runs and has tkinter: the Microsoft Store and Python
rem install manager stubs (pyw, pythonw, python) exist on PATH without a working Python.
py -3 -c "import tkinter" >nul 2>&1 && (start "" pyw -3 "%GUI%" & exit /b 0)
python -c "import tkinter" >nul 2>&1 && (
    where pythonw >nul 2>&1 && (start "" pythonw "%GUI%" & exit /b 0)
    start "" python "%GUI%" & exit /b 0
)
rem No Windows Python: run the window with python3 in WSL (it shows through WSLg).
where wsl.exe >nul 2>&1 || goto nopython
wsl.exe --exec python3 -c "import tkinter" >nul 2>&1 && goto runwsl
echo Python 3 with tkinter was not found in WSL.
rem apt-get only exists on Debian, Ubuntu and their derivatives.
wsl.exe --exec sh -c "command -v apt-get" >nul 2>&1 || goto noapt
echo AirBreaker needs these packages in WSL:
echo     python3 python3-tk make gcc-arm-none-eabi binutils-arm-none-eabi
echo Installing them uses sudo apt-get, needs internet and takes a minute; sudo asks
echo for your WSL password.
choice /C YN /M "Install them now"
if errorlevel 2 goto nopython
wsl.exe --exec sudo sh -c "apt-get update && apt-get install -y python3 python3-tk make gcc-arm-none-eabi binutils-arm-none-eabi"
wsl.exe --exec python3 -c "import tkinter" >nul 2>&1 || goto installfailed
:runwsl
powershell -NoProfile -WindowStyle Hidden -Command "Start-Process wsl.exe -WindowStyle Hidden -ArgumentList '--cd','%~dp0.','--exec','python3','python/airbreaker.py'"
exit /b 0

:installfailed
echo Python 3 with tkinter is still missing in WSL; see the messages above.
pause
exit /b 1

:noapt
echo Your WSL distribution has no apt-get. Install python3 with tkinter, make and the
echo ARM GCC toolchain with its own package manager (docs/guide/wsl_setup.md).
:nopython
echo Python 3 was not found.
echo Install it from https://www.python.org/downloads/windows/ with
echo "py launcher" and "tcl/tk and IDLE" selected, or set up WSL (docs/guide/wsl_setup.md),
echo then run this again.
pause
exit /b 1
