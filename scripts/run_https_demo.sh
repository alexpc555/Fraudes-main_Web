#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

if ! command -v mkcert >/dev/null 2>&1; then
  echo "Falta mkcert. Instálalo una vez desde https://github.com/FiloSottile/mkcert#installation y vuelve a ejecutar este script."
  exit 1
fi

mkcert -install
CERT_DIR="$(mktemp -d "${TMPDIR:-/tmp}/antifraude-https.XXXXXX")"
trap 'rm -rf "$CERT_DIR"' EXIT
mkcert -cert-file "$CERT_DIR/localhost.pem" -key-file "$CERT_DIR/localhost-key.pem" localhost 127.0.0.1 ::1

PROJECT_PYTHON="python3"
if [[ -x "$PROJECT_ROOT/.venv/bin/python" ]]; then
  PROJECT_PYTHON="$PROJECT_ROOT/.venv/bin/python"
fi

HTTPS_PORT="${HTTPS_PORT:-8443}"
"$PROJECT_PYTHON" scripts/https_dev_server.py \
  --cert "$CERT_DIR/localhost.pem" \
  --key "$CERT_DIR/localhost-key.pem" \
  --port "$HTTPS_PORT"
