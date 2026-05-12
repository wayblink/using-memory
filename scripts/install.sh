#!/usr/bin/env bash
# scripts/install.sh - copy the skill tree for a clean install in supported hosts.
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
HOST="${1:-both}"

run_first_time_setup() {
 local config_path="${USING_MEMORY_CONFIG:-$HOME/.skills/using-memory/config.yaml}"
 if [ "${USING_MEMORY_SKIP_SETUP:-0}" = "1" ]; then
  echo "Skipping memory storage setup because USING_MEMORY_SKIP_SETUP=1"
  return
 fi
 if [ -f "$config_path" ]; then
  echo "Memory storage config already exists: $config_path"
  return
 fi
 if [ -t 0 ]; then
  echo "No memory storage config found. Starting first-time setup."
  python3 "$HERE/scripts/memory_tool.py" setup
 else
  echo "No memory storage config found: $config_path"
  echo "Run this later to configure memory storage path, remote Git repo, namespace, and machine ID:"
  echo "  python3 $HERE/scripts/memory_tool.py setup"
 fi
}

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

run_first_time_setup
