@echo off
rem Abre o Chrome do agente (perfil dedicado) no TOTVS WebApp para o login.
rem Entre no TOTVS nessa janela e deixe-a aberta: a coleta usa essa sessao.
cd /d "%~dp0.."
where py >nul 2>nul && (set PY=py -3) || (set PY=python)
%PY% -m sorria agente abrir-navegador
pause
