@echo off
rem Inicia o servico do painel em uma janela minimizada (Windows).
cd /d "%~dp0.."
if not exist logs mkdir logs
if not exist dados mkdir dados
where py >nul 2>nul && (set PY=py -3) || (set PY=python)
start "Painel Financeiro - Grupo Sorria" /MIN cmd /c "%PY% -m sorria iniciar >> logs\console.log 2>&1"
timeout /t 3 /nobreak >nul
echo Painel: http://127.0.0.1:8750   (modo TV: http://127.0.0.1:8750/?tv=1)
echo Se a porta foi alterada no config.json, use a porta configurada.
start "" "http://127.0.0.1:8750/?tv=1"
