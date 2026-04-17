#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODE="${1:-unit}"

if [[ -x "$SCRIPT_DIR/.venv/bin/python" ]]; then
  PYTHON_BIN="$SCRIPT_DIR/.venv/bin/python"
elif [[ -x "$SCRIPT_DIR/../.venv/bin/python" ]]; then
  PYTHON_BIN="$SCRIPT_DIR/../.venv/bin/python"
else
  PYTHON_BIN="/usr/bin/python3"
fi

run_unit() {
  "$PYTHON_BIN" -m unittest discover -s "$SCRIPT_DIR/tests" -p "test_unit_*.py" -v
  "$PYTHON_BIN" "$SCRIPT_DIR/tests/test_unit_delta_xml.py"
}

run_integration() {
  "$PYTHON_BIN" -m unittest discover -s "$SCRIPT_DIR/tests" -p "test_integration_*.py" -v
}

case "$MODE" in
  unit)
    echo "Running unit tests / Стартиране на unit тестове"
    run_unit
    ;;
  full)
    echo "Running full tests (unit + integration) / Пълни тестове (unit + integration)"
    run_unit
    run_integration
    ;;
  integration)
    echo "Running integration tests / Стартиране на integration тестове"
    run_integration
    ;;
  *)
    echo "Usage: $0 [unit|integration|full]" >&2
    exit 2
    ;;
esac
