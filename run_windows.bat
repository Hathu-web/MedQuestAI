@echo off
setlocal
chcp 65001 >nul
pushd "%~dp0"
if not exist ".venv\Scripts\python.exe" goto missing
echo Mo trinh duyet tai http://127.0.0.1:5000
echo Nhan Ctrl+C de dung. Ban nay dung hoi thoai mau, chua ket noi AI.
".venv\Scripts\python.exe" -m flask --app medquest run --host 127.0.0.1 --port 5000
if errorlevel 1 pause
popd
exit /b
:missing
echo Hay chay setup_windows.bat truoc.
pause
popd
exit /b 1
