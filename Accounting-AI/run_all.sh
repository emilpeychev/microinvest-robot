#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="${1:-$SCRIPT_DIR}"
CLIENT="${2:-Client_A}"
LOCAL_VENV="$SCRIPT_DIR/.venv/bin/python"
PARENT_VENV="$SCRIPT_DIR/../.venv/bin/python"

if [[ -x "$LOCAL_VENV" ]]; then
  PYTHON_BIN="$LOCAL_VENV"
elif [[ -x "$PARENT_VENV" ]]; then
  PYTHON_BIN="$PARENT_VENV"
elif command -v python3 &>/dev/null; then
  PYTHON_BIN="python3"
elif command -v python &>/dev/null; then
  PYTHON_BIN="python"
else
  echo "Error / Грешка: Python not found / Python не е намерен" >&2
  echo "Install Python 3.10+ / Инсталирайте Python 3.10+" >&2
  exit 1
fi

"$PYTHON_BIN" "$SCRIPT_DIR/intake_v1.py" --base-dir "$BASE_DIR" --client "$CLIENT"
"$PYTHON_BIN" "$SCRIPT_DIR/extract_invoices_v1.py" --base-dir "$BASE_DIR" --client "$CLIENT"
"$PYTHON_BIN" "$SCRIPT_DIR/generate_delta_xml.py" --base-dir "$BASE_DIR" --client "$CLIENT"

echo "Done / Готово: intake + extraction + Delta Pro XML completed / вход, извличане и Delta Pro XML приключиха за $CLIENT"
