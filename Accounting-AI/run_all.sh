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
else
  echo "Error / Грешка: Python virtual environment not found. Checked / Проверени:" >&2
  echo "  - $LOCAL_VENV" >&2
  echo "  - $PARENT_VENV" >&2
  exit 1
fi

"$PYTHON_BIN" "$SCRIPT_DIR/intake_v1.py" --base-dir "$BASE_DIR" --client "$CLIENT"
"$PYTHON_BIN" "$SCRIPT_DIR/extract_invoices_v1.py" --base-dir "$BASE_DIR" --client "$CLIENT"

echo "Done / Готово: intake + extraction completed / вход и извличане приключиха за $CLIENT"
