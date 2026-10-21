@echo off
rem Executa uma coleta completa: Chrome do agente > TOTVS (Consulta Generica SE2,
rem Vencimento = Mes Atual, Exp. CSV) > captura > validacao > importacao > painel.
rem Para calibrar (grava tela e texto de cada etapa): agente.bat --diagnostico
cd /d "%~dp0.."
where py >nul 2>nul && (set PY=py -3) || (set PY=python)
%PY% -m sorria agente executar --origem manual %*
pause
