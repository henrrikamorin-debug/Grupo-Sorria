#!/usr/bin/env sh
# Encerra o serviço do painel (Linux/macOS).
cd "$(dirname "$0")/.."
"${PYTHON:-python3}" -m sorria parar
