#!/usr/bin/env bash
# Compatibility wrapper around tools/lostevo.py.
#   ./tools/build_lostevo.sh            # prepare + banks + runner
#   ./tools/build_lostevo.sh all        # same
#   ./tools/build_lostevo.sh smoke      # short boot verification
#   ./tools/build_lostevo.sh status     # language/ROM/bank status
#   ./tools/build_lostevo.sh play       # interactive language menu
set -euo pipefail

TITLE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python3}"
step="${1:-build}"
case "$step" in
  all|build)
    shift || true
    exec "$PYTHON" "$TITLE_DIR/tools/lostevo.py" build "$@"
    ;;
  smoke|verify)
    shift || true
    exec "$PYTHON" "$TITLE_DIR/tools/lostevo.py" verify "$@"
    ;;
  prepare|banks|runner)
    echo "note: '$step' is folded into the cross-platform build command" >&2
    shift || true
    exec "$PYTHON" "$TITLE_DIR/tools/lostevo.py" build "$@"
    ;;
  *)
    exec "$PYTHON" "$TITLE_DIR/tools/lostevo.py" "$@"
    ;;
esac
