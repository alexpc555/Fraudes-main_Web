#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

if ! command -v adb >/dev/null 2>&1; then
  echo "No se encontró adb. Instala Android SDK Platform-Tools y activa Depuración USB en el teléfono."
  exit 1
fi

adb start-server >/dev/null
mapfile -t DEVICE_SERIALS < <(adb devices | awk 'NR > 1 && $2 == "device" { print $1 }')
if [[ ${#DEVICE_SERIALS[@]} -eq 0 ]]; then
  echo "No hay Android autorizados conectados por USB. Conéctalos, activa Depuración USB y acepta el aviso en cada teléfono."
  exit 1
fi

for DEVICE_SERIAL in "${DEVICE_SERIALS[@]}"; do
  adb -s "$DEVICE_SERIAL" reverse tcp:8000 tcp:8000
  echo "USB listo: $DEVICE_SERIAL → http://localhost:8000/"
done
echo "En cada Android abre Chrome y visita http://localhost:8000/"
echo "Deja esta terminal abierta. Si Django ya está ejecutándose en el puerto 8000, detén ese proceso antes."

PROJECT_PYTHON="python3"
if [[ -x "$PROJECT_ROOT/.venv/bin/python" ]]; then
  PROJECT_PYTHON="$PROJECT_ROOT/.venv/bin/python"
fi
exec "$PROJECT_PYTHON" manage.py runserver 127.0.0.1:8000
