@echo off
chcp 65001 >nul
set "SCRIPT_DIR=%~dp0"
set "TASK_NAME=TelegramObsidianBot"

echo ==> Останавливаю запущенного бота
call "%SCRIPT_DIR%stop.bat" <nul

echo ==> Удаляю задачу из Планировщика заданий
schtasks /delete /tn "%TASK_NAME%" /f

if exist "%SCRIPT_DIR%hidden_launch.vbs" del /q "%SCRIPT_DIR%hidden_launch.vbs"

echo.
echo Автозапуск удалён. Код проекта, venv и .env не тронуты.
pause
