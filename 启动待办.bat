@echo off
rem TodoApp launcher (ASCII only, CRLF required)
setlocal enableextensions
set "PYW="
for /f "delims=" %%i in ('where pythonw 2^>nul') do (
    if not defined PYW set "PYW=%%i"
)
if not defined PYW (
    if exist "%LocalAppData%\Programs\Python\Python313\pythonw.exe" set "PYW=%LocalAppData%\Programs\Python\Python313\pythonw.exe"
)
if not defined PYW (
    for /f "delims=" %%i in ('where pyw 2^>nul') do (
        if not defined PYW set "PYW=%%i"
    )
)
if not defined PYW (
    echo [TodoApp] pythonw.exe not found. Please install Python 3.8+ first.
    pause
    exit /b 1
)
start "" "%PYW%" "%~dp0app.py" %*
endlocal
