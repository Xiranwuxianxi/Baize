#!/usr/bin/env sh
# macOS / Linux launcher. All the logic lives in run.py so every platform behaves the same.
set -e
cd "$(dirname "$0")"
if command -v python3 >/dev/null 2>&1; then
  exec python3 run.py "$@"
elif command -v python >/dev/null 2>&1; then
  exec python run.py "$@"
fi
echo "Python 3.9+ is required. Install it and try again." >&2
exit 1
