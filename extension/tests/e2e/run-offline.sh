#!/bin/sh
set -eu

cd "$(dirname "$0")"

unshare --net -- sh -c '
  ip link set lo up
  cd "'"$PWD"'"
  uv run pytest -q "$@"
' -- "$@"
