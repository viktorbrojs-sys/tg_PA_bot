@echo off
chcp 65001 >nul
echo ==> Запускаю бота (Планировщик заданий)
schtasks /run /tn "TelegramObsidianBot"
if errorlevel 1 (
    echo Не удалось запустить через Планировщик. Задача не найдена?
    echo Сначала выполните install.bat.
) else (
    echo Готово. Бот запускается в фоне без окна консоли.
    echo Логи: %~dp0logs\run_bot.log
)
pause
