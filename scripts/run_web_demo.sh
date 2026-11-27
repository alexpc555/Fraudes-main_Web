#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

PROJECT_PYTHON="python3"
if [[ -x "$PROJECT_ROOT/.venv/bin/python" ]]; then
  PROJECT_PYTHON="$PROJECT_ROOT/.venv/bin/python"
fi

echo "Aplicación disponible en http://localhost:8000/"
echo "Abre esa dirección en Chrome en esta misma computadora para usar el micrófono."
echo "Deja esta terminal abierta mientras haces la demostración. Ctrl+C para detener."
exec "$PROJECT_PYTHON" manage.py runserver 127.0.0.1:8000
