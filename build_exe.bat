@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

echo [1/5] Detecting Python launcher...
set "PY_CMD="
where py >nul 2>nul
if %errorlevel%==0 (
  set "PY_CMD=py -3"
)

if not defined PY_CMD (
  where python >nul 2>nul
  if %errorlevel%==0 (
    set "PY_CMD=python"
  )
)

if not defined PY_CMD (
  echo [ERROR] Python 3 was not found. Please install Python 3 first.
  pause
  exit /b 1
)

echo [2/5] Using: %PY_CMD%
%PY_CMD% --version
if errorlevel 1 (
  echo [ERROR] Cannot run Python.
  pause
  exit /b 1
)

echo [3/5] Installing/upgrading PyInstaller...
%PY_CMD% -m pip install --upgrade pip --timeout 120 --retries 8 >nul 2>nul
%PY_CMD% -m pip install --upgrade pyinstaller --timeout 120 --retries 8
if errorlevel 1 (
  echo [ERROR] Failed to install PyInstaller.
  pause
  exit /b 1
)

echo [4/5] Cleaning deployed folder...
taskkill /f /im windows-content-uploader.exe >nul 2>nul
if not exist "deployed" mkdir "deployed"
set "CLEAN_OK=0"
for /l %%I in (1,1,5) do (
  set "CLEAN_OK=1"
  for /d %%D in ("deployed\\*") do (
    rmdir /s /q "%%~fD" >nul 2>nul
    if exist "%%~fD" set "CLEAN_OK=0"
  )
  for %%F in ("deployed\\*") do (
    if exist "%%~fF" (
      del /f /q "%%~fF" >nul 2>nul
      if exist "%%~fF" set "CLEAN_OK=0"
    )
  )
  if "!CLEAN_OK!"=="1" goto :clean_done
  echo [WARN] deployed contents are locked, retry %%I/5...
  powershell -NoProfile -Command "Start-Sleep -Seconds 2"
)
:clean_done
if not "!CLEAN_OK!"=="1" (
  echo [ERROR] Cannot clean deployed contents. Please close files under deployed and retry.
  pause
  exit /b 1
)

echo [5/5] Building EXE...
%PY_CMD% -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --onefile ^
  --windowed ^
  --name "windows-content-uploader" ^
  --distpath "%cd%\\deployed" ^
  --workpath "%cd%\\deployed\\build" ^
  --specpath "%cd%\\deployed" ^
  "%cd%\\main.py"

if errorlevel 1 (
  echo [ERROR] Build failed.
  pause
  exit /b 1
)

echo.
echo Build finished successfully.
echo EXE path: "%cd%\\deployed\\windows-content-uploader.exe"
pause
