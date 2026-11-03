@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo [1/3] Membuat virtual environment Python...
  py -3 -m venv .venv
  if errorlevel 1 goto :error
)
echo [2/3] Memasang dependensi...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :error
echo [3/3] Menjalankan UsahaInsight...
echo Buka http://127.0.0.1:8000 di browser.
".venv\Scripts\python.exe" run.py
pause
exit /b 0
:error
echo.
echo GAGAL. Pastikan Python 3.10+ dan koneksi internet untuk instalasi pertama.
pause
exit /b 1
