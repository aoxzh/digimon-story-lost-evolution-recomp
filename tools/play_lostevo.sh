#!/usr/bin/env bash
# Interactive launcher with the language menu. Equivalent to:
#   python tools/lostevo.py play [--language <id>] [runner options]
set -euo pipefail

TITLE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python3}"
exec "$PYTHON" "$TITLE_DIR/tools/lostevo.py" play "$@"
