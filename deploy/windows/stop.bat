@echo off
chcp 65001 >nul
echo ==> Останавливаю бота...

REM Точечно завершаем только процессы, относящиеся к этому боту -
REM ищем по командной строке, чтобы не задеть другие python/cmd на компьютере.
powershell -NoProfile -Command ^
    "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'bot\\main\.py' -or $_.CommandLine -match 'run_bot\.bat' } | ForEach-Object { Write-Host ('Завершаю PID ' + $_.ProcessId + ': ' + $_.Name); Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"

echo Готово. Автозапуск при следующем входе в систему останется включённым
echo (используйте uninstall.bat, чтобы отключить автозапуск совсем).
pause
