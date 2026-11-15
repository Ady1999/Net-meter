@echo off
title NetMeter uninstaller
taskkill /im NetMeter.exe /f >nul 2>nul
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v NetMeter /f >nul 2>nul
del /q "%APPDATA%\Microsoft\Windows\Start Menu\Programs\NetMeter.lnk" >nul 2>nul
rmdir /s /q "%LOCALAPPDATA%\Programs\NetMeter" >nul 2>nul
echo NetMeter removed.
choice /m "Also delete your settings, skins, plugins and traffic history (%APPDATA%\NetMeter)"
if errorlevel 2 goto :end
rmdir /s /q "%APPDATA%\NetMeter"
:end
pause
