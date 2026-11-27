#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

if ! command -v cloudflared >/dev/null 2>&1; then
  echo "Falta cloudflared. Instálalo desde la guía oficial: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/"
  exit 1
fi

PROJECT_PYTHON="python3"
if [[ -x "$PROJECT_ROOT/.venv/bin/python" ]]; then
  PROJECT_PYTHON="$PROJECT_ROOT/.venv/bin/python"
fi
DEMO_PORT="${DEMO_PORT:-8001}"

ENABLE_TEMPORARY_DEMO_TUNNEL=1 "$PROJECT_PYTHON" manage.py runserver "127.0.0.1:$DEMO_PORT" --noreload &
DJANGO_PID=$!
cleanup() {
  kill "$DJANGO_PID" 2>/dev/null || true
  wait "$DJANGO_PID" 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 130' INT TERM

for attempt in {1..40}; do
  if ! kill -0 "$DJANGO_PID" 2>/dev/null; then
    wait "$DJANGO_PID"
    exit 1
  fi
  if (echo >"/dev/tcp/127.0.0.1/$DEMO_PORT") >/dev/null 2>&1; then
    break
  fi
  sleep 0.25
done

echo "Django está listo. Cloudflare imprimirá un enlace HTTPS temporal; ábrelo en Chrome del otro dispositivo."
echo "Deja esta terminal abierta durante la demostración. Ctrl+C detiene el enlace y Django."
cloudflared tunnel --url "http://127.0.0.1:$DEMO_PORT"
