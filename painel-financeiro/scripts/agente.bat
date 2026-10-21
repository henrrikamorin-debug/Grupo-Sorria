@echo off
rem Executa o agente TOTVS (aguarda a exportacao SE2 na pasta de entrada).
cd /d "%~dp0.."
where py >nul 2>nul && (set PY=py -3) || (set PY=python)
%PY% -m sorria agente executar --origem manual
pause
