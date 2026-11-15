@echo off
setlocal
cd /d "%~dp0"
title NetMeter installer

set "PY=python"
where py >nul 2>nul && set "PY=py -3"
%PY% --version >nul 2>nul
if errorlevel 1 (
  echo Python 3 was not found.
  echo Install it from https://www.python.org/downloads/ and tick "Add python.exe to PATH", then run this again.
  pause
  exit /b 1
)

echo [1/5] Installing what NetMeter needs...
%PY% -m pip install --upgrade psutil pystray pillow pyinstaller || goto :fail

echo [2/5] Making the icon...
%PY% -c "from netmeter.tray import make_image; make_image().save('netmeter.ico', sizes=[(16,16),(24,24),(32,32),(48,48),(64,64)])" || goto :fail

echo [3/5] Building NetMeter.exe (takes a minute)...
%PY% -m PyInstaller --noconfirm --onefile --windowed --name NetMeter --icon netmeter.ico --hidden-import pystray._win32 run.py || goto :fail

echo [4/5] Installing to %LOCALAPPDATA%\Programs\NetMeter ...
taskkill /im NetMeter.exe /f >nul 2>nul
timeout /t 1 /nobreak >nul
set "DEST=%LOCALAPPDATA%\Programs\NetMeter"
if not exist "%DEST%" mkdir "%DEST%"
copy /y "dist\NetMeter.exe" "%DEST%\NetMeter.exe" >nul || goto :fail
xcopy /y /i /q "plugin-examples" "%DEST%\plugin-examples" >nul
copy /y "README.md" "%DEST%\README.md" >nul
powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Programs')+'\NetMeter.lnk'); $s.TargetPath='%DEST%\NetMeter.exe'; $s.Save()"

echo [5/5] Turning on "start with Windows"...
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v NetMeter /t REG_SZ /d "\"%DEST%\NetMeter.exe\" --startup" /f >nul

start "" "%DEST%\NetMeter.exe"
echo.
echo Done! NetMeter is now in your taskbar, next to the clock.
echo Right-click it for options. It's also in the Start menu as "NetMeter".
echo.
echo Tip: turn off TrafficMonitor's own startup so the two don't fight over the taskbar.
pause
exit /b 0

:fail
echo.
echo Something went wrong - see the messages above.
pause
exit /b 1
