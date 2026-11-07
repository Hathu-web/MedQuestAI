@echo off
setlocal
chcp 65001 >nul
pushd "%~dp0"
if exist ".venv\Scripts\python.exe" goto install
py -3.12 --version >nul 2>&1
if errorlevel 1 goto fallback
py -3.12 -m venv .venv
if errorlevel 1 goto failed
goto install
:fallback
python -c "import sys; sys.exit(0 if sys.version_info >= (3,12) else 1)" >nul 2>&1
if errorlevel 1 goto python_missing
python -m venv .venv
if errorlevel 1 goto failed
:install
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
".venv\Scripts\python.exe" scripts\setup_local.py
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m flask --app medquest check
if errorlevel 1 goto failed
echo.
echo Da cai moi truong. Neu cai moi: chay python scripts\setup_database.py
echo Neu da co database buoc 2: chay python scripts\upgrade_step3.py
echo Sau khi database san sang, mo run_windows.bat de chay MedQuest AI.
pause
popd
exit /b 0
:python_missing
echo Can Python 3.12 hoac moi hon. Khuyen nghi Python 3.12 va Add python.exe to PATH.
goto failed
:failed
echo Cai dat chua hoan tat. Hay doc thong bao loi phia tren.
pause
popd
exit /b 1
