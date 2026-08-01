#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3.10 or newer is required."
  exit 1
fi

if [ ! -x ".venv/bin/python" ]; then
  echo "Creating virtual environment..."
  python3 -m venv .venv
fi

.venv/bin/python -m pip install --upgrade pip

# pywin32 and pywinauto are Windows-only; filter them out on other platforms
# so the desktop-control dependencies never break Unix installs.
REQ_FILE="requirements.txt"
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) ;;  # Windows shells keep the full dependency set
  *)
    REQ_FILE=".requirements-unix.txt"
    grep -v -i -E '^(pywin32|pywinauto)[><=]' requirements.txt > "$REQ_FILE"
    ;;
esac
.venv/bin/python -m pip install -r "$REQ_FILE"
[ "$REQ_FILE" = ".requirements-unix.txt" ] && rm -f "$REQ_FILE"

if [ ! -f "config.json" ]; then
  cp config.example.json config.json
  echo "Created config.json from config.example.json."
fi

exec .venv/bin/python main.py
