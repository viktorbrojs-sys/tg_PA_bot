@echo off
chcp 65001 >nul
REM Установка Telegram -> Obsidian Bot на Windows: venv, зависимости, .env
REM и автозапуск через Планировщик заданий (запуск при входе в систему,
REM плюс автоперезапуск при падении процесса через run_bot.bat).
REM
REM Использование: просто запустите этот файл двойным кликом
REM (или из cmd: deploy\windows\install.bat)

setlocal enabledelayedexpansion
set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "PROJECT_DIR=%%~fI"
set "TASK_NAME=TelegramObsidianBot"

echo ==> Проект: %PROJECT_DIR%
cd /d "%PROJECT_DIR%"

REM ---------------------------------------------------------------------
REM 1. Проверка Python
REM ---------------------------------------------------------------------
where python >nul 2>nul
if errorlevel 1 (
    echo Ошибка: python не найден в PATH.
    echo Установите Python 3.12+ с https://www.python.org/downloads/
    echo При установке обязательно отметьте галочку "Add python.exe to PATH".
    pause
    exit /b 1
)
echo ==> Найден Python:
python --version

REM ---------------------------------------------------------------------
REM 2. Виртуальное окружение и зависимости
REM ---------------------------------------------------------------------
if not exist "%PROJECT_DIR%\.venv\Scripts\python.exe" (
    echo ==> Создаю виртуальное окружение .venv
    python -m venv "%PROJECT_DIR%\.venv"
)

echo ==> Устанавливаю зависимости из requirements.txt
"%PROJECT_DIR%\.venv\Scripts\python.exe" -m pip install --upgrade pip >nul
"%PROJECT_DIR%\.venv\Scripts\python.exe" -m pip install -r "%PROJECT_DIR%\requirements.txt"

REM ---------------------------------------------------------------------
REM 3. Файл .env
REM ---------------------------------------------------------------------
if not exist "%PROJECT_DIR%\.env" (
    echo ==> Создаю .env из .env.example
    copy "%PROJECT_DIR%\.env.example" "%PROJECT_DIR%\.env" >nul
    echo.
    echo Сейчас откроется Блокнот - вставьте токен бота от @BotFather
    echo в переменную TG_BOT_TOKEN, сохраните файл (Ctrl+S) и закройте Блокнот.
    pause
    start /wait notepad "%PROJECT_DIR%\.env"
) else (
    echo ==> Файл .env уже существует - оставляю как есть
)

REM ---------------------------------------------------------------------
REM 4. Скрытый запуск (без окна консоли) через VBScript-обёртку
REM ---------------------------------------------------------------------
set "VBS_FILE=%SCRIPT_DIR%hidden_launch.vbs"
set "RUN_BAT=%SCRIPT_DIR%run_bot.bat"

> "%VBS_FILE%" echo Set WshShell = CreateObject("WScript.Shell")
>> "%VBS_FILE%" echo WshShell.Run """%RUN_BAT%""", 0, False

REM ---------------------------------------------------------------------
REM 5. Регистрация автозапуска в Планировщике заданий
REM ---------------------------------------------------------------------
echo ==> Регистрирую автозапуск в Планировщике заданий (триггер: вход в систему)
schtasks /delete /tn "%TASK_NAME%" /f >nul 2>nul
schtasks /create /tn "%TASK_NAME%" ^
    /tr "wscript.exe \"%VBS_FILE%\"" ^
    /sc onlogon ^
    /rl highest ^
    /f
if errorlevel 1 (
    echo.
    echo Не удалось создать задачу автоматически. Попробуйте запустить
    echo этот файл от имени администратора ^(правой кнопкой -^> "Запуск от
    echo имени администратора"^).
    pause
    exit /b 1
)

echo ==> Запускаю бота прямо сейчас
schtasks /run /tn "%TASK_NAME%"

echo.
echo ======================================================================
echo Готово! Бот установлен и запущен в фоне (без окна консоли).
echo Он будет автоматически запускаться при каждом входе в Windows и
echo перезапускаться сам при падении (см. run_bot.bat).
echo.
echo Логи: %PROJECT_DIR%\deploy\windows\logs\run_bot.log
echo.
echo Управление:
echo   deploy\windows\stop.bat       - остановить бота
echo   deploy\windows\start.bat      - запустить вручную
echo   deploy\windows\uninstall.bat  - убрать автозапуск
echo ======================================================================
pause
