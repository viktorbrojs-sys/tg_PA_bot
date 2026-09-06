@echo off
REM Запускает бота в бесконечном цикле: если процесс упадёт (или его закроют),
REM он автоматически перезапустится через 10 секунд.
REM Этот файл вызывается либо вручную, либо задачей в Планировщике заданий
REM (регистрируется install.bat).

setlocal
cd /d "%~dp0..\.."
set "PYTHON=%CD%\.venv\Scripts\python.exe"
set "LOGDIR=%CD%\deploy\windows\logs"
if not exist "%LOGDIR%" mkdir "%LOGDIR%"

:loop
echo [%date% %time%] Запуск бота... >> "%LOGDIR%\run_bot.log"
"%PYTHON%" "%CD%\bot\main.py" >> "%LOGDIR%\run_bot.log" 2>&1
echo [%date% %time%] Бот остановился (код %errorlevel%). Перезапуск через 10 секунд... >> "%LOGDIR%\run_bot.log"
timeout /t 10 /nobreak >nul
goto loop
