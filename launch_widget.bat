@echo off
cd /d "%~dp0"
where pythonw >nul 2>nul
if %ERRORLEVEL% equ 0 (
    start "" pythonw widget.py
) else (
    if exist "%LOCALAPPDATA%\Microsoft\WindowsApps\pythonw.exe" (
        start "" "%LOCALAPPDATA%\Microsoft\WindowsApps\pythonw.exe" widget.py
    ) else (
        start "" python widget.py
    )
)
exit /b 0
