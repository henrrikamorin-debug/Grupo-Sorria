@echo off
rem Instala a biblioteca que controla o Chrome (usa o Google Chrome ja instalado).
cd /d "%~dp0.."
where py >nul 2>nul && (set PY=py -3) || (set PY=python)
%PY% -m pip install -r requirements-navegador.txt
pause
