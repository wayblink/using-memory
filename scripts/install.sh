#!/usr/bin/env bash
# scripts/install.sh - copy the skill tree for a clean install in supported hosts.
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
HOST="${1:-both}"

install_host() {
 local name="$1"
 local dest="$2"
 echo "Installing $name: $HERE -> $dest"
 if [ -L "$dest" ]; then
  rm "$dest"
 elif [ -e "$dest" ]; then
  if [ "${USING_MEMORY_INSTALL_FORCE:-0}" != "1" ]; then
   echo "refusing to overwrite existing destination: $dest" >&2
   echo "Set USING_MEMORY_INSTALL_FORCE=1 to replace it." >&2
   exit 2
  fi
  rm -rf "$dest"
 fi
 mkdir -p "$dest"
 tar -C "$HERE" \
  --exclude=.git \
  --exclude=tests \
  --exclude=__pycache__ \
  --exclude='*.pyc' \
  --exclude='*.swp' \
  -cf - . | tar -C "$dest" -xf -
 echo "Installed $name. Destination: $dest"
}

case "$HOST" in
 codex)
 install_host "codex" "${CODEX_HOME:-$HOME/.codex}/skills/using-memory"
 ;;
 claude-code)
 install_host "claude-code" "${CLAUDE_HOME:-$HOME/.claude}/skills/using-memory"
 ;;
 both)
 install_host "codex" "${CODEX_HOME:-$HOME/.codex}/skills/using-memory"
 install_host "claude-code" "${CLAUDE_HOME:-$HOME/.claude}/skills/using-memory"
 ;;
 *)
 echo "Usage: $0 [codex|claude-code|both]" >&2
 exit 2
 ;;
esac
