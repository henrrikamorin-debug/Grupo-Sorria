#!/usr/bin/env sh
# Inicia o serviço do painel em segundo plano (Linux/macOS).
set -e
cd "$(dirname "$0")/.."
PY="${PYTHON:-python3}"
mkdir -p logs dados
if [ -f dados/servico.pid ] && kill -0 "$(cat dados/servico.pid)" 2>/dev/null; then
  echo "O serviço já está em execução (PID $(cat dados/servico.pid))."
  exit 0
fi
nohup "$PY" -m sorria iniciar >> logs/console.log 2>&1 &
PORTA=$("$PY" -c "from sorria import config; print(config.carregar()['servidor']['porta'])")
for _ in 1 2 3 4 5 6 7 8 9 10; do
  if "$PY" -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:$PORTA/api/saude', timeout=1)" 2>/dev/null; then
    echo "Painel em execução:  http://127.0.0.1:$PORTA"
    echo "Modo televisão:      http://127.0.0.1:$PORTA/?tv=1"
    exit 0
  fi
  sleep 1
done
echo "O serviço não respondeu. Veja logs/console.log e logs/painel.log."
exit 1
